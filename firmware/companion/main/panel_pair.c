// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later

#include "panel_pair.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "mbedtls/ecdh.h"
#include "mbedtls/ecp.h"
#include "mbedtls/md.h"

// These calls are the same in mbedtls 2 and mbedtls 3, so the same file
// builds on the board and on the machine that tests it. See panel_auth.c
// for the other side of that choice.

#define SECRET_LABEL "steamos-utility-center pairing secret"
#define CODE_LABEL "steamos-utility-center pairing code"

// mbedtls asks for a random generator to blind the calculation. It takes
// it as a function and a pointer, so the pointer carries ours.
typedef struct {
    panel_pair_random_t random;
} source_t;

static int bridge(void *source, unsigned char *out, size_t size)
{
    ((const source_t *)source)->random(out, size);
    return 0;
}

bool panel_pair_x25519(const unsigned char scalar[PANEL_PAIR_KEY],
                       const unsigned char point[PANEL_PAIR_KEY],
                       unsigned char out[PANEL_PAIR_KEY],
                       panel_pair_random_t random)
{
    if (!scalar || !point || !out || !random) return false;
    unsigned char k[PANEL_PAIR_KEY], u[PANEL_PAIR_KEY];
    memcpy(k, scalar, sizeof(k));
    k[0] &= 248;
    k[31] &= 127;
    k[31] |= 64;
    memcpy(u, point, sizeof(u));
    u[31] &= 127;
    source_t source = {.random = random};
    mbedtls_ecp_group group;
    mbedtls_ecp_point other;
    mbedtls_mpi secret, product;
    mbedtls_ecp_group_init(&group);
    mbedtls_ecp_point_init(&other);
    mbedtls_mpi_init(&secret);
    mbedtls_mpi_init(&product);
    bool ok = mbedtls_ecp_group_load(&group, MBEDTLS_ECP_DP_CURVE25519) == 0
        && mbedtls_mpi_read_binary_le(&secret, k, sizeof(k)) == 0
        && mbedtls_ecp_point_read_binary(&group, &other, u, sizeof(u)) == 0
        && mbedtls_ecdh_compute_shared(&group, &product, &other, &secret,
                                       bridge, &source) == 0
        && mbedtls_mpi_write_binary_le(&product, out, PANEL_PAIR_KEY) == 0;
    mbedtls_mpi_free(&product);
    mbedtls_mpi_free(&secret);
    mbedtls_ecp_point_free(&other);
    mbedtls_ecp_group_free(&group);
    memset(k, 0, sizeof(k));
    return ok;
}

bool panel_pair_keys(panel_pair_keys_t *keys, panel_pair_random_t random)
{
    if (!keys || !random) return false;
    static const unsigned char BASE[PANEL_PAIR_KEY] = {9};
    random(keys->private_key, sizeof(keys->private_key));
    return panel_pair_x25519(keys->private_key, BASE, keys->public_key, random);
}

bool panel_pair_shared(const unsigned char private_key[PANEL_PAIR_KEY],
                       const unsigned char pc_key[PANEL_PAIR_KEY],
                       unsigned char shared[PANEL_PAIR_KEY],
                       panel_pair_random_t random)
{
    if (!panel_pair_x25519(private_key, pc_key, shared, random)) return false;
    unsigned char any = 0;
    for (size_t i = 0; i < PANEL_PAIR_KEY; i++) any |= shared[i];
    return any != 0;
}

static void to_hex(const unsigned char *bytes, size_t count, char *out)
{
    static const char DIGITS[] = "0123456789abcdef";
    for (size_t i = 0; i < count; i++) {
        out[i * 2] = DIGITS[bytes[i] >> 4];
        out[i * 2 + 1] = DIGITS[bytes[i] & 0x0f];
    }
    out[count * 2] = 0;
}

// An HMAC-SHA256 under the shared secret, over a label and the two keys.
static bool mac(const unsigned char shared[PANEL_PAIR_KEY], const char *label,
                const unsigned char panel_key[PANEL_PAIR_KEY],
                const unsigned char pc_key[PANEL_PAIR_KEY],
                unsigned char out[32])
{
    unsigned char message[64 + 2 * PANEL_PAIR_KEY];
    size_t length = strlen(label);
    if (length > 64) return false;
    memcpy(message, label, length);
    memcpy(message + length, panel_key, PANEL_PAIR_KEY);
    memcpy(message + length + PANEL_PAIR_KEY, pc_key, PANEL_PAIR_KEY);
    const mbedtls_md_info_t *sha = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    return sha && mbedtls_md_hmac(sha, shared, PANEL_PAIR_KEY, message,
                                  length + 2 * PANEL_PAIR_KEY, out) == 0;
}

bool panel_pair_derive(const unsigned char shared[PANEL_PAIR_KEY],
                       const unsigned char panel_key[PANEL_PAIR_KEY],
                       const unsigned char pc_key[PANEL_PAIR_KEY],
                       char secret[PANEL_PAIR_SECRET],
                       char code[PANEL_PAIR_CODE])
{
    if (!shared || !panel_key || !pc_key || !secret || !code) return false;
    unsigned char out[32];
    if (!mac(shared, SECRET_LABEL, panel_key, pc_key, out)) return false;
    to_hex(out, sizeof(out), secret);
    if (!mac(shared, CODE_LABEL, panel_key, pc_key, out)) return false;
    uint32_t number = ((uint32_t)out[0] << 24) | ((uint32_t)out[1] << 16)
                      | ((uint32_t)out[2] << 8) | out[3];
    snprintf(code, PANEL_PAIR_CODE, "%06u", (unsigned)(number % 1000000u));
    memset(out, 0, sizeof(out));
    return true;
}

static bool name_char(char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
        || (c >= '0' && c <= '9') || c == ' ' || c == '.' || c == '_'
        || c == '-';
}

void panel_pair_name(char out[PANEL_PAIR_NAME], const char *text)
{
    size_t kept = 0;
    for (; text && *text && kept < PANEL_PAIR_NAME - 1; text++)
        if (name_char(*text)) out[kept++] = *text;
    out[kept] = 0;
}

size_t panel_pair_body(char *out, size_t room, const char *name,
                       const unsigned char key[PANEL_PAIR_KEY])
{
    if (!out || !key) return 0;
    char safe[PANEL_PAIR_NAME], hex[2 * PANEL_PAIR_KEY + 1];
    panel_pair_name(safe, name);
    to_hex(key, PANEL_PAIR_KEY, hex);
    int written = snprintf(out, room, "{\"name\":\"%s\",\"key\":\"%s\"}", safe,
                           hex);
    if (written < 0 || (size_t)written >= room) {
        if (room) out[0] = 0;
        return 0;
    }
    return (size_t)written;
}

static int digit(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

bool panel_pair_unhex(const char *text, unsigned char out[PANEL_PAIR_KEY])
{
    if (!text || strlen(text) != 2 * PANEL_PAIR_KEY) return false;
    for (size_t i = 0; i < PANEL_PAIR_KEY; i++) {
        int high = digit(text[2 * i]), low = digit(text[2 * i + 1]);
        if (high < 0 || low < 0) return false;
        out[i] = (unsigned char)(high * 16 + low);
    }
    return true;
}

bool panel_pair_id_ok(const char *text)
{
    if (!text || strlen(text) != PANEL_PAIR_ID - 1) return false;
    for (; *text; text++)
        if (digit(*text) < 0) return false;
    return true;
}
