// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include "esp_err.h"
esp_err_t panel_power_init(void);
bool panel_power_take_toggle(void);
