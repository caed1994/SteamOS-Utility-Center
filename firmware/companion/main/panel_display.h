// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "lvgl.h"
#include "esp_err.h"
#include <stddef.h>
lv_display_t *panel_display_start(void);

/* How much stack the task that draws was given.
 *
 * Read by whatever reports how much of it is left, so the two numbers come
 * from one place and a reader can see the headroom against the whole. */
size_t panel_display_stack_bytes(void);

/* Caller must hold the LVGL lock. Network and RGB timing continue running. */
esp_err_t panel_display_standby(bool sleep, int brightness);

/* Whether a finger is on the glass of a sleeping panel.
 *
 * false while the panel is awake, because LVGL reads the same controller
 * then and two readers share one bus. See panel_display_touched. */
bool panel_display_touched(void);

/* The startup animation is over, and the panel takes the pixel clock of a
 * scroll. The LVGL task calls it; a second call does nothing. See
 * PANEL_PCLK_HZ in panel_display.c. */
void panel_display_boot_over(void);
