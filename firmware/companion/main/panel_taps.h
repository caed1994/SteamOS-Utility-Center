// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// How the touch screen answers, for the page of the panel and for the log.
//
// Asked for: taps that sometimes seem not to land. Before anything about
// the touch changes, this measures it. Each read of the touch controller
// goes in, and so does what LVGL made of each press: a tap, a swipe, or
// neither.
//
// A press is the reads from the first one with a finger to the first one
// without. Its numbers come from those reads: how long it lasted, how far
// the finger went from where it came down, and the weakest contact the
// controller reported. The controller reports the size of the contact,
// which is smaller for a weaker one: a finger that barely touches, or a
// glass over the screen. What it became comes from LVGL, which sends its
// events for a release in the same read: RELEASED with the object being
// scrolled still set for a swipe, and CLICKED after it for a tap. So a
// press is over, and counted, at the read after its release.
//
// A lost tap is a press that came down on something that takes a tap and
// became neither a tap nor a swipe. That is the one somebody feels as a tap
// that did not land.
//
// A late read is a read that came more than PANEL_TAPS_LATE_MS after the
// one before it. LVGL reads the touch between two frames, so a long frame
// pushes the read back, and a tap shorter than the gap is never seen at
// all: the controller keeps the last state and nothing before it.
//
// The configuration of the controller is read once, at the start, and its
// numbers go on the page too: the thresholds a finger has to cross to come
// down and to go up again, and the period of its reports.
//
// No ESP-IDF and no LVGL in here, so tests/test_panel_taps.py builds this
// file on the machine that runs the tests and asks it.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// A read later than this after the one before it is a late one. LVGL reads
// every 15 ms when nothing holds it back.
#define PANEL_TAPS_LATE_MS 40

// What a press became.
typedef enum {
    PANEL_TAPS_NOTHING,  // came down on nothing that takes a tap
    PANEL_TAPS_TAP,      // reached something as a tap
    PANEL_TAPS_SWIPE,    // LVGL scrolled with it
    PANEL_TAPS_LOST,     // came down on something to tap, and was neither
} panel_taps_end_t;

// One press, as the log says it.
typedef struct {
    uint32_t ms;       // from the first read with the finger to the first without
    int moved;         // the farthest the finger went from where it came down, in px
    int weakest;       // the weakest contact the controller reported, -1 for none
    panel_taps_end_t end;
} panel_taps_press_t;

typedef struct {
    // The press on its way, or the one whose release LVGL just saw.
    bool down, ending;
    uint32_t down_at_ms, up_at_ms;
    int start_x, start_y, moved, weakest;
    bool on_target, tapped, swiped;
    // The reads.
    bool read_before;
    uint32_t last_read_ms;
    // What counts since the last reset.
    uint32_t presses, taps, swipes, lost, late, errors;
    uint32_t longest_gap_ms, shortest_ms;
    int weakest_ever;
    // Nothing counts while this is set.
    bool held;
} panel_taps_t;

// The configuration of the controller, as the start of the panel read it.
typedef struct {
    bool known;          // read, and its checksum holds
    char version;        // the version of the configuration, a letter
    int touch_level;     // the threshold for a finger to come down
    int leave_level;     // and to go up again
    int report_ms;       // the period of its reports
} panel_taps_chip_t;

// Where the configuration starts, how long it is up to and with its
// checksum, and the place of each number in it.
#define PANEL_TAPS_CHIP_START 0x8047
#define PANEL_TAPS_CHIP_LENGTH (0x80FF - 0x8047 + 1)

// The one the firmware counts in, and the configuration of the controller.
// panel_display.c gives them what it reads, and ui.c holds the count while
// the page of the panel shows it.
extern panel_taps_t panel_taps;
extern panel_taps_chip_t panel_taps_chip;

// Back to nothing counted, and not held.
void panel_taps_reset(panel_taps_t *taps);
// Held, nothing counts. A press on its way when the hold ends counts.
void panel_taps_hold(panel_taps_t *taps, bool hold);
// The reads stop and start again, as around a sleep of the panel: the gap
// between the two is no late read, and a press on its way is gone.
void panel_taps_break(panel_taps_t *taps);

// Each read of the controller: ok is false for a read the bus refused, and
// then the rest is what the read before it said. true when a press was
// over at this read, with its numbers in done.
bool panel_taps_read(panel_taps_t *taps, uint32_t now_ms, bool ok, bool pressed,
                     int x, int y, int strength, panel_taps_press_t *done);
// The events of LVGL for the press on its way: PRESSED, with whether the
// object takes a tap; RELEASED, with whether LVGL scrolled with the press;
// and CLICKED.
void panel_taps_pressed(panel_taps_t *taps, bool on_target);
void panel_taps_released(panel_taps_t *taps, bool swiped);
void panel_taps_clicked(panel_taps_t *taps);

// The configuration out of its bytes, from PANEL_TAPS_CHIP_START on. false,
// and nothing known, for too few bytes or a checksum that does not hold.
bool panel_taps_chip_parse(const uint8_t *config, size_t length, panel_taps_chip_t *out);
