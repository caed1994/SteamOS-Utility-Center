// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#define LV_CONF_H
// The depth the firmware runs at, and not a comfortable 32.
//
// It was 32 here, and that hid a fault the board showed at once: the panel
// played its startup animation as a square of solid green. The reason is in
// lv_gif.c, in gif_blend_to_rgb565, which writes the background colour of
// the image over every transparent pixel rather than leaving the pixel of
// the frame before. The path for ARGB8888 does not, so at 32 bits these
// checks saw a correct screen that the board never showed.
//
// A check environment that differs from the target is a check that answers
// about a machine nobody has.
#define LV_COLOR_DEPTH 16
#define LV_USE_OS LV_OS_NONE
#define LV_USE_STDLIB_MALLOC LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF LV_STDLIB_CLIB
#define LV_FONT_MONTSERRAT_12 1
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_18 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_24 1
#define LV_FONT_MONTSERRAT_32 1
#define LV_FONT_DEFAULT &lv_font_montserrat_16
#define LV_BUILD_EXAMPLES 0
#define LV_BUILD_DEMOS 0
#define LV_USE_LOG 0
// panel_boot.c plays the startup animation, and check_boot runs it.
#define LV_USE_GIF 1
