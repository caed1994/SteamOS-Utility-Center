// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Whether the panel was lifted, out of the readings of its accelerometer.
//
// Asked for: the display comes back when somebody lifts the panel, after
// it went dark by itself. A panel at rest reads gravity and nothing else,
// the same vector at every reading. A hand that lifts it tilts it or moves
// it, and the reading moves away from that vector.
//
// So this keeps the vector of the rest, and says "lifted" when a reading
// stands PANEL_LIFT_MG or more away from it on PANEL_LIFT_READINGS
// readings in a row. One reading alone is not enough: a door that closes
// shakes a wall for a moment and not for two readings. The rest follows
// slow changes, an eighth of the way at each quiet reading, so a sensor
// that drifts with its temperature does not wake anything.
//
// The first readings after the start only find the rest: the sensor has
// just been switched on. A reading far from one g is no reading of a
// panel at rest or in a hand, a sensor without data or a panel in free
// fall, and is left out.
//
// No ESP-IDF in here, so tests/test_panel_motion.py builds this file on
// the machine that runs the tests and asks it.
#pragma once

#include <stdbool.h>
#include <stdint.h>

// About 9 degrees of tilt, or a tenth and a half of g of movement.
#define PANEL_LIFT_MG 150
#define PANEL_LIFT_READINGS 2
// The readings after the start that find the rest; the last of them is it.
#define PANEL_LIFT_SETTLE 3
// A reading whose length is outside this, in mg, is left out.
#define PANEL_LIFT_LEAST_MG 500
#define PANEL_LIFT_MOST_MG 2000

typedef struct {
    int32_t rest[3];
    int settled, over;
} panel_lift_t;

void panel_lift_reset(panel_lift_t *lift);

// One reading in mg on the three axes. true when the panel was lifted.
bool panel_lift_feed(panel_lift_t *lift, const int32_t mg[3]);
