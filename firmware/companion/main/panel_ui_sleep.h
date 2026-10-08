// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "lvgl.h"
/* UI-only standby; caller holds the LVGL lock. A second call the same way
 * does nothing: LVGL counts each switch of the invalidation, so an extra
 * wake would leave a later sleep with the invalidation still on. */
void panel_ui_sleep(lv_display_t *screen, lv_indev_t *input, bool sleep);

/* Forget the black cover, for a caller that cleaned the screen under it.
 * A pointer to a deleted object is a use of one at the next sleep. */
void panel_ui_sleep_reset(void);

/* The clock on the cover: the time, and the day and the date under it.
 * Empty texts leave the cover black, as it was before the clock.
 *
 * A text that is the same as the one shown costs a comparison and
 * nothing else. A sleeping panel draws a new one at once, and only the
 * line that changed: invalidation goes on for the change and off again.
 * An awake panel keeps it for the next sleep. Same lock as above. true
 * when it drew on a sleeping panel. */
bool panel_ui_sleep_clock(lv_display_t *screen, const char *time, const char *date);
