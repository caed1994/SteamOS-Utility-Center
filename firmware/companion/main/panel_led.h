// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The effects of the LED bar of the PC, for the page of the LED bar.
//
// Two lists, one for each mode of the PC. The desktop list is every scene
// that the LED service draws on the desktop: the effects of Steam and the
// effects of this project. The Game Mode list is what the rainbow entry of
// the LED menu of Steam can show: the rainbow of Steam, or an effect of
// this project in its place. Steam keeps the other entries of that menu,
// and nothing on the panel changes them.
//
// The keys are the words of the LED service, in its order: desktop.SCENES
// and render.RAINBOW_CHOICES. tests/test_panel_led.py holds the two lists
// here equal to the two there, so an effect that the service learns is a
// failing test until this file has it too.
#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "panel_text.h"

typedef enum { PANEL_LED_DESKTOP, PANEL_LED_GAME, PANEL_LED_MODES } panel_led_mode_t;

/* The room for a key and its end. The longest is "temperature". */
#define PANEL_LED_KEY 16

/* How many effects the mode has. */
int panel_led_count(panel_led_mode_t mode);
/* The key of the effect at "index", or NULL for an index outside the
 * list. */
const char *panel_led_key(panel_led_mode_t mode, int index);
/* The place of a key in the list of its mode, or -1 for a key that this
 * firmware does not know: one of a later service, or none at all. */
int panel_led_find(panel_led_mode_t mode, const char *key);
/* The name of the effect at "index" on the screen. */
panel_text_id_t panel_led_name(panel_led_mode_t mode, int index);
/* Whether the effect at "index" draws in the desktop colour of the LED
 * service: desktop.SCENES_WITH_COLOUR. The panel does not set that colour,
 * and the page says where it comes from. */
bool panel_led_coloured(panel_led_mode_t mode, int index);
/* The effect "step" places from "index", round the ends of the list. An
 * index of -1 steps to the first effect, or to the last for a step back. */
int panel_led_step(panel_led_mode_t mode, int index, int step);
/* The name of a mode in the status of the companion service and in a
 * change: "desktop" and "game". companion.LED_CHOICES holds the same two. */
const char *panel_led_mode_name(panel_led_mode_t mode);
/* The body of a change for the companion service: a JSON object with the
 * key of each mode that has one, as {"desktop":"fire"}. An empty key is
 * left out. Answers the length, and nought for no key at all or for too
 * little room. The keys come from the lists above, which hold letters and
 * nothing to escape. */
size_t panel_led_body(char *out, size_t room, const char keys[PANEL_LED_MODES][PANEL_LED_KEY]);
