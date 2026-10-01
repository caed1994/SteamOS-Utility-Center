// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Drives panel_battery.c against a power chip made of 256 bytes, and prints
// what it writes to the log. A test on this machine reads it.
//
// Commands on standard input, one to a line:
//
//   set <register> <value>   both in hexadecimal
//   at <seconds>             the clock of esp_timer_get_time
//   init                     panel_battery_init
//   read                     panel_battery_read
//
// The registers start as an AXP2101 with no cell. Every transfer that is
// not a read of one register is counted, and the count is printed at the
// end, so a write the source makes shows here as well. See
// tests/test_panel_battery.py.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/i2c_master.h"
#include "bsp/esp-bsp.h"
#include "esp_timer.h"
#include "panel_battery.h"

static uint8_t registers[256];
static int64_t clock_us;
static int not_a_read;

const char *esp_err_to_name(esp_err_t err) { return err ? "ERROR" : "ESP_OK"; }
int64_t esp_timer_get_time(void) { return clock_us; }
i2c_master_bus_handle_t bsp_i2c_get_handle(void)
{
    return (i2c_master_bus_handle_t)registers;
}

esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t device,
                                      const uint8_t *write, size_t write_size,
                                      uint8_t *read, size_t read_size,
                                      int timeout_ms)
{
    (void)device; (void)timeout_ms;
    if (write_size != 1 || read_size != 1) {
        not_a_read++;
        return ESP_FAIL;
    }
    *read = registers[*write];
    return ESP_OK;
}

esp_err_t i2c_master_probe(i2c_master_bus_handle_t bus, uint16_t address,
                           int timeout_ms)
{
    (void)bus; (void)timeout_ms;
    return address == 0x34 ? ESP_OK : ESP_FAIL;
}

esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t bus,
                                    const i2c_device_config_t *config,
                                    i2c_master_dev_handle_t *device)
{
    (void)bus; (void)config;
    *device = (i2c_master_dev_handle_t)registers;
    return ESP_OK;
}

esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t device)
{
    (void)device;
    return ESP_OK;
}

int main(void)
{
    registers[0x03] = 0x4A;
    char line[128];
    while (fgets(line, sizeof line, stdin)) {
        unsigned reg, value;
        double seconds;
        if (sscanf(line, "set %x %x", &reg, &value) == 2) {
            registers[reg & 0xFF] = (uint8_t)value;
        } else if (sscanf(line, "at %lf", &seconds) == 1) {
            clock_us = (int64_t)(seconds * 1e6);
        } else if (strncmp(line, "init", 4) == 0) {
            panel_battery_init();
        } else if (strncmp(line, "read", 4) == 0) {
            panel_supply_t supply;
            int percent;
            bool charging;
            panel_battery_read(&supply, &percent, &charging);
        }
    }
    printf("not a read: %d\n", not_a_read);
    return 0;
}
