// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// See panel_motion.h.
//
// A task of its own reads the sensor, every MOTION_PERIOD_MS while the
// watch is on and not at all otherwise. Not the task that draws: an I2C
// read on a shared bus can stall, and a stall there is a frozen screen.
// Not the network task either: a request to a PC that does not answer
// holds that task for seconds, and a lift would wait for it.
//
// The registers and the values are those of SensorLib, the driver the
// maker of the board ships with its examples:
//   examples/arduino/libraries/SensorLib/src/REG/QMI8658Constants.h and
//   SensorQMI8658.hpp in waveshareteam/ESP32-S3-Touch-LCD-4B.
// This writes to the sensor and to nothing else: it has a device of its
// own on the bus, at the address of the sensor.
#include "panel_motion.h"

#include <stdatomic.h>

#include "bsp/esp-bsp.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "panel_lift.h"
#include "panel_psram.h"

#define QMI8658_ADDRESS        0x6B
#define QMI8658_ADDRESS_OTHER  0x6A
#define QMI8658_WHO_AM_I       0x00
#define QMI8658_ID             0x05
#define QMI8658_CTRL1          0x02  /* bit 6 address counts up, bit 5 big endian */
#define QMI8658_CTRL2          0x03  /* 6:4 range, 3:0 rate of the accelerometer */
#define QMI8658_CTRL7          0x08  /* bit 0 accelerometer, bit 1 gyroscope */
#define QMI8658_STATUS0        0x2E  /* bit 0: a new reading of the accelerometer */
#define QMI8658_AX_L           0x35  /* six bytes: x, y and z, low byte first */
#define QMI8658_RESET          0x60
#define QMI8658_RESET_VALUE    0xB0
#define QMI8658_RESET_RESULT   0x4D
#define QMI8658_RESET_DONE     0x80

/* Little endian, with the address counting up: six bytes in one read. */
#define CTRL1_VALUE            0x40
/* 4 g, so the hand that lifts it does not run off the end of the range,
 * and 21 readings a second in the mode of low power, which needs the
 * gyroscope off. */
#define CTRL2_VALUE            0x1D
#define ACCEL_ON               0x01
#define ACCEL_OFF              0x00
/* At 4 g, 32768 counts are 4000 mg. */
#define MG_FULL_SCALE          4000

/* Ten readings a second. A lift takes most of a second, so two readings
 * in a row fall well inside it. */
#define MOTION_PERIOD_MS       100
/* Short, like the reads of the power chip: the bus is shared with the
 * touch, the codec, the key and the power chip. */
#define MOTION_TIMEOUT_MS      20
#define MOTION_TASK_STACK      4096
#define MOTION_TASK_PRIORITY   3

static const char *tag = "panel_motion";
static i2c_master_dev_handle_t sensor;
static atomic_bool watching, lifted;

static esp_err_t sensor_write(uint8_t reg, uint8_t value)
{
    const uint8_t data[2] = {reg, value};
    return i2c_master_transmit(sensor, data, 2, MOTION_TIMEOUT_MS);
}

static esp_err_t sensor_read(uint8_t reg, uint8_t *out, size_t length)
{
    return i2c_master_transmit_receive(sensor, &reg, 1, out, length, MOTION_TIMEOUT_MS);
}

static void motion_task(void *arg)
{
    (void)arg;
    bool active = false, complained = false;
    panel_lift_t lift;
    panel_lift_reset(&lift);
    for (;;) {
        /* The accelerometer on for a watch and off after it, and a fresh
         * rest for each watch: the panel may lie in another way now. */
        bool wanted = atomic_load(&watching);
        if (wanted != active) {
            esp_err_t err = sensor_write(QMI8658_CTRL7, wanted ? ACCEL_ON : ACCEL_OFF);
            if (err == ESP_OK) {
                active = wanted;
                panel_lift_reset(&lift);
                atomic_store(&lifted, false);
                complained = false;
            } else if (!complained) {
                ESP_LOGW(tag, "the accelerometer did not switch %s: %s",
                         wanted ? "on" : "off", esp_err_to_name(err));
                complained = true;
            }
        }
        if (active) {
            uint8_t status = 0, data[6];
            if (sensor_read(QMI8658_STATUS0, &status, 1) == ESP_OK && (status & 0x01) &&
                sensor_read(QMI8658_AX_L, data, sizeof data) == ESP_OK) {
                int32_t mg[3];
                for (int i = 0; i < 3; i++) {
                    int16_t raw = (int16_t)(data[2 * i] | (data[2 * i + 1] << 8));
                    mg[i] = (int32_t)raw * MG_FULL_SCALE / 32768;
                }
                if (panel_lift_feed(&lift, mg)) {
                    atomic_store(&lifted, true);
                    panel_lift_reset(&lift);
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(MOTION_PERIOD_MS));
    }
}

esp_err_t panel_motion_init(void)
{
    i2c_master_bus_handle_t bus = bsp_i2c_get_handle();
    if (!bus) return ESP_ERR_INVALID_STATE;
    /* A probe first, at both addresses the sensor can have: a read of an
     * address nobody holds makes the driver write an error of its own. */
    uint16_t address = 0;
    if (i2c_master_probe(bus, QMI8658_ADDRESS, MOTION_TIMEOUT_MS) == ESP_OK)
        address = QMI8658_ADDRESS;
    else if (i2c_master_probe(bus, QMI8658_ADDRESS_OTHER, MOTION_TIMEOUT_MS) == ESP_OK)
        address = QMI8658_ADDRESS_OTHER;
    if (!address) {
        ESP_LOGW(tag, "no accelerometer answers, so a lift wakes nothing");
        return ESP_ERR_NOT_FOUND;
    }
    const i2c_device_config_t config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = address,
        .scl_speed_hz = 100000,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &config, &sensor);
    if (err != ESP_OK) return err;
    /* Something answers there. That it is this sensor is what its identity
     * says, and another chip gets nothing written to it. */
    uint8_t id = 0;
    err = sensor_read(QMI8658_WHO_AM_I, &id, 1);
    if (err != ESP_OK || id != QMI8658_ID) {
        ESP_LOGW(tag, "0x%02x answers but is not a QMI8658 (0x%02x), so a lift "
                 "wakes nothing", address, id);
        i2c_master_bus_rm_device(sensor);
        sensor = NULL;
        return err != ESP_OK ? err : ESP_ERR_NOT_FOUND;
    }
    /* A reset, so the sensor starts from its datasheet whatever an earlier
     * firmware set. It says it is done in 15 ms at the most. */
    err = sensor_write(QMI8658_RESET, QMI8658_RESET_VALUE);
    uint8_t done = 0;
    for (int i = 0; err == ESP_OK && i < 10 && done != QMI8658_RESET_DONE; i++) {
        vTaskDelay(pdMS_TO_TICKS(5));
        if (sensor_read(QMI8658_RESET_RESULT, &done, 1) != ESP_OK) done = 0;
    }
    if (err == ESP_OK) err = sensor_write(QMI8658_CTRL1, CTRL1_VALUE);
    if (err == ESP_OK) err = sensor_write(QMI8658_CTRL2, CTRL2_VALUE);
    if (err == ESP_OK) err = sensor_write(QMI8658_CTRL7, ACCEL_OFF);
    if (err != ESP_OK) {
        ESP_LOGW(tag, "the QMI8658 did not take its settings: %s", esp_err_to_name(err));
        return err;
    }
    /* Its stack in PSRAM: see panel_psram.h. */
    if (panel_psram_task(motion_task, "panel_motion", MOTION_TASK_STACK,
                         MOTION_TASK_PRIORITY, tskNO_AFFINITY) != pdPASS)
        return ESP_ERR_NO_MEM;
    ESP_LOGI(tag, "QMI8658 at 0x%02x%s", address,
             done == QMI8658_RESET_DONE ? "" : ", its reset did not say it was done");
    return ESP_OK;
}

void panel_motion_watch(bool on)
{
    atomic_store(&watching, on);
}

bool panel_motion_take_lift(void)
{
    return atomic_exchange(&lifted, false);
}
