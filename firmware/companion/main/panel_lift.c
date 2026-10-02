// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// See panel_lift.h.
#include "panel_lift.h"

#include <string.h>

void panel_lift_reset(panel_lift_t *lift)
{
    memset(lift, 0, sizeof *lift);
}

static int64_t square(int64_t value) { return value * value; }

bool panel_lift_feed(panel_lift_t *lift, const int32_t mg[3])
{
    int64_t length = square(mg[0]) + square(mg[1]) + square(mg[2]);
    if (length < square(PANEL_LIFT_LEAST_MG) || length > square(PANEL_LIFT_MOST_MG))
        return false;
    if (lift->settled < PANEL_LIFT_SETTLE) {
        for (int i = 0; i < 3; i++) lift->rest[i] = mg[i];
        lift->settled++;
        lift->over = 0;
        return false;
    }
    int64_t away = square(mg[0] - lift->rest[0]) + square(mg[1] - lift->rest[1]) +
                   square(mg[2] - lift->rest[2]);
    if (away >= square(PANEL_LIFT_MG)) {
        lift->over++;
        return lift->over >= PANEL_LIFT_READINGS;
    }
    lift->over = 0;
    for (int i = 0; i < 3; i++) lift->rest[i] += (mg[i] - lift->rest[i]) / 8;
    return false;
}
