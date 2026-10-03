// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// panel_cpu.c, asked line by line by tests/test_panel_cpu.py.
//
//   key <profile>              prints the key of the profile, or "(none)"
//   find <key>                 prints the place of the key, or -1; the key
//                              (null) asks for a null pointer
//   name <profile>             prints the number of the text of its name,
//                              or "(none)" for the text of no name
//   body <room> <profile>      prints the body of a change in that room and
//                              its length, or "(empty) 0"; "(half) 0" for a
//                              room left with text in it, and "(written) 0"
//                              for a room of nought that the call wrote to
#include <stdio.h>
#include <string.h>

#include "panel_cpu.h"

int main(void)
{
    char line[256], key[64], body[256];
    int profile, room;
    while (fgets(line, sizeof line, stdin)) {
        if (sscanf(line, "key %d", &profile) == 1) {
            const char *found = panel_cpu_key(profile);
            printf("%s\n", found ? found : "(none)");
        } else if (sscanf(line, "find %63s", key) == 1) {
            printf("%d\n", panel_cpu_find(strcmp(key, "(null)") ? key : NULL));
        } else if (sscanf(line, "name %d", &profile) == 1) {
            panel_text_id_t name = panel_cpu_name(profile);
            if (name == TXT_LED_UNKNOWN) printf("(none)\n");
            else printf("%d\n", (int)name);
        } else if (sscanf(line, "body %d %d", &room, &profile) == 2) {
            if (room < 0 || room > (int)sizeof body) room = (int)sizeof body;
            memset(body, 'x', sizeof body - 1);
            body[sizeof body - 1] = 0;
            size_t length = panel_cpu_body(body, (size_t)room, profile);
            if (length) printf("%s %zu\n", body, length);
            else if (room == 0) printf("%s 0\n", body[0] == 'x' ? "(empty)" : "(written)");
            else printf("%s 0\n", body[0] ? "(half)" : "(empty)");
        } else {
            printf("?\n");
        }
    }
    return 0;
}
