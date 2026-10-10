// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_led.h"

#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

/* An effect: its key, its name, and whether it draws in the desktop colour
 * and in the desktop brightness. */
typedef struct {
    const char *key;
    panel_text_id_t name;
    bool coloured;
    bool lit;
} effect_t;

/* desktop.SCENES of the LED service, in its order. */
static const effect_t desktop[] = {
    {"steam", TXT_LED_STEAM, false, false},
    {"off", TXT_LED_OFF, false, false},
    {"color", TXT_LED_COLOR, true, true},
    {"breath", TXT_LED_BREATH, true, true},
    {"patrol", TXT_LED_PATROL, true, true},
    {"rainbow", TXT_LED_RAINBOW, false, true},
    {"fire", TXT_LED_FIRE, false, true},
    {"aurora", TXT_LED_AURORA, false, true},
    {"ooze", TXT_LED_OOZE, false, true},
    {"temperature", TXT_LED_TEMPERATURE, false, true},
    {"load", TXT_LED_LOAD, false, false},
};

/* render.RAINBOW_CHOICES of the LED service, in its order. */
static const effect_t game[] = {
    {"rainbow", TXT_LED_RAINBOW, false, false},
    {"temperature", TXT_LED_TEMPERATURE, false, false},
    {"load", TXT_LED_LOAD, false, false},
    {"fire", TXT_LED_FIRE, false, false},
    {"aurora", TXT_LED_AURORA, false, false},
    {"ooze", TXT_LED_OOZE, false, false},
    {"mirror", TXT_LED_MIRROR, false, false},
};

/* screen.STATES of the LED service, and the line of each one. "idle" is a
 * bar on a different effect of Steam, so its line is the line of the other
 * effects. */
static const struct {
    const char *state;
    panel_text_id_t text;
} mirror_lines[] = {
    {"off", TXT_MIRROR_OFF},
    {"idle", TXT_LED_GAME_WHAT},
    {"no-gstreamer", TXT_MIRROR_NO_GSTREAMER},
    {"no-plugin", TXT_MIRROR_NO_PLUGIN},
    {"no-screen", TXT_MIRROR_NO_SCREEN},
    {"busy", TXT_MIRROR_BUSY},
    {"starting", TXT_MIRROR_STARTING},
    {"waiting", TXT_MIRROR_WAITING},
    {"running", TXT_MIRROR_RUNNING},
    {"failed", TXT_MIRROR_FAILED},
    {"gone", TXT_MIRROR_GONE},
};

/* companion.LED_COLOURS, in its order. */
static const struct {
    const char *key;
    panel_text_id_t name;
} colours[PANEL_LED_COLOURS] = {
    {"#ff0000", TXT_COLOUR_RED},
    {"#ff8000", TXT_COLOUR_ORANGE},
    {"#ffff00", TXT_COLOUR_YELLOW},
    {"#00ff00", TXT_COLOUR_GREEN},
    {"#00ffff", TXT_COLOUR_CYAN},
    {"#0000ff", TXT_COLOUR_BLUE},
    {"#8000ff", TXT_COLOUR_PURPLE},
    {"#ff00ff", TXT_COLOUR_MAGENTA},
    {"#ffffff", TXT_COLOUR_WHITE},
};

/* screen.PROFILES, in its order. */
static const struct {
    const char *key;
    panel_text_id_t name;
} profiles[PANEL_LED_PROFILES] = {
    {"cinematic", TXT_PROFILE_CINEMATIC},
    {"pop", TXT_PROFILE_POP},
    {"solid", TXT_PROFILE_SOLID},
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

bool panel_led_lit(panel_led_mode_t mode, int index)
{
    int count;
    const effect_t *list = effects(mode, &count);
    return index >= 0 && index < count && list[index].lit;
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

const char *panel_led_colour(int index)
{
    return index >= 0 && index < PANEL_LED_COLOURS ? colours[index].key : NULL;
}

int panel_led_colour_find(const char *colour)
{
    for (int i = 0; colour && i < PANEL_LED_COLOURS; i++)
        if (strcmp(colours[i].key, colour) == 0) return i;
    return -1;
}

panel_text_id_t panel_led_colour_name(int index)
{
    return index >= 0 && index < PANEL_LED_COLOURS ? colours[index].name : TXT_COLOUR_OWN;
}

const char *panel_led_profile(int index)
{
    return index >= 0 && index < PANEL_LED_PROFILES ? profiles[index].key : NULL;
}

int panel_led_profile_find(const char *key)
{
    for (int i = 0; key && i < PANEL_LED_PROFILES; i++)
        if (strcmp(profiles[i].key, key) == 0) return i;
    return -1;
}

panel_text_id_t panel_led_profile_name(int index)
{
    return index >= 0 && index < PANEL_LED_PROFILES ? profiles[index].name : TXT_LED_UNKNOWN;
}

bool panel_led_rgb(const char *colour, uint32_t *rgb)
{
    if (!colour || colour[0] != '#' || strlen(colour) != 7) return false;
    uint32_t value = 0;
    for (int i = 1; i < 7; i++) {
        char c = colour[i];
        int digit = c >= '0' && c <= '9' ? c - '0'
                  : c >= 'a' && c <= 'f' ? c - 'a' + 10
                  : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (digit < 0) return false;
        value = value << 4 | (uint32_t)digit;
    }
    if (rgb) *rgb = value;
    return true;
}

int panel_led_percent(int brightness)
{
    if (brightness < 0) brightness = 0;
    if (brightness > 255) brightness = 255;
    return (brightness * 100 + 127) / 255;
}

int panel_led_brightness(int percent)
{
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    return (percent * 255 + 50) / 100;
}

/* One more field of a body at "*at", after a comma where a field stands
 * before it. false when the room ends. A field ends before the last byte
 * of the room, so the comma always has a place, and the field after it
 * does not fit when the comma takes that byte. */
static bool add(char *out, size_t room, size_t *at, const char *format, ...)
{
    if (*at > 1) out[(*at)++] = ',';
    va_list args;
    va_start(args, format);
    int wrote = vsnprintf(out + *at, room - *at, format, args);
    va_end(args);
    if (wrote < 0 || (size_t)wrote >= room - *at) return false;
    *at += (size_t)wrote;
    return true;
}

size_t panel_led_body(char *out, size_t room, const panel_led_change_t *change)
{
    if (!out || room == 0) return 0;
    out[0] = 0;
    if (!change || room < 3) return 0;
    /* What goes into the object between quotes or as a number must be what
     * the service reads, so a body is never half an object. */
    if (change->colour[0] && !panel_led_rgb(change->colour, NULL)) return 0;
    if (change->brightness > 255) return 0;
    if (change->profile[0] && panel_led_profile_find(change->profile) < 0) return 0;
    size_t at = 0;
    out[at++] = '{';
    for (int mode = 0; mode < PANEL_LED_MODES; mode++) {
        if (!change->effect[mode][0]) continue;
        if (!add(out, room, &at, "\"%s\":\"%s\"", panel_led_mode_name((panel_led_mode_t)mode),
                 change->effect[mode])) { out[0] = 0; return 0; }
    }
    if (change->colour[0]
        && !add(out, room, &at, "\"%s\":\"%s\"", PANEL_LED_COLOUR_KEY, change->colour)) {
        out[0] = 0;
        return 0;
    }
    if (change->brightness >= 0
        && !add(out, room, &at, "\"%s\":%d", PANEL_LED_BRIGHTNESS_KEY, change->brightness)) {
        out[0] = 0;
        return 0;
    }
    if (change->profile[0]
        && !add(out, room, &at, "\"%s\":\"%s\"", PANEL_LED_PROFILE_KEY, change->profile)) {
        out[0] = 0;
        return 0;
    }
    if (at == 1 || at + 2 > room) { out[0] = 0; return 0; }
    out[at++] = '}';
    out[at] = 0;
    return at;
}

void panel_led_mirror_line(char *out, size_t room, const panel_led_mirror_t *mirror)
{
    if (!out || !room) return;
    out[0] = '\0';
    panel_text_id_t text = TXT_LED_GAME_WHAT;
    for (size_t i = 0; mirror && i < sizeof mirror_lines / sizeof mirror_lines[0]; i++)
        if (strcmp(mirror->state, mirror_lines[i].state) == 0) text = mirror_lines[i].text;
    switch (text) {
    case TXT_MIRROR_RUNNING:
        /* The rate and the load, and the size of the screen where the PC
         * knows it. A status with no numbers says only that it runs. */
        if (mirror->fps >= 0 && mirror->cpu >= 0) {
            int used = snprintf(out, room, panel_text(TXT_MIRROR_RUNNING), mirror->fps,
                                mirror->cpu / 10, mirror->cpu % 10);
            if (mirror->source[0] && used > 0 && (size_t)used < room)
                snprintf(out + used, room - (size_t)used, ", %s", mirror->source);
        } else {
            snprintf(out, room, "%s", panel_text(TXT_MIRROR_RUNS));
        }
        break;
    case TXT_MIRROR_BUSY:
    case TXT_MIRROR_NO_PLUGIN:
    case TXT_MIRROR_FAILED:
        snprintf(out, room, panel_text(text), mirror->detail[0] ? mirror->detail : "?");
        break;
    default:
        snprintf(out, room, "%s", panel_text(text));
        break;
    }
}
