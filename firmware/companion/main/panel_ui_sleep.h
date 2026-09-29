// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "lvgl.h"
/* UI-only standby; caller holds the LVGL lock and balances enter/leave calls. */
void panel_ui_sleep(lv_display_t *screen, lv_indev_t *input, bool sleep);

/* Forget the black cover, for a caller that cleaned the screen under it.
 * A pointer to a deleted object is a use of one at the next sleep. */
void panel_ui_sleep_reset(void);
