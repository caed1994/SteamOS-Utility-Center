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
//
// The page also sets the colour and the brightness of the desktop scenes.
// The colours are the nine that the control panel offers, in its order:
// companion.LED_COLOURS, which the same test holds equal to this list.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "panel_text.h"

typedef enum { PANEL_LED_DESKTOP, PANEL_LED_GAME, PANEL_LED_MODES } panel_led_mode_t;

/* The room for a key and its end. The longest is "temperature". */
#define PANEL_LED_KEY 16

/* How many colours the page offers, and the room for one and its end:
 * "#rrggbb". */
#define PANEL_LED_COLOURS 9
#define PANEL_LED_COLOUR 8

/* The keys of the colour and of the brightness in the status of the
 * companion service and in a change: companion.LED_LOOK. */
#define PANEL_LED_COLOUR_KEY "desktop_color"
#define PANEL_LED_BRIGHTNESS_KEY "desktop_brightness"

/* The profiles of the mirror: screen.PROFILES, in its order. The key of
 * the profile in the status and in a change: companion.LED_MIRROR. The
 * names are English in each language, as the owner asked. */
#define PANEL_LED_PROFILES 3
#define PANEL_LED_PROFILE_KEY "mirror_profile"
/* A change of the page: the key of the new effect of each mode, the new
 * colour of the desktop scenes, their new brightness from 0 to 255, and the
 * new profile of the mirror. An empty key, colour or profile, and a
 * brightness below nought, keep what the PC has. */
typedef struct {
    char effect[PANEL_LED_MODES][PANEL_LED_KEY];
    char colour[PANEL_LED_COLOUR];
    int brightness;
    char profile[PANEL_LED_KEY];
} panel_led_change_t;

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
 * service: desktop.SCENES_WITH_COLOUR. */
bool panel_led_coloured(panel_led_mode_t mode, int index);
/* Whether the effect at "index" draws in the desktop brightness of the LED
 * service: desktop.SCENES_LIT. Steam sets the brightness in Game Mode, so
 * no effect of that list does. */
bool panel_led_lit(panel_led_mode_t mode, int index);
/* The effect "step" places from "index", round the ends of the list. An
 * index of -1 steps to the first effect, or to the last for a step back. */
int panel_led_step(panel_led_mode_t mode, int index, int step);
/* The name of a mode in the status of the companion service and in a
 * change: "desktop" and "game". companion.LED_CHOICES holds the same two. */
const char *panel_led_mode_name(panel_led_mode_t mode);
/* The colour at "index" as the service writes it, "#ff0000", or NULL for
 * an index outside the list. */
const char *panel_led_colour(int index);
/* The place of a colour in the list, or -1 for a colour that is not in it:
 * one that somebody wrote into the file of the service. */
int panel_led_colour_find(const char *colour);
/* The name of the colour at "index" on the screen. */
panel_text_id_t panel_led_colour_name(int index);
/* The key of the profile at "index", or NULL for an index outside the
 * list. */
const char *panel_led_profile(int index);
/* The place of a profile, or -1 for one that this firmware does not know. */
int panel_led_profile_find(const char *key);
/* The name of the profile at "index" on the screen. */
panel_text_id_t panel_led_profile_name(int index);
/* A colour "#rrggbb" as the number 0xRRGGBB. false, and nothing in "rgb",
 * for a text that is no such colour. */
bool panel_led_rgb(const char *colour, uint32_t *rgb);
/* A brightness of the service, 0 to 255, as a per cent, and a per cent as
 * a brightness. Each per cent comes back to itself through the two. */
int panel_led_percent(int brightness);
int panel_led_brightness(int percent);
/* The body of a change for the companion service: a JSON object with the
 * key of each mode that has one, the colour, the brightness and the
 * profile, as {"desktop":"breath","desktop_color":"#ff0000"}. What keeps
 * the value of the PC is left out. Answers the length, and nought for
 * nothing to send, for too little room, for a colour that is no "#rrggbb",
 * a brightness above 255 and a profile that is not in the list. The keys
 * come from the lists above, which hold letters and nothing to escape. */
size_t panel_led_body(char *out, size_t room, const panel_led_change_t *change);

/* The room for the detail and for the size of the screen in the status of
 * the mirror, each with its end: screen.DETAIL_CHARS and "65535x65535". */
#define PANEL_MIRROR_DETAIL 41
#define PANEL_MIRROR_SOURCE 12

/* The status of the mirror on the PC: the state word of screen.STATES, its
 * detail, the pictures each second, the processor time in tenths of a per
 * cent, and the size of the screen. An empty state is a PC that sends no
 * status, and a number below nought is a number that the status does not
 * have. */
typedef struct {
    char state[PANEL_LED_KEY];
    char detail[PANEL_MIRROR_DETAIL];
    char source[PANEL_MIRROR_SOURCE];
    int fps;
    int cpu;
} panel_led_mirror_t;

/* The line under the Game Mode card while it shows the mirror, in the
 * language of the panel. A state that this firmware does not know gets the
 * line of each other effect of that card. */
void panel_led_mirror_line(char *out, size_t room, const panel_led_mirror_t *mirror);
