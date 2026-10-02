// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The history of the temperatures and the power, for the page of the card.
//
// One point every five seconds, for each of three series: the processor,
// the card, and the power of the card. A point is the newest reading of the
// PC that came in during its five seconds. A step with no answer of the PC
// is a gap, and the curve on the screen breaks there and does not draw a
// line across the time it knows nothing about.
//
// The panel keeps an hour. The page shows the last 15, 30 or 60 minutes, as
// was asked: 15 to 30, and the hour is the room above that. A restart of the
// panel starts the history again; the PC keeps none.
//
// No ESP-IDF and no LVGL in here, so tests/test_panel_history.py builds this
// file on the machine that runs the tests and asks it.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define PANEL_HISTORY_STEP_MS 5000u
#define PANEL_HISTORY_POINTS 720
// The points the screen draws for any window. 15 minutes are 180 points,
// and the longer windows are their mean, two or four to one.
#define PANEL_HISTORY_DRAWN 180
// A point with no reading.
#define PANEL_HISTORY_GAP INT16_MIN

typedef enum {
    PANEL_HISTORY_CPU,
    PANEL_HISTORY_GPU,
    PANEL_HISTORY_WATTS,
    PANEL_HISTORY_SERIES
} panel_history_series_t;

typedef struct {
    int16_t points[PANEL_HISTORY_SERIES][PANEL_HISTORY_POINTS];
    // The slot of the next point, and how many points there are.
    int next, count;
    // When the step that runs now began, in the milliseconds of the caller.
    uint32_t step_began;
    bool started;
    // The newest reading of the step that runs now, if one came.
    int16_t newest[PANEL_HISTORY_SERIES];
    bool have_newest;
    // Counts the points, so the screen knows when to draw again.
    uint32_t version;
    // Room for the screen: the points of the window it draws, which the
    // chart reads in place. ui.c fills it with panel_history_read. Here
    // and not in ui.c, so it is in PSRAM with the rest.
    int32_t drawn[PANEL_HISTORY_SERIES][PANEL_HISTORY_DRAWN];
} panel_history_t;

void panel_history_reset(panel_history_t *history);

// A reading of an answer of the PC: degrees, degrees and watts. A value
// below nought is a sensor that said nothing, and a gap in that series.
void panel_history_offer(panel_history_t *history,
                         const int values[PANEL_HISTORY_SERIES]);

// Whether a step is over, or the clock has not started. main.c reads the
// state only then while the display sleeps.
bool panel_history_due(const panel_history_t *history, uint32_t now_ms);

// The clock. Ends each step that is over: the first with the newest
// reading of it, or a gap, and any more with a gap. true when it added a
// point. A clock that jumps by more than the whole history clears it.
bool panel_history_tick(panel_history_t *history, uint32_t now_ms);

// The last `minutes` of one series, oldest first, as `out_count` points:
// the mean of the readings of each part, or PANEL_HISTORY_GAP for a part
// with none. The time before the first point is a gap too. Answers the
// number of points with a reading.
int panel_history_read(const panel_history_t *history,
                       panel_history_series_t series, int minutes,
                       int32_t *out, int out_count);

// The lowest and the highest reading of one series in the last `minutes`.
// false when there is none.
bool panel_history_range(const panel_history_t *history,
                         panel_history_series_t series, int minutes,
                         int *low, int *high);
