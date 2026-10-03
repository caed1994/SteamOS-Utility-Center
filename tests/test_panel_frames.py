# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The frames of a scroll, and the settings that pace them.

Asked for: a scroll on the panel that is as smooth as the board allows,
and a measurement of it on the page of the panel. The measurement comes
first, so that each change is checked against numbers from the board.

firmware/companion/main/panel_frames.c counts the frames, and the harness
in tests/c/panel-frames-harness.c drives it here. Each frame gives its
interval, its draw time and its lead time. It also counts for the periods
of the panel that it took. The rules below hold where the frames come
from, when the count stands still, and the pace of the refresh and of the
tasks around the drawing.

The frames are not in the state of the screen. A state that changed at
each frame made panel_ui_update do all of its work at each tick of a
scroll. The page of the panel reads the count itself.

The last rules hold the clock of LVGL, the internal memory that the radio
gives back to the display, and the larger caches that it pays for.
"""

from __future__ import annotations

import fractions
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

# The panel shows a frame every 22.1 ms at 12 MHz, and every 16.6 ms at
# 16 MHz, the clock after the startup animation. A frame is 520 by 510
# pixel clocks. See PANEL_FRAME_CLOCKS in panel_display.c.
PANEL_FRAME_US = 22100
PANEL_FAST_FRAME_US = 16575


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


# The numbers of the harness: the frames, the rate, the interval, the draw
# time and the lead time (each mean, 95 % and most), and four shares.
NUMBERS = 15


def shares(counts):
    """Whole percent that add up to a hundred, worked out with fractions:
    each share rounded down, then a point to each of the shares with the
    largest rest, the first of equals first."""
    total = sum(counts)
    if not total:
        return (0,) * len(counts)
    exact = [fractions.Fraction(100 * count, total) for count in counts]
    given = [math.floor(share) for share in exact]
    order = sorted(range(len(counts)), key=lambda i: (-(exact[i] - given[i]), i))
    for i in order[:100 - sum(given)]:
        given[i] += 1
    return tuple(given)


def periods(interval, period):
    """The periods of the panel in an interval, to the nearest whole one,
    one at the least and four for four and more."""
    return min(max((interval + period // 2) // period, 1), 4)


def expected(frames, period=0):
    """The numbers of the page for frames in movement, worked out here on
    their own. Each frame is the interval, the draw time and the lead time
    in us. A frame with no lead time has a lead time of 1 us, as
    commands_for gives it."""
    if not frames:
        return (0,) * NUMBERS
    count = len(frames)
    intervals = [one[0] for one in frames]
    draws = [one[1] for one in frames]
    leads = [max(one[2], 0) if len(one) > 2 else 1 for one in frames]

    def p95(values):
        steps = sorted(min(value // 1000, 127) for value in values)
        return steps[math.ceil(len(steps) * 95 / 100) - 1]

    counts = [0] * 4
    if period:
        for interval in intervals:
            counts[periods(interval, period) - 1] += 1
    total = sum(intervals)
    return (count, (count * 1000000 + total // 2) // total,
            total // count // 1000, p95(intervals), max(intervals) // 1000,
            sum(draws) // count // 1000, p95(draws), max(draws) // 1000,
            sum(leads) // count // 1000, p95(leads), max(leads) // 1000) + shares(counts)


def commands_for(frames, start=1000000):
    """A start frame, then one frame for each. A frame is the interval and
    the draw time in us, and the lead time when there is a third number.
    With no lead time, the frame begins 1 us after the one before it is on
    the screen."""
    shown = start
    lines = ["frame %d %d %d" % (shown - 20000, shown - 10000, shown)]
    for one in frames:
        interval, draw = one[0], one[1]
        begun = shown + (one[2] if len(one) > 2 else 1)
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
        self.assertEqual(self.stats(), (0,) * NUMBERS)

    def test_the_first_frame_after_a_rest_is_a_start(self):
        self.assertEqual(self.stats("frame 1000000 1010000 1022100"), (0,) * NUMBERS)
        self.assertEqual(self.stats(*commands_for([(PANEL_FRAME_US, 14000)])),
                         (1, 45, 22, 22, 22, 14, 14, 14, 0, 0, 0, 0, 0, 0, 0))

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
        self.assertEqual((got[3], got[4], got[6], got[7]), (22, 66, 12, 60))

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
        self.assertEqual(self.stats(*frames), (0,) * NUMBERS)
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
        self.assertEqual(got[3], 44)

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

    def test_the_lead_time_runs_from_the_frame_on_the_screen_to_the_next_begin(self):
        frames = [(2 * PANEL_FAST_FRAME_US, 29000, 2500), (2 * PANEL_FAST_FRAME_US, 30000, 1200),
                  (3 * PANEL_FAST_FRAME_US, 31000, 6000)]
        got = self.stats(*commands_for(frames))
        self.assertEqual(got, expected(frames))
        self.assertEqual(got[8:11], (3, 6, 6))

    def test_a_lead_time_below_nought_counts_as_nought(self):
        start = ["frame 1000000 1010000 1020000"]
        got = self.stats(*start + ["begin 1019000", "drawn 1030000", "shown 1053150"])
        self.assertEqual((got[0], got[8], got[9], got[10]), (1, 0, 0, 0))

    def test_each_frame_counts_for_the_periods_it_took(self):
        frames = ([(2 * PANEL_FAST_FRAME_US, 29000)] * 51 + [(3 * PANEL_FAST_FRAME_US, 31000)] * 44
                  + [(4 * PANEL_FAST_FRAME_US, 40000)] * 5)
        got = self.stats("period %d" % PANEL_FAST_FRAME_US, *commands_for(frames))
        self.assertEqual(got, expected(frames, PANEL_FAST_FRAME_US))
        self.assertEqual(got[11:], (0, 51, 44, 5))

    def test_the_periods_round_to_the_nearest_one(self):
        period = PANEL_FAST_FRAME_US
        # Late or early by less than half a period: the same count. Under
        # one is one, and four and more is the last count.
        cases = [(period * 3 // 10, 1), (period * 149 // 100, 1), (period * 151 // 100, 2),
                 (2 * period + 900, 2), (3 * period - 900, 3), (period * 449 // 100, 4),
                 (period * 59 // 10, 4)]
        for interval, taken in cases:
            got = self.stats("period %d" % period, *commands_for([(interval, 1000)]))
            share = [0, 0, 0, 0]
            share[taken - 1] = 100
            self.assertEqual(got[11:], tuple(share), interval)

    def test_the_shares_add_up_to_a_hundred(self):
        period = PANEL_FAST_FRAME_US
        # A third each: the point that is left goes to the first.
        got = self.stats("period %d" % period, *commands_for(
            [(period, 1000), (2 * period, 1000), (3 * period, 1000)]))
        self.assertEqual(got[11:], (34, 33, 33, 0))
        # One, two, three and one of seven: 14.3, 28.6, 42.9 and 14.3 %.
        frames = ([(period, 1000)] + [(2 * period, 1000)] * 2 + [(3 * period, 1000)] * 3
                  + [(4 * period, 1000)])
        got = self.stats("period %d" % period, *commands_for(frames))
        self.assertEqual(got[11:], (14, 29, 43, 14))
        draw = random.Random(1661)
        for _ in range(40):
            frames = [(draw.randint(1, 5) * period + draw.randint(-2000, 2000), 1000)
                      for _ in range(draw.randint(1, 60))]
            got = self.stats("period %d" % period, *commands_for(frames))
            self.assertEqual(sum(got[11:]), 100)
            self.assertEqual(got, expected(frames, period))

    def test_no_shares_while_the_period_is_not_known(self):
        frames = [(2 * PANEL_FAST_FRAME_US, 29000)] * 3
        got = self.stats(*commands_for(frames))
        self.assertEqual((got[0], got[11:]), (3, (0, 0, 0, 0)))
        # A period of nought or less is not known either.
        for period in (0, -PANEL_FAST_FRAME_US):
            got = self.stats("period %d" % PANEL_FAST_FRAME_US, "period %d" % period,
                             *commands_for(frames))
            self.assertEqual((got[0], got[11:]), (3, (0, 0, 0, 0)), period)

    def test_a_reset_keeps_the_period(self):
        frames = [(2 * PANEL_FAST_FRAME_US, 29000)] * 2
        got = self.stats("period %d" % PANEL_FAST_FRAME_US, "reset", *commands_for(frames))
        self.assertEqual(got[11:], (0, 100, 0, 0))

    def test_a_new_period_starts_a_new_movement(self):
        first = ["period %d" % PANEL_FRAME_US] + commands_for([(2 * PANEL_FRAME_US, 29000)] * 2)
        # The same period again changes nothing.
        got = self.stats(*first + ["period %d" % PANEL_FRAME_US, "frame 1088401 1100000 1132600"])
        self.assertEqual(got[0], 3)
        # A new one: the next frame is a start, and the frame after it
        # counts in the new period.
        got = self.stats(*first + ["period %d" % PANEL_FAST_FRAME_US,
                                   "frame 1088401 1100000 1121550",
                                   "frame 1121551 1140000 1154700"])
        self.assertEqual(got[0], 3)
        self.assertEqual(got[11:], (0, 100, 0, 0))


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

    def test_the_numbers_reach_the_health_line(self):
        main = code("main.c")
        tick = function(main, "ui_tick")
        self.assertIn("panel_frames_stats(&panel_frames,&frames);", tick)
        self.assertIn("health_frames=frames; copy=state;", tick)
        self.assertIn("panel_frame_stats_t frames=health_frames;", main)
        health = re.search(r'ESP_LOGI\("panel_health"[^;]*;', main, re.S).group(0)
        for said in ("internal_min=", "frames=", "fps=", "gap=", "draw=", "lead=", "periods="):
            self.assertIn(said, health)
        for number in ("frames.lead_mean_ms", "frames.periods_pct[0]", "frames.periods_pct[3]"):
            self.assertIn(number, health)
        self.assertIn("heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)",
                      health)

    def test_the_frames_are_not_in_the_state_of_the_screen(self):
        # A state that changes at each frame makes panel_ui_update do all
        # of its work at each tick of a scroll.
        header = code("ui.h")
        end = header.index("} panel_state_t;")
        state = header[header.rindex("typedef struct", 0, end):end]
        self.assertNotIn("panel_frame_stats_t", state)
        self.assertNotIn("panel_frames", header)
        main = code("main.c")
        self.assertNotRegex(main, r"\b(state|copy)\.frames\b")
        # The test in panel_ui_update stays a test of the whole state.
        self.assertIn("memcmp(&last_state,s,sizeof(*s))==0", function(code("ui.c"), "panel_ui_update"))

    def test_the_page_reads_the_count_as_it_opens(self):
        ui = code("ui.c")
        opened = function(ui, "panel_ui_self_open")
        self.assertLess(opened.index("panel_frames_hold(&panel_frames,true);"),
                        opened.index("self_frames_show();"))
        self.assertIn("panel_frames_stats(&panel_frames,&frames);", function(ui, "self_frames_show"))
        # Once, as the page opens: the count stands still while it is open.
        self.assertEqual(ui.count("self_frames_show();"), 1)
        self.assertNotIn("frames", function(ui, "self_show"))

    def test_the_display_gives_the_period_of_an_awake_panel(self):
        display = code("panel_display.c")
        self.assertIn("#define PANEL_FRAME_CLOCKS (520 * 510)", display)
        self.assertIn("return (int64_t)PANEL_FRAME_CLOCKS*1000000/pclk_hz;",
                      function(display, "frame_us"))
        start = function(display, "panel_display_start")
        self.assertLess(start.index("esp_lcd_rgb_panel_set_pclk(panel,PANEL_PCLK_BOOT_HZ)"),
                        start.index("panel_frames_period(&panel_frames,frame_us(PANEL_PCLK_BOOT_HZ));"))
        # Before the events of the display can give the count a frame.
        self.assertLess(start.index("panel_frames_period("), start.index("lv_display_add_event_cb("))
        over = function(display, "panel_display_boot_over")
        self.assertLess(over.index("pclk_awake=PANEL_PCLK_HZ;"),
                        over.index("panel_frames_period(&panel_frames,frame_us(pclk_awake));"))

    def test_the_period_is_the_one_the_board_read(self):
        # The page of the panel read frame intervals of 66 and 99 ms at
        # 16 MHz: four and six periods. At 12 MHz it read 66 and 88 ms:
        # three and four periods.
        clocks = re.search(r"#define PANEL_FRAME_CLOCKS \((\d+) \* (\d+)\)", code("panel_display.c"))
        frame = int(clocks.group(1)) * int(clocks.group(2))
        fast, slow = frame * 1000000 // 16000000, frame * 1000000 // 12000000
        self.assertEqual((fast * 4 // 1000, fast * 6 // 1000), (66, 99))
        self.assertEqual((slow * 3 // 1000, slow * 4 // 1000), (66, 88))
        self.assertEqual((fast, slow), (PANEL_FAST_FRAME_US, PANEL_FRAME_US))

    def test_the_refresh_waits_less_than_a_frame_of_the_panel(self):
        found = re.search(r"(?m)^CONFIG_LV_DEF_REFR_PERIOD=(\d+)$", defaults())
        self.assertIsNotNone(found)
        self.assertLess(int(found.group(1)) * 1000, PANEL_FAST_FRAME_US)
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


class RoomTest(unittest.TestCase):
    """The panel read 43 KB of internal memory free and 22 KB at the least.
    Each change that makes the scroll faster takes some of it, so the radio
    gives some back first."""

    def test_the_radio_keeps_no_code_in_iram_and_its_buffers_in_psram(self):
        settings = defaults()
        for line in ("CONFIG_ESP_WIFI_IRAM_OPT=n", "CONFIG_ESP_WIFI_RX_IRAM_OPT=n",
                     "CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP=y"):
            self.assertRegex(settings, r"(?m)^%s$" % re.escape(line))
        # No other option puts the code of the radio back into IRAM.
        self.assertNotRegex(settings, r"(?m)^CONFIG_ESP_WIFI_(SLP|EXTRA)_IRAM_OPT=y")


class ThreadsTest(unittest.TestCase):
    """One thread draws. Two were measured on the board, and a frame of a
    scroll took 29 ms to draw with two where it took 28 with one: the
    drawing waits on PSRAM, which both cores share."""

    def test_one_thread_draws(self):
        self.assertRegex(defaults(), r"(?m)^CONFIG_LV_DRAW_SW_DRAW_UNIT_CNT=1$")

    def test_the_lvgl_task_keeps_the_smaller_stack(self):
        self.assertIn("#define PANEL_LVGL_STACK (16 * 1024)", code("panel_display.c"))


class ClockTest(unittest.TestCase):
    """The clock of LVGL comes from the system timer, to the millisecond.
    esp_lvgl_port counts it in steps of 5 ms, and an animation of LVGL
    finds where it is from that clock at each frame."""

    def test_the_clock_reads_the_system_timer(self):
        self.assertIn("return (uint32_t)(esp_timer_get_time()/1000);",
                      function(code("panel_display.c"), "lvgl_tick_ms"))

    def test_the_clock_is_set_after_lv_init_and_under_the_lock(self):
        start = function(code("panel_display.c"), "panel_display_start")
        self.assertEqual(start.count("lv_tick_set_cb("), 1)
        found = re.search(r"lvgl_port_lock\(0\);\s*lv_tick_set_cb\(lvgl_tick_ms\);\s*"
                          r"lvgl_port_unlock\(\);", start)
        self.assertIsNotNone(found)
        self.assertLess(start.index("ESP_ERROR_CHECK(lvgl_port_init(&port));"), found.start())
        # Before the display and anything on it.
        self.assertLess(found.start(), start.index("bsp_display_new("))


class CacheTest(unittest.TestCase):
    """LVGL draws into a frame buffer in PSRAM and runs out of PSRAM, both
    through the caches. With internal memory to spare, both are larger."""

    def test_the_caches_are_the_largest_this_chip_has(self):
        settings = defaults()
        for line in ("CONFIG_ESP32S3_DATA_CACHE_64KB=y", "CONFIG_ESP32S3_DATA_CACHE_LINE_64B=y",
                     "CONFIG_ESP32S3_INSTRUCTION_CACHE_32KB=y"):
            self.assertRegex(settings, r"(?m)^%s$" % re.escape(line))


if __name__ == "__main__":
    unittest.main()
