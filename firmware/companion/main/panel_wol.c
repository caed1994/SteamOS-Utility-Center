// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_wol.h"

static int digit(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool panel_wol_parse(const char *text, uint8_t address[PANEL_WOL_MAC_BYTES])
{
    if (!text || !address) return false;
    uint8_t read[PANEL_WOL_MAC_BYTES];
    size_t at = 0;
    for (size_t i = 0; i < PANEL_WOL_MAC_BYTES; i++) {
        int high = digit(text[at]);
        int low = high < 0 ? -1 : digit(text[at + 1]);
        if (low < 0) return false;
        read[i] = (uint8_t)((high << 4) | low);
        at += 2;
        /* A colon between each pair, and the end of the string after the
         * last one. Anything else is a longer text that starts like an
         * address, and this refuses it rather than taking the first part. */
        if (i + 1 < PANEL_WOL_MAC_BYTES) {
            if (text[at] != ':') return false;
            at++;
        } else if (text[at] != '\0') {
            return false;
        }
    }
    /* An address of nothing is what a card reports before it is ready, and
     * a packet naming it wakes nothing. */
    uint8_t any = 0;
    for (size_t i = 0; i < PANEL_WOL_MAC_BYTES; i++) any |= read[i];
    if (any == 0) return false;
    for (size_t i = 0; i < PANEL_WOL_MAC_BYTES; i++) address[i] = read[i];
    return true;
}

size_t panel_wol_packet(const uint8_t address[PANEL_WOL_MAC_BYTES],
                        uint8_t *out, size_t room)
{
    if (!address || !out || room < PANEL_WOL_PACKET_BYTES) return 0;
    size_t at = 0;
    while (at < 6) out[at++] = 0xFF;
    for (int repeat = 0; repeat < 16; repeat++)
        for (size_t i = 0; i < PANEL_WOL_MAC_BYTES; i++)
            out[at++] = address[i];
    return at;
}
