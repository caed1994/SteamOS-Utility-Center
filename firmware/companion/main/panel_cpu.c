// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_cpu.h"

#include <stdio.h>
#include <string.h>

/* power.profiles of the PC, in its order: the three from the least power to
 * the most, and then "steamos". */
static const struct {
    const char *key;
    panel_text_id_t name;
} profiles[PANEL_CPU_PROFILES] = {
    {"powersave", TXT_CPU_POWERSAVE},
    {"balanced", TXT_CPU_BALANCED},
    {"performance", TXT_CPU_PERFORMANCE},
    {"steamos", TXT_CPU_STEAMOS},
};

const char *panel_cpu_key(int profile)
{
    return profile >= 0 && profile < PANEL_CPU_PROFILES ? profiles[profile].key : NULL;
}

int panel_cpu_find(const char *key)
{
    for (int i = 0; key && i < PANEL_CPU_PROFILES; i++)
        if (strcmp(profiles[i].key, key) == 0) return i;
    return -1;
}

panel_text_id_t panel_cpu_name(int profile)
{
    /* A place outside the list has no name. The dash of the LED bar is the
     * text for that, so this answers a text and never a null pointer. */
    return profile >= 0 && profile < PANEL_CPU_PROFILES ? profiles[profile].name : TXT_LED_UNKNOWN;
}

size_t panel_cpu_body(char *out, size_t room, int profile)
{
    const char *key = panel_cpu_key(profile);
    if (!out || room == 0) return 0;
    out[0] = 0;
    if (!key) return 0;
    int wrote = snprintf(out, room, "{\"profile\":\"%s\"}", key);
    if (wrote < 0 || (size_t)wrote >= room) { out[0] = 0; return 0; }
    return (size_t)wrote;
}
