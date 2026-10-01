// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The part of esp_pm that panel_clock.c uses. See tests/c/stubs/esp_err.h.
#pragma once
#include <stdbool.h>
#include "esp_err.h"
typedef enum {
    ESP_PM_CPU_FREQ_MAX,
    ESP_PM_APB_FREQ_MAX,
    ESP_PM_NO_LIGHT_SLEEP,
} esp_pm_lock_type_t;
typedef struct esp_pm_lock *esp_pm_lock_handle_t;
typedef struct {
    int max_freq_mhz;
    int min_freq_mhz;
    bool light_sleep_enable;
} esp_pm_config_t;
esp_err_t esp_pm_lock_create(esp_pm_lock_type_t type, int arg,
                             const char *name, esp_pm_lock_handle_t *handle);
esp_err_t esp_pm_lock_acquire(esp_pm_lock_handle_t handle);
esp_err_t esp_pm_lock_release(esp_pm_lock_handle_t handle);
esp_err_t esp_pm_lock_delete(esp_pm_lock_handle_t handle);
esp_err_t esp_pm_configure(const void *config);
