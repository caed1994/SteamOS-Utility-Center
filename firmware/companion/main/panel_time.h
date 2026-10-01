// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <time.h>

// The time of day for the clock page, from the network.
//
// Call panel_time_init once, after esp_netif_init and before the radio
// joins the network: it asks DHCP for a time server, and DHCP answers
// that only to a request it has not made yet.
void panel_time_init(void);

// The local time now. false while the clock has never been set, which is
// the case from the start of the panel until the first answer of a time
// server.
bool panel_time_now(struct tm *now);
