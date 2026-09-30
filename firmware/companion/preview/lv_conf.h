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
// The log.
//
// A nought here was the same shape of blind spot as the colour depth above:
// panel_boot.c measures the pacing of the animation and prints it with
// LV_LOG_USER, and a check with no log never runs that line at all.
//
// The level is WARN, and USER is not a quieter setting although it reads
// like one. The order is TRACE, INFO, WARN, ERROR, USER, NONE, and LVGL
// prints what stands at the level or above. At USER that is USER alone:
// every LV_LOG_ERROR goes missing. The preview ran that way while LVGL
// was writing "Failed to open image" at every refresh of the card, and
// the checks all passed. check_pages now fails on such a line, and it
// needs the line to arrive first.
#define LV_USE_LOG 1
#define LV_LOG_LEVEL LV_LOG_LEVEL_WARN
#define LV_LOG_PRINTF 1
// panel_boot.c plays the startup animation, and check_boot runs it.
#define LV_USE_GIF 1
// ui.c draws the picture of the game that runs, and check_pages runs it.
// The same two as the panel: a preview configured differently from the
// board is a preview that watches a screen the board never shows. The
// colour depth above is here for the same reason.
#define LV_USE_TJPGD 1
// TJPGD refuses bytes in memory without this. It reads a file, and this
// is the driver that makes a block of memory look like one. See the
// LV_IMAGE_SRC_VARIABLE branch of decoder_open in lv_tjpgd.c.
#define LV_USE_FS_MEMFS 1
#define LV_FS_MEMFS_LETTER 'M'
