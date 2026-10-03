// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// See panel_frames.h.
#include "panel_frames.h"

#include <string.h>

panel_frames_t panel_frames;

void panel_frames_reset(panel_frames_t *frames)
{
    int64_t period_us = frames->period_us;
    memset(frames, 0, sizeof *frames);
    frames->period_us = period_us;
}

void panel_frames_break(panel_frames_t *frames)
{
    frames->begun_us = frames->drawn_us = frames->shown_us = 0;
}

void panel_frames_hold(panel_frames_t *frames, bool hold)
{
    frames->held = hold;
    panel_frames_break(frames);
}

void panel_frames_period(panel_frames_t *frames, int64_t period_us)
{
    if (period_us < 0) period_us = 0;
    if (period_us == frames->period_us) return;
    frames->period_us = period_us;
    panel_frames_break(frames);
}

void panel_frames_begin(panel_frames_t *frames, int64_t now_us)
{
    frames->begun_us = now_us;
    frames->drawn_us = 0;
}

/* A frame counts with all three moments, so a drawn with no begin before
 * it counts for nothing: panel_frames_shown asks for both. */
void panel_frames_drawn(panel_frames_t *frames, int64_t now_us)
{
    frames->drawn_us = now_us;
}

static void add(panel_frames_spread_t *spread, int64_t us)
{
    if (us < 0) us = 0;
    int64_t ms = us / 1000;
    int bin = ms < PANEL_FRAMES_BINS - 1 ? (int)ms : PANEL_FRAMES_BINS - 1;
    if (spread->bins[bin] == UINT16_MAX)
        for (int i = 0; i < PANEL_FRAMES_BINS; i++) spread->bins[i] /= 2;
    spread->bins[bin]++;
    spread->sum_us += (uint64_t)us;
    if (us > spread->most_us) spread->most_us = (uint32_t)us;
}

/* The periods of the panel in an interval, to the nearest whole one: the
 * frames come at the ends of periods, a little late at times, never
 * between. One at the least, and the last count for four and more. */
static int periods(int64_t interval_us, int64_t period_us)
{
    int64_t taken = (interval_us + period_us / 2) / period_us;
    if (taken < 1) return 1;
    return taken < PANEL_FRAMES_PERIODS ? (int)taken : PANEL_FRAMES_PERIODS;
}

void panel_frames_shown(panel_frames_t *frames, int64_t now_us)
{
    if (frames->held) return;
    bool whole = frames->begun_us && frames->drawn_us;
    int64_t interval_us = now_us - frames->shown_us;
    if (whole && frames->shown_us && interval_us < (int64_t)PANEL_FRAMES_GAP_MS * 1000) {
        add(&frames->interval, interval_us);
        add(&frames->draw, frames->drawn_us - frames->begun_us);
        add(&frames->lead, frames->begun_us - frames->shown_us);
        if (frames->period_us)
            frames->periods[periods(interval_us, frames->period_us) - 1]++;
        frames->counted++;
    }
    frames->shown_us = now_us;
    frames->begun_us = frames->drawn_us = 0;
}

/* The step at which 95 frames of a hundred are in, or fewer. */
static int p95(const panel_frames_spread_t *spread)
{
    uint32_t total = 0;
    for (int i = 0; i < PANEL_FRAMES_BINS; i++) total += spread->bins[i];
    uint32_t wanted = (total * 95 + 99) / 100, seen = 0;
    for (int i = 0; i < PANEL_FRAMES_BINS; i++) {
        seen += spread->bins[i];
        if (seen >= wanted) return i;
    }
    return PANEL_FRAMES_BINS - 1;
}

/* Whole milliseconds, as the steps count them, so that the mean, the
 * 95th percentile and the most of a number read alike. */
static int to_ms(uint64_t us)
{
    return (int)(us / 1000);
}

/* Whole percent that add up to a hundred: each share rounded down, and the
 * points left over to the shares that lost the most by it, the first of
 * equals first. */
static void shares(const uint32_t *counts, int *out)
{
    uint64_t total = 0, lost[PANEL_FRAMES_PERIODS];
    for (int i = 0; i < PANEL_FRAMES_PERIODS; i++) total += counts[i];
    if (!total) return;
    int given = 0;
    for (int i = 0; i < PANEL_FRAMES_PERIODS; i++) {
        out[i] = (int)((uint64_t)counts[i] * 100 / total);
        lost[i] = (uint64_t)counts[i] * 100 % total;
        given += out[i];
    }
    for (; given < 100; given++) {
        int most = 0;
        for (int i = 1; i < PANEL_FRAMES_PERIODS; i++)
            if (lost[i] > lost[most]) most = i;
        out[most]++;
        lost[most] = 0;
    }
}

void panel_frames_stats(const panel_frames_t *frames, panel_frame_stats_t *out)
{
    memset(out, 0, sizeof *out);
    if (!frames->counted) return;
    out->frames = frames->counted;
    const panel_frames_spread_t *interval = &frames->interval, *draw = &frames->draw;
    if (interval->sum_us)
        out->fps = (int)(((uint64_t)frames->counted * 1000000u + interval->sum_us / 2) /
                         interval->sum_us);
    out->interval_mean_ms = to_ms(interval->sum_us / frames->counted);
    out->interval_p95_ms = p95(interval);
    out->interval_most_ms = to_ms(interval->most_us);
    out->draw_mean_ms = to_ms(draw->sum_us / frames->counted);
    out->draw_p95_ms = p95(draw);
    out->draw_most_ms = to_ms(draw->most_us);
    const panel_frames_spread_t *lead = &frames->lead;
    out->lead_mean_ms = to_ms(lead->sum_us / frames->counted);
    out->lead_p95_ms = p95(lead);
    out->lead_most_ms = to_ms(lead->most_us);
    shares(frames->periods, out->periods_pct);
}
