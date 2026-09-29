// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The magic packet, byte for byte.
//
// A wake that does not work leaves nothing behind: no error, no log on the
// far side, just a machine that stays off. So the packet is read here
// rather than believed, and the address parser is given the texts that a
// service, a person and a mistake produce.
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "panel_wol.h"

static void parses(const char *text, const char *why)
{
    uint8_t got[PANEL_WOL_MAC_BYTES];
    if (!panel_wol_parse(text, got)) {
        fprintf(stderr, "check_wol: refused \"%s\", which it should take: %s\n",
                text, why);
        assert(0);
    }
}
static void refuses(const char *text, const char *why)
{
    uint8_t got[PANEL_WOL_MAC_BYTES] = {1, 2, 3, 4, 5, 6};
    if (panel_wol_parse(text, got)) {
        fprintf(stderr, "check_wol: took \"%s\", which it should refuse: %s\n",
                text, why);
        assert(0);
    }
    /* A refusal leaves what was there, so a bad answer from the service
     * cannot wipe an address the panel already had. */
    for (int i = 0; i < PANEL_WOL_MAC_BYTES; i++) assert(got[i] == i + 1);
}
int main(void)
{
    uint8_t address[PANEL_WOL_MAC_BYTES];

    /* What a service sends, and what a person types. */
    assert(panel_wol_parse("a4:bb:6d:1f:0e:27", address));
    const uint8_t wanted[] = {0xA4, 0xBB, 0x6D, 0x1F, 0x0E, 0x27};
    assert(memcmp(address, wanted, sizeof wanted) == 0);
    parses("A4:BB:6D:1F:0E:27", "upper case is the same address");
    parses("00:00:00:00:00:01", "only all zeroes is nothing");

    refuses(NULL, "no text at all");
    refuses("", "an empty string");
    refuses("a4:bb:6d:1f:0e", "five pairs and not six");
    refuses("a4:bb:6d:1f:0e:27:33", "seven pairs");
    refuses("a4:bb:6d:1f:0e:27 ", "something after the last pair");
    refuses("a4:bb:6d:1f:0e:2", "one digit in the last pair");
    refuses("a4-bb-6d-1f-0e-27", "dashes are another spelling, not this one");
    refuses("a4:bb:6d:1f:0e:2g", "g is not a digit");
    refuses("00:00:00:00:00:00", "the address a card reports before it is ready");
    refuses("the pc is at a4:bb:6d:1f:0e:27", "a sentence holding one");

    /* The packet. Six of 0xFF, then the address sixteen times, and nothing
     * else. 102 bytes in all. */
    uint8_t packet[PANEL_WOL_PACKET_BYTES + 8];
    memset(packet, 0x5A, sizeof packet);
    assert(panel_wol_packet(wanted, packet, PANEL_WOL_PACKET_BYTES)
           == PANEL_WOL_PACKET_BYTES);
    assert(PANEL_WOL_PACKET_BYTES == 102);
    for (int i = 0; i < 6; i++) assert(packet[i] == 0xFF);
    for (int repeat = 0; repeat < 16; repeat++)
        for (int i = 0; i < PANEL_WOL_MAC_BYTES; i++)
            assert(packet[6 + repeat * PANEL_WOL_MAC_BYTES + i] == wanted[i]);
    /* It wrote its own length and not one byte more. */
    for (size_t i = PANEL_WOL_PACKET_BYTES; i < sizeof packet; i++)
        assert(packet[i] == 0x5A);

    /* Too little room writes nothing at all, rather than half a packet. */
    memset(packet, 0x5A, sizeof packet);
    assert(panel_wol_packet(wanted, packet, PANEL_WOL_PACKET_BYTES - 1) == 0);
    for (size_t i = 0; i < sizeof packet; i++) assert(packet[i] == 0x5A);
    assert(panel_wol_packet(NULL, packet, sizeof packet) == 0);
    assert(panel_wol_packet(wanted, NULL, sizeof packet) == 0);

    puts("OK: the address parser takes what a service sends and refuses ten "
         "other things; the packet is 102 bytes of 0xFF and the address.");
    return 0;
}
