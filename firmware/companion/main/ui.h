// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "panel_text.h"
#include "panel_timer.h"

/* The band of pages that scrolls sideways: the controls, the session and
 * the drives, the game that runs, and the clock with the timer. */
#define PANEL_PAGES 4

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

/* What powers this panel, as its own power chip answers.
 *
 * Three answers and not two. A board whose chip did not answer says
 * nothing about its supply, and the screen shows nothing for it rather
 * than a battery that may not be there. A chip that answers and has no
 * cell behind it is a panel on its cable. */
typedef enum {
    PANEL_SUPPLY_UNKNOWN,
    PANEL_SUPPLY_CABLE,
    PANEL_SUPPLY_BATTERY
} panel_supply_t;

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
    /* How many achievements of that game are unlocked, out of how many.
     * A total of nought means nothing to count: no game, a game with no
     * achievements, or a page the Steam client never wrote. The panel
     * draws those alike, and a zeroed state is already that. */
    int achievements_done, achievements_total;
    panel_drive_t drives[PANEL_DRIVES];
    int drive_count;
    /* The panel itself, and not the controller that battery and charging
     * above belong to. esp_battery is a percentage and means something
     * only for PANEL_SUPPLY_BATTERY. */
    panel_supply_t esp_supply;
    int esp_battery;
    bool esp_charging;
    /* The time of day for the fourth page, local, as struct tm counts:
     * weekday from 0 for Sunday, month from 1. clock_set is false until
     * the network has set the clock. */
    bool clock_set;
    int hour, minute, weekday, day, month;
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
/* What the screen shows, in a few words for the log: the page of the band,
 * the settings, a question, or the setup. From the LVGL task only. */
const char *panel_ui_where(void);
/* The timer of the fourth page, once a tick of the panel, asleep or awake:
 * it runs on in a sleep. main.c wakes the display and beeps on what this
 * answers. From the LVGL task only, like everything in this file. */
panel_timer_news_t panel_ui_timer_tick(void);
/* Quiet a timer that rings. false when none rang. */
bool panel_ui_timer_stop(void);
bool panel_ui_timer_ringing(void);
/* The volume of the alarm: the volume of the sounds, and never so low that
 * a timer goes off unheard. */
int panel_ui_alarm_volume(void);
