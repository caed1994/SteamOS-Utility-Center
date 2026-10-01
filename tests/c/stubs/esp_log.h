// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// ESP_LOG to standard output, one line each. See tests/c/stubs/esp_err.h.
#pragma once
#include <stdio.h>
#define ESP_LOGI(tag, format, ...) printf("I %s: " format "\n", tag, ##__VA_ARGS__)
#define ESP_LOGW(tag, format, ...) printf("W %s: " format "\n", tag, ##__VA_ARGS__)
