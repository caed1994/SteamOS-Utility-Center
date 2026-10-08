// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The alarm clock of the clock page. See panel_alarm.h.
#include "panel_alarm.h"
#include "panel_timer.h"
#include <string.h>

// The stored number: the minute in bits 0 to 5, the hour in bits 6 to 10,
// the days in bits 11 to 17 and "on" in bit 18. The mark in the top byte
// tells a number of this firmware from any other.
#define PACK_MARK 0xA1u
#define PACK_USED 0x0007FFFFu

#define DAY_MINUTES 1440

// Milliseconds from now until then, below nought once then has passed. A
// ringing and a snooze are minutes long, far inside what an int32 holds.
static int32_t until(uint32_t then, uint32_t now)
{
    return (int32_t)(then - now);
}

// Whether the alarm rings on a weekday that struct tm counts from Sunday.
static bool rings_on(uint8_t days, uint8_t weekday)
{
    if (!days) return true;
    return (days >> ((weekday + 6) % 7)) & 1u;
}

static int64_t minute_of(int32_t day, int minute)
{
    return (int64_t)day * DAY_MINUTES + minute;
}

panel_alarm_set_t panel_alarm_default(void)
{
    return (panel_alarm_set_t){.on = false, .hour = 7, .minute = 0, .days = 0};
}

uint32_t panel_alarm_pack(panel_alarm_set_t set)
{
    return PACK_MARK << 24 | (uint32_t)set.on << 18 |
           (uint32_t)(set.days & PANEL_ALARM_EVERY_DAY) << 11 |
           (uint32_t)(set.hour & 0x1Fu) << 6 | (uint32_t)(set.minute & 0x3Fu);
}

panel_alarm_set_t panel_alarm_unpack(uint32_t packed)
{
    panel_alarm_set_t set = {
        .on = (packed >> 18) & 1u,
        .hour = (packed >> 6) & 0x1Fu,
        .minute = packed & 0x3Fu,
        .days = (packed >> 11) & PANEL_ALARM_EVERY_DAY,
    };
    if (packed >> 24 != PACK_MARK || (packed & 0x00FFFFFFu & ~PACK_USED) ||
        set.hour > 23 || set.minute > 59)
        return panel_alarm_default();
    return set;
}

void panel_alarm_init(panel_alarm_t *alarm, panel_alarm_set_t set)
{
    memset(alarm, 0, sizeof *alarm);
    alarm->set = set;
    alarm->phase = PANEL_ALARM_WAITING;
    alarm->rang = -1;
}

// The end of one ring, by a person or by the time.
static void quiet(panel_alarm_t *alarm)
{
    alarm->phase = PANEL_ALARM_WAITING;
    if (!alarm->set.days) alarm->set.on = false;
}

static void ring(panel_alarm_t *alarm, uint32_t now_ms)
{
    alarm->phase = PANEL_ALARM_RINGING;
    alarm->ring_ms = now_ms;
    alarm->slot = -1;
}

void panel_alarm_change(panel_alarm_t *alarm, panel_alarm_set_t set,
                        const panel_alarm_clock_t *now)
{
    alarm->set = set;
    alarm->phase = PANEL_ALARM_WAITING;
    // The minute that runs now counts as rung. Somebody who sets 7:00 at
    // 7:00 and a few seconds wants the next morning, not a ring at once.
    if (now->known) alarm->rang = minute_of(now->day, now->hour * 60 + now->minute);
}

bool panel_alarm_snooze(panel_alarm_t *alarm, uint32_t now_ms)
{
    if (alarm->phase != PANEL_ALARM_RINGING) return false;
    alarm->phase = PANEL_ALARM_SNOOZING;
    alarm->wake_ms = now_ms + PANEL_ALARM_SNOOZE_MS;
    return true;
}

bool panel_alarm_off(panel_alarm_t *alarm)
{
    if (alarm->phase == PANEL_ALARM_WAITING) return false;
    quiet(alarm);
    return true;
}

panel_alarm_news_t panel_alarm_tick(panel_alarm_t *alarm,
                                    const panel_alarm_clock_t *now,
                                    uint32_t now_ms)
{
    panel_alarm_news_t news = {0};
    if (alarm->phase == PANEL_ALARM_WAITING && alarm->set.on && now->known &&
        now->hour == alarm->set.hour && now->minute == alarm->set.minute &&
        rings_on(alarm->set.days, now->weekday)) {
        int64_t at = minute_of(now->day, now->hour * 60 + now->minute);
        if (at != alarm->rang) {
            alarm->rang = at;
            ring(alarm, now_ms);
            news.went_off = true;
        }
    }
    if (alarm->phase == PANEL_ALARM_SNOOZING && until(alarm->wake_ms, now_ms) <= 0) {
        ring(alarm, now_ms);
        news.went_off = true;
    }
    if (alarm->phase != PANEL_ALARM_RINGING) return news;
    int32_t rung = -until(alarm->ring_ms, now_ms);
    if (rung >= PANEL_ALARM_RING_MS) {
        quiet(alarm);
        news.gave_up = true;
        return news;
    }
    // The rhythm of the timer, so the two sound the same. One answer for
    // each slot: a slot that no tick reached is a beep left out.
    int32_t slot = rung / PANEL_TIMER_SLOT_MS;
    if (slot != alarm->slot) {
        alarm->slot = slot;
        news.beep = slot % PANEL_TIMER_SLOTS < PANEL_TIMER_BEEPS;
    }
    return news;
}

panel_alarm_next_t panel_alarm_next(const panel_alarm_t *alarm,
                                    const panel_alarm_clock_t *now,
                                    uint32_t now_ms)
{
    panel_alarm_next_t next = {0};
    if (!now->known) return next;
    if (alarm->phase == PANEL_ALARM_SNOOZING) {
        // The time now and what is left of the snooze, in whole seconds.
        int32_t left = until(alarm->wake_ms, now_ms);
        if (left < 0) left = 0;
        int32_t at = now->hour * 3600 + now->minute * 60 + now->second + (left + 999) / 1000;
        next.due = true;
        next.weekday = (uint8_t)((now->weekday + at / 86400) % 7);
        next.hour = (uint8_t)(at % 86400 / 3600);
        next.minute = (uint8_t)(at % 3600 / 60);
        return next;
    }
    if (!alarm->set.on) return next;
    int set = alarm->set.hour * 60 + alarm->set.minute;
    int clock = now->hour * 60 + now->minute;
    // Today and the seven days after it: a day of the week comes again in
    // seven days, so one of these is the next ring.
    for (int ahead = 0; ahead <= PANEL_ALARM_DAYS; ahead++) {
        uint8_t weekday = (uint8_t)((now->weekday + ahead) % 7);
        if (!rings_on(alarm->set.days, weekday)) continue;
        if (ahead == 0 && alarm->phase == PANEL_ALARM_WAITING &&
            (set < clock || (set == clock && alarm->rang == minute_of(now->day, set))))
            continue;
        next.due = true;
        next.weekday = weekday;
        next.hour = alarm->set.hour;
        next.minute = alarm->set.minute;
        return next;
    }
    return next;
}
