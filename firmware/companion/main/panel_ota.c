// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// See panel_ota.h.
#include "panel_ota.h"

#include <inttypes.h>
#include <stdio.h>

#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "mbedtls/md.h"

#include "panel_auth.h"

static const char *tag = "panel_ota";

static esp_ota_handle_t handle;
static const esp_partition_t *target;
static mbedtls_md_context_t digest;
static bool writing;
static uint32_t expected, written;

const char *panel_ota_version(void)
{
    return esp_app_get_description()->version;
}

void panel_ota_abort(void)
{
    if (!writing) return;
    esp_ota_abort(handle);
    mbedtls_md_free(&digest);
    writing = false;
}

esp_err_t panel_ota_begin(uint32_t size)
{
    panel_ota_abort();
    target = esp_ota_get_next_update_partition(NULL);
    if (!target) return ESP_ERR_NOT_FOUND;
    if (size == 0 || size > target->size) return ESP_ERR_INVALID_SIZE;
    esp_err_t err = esp_ota_begin(target, size, &handle);
    if (err != ESP_OK) return err;
    mbedtls_md_init(&digest);
    const mbedtls_md_info_t *sha = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (!sha || mbedtls_md_setup(&digest, sha, 0) != 0 ||
        mbedtls_md_starts(&digest) != 0) {
        esp_ota_abort(handle);
        mbedtls_md_free(&digest);
        return ESP_FAIL;
    }
    writing = true;
    expected = size;
    written = 0;
    ESP_LOGI(tag, "Writing %" PRIu32 " bytes to %s", size, target->label);
    return ESP_OK;
}

esp_err_t panel_ota_write(const void *data, size_t length)
{
    if (!writing) return ESP_ERR_INVALID_STATE;
    if (length > expected - written) return ESP_ERR_INVALID_SIZE;
    esp_err_t err = esp_ota_write(handle, data, length);
    if (err != ESP_OK) return err;
    if (mbedtls_md_update(&digest, data, length) != 0) return ESP_FAIL;
    written += (uint32_t)length;
    return ESP_OK;
}

esp_err_t panel_ota_finish(const char *sha256)
{
    if (!writing) return ESP_ERR_INVALID_STATE;
    bool whole = written == expected;
    unsigned char sum[32];
    char said[PANEL_AUTH_HEX];
    bool same = false;
    if (whole && mbedtls_md_finish(&digest, sum) == 0) {
        for (int i = 0; i < 32; i++) snprintf(said + 2 * i, 3, "%02x", sum[i]);
        same = panel_auth_equal(said, sha256);
    }
    mbedtls_md_free(&digest);
    writing = false;
    if (!same) {
        esp_ota_abort(handle);
        ESP_LOGW(tag, "The image is %s, so the running firmware stays",
                 whole ? "not the one of the offer" : "shorter than it was said to be");
        return whole ? ESP_ERR_INVALID_CRC : ESP_ERR_INVALID_SIZE;
    }
    // esp_ota_end checks the image itself: its header, its segments and the
    // hash the build appended.
    esp_err_t err = esp_ota_end(handle);
    if (err != ESP_OK) {
        ESP_LOGW(tag, "ESP-IDF refused the image: %s", esp_err_to_name(err));
        return err;
    }
    err = esp_ota_set_boot_partition(target);
    if (err == ESP_OK) ESP_LOGI(tag, "The next start boots %s on trial", target->label);
    return err;
}

bool panel_ota_confirm(void)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    if (!running || esp_ota_get_state_partition(running, &state) != ESP_OK)
        return false;
    if (state != ESP_OTA_IMG_PENDING_VERIFY) return false;
    if (esp_ota_mark_app_valid_cancel_rollback() != ESP_OK) return false;
    ESP_LOGI(tag, "The PC answered, so %s %s stays", running->label,
             panel_ota_version());
    return true;
}
