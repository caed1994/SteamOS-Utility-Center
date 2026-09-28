// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// How this panel proves that it knows the secret, without sending it.
//
// The secret stays in NVS on this board and in a file on the machine. What
// goes over the wireless network is a signature over the method, the path
// and the body, with a nonce that the machine issued. A request that
// somebody reads off the air is then worth nothing: the nonce is spent, and
// the signature fits no other path and no other action.
//
// The same message is built on the other side by signature() in
// server/steamos_utility_center/companion.py. The two have to agree byte for
// byte, and tests/test_companion_auth.py compiles this file and holds them
// equal.
#pragma once

#include <stdbool.h>
#include <stddef.h>

// A SHA-256 in hexadecimal, and room for the terminator.
#define PANEL_AUTH_HEX 65

// Builds the signature for one request. Returns false where a buffer is too
// small or mbedtls refuses, and the caller then sends no signature at all.
bool panel_auth_sign(const char *token, const char *method, const char *path,
                     const char *nonce, const char *body, size_t body_length,
                     char out[PANEL_AUTH_HEX]);
