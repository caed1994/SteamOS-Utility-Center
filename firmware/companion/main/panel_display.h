// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "lvgl.h"
#include "esp_err.h"
lv_display_t *panel_display_start(void);

/* Caller must hold the LVGL lock. Network and RGB timing continue running. */
esp_err_t panel_display_standby(bool sleep, int brightness);
