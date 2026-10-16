// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stdint.h>

// The alarm clock of the clock page, without a screen.
//
// No LVGL and no ESP-IDF here, so tests/test_panel_alarm.py builds this
// file on any machine and runs it. The screen in ui.c draws what this
// holds, and main.c wakes the display and beeps when this says so.
//
// The alarm reads the local time as a clock on a wall shows it: a day, a
// weekday, an hour and a minute. It rings in the minute that it is set to,
// and one minute rings one time. So the hour that the change to winter time
// gives twice rings one time. The hour that summer time leaves out does not
// ring.
//
// The ringing and the snooze count milliseconds, as lv_tick_get gives them,
// with the rhythm of the timer. See panel_timer.h.

// Asked for: one alarm, with a choice of weekdays. With no weekday it rings
// one time and then switches itself off. A snooze is five minutes. An alarm
// that nobody answers rings for five minutes and is then quiet.
#define PANEL_ALARM_SNOOZE_MS (5 * 60 * 1000)
#define PANEL_ALARM_RING_MS (5 * 60 * 1000)

// A bit for each weekday, Monday in bit 0 and Sunday in bit 6, in the order
// of the buttons on the screen.
#define PANEL_ALARM_DAYS 7
#define PANEL_ALARM_EVERY_DAY 0x7F

typedef struct {
    bool on;
    uint8_t hour;    // 0 to 23
    uint8_t minute;  // 0 to 59
    uint8_t days;    // the weekdays, see above; none: one time
} panel_alarm_set_t;

// The local time, as panel_time_now gives it.
typedef struct {
    bool known;       // false until the clock is set, and then nothing rings
    int32_t day;      // a number that is new at each midnight
    uint8_t weekday;  // 0 for Sunday to 6 for Saturday, as struct tm counts
    uint8_t hour;
    uint8_t minute;
    uint8_t second;
} panel_alarm_clock_t;

typedef enum {
    PANEL_ALARM_WAITING,   // off, or on and before its time
    PANEL_ALARM_RINGING,   // its minute came, and nobody answered yet
    PANEL_ALARM_SNOOZING,  // quiet until the snooze ends
} panel_alarm_phase_t;

typedef struct {
    panel_alarm_set_t set;
    panel_alarm_phase_t phase;
    int64_t rang;      // the day and minute of the last ring, -1 for none
    uint32_t ring_ms;  // when it began to ring
    uint32_t wake_ms;  // when the snooze ends
    int32_t slot;      // the slot of the ringing last answered
} panel_alarm_t;

// What one tick has to say to the rest of the panel.
typedef struct {
    bool went_off;  // it began to ring at this tick
    bool beep;      // a beep is due
    bool gave_up;   // it rang for PANEL_ALARM_RING_MS and nobody answered
} panel_alarm_news_t;

// The next ring, as the screen shows it. The weekday counts from Sunday at
// 0, as struct tm does.
typedef struct {
    bool due;
    uint8_t weekday;
    uint8_t hour;
    uint8_t minute;
} panel_alarm_next_t;

// The setting of a panel with nothing stored: off, at seven, one time.
panel_alarm_set_t panel_alarm_default(void);

// The setting as one number for NVS, and back. A number that this firmware
// did not write reads as the default.
uint32_t panel_alarm_pack(panel_alarm_set_t set);
panel_alarm_set_t panel_alarm_unpack(uint32_t packed);

void panel_alarm_init(panel_alarm_t *alarm, panel_alarm_set_t set);

// A new setting from the screen. It ends a ringing and a snooze. A setting
// for the minute that runs now rings at the next day of the alarm, not at
// once.
void panel_alarm_change(panel_alarm_t *alarm, panel_alarm_set_t set,
                        const panel_alarm_clock_t *now);

// A snooze of an alarm that rings. False when it does not ring.
bool panel_alarm_snooze(panel_alarm_t *alarm, uint32_t now_ms);

// The end of a ringing or of a snooze. The alarm waits for its next day,
// and an alarm with no weekday switches itself off. False when neither ran.
bool panel_alarm_off(panel_alarm_t *alarm);

panel_alarm_news_t panel_alarm_tick(panel_alarm_t *alarm,
                                    const panel_alarm_clock_t *now,
                                    uint32_t now_ms);

// The next ring: the end of a snooze, or the next day of the alarm. Nothing
// when the alarm is off or the clock is not set.
panel_alarm_next_t panel_alarm_next(const panel_alarm_t *alarm,
                                    const panel_alarm_clock_t *now,
                                    uint32_t now_ms);
