// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
esp_err_t panel_power_init(void);
bool panel_power_take_toggle(void);

/* Whether the home key was pressed since this was last asked, and it
 * clears that. Two presses between two asks are one: both ask for the
 * same start page. */
bool panel_power_take_home(void);

/* The longest one turn of the key loop took since this was last asked, in
 * milliseconds, and it clears the mark. The shortest press the panel can
 * see is about twice this, so a number far above PWRKEY_PERIOD_MS means a
 * short press can be lost. main.c puts it in the periodic log line. */
uint32_t panel_power_slowest_read_ms(void);
