// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_taps.h"

#include <string.h>

panel_taps_t panel_taps;
panel_taps_chip_t panel_taps_chip;

void panel_taps_reset(panel_taps_t *taps)
{
    *taps = (panel_taps_t){.weakest_ever = -1};
}

void panel_taps_hold(panel_taps_t *taps, bool hold)
{
    taps->held = hold;
}

void panel_taps_break(panel_taps_t *taps)
{
    taps->read_before = false;
    taps->down = false;
    taps->ending = false;
}

/* A press that ended goes into the counts, and out as one line. */
static void finish(panel_taps_t *taps, panel_taps_press_t *done)
{
    panel_taps_end_t end = taps->swiped ? PANEL_TAPS_SWIPE
                         : taps->tapped ? PANEL_TAPS_TAP
                         : taps->on_target ? PANEL_TAPS_LOST : PANEL_TAPS_NOTHING;
    uint32_t ms = taps->up_at_ms - taps->down_at_ms;
    if (done) *done = (panel_taps_press_t){.ms = ms, .moved = taps->moved,
                                           .weakest = taps->weakest, .end = end};
    taps->ending = false;
    if (taps->held) return;
    taps->presses++;
    if (end == PANEL_TAPS_TAP) taps->taps++;
    if (end == PANEL_TAPS_SWIPE) taps->swipes++;
    if (end == PANEL_TAPS_LOST) taps->lost++;
    if (taps->presses == 1 || ms < taps->shortest_ms) taps->shortest_ms = ms;
    if (taps->weakest >= 0 && (taps->weakest_ever < 0 || taps->weakest < taps->weakest_ever))
        taps->weakest_ever = taps->weakest;
}

bool panel_taps_read(panel_taps_t *taps, uint32_t now_ms, bool ok, bool pressed,
                     int x, int y, int strength, panel_taps_press_t *done)
{
    if (taps->read_before && !taps->held) {
        uint32_t gap = now_ms - taps->last_read_ms;
        if (gap > taps->longest_gap_ms) taps->longest_gap_ms = gap;
        if (gap > PANEL_TAPS_LATE_MS) taps->late++;
    }
    taps->read_before = true;
    taps->last_read_ms = now_ms;
    if (!ok) {
        if (!taps->held) taps->errors++;
        return false;
    }
    /* LVGL sent its events for the release at the read before this one. */
    bool over = false;
    if (taps->ending) {
        finish(taps, done);
        over = true;
    }
    if (pressed) {
        if (!taps->down) {
            taps->down = true;
            taps->down_at_ms = now_ms;
            taps->start_x = x;
            taps->start_y = y;
            taps->moved = 0;
            taps->weakest = -1;
            taps->on_target = taps->tapped = taps->swiped = false;
        }
        int dx = x - taps->start_x, dy = y - taps->start_y;
        if (dx < 0) dx = -dx;
        if (dy < 0) dy = -dy;
        int far = dx > dy ? dx : dy;
        if (far > taps->moved) taps->moved = far;
        if (strength >= 0 && (taps->weakest < 0 || strength < taps->weakest)) taps->weakest = strength;
    } else if (taps->down) {
        taps->down = false;
        taps->up_at_ms = now_ms;
        taps->ending = true;
    }
    return over;
}

void panel_taps_pressed(panel_taps_t *taps, bool on_target)
{
    taps->on_target = on_target;
}

void panel_taps_released(panel_taps_t *taps, bool swiped)
{
    taps->swiped = swiped;
}

void panel_taps_clicked(panel_taps_t *taps)
{
    taps->tapped = true;
}

bool panel_taps_chip_parse(const uint8_t *config, size_t length, panel_taps_chip_t *out)
{
    *out = (panel_taps_chip_t){0};
    if (!config || length < PANEL_TAPS_CHIP_LENGTH) return false;
    /* The checksum makes the bytes before it add up to nought. */
    uint8_t sum = 0;
    for (size_t i = 0; i < PANEL_TAPS_CHIP_LENGTH; i++) sum += config[i];
    if (sum != 0) return false;
    out->known = true;
    out->version = (char)config[0x8047 - PANEL_TAPS_CHIP_START];
    out->touch_level = config[0x8053 - PANEL_TAPS_CHIP_START];
    out->leave_level = config[0x8054 - PANEL_TAPS_CHIP_START];
    /* Refresh_Rate: a report every 5 ms and the low four bits more. */
    out->report_ms = 5 + (config[0x8056 - PANEL_TAPS_CHIP_START] & 0x0F);
    return true;
}
