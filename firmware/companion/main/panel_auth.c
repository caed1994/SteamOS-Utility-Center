// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later

#include "panel_auth.h"

#include <stdio.h>
#include <string.h>

#include "mbedtls/md.h"

// mbedtls_md and mbedtls_md_hmac, rather than the sha256 calls.
//
// ESP-IDF v5.5 carries mbedtls 3 and an ordinary Linux carries mbedtls 2.
// The sha256 entry points were renamed between the two. These two were not,
// so the same file builds on the board and on the machine that tests it.

// The longest message this builds is the method, the path, the nonce and a
// 64 character digest, with three newlines. The path of this service is
// short and fixed, so this is far more room than it needs.
#define MESSAGE_ROOM 512

static void to_hex(const unsigned char *bytes, size_t count, char *out)
{
    static const char DIGITS[] = "0123456789abcdef";
    for (size_t i = 0; i < count; i++) {
        out[i * 2] = DIGITS[bytes[i] >> 4];
        out[i * 2 + 1] = DIGITS[bytes[i] & 0x0f];
    }
    out[count * 2] = 0;
}

bool panel_auth_sign(const char *token, const char *method, const char *path,
                     const char *nonce, const char *body, size_t body_length,
                     char out[PANEL_AUTH_HEX])
{
    if (!token || !method || !path || !nonce || !out) return false;
    if (!body) body_length = 0;

    const mbedtls_md_info_t *sha = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (!sha) return false;

    // The body goes in as its digest and not as itself. A GET has no body,
    // and the digest of nothing is still a value, so both requests have the
    // same shape.
    unsigned char digest[32];
    char body_hex[PANEL_AUTH_HEX];
    if (mbedtls_md(sha, (const unsigned char *)(body ? body : ""),
                   body_length, digest) != 0) return false;
    to_hex(digest, sizeof(digest), body_hex);

    char message[MESSAGE_ROOM];
    int written = snprintf(message, sizeof(message), "%s\n%s\n%s\n%s",
                           method, path, nonce, body_hex);
    if (written < 0 || (size_t)written >= sizeof(message)) return false;

    unsigned char mac[32];
    if (mbedtls_md_hmac(sha, (const unsigned char *)token, strlen(token),
                        (const unsigned char *)message, (size_t)written,
                        mac) != 0) return false;
    to_hex(mac, sizeof(mac), out);
    return true;
}
