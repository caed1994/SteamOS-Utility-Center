# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The button on the side of the wall panel.

Reported from the board: one press did nothing and two worked. The first
guess was the rate of the poll, and the rate was fixed. The fault stayed,
with key_slowest at 15 to 17 ms in the health line.

The cause was the level of the pin. On the schematic, the key reaches EXIO4
through T1, an N-channel MOSFET, so the pin is high while the key is pressed.
The firmware read it as low while pressed. Then the machine took the gap
between two presses for one press, and only a double press counted.

These tests hold both halves of what the machine promises, at the rate
panel_power.c keeps: an ordinary press is seen exactly one time, and a
contact bounce is never seen at all. They sweep the phase of the poll,
because a person does not press in time with the loop. And they drive the
machine with the level that the board gives, both ways round.

The numbers in PANEL_KEY_* are the ones that were measured. A change to
them that breaks either half fails here rather than on a wall.
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
HARNESS = os.path.join(REPO, "tests", "c", "panel-key-harness.c")

# The rate the key task keeps, and what the machine works to. Read from the
# firmware rather than repeated here: two copies of a number drift.
POLL_MS = None
SHORTEST_MS = None


def constant(path, name):
    with open(path) as handle:
        found = re.search(r"^#define %s (\d+)" % name, handle.read(), re.M)
    assert found, "%s names no %s" % (path, name)
    return int(found.group(1))


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


@unittest.skipUnless(compiler(), "no C compiler here")
class PanelKeyTest(unittest.TestCase):
    """The real state machine, built and driven."""

    @classmethod
    def setUpClass(cls):
        cls.poll = constant(os.path.join(FIRMWARE, "panel_power.c"),
                            "PWRKEY_PERIOD_MS")
        cls.shortest = constant(os.path.join(FIRMWARE, "panel_key.h"),
                                "PANEL_KEY_SHORTEST_MS")
        cls.settle = constant(os.path.join(FIRMWARE, "panel_key.h"),
                              "PANEL_KEY_SETTLE_MS")
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-key")
        done = subprocess.run(
            [compiler(), "-Wall", "-Wextra", "-Werror", "-I", FIRMWARE,
             "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_key.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_key.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def events(self, hold, poll=None):
        """(lowest, highest) events for that press, over every phase."""
        done = subprocess.run(
            [self.program, str(poll or self.poll), str(hold)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        low, high = done.stdout.split()
        return int(low), int(high)

    def test_an_ordinary_press_is_seen_exactly_one_time(self):
        """120 ms is a deliberate tap. Nobody has to press it twice."""
        self.assertEqual(self.events(120), (1, 1))

    def test_a_long_press_is_seen_one_time_as_well(self):
        """Up to the point where it stops being a short press."""
        for hold in (200, 400, 700, 900):
            with self.subTest(hold=hold):
                self.assertEqual(self.events(hold), (1, 1))

    def test_a_press_held_past_the_window_does_nothing(self):
        """A long hold belongs to the power chip, not to this."""
        self.assertEqual(self.events(2000), (0, 0))

    def test_a_contact_bounce_is_never_a_press(self):
        """The other half. A press that arrives by itself is worse than a
        press that needs a second try."""
        for width in (1, 3, 5, 8):
            with self.subTest(width=width):
                self.assertEqual(self.events(width), (0, 0))

    def test_the_shortest_press_it_promises_works(self):
        """PANEL_KEY_SHORTEST_MS is a promise, so it is kept at the rate
        panel_power.c polls at."""
        self.assertEqual(self.events(self.shortest + self.poll), (1, 1))

    def test_the_shortest_press_grows_with_the_period(self):
        """A slow poll loses a short press. The number that decides is the
        period, and this says by how much."""
        worked = [poll for poll in (20, 40, 60, 80, 120)
                  if self.events(120, poll=poll) == (1, 1)]
        self.assertIn(20, worked)
        self.assertNotIn(120, worked,
                         "a 120 ms press cannot be seen by a 120 ms poll")

    def test_the_rate_the_task_keeps_is_fast_enough_for_a_tap(self):
        """The whole point of the change. A 120 ms tap has to survive the
        period that panel_power.c asks for."""
        self.assertLessEqual(self.poll * 2, 120,
                             "the poll is too slow for an ordinary tap")

    def test_the_settle_time_is_not_longer_than_the_shortest_press(self):
        self.assertLessEqual(self.settle, self.shortest)

    def pin(self, *presses, reading="high"):
        """(lowest, highest) events for those presses on the board.

        Each press is (start, length) in ms, and EXIO4 is high during it.
        A reading of "low" reads the pin as the firmware did before."""
        command = [self.program, "pin", str(self.poll), reading]
        for start, length in presses:
            command += [str(start), str(length)]
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        low, high = done.stdout.split()
        return int(low), int(high)

    def pressed(self, levels, pin):
        done = subprocess.run([self.program, "level", "%x" % levels,
                               "%x" % pin],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip() == "1"

    def test_one_press_on_the_board_is_one_event(self):
        """The report: one press has to be enough."""
        self.assertEqual(self.pin((5000, 120)), (1, 1))

    def test_two_presses_on_the_board_are_two_events(self):
        """A double press is two presses, close together or far apart."""
        self.assertEqual(self.pin((5000, 100), (5250, 100)), (2, 2))
        self.assertEqual(self.pin((3000, 120), (7000, 120)), (2, 2))

    def test_the_old_reading_gives_the_fault_from_the_board(self):
        """Read as low while pressed, one press does nothing and a double
        press gives one event. That is what the board did."""
        self.assertEqual(self.pin((5000, 120), reading="low"), (0, 0))
        self.assertEqual(self.pin((5000, 100), (5250, 100), reading="low"),
                         (1, 1))

    def test_a_key_held_at_the_start_is_no_press(self):
        """The hand that switches the board on can still be on the key when
        the task starts. That press does not put the display down."""
        self.assertEqual(self.pin((0, 500)), (0, 0))
        self.assertEqual(self.pin((0, 500), (3000, 120)), (1, 1))

    def test_the_pin_is_high_while_the_key_is_pressed(self):
        """T1 conducts while the key is up and pulls EXIO4 low. A press
        stops it, and R11 pulls the pin high."""
        key = 1 << 4
        self.assertTrue(self.pressed(key, key))
        self.assertFalse(self.pressed(0, key))

    def test_only_the_pin_of_the_key_counts(self):
        key = 1 << 4
        self.assertFalse(self.pressed(0xFF & ~key, key))
        self.assertTrue(self.pressed(0xFF, key))


class KeyTaskTest(unittest.TestCase):
    """How the key is read, out of panel_power.c. No compiler needed."""

    def source(self):
        with open(os.path.join(FIRMWARE, "panel_power.c")) as handle:
            return handle.read()

    def test_the_loop_keeps_a_rate_rather_than_a_gap(self):
        """vTaskDelay measures the gap between turns, so the I2C read was
        added on top of it. That is what made the period drift."""
        text = self.source()
        self.assertIn("vTaskDelayUntil", text)
        self.assertNotIn("vTaskDelay(pdMS_TO_TICKS(read_failed", text)

    def test_the_task_is_not_below_the_drawing(self):
        """A task that is not run does not sample."""
        self.assertIn("#define PWRKEY_TASK_PRIORITY 5", self.source())

    def test_the_key_is_read_with_the_level_of_the_board(self):
        """High while pressed, through panel_key_pressed. The other way
        round, only a double press worked."""
        text = self.source()
        self.assertIn(
            "panel_key_sample(&key,panel_key_pressed(level,PWRKEY_PIN),now)",
            text)
        self.assertNotRegex(text, r"\(level\s*&\s*PWRKEY_PIN\)\s*==\s*0")

    def test_each_press_that_counts_is_in_the_log(self):
        """So the next log from the board shows each press and its length."""
        self.assertIn("PWRKEY short press of about", self.source())

    def test_it_reports_the_period_it_really_kept(self):
        """So a press that still does nothing comes with the number that
        explains it, instead of somebody guessing with a button."""
        self.assertIn("panel_power_slowest_read_ms", self.source())
        with open(os.path.join(FIRMWARE, "main.c")) as handle:
            self.assertIn("key_slowest", handle.read())


if __name__ == "__main__":
    unittest.main()
