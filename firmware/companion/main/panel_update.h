// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// When the panel takes a firmware that the PC offers, and when not.
//
// The PC sends an offer with every status: the number of the build, the
// version, the size, the SHA-256 and a signature over the first three and
// the hash, made with the token. The panel shows the offer only when the
// signature fits and the number is higher than its own. It writes the image
// only with enough battery, and boots it only when the SHA-256 of what it
// downloaded is the one of the offer. panel_ota.c does the writing.
//
// No ESP-IDF in here, so tests/test_panel_update.py builds this file on the
// machine that runs the tests and asks it.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "panel_auth.h"

// A slot of the partition table, and an image larger than that is none.
#define PANEL_UPDATE_SLOT_BYTES 0x700000u
// Below this, on the battery and not charging, an update waits for the
// cable: an image half written is safe, but a panel that dies on the way
// is one more thing for somebody to sort out.
#define PANEL_UPDATE_LEAST_BATTERY 20

// The path of the image on the service, and the size of the blocks the
// download hands to the flash. FIRMWARE_PATH in companion.py is the same.
#define PANEL_UPDATE_PATH "/v1/firmware"
#define PANEL_UPDATE_BLOCK 4096

typedef struct {
    int build;
    uint32_t size;
    char version[32];
    char sha256[PANEL_AUTH_HEX];
    char sign[PANEL_AUTH_HEX];
} panel_offer_t;

// The number of a build, out of its version: 61 for "61-1eec536", and 0
// for one with no number in front, which is a build made by hand.
int panel_update_build(const char *version);

// Whether the panel offers that update: signed with this token, a number
// above the running one, a size that fits a slot, and a hash that is a
// hash.
bool panel_update_wanted(const char *token, int running,
                         const panel_offer_t *offer);

// Whether the power allows an update: on the cable, charging, or on the
// battery with PANEL_UPDATE_LEAST_BATTERY per cent at least.
bool panel_update_power_ok(bool on_battery, int percent, bool charging);
