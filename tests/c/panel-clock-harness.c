// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Drives the clock measurement of panel_clock.c with two made-up cycle
// counters, one for each core, and a made-up time. A test on this machine
// reads what it prints.
//
// Commands on standard input, one to a line:
//
//   on <core>            the core the next reading comes from
//   run <us> <mhz>       time goes on, and both counters count at that speed
//   sample               panel_clock_sample
//   average              panel_clock_average, printed as "<mhz> <low %>"
//
// See tests/test_panel_clock.py.

#include <stdio.h>
#include <stdint.h>
#include <string.h>

#include "esp_cpu.h"
#include "esp_timer.h"
#include "esp_pm.h"
#include "panel_clock.h"

static int core;
static uint32_t counter[2] = {1000u, 4000000000u};
static int64_t now_us = 1000;

int esp_cpu_get_core_id(void) { return core; }
uint32_t esp_cpu_get_cycle_count(void) { return counter[core]; }
int64_t esp_timer_get_time(void) { return now_us; }
const char *esp_err_to_name(esp_err_t err) { return err ? "ERROR" : "ESP_OK"; }
esp_err_t esp_pm_lock_create(esp_pm_lock_type_t type, int arg,
                             const char *name, esp_pm_lock_handle_t *handle)
{
    (void)type; (void)arg; (void)name;
    *handle = (esp_pm_lock_handle_t)&core;
    return ESP_OK;
}
esp_err_t esp_pm_lock_acquire(esp_pm_lock_handle_t handle) { (void)handle; return ESP_OK; }
esp_err_t esp_pm_lock_release(esp_pm_lock_handle_t handle) { (void)handle; return ESP_OK; }
esp_err_t esp_pm_lock_delete(esp_pm_lock_handle_t handle) { (void)handle; return ESP_OK; }
esp_err_t esp_pm_configure(const void *config) { (void)config; return ESP_OK; }

int main(void)
{
    char line[128];
    while (fgets(line, sizeof line, stdin)) {
        int number;
        long long us;
        unsigned mhz;
        if (sscanf(line, "on %d", &number) == 1) {
            core = number & 1;
        } else if (sscanf(line, "run %lld %u", &us, &mhz) == 2) {
            now_us += us;
            for (int i = 0; i < 2; i++)
                counter[i] += (uint32_t)((uint64_t)us * mhz);
        } else if (strncmp(line, "sample", 6) == 0) {
            panel_clock_sample();
        } else if (strncmp(line, "average", 7) == 0) {
            unsigned mean, low;
            panel_clock_average(&mean, &low);
            printf("%u %u\n", mean, low);
        }
    }
    return 0;
}
