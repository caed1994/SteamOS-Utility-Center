# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The timer of the clock page, built and driven on this machine.

Asked for: a timer on the page of the clock, with + and -. A tap is a
minute and a press that is held counts on in steps of five, between nought
and 180 minutes. It runs on while the display sleeps, and at its end it
beeps and wakes the display, from the sleep of the button as well.

firmware/companion/main/panel_timer.c is the timer without a screen. The
harness in tests/c/panel-timer-harness.c drives it with a clock of its own,
so every rule here is about the real state machine and not about its
shape.
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
HARNESS = os.path.join(REPO, "tests", "c", "panel-timer-harness.c")

MINUTE = 60 * 1000


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


def constant(name):
    with open(os.path.join(FIRMWARE, "panel_timer.h"), encoding="utf-8") as h:
        found = re.search(r"^#define %s \(?([\d *]+)\)?" % name, h.read(), re.M)
    assert found, name
    return eval(found.group(1))  # digits and * only, see the pattern


@unittest.skipUnless(compiler(), "no C compiler here")
class TimerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-timer")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_timer.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_timer.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def run_timer(self, *commands):
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def shown(self, *commands):
        """The last "show" of a run, as (phase, ms left)."""
        last = [line for line in self.run_timer(*commands)
                if re.fullmatch(r"(idle|running|paused|ringing) \d+", line)][-1]
        phase, left = last.split()
        return phase, int(left)

    def test_the_numbers_are_the_ones_asked_for(self):
        self.assertEqual(constant("PANEL_TIMER_TAP_MIN"), 1)
        self.assertEqual(constant("PANEL_TIMER_HOLD_MIN"), 5)
        self.assertEqual(constant("PANEL_TIMER_MAX_MIN"), 180)

    def test_it_starts_at_nought_and_counts_up_in_minutes(self):
        self.assertEqual(self.shown("show 0"), ("idle", 0))
        self.assertEqual(self.shown("adjust 1", "adjust 5", "adjust 1",
                                    "show 0"), ("idle", 7 * MINUTE))

    def test_it_stays_between_nought_and_180_minutes(self):
        self.assertEqual(self.shown("adjust -1", "show 0"), ("idle", 0))
        self.assertIn("adjust no", self.run_timer("adjust -1"))
        up = ["adjust 5"] * 40
        self.assertEqual(self.shown(*up, "show 0"), ("idle", 180 * MINUTE))
        self.assertEqual(self.run_timer(*up, "adjust 1")[-1], "adjust no")

    def test_it_counts_down_while_it_runs(self):
        self.assertEqual(self.shown("adjust 5", "start 1000", "show 61000"),
                         ("running", 4 * MINUTE))

    def test_nought_minutes_does_not_start(self):
        self.assertEqual(self.run_timer("start 0")[-1], "start no")

    def test_plus_and_minus_wait_while_it_runs(self):
        out = self.run_timer("adjust 5", "start 0", "adjust 1", "show 0")
        self.assertIn("adjust no", out)
        self.assertEqual(out[-1], "running %d" % (5 * MINUTE))

    def test_a_pause_keeps_what_is_left_and_a_start_goes_on_from_it(self):
        commands = ["adjust 5", "start 0", "pause 90000"]
        self.assertEqual(self.shown(*commands, "show 500000"),
                         ("paused", 5 * MINUTE - 90000))
        self.assertEqual(self.shown(*commands, "start 500000", "show 530000"),
                         ("running", 5 * MINUTE - 90000 - 30000))

    def test_plus_and_minus_change_what_is_left_of_a_paused_timer(self):
        self.assertEqual(self.shown("adjust 5", "start 0", "pause 90000",
                                    "adjust 1", "show 90000"),
                         ("paused", 6 * MINUTE - 90000))

    def test_a_paused_timer_taken_to_nought_is_idle(self):
        self.assertEqual(self.shown("adjust 1", "start 0", "pause 30000",
                                    "adjust -1", "show 30000"), ("idle", 0))

    def test_reset_goes_back_to_the_start_and_a_second_one_clears(self):
        commands = ["adjust 5", "start 0", "pause 90000", "reset"]
        self.assertEqual(self.shown(*commands, "show 90000"),
                         ("idle", 5 * MINUTE))
        self.assertEqual(self.shown(*commands, "reset", "show 90000"),
                         ("idle", 0))

    def test_it_goes_off_once_at_nought(self):
        out = self.run_timer("adjust 1", "start 0",
                             "ticks 0 61000 200", "show 61000")
        went = [line for line in out if line.endswith("went_off")]
        self.assertEqual(went, ["60000 went_off"])
        self.assertEqual(out[-1], "ringing 0")

    def test_it_beeps_three_times_and_pauses_once_a_second(self):
        out = self.run_timer("adjust 1", "start 0", "ticks 60000 62999 200")
        beeps = [int(line.split()[0]) for line in out if line.endswith("beep")]
        self.assertEqual(beeps, [60000, 60200, 60400, 61000, 61200, 61400,
                                 62000, 62200, 62400])

    def test_a_late_tick_leaves_a_beep_out_and_plays_none_twice(self):
        """The ticks of the panel are 200 ms apart, and a busy one comes
        late. One answer for each slot, never two."""
        out = self.run_timer("adjust 1", "start 0", "ticks 60000 62999 350")
        beeps = [int(line.split()[0]) for line in out if line.endswith("beep")]
        slots = [(at - 60000) // 200 for at in beeps]
        self.assertEqual(len(slots), len(set(slots)))
        self.assertTrue(all(slot % 5 < 3 for slot in slots))

    def test_ticks_faster_than_the_slots_beep_once_a_slot(self):
        out = self.run_timer("adjust 1", "start 0", "ticks 60000 60999 100")
        beeps = [int(line.split()[0]) for line in out if line.endswith("beep")]
        self.assertEqual(beeps, [60000, 60200, 60400])

    def test_a_reset_after_a_pause_and_a_resume_goes_back_to_the_start(self):
        """The start that counts is the first one, from idle. A resume is
        not a new start."""
        self.assertEqual(self.shown("adjust 5", "start 0", "pause 90000",
                                    "start 100000", "reset", "show 100000"),
                         ("idle", 5 * MINUTE))

    def test_it_gives_up_after_a_minute_and_is_ready_again(self):
        ring = constant("PANEL_TIMER_RING_MS")
        self.assertEqual(ring, 60 * 1000)
        out = self.run_timer("adjust 2", "start 0",
                             "ticks 120000 %d 200" % (120000 + ring + 400),
                             "show %d" % (120000 + ring + 400))
        gave = [line for line in out if line.endswith("gave_up")]
        self.assertEqual(gave, ["%d gave_up" % (120000 + ring)])
        self.assertEqual(out[-1], "idle %d" % (2 * MINUTE))

    def test_stop_quiets_it_and_sets_it_up_again(self):
        out = self.run_timer("adjust 3", "start 0", "tick 180000", "stop",
                             "tick 180200", "show 180200")
        self.assertIn("stop yes", out)
        self.assertNotIn("180200 beep", out)
        self.assertEqual(out[-1], "idle %d" % (3 * MINUTE))
        self.assertEqual(self.run_timer("stop")[-1], "stop no")

    def test_it_is_right_across_the_turn_of_the_counter(self):
        """lv_tick_get counts milliseconds in 32 bits and turns over after
        49 days, which a panel on a wall reaches."""
        start = 2 ** 32 - 30000
        out = self.run_timer("adjust 1", "start %d" % start,
                             "show %d" % (start + 20000),
                             "tick %d" % ((start + 60000) % 2 ** 32))
        self.assertIn("running 40000", out)
        self.assertIn("%d went_off" % ((start + 60000) % 2 ** 32), out)

    def test_a_pause_at_the_very_end_is_the_end(self):
        out = self.run_timer("adjust 1", "start 0", "pause 60000",
                             "tick 60000")
        self.assertIn("pause no", out)
        self.assertEqual(out[-1], "60000 beep")


if __name__ == "__main__":
    unittest.main()
