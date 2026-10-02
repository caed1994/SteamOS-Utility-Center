// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The I2C master calls that panel_battery.c and panel_rtc.c make, and no
// others. The harnesses count each transmit, which is a write, by
// register. See tests/c/stubs/esp_err.h.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef struct i2c_master_dev_t *i2c_master_dev_handle_t;
typedef struct i2c_master_bus_t *i2c_master_bus_handle_t;
typedef enum { I2C_ADDR_BIT_LEN_7 } i2c_addr_bit_len_t;
typedef struct {
    i2c_addr_bit_len_t dev_addr_length;
    uint16_t device_address;
    uint32_t scl_speed_hz;
} i2c_device_config_t;
esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t device,
                                      const uint8_t *write, size_t write_size,
                                      uint8_t *read, size_t read_size,
                                      int timeout_ms);
esp_err_t i2c_master_transmit(i2c_master_dev_handle_t device,
                              const uint8_t *write, size_t write_size,
                              int timeout_ms);
esp_err_t i2c_master_probe(i2c_master_bus_handle_t bus, uint16_t address,
                           int timeout_ms);
esp_err_t i2c_master_bus_add_device(i2c_master_bus_handle_t bus,
                                    const i2c_device_config_t *config,
                                    i2c_master_dev_handle_t *device);
esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t device);
