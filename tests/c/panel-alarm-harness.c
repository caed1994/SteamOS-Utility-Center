// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Drives the alarm clock of the clock page and prints what it does. A test
// on this machine reads it.
//
// Commands on standard input, one to a line:
//
//   init <on> <hour> <minute> <days>    panel_alarm_init
//   set <on> <hour> <minute> <days>     panel_alarm_change at the clock
//   clock <day> <weekday> <h> <m> <s>   the local time, and the clock known
//   unknown                             a clock that nobody set
//   ms <ms>                             the millisecond count
//   tick                                one tick, prints its news, if any
//   walk <seconds> <step ms>            a tick every step, the clock and the
//                                       count going on together; prints the
//                                       time of each "went_off" and
//                                       "gave_up", and then "beeps <count>"
//   snooze                              prints "snooze yes|no"
//   off                                 prints "off yes|no"
//   next                                prints "next none" or
//                                       "next <weekday> <hh>:<mm>"
//   show                                prints "<phase> <on> <h> <m> <days>"
//   pack <on> <hour> <minute> <days>    prints the stored number in hex
//   unpack <hex>                        prints "<on> <h> <m> <days>"
//
// See tests/test_panel_alarm.py.

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "panel_alarm.h"

static panel_alarm_t wake;
static panel_alarm_clock_t clock_now;
static uint32_t now_ms;
// What the clock has of a second that it did not count yet.
static uint32_t part;

static const char *const phases[] = {"waiting", "ringing", "snoozing"};

static void step_clock(uint32_t ms)
{
    part += ms;
    while (part >= 1000) {
        part -= 1000;
        if (++clock_now.second < 60) continue;
        clock_now.second = 0;
        if (++clock_now.minute < 60) continue;
        clock_now.minute = 0;
        if (++clock_now.hour < 24) continue;
        clock_now.hour = 0;
        clock_now.day++;
        clock_now.weekday = (uint8_t)((clock_now.weekday + 1) % 7);
    }
}

static void stamp(const char *what)
{
    printf("%s %d %02d:%02d:%02d\n", what, (int)clock_now.day, clock_now.hour,
           clock_now.minute, clock_now.second);
}

int main(void)
{
    char line[256];
    panel_alarm_init(&wake, panel_alarm_default());
    while (fgets(line, sizeof line, stdin)) {
        char word[32] = "";
        long a = 0, b = 0, c = 0, d = 0, e = 0;
        int got = sscanf(line, "%31s %li %li %li %li %li", word, &a, &b, &c, &d, &e);
        if (got <= 0) continue;
        panel_alarm_set_t set = {.on = a != 0, .hour = (uint8_t)b, .minute = (uint8_t)c,
                                 .days = (uint8_t)d};
        if (!strcmp(word, "init")) {
            panel_alarm_init(&wake, set);
        } else if (!strcmp(word, "set")) {
            panel_alarm_change(&wake, set, &clock_now);
        } else if (!strcmp(word, "clock")) {
            part = 0;
            clock_now = (panel_alarm_clock_t){.known = true, .day = (int32_t)a,
                                              .weekday = (uint8_t)b, .hour = (uint8_t)c,
                                              .minute = (uint8_t)d, .second = (uint8_t)e};
        } else if (!strcmp(word, "unknown")) {
            clock_now.known = false;
        } else if (!strcmp(word, "ms")) {
            now_ms = (uint32_t)strtoul(line + 3, NULL, 0);
        } else if (!strcmp(word, "tick")) {
            panel_alarm_news_t news = panel_alarm_tick(&wake, &clock_now, now_ms);
            if (news.went_off) puts("went_off");
            if (news.beep) puts("beep");
            if (news.gave_up) puts("gave_up");
        } else if (!strcmp(word, "walk")) {
            long beeps = 0;
            for (long gone = 0; gone < a * 1000; gone += b) {
                now_ms += (uint32_t)b;
                step_clock((uint32_t)b);
                panel_alarm_news_t news = panel_alarm_tick(&wake, &clock_now, now_ms);
                if (news.went_off) stamp("went_off");
                if (news.gave_up) stamp("gave_up");
                if (news.beep) beeps++;
            }
            printf("beeps %ld\n", beeps);
        } else if (!strcmp(word, "snooze")) {
            printf("snooze %s\n", panel_alarm_snooze(&wake, now_ms) ? "yes" : "no");
        } else if (!strcmp(word, "off")) {
            printf("off %s\n", panel_alarm_off(&wake) ? "yes" : "no");
        } else if (!strcmp(word, "next")) {
            panel_alarm_next_t next = panel_alarm_next(&wake, &clock_now, now_ms);
            if (!next.due) puts("next none");
            else printf("next %d %02d:%02d\n", next.weekday, next.hour, next.minute);
        } else if (!strcmp(word, "show")) {
            printf("%s %d %d %d %d\n", phases[wake.phase], wake.set.on, wake.set.hour,
                   wake.set.minute, wake.set.days);
        } else if (!strcmp(word, "pack")) {
            printf("%08lx\n", (unsigned long)panel_alarm_pack(set));
        } else if (!strcmp(word, "unpack")) {
            panel_alarm_set_t back = panel_alarm_unpack((uint32_t)strtoul(line + 7, NULL, 16));
            printf("%d %d %d %d\n", back.on, back.hour, back.minute, back.days);
        } else {
            fprintf(stderr, "unknown command: %s", line);
            return 2;
        }
        fflush(stdout);
    }
    return 0;
}
