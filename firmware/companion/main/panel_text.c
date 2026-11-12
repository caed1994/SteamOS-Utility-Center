// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later

#include "panel_text.h"

#include <stdio.h>

#define PANEL_TEXT_AS_ENGLISH(name, english, german) english,
#define PANEL_TEXT_AS_GERMAN(name, english, german) german,

static const char *const ENGLISH[TXT_COUNT] = {
    PANEL_TEXTS(PANEL_TEXT_AS_ENGLISH)
};

static const char *const GERMAN[TXT_COUNT] = {
    PANEL_TEXTS(PANEL_TEXT_AS_GERMAN)
};

static const char *const *const TABLES[PANEL_LANGUAGE_COUNT] = {
    ENGLISH, GERMAN
};

static const char *const NAMES[PANEL_LANGUAGE_COUNT] = {
    "English", "Deutsch"
};

static panel_language_t chosen = PANEL_ENGLISH;

const char *panel_text(panel_text_id_t id)
{
    // Out of range answers with something and never with a null pointer.
    // LVGL follows what it is given, and a restart in front of the person
    // using the panel is a worse answer than the wrong word.
    if (id < 0 || id >= TXT_COUNT) return "";
    return TABLES[chosen][id];
}

void panel_text_set(panel_language_t language)
{
    if (language < 0 || language >= PANEL_LANGUAGE_COUNT) return;
    chosen = language;
}

panel_language_t panel_text_language(void)
{
    return chosen;
}

const char *panel_language_name(panel_language_t language)
{
    if (language < 0 || language >= PANEL_LANGUAGE_COUNT) return "";
    return NAMES[language];
}

void panel_text_date(char *out, size_t room, int weekday, int day, int month)
{
    if (!out || room == 0) return;
    out[0] = 0;
    if (weekday < 0 || weekday > 6 || day < 1 || day > 31 || month < 1 || month > 12) return;
    snprintf(out, room, panel_text(TXT_DATE_FORMAT),
             panel_text((panel_text_id_t)(TXT_SUNDAY + weekday)), day,
             panel_text((panel_text_id_t)(TXT_JANUARY + month - 1)));
}

// How many bytes the character has that starts with this byte, as LVGL
// counts them (lv_text_encoded_size), and nought for a byte that starts
// none.
static size_t character_bytes(unsigned char first)
{
    if (first < 0x80) return 1;
    if ((first & 0xE0) == 0xC0) return 2;
    if ((first & 0xF0) == 0xE0) return 3;
    if ((first & 0xF8) == 0xF0) return 4;
    return 0;
}

// The bytes of the whole character at the start of the text, or nought.
// The end of the text is no byte of a character, so a cut character is not
// whole.
static size_t whole_character(const char *text)
{
    size_t bytes = character_bytes((unsigned char)text[0]);
    for (size_t i = 1; i < bytes; i++)
        if (((unsigned char)text[i] & 0xC0) != 0x80) return 0;
    return bytes;
}

bool panel_text_is_whole(const char *text)
{
    if (!text) return true;
    while (*text) {
        size_t bytes = whole_character(text);
        if (!bytes) return false;
        text += bytes;
    }
    return true;
}

const char *panel_text_whole(const char *text, char *room, size_t size)
{
    if (!text) return "";
    if (panel_text_is_whole(text)) return text;
    if (!room || size == 0) return "";
    size_t used = 0;
    while (*text) {
        size_t bytes = whole_character(text);
        if (bytes) {
            if (used + bytes >= size) break;
            for (size_t i = 0; i < bytes; i++) room[used++] = *text++;
            continue;
        }
        // The start of a character that the end of the text cuts goes. Each
        // other byte that is no part of a whole character shows as '?'.
        size_t rest = 1;
        while (((unsigned char)text[rest] & 0xC0) == 0x80) rest++;
        if (!text[rest] && rest < character_bytes((unsigned char)text[0])) break;
        if (used + 1 >= size) break;
        room[used++] = '?';
        text++;
    }
    room[used] = 0;
    return room;
}
