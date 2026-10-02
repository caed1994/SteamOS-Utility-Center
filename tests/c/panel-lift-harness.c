// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// panel_lift.c, asked line by line by tests/test_panel_motion.py.
//
//   feed <x> <y> <z>   one reading in mg; prints 1 for a lift, else 0
//   reset              panel_lift_reset, as the task does after a lift
#include <stdio.h>
#include <string.h>

#include "panel_lift.h"

int main(void)
{
    panel_lift_t lift;
    panel_lift_reset(&lift);
    char line[128];
    while (fgets(line, sizeof line, stdin)) {
        long x, y, z;
        if (sscanf(line, "feed %ld %ld %ld", &x, &y, &z) == 3) {
            const int32_t mg[3] = {(int32_t)x, (int32_t)y, (int32_t)z};
            printf("%d\n", panel_lift_feed(&lift, mg) ? 1 : 0);
        } else if (strncmp(line, "reset", 5) == 0) {
            panel_lift_reset(&lift);
        } else {
            return 2;
        }
        fflush(stdout);
    }
    return 0;
}
