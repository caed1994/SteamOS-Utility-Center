# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mirror: from a picture of the screen to the colours of the bar.

Three parts are here. The arithmetic makes 17 colours from one small
picture. Mirror is the end of the pipe in the LED service. Watcher is the
user service that starts the capture and tells a person what it does.

The capture itself needs gamescope and PipeWire, which this machine does not
have. A real child process with real pipes takes the place of gst-launch-1.0,
so each other part runs as it does on the machine.
"""

import errno
import json
import os
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "gui"))

from steamos_utility_center import config, render, screen  # noqa: E402
from steamos_utility_center import service, shim               # noqa: E402
import ledpanel                                                # noqa: E402

RED = (200, 30, 20)


def picture(colour_of, width=screen.WIDTH, height=screen.HEIGHT):
    """Returns one RGB picture. colour_of(column, row) gives each pixel."""
    data = bytearray()
    for row in range(height):
        for column in range(width):
            data.extend(colour_of(column, row))
    return bytes(data)


def stripes(colours, left=0, top=0):
    """A picture of equal vertical stripes, inside black bars."""
    inner = screen.WIDTH - 2 * left

    def colour_of(column, row):
        if (row < top or row >= screen.HEIGHT - top or column < left
                or column >= screen.WIDTH - left):
            return (0, 0, 0)
        return colours[(column - left) * len(colours) // inner]
    return picture(colour_of)


def spectrum():
    """Seventeen colours that are far apart."""
    return [((zone * 15) % 256, (255 - zone * 15) % 256, (zone * 97) % 256)
            for zone in range(screen.ZONES)]


class BarsTest(unittest.TestCase):

    def test_a_film_has_rows_at_the_top_and_the_bottom(self):
        self.assertEqual(screen.bars(stripes([RED], top=5)), (5, 0))

    def test_an_old_programme_has_columns_at_the_sides(self):
        self.assertEqual(screen.bars(stripes([RED], left=9)), (0, 9))

    def test_a_black_picture_says_nothing(self):
        self.assertIsNone(screen.bars(picture(lambda c, r: (0, 0, 0))))

    def test_noise_in_the_black_is_still_black(self):
        frame = stripes([RED], top=4)
        noisy = bytearray(frame)
        noisy[0] = screen.BLACK
        self.assertEqual(screen.bars(bytes(noisy)), (4, 0))

    def test_unequal_sides_count_the_smaller_one(self):
        def colour_of(column, row):
            return (0, 0, 0) if row < 6 or row >= screen.HEIGHT - 2 else RED
        self.assertEqual(screen.bars(picture(colour_of)), (2, 0))

    def test_a_light_in_a_dark_scene_is_not_a_film(self):
        def colour_of(column, row):
            middle = abs(row - screen.HEIGHT // 2) < 3
            return RED if middle else (0, 0, 0)
        self.assertEqual(screen.bars(picture(colour_of)), (0, 0))


class CropTest(unittest.TestCase):

    def test_a_larger_bar_must_stay_before_it_is_used(self):
        crop = screen.Crop()
        self.assertEqual(crop.update((5, 0), 0.0), (0, 0))
        self.assertEqual(crop.update((5, 0), screen.GROW_SECONDS - 0.1),
                         (0, 0))
        self.assertEqual(crop.update((5, 0), screen.GROW_SECONDS), (5, 0))

    def test_a_smaller_bar_comes_quickly(self):
        crop = screen.Crop()
        crop.update((5, 0), 0.0)
        crop.update((5, 0), 10.0)
        self.assertEqual(crop.update((0, 0), 10.0), (5, 0))
        self.assertEqual(crop.update((0, 0),
                                     10.0 + screen.SHRINK_SECONDS + 0.01),
                         (0, 0))
        self.assertLess(screen.SHRINK_SECONDS, screen.GROW_SECONDS)

    def test_a_black_picture_keeps_the_bars(self):
        crop = screen.Crop()
        crop.update((5, 0), 0.0)
        crop.update((5, 0), 10.0)
        self.assertEqual(crop.update(None, 20.0), (5, 0))

    def test_a_change_that_goes_away_starts_again(self):
        crop = screen.Crop()
        crop.update((5, 0), 0.0)
        crop.update((0, 0), 1.0)
        self.assertEqual(crop.update((5, 0), screen.GROW_SECONDS + 0.5),
                         (0, 0))


class ZonesTest(unittest.TestCase):

    def test_each_zone_takes_its_stripe_from_the_left(self):
        colours = spectrum()
        found = screen.zones(stripes(colours))
        self.assertEqual(len(found), screen.ZONES)
        for zone, (want, got) in enumerate(zip(colours, found)):
            for channel in range(3):
                self.assertAlmostEqual(got[channel], want[channel], delta=0.5,
                                       msg="zone %d" % zone)

    def test_the_zones_span_the_picture_inside_the_bars(self):
        """34 columns inside the bars: two for each zone."""
        colours = spectrum()
        found = screen.zones(stripes(colours, left=17, top=5), crop=(5, 17))
        for zone, (want, got) in enumerate(zip(colours, found)):
            for channel in range(3):
                self.assertAlmostEqual(got[channel], want[channel], delta=0.5,
                                       msg="zone %d" % zone)

    def test_the_bars_do_not_darken_the_zones(self):
        found = screen.zones(stripes([RED], top=6), crop=(6, 0))
        for colour in found:
            self.assertAlmostEqual(colour[0], RED[0], delta=0.01)

    def test_a_column_on_a_border_counts_in_both_zones(self):
        """52 columns: each zone has three columns and a twelfth."""
        weights = [sum(part for _column, part in parts)
                   for parts in screen._spans(52)]
        for weight in weights:
            self.assertAlmostEqual(weight, 52 / 17.0)
        columns = {}
        for parts in screen._spans(52):
            for column, part in parts:
                columns[column] = columns.get(column, 0.0) + part
        self.assertEqual(sorted(columns), list(range(52)))
        for column, total in columns.items():
            self.assertAlmostEqual(total, 1.0, msg=column)


class TreatTest(unittest.TestCase):

    def test_a_dark_zone_is_black(self):
        self.assertEqual(screen.treat((screen.DARK, 10.0, 0.0)),
                         (0.0, 0.0, 0.0))

    def test_white_stays_white(self):
        for got in screen.treat((255.0, 255.0, 255.0)):
            self.assertAlmostEqual(got, 255.0)

    def test_grey_stays_grey(self):
        red, green, blue = screen.treat((120.0, 120.0, 120.0))
        self.assertAlmostEqual(red, green)
        self.assertAlmostEqual(green, blue)

    def test_a_colour_gets_further_from_grey(self):
        before = (150.0, 100.0, 80.0)
        after = screen.treat(before)
        self.assertGreater(after[0] - after[2], before[0] - before[2])

    def test_a_bright_colour_keeps_its_hue(self):
        """A clamp of one channel changes the hue, and a scale does not."""
        red, green, blue = screen.treat((255.0, 200.0, 40.0))
        self.assertLessEqual(max(red, green, blue), 255.0 + 1e-9)
        self.assertAlmostEqual(red, 255.0)
        self.assertGreater(green, blue)
        self.assertGreater(green, 0.0)

    def test_the_picture_gives_one_treated_colour_for_each_zone(self):
        found = screen.Picture().colours(stripes([RED]), 0.0)
        self.assertEqual(len(found), screen.ZONES)
        self.assertEqual(found[0], screen.treat(RED))


class MessageTest(unittest.TestCase):

    def test_the_colours_go_through_the_pipe_unchanged(self):
        colours = [tuple(float(value) for value in colour)
                   for colour in spectrum()]
        message = screen.encode(colours)
        self.assertEqual(len(message), screen.MESSAGE)
        self.assertEqual(screen.decode(message), colours)

    def test_a_message_fits_in_one_atomic_write(self):
        self.assertLessEqual(screen.MESSAGE, select.PIPE_BUF)

    def test_values_out_of_range_are_clamped(self):
        message = screen.encode([(300.0, -5.0, 127.6)] * screen.ZONES)
        self.assertEqual(tuple(message[1:4]), (255, 0, 128))

    def test_a_foreign_message_is_refused(self):
        message = screen.encode([RED] * screen.ZONES)
        self.assertIsNone(screen.decode(b"\x02" + message[1:]))
        self.assertIsNone(screen.decode(message[:-1]))


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


class PipeCase(unittest.TestCase):
    """A temporary directory with the pipe of the LED service in it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.fifo = os.path.join(self.dir, "mirror")
        self.clock = Clock()
        self.mirror = screen.Mirror(self.fifo, clock=self.clock)
        self.mirror.create()
        self.addCleanup(self.mirror.close)
        self.writers = []
        self.addCleanup(self._close_writers)

    def _close_writers(self):
        for fd in self.writers:
            try:
                os.close(fd)
            except OSError:
                pass

    def writer(self):
        fd = os.open(self.fifo, os.O_WRONLY | os.O_NONBLOCK)
        self.writers.append(fd)
        return fd


class MirrorTest(PipeCase):

    def test_the_pipe_is_a_pipe_that_others_can_only_write(self):
        mode = os.lstat(self.fifo).st_mode
        self.assertTrue(stat.S_ISFIFO(mode))
        self.assertEqual(stat.S_IMODE(mode), 0o622)

    def test_a_file_in_place_of_the_pipe_is_refused(self):
        path = os.path.join(self.dir, "plain")
        open(path, "w").close()
        with self.assertRaises(OSError):
            screen.Mirror(path).create()

    def test_nothing_reads_until_the_bar_shows_the_mirror(self):
        with self.assertRaises(OSError) as caught:
            self.writer()
        self.assertEqual(caught.exception.errno, errno.ENXIO)
        self.assertIsNone(self.mirror.colours())
        self.writer()

    def test_the_newest_message_is_the_one_shown(self):
        self.mirror.colours()
        fd = self.writer()
        os.write(fd, screen.encode([(10, 20, 30)] * screen.ZONES))
        os.write(fd, screen.encode([RED] * screen.ZONES))
        self.assertEqual(self.mirror.colours(), [RED] * screen.ZONES)

    def test_a_message_split_over_two_reads_is_not_lost(self):
        self.mirror.colours()
        fd = self.writer()
        first = screen.encode([(10, 20, 30)] * screen.ZONES)
        second = screen.encode([RED] * screen.ZONES)
        os.write(fd, first[:30])
        self.assertIsNone(self.mirror.colours())
        os.write(fd, first[30:] + second)
        self.assertEqual(self.mirror.colours(), [RED] * screen.ZONES)

    def test_light_comes_faster_than_it_goes(self):
        self.mirror.colours()
        fd = self.writer()
        middle = (100.0, 100.0, 100.0)
        os.write(fd, screen.encode([middle] * screen.ZONES))
        self.mirror.colours()
        os.write(fd, screen.encode([(200.0,) * 3] * (screen.ZONES // 2)
                                   + [(0.0,) * 3]
                                   * (screen.ZONES - screen.ZONES // 2)))
        self.clock.now += 0.1
        shown = self.mirror.colours()
        rise = shown[0][0] - middle[0]
        fall = middle[0] - shown[-1][0]
        self.assertGreater(rise, 0.0)
        self.assertGreater(fall, 0.0)
        self.assertGreater(rise, fall)
        self.assertLess(shown[0][0], 200.0)

    def test_the_bar_gives_up_the_picture_after_the_hold(self):
        self.mirror.colours()
        os.write(self.writer(), screen.encode([RED] * screen.ZONES))
        self.assertIsNotNone(self.mirror.colours())
        self.clock.now += screen.HOLD - 0.1
        self.assertIsNotNone(self.mirror.colours())
        self.clock.now += 0.2
        self.assertIsNone(self.mirror.colours())

    def test_the_pipe_closes_when_the_bar_shows_something_else(self):
        self.mirror.colours()
        fd = self.writer()
        self.clock.now += screen.RELEASE - 1.0
        self.mirror.poll()
        self.assertIsNotNone(self.mirror.fd)
        self.clock.now += 2.0
        self.mirror.poll()
        self.assertIsNone(self.mirror.fd)
        with self.assertRaises(BrokenPipeError):
            os.write(fd, screen.encode([RED] * screen.ZONES))


# The stand-in for gst-launch-1.0. Its first argument says what it does.
FAKE = r"""
import os, sys, time
mode = sys.argv[1]
frame = bytes((200, 30, 20)) * (%d)
if mode == "frames":
    while True:
        os.write(1, frame)
        time.sleep(0.02)
elif mode == "error":
    sys.stderr.write("ERROR: from element /GstPipeline:pipeline0/"
                     "GstPipeWireSrc:pipewiresrc0: Internal data stream error.\n"
                     "Additional debug info:\n"
                     "../libs/gst/base/gstbasesrc.c(3132): gst_base_src_loop "
                     "(): /GstPipeline:pipeline0/GstPipeWireSrc:pipewiresrc0:\n"
                     "streaming stopped, reason not-negotiated (-4)\n")
    sys.exit(1)
elif mode == "videorate":
    # What GStreamer 1.24 does on the stream of gamescope: GLib writes the
    # failed check into both streams and stops the program.
    if "videorate" in sys.argv[2:]:
        os.write(1, b"Bail out! ERROR:../gst/videorate/gstvideorate.c:757:"
                    b"gst_video_rate_push_buffer: assertion failed\n")
        sys.stderr.write("**\nERROR:../gstreamer/subprojects/gst-plugins-base/"
                         "gst/videorate/gstvideorate.c:757:"
                         "gst_video_rate_push_buffer: assertion failed: "
                         "(GST_BUFFER_DURATION_IS_VALID (outbuf))\n")
        sys.stderr.flush()
        os.abort()
    while True:
        os.write(1, frame)
        time.sleep(0.02)
elif mode == "old":
    sys.stderr.write('WARNING: erroneous pipeline: no property '
                     '"target-object" in element "pipewiresrc0"\n')
    sys.exit(1)
else:
    time.sleep(30)
""" % (screen.WIDTH * screen.HEIGHT)


def objects(readers=(), size=None, own=None):
    """What pw-dump says: the stream of gamescope and who reads it.

    `own` is the link of the capture: (process id, state, error).
    """
    found = [{"id": 40, "type": "PipeWire:Interface:Node",
              "info": {"props": {"node.name": "gamescope",
                                 "media.class": "Video/Source"}}}]
    if size:
        found.append({"id": 41, "type": "PipeWire:Interface:Port",
                      "info": {"direction": "output",
                               "props": {"node.id": 40},
                               "params": {"Format": [{"size": {
                                   "width": size[0], "height": size[1]}}]}}})
    for index, (name, pid) in enumerate(readers):
        found.append({"id": 100 + index, "type": "PipeWire:Interface:Client",
                      "info": {"props": {"pipewire.sec.pid": pid,
                                         "application.name": name}}})
        found.append({"id": 200 + index, "type": "PipeWire:Interface:Node",
                      "info": {"props": {"client.id": 100 + index,
                                         "node.name": name}}})
        found.append({"id": 300 + index, "type": "PipeWire:Interface:Link",
                      "info": {"output-node-id": 40,
                               "input-node-id": 200 + index}})
    if own is not None:
        pid, state, error = own
        found.append({"id": 150, "type": "PipeWire:Interface:Client",
                      "info": {"props": {"pipewire.sec.pid": pid,
                                         "application.name":
                                         "gst-launch-1.0"}}})
        found.append({"id": 250, "type": "PipeWire:Interface:Node",
                      "info": {"props": {"client.id": 150,
                                         "node.name": screen.CLIENT}}})
        found.append({"id": 350, "type": "PipeWire:Interface:Link",
                      "info": {"output-node-id": 40, "input-node-id": 250,
                               "state": state, "error": error}})
    return found


class WatcherCase(PipeCase):

    def setUp(self):
        super().setUp()
        self.status = os.path.join(self.dir, "status.json")
        self.mode = "frames"
        self.argvs = []
        self.dumped = objects()
        self.missing = set()
        self.watcher = screen.Watcher(
            fifo=self.fifo, status=self.status, dump=lambda: self.dumped,
            launch=self.launch,
            which=lambda name: None if name in self.missing else "/usr/bin/" + name,
            element=lambda name: name not in self.missing,
            clock=self.clock, wall=lambda: 1000.0)
        self.addCleanup(self.watcher.close)

    def launch(self, argv, **options):
        self.argvs.append(argv)
        return subprocess.Popen([sys.executable, "-c", FAKE, self.mode]
                                + argv, **options)

    def written(self):
        with open(self.status, encoding="utf-8") as handle:
            return json.load(handle)

    def until(self, state, turns=40):
        for _turn in range(turns):
            self.watcher.step()
            if self.watcher.state == state:
                return
        self.fail("no %s after %d turns, but %s (%s)"
                  % (state, turns, self.watcher.state, self.watcher.detail))


class WatcherTest(WatcherCase):

    def test_with_no_pipe_the_mirror_is_off(self):
        os.unlink(self.fifo)
        self.assertEqual(self.watcher.step(), screen.LOOK_SECONDS)
        self.assertEqual(self.watcher.state, screen.OFF)
        self.assertEqual(self.written(), {"state": "off", "at": 1000.0})

    def test_a_pipe_that_comes_later_is_found_at_the_next_look(self):
        """The LED service makes the pipe when it starts again after a
        change, and a person looks at the status at that time."""
        os.unlink(self.fifo)
        self.watcher.step()
        self.assertEqual(self.watcher.state, screen.OFF)
        self.mirror.create()
        self.watcher.step()
        self.assertEqual(self.watcher.state, screen.IDLE)

    def test_with_no_reader_it_waits_and_starts_nothing(self):
        self.assertEqual(self.watcher.step(), screen.LOOK_SECONDS)
        self.assertEqual(self.watcher.state, screen.IDLE)
        self.assertEqual(self.argvs, [])

    def test_a_machine_with_no_gstreamer_says_so(self):
        self.mirror.colours()
        self.missing.add(screen.GST_LAUNCH)
        self.watcher.step()
        self.assertEqual(self.watcher.state, screen.NO_GSTREAMER)
        self.assertEqual(self.argvs, [])

    def test_a_missing_plugin_is_named(self):
        self.mirror.colours()
        self.missing.add("pipewiresrc")
        self.watcher.step()
        self.assertEqual(self.written()["state"], "no-plugin")
        self.assertEqual(self.written()["detail"], "pipewiresrc")

    def test_with_no_game_mode_there_is_no_screen(self):
        self.mirror.colours()
        self.dumped = []
        asked = []
        self.watcher.dump = lambda: (asked.append(1), self.dumped)[1]
        self.watcher.step()
        self.assertEqual(self.watcher.state, screen.NO_SCREEN)
        self.assertEqual(self.argvs, [])
        # pw-dump runs again only after CHECK_SECONDS.
        self.clock.now += screen.CHECK_SECONDS - 0.5
        self.watcher.step()
        self.assertEqual(len(asked), 1)
        self.clock.now += 0.5
        self.watcher.step()
        self.assertEqual(len(asked), 2)

    def test_it_never_starts_while_a_different_program_reads(self):
        self.mirror.colours()
        self.dumped = objects(readers=[("steam", 4242)])
        self.watcher.step()
        self.assertEqual(self.watcher.state, screen.BUSY)
        self.assertEqual(self.watcher.detail, "steam")
        self.assertEqual(self.argvs, [])

    def test_the_colours_of_the_screen_reach_the_bar(self):
        self.mirror.colours()
        self.until(screen.RUNNING)
        colours = None
        for _turn in range(20):
            colours = self.mirror.colours()
            if colours:
                break
            self.watcher.step()
        want = [round(channel) for channel in screen.treat(RED)]
        self.assertEqual([list(colour) for colour in colours],
                         [want] * screen.ZONES)
        argv = self.argvs[0]
        self.assertEqual(argv[:3], [screen.GST_LAUNCH, "-q", "pipewiresrc"])
        self.assertIn("target-object=gamescope", argv)

    def test_the_status_of_a_capture_says_how_fast_and_how_costly(self):
        self.mirror.colours()
        self.dumped = objects(size=(1280, 800))
        self.until(screen.RUNNING)
        self.clock.now += screen.CHECK_SECONDS
        for _turn in range(5):
            self.watcher.step()
        self.clock.now += screen.STATUS_SECONDS
        self.watcher.step()
        written = self.written()
        self.assertEqual(written["state"], "running")
        self.assertEqual(written["source"], "1280x800")
        self.assertGreater(written["fps"], 0.0)
        self.assertIn("cpu", written)

    def test_its_own_reader_is_not_a_different_program(self):
        self.mirror.colours()
        self.until(screen.RUNNING)
        self.dumped = objects(readers=[("gst-launch-1.0",
                                        self.watcher.pipeline.pid)])
        self.clock.now += screen.CHECK_SECONDS
        self.watcher.step()
        self.assertEqual(self.watcher.state, screen.RUNNING)

    def test_it_makes_room_for_a_recording(self):
        self.mirror.colours()
        self.until(screen.RUNNING)
        child = self.watcher.pipeline.process
        self.dumped = objects(readers=[
            ("gst-launch-1.0", self.watcher.pipeline.pid), ("steam", 4242)])
        self.clock.now += screen.CHECK_SECONDS
        self.watcher.step()
        self.assertEqual(self.watcher.state, screen.BUSY)
        self.assertIsNone(self.watcher.pipeline)
        self.assertIsNotNone(child.poll())

    def test_it_stops_when_the_bar_shows_something_else(self):
        self.mirror.colours()
        self.until(screen.RUNNING)
        child = self.watcher.pipeline.process
        self.mirror.close()
        self.watcher.step()
        self.assertEqual(self.watcher.state, screen.IDLE)
        self.assertIsNone(self.watcher.pipeline)
        self.assertIsNotNone(child.poll())

    def test_a_still_screen_keeps_the_bar(self):
        """gamescope sends nothing while the screen does not change."""
        self.mirror.colours()
        self.until(screen.RUNNING)
        sent = self.watcher.sent_at
        self.watcher.pipeline.frame = lambda timeout: None
        self.clock.now += screen.REPEAT_SECONDS
        self.watcher.step()
        self.assertEqual(self.watcher.sent_at, self.clock.now)
        self.assertGreater(self.watcher.sent_at, sent)

    def test_a_failure_names_the_reason_and_waits_longer_each_time(self):
        self.mirror.colours()
        self.mode = "error"
        with self.assertLogs(screen.LOG, "WARNING") as logged:
            self.until(screen.FAILED)
        self.assertEqual(self.watcher.detail, "pipewiresrc: not-negotiated")
        # The log has each line, for a person who looks for the cause.
        self.assertTrue(any("reason not-negotiated (-4)" in line
                            for line in logged.output))
        self.assertEqual(self.watcher.retry_at,
                         self.clock.now + screen.RETRY_SECONDS)
        self.clock.now = self.watcher.retry_at
        self.watcher.state = None
        self.until(screen.FAILED)
        self.assertEqual(self.watcher.retry_at,
                         self.clock.now + 2 * screen.RETRY_SECONDS)
        self.assertEqual(len(self.argvs), 2)

    def test_an_older_gstreamer_gets_the_node_by_its_id(self):
        self.mirror.colours()
        self.mode = "old"
        for _turn in range(40):
            self.watcher.step()
            if len(self.argvs) == 2:
                break
        self.assertIn("path=40", self.argvs[1])
        self.assertNotIn("target-object=gamescope", self.argvs[1])

    def test_a_still_screen_at_the_start_is_no_failure(self):
        """gamescope sends no picture until the screen changes."""
        self.mirror.colours()
        self.mode = "silent"
        self.until(screen.STARTING)
        child = self.watcher.pipeline.process
        self.dumped = objects(own=(child.pid, "active", None))
        for _check in range(4):
            self.clock.now += screen.CHECK_SECONDS
            self.watcher.step()
            self.assertEqual(self.watcher.state, screen.WAITING)
        self.assertIs(self.watcher.pipeline.process, child)
        self.assertEqual(self.written()["state"], "waiting")

    def test_a_link_that_does_not_become_active_is_a_failure(self):
        for own, detail in (((None, "negotiating", None),
                             "link negotiating"),
                            ((None, "error", "no more input formats"),
                             "link error: no more input formats"),
                            (None, "no link to gamescope")):
            with self.subTest(detail=detail):
                self.watcher.close()
                self.watcher.state = None
                self.watcher.retry_at = 0.0
                self.mirror.colours()
                self.mode = "silent"
                self.dumped = objects()
                self.until(screen.STARTING)
                pid = self.watcher.pipeline.pid
                self.dumped = objects(own=None if own is None
                                      else (pid,) + own[1:])
                self.clock.now += screen.CHECK_SECONDS
                self.watcher.step()
                self.assertEqual(self.watcher.state, screen.STARTING)
                self.clock.now += screen.LINK_SECONDS
                self.watcher.step()
                self.assertEqual(self.watcher.state, screen.FAILED)
                self.assertEqual(self.watcher.detail, detail)

    def test_at_most_rate_pictures_each_second_reach_the_bar(self):
        self.mirror.colours()
        self.until(screen.RUNNING)
        self.assertEqual(self.watcher.frames, 1)
        # The fake gives a picture each 20 ms, but the clock stands.
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            self.watcher.step()
        self.assertEqual(self.watcher.frames, 1)
        self.assertIsNotNone(self.watcher.pending)
        self.clock.now += 1.0 / screen.RATE
        self.watcher.step()
        self.assertEqual(self.watcher.frames, 2)

    def test_the_last_picture_of_a_change_is_not_lost(self):
        self.mirror.colours()
        self.until(screen.RUNNING)
        deadline = time.monotonic() + 0.1
        while self.watcher.pending is None and time.monotonic() < deadline:
            self.watcher.step()
        self.assertIsNotNone(self.watcher.pending)
        # Then the screen stops: no picture comes after this one.
        self.watcher.pipeline.frame = lambda timeout: None
        self.clock.now += 1.0 / screen.RATE
        self.watcher.step()
        self.assertIsNone(self.watcher.pending)
        self.assertEqual(self.watcher.frames, 2)

    def test_a_videorate_that_stops_gives_way_to_watcher(self):
        """GStreamer 1.24 and 1.26 stop on the stream of gamescope when
        videorate has max-rate. This is the line that the panel showed."""
        self.mirror.colours()
        self.mode = "videorate"
        with self.assertLogs(screen.LOG, "WARNING") as logged:
            self.until(screen.RUNNING)
        self.assertEqual(len(self.argvs), 2)
        self.assertIn("videorate", self.argvs[0])
        self.assertNotIn("videorate", self.argvs[1])
        self.assertTrue(any("assertion failed" in line
                            for line in logged.output))

    def test_the_status_goes_away_with_the_watcher(self):
        self.watcher.step()
        self.assertTrue(os.path.exists(self.status))
        self.watcher.close()
        self.assertFalse(os.path.exists(self.status))


class CommandTest(unittest.TestCase):

    def test_the_pipeline_uses_the_elements_that_are_checked(self):
        argv = screen.command("gamescope")
        names = [argv[2]] + [argv[index + 1] for index, word in enumerate(argv)
                             if word == "!"]
        used = {name for name in names if not name.startswith("video/")}
        self.assertEqual(used, set(screen.ELEMENTS))

    def test_it_scales_in_two_steps_to_the_picture_size(self):
        argv = screen.command("gamescope")
        self.assertIn("video/x-raw,width=%d,height=%d"
                      % (screen.COARSE * screen.WIDTH,
                         screen.COARSE * screen.HEIGHT), argv)
        self.assertIn("video/x-raw,width=%d,height=%d"
                      % (screen.WIDTH, screen.HEIGHT), argv)
        self.assertIn("method=nearest-neighbour", argv)
        self.assertIn("method=bilinear2", argv)
        self.assertEqual(argv[-3:], ["fdsink", "fd=1", "sync=false"])

    def test_videorate_gives_a_fixed_rate(self):
        """videorate with max-rate and no fixed rate stops on a stream with
        the rate 0/1, and the stream of gamescope has that rate."""
        argv = screen.command("gamescope")
        at = argv.index("videorate")
        self.assertEqual(argv[at:at + 4],
                         ["videorate", "drop-only=true", "!",
                          "video/x-raw,framerate=%d/1" % screen.RATE])
        self.assertFalse([word for word in argv if "max-rate" in word])
        self.assertNotIn("videorate", screen.command("gamescope", rate=False))

    @unittest.skipUnless(shutil.which(screen.GST_LAUNCH),
                         "GStreamer is not on this machine")
    def test_a_real_gstreamer_accepts_the_pipeline(self):
        """With a test source in place of the stream of gamescope."""
        for rate in ("30/1", "0/1"):
            for videorate in (True, False):
                with self.subTest(rate=rate, videorate=videorate):
                    self.check_real(rate, videorate)

    def check_real(self, rate, videorate):
        # The stream of gamescope has the rate 0/1. A test source with that
        # rate gives one picture, with no duration, as gamescope does.
        argv = screen.command("gamescope", rate=videorate)
        tail = argv[argv.index("!"):]
        source = [screen.GST_LAUNCH, "-q", "videotestsrc", "num-buffers=4",
                  "pattern=red", "!",
                  "video/x-raw,format=BGRx,width=1280,height=800,"
                  "framerate=" + rate]
        done = subprocess.run(source + tail, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=60, check=False,
                              env=dict(os.environ, LC_ALL="C"))
        self.assertEqual(done.returncode, 0, done.stderr[-300:])
        self.assertGreater(len(done.stdout), 0)
        self.assertEqual(len(done.stdout) % screen.FRAME, 0)
        frame = done.stdout[:screen.FRAME]
        for colour in screen.zones(frame):
            self.assertGreater(colour[0], 240)
            self.assertLess(colour[1], 15)


class ReadersTest(unittest.TestCase):

    def test_the_stream_of_gamescope_is_found(self):
        self.assertEqual(screen.screen_node(objects()), 40)
        self.assertIsNone(screen.screen_node([]))

    def test_an_audio_node_with_the_name_is_not_the_screen(self):
        found = objects()
        found[0]["info"]["props"]["media.class"] = "Audio/Source"
        self.assertIsNone(screen.screen_node(found))

    def test_each_reader_is_named_and_its_own_is_left_out(self):
        found = objects(readers=[("steam", 1), ("gst-launch-1.0", 2)])
        self.assertEqual(screen.readers(found, 40), ["steam", "gst-launch-1.0"])
        self.assertEqual(screen.readers(found, 40, own_pid=2), ["steam"])

    def test_a_name_is_made_safe(self):
        found = objects(readers=[('evil"\n<name>' + "x" * 40, 1)])
        name = screen.readers(found, 40)[0]
        self.assertRegex(name, r"^[A-Za-z0-9 ._-]{1,24}$")

    def test_a_damaged_dump_finds_nothing(self):
        for found in ([{"type": "PipeWire:Interface:Link", "info": None}],
                      [{"id": 1, "info": "x"}]):
            self.assertIsNone(screen.screen_node(found))
            self.assertEqual(screen.readers(found, 40), [])
            self.assertEqual(screen.screen_size(found, 40), "")


class StatusTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "status.json")

    def write(self, values):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(values, handle)

    def read(self):
        return screen.read_status(self.path, wall=lambda: 1000.0)

    def test_no_file_means_no_watcher(self):
        self.assertEqual(self.read(), {"state": "gone"})

    def test_an_old_file_means_no_watcher(self):
        self.write({"state": "running", "at": 1000.0 - screen.STATUS_STALE - 1})
        self.assertEqual(self.read(), {"state": "gone"})

    def test_a_damaged_file_means_no_watcher(self):
        for values in ({"state": "dancing", "at": 1000.0}, [1, 2],
                       {"state": "running", "at": True}):
            self.write(values)
            self.assertEqual(self.read(), {"state": "gone"}, values)
        with open(self.path, "wb") as handle:
            handle.write(b"\xff{")
        self.assertEqual(self.read(), {"state": "gone"})

    def test_only_known_values_come_through(self):
        self.write({"state": "running", "at": 999.0, "fps": 14.96,
                    "cpu": 1.234, "source": "1280x800", "detail": "x" * 90,
                    "extra": "never"})
        self.assertEqual(self.read(), {"state": "running", "fps": 15.0,
                                       "cpu": 1.2, "source": "1280x800",
                                       "detail": "x" * screen.DETAIL_CHARS})

    def test_a_strange_source_is_left_out(self):
        self.write({"state": "running", "at": 999.0, "source": "big"})
        self.assertNotIn("source", self.read())


class ErrorTest(unittest.TestCase):

    def test_the_reason_of_a_stop_is_the_detail(self):
        pipeline = screen.Pipeline([])
        pipeline._errors = [
            "ERROR: from element /GstPipeline:pipeline0/GstPipeWireSrc:"
            "pipewiresrc0: Internal data stream error.",
            "Additional debug info:",
            "../gstreamer/subprojects/gstreamer/libs/gst/base/gstbasesrc.c"
            "(3177): gst_base_src_loop (): /GstPipeline:pipeline0/"
            "GstPipeWireSrc:pipewiresrc0:",
            "streaming stopped, reason not-negotiated (-4)"]
        pipeline._read_errors = lambda: 0
        self.assertEqual(pipeline.error(), "pipewiresrc: not-negotiated")

    def test_a_failed_assertion_names_the_element(self):
        """The line that the panel showed as "../gstreamer/subprojects/
        gst-plugins-bas"."""
        self.assertEqual(screen.describe([
            "**", "ERROR:../gstreamer/subprojects/gst-plugins-base/gst/"
            "videorate/gstvideorate.c:757:gst_video_rate_push_buffer: "
            "assertion failed: (GST_BUFFER_DURATION_IS_VALID (outbuf))"]),
            "videorate: assertion failed: (GST_BUFFER")

    def test_a_general_error_takes_the_text_for_a_developer(self):
        self.assertEqual(screen.describe([
            "ERROR: from element /GstPipeline:pipeline0/GstVideoRate:"
            "videorate0: GStreamer encountered a general stream error.",
            "Additional debug info:",
            "../gst/videorate/gstvideorate.c(1699): gst_video_rate_transform"
            "_ip (): /GstPipeline:pipeline0/GstVideoRate:videorate0:",
            "videorate requires a non-variable framerate",
            "ERROR: pipeline doesn't want to preroll."]),
            "videorate: videorate requires a non-vari")

    def test_an_error_of_the_stream_keeps_what_went_wrong(self):
        self.assertEqual(screen.describe([
            "ERROR: from element /GstPipeline:pipeline0/GstPipeWireSrc:"
            "pipewiresrc0: stream error: target not found",
            "Additional debug info:",
            "../src/gst/gstpipewiresrc.c(692): on_state_changed (): "
            "/GstPipeline:pipeline0/GstPipeWireSrc:pipewiresrc0"]),
            "pipewiresrc: target not found")

    def test_a_path_keeps_its_file_name(self):
        self.assertEqual(screen._short("at ../a/b/file.c(12) and "
                                       "video/x-raw"),
                         "at file.c(12) and video/x-raw")

    def test_a_line_in_two_reads_is_one_line(self):
        read, write = os.pipe()
        os.set_blocking(read, False)
        pipeline = screen.Pipeline([])
        pipeline.process = unittest.mock.Mock(stderr=os.fdopen(read, "rb"))
        self.addCleanup(pipeline.process.stderr.close)
        os.write(write, b"ERROR: from element /a/b0: tar")
        pipeline._read_errors()
        os.write(write, b"get not found\nthe end")
        os.close(write)
        self.assertEqual(pipeline.said(),
                         ["ERROR: from element /a/b0: target not found",
                          "the end"])

    def test_an_error_line_loses_its_element_path(self):
        self.assertEqual(screen._short("ERROR: from element /GstPipeline:"
                                       "pipeline0/GstX:x0: target not found"),
                         "target not found")


class FakeScreen:
    """Something with .colours(), which is all the renderer wants."""

    def __init__(self, colours=None):
        self.picture = colours
        self.asked = 0

    def colours(self, now=None):
        self.asked += 1
        return None if self.picture is None else list(self.picture)


def renderer(**options):
    return render.Renderer(led_count=shim.LOGICAL_LEDS,
                           mapping=render.MAPPING_CROP,
                           rainbow_shows=render.SHOWS_MIRROR, **options)


class RenderTest(unittest.TestCase):
    """The mirror in the rainbow slot of the renderer."""

    def setUp(self):
        self.colours = [tuple(float(value) for value in colour)
                        for colour in spectrum()]
        self.screen = FakeScreen(self.colours)
        self.rainbow = shim.make_snapshot(shim.EFFECT_RAINBOW)

    def test_the_slot_draws_the_colours_of_the_screen(self):
        drawn = renderer(screen=self.screen).render_logical(self.rainbow, 1.0)
        self.assertEqual(drawn, self.colours)

    def test_with_no_picture_the_slot_is_the_rainbow_of_steam(self):
        for source in (FakeScreen(None), None):
            engine = renderer(screen=source)
            self.assertEqual(engine.render_logical(self.rainbow, 1.0),
                             render._rainbow(self.rainbow, 1.0, engine))

    def test_the_screen_is_asked_one_time_for_each_frame(self):
        """A question says that the bar shows the screen."""
        engine = renderer(screen=self.screen)
        engine.is_animated(self.rainbow)
        engine.render(self.rainbow, 1.0)
        engine.render(self.rainbow, 1.1)
        self.assertEqual(self.screen.asked, 2)

    def test_the_screen_is_not_asked_for_a_different_effect(self):
        engine = renderer(screen=self.screen)
        for effect in (shim.EFFECT_BREATH, shim.EFFECT_MANUAL,
                       shim.EFFECT_OFF):
            engine.render(shim.make_snapshot(effect), 1.0)
        engine.render(shim.make_snapshot(shim.EFFECT_RAINBOW, enabled=0), 1.0)
        # A desktop scene names its own effect.
        engine.render(self.rainbow, 1.0, render.SHOWS_FIRE)
        render.Renderer(led_count=17, rainbow_shows=render.SHOWS_FIRE,
                        screen=self.screen).render(self.rainbow, 1.0)
        self.assertEqual(self.screen.asked, 0)

    def test_the_mirror_moves(self):
        engine = renderer(screen=self.screen)
        engine.render(self.rainbow, 1.0)
        self.assertTrue(engine.is_animated(self.rainbow))

    def test_the_brightness_of_steam_dims_it_and_the_speed_does_not_reach_it(self):
        self.assertEqual(render.rainbow_takes(render.SHOWS_MIRROR),
                         render.TAKES_LIGHT)
        full = renderer(screen=FakeScreen([(200.0, 100.0, 50.0)] * 17))
        dim = shim.make_snapshot(shim.EFFECT_RAINBOW, brightness=128)
        payload = full.render(dim, 1.0)
        self.assertEqual(tuple(payload[:3]), (100, 50, 25))


class LoopTest(unittest.TestCase):
    """The LED service with the mirror in its slot."""

    class Link:
        connected = True

        def __init__(self):
            self.sent = []

        def connect(self):
            return True

        def poll(self):
            pass

        def shutdown(self):
            pass

        def send_frame(self, payload, led_count):
            self.sent.append(bytes(payload))
            return True

    class Source:
        def __init__(self, snapshot):
            self.snapshot = snapshot

        def read(self):
            return self.snapshot

        def close(self):
            pass

    class Pipe(FakeScreen):
        def __init__(self, colours):
            super().__init__(colours)
            self.polls = 0
            self.closed = False

        def poll(self, now=None):
            self.polls += 1

        def close(self):
            self.closed = True

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.fifo = os.path.join(self.dir, "mirror")

    def conf(self, shows):
        conf = dict(config.DEFAULTS)
        conf.update(SERIAL_PORT="/dev/does-not-exist", NOTIFY=False,
                    RAINBOW_SHOWS=shows, MAPPING=render.MAPPING_CROP)
        return conf

    def test_only_the_mirror_makes_the_pipe(self):
        with unittest.mock.patch.object(screen, "FIFO", self.fifo):
            self.assertIsNone(service.build_mirror(self.conf("fire")))
            self.assertFalse(os.path.exists(self.fifo))
            mirror = service.build_mirror(self.conf("mirror"))
        self.assertEqual(mirror.path, self.fifo)
        self.assertTrue(stat.S_ISFIFO(os.lstat(self.fifo).st_mode))

    def test_a_pipe_that_cannot_be_made_is_a_warning(self):
        missing = os.path.join(self.dir, "no", "mirror")
        with unittest.mock.patch.object(screen, "FIFO", missing), \
                self.assertLogs("steamos-utility-center", "WARNING"):
            self.assertIsNotNone(service.build_mirror(self.conf("mirror")))

    def test_the_loop_draws_the_screen_and_lets_the_pipe_close(self):
        with unittest.mock.patch.object(screen, "FIFO", self.fifo):
            runner = service.Runner(self.conf("mirror"))
        self.assertIs(runner.renderer.screen, runner.mirror)
        pipe = self.Pipe([(200.0, 100.0, 50.0)] * 17)
        runner.mirror = runner.renderer.screen = pipe
        runner.link = self.Link()
        snapshot = shim.make_snapshot(shim.EFFECT_RAINBOW)
        snapshot.seq = 5
        runner.source = self.Source(snapshot)
        runner._wait = lambda interval: (time.sleep(0.005), (False, False))[1]
        thread = threading.Thread(target=runner._loop, daemon=True)
        thread.start()
        time.sleep(0.3)
        runner.running = False
        thread.join(timeout=10)
        self.assertGreater(pipe.polls, 0)
        self.assertGreater(pipe.asked, 0)
        self.assertEqual(runner.link.sent[-1][:3], bytes((200, 100, 50)))


class DemoTest(unittest.TestCase):
    """The made-up screen of the previews."""

    def test_the_loop_ends_where_it_starts(self):
        self.assertEqual(screen.demo(0.0), screen.demo(1.0))
        for end, start in zip(screen.demo(0.999999), screen.demo(0.0)):
            for one, two in zip(end, start):
                self.assertAlmostEqual(one, two, delta=0.01)

    def test_each_picture_is_a_bar_of_colours(self):
        for step in range(40):
            colours = screen.demo(step / 40.0)
            self.assertEqual(len(colours), screen.ZONES)
            for colour in colours:
                for channel in colour:
                    self.assertTrue(0.0 <= channel <= 255.0, colour)

    def test_a_picture_stays_before_it_changes(self):
        part = 1.0 / len(screen.DEMO)
        self.assertEqual(screen.demo(0.0),
                         screen.demo(part * screen.DEMO_STAY * 0.99))
        self.assertNotEqual(screen.demo(0.0), screen.demo(part * 0.99))


class StatusPageTest(unittest.TestCase):
    """The card of the mirror on the Status page of the control panel."""

    def test_no_card_while_the_slot_shows_a_different_effect(self):
        self.assertIsNone(ledpanel.mirror_part("fire", {"state": "running"}))

    def test_each_state_has_a_sentence(self):
        self.assertEqual(set(ledpanel.MIRROR_SAYS), set(screen.STATES))

    def test_a_running_mirror_gives_its_numbers(self):
        part = ledpanel.mirror_part("mirror", {
            "state": "running", "fps": 15.0, "cpu": 1.2,
            "source": "1280x800"})
        self.assertTrue(part.ok)
        self.assertEqual(part.verdict, "Runs.")
        self.assertEqual(part.detail[:3], ["Pictures each second: 15",
                                           "Processor: 1.2 % of one core",
                                           "Screen: 1280x800"])
        self.assertIn("steamos-utility-center-mirror", part.detail[-1])

    def test_the_detail_names_what_stops_it(self):
        part = ledpanel.mirror_part("mirror", {"state": "busy",
                                               "detail": "steam"})
        self.assertTrue(part.ok)
        self.assertEqual(part.verdict, "Paused, because steam reads the "
                                       "screen.")
        part = ledpanel.mirror_part("mirror", {"state": "no-plugin",
                                               "detail": "pipewiresrc"})
        self.assertFalse(part.ok)
        self.assertIn("pipewiresrc", part.verdict)

    def test_a_still_screen_is_no_fault(self):
        part = ledpanel.mirror_part("mirror", {"state": "waiting"})
        self.assertTrue(part.ok)
        self.assertIn("screen changes", part.verdict)

    def test_no_capture_service_is_a_fault(self):
        part = ledpanel.mirror_part("mirror", {"state": "gone"})
        self.assertFalse(part.ok)
        self.assertFalse(ledpanel.mirror_part("mirror", {}).ok)

    def test_the_menu_names_it(self):
        self.assertIn(("Mirror the screen", "mirror"),
                      ledpanel.rainbow_choices(render.RAINBOW_CHOICES))


if __name__ == "__main__":
    unittest.main()
