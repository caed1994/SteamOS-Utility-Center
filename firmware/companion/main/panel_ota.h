// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The writing of a firmware into the other slot, and its boot on trial.
//
// The partition table has two slots, and the firmware runs from one of
// them. An update goes into the other one while this one runs: a write that
// stops halfway leaves the running firmware as it was. panel_ota_finish
// switches the slot only when the SHA-256 of what was written is the one of
// the offer and ESP-IDF finds the image whole.
//
// The new firmware boots on trial. The bootloader goes back to the old one
// when the new one restarts before panel_ota_confirm, which main.c calls
// once the PC answered. That needs CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE,
// which is in sdkconfig.defaults.
//
// When to update at all is panel_update.c. The network task alone calls
// these.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

// The version of the running firmware, as its build gave it: "61-1eec536".
const char *panel_ota_version(void);

// Erases the other slot for an image of that size. Seconds, so this comes
// before the download and not between two of its blocks.
esp_err_t panel_ota_begin(uint32_t size);

// The next part of the image, written and counted into its SHA-256.
esp_err_t panel_ota_write(const void *data, size_t length);

// The end of the image. ESP_ERR_INVALID_SIZE for an image shorter than it
// was said to be, ESP_ERR_INVALID_CRC for one whose SHA-256 is not that
// one, an error of ESP-IDF for an image it refuses, and ESP_OK once the
// next start boots it.
esp_err_t panel_ota_finish(const char *sha256);

// Gives up a write that began, and leaves the slot to the next one.
void panel_ota_abort(void);

// The running firmware is the one to keep. true when this ended a trial.
bool panel_ota_confirm(void);
