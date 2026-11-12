// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Prints every word of the panel, in every language it offers, so that a
// test on this machine reads the tables that the board reads. See
// tests/test_panel_text.py.
//
// One line for each: language, id, and the text with its newlines written
// out, because a text of several lines is still one line here.
//
// Then the day and the date of panel_text_date: "date", language, weekday,
// day, month, room, and what it wrote. One line for each case below.
//
// With the argument "whole" it reads cases from its input, one a line: the
// size of the room and the bytes of a text in hex. For each it writes
// "same" or "copy", whether panel_text_is_whole holds, and the bytes of the
// text that panel_text_whole gave, in hex. A room of size nought is no room
// at all.

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "panel_text.h"

static void print_escaped(const char *text)
{
    for (; *text; text++) {
        if (*text == '\n') fputs("\\n", stdout);
        else if (*text == '\t') fputs("\\t", stdout);
        else putchar(*text);
    }
}

// The cases of panel_text_whole. The text and the room are memory of their
// exact size, so a tool that watches the memory sees a byte past either.
static int whole_cases(void)
{
    char line[1024];
    while (fgets(line, sizeof line, stdin)) {
        unsigned size = 0;
        int at = 0;
        if (sscanf(line, "%u %n", &size, &at) < 1) return 1;
        size_t length = 0;
        while (isxdigit((unsigned char)line[at + 2 * length]) &&
               isxdigit((unsigned char)line[at + 2 * length + 1])) length++;
        char *text = malloc(length + 1);
        char *room = size ? malloc(size) : NULL;
        if (!text || (size && !room)) return 1;
        for (size_t i = 0; i < length; i++) {
            unsigned byte = 0;
            sscanf(line + at + 2 * i, "%2x", &byte);
            text[i] = (char)byte;
        }
        text[length] = 0;
        if (room) memset(room, 'x', size);
        const char *got = panel_text_whole(text, room, size);
        printf("%s\t%d\t", got == text ? "same" : "copy", panel_text_is_whole(text));
        for (const char *c = got; *c; c++) printf("%02x", (unsigned char)*c);
        putchar('\n');
        free(text);
        free(room);
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc > 1 && strcmp(argv[1], "whole") == 0) return whole_cases();
    for (int language = 0; language < PANEL_LANGUAGE_COUNT; language++) {
        panel_text_set((panel_language_t)language);
        printf("name\t%d\t", language);
        print_escaped(panel_language_name((panel_language_t)language));
        putchar('\n');
        for (int id = 0; id < TXT_COUNT; id++) {
            printf("%d\t%d\t", language, id);
            print_escaped(panel_text((panel_text_id_t)id));
            putchar('\n');
        }
    }
    // The day and the date, in each language: an ordinary one, the two
    // ends of each range, each value just past them, and a room too small.
    static const int dates[][4] = {
        {4, 8, 10, 64}, {0, 1, 1, 64}, {6, 31, 12, 64}, {1, 3, 3, 64},
        {-1, 8, 10, 64}, {7, 8, 10, 64}, {4, 0, 10, 64}, {4, 32, 10, 64},
        {4, 8, 0, 64}, {4, 8, 13, 64}, {4, 8, 10, 9}, {4, 8, 10, 1},
    };
    for (int language = 0; language < PANEL_LANGUAGE_COUNT; language++) {
        panel_text_set((panel_language_t)language);
        for (size_t i = 0; i < sizeof dates / sizeof dates[0]; i++) {
            char out[64];
            memset(out, 'x', sizeof out);
            panel_text_date(out, (size_t)dates[i][3], dates[i][0], dates[i][1], dates[i][2]);
            printf("date\t%d\t%d\t%d\t%d\t%d\t", language, dates[i][0], dates[i][1],
                   dates[i][2], dates[i][3]);
            print_escaped(out);
            putchar('\n');
        }
    }
    // What an id outside the table answers with. A null pointer here is a
    // restart on the wall, because LVGL follows what it is given.
    panel_text_set(PANEL_ENGLISH);
    printf("range\t-1\t");
    print_escaped(panel_text((panel_text_id_t)-1));
    putchar('\n');
    printf("range\t%d\t", TXT_COUNT);
    print_escaped(panel_text((panel_text_id_t)TXT_COUNT));
    putchar('\n');
    return 0;
}
