// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// panel_led.c, asked line by line by tests/test_panel_led.py. A mode is 0
// for the desktop and 1 for Game Mode.
//
//   count <mode>               prints how many effects the mode has
//   key <mode> <index>         prints the key there, or "(none)"
//   find <mode> <key>          prints the place of the key, or -1
//   step <mode> <index> <step> prints the place of the effect it steps to
//   coloured <mode> <index>    prints 1 or 0
//   lit <mode> <index>         prints 1 or 0
//   mode <mode>                prints the name of the mode, or "(none)"
//   colour <index>             prints the colour there, or "(none)"
//   colourfind <colour>        prints the place of the colour, or -1; the
//                              colour (null) asks for a null pointer
//   colourname <index>         prints the number of the text of its name,
//                              or "own" for the text of a colour of its own
//   rgb <text>                 prints the colour as six hex digits, or
//                              "(none)"
//   percent <brightness>       prints the brightness as a per cent
//   brightness <percent>       prints the per cent as a brightness
//   body <room> <desktop> <game> [<colour> <brightness>]
//                              prints the body of a change in that room and
//                              its length, or "(empty) 0"; "-" is no key for
//                              that mode and no colour, and a brightness
//                              below nought is none. "(half) 0" is a room
//                              left with text in it, and "(written) 0" a
//                              room of nought that the call wrote to
//   profile <index>            prints the profile there, or "(none)"
//   profilefind <key>          prints the place of the profile, or -1
//   profilename <index> <language>
//                              prints the name of the profile, in English
//                              for 0 and German for 1
//   bodyp <room> <game> <profile>
//                              prints the body of a change of the effect of
//                              Game Mode and of the profile, as body does
//   merge <room> <desktop> <game> <colour> <brightness> <profile>
//         <desktop> <game> <colour> <brightness> <profile>
//                              merges the two changes, the first and then the
//                              second, into an empty one, and prints its
//                              body as body does; "-" is no value
//   mirror <room> <language> <fps> <cpu> <state> <source> <detail>
//                              prints the line of the mirror in a room of
//                              that size, in English for 0 and German for
//                              1; "-" is an empty text, and the detail is
//                              the rest of the line
#include <stdio.h>
#include <string.h>

#include "panel_led.h"

static void fill(panel_led_change_t *change, const char *desktop, const char *game,
                 const char *colour, int brightness, const char *profile)
{
    *change = (panel_led_change_t){.brightness = brightness};
    snprintf(change->effect[PANEL_LED_DESKTOP], PANEL_LED_KEY, "%.15s", strcmp(desktop, "-") ? desktop : "");
    snprintf(change->effect[PANEL_LED_GAME], PANEL_LED_KEY, "%.15s", strcmp(game, "-") ? game : "");
    snprintf(change->colour, PANEL_LED_COLOUR, "%.7s", strcmp(colour, "-") ? colour : "");
    snprintf(change->profile, PANEL_LED_KEY, "%.15s", strcmp(profile, "-") ? profile : "");
}

int main(void)
{
    char line[256], key[64], other[64], colour[64], body[256];
    int mode, index, step, room, level;
    while (fgets(line, sizeof line, stdin)) {
        int got;
        if (sscanf(line, "count %d", &mode) == 1) {
            printf("%d\n", panel_led_count((panel_led_mode_t)mode));
        } else if (sscanf(line, "key %d %d", &mode, &index) == 2) {
            const char *found = panel_led_key((panel_led_mode_t)mode, index);
            printf("%s\n", found ? found : "(none)");
        } else if (sscanf(line, "find %d %63s", &mode, key) == 2) {
            printf("%d\n", panel_led_find((panel_led_mode_t)mode, key));
        } else if (sscanf(line, "step %d %d %d", &mode, &index, &step) == 3) {
            printf("%d\n", panel_led_step((panel_led_mode_t)mode, index, step));
        } else if (sscanf(line, "coloured %d %d", &mode, &index) == 2) {
            printf("%d\n", panel_led_coloured((panel_led_mode_t)mode, index) ? 1 : 0);
        } else if (sscanf(line, "lit %d %d", &mode, &index) == 2) {
            printf("%d\n", panel_led_lit((panel_led_mode_t)mode, index) ? 1 : 0);
        } else if (sscanf(line, "mode %d", &mode) == 1) {
            const char *name = panel_led_mode_name((panel_led_mode_t)mode);
            printf("%s\n", name ? name : "(none)");
        } else if (sscanf(line, "colourfind %63s", key) == 1) {
            printf("%d\n", panel_led_colour_find(strcmp(key, "(null)") ? key : NULL));
        } else if (sscanf(line, "colourname %d", &index) == 1) {
            panel_text_id_t name = panel_led_colour_name(index);
            if (name == TXT_COLOUR_OWN) printf("own\n");
            else printf("%d\n", (int)name);
        } else if (sscanf(line, "colour %d", &index) == 1) {
            const char *found = panel_led_colour(index);
            printf("%s\n", found ? found : "(none)");
        } else if (sscanf(line, "rgb %63s", key) == 1) {
            uint32_t rgb = 0xDEAD;
            if (panel_led_rgb(key, &rgb)) printf("%06x\n", (unsigned)rgb);
            else printf("(none)%s\n", rgb == 0xDEAD ? "" : " but written");
        } else if (sscanf(line, "percent %d", &level) == 1) {
            printf("%d\n", panel_led_percent(level));
        } else if (sscanf(line, "brightness %d", &level) == 1) {
            printf("%d\n", panel_led_brightness(level));
        } else if ((got = sscanf(line, "body %d %63s %63s %63s %d", &room, key, other, colour,
                                 &level)) == 3 || got == 5) {
            panel_led_change_t change = {.brightness = got == 5 ? level : -1};
            snprintf(change.effect[PANEL_LED_DESKTOP], PANEL_LED_KEY, "%.15s", strcmp(key, "-") ? key : "");
            snprintf(change.effect[PANEL_LED_GAME], PANEL_LED_KEY, "%.15s", strcmp(other, "-") ? other : "");
            if (got == 5)
                snprintf(change.colour, PANEL_LED_COLOUR, "%.7s", strcmp(colour, "-") ? colour : "");
            if (room < 0 || room > (int)sizeof body) room = (int)sizeof body;
            memset(body, 'x', sizeof body - 1);
            body[sizeof body - 1] = 0;
            size_t length = panel_led_body(body, (size_t)room, &change);
            if (length) printf("%s %zu\n", body, length);
            else if (room == 0) printf("%s 0\n", body[0] == 'x' ? "(empty)" : "(written)");
            else printf("%s 0\n", body[0] ? "(half)" : "(empty)");
        } else if (sscanf(line, "profilefind %63s", key) == 1) {
            printf("%d\n", panel_led_profile_find(key));
        } else if (sscanf(line, "profilename %d %d", &index, &level) == 2) {
            panel_text_set(level ? PANEL_GERMAN : PANEL_ENGLISH);
            printf("%s\n", panel_text(panel_led_profile_name(index)));
        } else if (sscanf(line, "profile %d", &index) == 1) {
            const char *found = panel_led_profile(index);
            printf("%s\n", found ? found : "(none)");
        } else if (strncmp(line, "merge ", 6) == 0) {
            char d[2][16], g[2][16], c[2][8], p[2][16];
            int b[2];
            if (sscanf(line, "merge %d %15s %15s %7s %d %15s %15s %15s %7s %d %15s", &room, d[0], g[0],
                       c[0], &b[0], p[0], d[1], g[1], c[1], &b[1], p[1]) != 11) {
                printf("?\n");
                continue;
            }
            panel_led_change_t into = {.brightness = -1}, one;
            for (int i = 0; i < 2; i++) {
                fill(&one, d[i], g[i], c[i], b[i], p[i]);
                panel_led_merge(&into, &one);
            }
            if (room < 0 || room > (int)sizeof body) room = (int)sizeof body;
            size_t length = panel_led_body(body, (size_t)room, &into);
            printf("%s %zu\n", length ? body : "(empty)", length);
        } else if (sscanf(line, "bodyp %d %63s %63s", &room, other, key) == 3) {
            panel_led_change_t change = {.brightness = -1};
            snprintf(change.effect[PANEL_LED_GAME], PANEL_LED_KEY, "%.15s", strcmp(other, "-") ? other : "");
            snprintf(change.profile, PANEL_LED_KEY, "%.15s", strcmp(key, "-") ? key : "");
            if (room < 0 || room > (int)sizeof body) room = (int)sizeof body;
            size_t length = panel_led_body(body, (size_t)room, &change);
            printf("%s %zu\n", length ? body : "(empty)", length);
        } else if (sscanf(line, "mirror %d %d %d %d %63s %63s %n", &room, &level, &index, &step, key, other,
                          &got) == 6) {
            panel_led_mirror_t mirror = {.fps = index, .cpu = step};
            char *detail = line + got;
            detail[strcspn(detail, "\n")] = 0;
            snprintf(mirror.state, sizeof mirror.state, "%.15s", strcmp(key, "-") ? key : "");
            snprintf(mirror.source, sizeof mirror.source, "%.11s", strcmp(other, "-") ? other : "");
            snprintf(mirror.detail, sizeof mirror.detail, "%.40s", strcmp(detail, "-") ? detail : "");
            panel_text_set(level ? PANEL_GERMAN : PANEL_ENGLISH);
            if (room < 1 || room > (int)sizeof body) room = (int)sizeof body;
            panel_led_mirror_line(body, (size_t)room, &mirror);
            printf("%s\n", body);
        } else {
            printf("?\n");
        }
    }
    return 0;
}
