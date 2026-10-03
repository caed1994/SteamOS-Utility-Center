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
//   mode <mode>                prints the name of the mode, or "(none)"
//   body <room> <desktop> <game>
//                              prints the body of a change in that room, or
//                              "(empty)"; "-" is no key for that mode
#include <stdio.h>
#include <string.h>

#include "panel_led.h"

int main(void)
{
    char line[256], key[64], other[64], body[256];
    int mode, index, step, room;
    while (fgets(line, sizeof line, stdin)) {
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
        } else if (sscanf(line, "mode %d", &mode) == 1) {
            const char *name = panel_led_mode_name((panel_led_mode_t)mode);
            printf("%s\n", name ? name : "(none)");
        } else if (sscanf(line, "body %d %63s %63s", &room, key, other) == 3) {
            char keys[PANEL_LED_MODES][PANEL_LED_KEY];
            snprintf(keys[PANEL_LED_DESKTOP], PANEL_LED_KEY, "%.15s", strcmp(key, "-") ? key : "");
            snprintf(keys[PANEL_LED_GAME], PANEL_LED_KEY, "%.15s", strcmp(other, "-") ? other : "");
            if (room < 0 || room > (int)sizeof body) room = (int)sizeof body;
            size_t length = panel_led_body(body, (size_t)room, keys);
            printf("%s %zu\n", length ? body : "(empty)", length);
        } else {
            printf("?\n");
        }
    }
    return 0;
}
