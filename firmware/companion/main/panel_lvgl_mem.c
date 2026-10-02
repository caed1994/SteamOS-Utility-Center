// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The memory of LVGL out of PSRAM first, with CONFIG_LV_USE_CUSTOM_MALLOC.
//
// With the C library, a block under 16 KB came out of the internal memory
// (CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL), and nearly every object of LVGL is
// such a block. Measured on the host and taken to the sizes of this chip,
// the band holds about 36 KB of them, and the page of the panel 18 KB more
// while it is open. See panel_psram.h.
//
// The cost is a slower read of the objects while LVGL draws: they come
// through the cache. The card of the frames on the page of the panel says
// what that costs.
#include "lvgl.h"

#include "panel_psram.h"

void lv_mem_init(void)
{
}

void lv_mem_deinit(void)
{
}

lv_mem_pool_t lv_mem_add_pool(void *mem, size_t bytes)
{
    LV_UNUSED(mem);
    LV_UNUSED(bytes);
    return NULL;
}

void lv_mem_remove_pool(lv_mem_pool_t pool)
{
    LV_UNUSED(pool);
}

void *lv_malloc_core(size_t size)
{
    return panel_psram_malloc(size);
}

void *lv_realloc_core(void *p, size_t new_size)
{
    return panel_psram_realloc(p, new_size);
}

void lv_free_core(void *p)
{
    heap_caps_free(p);
}

void lv_mem_monitor_core(lv_mem_monitor_t *mon_p)
{
    LV_UNUSED(mon_p);
}

lv_result_t lv_mem_test_core(void)
{
    return LV_RESULT_OK;
}
