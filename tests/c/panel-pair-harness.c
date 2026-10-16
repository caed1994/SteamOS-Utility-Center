// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// panel_pair.c, asked line by line by tests/test_panel_pair.py. A key is 64
// hexadecimal digits.
//
//   x25519 <scalar> <point>     prints scalar times point, or "(refused)"
//   keys <seed>                 prints a new private and public key; the
//                               random bytes are seed, seed+1, ...
//   shared <private> <pc key>   prints the shared secret, or "(weak)"
//   derive <shared> <panel key> <pc key>
//                               prints the token and the code
//   body <room> <name> <key>    prints the body and its length, or
//                               "(empty) 0"
//   unhex <text>                prints the 32 bytes again, or "(no)"
//   name <text>                 prints the safe name between brackets
//   id <text>                   prints 1 for an id and 0 for anything else
#include <stdio.h>
#include <string.h>

#include "panel_pair.h"

static unsigned char next_byte;

static void counting(unsigned char *out, size_t size)
{
    for (size_t i = 0; i < size; i++) out[i] = next_byte++;
}

static void hex(const unsigned char *bytes, size_t count)
{
    for (size_t i = 0; i < count; i++) printf("%02x", bytes[i]);
}

int main(void)
{
    char line[512], one[160], two[160], three[160];
    unsigned char a[PANEL_PAIR_KEY], b[PANEL_PAIR_KEY], c[PANEL_PAIR_KEY];
    int number;
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\n")] = 0;
        if (sscanf(line, "x25519 %159s %159s", one, two) == 2) {
            if (panel_pair_unhex(one, a) && panel_pair_unhex(two, b)
                && panel_pair_x25519(a, b, c, counting)) {
                hex(c, sizeof c);
                printf("\n");
            } else {
                printf("(refused)\n");
            }
        } else if (sscanf(line, "keys %d", &number) == 1) {
            panel_pair_keys_t keys;
            next_byte = (unsigned char)number;
            if (panel_pair_keys(&keys, counting)) {
                hex(keys.private_key, sizeof keys.private_key);
                printf(" ");
                hex(keys.public_key, sizeof keys.public_key);
                printf("\n");
            } else {
                printf("(refused)\n");
            }
        } else if (sscanf(line, "shared %159s %159s", one, two) == 2) {
            if (panel_pair_unhex(one, a) && panel_pair_unhex(two, b)
                && panel_pair_shared(a, b, c, counting)) {
                hex(c, sizeof c);
                printf("\n");
            } else {
                printf("(weak)\n");
            }
        } else if (sscanf(line, "derive %159s %159s %159s", one, two, three) == 3) {
            unsigned char shared[PANEL_PAIR_KEY];
            char secret[PANEL_PAIR_SECRET], code[PANEL_PAIR_CODE];
            if (panel_pair_unhex(one, shared) && panel_pair_unhex(two, a)
                && panel_pair_unhex(three, b)
                && panel_pair_derive(shared, a, b, secret, code))
                printf("%s %s\n", secret, code);
            else
                printf("(refused)\n");
        } else if (sscanf(line, "body %d %159s %159s", &number, one, two) == 3) {
            char body[256];
            if (number < 0 || number > (int)sizeof body) number = (int)sizeof body;
            size_t length = panel_pair_unhex(two, a)
                ? panel_pair_body(body, (size_t)number, one, a) : 0;
            if (length) printf("%s %zu\n", body, length);
            else printf("(empty) 0\n");
        } else if (sscanf(line, "unhex %159s", one) == 1) {
            if (panel_pair_unhex(one, a)) {
                hex(a, sizeof a);
                printf("\n");
            } else {
                printf("(no)\n");
            }
        } else if (strncmp(line, "name ", 5) == 0) {
            char name[PANEL_PAIR_NAME];
            panel_pair_name(name, line + 5);
            printf("[%s]\n", name);
        } else if (strncmp(line, "id ", 3) == 0) {
            printf("%d\n", panel_pair_id_ok(line + 3) ? 1 : 0);
        } else {
            printf("?\n");
        }
    }
    return 0;
}
