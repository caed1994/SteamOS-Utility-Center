// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_led.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    const char *key;
    panel_text_id_t name;
    bool coloured;
} effect_t;

/* desktop.SCENES of the LED service, in its order. */
static const effect_t desktop[] = {
    {"steam", TXT_LED_STEAM, false},
    {"off", TXT_LED_OFF, false},
    {"color", TXT_LED_COLOR, true},
    {"breath", TXT_LED_BREATH, true},
    {"patrol", TXT_LED_PATROL, true},
    {"rainbow", TXT_LED_RAINBOW, false},
    {"fire", TXT_LED_FIRE, false},
    {"aurora", TXT_LED_AURORA, false},
    {"ooze", TXT_LED_OOZE, false},
    {"temperature", TXT_LED_TEMPERATURE, false},
    {"load", TXT_LED_LOAD, false},
};

/* render.RAINBOW_CHOICES of the LED service, in its order. */
static const effect_t game[] = {
    {"rainbow", TXT_LED_RAINBOW, false},
    {"temperature", TXT_LED_TEMPERATURE, false},
    {"load", TXT_LED_LOAD, false},
    {"fire", TXT_LED_FIRE, false},
    {"aurora", TXT_LED_AURORA, false},
    {"ooze", TXT_LED_OOZE, false},
};

static const effect_t *effects(panel_led_mode_t mode, int *count)
{
    if (mode == PANEL_LED_DESKTOP) {
        *count = (int)(sizeof desktop / sizeof desktop[0]);
        return desktop;
    }
    if (mode == PANEL_LED_GAME) {
        *count = (int)(sizeof game / sizeof game[0]);
        return game;
    }
    *count = 0;
    return NULL;
}

int panel_led_count(panel_led_mode_t mode)
{
    int count;
    effects(mode, &count);
    return count;
}

const char *panel_led_key(panel_led_mode_t mode, int index)
{
    int count;
    const effect_t *list = effects(mode, &count);
    return index >= 0 && index < count ? list[index].key : NULL;
}

int panel_led_find(panel_led_mode_t mode, const char *key)
{
    int count;
    const effect_t *list = effects(mode, &count);
    for (int i = 0; key && i < count; i++)
        if (strcmp(list[i].key, key) == 0) return i;
    return -1;
}

panel_text_id_t panel_led_name(panel_led_mode_t mode, int index)
{
    int count;
    const effect_t *list = effects(mode, &count);
    /* A place outside the list has no name, and the screen shows "--" for
     * it. The text of the dash is in the table so that this answers a
     * text and never a null pointer. */
    return index >= 0 && index < count ? list[index].name : TXT_LED_UNKNOWN;
}

bool panel_led_coloured(panel_led_mode_t mode, int index)
{
    int count;
    const effect_t *list = effects(mode, &count);
    return index >= 0 && index < count && list[index].coloured;
}

int panel_led_step(panel_led_mode_t mode, int index, int step)
{
    int count = panel_led_count(mode);
    if (count == 0) return -1;
    if (index < 0 || index >= count) return step < 0 ? count - 1 : 0;
    return ((index + step) % count + count) % count;
}

const char *panel_led_mode_name(panel_led_mode_t mode)
{
    static const char *const names[PANEL_LED_MODES] = {"desktop", "game"};
    return mode >= 0 && mode < PANEL_LED_MODES ? names[mode] : NULL;
}

size_t panel_led_body(char *out, size_t room, const char keys[PANEL_LED_MODES][PANEL_LED_KEY])
{
    if (!out || room < 3) return 0;
    size_t at = 0;
    out[at++] = '{';
    for (int mode = 0; mode < PANEL_LED_MODES; mode++) {
        if (!keys[mode][0]) continue;
        int wrote = snprintf(out + at, room - at, "%s\"%s\":\"%s\"", at > 1 ? "," : "",
                             panel_led_mode_name((panel_led_mode_t)mode), keys[mode]);
        if (wrote < 0 || (size_t)wrote >= room - at) { out[0] = 0; return 0; }
        at += (size_t)wrote;
    }
    if (at == 1 || at + 2 > room) { out[0] = 0; return 0; }
    out[at++] = '}';
    out[at] = 0;
    return at;
}
