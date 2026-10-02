// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Asks panel_update.c one question from the command line and prints the
// answer, so tests/test_panel_update.py holds it against companion.py.
//
//   build <version>
//   sign <token> <build> <size> <sha256>
//   wanted <token> <running> <build> <size> <sha256> <sign>
//   power <on_battery> <percent> <charging>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "panel_update.h"

int main(int argc, char **argv)
{
    if (argc == 3 && strcmp(argv[1], "build") == 0) {
        printf("%d\n", panel_update_build(argv[2]));
        return 0;
    }
    if (argc == 6 && strcmp(argv[1], "sign") == 0) {
        char out[PANEL_AUTH_HEX];
        if (!panel_auth_offer(argv[2], atoi(argv[3]),
                              strtoul(argv[4], NULL, 10), argv[5], out))
            return 1;
        printf("%s\n", out);
        return 0;
    }
    if (argc == 8 && strcmp(argv[1], "wanted") == 0) {
        panel_offer_t offer = {0};
        offer.build = atoi(argv[4]);
        offer.size = (uint32_t)strtoul(argv[5], NULL, 10);
        snprintf(offer.sha256, sizeof offer.sha256, "%s", argv[6]);
        snprintf(offer.sign, sizeof offer.sign, "%s", argv[7]);
        printf("%d\n", panel_update_wanted(argv[2], atoi(argv[3]), &offer));
        return 0;
    }
    if (argc == 5 && strcmp(argv[1], "power") == 0) {
        printf("%d\n", panel_update_power_ok(atoi(argv[2]) != 0, atoi(argv[3]),
                                             atoi(argv[4]) != 0));
        return 0;
    }
    fprintf(stderr, "usage: see the head of this file\n");
    return 2;
}
