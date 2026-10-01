// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The timer of the clock page. See panel_timer.h.
#include "panel_timer.h"
#include <string.h>

#define MAX_MS ((uint32_t)PANEL_TIMER_MAX_MIN * 60u * 1000u)

// Milliseconds from now until then, below nought once then has passed. A
// timer is at most three hours long, far inside what an int32 holds, so
// the difference is right across the turn over of the count.
static int32_t until(uint32_t then, uint32_t now)
{
    return (int32_t)(then - now);
}

void panel_timer_init(panel_timer_t *timer)
{
    memset(timer, 0, sizeof *timer);
    timer->phase = PANEL_TIMER_IDLE;
}

bool panel_timer_adjust(panel_timer_t *timer, int minutes)
{
    if (timer->phase != PANEL_TIMER_IDLE && timer->phase != PANEL_TIMER_PAUSED)
        return false;
    int64_t left = (int64_t)timer->left_ms + (int64_t)minutes * 60 * 1000;
    if (left < 0) left = 0;
    if (left > MAX_MS) left = MAX_MS;
    if ((uint32_t)left == timer->left_ms) return false;
    timer->left_ms = (uint32_t)left;
    // A paused timer taken down to nought has nothing left to resume.
    if (timer->left_ms == 0) timer->phase = PANEL_TIMER_IDLE;
    return true;
}

bool panel_timer_start(panel_timer_t *timer, uint32_t now_ms)
{
    if (timer->phase != PANEL_TIMER_IDLE && timer->phase != PANEL_TIMER_PAUSED)
        return false;
    if (timer->left_ms == 0) return false;
    // A start from idle is what a reset goes back to. A start after a
    // pause goes on from where it was and keeps that.
    if (timer->phase == PANEL_TIMER_IDLE) timer->set_ms = timer->left_ms;
    timer->end_ms = now_ms + timer->left_ms;
    timer->phase = PANEL_TIMER_RUNNING;
    return true;
}

bool panel_timer_pause(panel_timer_t *timer, uint32_t now_ms)
{
    if (timer->phase != PANEL_TIMER_RUNNING) return false;
    int32_t left = until(timer->end_ms, now_ms);
    // Paused at the very end is the end: the next tick rings.
    if (left <= 0) return false;
    timer->left_ms = (uint32_t)left;
    timer->phase = PANEL_TIMER_PAUSED;
    return true;
}

void panel_timer_reset(panel_timer_t *timer)
{
    if (timer->phase == PANEL_TIMER_IDLE) {
        timer->left_ms = 0;
        timer->set_ms = 0;
    } else {
        timer->left_ms = timer->set_ms;
    }
    timer->phase = PANEL_TIMER_IDLE;
}

bool panel_timer_stop(panel_timer_t *timer)
{
    if (timer->phase != PANEL_TIMER_RINGING) return false;
    timer->left_ms = timer->set_ms;
    timer->phase = PANEL_TIMER_IDLE;
    return true;
}

uint32_t panel_timer_left_ms(const panel_timer_t *timer, uint32_t now_ms)
{
    switch (timer->phase) {
    case PANEL_TIMER_RUNNING: {
        int32_t left = until(timer->end_ms, now_ms);
        return left > 0 ? (uint32_t)left : 0;
    }
    case PANEL_TIMER_RINGING:
        return 0;
    default:
        return timer->left_ms;
    }
}

panel_timer_news_t panel_timer_tick(panel_timer_t *timer, uint32_t now_ms)
{
    panel_timer_news_t news = {0};
    if (timer->phase == PANEL_TIMER_RUNNING && until(timer->end_ms, now_ms) <= 0) {
        timer->phase = PANEL_TIMER_RINGING;
        timer->ring_ms = now_ms;
        timer->slot = -1;
        news.went_off = true;
    }
    if (timer->phase != PANEL_TIMER_RINGING) return news;
    int32_t rung = -until(timer->ring_ms, now_ms);
    if (rung >= PANEL_TIMER_RING_MS) {
        timer->left_ms = timer->set_ms;
        timer->phase = PANEL_TIMER_IDLE;
        news.gave_up = true;
        return news;
    }
    // One answer for each slot, however many ticks fall into it; a slot
    // that no tick reached is a beep left out, not one played late.
    int32_t slot = rung / PANEL_TIMER_SLOT_MS;
    if (slot != timer->slot) {
        timer->slot = slot;
        news.beep = slot % PANEL_TIMER_SLOTS < PANEL_TIMER_BEEPS;
    }
    return news;
}
