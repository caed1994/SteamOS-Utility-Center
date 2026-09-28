// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"

typedef struct {
    char ssid[33];
    char password[65];
    char server[192];
    char token[128];
} panel_config_t;

bool panel_config_load(panel_config_t *config);
esp_err_t panel_config_portal(char *ssid, size_t ssid_size, char *password, size_t password_size);
