// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// See panel_rtc.h.
//
// The chip blocks its counters while a read or a write of the time goes
// on, and counts the second it missed after that. So the datasheet asks
// for the seconds to the years in one access, and here each read is one
// transfer and each write of the time is one transfer. Two reads could
// give the minutes of one moment and the hours of the next.
#include "panel_rtc.h"

#include "bsp/esp-bsp.h"
#include "driver/i2c_master.h"
#include "esp_log.h"

#define PCF85063_ADDRESS     0x51
#define PCF85063_CONTROL_1   0x00
#define PCF85063_SECONDS     0x04
/* Control_1 to the years, 00h to 0Ah, in one read. */
#define REGISTERS_READ       11

/* Control_1: an external clock in place of the crystal, a clock that
 * stands still, and hours of twelve. Each one means a time this does not
 * read, and a write of the time clears them. */
#define CONTROL_EXT_TEST     0x80
#define CONTROL_STOP         0x20
#define CONTROL_12_24        0x02
#define CONTROL_NOT_COUNTING (CONTROL_EXT_TEST | CONTROL_STOP | CONTROL_12_24)
/* The bits of Control_1 that a write keeps as they are: the interrupt of
 * the correction and the load of the crystal. Bit 4 starts a reset, and a
 * write here never sets it. */
#define CONTROL_KEPT         0x05
#define SECONDS_OS           0x80

/* Short, like the other reads on this bus: the touch, the codec, the key,
 * the power chip and the motion sensor share it. */
#define RTC_TIMEOUT_MS       20

static const char *tag = "panel_rtc";
static i2c_master_dev_handle_t chip;

/* A byte of two decimal digits, or -1 when a digit is no digit. */
static int from_bcd(uint8_t value)
{
    if ((value & 0x0F) > 9 || (value >> 4) > 9) return -1;
    return (value >> 4) * 10 + (value & 0x0F);
}

static uint8_t to_bcd(int value)
{
    return (uint8_t)(((value / 10) << 4) | (value % 10));
}

/* The chip adds a 29th day to February in each year that 4 divides, and
 * from 2000 to 2099 that is the calendar. */
static int days_in_month(int year, int month)
{
    static const int days[12] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    return month == 2 && year % 4 == 0 ? 29 : days[month - 1];
}

/* The days from 1970-01-01 to a date. The year starts in March here, so
 * that the leap day is the last day of a year. */
static int64_t days_since_1970(int year, int month, int day)
{
    int y = year - (month <= 2 ? 1 : 0);
    int era = y / 400;
    int of_era = y - era * 400;
    int of_year = (153 * (month > 2 ? month - 3 : month + 9) + 2) / 5 + day - 1;
    int days = of_era * 365 + of_era / 4 - of_era / 100 + of_year;
    return (int64_t)era * 146097 + days - 719468;
}

bool panel_rtc_decode(uint8_t control, const uint8_t time[7], time_t *utc)
{
    if (control & CONTROL_NOT_COUNTING) return false;
    if (time[0] & SECONDS_OS) return false;
    /* The bits the datasheet marks unused are left out, as SensorLib does.
     * The weekday is not needed: the date says it. */
    int second = from_bcd(time[0] & 0x7F);
    int minute = from_bcd(time[1] & 0x7F);
    int hour = from_bcd(time[2] & 0x3F);
    int day = from_bcd(time[3] & 0x3F);
    int month = from_bcd(time[5] & 0x1F);
    int year = from_bcd(time[6]);
    if (second < 0 || second > 59 || minute < 0 || minute > 59 || hour < 0 || hour > 23 ||
        month < 1 || month > 12 || year < 0)
        return false;
    year += PANEL_RTC_FIRST_YEAR;
    if (day < 1 || day > days_in_month(year, month)) return false;
    *utc = (time_t)(days_since_1970(year, month, day) * 86400 + hour * 3600 +
                    minute * 60 + second);
    return true;
}

bool panel_rtc_encode(time_t utc, uint8_t time[7])
{
    struct tm date;
    if (!gmtime_r(&utc, &date)) return false;
    int year = date.tm_year + 1900;
    if (year < PANEL_RTC_FIRST_YEAR || year > PANEL_RTC_LAST_YEAR) return false;
    /* The seconds with OS at nought: the write of the time clears it. */
    time[0] = to_bcd(date.tm_sec);
    time[1] = to_bcd(date.tm_min);
    time[2] = to_bcd(date.tm_hour);
    time[3] = to_bcd(date.tm_mday);
    /* 0 for Sunday, as in the datasheet and in struct tm. */
    time[4] = (uint8_t)date.tm_wday;
    time[5] = to_bcd(date.tm_mon + 1);
    time[6] = to_bcd(year - PANEL_RTC_FIRST_YEAR);
    return true;
}

esp_err_t panel_rtc_init(void)
{
    i2c_master_bus_handle_t bus = bsp_i2c_get_handle();
    if (!bus) return ESP_ERR_INVALID_STATE;
    /* A probe first: a read of an address nobody holds makes the driver
     * write an error of its own. */
    if (i2c_master_probe(bus, PCF85063_ADDRESS, RTC_TIMEOUT_MS) != ESP_OK) {
        ESP_LOGW(tag, "no clock chip answers, so the time comes from the network alone");
        return ESP_ERR_NOT_FOUND;
    }
    const i2c_device_config_t config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = PCF85063_ADDRESS,
        .scl_speed_hz = 100000,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &config, &chip);
    if (err != ESP_OK) chip = NULL;
    return err;
}

bool panel_rtc_read(time_t *utc)
{
    if (!chip) return false;
    const uint8_t first = PCF85063_CONTROL_1;
    uint8_t registers[REGISTERS_READ];
    if (i2c_master_transmit_receive(chip, &first, 1, registers, sizeof registers,
                                    RTC_TIMEOUT_MS) != ESP_OK)
        return false;
    return panel_rtc_decode(registers[PCF85063_CONTROL_1], registers + PCF85063_SECONDS, utc);
}

esp_err_t panel_rtc_write(time_t utc)
{
    if (!chip) return ESP_ERR_INVALID_STATE;
    uint8_t data[8] = {PCF85063_SECONDS};
    if (!panel_rtc_encode(utc, data + 1)) return ESP_ERR_INVALID_ARG;
    /* The hours of twelve go before the time does, or the chip reads the
     * hour of the write in them. */
    const uint8_t first = PCF85063_CONTROL_1;
    uint8_t control = 0;
    esp_err_t err = i2c_master_transmit_receive(chip, &first, 1, &control, 1, RTC_TIMEOUT_MS);
    if (err == ESP_OK && (control & CONTROL_NOT_COUNTING)) {
        const uint8_t counting[2] = {PCF85063_CONTROL_1, (uint8_t)(control & CONTROL_KEPT)};
        err = i2c_master_transmit(chip, counting, sizeof counting, RTC_TIMEOUT_MS);
    }
    if (err == ESP_OK) err = i2c_master_transmit(chip, data, sizeof data, RTC_TIMEOUT_MS);
    return err;
}
