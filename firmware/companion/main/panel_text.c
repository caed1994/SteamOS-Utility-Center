// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later

#include "panel_text.h"

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
