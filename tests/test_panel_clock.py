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
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(REPO, "firmware", "companion")
FIRMWARE = os.path.join(COMPANION, "main")


HARNESS = os.path.join(REPO, "tests", "c", "panel-clock-harness.c")
STUBS = os.path.join(REPO, "tests", "c", "stubs")


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


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


class MeasureTest(unittest.TestCase):
    """The mean speed of the clock, from the cycle counters."""

    def clock(self):
        return without_comments(read("main", "panel_clock.c"))

    def test_a_stretch_counts_only_on_one_core(self):
        """Each core has a counter of its own, and the network task moves
        between them. A stretch from one counter to the other is a number
        about neither."""
        sample = body(self.clock(), "void panel_clock_sample(void)")
        self.assertIn("int core = esp_cpu_get_core_id();", sample)
        self.assertIn("last_cycles[core]", sample)
        self.assertIn("last_us[core]", sample)
        self.assertLess(sample.index("portENTER_CRITICAL(&readings_lock);"),
                        sample.index("esp_cpu_get_core_id()"))

    def test_a_stretch_is_shorter_than_the_counter_turns_over(self):
        """32 bits at 240 MHz turn over after 17.9 seconds."""
        found = re.search(r"#define STRETCH_MAX_US \((\d+) \* 1000 \* 1000\)",
                          self.clock())
        self.assertIsNotNone(found)
        self.assertLess(int(found.group(1)) * 1000 * 1000,
                        (1 << 32) / 240)
        sample = body(self.clock(), "void panel_clock_sample(void)")
        self.assertIn("now - last_us[core] < STRETCH_MAX_US", sample)

    def test_the_share_runs_between_the_two_speeds(self):
        average = body(self.clock(),
                       "void panel_clock_average(unsigned *mhz, unsigned *low_percent)")
        self.assertIn("(PANEL_CLOCK_HIGH_MHZ - mean) * 100", average)
        self.assertIn("/ (PANEL_CLOCK_HIGH_MHZ - PANEL_CLOCK_LOW_MHZ)", average)
        self.assertIn("sum_cycles = 0;", average)


@unittest.skipUnless(compiler(), "no C compiler here")
class MeanSpeedTest(unittest.TestCase):
    """The measurement, built and driven with two made-up counters.

    The counters of the two cores start far apart, and the one of the
    second core close to where 32 bits turn over, so a stretch from one
    core to the other or across the turn shows as a wrong speed."""

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-clock")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", STUBS, "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_clock.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the stubs are plain C, so a build that
        # fails is a fault in the file.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_clock.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def averages(self, *commands):
        done = subprocess.run([self.program],
                              input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return [tuple(int(n) for n in line.split())
                for line in done.stdout.splitlines()]

    def loop(self, seconds, mhz, cores=(0,)):
        """The network loop: a reading every 100 ms, from the cores in
        turn."""
        commands = []
        for step in range(int(seconds * 10)):
            commands += ["on %d" % cores[step % len(cores)], "sample",
                         "run 100000 %d" % mhz]
        return commands

    def test_awake_it_is_the_full_speed(self):
        self.assertEqual(self.averages(*self.loop(5, 240), "sample",
                                       "average"), [(240, 0)])

    def test_asleep_and_idle_it_is_the_low_speed(self):
        self.assertEqual(self.averages(*self.loop(5, 80), "sample",
                                       "average"), [(80, 100)])

    def test_a_mix_comes_out_as_its_share(self):
        """A quarter of the time at 240 and the rest at 80 is a mean of
        120, and three quarters low."""
        commands = ["sample"]
        for _ in range(10):
            commands += ["run 25000 240", "run 75000 80", "sample"]
        self.assertEqual(self.averages(*commands, "average"), [(120, 75)])

    def test_two_cores_in_turn_still_measure_right(self):
        """The counters of the two cores are four thousand million apart
        here. A stretch from one to the other would say nonsense."""
        self.assertEqual(self.averages(*self.loop(6, 240, cores=(0, 1)),
                                       "on 0", "sample", "average"),
                         [(240, 0)])

    def test_the_counter_turning_over_is_not_a_fault(self):
        """The counter of the second core turns over in the first few
        seconds of this."""
        self.assertEqual(self.averages(*self.loop(30, 240, cores=(1,)),
                                       "on 1", "sample", "average"),
                         [(240, 0)])

    def test_a_stretch_too_long_to_trust_is_dropped(self):
        """Twenty seconds at 240 MHz is more cycles than 32 bits hold, so
        nothing is said about it, rather than something wrong."""
        self.assertEqual(self.averages("sample", "run 20000000 240",
                                       "sample", "average"), [(0, 0)])

    def test_each_average_starts_again(self):
        commands = self.loop(2, 240) + ["sample", "average"]
        commands += self.loop(2, 80) + ["sample", "average"]
        self.assertEqual(self.averages(*commands), [(240, 0), (80, 100)])

    def test_with_no_readings_it_says_nothing(self):
        self.assertEqual(self.averages("average"), [(0, 0)])


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

    def test_the_health_line_says_the_measured_speed(self):
        """The one way to see on the board that the clock went down.

        Read off the board: cpu=240MHz in a sleep. That reading asked
        esp_clk_cpu_freq, which says 240 from any code that runs, because
        esp_pm holds the full speed while a core is not idle. The line now
        carries the mean of the cycles counted over the time between, and
        the share of that time at the low speed."""
        code = self.main()
        self.assertIn("cpu_avg=%uMHz low=%u%%", code)
        self.assertIn("panel_clock_average(&clock_mhz,&clock_low);", code)
        self.assertNotIn("esp_clk_cpu_freq", without_comments(
            read("main", "panel_clock.c")))

    def test_the_clock_is_read_at_every_turn_of_the_network_loop(self):
        task = body(self.main(), "static void network_task(void *arg)")
        loop = task[task.index("for (;;) {"):]
        self.assertLess(loop.index("panel_clock_sample();"),
                        loop.index("if (rest!=rest_wanted)"))


if __name__ == "__main__":
    unittest.main()
