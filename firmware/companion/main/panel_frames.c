// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// See panel_frames.h.
#include "panel_frames.h"

#include <string.h>

panel_frames_t panel_frames;

void panel_frames_reset(panel_frames_t *frames)
{
    memset(frames, 0, sizeof *frames);
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

void panel_frames_shown(panel_frames_t *frames, int64_t now_us)
{
    if (frames->held) return;
    bool whole = frames->begun_us && frames->drawn_us;
    if (whole && frames->shown_us &&
        now_us - frames->shown_us < (int64_t)PANEL_FRAMES_GAP_MS * 1000) {
        add(&frames->interval, now_us - frames->shown_us);
        add(&frames->draw, frames->drawn_us - frames->begun_us);
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
}
