# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lift to wake: the accelerometer of the panel, and what counts as a lift.

Asked for: the display comes back when somebody lifts the panel, after it
went dark by itself, and as an option. A display the button switched off
stays off, as it does for a touch.

firmware/companion/main/panel_lift.c decides what a lift is, and the
harness in tests/c/panel-lift-harness.c drives it here with readings of
its own. panel_motion.c reads the QMI8658 of the board, and the rules
below hold where it reads, what it writes, and when it watches.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
HARNESS = os.path.join(REPO, "tests", "c", "panel-lift-harness.c")

REST = (0, 0, 1000)


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


def code(name):
    with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
        text = handle.read()
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def tilted(degrees):
    """Gravity in mg with the panel tilted about one axis."""
    angle = math.radians(degrees)
    return (round(1000 * math.sin(angle)), 0, round(1000 * math.cos(angle)))


@unittest.skipUnless(compiler(), "no C compiler here")
class LiftTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-lift")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_lift.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_lift.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def lifts(self, *readings):
        """The answer to each reading, as a string of 0 and 1."""
        commands = ["reset" if one == "reset" else "feed %d %d %d" % one
                    for one in readings]
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return "".join(done.stdout.split())

    def settled(self, *readings):
        return self.lifts(REST, REST, REST, *readings)[3:]

    def test_at_rest_nothing_happens(self):
        self.assertEqual(self.settled(*[REST] * 50), "0" * 50)

    def test_a_tilt_of_twenty_degrees_held_is_a_lift(self):
        """Lifted and turned toward the face: the second reading of it."""
        self.assertEqual(self.settled(tilted(20), tilted(20)), "01")

    def test_a_tilt_of_five_degrees_is_not(self):
        self.assertEqual(self.settled(*[tilted(5)] * 10), "0" * 10)

    def test_one_jolt_is_not_a_lift(self):
        """A door that closes shakes a wall for a moment."""
        self.assertEqual(self.settled((0, 0, 1300), REST, (250, 0, 970),
                                      REST, REST), "00000")

    def test_a_lift_straight_up_is_one(self):
        """Up without a tilt: more than a tenth and a half of g for two
        readings, which is how a hand starts a lift."""
        self.assertEqual(self.settled((0, 0, 1200), (0, 0, 1180)), "01")

    def test_the_noise_of_a_sensor_is_not(self):
        noise = [(17 * (n % 3) - 17, 13 * (n % 5) - 26, 1000 + 9 * (n % 4))
                 for n in range(60)]
        self.assertEqual(self.settled(*noise), "0" * 60)

    def test_a_slow_drift_is_followed(self):
        """A sensor that warms up moves by a few mg; the rest moves with
        it and nothing wakes."""
        drift = [(0, 0, 1000 + 2 * n) for n in range(150)]
        self.assertEqual(self.settled(*drift), "0" * 150)

    def test_the_first_readings_only_find_the_rest(self):
        """The sensor has just been switched on. The rest is the third
        reading, and nothing before it counts."""
        self.assertEqual(self.lifts(tilted(40), tilted(40), REST, REST,
                                    tilted(40), tilted(40)), "000001")

    def test_a_reading_far_from_one_g_is_left_out(self):
        """A sensor without data reads nought, and a panel in free fall
        nearly nought. Neither is a lift, and neither breaks one off."""
        self.assertEqual(self.settled((0, 0, 0), (0, 0, 120), (0, 0, 2600)),
                         "000")
        self.assertEqual(self.settled(tilted(30), (0, 0, 0), tilted(30)),
                         "001")

    def test_a_reset_starts_over(self):
        """The task resets after a lift, so the next lift needs a rest of
        its own first: the panel held still in the hand is that rest, and
        it wakes nothing more."""
        out = self.lifts(REST, REST, REST, tilted(30), tilted(30), "reset",
                         tilted(30), tilted(30), tilted(30), tilted(30))
        self.assertEqual(out, "00001" + "0000")

    def test_the_numbers_are_the_ones_meant(self):
        header = code("panel_lift.h")
        for name, value in (("PANEL_LIFT_MG", "150"),
                            ("PANEL_LIFT_READINGS", "2"),
                            ("PANEL_LIFT_SETTLE", "3")):
            self.assertRegex(header, r"#define %s %s\b" % (name, value))


class SensorTest(unittest.TestCase):
    """panel_motion.c: the QMI8658 and nothing else."""

    def test_the_numbers_are_those_of_sensorlib(self):
        motion = code("panel_motion.c")
        for name, value in (("QMI8658_ADDRESS", "0x6B"),
                            ("QMI8658_ADDRESS_OTHER", "0x6A"),
                            ("QMI8658_WHO_AM_I", "0x00"),
                            ("QMI8658_ID", "0x05"),
                            ("QMI8658_CTRL1", "0x02"),
                            ("QMI8658_CTRL2", "0x03"),
                            ("QMI8658_CTRL7", "0x08"),
                            ("QMI8658_STATUS0", "0x2E"),
                            ("QMI8658_AX_L", "0x35"),
                            ("QMI8658_RESET", "0x60"),
                            ("QMI8658_RESET_VALUE", "0xB0"),
                            ("CTRL1_VALUE", "0x40"),
                            ("CTRL2_VALUE", "0x1D"),
                            ("MG_FULL_SCALE", "4000")):
            self.assertRegex(motion, r"#define %s\s+%s\b" % (name, value))

    def test_it_writes_to_its_own_device_only(self):
        """A device of its own on the bus, at the address of the sensor.
        The power chip at 0x34 is panel_battery.c's, and its writes are
        counted there."""
        motion = code("panel_motion.c")
        self.assertNotIn("0x34", motion)
        self.assertEqual(motion.count("i2c_master_transmit("), 1)
        self.assertEqual(motion.count("i2c_master_bus_add_device("), 1)
        writes = re.findall(r"sensor_write\((\w+),", motion)
        self.assertEqual(set(writes), {"QMI8658_RESET", "QMI8658_CTRL1",
                                       "QMI8658_CTRL2", "QMI8658_CTRL7"})

    def test_nothing_is_written_before_the_identity(self):
        motion = code("panel_motion.c")
        start = motion[motion.index("esp_err_t panel_motion_init(void)"):]
        self.assertLess(start.index("QMI8658_ID"),
                        start.index("sensor_write("))

    def test_the_accelerometer_is_off_until_a_watch(self):
        motion = code("panel_motion.c")
        start = motion[motion.index("esp_err_t panel_motion_init(void)"):]
        self.assertIn("sensor_write(QMI8658_CTRL7, ACCEL_OFF)", start)
        self.assertIn("wanted ? ACCEL_ON : ACCEL_OFF", motion)

    def test_each_watch_starts_with_a_fresh_rest(self):
        motion = code("panel_motion.c")
        task = motion[motion.index("static void motion_task("):
                      motion.index("esp_err_t panel_motion_init(void)")]
        switch = task[task.index("if (wanted != active)"):
                      task.index("if (active)")]
        self.assertIn("panel_lift_reset(&lift);", switch)
        self.assertIn("atomic_store(&lifted, false);", switch)


class WhereTest(unittest.TestCase):
    """Who reads the sensor, and when a lift counts."""

    def ui_tick(self):
        main = code("main.c")
        found = re.search(r"static void ui_tick\(lv_timer_t \*timer\).*?\n\}",
                          main, re.S)
        self.assertIsNotNone(found)
        return found.group(0)

    def test_a_task_of_its_own_reads_it(self):
        """Not the task that draws, where a stalled bus freezes the screen,
        and not the network task, which a PC that does not answer holds
        for seconds."""
        motion = code("panel_motion.c")
        self.assertIn('xTaskCreate(motion_task, "panel_motion"', motion)
        tick = self.ui_tick()
        self.assertIn("panel_motion_take_lift()", tick)
        self.assertNotIn("i2c_master", tick)
        main = code("main.c")
        network = main[main.index("static void network_task"):]
        self.assertNotIn("panel_motion", network[:network.index("\n}\n")])

    def test_a_lift_wakes_only_a_sleep_of_the_timeout(self):
        tick = self.ui_tick()
        self.assertRegex(tick, r"if\(!atomic_load\(&asleep_by_hand\)\)\{\s*"
                               r"bool lifted=panel_motion_take_lift\(\);")
        self.assertIn("if(lifted || panel_display_touched())"
                      "display_sleeping(false,false);", tick)

    def test_the_watch_follows_the_sleep_and_the_setting(self):
        main = code("main.c")
        sleeping = main[main.index("static void display_sleeping("):]
        sleeping = sleeping[:sleeping.index("\n}\n")]
        self.assertIn("panel_motion_watch(sleep && !by_hand && "
                      "atomic_load(&lift_wake));", sleeping)
        self.assertLess(sleeping.index("atomic_store(&asleep_by_hand"),
                        sleeping.index("panel_motion_watch("))

    def test_switching_it_off_ends_a_watch(self):
        main = code("main.c")
        setter = main[main.index("static void setting_set("):]
        setter = setter[:setter.index("\n}\n")]
        self.assertIn("atomic_store(&lift_wake,value!=0);", setter)
        self.assertIn("if(!value)panel_motion_watch(false);", setter)
        self.assertIn('key==PANEL_LIFT_WAKE?"lift_wake":', setter)

    def test_it_is_on_until_somebody_switches_it_off(self):
        main = code("main.c")
        self.assertRegex(main, r"\.lift_wake=true\s*[,}]")
        self.assertIn('nvs_get_u8(h,"lift_wake",&value)', main)
        self.assertLess(main.index("panel_battery_init();"),
                        main.index("panel_motion_init();"))

    def test_the_build_knows_the_files(self):
        with open(os.path.join(FIRMWARE, "CMakeLists.txt"),
                  encoding="utf-8") as handle:
            build = handle.read()
        self.assertIn('"panel_lift.c"', build)
        self.assertIn('"panel_motion.c"', build)


if __name__ == "__main__":
    unittest.main()
