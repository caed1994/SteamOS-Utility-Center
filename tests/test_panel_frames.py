# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The frames of a scroll, and the settings that pace them.

Asked for: a scroll on the panel that is as smooth as the board allows,
and a measurement of it on the page of the panel. The measurement comes
first, so that each change is checked against numbers from the board.

firmware/companion/main/panel_frames.c counts the frames, and the harness
in tests/c/panel-frames-harness.c drives it here. The rules below hold
where the frames come from, when the count stands still, and the pace of
the refresh and of the tasks around the drawing.
"""

from __future__ import annotations

import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(REPO, "firmware", "companion")
FIRMWARE = os.path.join(COMPANION, "main")
HARNESS = os.path.join(REPO, "tests", "c", "panel-frames-harness.c")

# The panel shows a frame every 22.5 ms: 12 MHz and the timings of this
# panel, as the board measured it. See panel_display.c.
PANEL_FRAME_US = 22500


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


def code(name):
    with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
        text = handle.read()
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def defaults():
    with open(os.path.join(COMPANION, "sdkconfig.defaults"), encoding="utf-8") as handle:
        return handle.read()


def function(text, name):
    found = re.search(r"\n[^\n]*\b%s\([^)]*\)\s*\{(.*?)\n\}" % re.escape(name), text, re.S)
    if not found:
        raise AssertionError("no function " + name)
    return found.group(1)


def expected(frames):
    """The numbers of the page for frames in movement, each a pair of the
    interval and the draw time in us, worked out here on their own."""
    if not frames:
        return (0,) * 8
    count = len(frames)
    intervals = [one[0] for one in frames]
    draws = [one[1] for one in frames]

    def p95(values):
        steps = sorted(min(value // 1000, 127) for value in values)
        return steps[math.ceil(len(steps) * 95 / 100) - 1]

    total = sum(intervals)
    return (count, (count * 1000000 + total // 2) // total,
            total // count // 1000, p95(intervals), max(intervals) // 1000,
            sum(draws) // count // 1000, p95(draws), max(draws) // 1000)


def commands_for(frames, start=1000000):
    """A start frame, then one frame for each pair."""
    shown = start
    lines = ["frame %d %d %d" % (shown - 20000, shown - 10000, shown)]
    for interval, draw in frames:
        begun = shown + 1
        shown += interval
        lines.append("frame %d %d %d" % (begun, begun + draw, shown))
    return lines


@unittest.skipUnless(compiler(), "no C compiler here")
class FramesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-frames")
        build = [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
                 "-I", FIRMWARE, "-o", cls.program, HARNESS,
                 os.path.join(FIRMWARE, "panel_frames.c")]
        # With the sanitizers where this machine has them, so a step past
        # the end of the spread ends the harness.
        done = subprocess.run(build + ["-fsanitize=address,undefined",
                                       "-fno-sanitize-recover=all"],
                              capture_output=True, text=True)
        if done.returncode != 0:
            done = subprocess.run(build, capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_frames.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def stats(self, *commands):
        done = subprocess.run([self.program], input="\n".join(commands + ("stats",)) + "\n",
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return tuple(int(value) for value in done.stdout.splitlines()[-1].split())

    def test_no_frame_gives_noughts(self):
        self.assertEqual(self.stats(), (0,) * 8)

    def test_the_first_frame_after_a_rest_is_a_start(self):
        self.assertEqual(self.stats("frame 1000000 1010000 1022500"), (0,) * 8)
        self.assertEqual(self.stats(*commands_for([(PANEL_FRAME_US, 14000)])),
                         (1, 44, 22, 22, 22, 14, 14, 14))

    def test_a_rest_starts_a_new_movement(self):
        frames = commands_for([(PANEL_FRAME_US, 14000)])
        # 150 ms later: a start. 99.999 ms after that: in movement.
        frames += ["frame 1172000 1180000 1172500", "frame 1172501 1180000 1272499"]
        self.assertEqual(self.stats(*frames)[0], 2)
        # A gap of 100 ms is a rest.
        self.assertEqual(self.stats("frame 1000000 1001000 1002000",
                                    "frame 1002001 1003000 1102000")[0], 0)

    def test_the_numbers_are_those_of_the_frames(self):
        draw = random.Random(4420)
        frames = []
        for _ in range(3000):
            interval = draw.choice([PANEL_FRAME_US] * 8 + [2 * PANEL_FRAME_US, 3 * PANEL_FRAME_US])
            interval += draw.randint(-300, 300)
            frames.append((interval, draw.randint(4000, interval - 2000)))
        self.assertEqual(self.stats(*commands_for(frames)), expected(frames))

    def test_a_slow_frame_is_the_most_and_not_the_mean(self):
        frames = [(PANEL_FRAME_US, 12000)] * 99 + [(3 * PANEL_FRAME_US, 60000)]
        got = self.stats(*commands_for(frames))
        self.assertEqual(got, expected(frames))
        self.assertEqual((got[3], got[4], got[6], got[7]), (22, 67, 12, 60))

    def test_nothing_counts_while_held_and_the_next_frame_starts(self):
        frames = ["hold 1"] + commands_for([(PANEL_FRAME_US, 14000)] * 5)
        self.assertEqual(self.stats(*frames)[0], 0)
        frames += ["hold 0"] + commands_for([(PANEL_FRAME_US, 14000)] * 3, start=3000000)
        self.assertEqual(self.stats(*frames)[0], 3)
        # A hold in the middle of a movement breaks it there.
        frames = commands_for([(PANEL_FRAME_US, 14000)] * 2) + ["hold 1", "hold 0",
                                                                 "frame 1045002 1050000 1067500"]
        self.assertEqual(self.stats(*frames)[0], 2)

    def test_a_break_starts_a_new_movement(self):
        frames = commands_for([(PANEL_FRAME_US, 14000)] * 2) + ["break",
                                                                 "frame 1045002 1050000 1067500"]
        self.assertEqual(self.stats(*frames)[0], 2)

    def test_a_reset_forgets_everything(self):
        frames = commands_for([(PANEL_FRAME_US, 14000)] * 4) + ["reset"]
        self.assertEqual(self.stats(*frames), (0,) * 8)
        self.assertEqual(self.stats(*frames + ["frame 2000000 2010000 2020000"])[0], 0)

    def test_a_frame_without_its_three_moments_does_not_count(self):
        start = ["frame 1000000 1010000 1020000"]
        self.assertEqual(self.stats(*start + ["shown 1042500"])[0], 0)
        self.assertEqual(self.stats(*start + ["begin 1020001", "shown 1042500"])[0], 0)
        # Drawn before any begin is no frame either.
        self.assertEqual(self.stats(*start + ["shown 1021000", "drawn 1030000",
                                              "shown 1042500"])[0], 0)

    def test_a_drawn_of_an_earlier_refresh_does_not_count_for_the_next(self):
        start = ["frame 1000000 1010000 1020000"]
        self.assertEqual(self.stats(*start + ["begin 1020001", "drawn 1030000",
                                              "begin 1030001", "shown 1042500"])[0], 0)

    def test_a_draw_time_below_nought_counts_as_nought(self):
        start = ["frame 1000000 1010000 1020000"]
        got = self.stats(*start + ["begin 1030000", "drawn 1029000", "shown 1042500"])
        self.assertEqual((got[0], got[5], got[6], got[7]), (1, 0, 0, 0))

    def test_the_95th_percentile_rounds_up(self):
        # 21 frames, the last two slow: the 20th frame is the 95th
        # percentile, and it is a slow one.
        frames = [(PANEL_FRAME_US, 10000)] * 19 + [(2 * PANEL_FRAME_US, 10000)] * 2
        got = self.stats(*commands_for(frames))
        self.assertEqual(got, expected(frames))
        self.assertEqual(got[3], 45)

    def test_the_frame_rate_rounds_to_the_nearest(self):
        # 24.63 ms is 40.6 frames a second.
        self.assertEqual(self.stats(*commands_for([(24630, 10000)] * 10))[1], 41)

    def test_the_last_step_holds_the_longest_and_the_most_stays_exact(self):
        frames = [(90000, 150000)]
        got = self.stats(*commands_for(frames))
        self.assertEqual((got[6], got[7]), (127, 150))

    def test_a_step_that_fills_up_keeps_the_shape(self):
        # Ten of each hundred at twice the frame, for longer than a step
        # holds: the 95th percentile stays at the slow frames, and the
        # mean and the count stay exact.
        frames = ([(PANEL_FRAME_US, 10000)] * 9 + [(2 * PANEL_FRAME_US, 10000)]) * 7500
        got = self.stats(*commands_for(frames))
        self.assertEqual(got, expected(frames))
        frames = ([(PANEL_FRAME_US, 10000)] * 99 + [(2 * PANEL_FRAME_US, 10000)]) * 700
        got = self.stats(*commands_for(frames))
        self.assertEqual(got[0], 70000)
        self.assertEqual(got[3], 22)


class WhereTest(unittest.TestCase):

    def test_the_display_gives_the_three_moments(self):
        display = code("panel_display.c")
        for event, handler in (("LV_EVENT_REFR_START", "frame_begun"),
                               ("LV_EVENT_FLUSH_START", "frame_flush"),
                               ("LV_EVENT_FLUSH_FINISH", "frame_flushed")):
            self.assertRegex(display, r"lv_display_add_event_cb\(screen,%s,%s,NULL\)"
                             % (handler, event))
        # Only the last area hands a frame to the panel.
        self.assertIn("lv_display_flush_is_last", function(display, "frame_flush"))
        flushed = function(display, "frame_flushed")
        self.assertIn("lv_display_flush_is_last", flushed)
        # The startup animation does not count.
        self.assertIn("if(panel_boot_playing())panel_frames_break(&panel_frames);", flushed)

    def test_the_page_holds_the_count_and_its_end_starts_it_again(self):
        ui = code("ui.c")
        self.assertIn("panel_frames_hold(&panel_frames,true);", function(ui, "panel_ui_self_open"))
        self.assertIn("panel_frames_reset(&panel_frames);", function(ui, "self_drop"))

    def test_the_numbers_reach_the_page_and_the_health_line(self):
        main = code("main.c")
        self.assertIn("panel_frames_stats(&panel_frames,&frames);", function(main, "ui_tick"))
        health = re.search(r'ESP_LOGI\("panel_health"[^;]*;', main, re.S).group(0)
        for said in ("internal_min=", "frames=", "fps=", "gap=", "draw="):
            self.assertIn(said, health)
        self.assertIn("heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)",
                      health)

    def test_the_refresh_waits_less_than_a_frame_of_the_panel(self):
        found = re.search(r"(?m)^CONFIG_LV_DEF_REFR_PERIOD=(\d+)$", defaults())
        self.assertIsNotNone(found)
        self.assertLess(int(found.group(1)) * 1000, PANEL_FRAME_US)
        self.assertGreater(int(found.group(1)), 0)

    def test_nothing_of_the_network_stands_above_the_drawing(self):
        settings = defaults()
        draw = re.search(r"(?m)^CONFIG_LV_DRAW_THREAD_PRIO=(\d)$", settings)
        self.assertIsNotNone(draw)
        main = code("main.c")
        network = re.search(r"#define PANEL_NETWORK_PRIORITY (\d+)", main)
        self.assertIsNotNone(network)
        self.assertLess(int(network.group(1)), int(draw.group(1)))
        self.assertRegex(main, r'xTaskCreatePinnedToCore\(network_task,"panel_network",12288,NULL,'
                               r'\s*PANEL_NETWORK_PRIORITY,NULL,0\)')
        self.assertNotIn("xTaskCreate(network_task", main)
        self.assertRegex(settings, r"(?m)^CONFIG_LWIP_TCPIP_TASK_AFFINITY_CPU0=y$")

    def test_the_restart_at_every_frame_stays_off(self):
        self.assertNotRegex(defaults(), r"(?m)^CONFIG_LCD_RGB_RESTART_IN_VSYNC=y")

    def test_both_builds_know_the_file(self):
        for path in (os.path.join(FIRMWARE, "CMakeLists.txt"),
                     os.path.join(COMPANION, "preview", "CMakeLists.txt")):
            with open(path, encoding="utf-8") as handle:
                self.assertIn("panel_frames.c", handle.read(), path)


if __name__ == "__main__":
    unittest.main()
