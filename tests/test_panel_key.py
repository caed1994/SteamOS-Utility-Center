# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The button on the side of the wall panel.

Reported from the board: one press did nothing and two worked. The state
machine was not at fault. It needs the level to read the same on two samples
in a row at each edge, so the shortest press it can see is about twice the
polling period, and the poll was vTaskDelay(20) plus an I2C read on a bus
shared with the touch screen and the audio codec.

These tests hold both halves of what the machine promises, at the rate
panel_power.c now keeps: an ordinary press is seen exactly one time, and a
contact bounce is never seen at all. They sweep the phase of the poll,
because a person does not press in time with the loop.

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
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise unittest.SkipTest("panel_key.c did not build here:\n"
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

    def test_the_fault_from_the_board_is_the_one_this_covers(self):
        """One press did nothing on a board where the poll was slow. The
        number that decides is the period, and this says by how much: the
        shortest press that works grows with it."""
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

    def test_it_reports_the_period_it_really_kept(self):
        """So a press that still does nothing comes with the number that
        explains it, instead of somebody guessing with a button."""
        self.assertIn("panel_power_slowest_read_ms", self.source())
        with open(os.path.join(FIRMWARE, "main.c")) as handle:
            self.assertIn("key_slowest", handle.read())


if __name__ == "__main__":
    unittest.main()
