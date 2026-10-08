// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The colours of the screen: a dark theme and a light one, and an accent
// that somebody chooses for each.
//
// Asked for: a light theme beside the dark one, and a choice of eight
// colours for the sliders and the switches. The accent is the colour of
// everything the panel lights up, which was the blue of the dark theme:
// the sliders and the switches, the button that confirms, the choice on a
// page, the values beside the sliders, the readings of the sensors and the
// bars. A slider in orange beside readings in blue is two accents and not
// one.
//
// The eight are the colours of the LED bar of the PC without its white, in
// the order of the colour circle from the blue the panel always had. White
// is no accent: it is the colour of the text of the dark theme. So the
// panel can wear the colour of the bar, and their names are the ones of the
// page of the LED bar already.
//
// Each accent has its tones for each theme. The bright tone that reads on a
// dark card is too pale on a white one, so the light theme has a deeper
// tone of the same colour. Words in the accent take the deepest: a yellow
// dark enough to read on white is a brown, so in the light theme yellow is
// gold as a face, with dark words on it, and the words in yellow are a
// darker gold. tests/test_panel_theme.py holds every pair of colours that
// stand on each other to a contrast that reads, and
// firmware/companion/preview/check_pages.c holds every label of every page
// to it in each theme and each accent.
//
// Three colours do not follow the accent. Red warns: the button that
// switches the PC off, a drive that is nearly full, a panel with no
// network. The curves of the history keep a colour each, because a curve
// in the accent could be the curve of the card beside it. And the black
// cover of a sleeping panel stays black, with its clock in the colours of
// the dark theme: a light cover would be a panel that looks switched on.
// See panel_ui_sleep.c.
#pragma once

#include <stdint.h>

#include "panel_text.h"

/* The dark theme leads, so a panel with nothing stored, and a stored
 * number that this firmware does not have, look as the panel always did. */
typedef enum { PANEL_THEME_DARK, PANEL_THEME_LIGHT, PANEL_THEMES } panel_theme_t;

/* The number of an accent is what is stored, so a colour keeps its number:
 * a new one comes at the end. Blue leads for the reason above. */
typedef enum {
    PANEL_ACCENT_BLUE, PANEL_ACCENT_CYAN, PANEL_ACCENT_GREEN, PANEL_ACCENT_YELLOW,
    PANEL_ACCENT_ORANGE, PANEL_ACCENT_RED, PANEL_ACCENT_MAGENTA, PANEL_ACCENT_PURPLE,
    PANEL_ACCENTS
} panel_accent_t;

/* The colours of a theme in an accent, each as 0xRRGGBB. */
typedef struct {
    /* The page, a card on it, the border of a card and its lines and the
     * track of a slider, a bar or a switch that is off, the text, the words
     * that name a value, and the face of a button. */
    uint32_t bg, card, edge, text, muted, button;
    /* The accent as a face: a slider, a switch, a bar or a button. Words
     * and thin lines in the accent, on a card or a button. The words and
     * the signs on a face in the accent. */
    uint32_t accent, accent_text, on_accent;
    /* The knob of a switch, its rim, and the knob of a slider. The rim is
     * the knob itself in the dark theme. In the light one it is what keeps
     * a white knob on a pale track in sight, and a greyed one at all. */
    uint32_t knob, knob_edge, slider_knob;
    /* The red that warns, and the face and the border of the button that
     * switches the PC off. */
    uint32_t red, danger, danger_edge;
    /* The dot of the connection: the PC answers, or it does not. */
    uint32_t online, offline;
    /* The curves of the history: the processor, the card and its power. */
    uint32_t curve_cpu, curve_gpu, curve_watts;
} panel_palette_t;

/* The colours of "theme" in "accent". A theme or an accent outside the
 * lists is the dark theme or blue. */
panel_palette_t panel_palette(int theme, int accent);
/* The name of an accent on the screen, and of a theme. A number outside the
 * list is the name of the one that panel_palette shows for it. */
panel_text_id_t panel_accent_name(int accent);
panel_text_id_t panel_theme_name(int theme);
