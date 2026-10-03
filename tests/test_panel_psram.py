# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""What comes out of PSRAM first, so the internal memory stays for the display.

Asked for: more internal memory, so that the changes that make the scroll
faster have room. The page of the panel read 33 KB free and 20 KB at the
least. The objects of LVGL, the answer of the PC with its JSON, and three
task stacks go to PSRAM now, and each falls back to internal memory when
PSRAM has none. The stack of LVGL stays internal, for the speed of the
drawing.

The stack of the network task went to PSRAM as well, and came back.
Reported from the board: the first answer of the PC restarted the panel at
an assert, and every start after it did the same. The task confirms a new
firmware at that answer, and that call maps flash. A map of flash freezes
the caches and needs an internal stack.

A line of the log at the end of the start says the internal memory free
after each step, so the step that takes it is known.

firmware/companion/main/panel_psram.h holds the rules, and the tests below
hold where they apply.
"""

from __future__ import annotations

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(REPO, "firmware", "companion")
FIRMWARE = os.path.join(COMPANION, "main")


def raw(name):
    with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
        return handle.read()


def code(name):
    text = re.sub(r"/\*.*?\*/", " ", raw(name), flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def defaults():
    with open(os.path.join(COMPANION, "sdkconfig.defaults"), encoding="utf-8") as handle:
        return handle.read()


def function(text, name):
    found = re.search(r"\n[^\n]*\b%s\([^)]*\)\s*\{(.*?)\n\}" % re.escape(name), text, re.S)
    if not found:
        raise AssertionError("no function " + name)
    return found.group(1)


class RulesTest(unittest.TestCase):

    def test_psram_first_and_internal_memory_after(self):
        header = code("panel_psram.h")
        self.assertRegex(header, r"#define PANEL_PSRAM_FIRST 2, MALLOC_CAP_SPIRAM \| MALLOC_CAP_8BIT, "
                                 r"MALLOC_CAP_INTERNAL \| MALLOC_CAP_8BIT")
        for call in ("heap_caps_malloc_prefer(size, PANEL_PSRAM_FIRST)",
                     "heap_caps_calloc_prefer(count, size, PANEL_PSRAM_FIRST)",
                     "heap_caps_realloc_prefer(memory, size, PANEL_PSRAM_FIRST)"):
            self.assertIn(call, header)

    def test_a_stack_in_psram_falls_back_to_internal_memory(self):
        task = function(code("panel_psram.h"), "panel_psram_task")
        first = task.index("xTaskCreatePinnedToCoreWithCaps(")
        self.assertIn("MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT", task[first:])
        self.assertLess(first, task.index("return xTaskCreatePinnedToCore(code, name, stack, NULL, "
                                          "priority, NULL, core);"))

    def test_a_stack_in_psram_needs_the_cache_on_while_flash_is_written(self):
        # ESP-IDF: a stack in PSRAM must never be in use while the cache is
        # off. A write to flash leaves the cache on only with XIP from PSRAM.
        self.assertIn("#if !CONFIG_SPIRAM_XIP_FROM_PSRAM\n#error", raw("panel_psram.h"))
        settings = defaults()
        self.assertRegex(settings, r"(?m)^CONFIG_SPIRAM_XIP_FROM_PSRAM=y$")
        self.assertNotRegex(settings, r"(?m)^CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM=n")


class LvglTest(unittest.TestCase):

    def test_lvgl_takes_its_memory_from_this_file(self):
        settings = defaults()
        self.assertRegex(settings, r"(?m)^CONFIG_LV_USE_CUSTOM_MALLOC=y$")
        self.assertNotRegex(settings, r"(?m)^CONFIG_LV_USE_CLIB_MALLOC=y")
        mem = code("panel_lvgl_mem.c")
        for name in ("lv_mem_init", "lv_mem_deinit", "lv_mem_add_pool", "lv_mem_remove_pool",
                     "lv_malloc_core", "lv_realloc_core", "lv_free_core", "lv_mem_monitor_core",
                     "lv_mem_test_core"):
            function(mem, name)
        self.assertIn("return panel_psram_malloc(size);", function(mem, "lv_malloc_core"))
        self.assertIn("return panel_psram_realloc(p, new_size);", function(mem, "lv_realloc_core"))
        self.assertIn("heap_caps_free(p);", function(mem, "lv_free_core"))

    def test_the_link_keeps_the_file(self):
        with open(os.path.join(FIRMWARE, "CMakeLists.txt"), encoding="utf-8") as handle:
            build = handle.read()
        self.assertIn('"panel_lvgl_mem.c"', build)
        self.assertIn('INTERFACE_LINK_LIBRARIES "-u lv_mem_init"', build)

    def test_the_stack_of_lvgl_stays_internal(self):
        display = code("panel_display.c")
        self.assertNotIn("task_stack_caps", display)
        self.assertIn("port.task_stack=PANEL_LVGL_STACK;", display)


class WhereTest(unittest.TestCase):

    def test_the_answer_of_the_pc_and_its_json_come_out_of_psram(self):
        main = code("main.c")
        self.assertIn("response_t *out=panel_psram_calloc(1,sizeof(*out));", main)
        self.assertNotRegex(main, r"response_t \*out=calloc\(")
        self.assertIn("static void *json_alloc(size_t size){return panel_psram_malloc(size);}", main)
        start = function(main, "app_main")
        hooks = start.index("cJSON_InitHooks(&json);")
        self.assertIn("cJSON_Hooks json={.malloc_fn=json_alloc,.free_fn=heap_caps_free};", start)
        # Before the first task that parses an answer.
        self.assertLess(hooks, start.index("xTaskCreatePinnedToCore(network_task"))
        self.assertLess(hooks, start.index("panel_ui_create("))

    def test_three_stacks_are_in_psram(self):
        main = code("main.c")
        self.assertIn('panel_psram_task(sound_task,"panel_sound",6144,3,tskNO_AFFINITY)', main)
        self.assertIn('panel_psram_task(motion_task, "panel_motion", MOTION_TASK_STACK,',
                      code("panel_motion.c"))
        self.assertIn('panel_psram_task(key_task,"panel_pwrkey",PWRKEY_TASK_STACK,'
                      'PWRKEY_TASK_PRIORITY,tskNO_AFFINITY)', code("panel_power.c"))
        for name in ("main.c", "panel_motion.c", "panel_power.c"):
            self.assertNotRegex(code(name), r"\bxTaskCreate\(", name)

    def test_the_task_that_maps_flash_has_an_internal_stack(self):
        # The network task writes and confirms the updates of the firmware,
        # and those calls map flash. esp_mmu_map stops at an assert when the
        # stack is not internal.
        main = code("main.c")
        self.assertRegex(main, r'xTaskCreatePinnedToCore\(network_task,"panel_network",12288,NULL,'
                               r'\s*PANEL_NETWORK_PRIORITY,NULL,0\)')
        self.assertNotIn("panel_psram_task(network_task", main)
        self.assertIn("It is not safe for a task that maps flash.", raw("panel_psram.h"))
        # No other source calls the functions that map flash.
        for name in sorted(os.listdir(FIRMWARE)):
            if name.endswith(".c") and name not in ("main.c", "panel_ota.c"):
                self.assertNotRegex(code(name), r"\bpanel_ota_(begin|finish|confirm)\(", name)
                self.assertNotRegex(code(name), r"\besp_(ota|partition_mmap|mmu_map)_?\w*\(", name)

    def test_a_map_of_flash_from_a_stack_in_psram_is_refused(self):
        # A refusal and a line in the log, and not a restart at every start.
        ota = code("panel_ota.c")
        guard = function(ota, "may_map_flash")
        self.assertIn("if (esp_ptr_in_dram((const void *)esp_cpu_get_sp())) return true;", guard)
        self.assertIn("return false;", guard)
        for name, call in (("panel_ota_begin", "esp_ota_get_next_update_partition("),
                           ("panel_ota_finish", "esp_ota_end(handle)"),
                           ("panel_ota_confirm", "esp_ota_get_running_partition()")):
            body = function(ota, name)
            self.assertLess(body.index("may_map_flash("), body.index(call), name)

    def test_the_start_says_the_memory_after_each_step(self):
        start = function(code("main.c"), "app_main")
        steps = ["start", "display", "sensors", "sound", "screen", "netif", "wifi_init",
                 "wifi_start", "network"]
        places = [start.index('ram_step("%s");' % step) for step in steps]
        self.assertEqual(places, sorted(places))
        self.assertLess(start.index("panel_display_start()"), places[1])
        self.assertLess(start.index("panel_ui_create("), places[4])
        self.assertLess(places[-1], start.index('ESP_LOGI("panel_ram"'))


if __name__ == "__main__":
    unittest.main()
