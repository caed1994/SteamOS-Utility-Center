# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Nanoleaf Pegboard Desk Dock: server/steamos_utility_center/pegboard.py.

Everything measured here came off a board. It is written down because the
board is the only place it exists: Nanoleaf ships no program for Linux, and
each number below was read from the device or from its descriptors.

    37fa:8201                   the vendor and the product
    Report Count 64, no ID      so a write is 65 bytes, one of them the
                                report number that Linux hidraw wants
    02 00 c0 + 192 bytes        a colour frame for 64 LEDs, TLV
    82 00 01 00                 the answer: the type asked for, bit 7 set
    ff 00 00 -> green           the wire is GRB
    LED 0 bottom left,          one chain, up the left side and down the
    31 top left, 32 top         right. So the middle of the chain is the top
    right, 63 bottom right      of the board.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import ctl                       # noqa: E402
from steamos_utility_center import modules                   # noqa: E402
from steamos_utility_center import mounts                    # noqa: E402
from steamos_utility_center import pegboard                  # noqa: E402
from steamos_utility_center import render                    # noqa: E402
from steamos_utility_center import shim                      # noqa: E402


def triples(payload):
    return [tuple(payload[at:at + 3]) for at in range(0, len(payload), 3)]


class FramingTest(unittest.TestCase):
    """What goes on the wire."""

    def test_a_message_carries_its_length_big_endian(self):
        said = pegboard.message(pegboard.TYPE_COLOUR, bytes(192))
        self.assertEqual(said[:3].hex(), "0200c0")

    def test_a_frame_of_64_leds_needs_four_reports(self):
        """195 bytes into reports of 64. The last one is mostly padding."""
        said = pegboard.frame(bytes(3 * 32), pegboard.SHOWS_RAINBOW_WAVE)
        pieces = pegboard.reports(said)
        self.assertEqual(len(pieces), 4)
        self.assertTrue(all(len(piece) == 64 for piece in pieces))

    def test_the_last_report_is_padded_and_not_short(self):
        """A short write is a report of the wrong size, and the board drops it."""
        pieces = pegboard.reports(b"\x01\x02\x03")
        self.assertEqual(len(pieces[0]), pegboard.REPORT_BYTES)
        self.assertEqual(pieces[0][3:], bytes(pegboard.REPORT_BYTES - 3))

    def test_a_payload_too_long_for_the_length_field_is_refused(self):
        with self.assertRaises(pegboard.PegboardError):
            pegboard.message(pegboard.TYPE_COLOUR, bytes(0x10000))


class WireOrderTest(unittest.TestCase):
    """GRB, which is what the board did when it was asked."""

    def test_red_goes_in_the_second_byte(self):
        self.assertEqual(tuple(pegboard.on_the_wire(bytes([255, 0, 0]))),
                         (0, 255, 0))

    def test_green_goes_in_the_first(self):
        self.assertEqual(tuple(pegboard.on_the_wire(bytes([0, 255, 0]))),
                         (255, 0, 0))

    def test_blue_stays_where_it_is(self):
        self.assertEqual(tuple(pegboard.on_the_wire(bytes([0, 0, 255]))),
                         (0, 0, 255))

    def test_it_does_each_led_and_not_only_the_first(self):
        said = pegboard.on_the_wire(bytes([255, 0, 0, 0, 255, 0]))
        self.assertEqual(triples(said), [(0, 255, 0), (255, 0, 0)])


class FoldTest(unittest.TestCase):
    """The fold, which belongs to one effect and is not a setting.

    It was `SHAPE`, mirror against chain. Every effect looked better on the
    chain, where it travels once around the board, so the switch went and the
    one effect that gained from the fold became an effect of its own.
    """

    WAVE = pegboard.SHOWS_RAINBOW_WAVE
    DRAWN = bytes([1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4])   # bottom to top

    def test_the_wave_is_drawn_on_half_the_board(self):
        self.assertEqual(pegboard.logical_leds(self.WAVE), 32)

    def test_every_other_effect_takes_the_whole_chain(self):
        for name in pegboard.EFFECTS:
            if name == self.WAVE:
                continue
            self.assertEqual(pegboard.logical_leds(name), 64, name)

    def test_the_wave_is_the_rainbow_and_the_rest_are_themselves(self):
        """Two names go to the rainbow. The wave is the rainbow with a fold.

        The patrol is there for a different reason: the renderer takes the
        name of a slot effect whether it reads the slot or not, and "patrol"
        is not one of them. It draws by the snapshot's effect field, so the
        name is unread.
        """
        self.assertEqual(pegboard.drawn_by(self.WAVE), render.SHOWS_RAINBOW)
        self.assertEqual(pegboard.drawn_by(pegboard.SHOWS_PATROL),
                         render.SHOWS_RAINBOW)
        for name in pegboard.EFFECTS:
            if name in (self.WAVE, pegboard.SHOWS_PATROL):
                continue
            self.assertEqual(pegboard.drawn_by(name), name, name)

    def test_every_name_the_renderer_is_given_is_one_it_knows(self):
        """Which is what drawn_by is for. A name it does not know raises."""
        for name in pegboard.EFFECTS:
            self.assertIn(pegboard.drawn_by(name), render.RAINBOW_CHOICES,
                          name)

    def test_the_wave_puts_the_bottom_in_both_bottom_corners(self):
        """LED 0 is the bottom left and LED 63 the bottom right."""
        said = triples(pegboard.fold(self.DRAWN, self.WAVE))
        self.assertEqual(said[0], (1, 1, 1))
        self.assertEqual(said[-1], (1, 1, 1))

    def test_the_wave_puts_the_top_in_both_top_corners(self):
        """The two middle LEDs of the chain are the top of the board."""
        said = triples(pegboard.fold(self.DRAWN, self.WAVE))
        self.assertEqual(said[3], (4, 4, 4))
        self.assertEqual(said[4], (4, 4, 4))

    def test_the_wave_is_the_same_length_as_the_board(self):
        said = pegboard.fold(bytes(3 * 32), self.WAVE)
        self.assertEqual(len(said), 3 * 64)

    def test_an_unfolded_effect_is_left_alone(self):
        self.assertEqual(pegboard.fold(self.DRAWN, "ooze"), self.DRAWN)

    def test_the_shape_is_no_longer_a_setting(self):
        self.assertNotIn("SHAPE", pegboard.DEFAULTS)



class AnswerTest(unittest.TestCase):
    """82 00 01 00, which is how a frame says that it arrived."""

    def test_it_names_the_type_it_answers(self):
        said = pegboard.answer_of(bytes.fromhex("820001" + "00" * 61))
        self.assertEqual(said, (pegboard.TYPE_COLOUR, b"\x00"))

    def test_something_with_no_answer_bit_is_not_an_answer(self):
        self.assertIsNone(pegboard.answer_of(bytes.fromhex("020001 00")))

    def test_a_short_read_is_not_an_answer(self):
        self.assertIsNone(pegboard.answer_of(b"\x82"))


class FindTest(unittest.TestCase):
    """Which hidraw node it is, by vendor and product."""

    def _tree(self, entries):
        where = tempfile.mkdtemp()
        for node, hid_id in entries:
            at = os.path.join(where, "class", "hidraw", node, "device")
            os.makedirs(at)
            with open(os.path.join(at, "uevent"), "w") as handle:
                handle.write("DRIVER=hid-generic\nHID_ID=%s\n" % hid_id)
        return os.path.join(where, "class", "hidraw", "*", "device", "uevent")

    def test_it_finds_the_board_among_the_others(self):
        """A machine with a controller on it has several hidraw nodes."""
        where = self._tree([("hidraw0", "0003:000028DE:00001205"),
                            ("hidraw5", "0003:000037FA:00008201")])
        self.assertEqual(pegboard.find_device(where), "/dev/hidraw5")

    def test_a_machine_with_no_board_says_so(self):
        where = self._tree([("hidraw0", "0003:000028DE:00001205")])
        self.assertIsNone(pegboard.find_device(where))

    def test_it_does_not_go_by_the_number(self):
        """hidraw5 today is hidraw2 after the next boot."""
        where = self._tree([("hidraw2", "0003:000037FA:00008201")])
        self.assertEqual(pegboard.find_device(where), "/dev/hidraw2")


class ConfigTest(unittest.TestCase):
    """Its own file, its own validator."""

    def _write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".conf",
                                             delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_a_file_that_is_not_there_is_the_defaults(self):
        """A board nobody configured, which is not an error."""
        self.assertEqual(pegboard.read("/nowhere/at/all"), pegboard.DEFAULTS)

    def test_it_reads_the_types_the_defaults_have(self):
        values = pegboard.read(self._write("FPS=30\nSPEED=2.5\nENABLED=0\n"))
        self.assertEqual(values["FPS"], 30)
        self.assertEqual(values["SPEED"], 2.5)
        self.assertIs(values["ENABLED"], False)

    def test_the_file_this_project_ships_is_one_it_accepts(self):
        shipped = os.path.join(REPO, "server",
                               "steamos-utility-center-pegboard.conf")
        values = pegboard.read(shipped)
        self.assertEqual(set(values), set(pegboard.DEFAULTS))

    def test_an_unknown_option_is_a_mistake_and_not_a_shrug(self):
        with self.assertRaises(pegboard.PegboardError):
            pegboard.read(self._write("SIDEWAYS=1\n"))

    def test_the_count_of_leds_is_not_a_setting(self):
        """One board is 64. A different count is a different board, with a
        layout of its own and not only a number of its own."""
        self.assertEqual(pegboard.LEDS, 64)
        self.assertNotIn("LEDS", pegboard.DEFAULTS)
        # And a file that still names it is read. See RETIRED.
        self.assertEqual(pegboard.read(self._write("LEDS=32\n"))["FPS"],
                         pegboard.DEFAULTS["FPS"])

    def test_the_effects_are_the_renderer_s_without_the_load_gauge(self):
        """Derived and not written down, so a new effect reaches the board.

        Three exceptions. The gauge draws two bars of a fixed colour on a
        strip, which reads as a meter behind a case and as two coloured stubs
        on a board. The wave is the board's own, because the fold it needs is
        the geometry of this board and not an effect. The patrol is an effect
        of Steam's own and not one of the slot, so the list it comes from
        does not hold it.
        """
        self.assertEqual(
            set(pegboard.EFFECTS),
            (set(render.RAINBOW_CHOICES) - {render.SHOWS_LOAD})
            | {pegboard.SHOWS_RAINBOW_WAVE, pegboard.SHOWS_PATROL})
        for name in pegboard.EFFECTS:
            values = dict(pegboard.DEFAULTS, EFFECT=name)
            self.assertEqual(pegboard.validate(values)["EFFECT"], name)

    def test_the_patrol_is_on_the_board(self):
        """It is not an effect of the rainbow slot. Steam has it as an effect
        of its own, and the renderer reads that from the snapshot's field."""
        self.assertIn(pegboard.SHOWS_PATROL, pegboard.EFFECTS)
        self.assertNotIn(pegboard.SHOWS_PATROL, render.RAINBOW_CHOICES)
        snapshot = pegboard.build_snapshot(
            dict(pegboard.DEFAULTS, EFFECT=pegboard.SHOWS_PATROL))
        self.assertEqual(snapshot.effect, shim.EFFECT_PATROL)

    def test_every_other_effect_asks_for_the_rainbow_slot(self):
        for name in pegboard.EFFECTS:
            if name == pegboard.SHOWS_PATROL:
                continue
            snapshot = pegboard.build_snapshot(
                dict(pegboard.DEFAULTS, EFFECT=name))
            self.assertEqual(snapshot.effect, shim.EFFECT_RAINBOW, name)

    def test_a_pixel_carries_the_four_values_a_pixel_has(self):
        """PIXEL_SIZE is 4, and the fourth is that LED's brightness.

        base_color() unpacks all four, and three raised ValueError there.
        Nothing noticed until the patrol arrived: it is the first effect of
        this board that asks a snapshot for its colour.
        """
        snapshot = pegboard.build_snapshot(
            dict(pegboard.DEFAULTS, COLOR="#ff6e00"))
        self.assertEqual(len(snapshot.pixels[0]), shim.PIXEL_SIZE)
        self.assertEqual(snapshot.base_color(), (255, 110, 0))

    def test_a_colour_it_cannot_read_is_refused(self):
        with self.assertRaises(pegboard.PegboardError):
            pegboard.validate(dict(pegboard.DEFAULTS, COLOR="chartreuse"))

    def test_the_patrol_is_one_dot_and_not_a_number_of_them(self):
        self.assertNotIn("PATROL_DOTS", pegboard.DEFAULTS)
        self.assertIn("PATROL_DOTS", pegboard.RETIRED)

    def test_a_setting_this_board_dropped_is_read_and_ignored(self):
        """A file keeps the line a person wrote in it.

        A version that refuses to start because of an option it dropped
        itself turns its own change into a board that stays dark, and the
        message names a key that no documentation mentions any more.
        """
        values = pegboard.read(self._write(
            "BRIGHTNESS=200\nPATROL_DOTS=4\nSHAPE=mirror\n"
            "LOAD_SWAP=1\nLOAD_CPU_COLOR=#ff6e00\n"
            "LOAD_GPU_COLOR=#1a9fff\n"))
        self.assertEqual(values["BRIGHTNESS"], 200)
        for gone in pegboard.RETIRED:
            self.assertNotIn(gone, values, gone)

    def test_a_name_that_was_never_a_setting_is_still_refused(self):
        """A typed name is a fault, and silence about it is worse."""
        with self.assertRaises(pegboard.PegboardError):
            pegboard.read(self._write("BRIGTHNESS=200\n"))

    def test_the_load_gauge_is_refused_and_its_settings_are_gone(self):
        with self.assertRaises(pegboard.PegboardError):
            pegboard.validate(dict(pegboard.DEFAULTS,
                                   EFFECT=render.SHOWS_LOAD))
        for key in ("LOAD_CPU_COLOR", "LOAD_GPU_COLOR", "LOAD_SWAP"):
            self.assertNotIn(key, pegboard.DEFAULTS)

    def test_the_effects_run_at_the_speed_that_is_asked_for(self):
        """SPEED moved nothing, and every effect ran at the fastest cycle.

        The snapshot carried delay 0, which Steam writes and which means "as
        fast as possible": render._cycle then returns MIN_CYCLE_SECONDS
        whatever SPEED says. The ooze ran its fourteen seconds in under one.
        """
        snapshot = pegboard.build_snapshot(dict(pegboard.DEFAULTS))
        self.assertEqual(snapshot.delay, render.DELAY_DEFAULT)
        at_one = render._cycle(snapshot, render.OOZE_CYCLE, 1.0)
        self.assertAlmostEqual(at_one, render.OOZE_CYCLE)
        # And the slider divides it.
        self.assertAlmostEqual(
            render._cycle(snapshot, render.OOZE_CYCLE, 2.0), at_one / 2)
        self.assertGreater(
            render._cycle(snapshot, render.OOZE_CYCLE, 0.5), at_one)

    def test_an_effect_that_does_not_exist_is_refused(self):
        with self.assertRaises(pegboard.PegboardError):
            pegboard.read(self._write("EFFECT=disco\n"))

    def test_a_rate_the_board_cannot_draw_is_refused(self):
        """60 flashed single LEDs on a board. 30 was clean."""
        with self.assertRaises(pegboard.PegboardError):
            pegboard.read(self._write("FPS=60\n"))
        self.assertEqual(pegboard.DEFAULTS["FPS"], pegboard.MAX_FPS)

    def test_the_idle_rate_cannot_exceed_the_active_one(self):
        with self.assertRaises(pegboard.PegboardError):
            pegboard.read(self._write("FPS=10\nIDLE_FPS=20\n"))

    def test_what_it_writes_it_can_read_again(self):
        values = dict(pegboard.DEFAULTS, EFFECT="ooze", ENABLED=False)
        again = pegboard.read(self._write(pegboard.text(values)))
        self.assertEqual(again, values)


class DrawingTest(unittest.TestCase):
    """The loop, against a board that is a list."""

    class Fake:
        node = "/dev/fake"

        answering = True

        def __init__(self):
            self.sent = []
            self.settles = []
            self.frames = 0

        def show(self, text, settle=0.0):
            self.sent.append(text)
            self.settles.append(settle)
            self.frames += 1
            return ([(pegboard.TYPE_COLOUR, b"\x00")] if self.answering
                    else [])

        def drain(self):
            return []

        def blank(self):
            self.sent.append("blank")

        def close(self):
            pass

    def _run(self, values, turns=3):
        board = self.Fake()
        ticks = iter([n * 0.01 for n in range(turns * 8)])
        seen = []

        def stop():
            seen.append(1)
            return len(seen) > turns

        pegboard.run(values, board=board, stop=stop, now=lambda: next(ticks))
        return board

    def test_every_effect_fills_the_whole_board_and_no_more(self):
        """The wave is drawn on 32 and folded. The fold once put 128 LEDs on
        the wire, because the count came from the effect the renderer draws
        and not from the one the board was asked for."""
        for name in pegboard.EFFECTS:
            board = self._run(dict(pegboard.DEFAULTS, EFFECT=name))
            self.assertEqual(len(board.sent[0]) - 3, 3 * 64, name)

    def test_it_sends_a_dark_frame_when_it_stops(self):
        """The board holds the last frame. A service that stops without this
        leaves it lit and nothing on the machine can turn it off."""
        board = self._run(dict(pegboard.DEFAULTS))
        self.assertEqual(board.sent[-1], "blank")

    def test_the_wave_really_is_symmetrical_on_the_wire(self):
        board = self._run(dict(pegboard.DEFAULTS,
                               EFFECT=pegboard.SHOWS_RAINBOW_WAVE))
        wire = triples(board.sent[0][3:])
        self.assertEqual(wire[0], wire[-1])
        self.assertEqual(wire[31], wire[32])

    def test_the_board_asks_for_a_picture_as_fine_as_it_is_long(self):
        """The effects have a fixed number of features over the strip.

        This board got the same three blobs as a bar of seventeen, each one
        four times as wide, which is what a person reads as one flat colour.
        See render.Renderer.detail.
        """
        values = dict(pegboard.DEFAULTS, EFFECT="fire")
        renderer = pegboard.build_renderer(values)
        self.assertAlmostEqual(renderer.detail,
                               pegboard.LEDS / float(shim.LOGICAL_LEDS),
                               places=6)
        self.assertEqual(renderer.logical_count, pegboard.LEDS)

    def test_a_folded_effect_asks_for_the_half_it_draws(self):
        """The wave is drawn on 32 LEDs, and fold() puts the other 32 on."""
        values = dict(pegboard.DEFAULTS, EFFECT=pegboard.SHOWS_RAINBOW_WAVE)
        renderer = pegboard.build_renderer(values)
        self.assertAlmostEqual(
            renderer.detail,
            pegboard.LEDS / 2.0 / float(shim.LOGICAL_LEDS), places=6)

    def test_the_shaped_effects_have_more_to_look_at_than_the_bar(self):
        """Measured on the wire, and not on the renderer on its own."""
        def hills(effect):
            board = self._run(dict(pegboard.DEFAULTS, EFFECT=effect,
                                   BRIGHTNESS=255))
            wire = triples(board.sent[0][3:])
            levels = [max(pixel) for pixel in wire]
            steps = [b - a for a, b in zip(levels, levels[1:])]
            return sum(1 for a, b in zip(steps, steps[1:]) if a * b < 0)
        for effect in ("fire", "aurora", "ooze"):
            self.assertGreater(hills(effect), 6, effect)

    def test_the_patrol_puts_one_lit_led_on_the_wire(self):
        """The service loop, and not patrol_pixels on its own.

        The loop picks the drawing of this module for the effects in
        DRAWN_HERE and the renderer for the rest. A patrol that goes through
        the renderer is a dot 20 LEDs wide.
        """
        board = self._run(dict(pegboard.DEFAULTS,
                               EFFECT=pegboard.SHOWS_PATROL,
                               COLOR="#ff6e00", BRIGHTNESS=255))
        wire = triples(board.sent[0][3:])
        self.assertEqual(len(wire), pegboard.LEDS)
        self.assertEqual(sum(1 for pixel in wire if any(pixel)), 1)

    def test_the_patrol_lights_one_led_and_no_more(self):
        """One dot, and one LED wide.

        The renderer draws 17 logical LEDs and stretches them to the strip,
        which made this dot 20 LEDs wide. At the middle of the chain that
        blur lit the top of both sides at one time, and a board reads that as
        two dots. See pegboard.patrol_pixels.
        """
        values = dict(pegboard.DEFAULTS, EFFECT=pegboard.SHOWS_PATROL,
                      COLOR="#ff6e00", BRIGHTNESS=255)
        for elapsed in (0.0, 0.37, 0.8, 1.19, 1.6, 2.41, 3.0):
            pixels = pegboard.patrol_pixels(values, elapsed)
            lit = [index for index, pixel in enumerate(pixels) if any(pixel)]
            self.assertEqual(len(lit), 1, "%s at %.2f" % (lit, elapsed))

    def test_the_dot_walks_the_whole_chain_and_comes_back(self):
        """Every LED, end to end, and no jump at the turn."""
        values = dict(pegboard.DEFAULTS, EFFECT=pegboard.SHOWS_PATROL,
                      COLOR="#ff6e00", BRIGHTNESS=255)
        period = pegboard.patrol_period(values)
        steps = 400
        walk = []
        for step in range(steps + 1):
            pixels = pegboard.patrol_pixels(values, period * step / steps)
            walk.append(next(index for index, pixel in enumerate(pixels)
                             if any(pixel)))
        self.assertEqual(min(walk), 0)
        self.assertEqual(max(walk), pegboard.LEDS - 1)
        self.assertEqual(set(walk), set(range(pegboard.LEDS)))
        # One run out and one run back, and never two LEDs at a time.
        self.assertLessEqual(max(abs(b - a) for a, b in zip(walk, walk[1:])),
                             1)
        self.assertEqual(walk[0], 0)
        self.assertEqual(walk[-1], 0)

    def test_the_dot_moves_one_led_for_each_frame_at_the_default_speed(self):
        """The fastest a single dot moves and still lights every LED.

        Above that rate it steps over LEDs, which is what SPEED is for.
        """
        values = dict(pegboard.DEFAULTS, EFFECT=pegboard.SHOWS_PATROL)
        one_way = pegboard.patrol_period(values) / 2.0
        self.assertAlmostEqual(one_way * values["FPS"], pegboard.LEDS,
                               places=6)
        self.assertAlmostEqual(
            pegboard.patrol_period(dict(values, SPEED=2.0)),
            pegboard.patrol_period(values) / 2.0, places=6)

    def test_the_patrol_draws_in_the_colour_it_was_given(self):
        """The other effects make their own, and COLOR does nothing there."""
        board = self._run(dict(pegboard.DEFAULTS,
                               EFFECT=pegboard.SHOWS_PATROL,
                               COLOR="#0000ff", BRIGHTNESS=255))
        wire = triples(board.sent[0][3:])
        # GRB on the wire, so blue is the third byte and the first two are 0.
        brightest = max(wire, key=max)
        self.assertEqual(brightest[0], 0)
        self.assertEqual(brightest[1], 0)
        self.assertGreater(brightest[2], 128)

    def test_the_plain_rainbow_is_not(self):
        """Which is the whole difference between the two entries."""
        board = self._run(dict(pegboard.DEFAULTS, EFFECT="rainbow"))
        wire = triples(board.sent[0][3:])
        self.assertNotEqual(wire[0], wire[-1])

    def test_the_wait_for_an_answer_cannot_eat_a_frame(self):
        """It was a share of the frame, and at 60 that share was 13 of 16 ms.

        One slow answer then took the whole budget, the sleep after it was
        skipped, and the next frame went out with no gap: eight reports where
        the board expected four. That is what made single LEDs flash.
        """
        board = self.Fake()
        ticks = iter([n * 0.01 for n in range(40)])
        seen = []
        pegboard.run(dict(pegboard.DEFAULTS), board=board,
                     now=lambda: next(ticks),
                     stop=lambda: (seen.append(1), len(seen) > 2)[1])
        self.assertTrue(board.settles)
        for settle in board.settles:
            self.assertGreater(settle, 0)
            self.assertLess(settle, 1.0 / pegboard.MAX_FPS / 2)

    def test_a_frame_that_ran_over_still_leaves_a_gap(self):
        """The clock here jumps a whole frame at each reading, so every frame
        is late. The board must still get its gap."""
        board = self.Fake()
        slept = []
        real = pegboard.time.sleep
        pegboard.time.sleep = slept.append
        self.addCleanup(setattr, pegboard.time, "sleep", real)
        late = iter([n * 1.0 for n in range(40)])
        seen = []
        pegboard.run(dict(pegboard.DEFAULTS), board=board,
                     now=lambda: next(late),
                     stop=lambda: (seen.append(1), len(seen) > 2)[1])
        self.assertTrue(slept)
        for rest in slept:
            self.assertGreaterEqual(rest, pegboard.MIN_GAP_SECONDS)

    def test_a_board_that_answers_nothing_still_draws(self):
        """A quiet board is not a reason to stop lighting it."""
        board = self.Fake()
        board.answering = False
        ticks = iter([n * 0.01 for n in range(40)])
        seen = []
        pegboard.run(dict(pegboard.DEFAULTS), board=board,
                     now=lambda: next(ticks),
                     stop=lambda: (seen.append(1), len(seen) > 3)[1])
        self.assertGreaterEqual(board.frames, 3)

    def test_a_board_that_is_switched_off_is_drawn_dark(self):
        """ENABLED=0 is a person who wants the board off, not a fault.

        The switch reaches the renderer through the snapshot, which is where
        every effect of this project reads it. So it is one value and not a
        branch of its own, and an effect cannot forget to honour it.
        """
        board = self._run(dict(pegboard.DEFAULTS, ENABLED=False,
                               EFFECT="ooze", BRIGHTNESS=255))
        self.assertEqual(set(board.sent[0][3:]), {0})

    def test_a_board_that_is_on_is_not(self):
        board = self._run(dict(pegboard.DEFAULTS, ENABLED=True,
                               EFFECT="ooze", BRIGHTNESS=255))
        self.assertNotEqual(set(board.sent[0][3:]), {0})


class ModuleTest(unittest.TestCase):
    """The board is a module of its own, and nothing of the bar's."""

    def test_it_is_in_the_registry(self):
        self.assertIn(modules.PEGBOARD, modules.ORDER)
        self.assertIn(modules.PEGBOARD, modules.SAYS)
        self.assertIn(modules.PEGBOARD, modules.MARK)

    def test_it_is_installed_when_its_own_applier_is_there(self):
        """And not when the LED bar's is. See modules.installed."""
        here = modules.MARK[modules.PEGBOARD]
        self.assertTrue(modules.installed(modules.PEGBOARD,
                                          present=lambda p: p == here))
        led = modules.MARK[modules.LED]
        self.assertFalse(modules.installed(modules.PEGBOARD,
                                           present=lambda p: p == led))

    def test_the_bar_does_not_need_it_and_it_does_not_need_the_bar(self):
        here = modules.MARK[modules.PEGBOARD]
        self.assertFalse(modules.installed(modules.LED,
                                           present=lambda p: p == here))

    def test_its_rule_names_its_own_staged_file_and_no_wildcard(self):
        lines = [line for line
                 in ctl.sudoers_text("deck", present=lambda p: True).splitlines()
                 if line.startswith("deck") and "pegboard" in line]
        self.assertEqual(len(lines), 1)
        self.assertNotIn("*", lines[0])
        self.assertTrue(lines[0].endswith(ctl.STAGED["pegboard"]))

    def test_a_machine_without_it_gets_no_rule_for_it(self):
        text = ctl.sudoers_text("deck", present=lambda p: False)
        self.assertNotIn("pegboard", text)

    def test_a_steamos_update_keeps_its_unit_and_its_settings(self):
        for path in ("/etc/steamos-utility-center-pegboard.conf",
                     "/etc/systemd/system/"
                     "steamos-utility-center-pegboard.service"):
            self.assertIn(path, mounts.PROJECT_FILES)


class SleepTest(unittest.TestCase):
    """What takes the board dark while the machine sleeps.

    A shutdown always worked: systemd stops the unit and the service sends a
    dark frame as it goes. A suspend only freezes the process, so no frame
    follows and the board holds the last one it was given.
    """

    HOOK = os.path.join(REPO, "scripts", "sleep-pegboard.sh")

    def setUp(self):
        with open(self.HOOK) as handle:
            self.text = handle.read()

    def test_it_is_a_program_that_systemd_can_run(self):
        self.assertTrue(os.access(self.HOOK, os.X_OK))
        self.assertTrue(self.text.startswith("#!"))

    def test_it_parses(self):
        done = subprocess.run(["sh", "-n", self.HOOK],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_it_stops_the_service_before_the_machine_sleeps(self):
        """And systemd waits for that, which is what puts the frame out."""
        before = self.text.split("pre)")[1].split(";;")[0]
        self.assertIn("systemctl stop", before)

    def test_it_starts_the_service_again_after_a_wake(self):
        after = self.text.split("post)")[1].split(";;")[0]
        self.assertIn("systemctl start", after)

    def test_it_starts_nothing_that_a_person_switched_off(self):
        """A resume is not the moment to decide that a disabled unit runs."""
        after = self.text.split("post)")[1].split(";;")[0]
        self.assertIn("is-enabled", after)

    def test_it_does_not_write_to_the_board_itself(self):
        """The service holds the device open, and one frame is four reports.

        A second writer puts its bytes between them: the board loses its
        place in the stream and draws the wrong colours. That is the fault
        this project already met at 60 frames a second.

        The comments are cut out first. They name the device to say why this
        does not touch it, and a test that read them would refuse the
        explanation along with the thing it explains.
        """
        code = "\n".join(line for line in self.text.splitlines()
                         if not line.lstrip().startswith("#"))
        # The board's device and not every device: /dev/null is where the
        # output of each systemctl goes, and that is not the board.
        for named in ("hidraw", "37fa", "/dev/hid"):
            self.assertNotIn(named, code, named)

    def test_a_machine_without_the_module_is_not_an_error(self):
        self.assertIn("list-unit-files", self.text)
        self.assertIn("exit 0", self.text)


class SleepUnitTest(unittest.TestCase):
    """The two units that call that helper, and why they are units.

    The helper was a program in /usr/lib/systemd/system-sleep, which systemd
    runs with "pre" before a sleep and "post" after a wake. That worked, and
    a SteamOS update rebuilds /usr and took the file away each time, so the
    board stayed lit at the first suspend after an update. The keep-list
    carries /etc, so the same two moments are asked for with two units there.
    See server/steamos_utility_center/mounts.py.
    """

    SLEEP = os.path.join(REPO, "server",
                         "steamos-utility-center-pegboard-sleep.service")
    RESUME = os.path.join(REPO, "server",
                          "steamos-utility-center-pegboard-resume.service")
    HELPER = "@INSTALL_DIR@/steamos-utility-center-pegboard-sleep"

    def setUp(self):
        with open(self.SLEEP) as handle:
            self.sleep = handle.read()
        with open(self.RESUME) as handle:
            self.resume = handle.read()

    def test_the_board_goes_dark_before_the_machine_sleeps(self):
        """Before=sleep.target, and systemd waits for a oneshot unit.

        That wait is what puts the dark frame on the wire. After sleep.target
        the service is frozen, and the board holds the last picture it drew.
        """
        self.assertIn("Before=sleep.target", self.sleep)
        self.assertIn("Type=oneshot", self.sleep)
        self.assertIn("ExecStart=%s pre" % self.HELPER, self.sleep)

    def test_one_link_covers_every_kind_of_sleep(self):
        """suspend, hibernate and hybrid-sleep each pull in sleep.target."""
        self.assertIn("WantedBy=sleep.target", self.sleep)

    def test_the_suspend_is_not_held_for_the_default_time(self):
        """A oneshot with no limit of its own gets a minute and a half.

        The service gets ten seconds to send its dark frame and stop, and
        this is that with room for the systemctl around it.
        """
        self.assertIn("TimeoutStartSec=", self.sleep)

    def test_the_board_is_lit_again_after_the_wake(self):
        """suspend.target is reached after the sleeping is over.

        sleep.target is reached on the way down, so the resume side cannot
        use it.
        """
        self.assertIn("After=suspend.target", self.resume)
        self.assertIn("WantedBy=suspend.target", self.resume)
        self.assertIn("ExecStart=%s post" % self.HELPER, self.resume)

    def test_neither_unit_writes_to_the_board(self):
        """The service holds the device open. See the helper for why.

        The comments are cut out first, the way the helper's own test does.
        """
        for name, text in (("sleep", self.sleep), ("resume", self.resume)):
            code = "\n".join(line for line in text.splitlines()
                              if not line.lstrip().startswith("#"))
            for named in ("hidraw", "37fa"):
                self.assertNotIn(named, code, "%s: %s" % (name, named))


class InstallerTest(unittest.TestCase):
    """What install.sh and uninstall.sh do with it."""

    def setUp(self):
        with open(os.path.join(REPO, "install.sh")) as handle:
            self.install = handle.read()
        with open(os.path.join(REPO, "uninstall.sh")) as handle:
            self.uninstall = handle.read()

    def test_the_module_installs_the_suspend_helper_and_its_units(self):
        block = self.install.split("install_pegboard()")[1].split(
            "\nremove_pegboard")[0]
        self.assertIn("scripts/sleep-pegboard.sh", block)
        for wanted in ("PEGBOARD_SLEEP_HELPER_PATH",
                       "PEGBOARD_SLEEP_UNIT_PATH",
                       "PEGBOARD_RESUME_UNIT_PATH"):
            self.assertIn(wanted, block, wanted)

    def test_the_units_are_switched_on(self):
        """A unit with no link in sleep.target.wants never runs."""
        block = self.install.split("install_pegboard()")[1].split(
            "\nremove_pegboard")[0]
        self.assertIn("enable", block.split("PEGBOARD_RESUME_UNIT_PATH")[1])

    def test_removing_the_module_takes_the_units_away(self):
        """A link to a unit that is gone is a message at every suspend."""
        block = self.install.split("remove_pegboard()")[1].split("\n# --")[0]
        disabled = block.index("-pegboard-sleep.service")
        deleted = block.index("PEGBOARD_SLEEP_UNIT_PATH")
        self.assertLess(disabled, deleted)
        for wanted in ("PEGBOARD_SLEEP_HELPER_PATH",
                       "PEGBOARD_SLEEP_UNIT_PATH",
                       "PEGBOARD_RESUME_UNIT_PATH"):
            self.assertIn(wanted, block, wanted)
            self.assertIn(wanted, self.uninstall, wanted)

    def test_an_older_install_loses_its_copy_under_usr(self):
        """Or systemd runs the program there and the units as well.

        Each suspend then does the work two times. That is the fault this
        project already met in the CEC toolkit. See LEGACY_SLEEP_HOOKS in
        scripts/user-unit.sh.
        """
        block = self.install.split("install_pegboard()")[1].split(
            "\nremove_pegboard")[0]
        self.assertIn("remove_legacy_sleep_hooks", block)

    def test_the_module_installs_its_service_and_its_settings(self):
        block = self.install.split("install_pegboard()")[1].split(
            "\nremove_pegboard")[0]
        for wanted in ("apply-pegboard.sh", "PEGBOARD_UNIT_PATH",
                       "PEGBOARD_CONFIG_PATH", "PEGBOARD_APPLIER_PATH"):
            self.assertIn(wanted, block)

    def test_a_second_install_keeps_the_settings(self):
        block = self.install.split("install_pegboard()")[1].split(
            "\nremove_pegboard")[0]
        self.assertIn("Keeping existing", block)

    def test_removing_it_stops_the_service_before_the_files_go(self):
        """The board holds the last frame. The service sends a dark one when
        it stops, so it has to stop while it still has its files."""
        block = self.install.split("remove_pegboard()")[1].split("\n# --")[0]
        stopped = block.index("disable --now")
        deleted = block.index('rm -f "$PEGBOARD_UNIT_PATH"')
        self.assertLess(stopped, deleted)

    def test_the_uninstaller_does_the_same(self):
        stopped = self.uninstall.index(
            'systemctl disable --now "$NAME-pegboard.service"')
        deleted = self.uninstall.index('rm -f "$PEGBOARD_UNIT_PATH"')
        self.assertLess(stopped, deleted)

    def test_purge_takes_its_settings_and_a_plain_uninstall_does_not(self):
        self.assertIn('"$PEGBOARD_CONFIG_PATH"',
                      self.uninstall.split("if [[ $PURGE -eq 1 ]]")[1])


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
