// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// See panel_pages.h.
#include "panel_pages.h"

void panel_pages_order(uint32_t stored, uint8_t order[PANEL_PAGES])
{
    bool placed[PANEL_PAGES] = {false};
    int count = 0;
    for (int place = 0; place < PANEL_PAGE_PLACES && count < PANEL_PAGES; place++) {
        unsigned page = (stored >> (4 * place)) & 0xF;
        if (page >= PANEL_PAGES || placed[page]) continue;
        placed[page] = true;
        order[count++] = (uint8_t)page;
    }
    for (int page = 0; page < PANEL_PAGES; page++)
        if (!placed[page]) order[count++] = (uint8_t)page;
}

uint32_t panel_pages_pack(const uint8_t order[PANEL_PAGES])
{
    uint32_t stored = PANEL_PAGES_UNSET;
    for (int place = 0; place < PANEL_PAGES; place++) {
        stored &= ~(0xFu << (4 * place));
        stored |= (uint32_t)(order[place] & 0xF) << (4 * place);
    }
    return stored;
}

bool panel_pages_move(uint8_t order[PANEL_PAGES], int place, int step)
{
    int other = place + step;
    if (place < 0 || place >= PANEL_PAGES || other < 0 || other >= PANEL_PAGES ||
        (step != 1 && step != -1))
        return false;
    uint8_t page = order[place];
    order[place] = order[other];
    order[other] = page;
    return true;
}

int panel_pages_place(const uint8_t order[PANEL_PAGES], int page)
{
    for (int place = 0; place < PANEL_PAGES; place++)
        if (order[place] == page) return place;
    return -1;
}

/* A bit for each page this firmware has. */
#define ALL_PAGES ((1u << PANEL_PAGES) - 1)

uint32_t panel_pages_hidden(uint32_t stored)
{
    uint32_t hidden = stored & ALL_PAGES;
    return hidden == ALL_PAGES ? 0 : hidden;
}

bool panel_pages_toggle(uint32_t *hidden, int page)
{
    if (page < 0 || page >= PANEL_PAGES) return false;
    uint32_t next = *hidden ^ (1u << page);
    if ((next & ALL_PAGES) == ALL_PAGES) return false;
    *hidden = next;
    return true;
}

int panel_pages_shown(uint32_t hidden)
{
    int shown = 0;
    for (int page = 0; page < PANEL_PAGES; page++)
        if (!(hidden & (1u << page))) shown++;
    return shown;
}

int panel_pages_band_place(const uint8_t order[PANEL_PAGES], uint32_t hidden, int page)
{
    if (page < 0 || page >= PANEL_PAGES || (hidden & (1u << page))) return -1;
    int place = 0;
    for (int i = 0; i < PANEL_PAGES; i++) {
        if (order[i] == page) return place;
        if (!(hidden & (1u << order[i]))) place++;
    }
    return -1;
}

int panel_pages_band_page(const uint8_t order[PANEL_PAGES], uint32_t hidden, int place)
{
    int last = order[0];
    for (int i = 0; i < PANEL_PAGES; i++) {
        if (hidden & (1u << order[i])) continue;
        last = order[i];
        if (place-- <= 0) break;
    }
    return last;
}
