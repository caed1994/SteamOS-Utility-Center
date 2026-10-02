// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// panel_history.c, asked line by line by tests/test_panel_history.py.
//
//   offer <cpu> <gpu> <watts>    a reading of an answer of the PC
//   tick <ms>                    the clock; prints 1 when a point came
//   read <series> <min> <count>  prints the points and the readings
//   range <series> <min>         prints the lowest and the highest
//   state                        prints the count and the version
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "panel_history.h"

static panel_history_t history;

int main(void)
{
    panel_history_reset(&history);
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        char word[16];
        if (sscanf(line, "%15s", word) != 1) continue;
        if (strcmp(word, "offer") == 0) {
            int values[PANEL_HISTORY_SERIES];
            if (sscanf(line, "%*s %d %d %d", &values[0], &values[1], &values[2]) != 3) return 2;
            panel_history_offer(&history, values);
        } else if (strcmp(word, "tick") == 0) {
            unsigned long ms;
            if (sscanf(line, "%*s %lu", &ms) != 1) return 2;
            printf("%d\n", panel_history_tick(&history, (uint32_t)ms) ? 1 : 0);
        } else if (strcmp(word, "read") == 0) {
            int series, minutes, count;
            if (sscanf(line, "%*s %d %d %d", &series, &minutes, &count) != 3) return 2;
            int32_t *out = calloc((size_t)count, sizeof *out);
            if (!out) return 3;
            int readings = panel_history_read(&history, (panel_history_series_t)series,
                                              minutes, out, count);
            for (int i = 0; i < count; i++) {
                if (out[i] == PANEL_HISTORY_GAP) printf("gap ");
                else printf("%ld ", (long)out[i]);
            }
            printf("| %d\n", readings);
            free(out);
        } else if (strcmp(word, "range") == 0) {
            int series, minutes, low = 0, high = 0;
            if (sscanf(line, "%*s %d %d", &series, &minutes) != 2) return 2;
            if (panel_history_range(&history, (panel_history_series_t)series, minutes, &low, &high))
                printf("%d %d\n", low, high);
            else
                printf("none\n");
        } else if (strcmp(word, "state") == 0) {
            printf("%d %lu\n", history.count, (unsigned long)history.version);
        } else {
            return 2;
        }
        fflush(stdout);
    }
    return 0;
}
