// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_theme.h"

#include <stdbool.h>

/* A theme, without its accent. */
typedef struct {
    panel_text_id_t name;
    uint32_t bg, card, edge, text, muted, button;
    uint32_t knob, knob_edge;
    /* The knob of a slider in the accent, and not in the colour of the knob
     * of a switch: a white knob on a white card is the half of a knob that
     * stands on the track. */
    bool slider_knob_in_accent;
    uint32_t red, danger, danger_edge, online, offline;
    uint32_t curve_cpu, curve_gpu, curve_watts;
} theme_t;

static const theme_t themes[PANEL_THEMES] = {
    /* The panel as it always was. Each number here was a number in ui.c,
     * and tests/test_panel_theme.py holds them to it. */
    {
        .name = TXT_THEME_DARK,
        .bg = 0x0C1721, .card = 0x111F2B, .edge = 0x293D51,
        .text = 0xEDF4FC, .muted = 0xAEC4DE, .button = 0x1B2B3C,
        .knob = 0xEDF4FC, .knob_edge = 0xEDF4FC, .slider_knob_in_accent = false,
        .red = 0xF06B79, .danger = 0x2C202B, .danger_edge = 0xA54757,
        .online = 0x70C256, .offline = 0x60758A,
        .curve_cpu = 0x49A8F7, .curve_gpu = 0xF5A25D, .curve_watts = 0x70C256,
    },
    /* The same page in daylight: white cards on a pale page with the blue
     * cast of the dark one, and the text in the navy of its page. The
     * contrasts match the dark theme's: the border of a card stands off
     * the card as far, and a button off its card. */
    {
        .name = TXT_THEME_LIGHT,
        .bg = 0xE8EDF2, .card = 0xFFFFFF, .edge = 0xCBD5E0,
        .text = 0x15212D, .muted = 0x52667A, .button = 0xF1F4F8,
        .knob = 0xFFFFFF, .knob_edge = 0x9AA8B7, .slider_knob_in_accent = true,
        .red = 0xC62F3F, .danger = 0xFCECEE, .danger_edge = 0xE6A3AB,
        .online = 0x3A9A4B, .offline = 0x7F8FA0,
        .curve_cpu = 0x1F6FD1, .curve_gpu = 0xC9601A, .curve_watts = 0x2E8B45,
    },
};

/* An accent in one theme: its face, its words, and the words on its face.
 * See panel_palette_t. */
typedef struct {
    uint32_t face, words, on;
} tone_t;

/* The dark tones are bright enough for the words on them to be in the
 * colour of the page, and they read as words on a dark card as they are.
 *
 * The light ones are deep enough for white words on them and for words in
 * them on a white card, and the face and the words are one tone. Not cyan,
 * green, yellow and orange: deep enough for that, the four are a petrol, a
 * forest, a brown and a rust, and the row of the eight is four bright ones
 * and four dark ones. Their faces are lighter, with the dark text on them,
 * and their words are the deep tone. */
#define ON_DARK 0x0C1721
#define ON_LIGHT 0x15212D
static const struct {
    panel_text_id_t name;
    tone_t tone[PANEL_THEMES];
} accents[PANEL_ACCENTS] = {
    {TXT_COLOUR_BLUE, {{0x49A8F7, 0x49A8F7, ON_DARK}, {0x176DCF, 0x176DCF, 0xFFFFFF}}},
    {TXT_COLOUR_CYAN, {{0x3CC6D6, 0x3CC6D6, ON_DARK}, {0x14A3B5, 0x007987, ON_LIGHT}}},
    {TXT_COLOUR_GREEN, {{0x5CC46B, 0x5CC46B, ON_DARK}, {0x30A452, 0x257E3B, ON_LIGHT}}},
    {TXT_COLOUR_YELLOW, {{0xF2C94C, 0xF2C94C, ON_DARK}, {0xC88800, 0x8C6900, ON_LIGHT}}},
    {TXT_COLOUR_ORANGE, {{0xF5994A, 0xF5994A, ON_DARK}, {0xE2741A, 0xB35207, ON_LIGHT}}},
    {TXT_COLOUR_RED, {{0xF46B63, 0xF46B63, ON_DARK}, {0xD42531, 0xD42531, 0xFFFFFF}}},
    {TXT_COLOUR_MAGENTA, {{0xE76BD8, 0xE76BD8, ON_DARK}, {0xBA2FAE, 0xBA2FAE, 0xFFFFFF}}},
    {TXT_COLOUR_PURPLE, {{0xA88BF8, 0xA88BF8, ON_DARK}, {0x8350DA, 0x8350DA, 0xFFFFFF}}},
};

static int theme_of(int theme)
{
    return theme >= 0 && theme < PANEL_THEMES ? theme : PANEL_THEME_DARK;
}

static int accent_of(int accent)
{
    return accent >= 0 && accent < PANEL_ACCENTS ? accent : PANEL_ACCENT_BLUE;
}

panel_palette_t panel_palette(int theme, int accent)
{
    theme = theme_of(theme);
    const theme_t *t = &themes[theme];
    const tone_t *tone = &accents[accent_of(accent)].tone[theme];
    return (panel_palette_t){
        .bg = t->bg, .card = t->card, .edge = t->edge,
        .text = t->text, .muted = t->muted, .button = t->button,
        .accent = tone->face, .accent_text = tone->words, .on_accent = tone->on,
        .knob = t->knob, .knob_edge = t->knob_edge,
        .slider_knob = t->slider_knob_in_accent ? tone->face : t->knob,
        .red = t->red, .danger = t->danger, .danger_edge = t->danger_edge,
        .online = t->online, .offline = t->offline,
        .curve_cpu = t->curve_cpu, .curve_gpu = t->curve_gpu, .curve_watts = t->curve_watts,
    };
}

panel_text_id_t panel_accent_name(int accent)
{
    return accents[accent_of(accent)].name;
}

panel_text_id_t panel_theme_name(int theme)
{
    return themes[theme_of(theme)].name;
}
