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
// No ESP-IDF and no LVGL in here, so tests/test_panel_pages_order.py
// builds this file on the machine that runs the tests and asks it.
#pragma once

#include <stdbool.h>
#include <stdint.h>

// The pages, in the order the firmware builds them, and how many.
typedef enum {
    PANEL_PAGE_CONTROLS,
    PANEL_PAGE_SESSION,
    PANEL_PAGE_PLAYING,
    PANEL_PAGE_CLOCK,
    PANEL_PAGE_CARD,
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
