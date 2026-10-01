// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The part of ESP-IDF that panel_battery.c uses, so that it builds on this
// machine. Only the names; tests/c/panel-battery-harness.c holds the
// bodies. See tests/test_panel_battery.py.
#pragma once
#include <stdint.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_STATE 0x103
#define ESP_ERR_NOT_FOUND 0x105
const char *esp_err_to_name(esp_err_t err);
