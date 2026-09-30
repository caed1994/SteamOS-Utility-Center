// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The battery of the panel, read off its power chip.
//
// The 4B carries an AXP2101, which charges a cell and keeps a gauge of it.
// Nothing in the board support speaks to it, so this does, and it only
// reads. A power chip decides which rails of the board have power, and one
// wrong write to it can switch off the rail this code runs on. None of the
// registers below is written, and the rule in tests/test_panel_battery.py
// holds that.
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
    return true;
}
