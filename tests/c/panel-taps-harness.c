// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// panel_taps.c, asked line by line by tests/test_panel_taps.py.
//
//   reset                      back to nothing counted
//   hold <0|1>                 holds the count, or lets it go
//   break                      the reads stop and start again
//   read <ms> <ok> <down> <x> <y> <strength>
//                              one read of the controller; prints the press
//                              that was over at it as
//                              "<end> <ms> <moved> <weakest>", or "-"
//   pressed <0|1>              LVGL: a press on something that takes a tap
//   released <0|1>             LVGL: the release, and whether it scrolled
//   clicked                    LVGL: a tap
//   counts                     prints presses, taps, swipes, lost, late,
//                              errors, the longest gap, the shortest press,
//                              the weakest contact and whether it is held
//   chip <hex>                 the configuration out of those bytes; prints
//                              "<version> <touch> <leave> <report ms>", or
//                              "unknown"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "panel_taps.h"

int main(void)
{
    static char line[4096];
    static const char *const ends[] = {"nothing", "tap", "swipe", "lost"};
    panel_taps_t taps;
    panel_taps_reset(&taps);
    while (fgets(line, sizeof line, stdin)) {
        unsigned ms;
        int ok, down, x, y, strength, flag;
        char hex[1024];
        if (strncmp(line, "reset", 5) == 0) {
            panel_taps_reset(&taps);
            printf("ok\n");
        } else if (strncmp(line, "break", 5) == 0) {
            panel_taps_break(&taps);
            printf("ok\n");
        } else if (sscanf(line, "hold %d", &flag) == 1) {
            panel_taps_hold(&taps, flag != 0);
            printf("ok\n");
        } else if (sscanf(line, "read %u %d %d %d %d %d", &ms, &ok, &down, &x, &y, &strength) == 6) {
            panel_taps_press_t done;
            if (panel_taps_read(&taps, ms, ok != 0, down != 0, x, y, strength, &done))
                printf("%s %u %d %d\n", ends[done.end], (unsigned)done.ms, done.moved, done.weakest);
            else
                printf("-\n");
        } else if (sscanf(line, "pressed %d", &flag) == 1) {
            panel_taps_pressed(&taps, flag != 0);
            printf("ok\n");
        } else if (sscanf(line, "released %d", &flag) == 1) {
            panel_taps_released(&taps, flag != 0);
            printf("ok\n");
        } else if (strncmp(line, "clicked", 7) == 0) {
            panel_taps_clicked(&taps);
            printf("ok\n");
        } else if (strncmp(line, "counts", 6) == 0) {
            printf("%u %u %u %u %u %u %u %u %d %d\n", (unsigned)taps.presses, (unsigned)taps.taps,
                   (unsigned)taps.swipes, (unsigned)taps.lost, (unsigned)taps.late,
                   (unsigned)taps.errors, (unsigned)taps.longest_gap_ms,
                   (unsigned)taps.shortest_ms, taps.weakest_ever, taps.held ? 1 : 0);
        } else if (sscanf(line, "chip %1023s", hex) == 1) {
            uint8_t bytes[512];
            size_t length = strlen(hex) / 2;
            if (length > sizeof bytes) length = sizeof bytes;
            for (size_t i = 0; i < length; i++) {
                char pair[3] = {hex[2 * i], hex[2 * i + 1], 0};
                bytes[i] = (uint8_t)strtoul(pair, NULL, 16);
            }
            panel_taps_chip_t chip;
            if (panel_taps_chip_parse(bytes, length, &chip) && chip.known)
                printf("%c %d %d %d\n", chip.version, chip.touch_level, chip.leave_level,
                       chip.report_ms);
            else
                printf("unknown\n");
        } else {
            printf("?\n");
        }
    }
    return 0;
}
