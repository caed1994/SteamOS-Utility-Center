// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    bool initialized, ready, raw, stable, down;
    uint32_t changed_ms, pressed_ms;
} panel_key_t;
/* The three times this works to. They are named because they were measured,
 * and because the measurement said something surprising: they matter far
 * less than how often panel_key_sample is called.
 *
 * The machine needs the level to read the same on two samples in a row, at
 * each edge. So the shortest press it can see is about twice the polling
 * period. At a steady 20 ms that is 40 ms and nobody notices. At 60 ms, a
 * press has to last 120 ms, and an ordinary tap does nothing at all.
 *
 * That was the fault on the board: a single press did nothing and a double
 * press worked. The poll was vTaskDelay(20) plus an I2C read on a bus that
 * the touch screen and the audio codec also use, so the real period was
 * whatever was left over. See panel_power.c, which now holds the rate.
 *
 * tests/test_panel_key.py sweeps press length against polling period and
 * holds both halves of this: an ordinary press is seen, and a contact
 * bounce is not. */
#define PANEL_KEY_SETTLE_MS 20
#define PANEL_KEY_SHORTEST_MS 40
#define PANEL_KEY_LONGEST_MS 1000

/* Return one event on release of a debounced short press.
 * Held-at-boot keys and held keys after a bus error must first be released. */
bool panel_key_sample(panel_key_t *key, bool pressed, uint32_t now_ms);
void panel_key_reset(panel_key_t *key);
