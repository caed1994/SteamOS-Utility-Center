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
//
//   panel-key pin <poll period ms> <high|low> <start ms> <length ms> ...
//
// The same, for presses as EXIO4 carries them on the board: high while the
// key is pressed, low at rest. "high" reads the pin with panel_key_pressed,
// as panel_power.c does. "low" reads it the other way round, as panel_power.c
// did before. The run starts at 0 with the key up, unless a press starts at 0.
//
//   panel-key level <levels> <pin>
//
// panel_key_pressed for those two, both in hex. Prints 1 or 0.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>

#include "panel_key.h"

// EXIO4, as panel_power.c asks for it.
#define PIN (1u << 4)
#define MOST_PRESSES 16

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

static int press_pin(const uint32_t *start, const uint32_t *length, int count,
                     bool as_before, uint32_t phase, uint32_t period)
{
    panel_key_t key;
    panel_key_reset(&key);
    uint32_t end = 0;
    for (int i = 0; i < count; i++)
        if (start[i] + length[i] > end) end = start[i] + length[i];
    int events = 0;
    for (uint32_t at = phase; at < end + 3000; at += period) {
        // The other pins of the expander read high, so only EXIO4 may count.
        uint32_t levels = 0xFFu & ~PIN;
        for (int i = 0; i < count; i++)
            if (at >= start[i] && at < start[i] + length[i]) levels |= PIN;
        bool pressed = panel_key_pressed(levels, PIN);
        if (as_before) pressed = !pressed;
        if (panel_key_sample(&key, pressed, at)) events++;
    }
    return events;
}

static int usage(const char *name)
{
    fprintf(stderr,
            "usage: %s <poll period ms> <hold ms>\n"
            "       %s pin <poll period ms> <high|low> <start ms> <length ms> ...\n"
            "       %s level <levels> <pin>\n",
            name, name, name);
    return 2;
}

int main(int argc, char **argv)
{
    if (argc == 4 && strcmp(argv[1], "level") == 0) {
        uint32_t levels = (uint32_t)strtoul(argv[2], NULL, 16);
        uint32_t pin = (uint32_t)strtoul(argv[3], NULL, 16);
        printf("%d\n", panel_key_pressed(levels, pin) ? 1 : 0);
        return 0;
    }
    if (argc >= 6 && strcmp(argv[1], "pin") == 0) {
        uint32_t period = (uint32_t)strtoul(argv[2], NULL, 10);
        bool as_before = strcmp(argv[3], "low") == 0;
        if (period == 0 || (!as_before && strcmp(argv[3], "high") != 0)) return usage(argv[0]);
        if ((argc - 4) % 2 != 0 || (argc - 4) / 2 > MOST_PRESSES) return usage(argv[0]);
        uint32_t start[MOST_PRESSES], length[MOST_PRESSES];
        int count = (argc - 4) / 2;
        for (int i = 0; i < count; i++) {
            start[i] = (uint32_t)strtoul(argv[4 + 2 * i], NULL, 10);
            length[i] = (uint32_t)strtoul(argv[5 + 2 * i], NULL, 10);
        }
        int lowest = -1, highest = -1;
        for (uint32_t phase = 0; phase < period; phase++) {
            int n = press_pin(start, length, count, as_before, phase, period);
            if (lowest < 0 || n < lowest) lowest = n;
            if (n > highest) highest = n;
        }
        printf("%d %d\n", lowest, highest);
        return 0;
    }
    if (argc != 3) return usage(argv[0]);
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
