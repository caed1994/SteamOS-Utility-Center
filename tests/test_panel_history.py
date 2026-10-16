# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The history of the temperatures and the power, built and driven here.

Asked for: curves of the last 30 minutes of the temperature of the
processor and of the card, and of the power of the card. The panel keeps
30 minutes, one point every five seconds, and the page shows all of them.

firmware/companion/main/panel_history.c is that history without a screen.
The harness in tests/c/panel-history-harness.c drives it with a clock of
its own, so every rule here is about the real ring and not its shape.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
HARNESS = os.path.join(REPO, "tests", "c", "panel-history-harness.c")

STEP = 5000
CPU, GPU, WATTS = 0, 1, 2


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


def constant(name):
    with open(os.path.join(FIRMWARE, "panel_history.h"),
              encoding="utf-8") as handle:
        found = re.search(r"^#define %s (\d+)u?$" % name, handle.read(),
                          re.M)
    assert found, name
    return int(found.group(1))


@unittest.skipUnless(compiler(), "no C compiler here")
class HistoryTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-history")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_history.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_history.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def run_history(self, commands):
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    @staticmethod
    def steady(readings, start=0):
        """One answer in each step, the way a PC that answers every three
        seconds fills them: the reading, then the end of its step."""
        commands = ["tick %d" % start]
        now = start
        for one in readings:
            commands.append("offer %d %d %d" % one)
            now += STEP
            commands.append("tick %d" % now)
        return commands, now

    def read(self, commands, series, minutes, count):
        out = self.run_history(commands + ["read %d %d %d" % (series, minutes,
                                                             count)])[-1]
        points, readings = out.split("|")
        return ([None if one == "gap" else int(one)
                 for one in points.split()], int(readings))

    def test_the_numbers_are_the_ones_asked_for(self):
        """Five seconds, 30 minutes kept and shown, and 180 points drawn:
        two to one."""
        self.assertEqual(constant("PANEL_HISTORY_STEP_MS"), STEP)
        self.assertEqual(constant("PANEL_HISTORY_MINUTES"), 30)
        self.assertEqual(constant("PANEL_HISTORY_POINTS") * STEP,
                         30 * 60 * 1000)
        self.assertEqual(constant("PANEL_HISTORY_DRAWN") * 2,
                         constant("PANEL_HISTORY_POINTS"))

    def test_each_step_is_the_newest_answer_in_it(self):
        commands = ["tick 0", "offer 50 60 200", "offer 51 61 210",
                    "tick 5000", "state"]
        out = self.run_history(commands)
        self.assertEqual(out[-2:], ["1", "1 1"])
        points, readings = self.read(commands, CPU, 15, 180)
        self.assertEqual(points[-1], 51)
        self.assertEqual(points[:-1], [None] * 179)
        self.assertEqual(readings, 1)

    def test_a_step_with_no_answer_is_a_gap(self):
        """A PC that does not answer, and a panel whose radio rests, give
        no reading. The curve breaks there rather than drawing a line
        across what nobody measured."""
        commands = ["tick 0", "offer 50 60 200", "tick 5000",
                    "tick 10000", "offer 52 62 220", "tick 15000"]
        points, _ = self.read(commands, CPU, 15, 180)
        self.assertEqual(points[-3:], [50, None, 52])

    def test_a_sensor_with_no_reading_is_a_gap_in_its_series_alone(self):
        commands = ["tick 0", "offer 50 -1 200", "tick 5000"]
        self.assertEqual(self.read(commands, CPU, 15, 180)[0][-1], 50)
        self.assertIsNone(self.read(commands, GPU, 15, 180)[0][-1])
        self.assertEqual(self.read(commands, WATTS, 15, 180)[0][-1], 200)

    def test_a_late_clock_ends_every_step_it_missed(self):
        """Twenty seconds at once: the reading goes to the first step and
        the three after it are gaps, so the time axis stays true."""
        commands = ["tick 0", "offer 50 60 200", "tick 20000", "state"]
        self.assertEqual(self.run_history(commands)[-1], "4 4")
        points, _ = self.read(commands, CPU, 15, 180)
        self.assertEqual(points[-4:], [50, None, None, None])

    def test_steps_keep_their_place_between_ticks(self):
        """The ticks of the panel come every 200 ms and not on the step.
        The steps stay five seconds apart all the same."""
        commands = ["tick 0"]
        for now in range(200, 60001, 200):
            commands.append("tick %d" % now)
        out = self.run_history(commands + ["state"])
        self.assertEqual(out[-1], "12 12")

    def test_the_clock_may_wrap(self):
        """The milliseconds of the panel are 32 bits and wrap after 49
        days. The step after the wrap is one step."""
        start = 2 ** 32 - 3000
        commands = ["tick %d" % start, "offer 50 60 200",
                    "tick %d" % ((start + STEP) % 2 ** 32), "state"]
        self.assertEqual(self.run_history(commands)[-2:], ["1", "1 1"])

    def test_a_jump_past_the_whole_history_starts_again(self):
        """31 minutes, and the panel keeps 30."""
        commands, now = self.steady([(50, 60, 200)] * 10)
        commands += ["tick %d" % (now + 31 * 60 * 1000), "state"]
        self.assertEqual(self.run_history(commands)[-1], "0 11")

    def test_30_minutes_are_kept_and_no_more(self):
        readings = [(n % 100, 60, 200) for n in range(400)]
        commands, _ = self.steady(readings)
        self.assertEqual(self.run_history(commands + ["state"])[-1],
                         "360 400")
        points, count = self.read(commands, CPU, 30, 360)
        self.assertEqual(count, 360)
        self.assertEqual(points, [n % 100 for n in range(40, 400)])

    def test_a_drawn_point_is_the_mean_of_two(self):
        """30 minutes are 360 points in 180, two to one. The mean rounds
        half up."""
        readings = [(40 + (n % 2), 60, 100 + n % 4) for n in range(360)]
        commands, _ = self.steady(readings)
        points, count = self.read(commands, CPU, 30, 180)
        self.assertEqual(count, 360)
        self.assertEqual(set(points), {41})
        points, _ = self.read(commands, WATTS, 30, 180)
        self.assertEqual(points, [101, 103] * 90)
        points, _ = self.read(commands, CPU, 30, 360)
        self.assertEqual(points[-2:], [40, 41])

    def test_a_part_with_some_readings_is_their_mean(self):
        """A gap in a part does not pull it to nought."""
        commands = ["tick 0", "offer 60 60 200", "tick 5000", "tick 10000",
                    "tick 15000", "offer 64 60 200", "tick 20000"]
        points, count = self.read(commands, CPU, 30, 90)
        self.assertEqual(points[-1], 62)
        self.assertEqual(count, 2)

    def test_the_time_before_the_first_point_is_empty(self):
        commands, _ = self.steady([(50, 60, 200)] * 30)
        points, _ = self.read(commands, CPU, 15, 180)
        self.assertEqual(points[:150], [None] * 150)
        self.assertEqual(points[150:], [50] * 30)

    def test_the_range_of_a_window(self):
        readings = [(30, 60, 10)] * 200 + [(45, 61, 250), (70, 62, 300)]
        commands, _ = self.steady(readings)
        self.assertEqual(self.run_history(commands + ["range 0 15"])[-1],
                         "30 70")
        # The two hot points are the newest, and 30 is still in the window.
        self.assertEqual(self.run_history(commands + ["range 2 30"])[-1],
                         "10 300")
        self.assertEqual(self.run_history(["range 0 15"])[-1], "none")

    def test_a_reading_past_the_range_of_a_point_is_held_at_its_end(self):
        commands = ["tick 0", "offer 50 60 99999", "tick 5000"]
        self.assertEqual(self.read(commands, WATTS, 15, 180)[0][-1], 32767)


class SourceTest(unittest.TestCase):
    """Where the history lives and who feeds it, read off the firmware."""

    @staticmethod
    def code(name):
        with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
            text = handle.read()
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        return re.sub(r"//[^\n]*", " ", text)

    def test_the_history_lives_in_psram(self):
        """Internal memory is for the network and the drawing."""
        self.assertRegex(self.code("main.c"),
                         r"heap_caps_calloc\(1,sizeof\(panel_history_t\),"
                         r"MALLOC_CAP_SPIRAM\)")

    def test_it_is_fed_in_a_sleep_too(self):
        """The display goes dark after the set time and the PC is still
        asked. The history keeps going then, so it comes before the
        return of a sleeping display."""
        code = self.code("main.c")
        tick = code.index("panel_ui_history_tick(")
        asleep = code.index("if(atomic_load(&display_asleep))return;")
        self.assertLess(tick, asleep)

    def test_a_point_is_an_answer_and_not_the_last_one_again(self):
        """The state keeps the last reading while the PC is gone. A point
        needs a new answer, which the count of answers tells."""
        code = self.code("main.c")
        self.assertIn("state.answers++;", code)
        ui = self.code("ui.c")
        self.assertRegex(ui, r"s->online\s*&&\s*s->answers\s*!=\s*"
                             r"history_answers")

    def test_the_curve_is_the_sensor_of_the_tile(self):
        """The choice of a sensor for a tile is the choice for its curve."""
        ui = self.code("ui.c")
        body = ui[ui.index("void panel_ui_history_tick("):]
        body = body[:body.index("\n}\n")]
        self.assertIn("sensor_shown(s->cpu_sensors,s->cpu_sensor_count,"
                      "local.cpu_sensor,s->cpu_temp)", body)
        self.assertIn("sensor_shown(s->gpu_sensors,s->gpu_sensor_count,"
                      "local.gpu_sensor,s->gpu_temp)", body)


if __name__ == "__main__":
    unittest.main()
