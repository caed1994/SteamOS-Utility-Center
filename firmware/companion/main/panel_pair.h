// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The pairing of this panel with the PC, with no token to type.
//
// The panel and the PC do a key exchange, X25519 of RFC 7748. Each side
// sends its public key, and each side then calculates the same secret,
// which never goes over the network. Both show a code of six digits from
// the same calculation, and a person accepts the panel on the PC when the
// two codes are the same.
//
// The PC does the same in server/steamos_utility_center/pairing.py, and
// tests/test_panel_pair.py builds this file and holds the two equal.
//
// No ESP-IDF here, so the machine that tests it can build it: mbedtls is on
// both, and the random bytes come from the caller.
#pragma once

#include <stdbool.h>
#include <stddef.h>

#define PANEL_PAIR_KEY 32
// The token: a SHA-256 in hexadecimal, and the end.
#define PANEL_PAIR_SECRET 65
// Six digits and the end.
#define PANEL_PAIR_CODE 7
// The id of a request on the PC: 16 hexadecimal digits and the end.
#define PANEL_PAIR_ID 17
// A name of the PC or of the panel: pairing.NAME_CHARS and the end.
#define PANEL_PAIR_NAME 25
// The port of the service, for the search with a broadcast as for HTTP.
#define PANEL_PAIR_PORT 8765
// The broadcast of a panel that looks for the PC: pairing.DISCOVER.
#define PANEL_PAIR_DISCOVER "steamos-utility-center discover 1"
#define PANEL_PAIR_SERVICE "steamos-utility-center"
#define PANEL_PAIR_PATH "/v1/pair"

// Fills `out` with `size` bytes that nobody can guess. The board gives its
// hardware generator, and a test gives fixed bytes.
typedef void (*panel_pair_random_t)(unsigned char *out, size_t size);

// One pair of keys. The private key never leaves the panel and is wiped
// after the pairing.
typedef struct {
    unsigned char private_key[PANEL_PAIR_KEY];
    unsigned char public_key[PANEL_PAIR_KEY];
} panel_pair_keys_t;

// scalar times point, as RFC 7748 says: the scalar is clamped, and the top
// bit of the point is ignored. false where mbedtls refuses.
bool panel_pair_x25519(const unsigned char scalar[PANEL_PAIR_KEY],
                       const unsigned char point[PANEL_PAIR_KEY],
                       unsigned char out[PANEL_PAIR_KEY],
                       panel_pair_random_t random);

// A new pair of keys from `random`.
bool panel_pair_keys(panel_pair_keys_t *keys, panel_pair_random_t random);

// The shared secret with the key of the PC. false for a weak key, whose
// result is zero whatever the other key is.
bool panel_pair_shared(const unsigned char private_key[PANEL_PAIR_KEY],
                       const unsigned char pc_key[PANEL_PAIR_KEY],
                       unsigned char shared[PANEL_PAIR_KEY],
                       panel_pair_random_t random);

// The token and the code, as pairing.derive on the PC: an HMAC-SHA256 under
// the shared secret over a label and the two keys, the key of the panel
// first.
bool panel_pair_derive(const unsigned char shared[PANEL_PAIR_KEY],
                       const unsigned char panel_key[PANEL_PAIR_KEY],
                       const unsigned char pc_key[PANEL_PAIR_KEY],
                       char secret[PANEL_PAIR_SECRET],
                       char code[PANEL_PAIR_CODE]);

// The body of the request: {"name":"...","key":"<64 hex digits>"}. Answers
// the length, and nought for too little room. The name keeps the letters,
// digits, spaces and ".", "_" and "-" of the name it gets.
size_t panel_pair_body(char *out, size_t room, const char *name,
                       const unsigned char key[PANEL_PAIR_KEY]);

// 64 hexadecimal digits in small letters as 32 bytes. false for anything
// else.
bool panel_pair_unhex(const char *text, unsigned char out[PANEL_PAIR_KEY]);

// Copies a name that the PC sent, with only the characters of a name.
void panel_pair_name(char out[PANEL_PAIR_NAME], const char *text);

// 16 hexadecimal digits in small letters: the id of a request.
bool panel_pair_id_ok(const char *text);
