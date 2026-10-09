// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"

typedef struct {
    char ssid[33];
    char password[65];
    char server[192];
    char token[128];
    /* The wired card of the PC, which the service reports and the panel
     * keeps. It is not typed in and not part of the setup: the panel learns
     * it while the PC is up, and needs it when the PC is off. Empty until
     * the first answer that carries one. */
    char wol_mac[18];
} panel_config_t;

bool panel_config_load(panel_config_t *config);

/* Writes the address on its own. The rest of the configuration is written
 * by the setup form, and this is learnt instead, so the two do not share a
 * path that could drop one while saving the other. */
esp_err_t panel_config_save_wol(const char *mac);

/* The address of the PC and the secret that a pairing gave, in one commit,
 * and the address alone, for a PC that the panel found again at a new
 * address. See panel_pair.h. */
esp_err_t panel_config_save_pairing(const char *server, const char *token);
esp_err_t panel_config_save_server(const char *server);
esp_err_t panel_config_portal(char *ssid, size_t ssid_size, char *password, size_t password_size);
