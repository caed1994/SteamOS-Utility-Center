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
 * The machine needs the level to hold for PANEL_KEY_SETTLE_MS at each edge.
 * So the shortest press it can see is about twice the polling period. At a
 * steady 20 ms that is 40 ms and nobody notices. At 60 ms, a press has to
 * last 120 ms, and an ordinary tap does nothing at all. panel_power.c holds
 * the rate for that reason.
 *
 * The rate was not why a single press did nothing and a double press
 * worked, although that was the first guess. With the rate held, the
 * health line read key_slowest=15 to 17 ms and the fault stayed. The level
 * of the pin was read the wrong way round. See panel_key_pressed.
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

/* Whether the key is down, out of the levels the expander read and the pin
 * of the key among them.
 *
 * High while pressed. The key does not reach the expander directly. On the
 * schematic of the 4B, PWR (Key3) takes PWRON of the AXP2101 to ground
 * through R10, and the same node drives the gate of T1, an N-channel MOSFET
 * (BSS138) through R16. The drain of T1 is EXIO4, with R11, 10k, to 3.3 V.
 * At rest the AXP2101 holds PWRON high with its own 100k pull-up, so T1
 * conducts and EXIO4 reads low. A press takes the gate to ground, T1 stops
 * conducting, and R11 pulls EXIO4 high.
 *
 * This was read the other way round, as low while pressed. Then the machine
 * took the gap between two presses for one press: a single press after a
 * pause came after a "press" longer than PANEL_KEY_LONGEST_MS and did
 * nothing, and the second press of a double press ended a "press" as long
 * as the gap between the two, which counted. That was the fault on the
 * board. tests/test_panel_key.py drives the machine with the level the
 * schematic gives, both ways round, and holds it. */
bool panel_key_pressed(uint32_t levels, uint32_t pin);
