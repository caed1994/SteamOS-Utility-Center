// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Memory out of PSRAM first, so the internal memory stays for the display.
//
// The page of the panel read 33 KB of internal memory free and 20 KB at
// the least. The bounce buffers of the display take 75 KB of it, and they
// have to: the display reads them by DMA. Much of the rest went to things
// that do not need internal memory at all, and those come out of PSRAM
// now:
//
//   the objects of LVGL     panel_lvgl_mem.c, about 36 KB for the band
//   the answer of the PC    8 KB and its JSON at every poll
//   three task stacks       the sound, the motion and the key
//
// Each falls back to internal memory when PSRAM has none.
//
// A stack in PSRAM is safe for a task that writes to flash, for one
// reason. ESP-IDF says a task stack in PSRAM must never be in use while
// the cache is off, and a write to flash switches the cache off. With
// CONFIG_SPIRAM_XIP_FROM_PSRAM it does not (docs: spi_flash_concurrency):
// a write takes a mutex and leaves the cache on. The build stops if that
// option goes.
//
// It is not safe for a task that maps flash. esp_mmu_map, under
// esp_partition_mmap, freezes the caches and stops at an assert when the
// stack is not internal (esp_cache_utils.c). Each call of esp_ota_ that
// reads the state of the partitions maps flash, so the network task, which
// writes and confirms the updates, keeps an internal stack: see main.c.
// panel_ota.c refuses those calls from a stack in PSRAM.
#pragma once

#include <stddef.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#if !CONFIG_SPIRAM_XIP_FROM_PSRAM
#error "task stacks in PSRAM need CONFIG_SPIRAM_XIP_FROM_PSRAM, see panel_psram.h"
#endif

#define PANEL_PSRAM_FIRST 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT

static inline void *panel_psram_malloc(size_t size)
{
    return heap_caps_malloc_prefer(size, PANEL_PSRAM_FIRST);
}

static inline void *panel_psram_calloc(size_t count, size_t size)
{
    return heap_caps_calloc_prefer(count, size, PANEL_PSRAM_FIRST);
}

static inline void *panel_psram_realloc(void *memory, size_t size)
{
    return heap_caps_realloc_prefer(memory, size, PANEL_PSRAM_FIRST);
}

// A task with its stack in PSRAM, on that core or on either with
// tskNO_AFFINITY. A task that cannot have one gets an internal stack and a
// line in the log. None of these tasks ends, so none is deleted.
static inline BaseType_t panel_psram_task(TaskFunction_t code, const char *name, uint32_t stack,
                                          UBaseType_t priority, BaseType_t core)
{
    if (xTaskCreatePinnedToCoreWithCaps(code, name, stack, NULL, priority, NULL, core,
                                        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) == pdPASS)
        return pdPASS;
    ESP_LOGW("panel_psram", "%s: no stack in PSRAM, so an internal one", name);
    return xTaskCreatePinnedToCore(code, name, stack, NULL, priority, NULL, core);
}
