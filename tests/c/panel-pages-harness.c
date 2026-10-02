// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// panel_pages.c, asked line by line by tests/test_panel_pages_order.py.
//
//   size                       prints PANEL_PAGES and PANEL_PAGE_PLACES
//   order <stored>             prints the page at each place
//   pack <page> ...            prints the stored number of that order
//   move <stored> <place> <step>
//                              prints 1 or 0 for the answer, then the order
//   place <stored> <page>      prints the place of that page
//
// A stored number is hexadecimal, as the tests write it.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "panel_pages.h"

static void show(const uint8_t order[PANEL_PAGES])
{
    for (int place = 0; place < PANEL_PAGES; place++)
        printf("%s%u", place ? " " : "", order[place]);
    printf("\n");
}

int main(void)
{
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        uint8_t order[PANEL_PAGES];
        unsigned long stored;
        int place, step, page;
        if (strncmp(line, "size", 4) == 0) {
            printf("%d %d\n", PANEL_PAGES, PANEL_PAGE_PLACES);
        } else if (sscanf(line, "order %lx", &stored) == 1) {
            panel_pages_order((uint32_t)stored, order);
            show(order);
        } else if (strncmp(line, "pack", 4) == 0) {
            char *at = line + 4;
            for (int i = 0; i < PANEL_PAGES; i++)
                order[i] = (uint8_t)strtoul(at, &at, 10);
            printf("%08x\n", (unsigned)panel_pages_pack(order));
        } else if (sscanf(line, "move %lx %d %d", &stored, &place, &step) == 3) {
            panel_pages_order((uint32_t)stored, order);
            printf("%d ", panel_pages_move(order, place, step) ? 1 : 0);
            show(order);
        } else if (sscanf(line, "place %lx %d", &stored, &page) == 2) {
            panel_pages_order((uint32_t)stored, order);
            printf("%d\n", panel_pages_place(order, page));
        } else {
            return 2;
        }
        fflush(stdout);
    }
    return 0;
}
