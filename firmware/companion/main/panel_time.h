// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <time.h>

// The time of day for the clock page, from the clock chip of the board
// and from the network.
//
// Call panel_time_start once, after the I2C bus is up and before the
// screen is built. It sets the zone, and the time of the clock chip when
// the chip holds one to trust. So the clock page has the time right after
// a restart, with no network.
void panel_time_start(void);

// Call panel_time_init once, after esp_netif_init and before the radio
// joins the network: it asks DHCP for a time server, and DHCP answers
// that only to a request it has not made yet.
void panel_time_init(void);

// From the task of the network, at each turn: the clock chip takes the
// time after each answer of a time server.
void panel_time_keep(void);

// The local time now. false while the clock has never been set, which is
// the case from the start of the panel until the first answer of a time
// server, when the clock chip held no time.
bool panel_time_now(struct tm *now);
