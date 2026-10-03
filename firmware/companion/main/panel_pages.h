// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The order of the pages of the band, which somebody can change.
//
// A page is its number, in the order the firmware builds them. The order
// is a place for each page, and it is stored as one number: four bits for
// each place, the first place in the lowest four bits, and room for eight
// places. A place nobody holds is 0xF.
//
// A stored order is read with care, because a firmware of another day
// wrote it. A page that this firmware does not have is left out, a page
// that comes twice counts once, and a page the stored order does not name
// comes at the end, in the order of the firmware. So an update that adds
// a page keeps the order somebody chose, and puts the new page last.
//
// A page can also be hidden. Then it keeps its place in the order and is
// not in the band: the pages that are shown stand next to each other, in
// the order, and the first of them is the start page. The hidden pages are
// stored as a number of their own, a bit for each page, bit 0 for
// PANEL_PAGE_CONTROLS. One page at the least is always shown.
//
// No ESP-IDF and no LVGL in here, so tests/test_panel_pages_order.py
// builds this file on the machine that runs the tests and asks it.
#pragma once

#include <stdbool.h>
#include <stdint.h>

// The pages, in the order the firmware builds them, and how many. A new
// page goes at the end: a stored order names each page by this number, and
// a page that took the number of another would take its place too.
typedef enum {
    PANEL_PAGE_CONTROLS,
    PANEL_PAGE_SESSION,
    PANEL_PAGE_PLAYING,
    PANEL_PAGE_CLOCK,
    PANEL_PAGE_CARD,
    PANEL_PAGE_LED,
    PANEL_PAGE_CPU,
    PANEL_PAGES
} panel_page_t;

// Room for this many places in the stored number.
#define PANEL_PAGE_PLACES 8
// The stored number of a panel where nobody chose an order.
#define PANEL_PAGES_UNSET 0xFFFFFFFFu

_Static_assert(PANEL_PAGES <= PANEL_PAGE_PLACES, "more pages than the stored number holds");

// The page at each place, out of a stored number.
void panel_pages_order(uint32_t stored, uint8_t order[PANEL_PAGES]);

// The stored number of an order.
uint32_t panel_pages_pack(const uint8_t order[PANEL_PAGES]);

// The page at that place one place up (step -1) or down (step 1), and the
// page there in its place. false at an end, where nothing moves.
bool panel_pages_move(uint8_t order[PANEL_PAGES], int place, int step);

// The place of a page.
int panel_pages_place(const uint8_t order[PANEL_PAGES], int page);

// The hidden pages out of a stored number. A bit of a page this firmware
// does not have is left out, and a number that hides every page hides
// none.
uint32_t panel_pages_hidden(uint32_t stored);

// The page hidden, or shown again if it was hidden. false, and nothing
// changes, for the last page that is shown or a page this firmware does
// not have.
bool panel_pages_toggle(uint32_t *hidden, int page);

// The pages that are shown.
int panel_pages_shown(uint32_t hidden);

// The place of a page in the band, among the pages that are shown, or -1
// for a page that is hidden.
int panel_pages_band_place(const uint8_t order[PANEL_PAGES], uint32_t hidden, int page);

// The page at that place in the band. A place before the first is the
// first, and a place past the last is the last.
int panel_pages_band_page(const uint8_t order[PANEL_PAGES], uint32_t hidden, int place);
