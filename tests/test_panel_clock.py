# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The clock of the panel CPU: full speed while the display is awake, and
80 MHz while it sleeps.

Asked for: less power while the display sleeps. None of this runs here,
because the container has no ESP32-S3. The rules hold the shape, and each
one is a way the change breaks that the board would show late or never.
The reasons are in firmware/companion/main/panel_clock.c, with the places
in ESP-IDF 5.5.5 that they were read from.
"""

from __future__ import annotations

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(REPO, "firmware", "companion")
FIRMWARE = os.path.join(COMPANION, "main")


def read(*parts):
    with open(os.path.join(COMPANION, *parts), encoding="utf-8") as handle:
        return handle.read()


def without_comments(text):
    """The C with its comments taken out, because these read calls."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def body(code, start):
    found = re.search(re.escape(start) + r".*?\n\}", code, re.S)
    assert found, start
    return found.group(0)


class ConfigurationTest(unittest.TestCase):
    def test_power_management_is_on_and_light_sleep_is_not(self):
        """The speed of the clock only. Tickless idle is the way into light
        sleep, and the RGB panel holds the chip out of it anyway."""
        defaults = read("sdkconfig.defaults")
        self.assertRegex(defaults, r"(?m)^CONFIG_PM_ENABLE=y$")
        self.assertNotRegex(defaults,
                            r"(?m)^CONFIG_FREERTOS_USE_TICKLESS_IDLE=y")
        self.assertNotRegex(defaults, r"(?m)^CONFIG_PM_DFS_INIT_AUTO=y",
                            "that configures esp_pm at the start with the "
                            "crystal as the low speed")

    def test_the_build_stops_if_the_setting_does_not_take(self):
        """Kconfig drops a name it does not know without a word."""
        code = read("main", "panel_clock.c")
        self.assertRegex(code, r"#if !CONFIG_PM_ENABLE\s*\n#error")

    def test_the_file_is_built_and_its_component_is_named(self):
        cmake = read("main", "CMakeLists.txt")
        self.assertIn('"panel_clock.c"', cmake)
        self.assertRegex(cmake, r"REQUIRES[^\n]*\besp_pm\b")


class SpeedTest(unittest.TestCase):
    def clock(self):
        return without_comments(read("main", "panel_clock.c"))

    def number(self, name):
        found = re.search(r"#define %s (\d+)" % name, self.clock())
        self.assertIsNotNone(found, name)
        return int(found.group(1))

    def test_the_low_speed_keeps_the_psram_at_its_speed(self):
        """Below 80 MHz the CPU runs from the crystal, and esp_pm then puts
        the PSRAM down to 20 MHz with it. The frame buffers are in PSRAM,
        and the display reads them at every frame."""
        self.assertGreaterEqual(self.number("PANEL_CLOCK_LOW_MHZ"), 80)

    def test_the_high_speed_is_the_speed_the_panel_always_had(self):
        defaults = read("sdkconfig.defaults")
        self.assertRegex(defaults, r"(?m)^CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240=y")
        self.assertEqual(self.number("PANEL_CLOCK_HIGH_MHZ"), 240)

    def test_the_configuration_uses_both_and_no_light_sleep(self):
        init = body(self.clock(), "esp_err_t panel_clock_init(void)")
        self.assertIn(".max_freq_mhz=PANEL_CLOCK_HIGH_MHZ", init)
        self.assertIn(".min_freq_mhz=PANEL_CLOCK_LOW_MHZ", init)
        self.assertIn(".light_sleep_enable=false", init)

    def test_the_full_speed_is_held_before_the_configuration(self):
        """The other way round, the CPU drops to the low speed for the
        moment between the two, while the startup still draws."""
        init = body(self.clock(), "esp_err_t panel_clock_init(void)")
        self.assertIn("ESP_PM_CPU_FREQ_MAX", init)
        self.assertLess(init.index("esp_pm_lock_acquire(awake)"),
                        init.index("esp_pm_configure("))

    def test_a_second_call_with_the_same_value_does_nothing(self):
        """The lock counts. Two releases in a row are an error, and two
        takes in a row hold the full speed through every sleep after."""
        low = body(self.clock(), "void panel_clock_low(bool low)")
        self.assertRegex(low, r"if\(!awake \|\| low==is_low\)return;")
        self.assertRegex(low, r"is_low=low;\s*\}$")


class SleepTest(unittest.TestCase):
    def main(self):
        return without_comments(read("main", "main.c"))

    def door(self):
        return body(self.main(),
                    "static void display_sleeping(bool sleep,bool by_hand)")

    def test_full_speed_before_the_display_comes_back(self):
        """So the first frame after a sleep is drawn at it."""
        door = self.door()
        self.assertLess(door.index("if(!sleep)panel_clock_low(false);"),
                        door.index("panel_display_standby("))

    def test_low_speed_only_once_the_display_is_down(self):
        door = self.door()
        self.assertLess(door.index("panel_display_standby("),
                        door.index("if(sleep)panel_clock_low(true);"))

    def test_a_display_that_did_not_come_up_goes_back_to_low_speed(self):
        failed = re.search(r"if\(err!=ESP_OK\)\{(.*?)\n    \}", self.door(),
                           re.S)
        self.assertIsNotNone(failed)
        self.assertIn("if(!sleep)panel_clock_low(true);", failed.group(1))

    def test_the_clock_is_set_up_before_the_display_starts(self):
        start = body(self.main(), "void app_main(void)")
        self.assertLess(start.index("panel_clock_init()"),
                        start.index("panel_display_start()"))

    def test_the_health_line_says_the_speed(self):
        """The one way to see on the board that the clock went down."""
        self.assertIn("cpu=%uMHz", self.main())
        self.assertIn("panel_clock_mhz()", self.main())


if __name__ == "__main__":
    unittest.main()
