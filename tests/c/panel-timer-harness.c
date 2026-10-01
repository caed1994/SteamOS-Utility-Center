// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Drives the timer of the clock page and prints what it does. A test on
// this machine reads it.
//
// Commands on standard input, one to a line, each with the time in ms:
//
//   adjust <minutes>     panel_timer_adjust, prints "adjust yes|no"
//   start <ms>           panel_timer_start, prints "start yes|no"
//   pause <ms>           panel_timer_pause, prints "pause yes|no"
//   reset                panel_timer_reset
//   stop                 panel_timer_stop, prints "stop yes|no"
//   tick <ms>            panel_timer_tick, prints the news it gave, if any
//   show <ms>            prints "<phase> <left ms>"
//   ticks <from> <to> <step>   a tick every step ms, the news of each
//
// See tests/test_panel_timer.py.

#include <stdio.h>
#include <stdint.h>
#include <string.h>

#include "panel_timer.h"

static const char *names[] = {"idle", "running", "paused", "ringing"};

static void tick(panel_timer_t *timer, uint32_t now)
{
    panel_timer_news_t news = panel_timer_tick(timer, now);
    if (news.went_off) printf("%u went_off\n", (unsigned)now);
    if (news.beep) printf("%u beep\n", (unsigned)now);
    if (news.gave_up) printf("%u gave_up\n", (unsigned)now);
}

int main(void)
{
    panel_timer_t timer;
    panel_timer_init(&timer);
    char line[128];
    while (fgets(line, sizeof line, stdin)) {
        int minutes;
        unsigned now, to, step;
        if (sscanf(line, "adjust %d", &minutes) == 1) {
            printf("adjust %s\n", panel_timer_adjust(&timer, minutes) ? "yes" : "no");
        } else if (sscanf(line, "start %u", &now) == 1) {
            printf("start %s\n", panel_timer_start(&timer, now) ? "yes" : "no");
        } else if (sscanf(line, "pause %u", &now) == 1) {
            printf("pause %s\n", panel_timer_pause(&timer, now) ? "yes" : "no");
        } else if (strncmp(line, "reset", 5) == 0) {
            panel_timer_reset(&timer);
        } else if (strncmp(line, "stop", 4) == 0) {
            printf("stop %s\n", panel_timer_stop(&timer) ? "yes" : "no");
        } else if (sscanf(line, "ticks %u %u %u", &now, &to, &step) == 3) {
            for (uint32_t at = now; (int32_t)(to - at) >= 0; at += step) tick(&timer, at);
        } else if (sscanf(line, "tick %u", &now) == 1) {
            tick(&timer, now);
        } else if (sscanf(line, "show %u", &now) == 1) {
            printf("%s %u\n", names[timer.phase],
                   (unsigned)panel_timer_left_ms(&timer, now));
        }
    }
    return 0;
}
