// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include "esp_err.h"

/* The clock of the CPU, at full speed until panel_clock_low says not.
 *
 * Call once at the start, before anything that draws. An error leaves the
 * CPU at the speed it started at, which is the speed it had before this
 * file existed, so the caller writes a warning and goes on. */
esp_err_t panel_clock_init(void);

/* true while the display sleeps, false when it comes back. A second call
 * with the same value does nothing. */
void panel_clock_low(bool low);

/* The speed of the CPU now, in MHz, for the health line. */
unsigned panel_clock_mhz(void);
