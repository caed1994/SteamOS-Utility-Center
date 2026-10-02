// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The battery of the panel, read off its power chip.
//
// The 4B carries an AXP2101, which charges a cell and keeps a gauge of it.
// Nothing in the board support speaks to it, so this does. A power chip
// decides which rails of the board have power, and one wrong write to it
// can switch off the rail this code runs on. So it reads, and writes four
// fields and nothing else: three of the charger and one of the ADC. See
// charger_set. The rules in tests/test_panel_battery.py hold that.
//
// The addresses and the bits are those of XPowersLib, the driver that the
// makers of these boards use themselves:
//   https://github.com/lewisxhe/XPowersLib, src/REG/AXP2101Constants.h
//   and the reads in src/XPowersAXP2101.hpp.
// That driver switches nothing on to read the gauge either: its start
// checks the type of the chip and its percentage is one read of 0xA4.
#include "panel_battery.h"
#include "driver/i2c_master.h"
#include "bsp/esp-bsp.h"
#include "esp_log.h"
#include "esp_timer.h"
#include <stdio.h>
#include <string.h>

#define AXP2101_ADDRESS  0x34
/* Bit 3: a cell is connected. */
#define AXP2101_STATUS1  0x00
/* Bits 7 to 5: 1 while it charges, 0 at rest, 2 while it runs off the
 * cell. */
#define AXP2101_STATUS2  0x01
#define AXP2101_IC_TYPE  0x03
#define AXP2101_CHIP_ID  0x4A
/* The gauge, in per cent. */
#define AXP2101_PERCENT  0xA4

/* The charger, read for the line in the log below and for the page of
 * the panel. charger_set writes a field of four of them, and only those.
 * The numbers and the bits are those of the AXP2101 datasheet V1.4,
 * chapter 6.13.2, which XPowersLib carries in its datasheet/ directory. */
#define AXP2101_VINDPM          0x15  /* 3:0, 3.88 V and 80 mV a step */
#define AXP2101_INPUT_LIMIT     0x16  /* 2:0, see input_limit_ma */
#define AXP2101_CHARGER_ON      0x18  /* bit 1, the cell charger */
#define AXP2101_ADC_ON          0x30  /* 4:0, the channels of the ADC */
#define AXP2101_VBAT_HIGH       0x34  /* with 0x35, the cell in mV */
#define AXP2101_VBAT_LOW        0x35
#define AXP2101_TS_HIGH         0x36  /* with 0x37, the TS pin in 0.5 mV */
#define AXP2101_TS_LOW          0x37
#define AXP2101_VBUS_HIGH       0x38  /* with 0x39, the input in mV */
#define AXP2101_VBUS_LOW        0x39
#define AXP2101_VSYS_HIGH       0x3A  /* with 0x3B, the system rail in mV */
#define AXP2101_VSYS_LOW        0x3B
#define AXP2101_TDIE_HIGH       0x3C  /* with 0x3D, the die: see die_celsius */
#define AXP2101_TDIE_LOW        0x3D
#define AXP2101_TS_CONTROL      0x50  /* bit 4: 0 when TS can stop the charger */
#define AXP2101_JEITA           0x58  /* bit 0 */
#define AXP2101_PRECHARGE       0x61  /* 3:0, 25 mA a step */
#define AXP2101_CHARGE_CURRENT  0x62  /* 4:0, see charge_current_ma */
#define AXP2101_TERMINATION     0x63  /* 3:0, 25 mA a step; bit 4 on */
#define AXP2101_CHARGE_VOLTAGE  0x64  /* 2:0, see charge_voltage_mv */
#define AXP2101_CHGLED          0x69  /* bit 0 pin on, 2:1 how, see led_name */
/* A reading of the TS pin with nothing connected to it. */
#define AXP2101_TS_OPEN         0x2000
/* At most one line about the charger in this time, however often its
 * state changes. A change in the hold is written at the end of it. */
#define CHARGER_HOLD_MS         30000

/* The cell of this panel, as its owner read it off the cell. */
#define PANEL_CELL_MAH          5000
/* The three fields charger_set writes. 1000 mA is the most the chip
 * gives, and a fifth of the cell an hour (0.2 C), well under what a cell
 * of this size takes. Bit 4 of the TS control sets the TS pin apart from
 * the charger. 0x01 in bits 2:0 of the CHGLED control is the pin on, with
 * the LED of type A. */
#define CHARGE_CURRENT_MA       1000
#define CHARGE_CURRENT_CODE     0x10
#define CHARGE_CURRENT_MASK     0x1F
#define TS_APART                0x10
#define TS_APART_MASK           0x10
#define CHGLED_TYPE_A           0x01
#define CHGLED_MASK             0x07
/* Bits 4:2 of REG 30: the ADC channels of the temperature of the die, of
 * the system voltage and of the input voltage. All three are 0 after a
 * reset (datasheet V1.4, 6.13.2.29). Bits 1:0, the TS pin and the cell,
 * are on from the reset and stay as they are. */
#define ADC_MEASURE             0x1C
#define ADC_MEASURE_MASK        0x1C
_Static_assert(CHARGE_CURRENT_MA <= PANEL_CELL_MAH / 2,
               "more than half the cell an hour is too fast for it");
_Static_assert(CHARGE_CURRENT_CODE == 8 + (CHARGE_CURRENT_MA - 200) / 100,
               "REG 62 counts 100 mA a step above 200 mA");

/* Short, because the bus is shared with the touch, the codec and the key.
 * A chip that does not answer in this time is a reading skipped, and the
 * next one comes a few seconds later. */
#define READ_TIMEOUT_MS  50

static const char *tag = "panel_battery";
static i2c_master_dev_handle_t chip;

static esp_err_t read_register(uint8_t reg, uint8_t *value)
{
    return i2c_master_transmit_receive(chip, &reg, 1, value, 1,
                                       READ_TIMEOUT_MS);
}

static esp_err_t write_register(uint8_t reg, uint8_t value)
{
    const uint8_t data[2] = {reg, value};
    return i2c_master_transmit(chip, data, 2, READ_TIMEOUT_MS);
}

/* One field of one register to the value given, and the rest of the
 * register as it was. Read first, so a field that already holds the value
 * is not written at all, and read back after, so a write that did not
 * take says so. */
static void set_field(uint8_t reg, uint8_t mask, uint8_t bits, const char *what)
{
    uint8_t before = 0, after = 0;
    if (read_register(reg, &before) != ESP_OK) {
        ESP_LOGW(tag, "%s: 0x%02x did not answer, nothing written", what, reg);
        return;
    }
    if ((before & mask) == bits) return;
    esp_err_t err = write_register(reg, (uint8_t)((before & ~mask) | bits));
    if (err == ESP_OK) err = read_register(reg, &after);
    if (err != ESP_OK || (after & mask) != bits) {
        ESP_LOGW(tag, "%s: 0x%02x did not take it (0x%02x, %s)", what, reg,
                 after, esp_err_to_name(err));
        return;
    }
    ESP_LOGI(tag, "%s: 0x%02x from 0x%02x to 0x%02x", what, reg, before, after);
}

/* The three settings of the charger that this panel needs, the channels
 * of the ADC that its page reads, and the only writes to the chip
 * anywhere in this firmware.
 *
 * Read off the board, before this existed: the panel charged slowly, with
 * a charger and a cable that charge a Switch 2 fast, and off as slowly as
 * on. The chip charges at what it is set to, and the charger on the wall
 * does not change that.
 *
 * The TS pin. The chip can read a sensor in the cell through it, and stop
 * or slow the charge when the sensor says too cold or too hot. The cell of
 * this panel has no sensor; its plug has two pins. The example of the
 * maker of the board sets the pin apart from the charger, with the note
 * that a board without the sensor otherwise charges abnormally
 * (examples/esp-idf/01_AXP2101/main/port_axp2101.cpp in
 * waveshareteam/ESP32-S3-Touch-LCD-4B).
 *
 * The charge current. The datasheet gives 300 mA after a reset, from a
 * fuse in the chip. That fills a cell of 5000 mAh in most of a day. See
 * CHARGE_CURRENT_MA for the value now.
 *
 * The CHG LED beside the USB-OTG port, which its owner found dark. The
 * chip drives it through its CHGLED pin, in the way bits 2:1 of 0x69
 * say, and the value of those after a reset comes from a fuse. One of the
 * ways keeps the LED for software to switch, and dark until then. Type A,
 * which this sets, lights it while the cell charges, keeps it dark when
 * the cell is full or nothing charges, and blinks it when the charger has
 * a fault: 1 Hz for a safety timer that ran out or heat, 4 Hz for too
 * high a voltage (datasheet V1.4, table 6-4). Its owner allowed this
 * third write after the first two.
 *
 * The ADC. It measures the cell and the TS pin from the reset, and the
 * input, the system rail and the die only when bits 4:2 of 0x30 say so.
 * The page of the panel shows those three. Measuring switches no rail
 * and changes nothing of the charge. Its owner allowed this fourth write
 * for the page.
 *
 * All four keep their values while the chip has power, and the chip has
 * power from the cell when the panel is off. So the panel charges at this
 * speed, and shows it, off as well, until the cell is unplugged.
 * Everything else stays at what the chip came with: the rails, the target
 * voltage, the safety timers. */
static void charger_set(void)
{
    set_field(AXP2101_TS_CONTROL, TS_APART_MASK, TS_APART,
              "TS pin apart from the charger");
    set_field(AXP2101_CHARGE_CURRENT, CHARGE_CURRENT_MASK, CHARGE_CURRENT_CODE,
              "charge current 1000 mA");
    set_field(AXP2101_CHGLED, CHGLED_MASK, CHGLED_TYPE_A,
              "charge LED on while charging");
    set_field(AXP2101_ADC_ON, ADC_MEASURE_MASK, ADC_MEASURE,
              "measure the input, the system rail and the die");
}

/* One register for the log line, or -1 when the chip did not answer. */
static int read_or_none(uint8_t reg)
{
    uint8_t value = 0;
    return read_register(reg, &value) == ESP_OK ? value : -1;
}

/* Two registers that hold one number, the high one first. */
static int read_pair(uint8_t high, uint8_t low, uint8_t mask)
{
    int h = read_or_none(high), l = read_or_none(low);
    return h < 0 || l < 0 ? -1 : ((h & mask) << 8) | l;
}

static int charge_current_ma(int code)
{
    if (code < 0) return -1;
    code &= 0x1F;
    if (code <= 8) return 25 * code;
    if (code <= 16) return 200 + 100 * (code - 8);
    return -1;
}

static int input_limit_ma(int code)
{
    static const int table[] = {100, 500, 900, 1000, 1500, 2000};
    if (code < 0 || (code & 0x07) > 5) return -1;
    return table[code & 0x07];
}

static int charge_voltage_mv(int code)
{
    static const int table[] = {5000, 4000, 4100, 4200, 4350, 4400};
    if (code < 0 || (code & 0x07) > 5) return -1;
    return table[code & 0x07];
}

static const char *charge_state_name(uint8_t status2)
{
    switch (status2 & 0x07) {
    case 0: return "trickle";
    case 1: return "pre-charge";
    case 2: return "constant current";
    case 3: return "constant voltage";
    case 4: return "done";
    case 5: return "not charging";
    default: return "reserved";
    }
}

/* What the CHG LED does, from bits 2:0 of 0x69. */
static const char *led_name(int code)
{
    if (code < 0) return "?";
    if (!(code & 0x01)) return "off";
    switch ((code >> 1) & 0x03) {
    case 0: return "shows the charge (type A)";
    case 1: return "type B";
    case 2: return "for software to switch";
    default: return "reserved";
    }
}

/* What the charger does and what it is set to, in one line.
 *
 * Asked about on the board: the panel charges slowly, with a charger and
 * a cable that charge a Switch 2 fast, and switched off as slowly as
 * switched on. The speed of a charge is not the charger on the wall here.
 * It is what this chip is set to, and two of its settings are suspects:
 *
 * The charge current, the TS pin and the LED, which charger_set writes.
 * This line shows what they hold, and whether the chip holds the current
 * under its setting for a reason of its own: heat, or an input that gives
 * less.
 *
 * Reads only. */
static void charger_report(uint8_t status1, uint8_t status2)
{
    int ts_control = read_or_none(AXP2101_TS_CONTROL);
    int adc = read_or_none(AXP2101_ADC_ON);
    int ts = read_pair(AXP2101_TS_HIGH, AXP2101_TS_LOW, 0x3F);
    int on = read_or_none(AXP2101_CHARGER_ON);
    int jeita = read_or_none(AXP2101_JEITA);
    int pre = read_or_none(AXP2101_PRECHARGE);
    int term = read_or_none(AXP2101_TERMINATION);
    int vindpm = read_or_none(AXP2101_VINDPM);

    char ts_text[24];
    if (ts < 0 || adc < 0 || !(adc & 0x02))
        snprintf(ts_text, sizeof ts_text, "not measured");
    else if (ts == AXP2101_TS_OPEN)
        snprintf(ts_text, sizeof ts_text, "open");
    else
        snprintf(ts_text, sizeof ts_text, "%d mV", ts / 2);

    /* What holds the current below its setting, if anything does. */
    char held[48] = "";
    if (status1 & (1u << 1)) strcat(held, "heat, ");
    if (status1 & (1u << 0)) strcat(held, "input current, ");
    if (status2 & (1u << 3)) strcat(held, "input voltage, ");
    size_t length = strlen(held);
    if (length) held[length - 2] = 0;
    else strcpy(held, "nothing");

    ESP_LOGI(tag, "charger: %s, %s, charger %s, vbat=%d mV, held by %s; "
             "set to icc=%d mA pre=%d mA term=%d mA%s cv=%d mV iin=%d mA "
             "vindpm=%d mV; ts=%s, %s, jeita %s; led %s",
             charge_state_name(status2),
             (status1 & (1u << 5)) ? "input good" : "no good input",
             on < 0 ? "?" : (on & 0x02) ? "on" : "off",
             read_pair(AXP2101_VBAT_HIGH, AXP2101_VBAT_LOW, 0x1F),
             held,
             charge_current_ma(read_or_none(AXP2101_CHARGE_CURRENT)),
             pre < 0 ? -1 : 25 * (pre & 0x0F),
             term < 0 ? -1 : 25 * (term & 0x0F),
             term >= 0 && !(term & 0x10) ? " (off)" : "",
             charge_voltage_mv(read_or_none(AXP2101_CHARGE_VOLTAGE)),
             input_limit_ma(read_or_none(AXP2101_INPUT_LIMIT)),
             vindpm < 0 ? -1 : 3880 + 80 * (vindpm & 0x0F),
             ts_text,
             ts_control < 0 ? "?" : (ts_control & 0x10)
                 ? "apart from the charger" : "a sensor that can stop the charger",
             jeita < 0 ? "?" : (jeita & 0x01) ? "on" : "off",
             led_name(read_or_none(AXP2101_CHGLED)));
}

/* A line at the first reading, and one when the state of the charger
 * changes after that, CHARGER_HOLD_MS apart at the closest. */
static void charger_watch(uint8_t status1, uint8_t status2)
{
    static int last = -1;
    static int64_t last_us;
    int now_state = ((status1 & 0x3F) << 8) | (status2 & 0x7F);
    int64_t now = esp_timer_get_time();
    if (now_state == last) return;
    if (last >= 0 && now - last_us < (int64_t)CHARGER_HOLD_MS * 1000) return;
    last = now_state;
    last_us = now;
    charger_report(status1, status2);
}

esp_err_t panel_battery_init(void)
{
    /* The same bus the IO expander of the key is on, which is up by now.
     * The board support hands out the one it made. */
    i2c_master_bus_handle_t bus = bsp_i2c_get_handle();
    if (!bus) return ESP_ERR_INVALID_STATE;

    /* A probe first. A read of an address nobody holds makes the driver
     * write an error of its own, and a board without this chip is not an
     * error. */
    esp_err_t err = i2c_master_probe(bus, AXP2101_ADDRESS, READ_TIMEOUT_MS);
    if (err != ESP_OK) {
        ESP_LOGW(tag, "nothing answers at 0x%02x, so the panel shows no "
                 "battery (%s)", AXP2101_ADDRESS, esp_err_to_name(err));
        return err;
    }
    /* 100 kHz. Four bytes every few seconds need no more, and it is the
     * speed every device on an I2C bus has to manage. */
    const i2c_device_config_t config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = AXP2101_ADDRESS,
        .scl_speed_hz = 100000,
    };
    err = i2c_master_bus_add_device(bus, &config, &chip);
    if (err != ESP_OK) return err;

    /* Something answers at that address. That it is the chip this reads
     * is what the type register says, and a different chip gets nothing
     * read from it. */
    uint8_t type = 0;
    err = read_register(AXP2101_IC_TYPE, &type);
    if (err != ESP_OK || type != AXP2101_CHIP_ID) {
        ESP_LOGW(tag, "0x%02x answers but is not an AXP2101 (type 0x%02x, "
                 "%s), so the panel shows no battery", AXP2101_ADDRESS, type,
                 esp_err_to_name(err));
        i2c_master_bus_rm_device(chip);
        chip = NULL;
        return err != ESP_OK ? err : ESP_ERR_NOT_FOUND;
    }

    /* Only after the type, so no other chip is written to, and before the
     * first reading, so the line about the charger shows the new values. */
    charger_set();

    /* What the board really says, once, in the log. This is the one
     * reading of these registers anybody has off a real 4B. */
    panel_supply_t supply;
    int percent;
    bool charging;
    if (panel_battery_read(&supply, &percent, &charging)) {
        if (supply == PANEL_SUPPLY_BATTERY)
            ESP_LOGI(tag, "AXP2101 found: a cell at %d %%, %s", percent,
                     charging ? "charging" : "not charging");
        else
            ESP_LOGI(tag, "AXP2101 found: no cell, the panel runs on its "
                     "cable");
    }
    return ESP_OK;
}

bool panel_battery_read(panel_supply_t *supply, int *percent, bool *charging)
{
    *supply = PANEL_SUPPLY_UNKNOWN;
    *percent = -1;
    *charging = false;
    if (!chip) return false;

    uint8_t status1 = 0;
    if (read_register(AXP2101_STATUS1, &status1) != ESP_OK) return false;
    if (!(status1 & (1u << 3))) {
        *supply = PANEL_SUPPLY_CABLE;
        return true;
    }
    uint8_t status2 = 0, level = 0;
    if (read_register(AXP2101_STATUS2, &status2) != ESP_OK) return false;
    if (read_register(AXP2101_PERCENT, &level) != ESP_OK) return false;
    *supply = PANEL_SUPPLY_BATTERY;
    *percent = level > 100 ? 100 : level;
    *charging = (status2 >> 5) == 0x01;
    charger_watch(status1, status2);
    return true;
}

bool panel_battery_cable(void)
{
    uint8_t status1 = 0;
    if (!chip || read_register(AXP2101_STATUS1, &status1) != ESP_OK) return false;
    return (status1 & (1u << 5)) != 0;
}

/* The die of the chip in degrees, from the 14 bits of its ADC. The
 * formula is that of XPowersLib (XPOWERS_AXP2101_CONVERSION). A result
 * no chip reaches is no reading: an ADC that does not measure reads 0,
 * which this turns into 385 degrees. */
static int die_celsius(int raw)
{
    if (raw < 0) return PANEL_NO_DEGREES;
    int celsius = 22 + (7274 - raw) / 20;
    return celsius < -40 || celsius > 150 ? PANEL_NO_DEGREES : celsius;
}

bool panel_battery_detail(panel_power_detail_t *out)
{
    *out = (panel_power_detail_t){
        .vbat_mv = -1, .vbus_mv = -1, .vsys_mv = -1,
        .die_c = PANEL_NO_DEGREES, .phase = -1,
        .charge_ma = -1, .charge_mv = -1, .input_ma = -1};
    if (!chip) return false;
    int status1 = read_or_none(AXP2101_STATUS1);
    int status2 = read_or_none(AXP2101_STATUS2);
    int adc = read_or_none(AXP2101_ADC_ON);
    if (status1 < 0 || status2 < 0 || adc < 0) return false;
    bool cell = status1 & (1u << 3), input = status1 & (1u << 5);
    /* A channel the ADC does not measure reads 0, and a voltage of 0 is
     * no reading either. The input reads what is left on the pin after
     * the cable went, so it counts only while the input is good. */
    if (cell && (adc & 0x01))
        out->vbat_mv = read_pair(AXP2101_VBAT_HIGH, AXP2101_VBAT_LOW, 0x1F);
    if (input && (adc & 0x04))
        out->vbus_mv = read_pair(AXP2101_VBUS_HIGH, AXP2101_VBUS_LOW, 0x3F);
    if (adc & 0x08)
        out->vsys_mv = read_pair(AXP2101_VSYS_HIGH, AXP2101_VSYS_LOW, 0x3F);
    if (adc & 0x10)
        out->die_c = die_celsius(read_pair(AXP2101_TDIE_HIGH, AXP2101_TDIE_LOW, 0x3F));
    if (out->vbat_mv == 0) out->vbat_mv = -1;
    if (out->vbus_mv == 0) out->vbus_mv = -1;
    if (out->vsys_mv == 0) out->vsys_mv = -1;
    if (cell && (status2 & 0x07) <= 5) out->phase = status2 & 0x07;
    /* The same three as "held by" in the line of the charger. */
    out->held_heat = status1 & (1u << 1);
    out->held_current = status1 & (1u << 0);
    out->held_voltage = status2 & (1u << 3);
    out->charge_ma = charge_current_ma(read_or_none(AXP2101_CHARGE_CURRENT));
    out->charge_mv = charge_voltage_mv(read_or_none(AXP2101_CHARGE_VOLTAGE));
    out->input_ma = input_limit_ma(read_or_none(AXP2101_INPUT_LIMIT));
    return true;
}
