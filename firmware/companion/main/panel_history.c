// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// See panel_history.h.
#include "panel_history.h"

#include <string.h>

void panel_history_reset(panel_history_t *history)
{
    memset(history, 0, sizeof *history);
}

static int16_t reading(int value)
{
    if (value < 0) return PANEL_HISTORY_GAP;
    if (value > INT16_MAX) return INT16_MAX;
    return (int16_t)value;
}

void panel_history_offer(panel_history_t *history,
                         const int values[PANEL_HISTORY_SERIES])
{
    for (int i = 0; i < PANEL_HISTORY_SERIES; i++)
        history->newest[i] = reading(values[i]);
    history->have_newest = true;
}

static void push(panel_history_t *history, const int16_t *values)
{
    for (int i = 0; i < PANEL_HISTORY_SERIES; i++)
        history->points[i][history->next] = values ? values[i] : PANEL_HISTORY_GAP;
    history->next = (history->next + 1) % PANEL_HISTORY_POINTS;
    if (history->count < PANEL_HISTORY_POINTS) history->count++;
    history->version++;
}

bool panel_history_due(const panel_history_t *history, uint32_t now_ms)
{
    return !history->started || now_ms - history->step_began >= PANEL_HISTORY_STEP_MS;
}

bool panel_history_tick(panel_history_t *history, uint32_t now_ms)
{
    if (!history->started) {
        history->started = true;
        history->step_began = now_ms;
        return false;
    }
    // Unsigned, so the count of the milliseconds may wrap after 49 days.
    uint32_t passed = now_ms - history->step_began;
    if (passed < PANEL_HISTORY_STEP_MS) return false;
    uint32_t steps = passed / PANEL_HISTORY_STEP_MS;
    if (steps > PANEL_HISTORY_POINTS) {
        // Longer than the whole history: nothing in it is known any more.
        uint32_t version = history->version;
        panel_history_reset(history);
        history->started = true;
        history->step_began = now_ms;
        history->version = version + 1;
        return true;
    }
    push(history, history->have_newest ? history->newest : NULL);
    history->have_newest = false;
    for (uint32_t i = 1; i < steps; i++) push(history, NULL);
    history->step_began += steps * PANEL_HISTORY_STEP_MS;
    return true;
}

static int window_of(int minutes)
{
    long points = (long)minutes * 60L * 1000L / (long)PANEL_HISTORY_STEP_MS;
    if (points < 1) points = 1;
    if (points > PANEL_HISTORY_POINTS) points = PANEL_HISTORY_POINTS;
    return (int)points;
}

// The point `age` steps before the newest one, or a gap where there is none.
static int16_t aged(const panel_history_t *history, int series, int age)
{
    if (age < 0 || age >= history->count) return PANEL_HISTORY_GAP;
    int slot = (history->next - 1 - age + 2 * PANEL_HISTORY_POINTS) % PANEL_HISTORY_POINTS;
    return history->points[series][slot];
}

int panel_history_read(const panel_history_t *history,
                       panel_history_series_t series, int minutes,
                       int32_t *out, int out_count)
{
    if ((int)series < 0 || series >= PANEL_HISTORY_SERIES || out_count < 1) return 0;
    int window = window_of(minutes);
    int readings = 0;
    for (int part = 0; part < out_count; part++) {
        int first = (int)((long)window * part / out_count);
        int end = (int)((long)window * (part + 1) / out_count);
        long sum = 0;
        int found = 0;
        for (int k = first; k < end; k++) {
            int16_t value = aged(history, series, window - 1 - k);
            if (value == PANEL_HISTORY_GAP) continue;
            sum += value;
            found++;
        }
        // The readings are nought or more, so this rounds half up.
        out[part] = found ? (int32_t)((sum + found / 2) / found) : PANEL_HISTORY_GAP;
        readings += found;
    }
    return readings;
}

bool panel_history_range(const panel_history_t *history,
                         panel_history_series_t series, int minutes,
                         int *low, int *high)
{
    if ((int)series < 0 || series >= PANEL_HISTORY_SERIES) return false;
    int window = window_of(minutes);
    bool any = false;
    for (int age = 0; age < window; age++) {
        int16_t value = aged(history, series, age);
        if (value == PANEL_HISTORY_GAP) continue;
        if (!any || value < *low) *low = value;
        if (!any || value > *high) *high = value;
        any = true;
    }
    return any;
}
