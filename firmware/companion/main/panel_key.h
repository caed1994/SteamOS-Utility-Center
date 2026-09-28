// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    bool initialized, ready, raw, stable, down;
    uint32_t changed_ms, pressed_ms;
} panel_key_t;
/* Return one event on release of a debounced 60..1000 ms press.
 * Held-at-boot keys and held keys after a bus error must first be released. */
bool panel_key_sample(panel_key_t *key, bool pressed, uint32_t now_ms);
void panel_key_reset(panel_key_t *key);
