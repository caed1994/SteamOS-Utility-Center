// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stdint.h>

// The timer of the clock page, without a screen.
//
// No LVGL and no ESP-IDF here, so tests/test_panel_timer.py builds this
// file on any machine and runs it. The screen in ui.c draws what this
// holds, and main.c wakes the display and beeps when this says so.
//
// Time comes in as a millisecond count that goes up and turns over, as
// lv_tick_get gives it, and every difference is taken so that the turn
// over does not matter.

// Asked for: 0 to 180 minutes, a tap is one minute, and a press that is
// held counts on in steps of five.
#define PANEL_TIMER_MAX_MIN 180
#define PANEL_TIMER_TAP_MIN 1
#define PANEL_TIMER_HOLD_MIN 5
// How long it rings when nobody stops it.
#define PANEL_TIMER_RING_MS (60 * 1000)
// The rhythm of the ringing: slots of this length, a beep in the first
// three of each five, so three short beeps and a pause, once a second.
#define PANEL_TIMER_SLOT_MS 200
#define PANEL_TIMER_SLOTS 5
#define PANEL_TIMER_BEEPS 3

typedef enum {
    PANEL_TIMER_IDLE,     // set with + and -, not counting
    PANEL_TIMER_RUNNING,  // counting down
    PANEL_TIMER_PAUSED,   // stopped part of the way, + and - change what is left
    PANEL_TIMER_RINGING,  // reached nought, and nobody has stopped it yet
} panel_timer_phase_t;

typedef struct {
    panel_timer_phase_t phase;
    uint32_t set_ms;    // what the last start started from, for a reset
    uint32_t left_ms;   // what is left, while idle or paused
    uint32_t end_ms;    // when a running timer reaches nought
    uint32_t ring_ms;   // when it began to ring
    int32_t slot;       // the slot of the ringing last answered
} panel_timer_t;

// What one tick has to say to the rest of the panel.
typedef struct {
    bool went_off;  // it reached nought at this tick
    bool beep;      // a beep is due
    bool gave_up;   // it rang for PANEL_TIMER_RING_MS and nobody stopped it
} panel_timer_news_t;

// A zeroed panel_timer_t is an idle timer at nought as well.
void panel_timer_init(panel_timer_t *timer);

// Minutes on or off, idle or paused, between nought and the most. false
// when nothing changed, which is also the answer while it runs or rings.
bool panel_timer_adjust(panel_timer_t *timer, int minutes);

bool panel_timer_start(panel_timer_t *timer, uint32_t now_ms);
bool panel_timer_pause(panel_timer_t *timer, uint32_t now_ms);

// Running or paused: back to what the last start started from. Idle: to
// nought. A second press after the first clears the timer.
void panel_timer_reset(panel_timer_t *timer);

// Ringing: quiet, and back to what it started from. false when it did not
// ring.
bool panel_timer_stop(panel_timer_t *timer);

uint32_t panel_timer_left_ms(const panel_timer_t *timer, uint32_t now_ms);

// Once a tick of the panel, asleep or awake.
panel_timer_news_t panel_timer_tick(panel_timer_t *timer, uint32_t now_ms);
