// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// The magic packet that wakes a machine, and the address it names.
//
// No sockets in here, the same way panel_key.c holds the state machine of
// the key and panel_power.c holds the hardware. What is left is arithmetic
// on bytes, which check_wol runs on any machine.

#define PANEL_WOL_MAC_BYTES 6
// Six of 0xFF, then the address sixteen times over.
#define PANEL_WOL_PACKET_BYTES (6 + 16 * PANEL_WOL_MAC_BYTES)
// "aa:bb:cc:dd:ee:ff" and the end of the string.
#define PANEL_WOL_TEXT_ROOM 18
// Where a magic packet goes. Nothing listens there: the card reads the
// wire, and the port only has to be one that a router forwards as an
// ordinary broadcast. 9 is the discard port and the usual choice.
#define PANEL_WOL_PORT 9

// Reads "aa:bb:cc:dd:ee:ff" into six bytes. Upper case is fine, anything
// else is not. False leaves the address untouched.
bool panel_wol_parse(const char *text, uint8_t address[PANEL_WOL_MAC_BYTES]);

// Writes the packet. Returns how many bytes it wrote, or zero when the room
// is too small to hold one.
size_t panel_wol_packet(const uint8_t address[PANEL_WOL_MAC_BYTES],
                        uint8_t *out, size_t room);
