// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// panel_frames.c, asked line by line by tests/test_panel_frames.py.
//
//   frame <begun> <drawn> <shown>   one frame, the three moments in us
//   begin <us> | drawn <us> | shown <us>
//                                   one moment alone
//   hold <0|1>                      panel_frames_hold
//   break                           panel_frames_break
//   reset                           panel_frames_reset
//   period <us>                     panel_frames_period
//   stats                           the numbers of the page, on one line:
//                                   the frames, the rate, the interval,
//                                   the draw time and the lead time (each
//                                   mean, 95 % and most), and the shares
//                                   of one to four and more periods
#include <stdio.h>
#include <string.h>

#include "panel_frames.h"

int main(void)
{
    panel_frames_t frames;
    panel_frames_reset(&frames);
    char line[128];
    while (fgets(line, sizeof line, stdin)) {
        long long a, b, c;
        int on;
        if (sscanf(line, "frame %lld %lld %lld", &a, &b, &c) == 3) {
            panel_frames_begin(&frames, a);
            panel_frames_drawn(&frames, b);
            panel_frames_shown(&frames, c);
        } else if (sscanf(line, "begin %lld", &a) == 1) {
            panel_frames_begin(&frames, a);
        } else if (sscanf(line, "drawn %lld", &a) == 1) {
            panel_frames_drawn(&frames, a);
        } else if (sscanf(line, "shown %lld", &a) == 1) {
            panel_frames_shown(&frames, a);
        } else if (sscanf(line, "period %lld", &a) == 1) {
            panel_frames_period(&frames, a);
        } else if (sscanf(line, "hold %d", &on) == 1) {
            panel_frames_hold(&frames, on != 0);
        } else if (strncmp(line, "break", 5) == 0) {
            panel_frames_break(&frames);
        } else if (strncmp(line, "reset", 5) == 0) {
            panel_frames_reset(&frames);
        } else if (strncmp(line, "stats", 5) == 0) {
            panel_frame_stats_t s;
            panel_frames_stats(&frames, &s);
            printf("%u %d %d %d %d %d %d %d %d %d %d %d %d %d %d\n", (unsigned)s.frames, s.fps,
                   s.interval_mean_ms, s.interval_p95_ms, s.interval_most_ms,
                   s.draw_mean_ms, s.draw_p95_ms, s.draw_most_ms,
                   s.lead_mean_ms, s.lead_p95_ms, s.lead_most_ms,
                   s.periods_pct[0], s.periods_pct[1], s.periods_pct[2], s.periods_pct[3]);
        } else {
            return 2;
        }
        fflush(stdout);
    }
    return 0;
}
