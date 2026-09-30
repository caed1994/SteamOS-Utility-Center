// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "panel_text.h"

typedef enum {
    PANEL_VOLUME_DOWN, PANEL_MUTE, PANEL_VOLUME_UP,
    PANEL_SUSPEND, PANEL_REBOOT, PANEL_POWEROFF,
    /* Where to go, and not "the other one". The panel reads the session
     * out of a status that is up to three seconds old, so one name that
     * means "switch" would now and then switch to the side it is already
     * on. companion.py carries the same reasoning at its end. */
    PANEL_DESKTOP_MODE, PANEL_GAME_MODE,
    PANEL_SETUP,
    /* After PANEL_SETUP on purpose. Everything below it is a name that
     * main.c sends to the service, and the dispatch there reads that table
     * by this number. These last two are done by the panel itself. */
    PANEL_WAKE
} panel_action_t;

/* One drive, as the second page draws it.
 *
 * Bytes and not a percentage. The panel has the room to write what is left
 * beside what there is, and a percentage alone answers the wrong question:
 * ten percent of a card and ten percent of the internal drive are not the
 * same amount of game. */
#define PANEL_DRIVE_NAME 16
#define PANEL_DRIVES 3
typedef struct {
    char name[PANEL_DRIVE_NAME];
    /* Bytes. A drive of this size passes four thousand million a long way,
     * so this is not an int. */
    uint64_t total, free;
} panel_drive_t;

typedef struct {
    // charging is a flag and not a word any more. It was the text that the
    // service sends, translated into German before it was stored, and the
    // screen compared it against that German to pick the charge symbol. A
    // second language would have made that comparison fail in silence.
    bool wifi, online, muted, setup, sound_error, charging;
    /* Whether the panel knows an address to wake the PC at. The screen
     * offers the button only then, because a button that cannot work is
     * worse than no button. */
    bool can_wake;
    int battery, volume, cpu_temp, gpu_temp, gpu_watts;
    char host[48], controller[64], message[80];
    char setup_ssid[32], setup_password[32];
    /* The second page. game_mode says which session runs, playing holds
     * the name of the game or nothing at all, and the drives are however
     * many answered up to the room there is. */
    bool game_mode;
    char playing[64];
    panel_drive_t drives[PANEL_DRIVES];
    int drive_count;
} panel_state_t;

typedef void (*panel_action_cb_t)(panel_action_t action);
typedef enum { PANEL_BRIGHTNESS, PANEL_SOUND_VOLUME, PANEL_TOUCH_TONES,
               PANEL_LANGUAGE, PANEL_SLEEP_AFTER } panel_setting_t;
/* sleep_after counts minutes, and nought means the display stays on. The
 * stored value is the count and not a place in the list of choices, so a
 * later firmware that offers other choices still reads what somebody
 * picked with this one. */
typedef struct { int brightness, sound_volume; bool touch_tones;
                 panel_language_t language; int sleep_after; }
    panel_settings_t;
typedef void (*panel_setting_cb_t)(panel_setting_t key, int value, bool save);
typedef void (*panel_sound_cb_t)(int volume);
void panel_ui_create(panel_action_cb_t callback, panel_setting_cb_t setting_cb, panel_sound_cb_t sound_cb, const panel_settings_t *settings);
void panel_ui_settings_open(void);
void panel_ui_update(const panel_state_t *state);
void panel_ui_confirm(panel_action_t action);
