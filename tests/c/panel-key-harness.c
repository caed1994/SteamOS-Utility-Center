// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Prints what the PWRKEY state machine does with one press, for each length
// of press and each polling period. A test on this machine reads it.
//
//   panel-key <poll period ms> <hold ms>
//
// It prints the lowest number of events over every phase of the poll. The
// phase matters: a person does not press in time with the loop, so the
// answer that counts is the worst one. See tests/test_panel_key.py.

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdint.h>

#include "panel_key.h"

static int press_once(uint32_t hold, uint32_t start, uint32_t period)
{
    panel_key_t key;
    panel_key_reset(&key);
    int events = 0;
    // Far past the release, so a late event is still counted.
    for (uint32_t at = 0; at < start + hold + 3000; at += period) {
        bool down = (at >= start) && (at < start + hold);
        if (panel_key_sample(&key, down, at)) events++;
    }
    return events;
}

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: %s <poll period ms> <hold ms>\n", argv[0]);
        return 2;
    }
    uint32_t period = (uint32_t)strtoul(argv[1], NULL, 10);
    uint32_t hold = (uint32_t)strtoul(argv[2], NULL, 10);
    if (period == 0) return 2;

    int lowest = -1, highest = -1;
    for (uint32_t phase = 0; phase < period; phase++) {
        // 1000 ms in, so the gate that waits for a released key has opened.
        int n = press_once(hold, 1000 + phase, period);
        if (lowest < 0 || n < lowest) lowest = n;
        if (n > highest) highest = n;
    }
    printf("%d %d\n", lowest, highest);
    return 0;
}
