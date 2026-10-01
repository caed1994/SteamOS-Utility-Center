// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The fonts of the panel's text, in place of the Montserrat built into
// LVGL.
//
// The built-in fonts hold ASCII, the degree sign and the symbols, and no
// letter of German past that. So the German was written as "Bestaetigen".
// These hold the same and Ä Ö Ü ä ö ü ß as well, with the small letters
// with an accent that a game name can carry. ui.c draws every word with
// one of them, and tests/test_panel_text.py holds each word of the table
// to the letters they have.
//
// Each file says how it was made, on its "Opts" line: lv_font_conv 1.5.2,
// the options of LVGL's own scripts/built_in_font/built_in_font_gen.py,
// and the wider range of letters.
#pragma once
#include "lvgl.h"

LV_FONT_DECLARE(panel_font_12);
LV_FONT_DECLARE(panel_font_14);
LV_FONT_DECLARE(panel_font_16);
LV_FONT_DECLARE(panel_font_18);
LV_FONT_DECLARE(panel_font_20);
LV_FONT_DECLARE(panel_font_24);
LV_FONT_DECLARE(panel_font_26);
LV_FONT_DECLARE(panel_font_32);
