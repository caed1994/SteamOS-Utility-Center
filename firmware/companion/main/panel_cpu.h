// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The energy profiles of the CPU of the PC, for the page of the CPU.
//
// A profile is a governor and a preference together, and the PC decides what
// each one is on its own machine: see power.PROFILES on its side. The panel
// knows the names and the order, and the status says which of them the
// machine offers. "steamos" is no setting: SteamOS has the CPU again at the
// next start of the PC.
//
// tests/test_panel_cpu.py holds the keys here equal to the profiles of
// power.py, in the same order.
#pragma once

#include <stddef.h>

#include "panel_text.h"

typedef enum {
    PANEL_CPU_POWERSAVE, PANEL_CPU_BALANCED, PANEL_CPU_PERFORMANCE,
    PANEL_CPU_STEAMOS, PANEL_CPU_PROFILES
} panel_cpu_profile_t;

/* The room for a key and its end. The longest is "performance". */
#define PANEL_CPU_KEY 16

/* The key of a profile, or NULL for one outside the list. */
const char *panel_cpu_key(int profile);
/* The profile of a key, or -1 for "custom" and for a key that this firmware
 * does not know. */
int panel_cpu_find(const char *key);
/* The name of a profile on the screen. */
panel_text_id_t panel_cpu_name(int profile);
/* The body of a change for the companion service: {"profile":"balanced"}.
 * Answers the length, and nought for a profile outside the list or for too
 * little room. */
size_t panel_cpu_body(char *out, size_t room, int profile);
