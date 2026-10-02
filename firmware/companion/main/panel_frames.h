// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// How fast the frames come while something moves, for the page of the
// panel.
//
// Asked for: a measurement of the scroll on the panel itself, which its
// owner reads off the page of the panel. Without one, a change that is
// meant to make the scroll smooth has nothing to be checked against.
//
// Three moments of each frame go in. The refresh begins (begin), LVGL
// hands the last area of the frame to the panel (drawn), and the panel
// shows it (shown). The flush of the port waits there for the end of the
// frame on the glass, so shown is the moment the frame is on the screen.
//
// Two numbers come out of each frame:
//   interval   from the frame before it on the screen to this one
//   draw time  from begin to drawn: the work of the CPU for the frame
//
// Only frames in movement count. A frame more than PANEL_FRAMES_GAP_MS
// after the one before it is the first one after a rest, and its interval
// is the rest and not the movement. It counts as a start and nothing
// else.
//
// The spread of each number is kept in steps of a millisecond, so the
// mean, the 95th percentile and the most are there without a list of
// every frame. A step that fills up halves all the steps of its number:
// the shape stays and the count goes on.
//
// No ESP-IDF and no LVGL in here, so tests/test_panel_frames.py builds
// this file on the machine that runs the tests and asks it.
#pragma once

#include <stdbool.h>
#include <stdint.h>

// A millisecond to a step, and the last step holds that and more.
#define PANEL_FRAMES_BINS 128
// A frame later than this after the one before it starts a movement.
#define PANEL_FRAMES_GAP_MS 100

typedef struct {
    uint16_t bins[PANEL_FRAMES_BINS];
    uint64_t sum_us;
    uint32_t most_us;
} panel_frames_spread_t;

typedef struct {
    panel_frames_spread_t interval, draw;
    // The frames that counted.
    uint32_t counted;
    // The frame on its way, and the one on the screen. Nought for none.
    int64_t begun_us, drawn_us, shown_us;
    // Nothing counts while this is set.
    bool held;
} panel_frames_t;

// What the page shows. All nought while no frame counted.
typedef struct {
    uint32_t frames;
    int fps;
    int interval_mean_ms, interval_p95_ms, interval_most_ms;
    int draw_mean_ms, draw_p95_ms, draw_most_ms;
} panel_frame_stats_t;

// The one the firmware counts in. panel_display.c gives it the frames, and
// ui.c holds it while the page of the panel shows what it counted.
extern panel_frames_t panel_frames;

// Back to no frames, and not held.
void panel_frames_reset(panel_frames_t *frames);
// Held, no frame counts. Either way the next frame starts a movement.
void panel_frames_hold(panel_frames_t *frames, bool hold);
// The next frame starts a movement: the frames before it were not ones
// to count, like those of the startup animation.
void panel_frames_break(panel_frames_t *frames);

void panel_frames_begin(panel_frames_t *frames, int64_t now_us);
void panel_frames_drawn(panel_frames_t *frames, int64_t now_us);
void panel_frames_shown(panel_frames_t *frames, int64_t now_us);

void panel_frames_stats(const panel_frames_t *frames, panel_frame_stats_t *out);
