// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// See panel_update.h.
#include "panel_update.h"

#include <ctype.h>
#include <string.h>

int panel_update_build(const char *version)
{
    if (!version) return 0;
    long number = 0;
    for (const char *at = version; isdigit((unsigned char)*at); at++) {
        number = number * 10 + (*at - '0');
        // A number past this is no build of this project.
        if (number > 100000000L) return 0;
    }
    return (int)number;
}

static bool is_hash(const char *text)
{
    if (strlen(text) != PANEL_AUTH_HEX - 1) return false;
    for (const char *at = text; *at; at++)
        if (!isxdigit((unsigned char)*at) || isupper((unsigned char)*at))
            return false;
    return true;
}

bool panel_update_wanted(const char *token, int running,
                         const panel_offer_t *offer)
{
    if (!token || !token[0] || !offer) return false;
    if (offer->build <= running) return false;
    if (offer->size == 0 || offer->size > PANEL_UPDATE_SLOT_BYTES) return false;
    if (!is_hash(offer->sha256)) return false;
    char wanted[PANEL_AUTH_HEX];
    if (!panel_auth_offer(token, offer->build, (unsigned long)offer->size,
                          offer->sha256, wanted)) return false;
    return panel_auth_equal(wanted, offer->sign);
}

bool panel_update_power_ok(bool on_battery, int percent, bool charging)
{
    return !on_battery || charging || percent >= PANEL_UPDATE_LEAST_BATTERY;
}
