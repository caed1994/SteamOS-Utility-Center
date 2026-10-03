// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "panel_history.h"
#include "panel_pages.h"
#include "panel_text.h"
#include "panel_timer.h"

/* The band of pages that scrolls sideways: the controls, the session and
 * the drives, the game that runs, the clock with the timer, and the card
 * with its history. PANEL_PAGES and their order are panel_pages.h's:
 * somebody can put them in another order, and the first is the page the
 * panel starts on. */

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
     * by this number. These last ones are done by the panel itself:
     * PANEL_UPDATE takes the firmware the PC offers. */
    PANEL_WAKE,
    PANEL_UPDATE
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

/* One controller, as the head and the page of the controllers draw it.
 *
 * The head has room for two and the page for four, so the panel keeps
 * four. battery is a percentage, or -1 for a controller whose battery
 * nobody reports: a controller on a cable, for one. Such a controller is
 * on the list all the same, with "--" in place of a number. */
#define PANEL_PADS 4
#define PANEL_PAD_NAME 48
typedef struct {
    char name[PANEL_PAD_NAME];
    int battery;
    bool charging;
} panel_pad_t;

/* One temperature sensor of the processor or the card, for the choice of
 * the sensor of each tile. id is what the service names it by, and what
 * the choice is a key of; name is what the menu shows. celsius is -1 for
 * a sensor with no reading. */
#define PANEL_SENSORS 6
typedef struct {
    char id[32], name[24];
    int celsius;
} panel_sensor_t;
/* The key of a sensor, for its id: FNV-1a, and never nought, which is
 * the choice of the service. */
uint32_t panel_sensor_key(const char *id);

/* The PC, as the page behind the head on the left shows it: the system,
 * the hardware and the network, in that order. A text the service did not
 * send is empty, a number it did not send is -1, and the screen writes
 * "--" for both. answer_ms is the time the last answer took, which the
 * panel measures itself. */
#define PANEL_PC_TEXT 48
typedef enum { PANEL_LINK_UNKNOWN, PANEL_LINK_WIRED, PANEL_LINK_WIRELESS } panel_link_t;
typedef struct {
    char os[32], build[24], channel[16], kernel[PANEL_PC_TEXT];
    char cpu[PANEL_PC_TEXT], gpu[PANEL_PC_TEXT];
    char ip[16], mac[18];
    int32_t uptime_s;
    int cpu_load, fan_rpm, gpu_fan_rpm;
    /* Bytes. A total of nought means nothing to show. */
    uint64_t memory_used, memory_total;
    panel_link_t link;
    int link_mbit;
    int answer_ms;
} panel_pc_t;

/* The panel itself, as its page of information shows it. The texts are
 * empty and the numbers nought where the panel has none yet. */
typedef struct {
    char version[32], ssid[33], ip[16], mac[18], server[64];
    int rssi;
    uint32_t uptime_s, heap_free, psram_free;
    /* The least internal memory that was free since the start. Nought for
     * none, and the page then shows what is free alone. */
    uint32_t heap_least;
} panel_self_t;

/* An update of the firmware over the network. offered is the version of a
 * firmware the PC offers and this panel takes, see panel_update.c, and
 * empty for none. The phase says where an update that began is; percent
 * counts the download. failure is the text that says why one failed. */
typedef enum { PANEL_UPDATE_NONE, PANEL_UPDATE_RUNNING,
               PANEL_UPDATE_RESTARTING, PANEL_UPDATE_FAILED } panel_update_phase_t;
typedef struct {
    char offered[32];
    panel_update_phase_t phase;
    int percent;
    panel_text_id_t failure;
} panel_update_t;

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

/* The power chip of the panel in detail, for the page of the panel. The
 * voltages are mV and the currents mA, and -1 where the chip gave none.
 * die_c is the temperature of the chip, PANEL_NO_DEGREES for none. phase
 * is bits 2:0 of its REG 01, -1 without a cell: 0 trickle, 1 pre-charge,
 * 2 constant current, 3 constant voltage, 4 done, 5 not charging. The
 * three held flags say what holds the charge current down. */
#define PANEL_NO_DEGREES (-128)
typedef struct {
    int vbat_mv, vbus_mv, vsys_mv, die_c, phase;
    bool held_heat, held_current, held_voltage;
    int charge_ma, charge_mv, input_ma;
} panel_power_detail_t;

typedef struct {
    bool wifi, online, muted, setup, sound_error;
    /* Whether the panel knows an address to wake the PC at. The screen
     * offers the button only then, because a button that cannot work is
     * worse than no button. */
    bool can_wake;
    int volume, cpu_temp, gpu_temp, gpu_watts;
    /* The rest of the card, for its page: how busy it is in per cent and
     * its clock in MHz, or -1; its memory in bytes, and a total of nought
     * for none. */
    int gpu_load, gpu_mhz;
    uint64_t vram_used, vram_total;
    /* Counts the answers of the PC. The history takes a point from an
     * answer, and the readings above stay as they were while the PC is
     * gone: the count is what tells a new reading from the last one. */
    uint32_t answers;
    char host[48], message[80];
    /* The controllers, in the order the service sends them. Each charging
     * is a flag and not a word. It was the text that the service sends,
     * translated into German before it was stored, and the screen compared
     * it against that German to pick the charge symbol. A second language
     * would have made that comparison fail in silence. */
    panel_pad_t pads[PANEL_PADS];
    int pad_count;
    panel_pc_t pc;
    panel_sensor_t cpu_sensors[PANEL_SENSORS], gpu_sensors[PANEL_SENSORS];
    int cpu_sensor_count, gpu_sensor_count;
    panel_self_t self;
    panel_update_t update;
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
    /* The panel itself, and not the controllers above. esp_battery is a
     * percentage and means something only for PANEL_SUPPLY_BATTERY. */
    panel_supply_t esp_supply;
    int esp_battery;
    bool esp_charging, esp_cable;
    panel_power_detail_t esp_detail;
    /* The time of day for the fourth page, local, as struct tm counts:
     * weekday from 0 for Sunday, month from 1. clock_set is false until
     * the network has set the clock. */
    bool clock_set;
    int hour, minute, weekday, day, month;
    /* The frames in movement are not in here. They change at each frame
     * of a movement, and a state that changes makes panel_ui_update do
     * all of its work again: in a scroll, at every tick. The page of the
     * panel reads them itself. See panel_frames.h. */
} panel_state_t;

typedef void (*panel_action_cb_t)(panel_action_t action);
typedef enum { PANEL_BRIGHTNESS, PANEL_SOUND_VOLUME, PANEL_TOUCH_TONES,
               PANEL_LANGUAGE, PANEL_SLEEP_AFTER,
               PANEL_CPU_SENSOR, PANEL_GPU_SENSOR, PANEL_LIFT_WAKE,
               PANEL_PAGE_ORDER } panel_setting_t;
/* sleep_after counts minutes, and nought means the display stays on. The
 * stored value is the count and not a place in the list of choices, so a
 * later firmware that offers other choices still reads what somebody
 * picked with this one.
 *
 * cpu_sensor and gpu_sensor are the sensor somebody chose for each tile,
 * as panel_sensor_key of its id, and nought for the choice of the
 * service. A key and not a place in the list: the list is in the order
 * of the service, and that order is not a promise.
 *
 * lift_wake: a lift of the panel brings back a display that went dark
 * after the set time, as a touch does. See panel_motion.c.
 *
 * page_order: the order of the pages of the band, as panel_pages.h
 * stores it. */
typedef struct { int brightness, sound_volume; bool touch_tones;
                 panel_language_t language; int sleep_after;
                 uint32_t cpu_sensor, gpu_sensor; bool lift_wake;
                 uint32_t page_order; }
    panel_settings_t;
typedef void (*panel_setting_cb_t)(panel_setting_t key, int value, bool save);
typedef void (*panel_sound_cb_t)(int volume);
void panel_ui_create(panel_action_cb_t callback, panel_setting_cb_t setting_cb, panel_sound_cb_t sound_cb, const panel_settings_t *settings);
void panel_ui_settings_open(void);
/* The page of the controllers, which a tap on the head opens. */
void panel_ui_pads_open(void);
/* The page of the PC, which a tap on the left of the head opens. */
void panel_ui_pc_open(void);
/* The page of the panel itself, which a tap on its battery opens. */
void panel_ui_self_open(void);
/* The order of the pages, which a button in the settings opens. */
void panel_ui_arrange_open(void);
/* The history of the page of the card, which main.c keeps in PSRAM. Set
 * once and before the first tick; the screen draws no curve without it. */
void panel_ui_history_use(panel_history_t *history);
/* A step of the history, asleep or awake: main.c calls it when
 * panel_history_due says so. The point is what the tiles show, with the
 * sensor somebody chose for each. */
void panel_ui_history_tick(const panel_state_t *state, uint32_t now_ms);
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
