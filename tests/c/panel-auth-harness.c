// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Prints one signature of the panel's firmware, so that a test on this
// machine reads it and compares it with the one the service builds.
//
// The two are in different languages and neither calls the other. The only
// thing that holds them equal is a test that runs both, and this is the half
// that the test cannot import. See tests/test_companion_auth.py.

#include <stdio.h>
#include <string.h>

#include "panel_auth.h"

int main(int argc, char **argv)
{
    if (argc != 6) {
        fprintf(stderr, "usage: %s <token> <method> <path> <nonce> <body>\n",
                argv[0]);
        return 2;
    }
    char out[PANEL_AUTH_HEX];
    if (!panel_auth_sign(argv[1], argv[2], argv[3], argv[4], argv[5],
                         strlen(argv[5]), out)) {
        fprintf(stderr, "panel_auth_sign refused\n");
        return 1;
    }
    printf("%s\n", out);
    return 0;
}
