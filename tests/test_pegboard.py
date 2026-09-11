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


def triples(payload):
    return [tuple(payload[at:at + 3]) for at in range(0, len(payload), 3)]


class FramingTest(unittest.TestCase):
    """What goes on the wire."""

    def test_a_message_carries_its_length_big_endian(self):
        said = pegboard.message(pegboard.TYPE_COLOUR, bytes(192))
        self.assertEqual(said[:3].hex(), "0200c0")

    def test_a_frame_of_64_leds_needs_four_reports(self):
        """195 bytes into reports of 64. The last one is mostly padding."""
        said = pegboard.frame(bytes(3 * 32), pegboard.SHAPE_MIRROR)
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


class ShapeTest(unittest.TestCase):
    """The fold, which is the whole reason SHAPE exists."""

    DRAWN = bytes([1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4])   # bottom to top

    def test_the_mirror_draws_half_the_leds(self):
        self.assertEqual(pegboard.logical_leds(pegboard.SHAPE_MIRROR), 32)

    def test_the_chain_draws_all_of_them(self):
        self.assertEqual(pegboard.logical_leds(pegboard.SHAPE_CHAIN), 64)

    def test_the_mirror_puts_the_bottom_in_both_bottom_corners(self):
        """LED 0 is the bottom left and LED 63 the bottom right."""
        said = triples(pegboard.fold(self.DRAWN, pegboard.SHAPE_MIRROR))
        self.assertEqual(said[0], (1, 1, 1))
        self.assertEqual(said[-1], (1, 1, 1))

    def test_the_mirror_puts_the_top_in_both_top_corners(self):
        """The two middle LEDs of the chain are the top of the board."""
        said = triples(pegboard.fold(self.DRAWN, pegboard.SHAPE_MIRROR))
        self.assertEqual(said[3], (4, 4, 4))
        self.assertEqual(said[4], (4, 4, 4))

    def test_the_mirror_is_the_same_length_as_the_board(self):
        said = pegboard.fold(bytes(3 * 32), pegboard.SHAPE_MIRROR)
        self.assertEqual(len(said), 3 * 64)

    def test_the_chain_changes_nothing(self):
        self.assertEqual(pegboard.fold(self.DRAWN, pegboard.SHAPE_CHAIN),
                         self.DRAWN)



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

    def test_a_shape_it_cannot_draw_is_refused(self):
        with self.assertRaises(pegboard.PegboardError):
            pegboard.read(self._write("SHAPE=diagonal\n"))

    def test_the_count_of_leds_is_not_a_setting(self):
        """One board is 64. A different count is a different board, with a
        layout of its own and not only a number of its own."""
        self.assertEqual(pegboard.LEDS, 64)
        self.assertNotIn("LEDS", pegboard.DEFAULTS)
        with self.assertRaises(pegboard.PegboardError):
            pegboard.read(self._write("LEDS=32\n"))

    def test_the_effects_are_the_ones_the_renderer_has(self):
        """Derived and not written down, so a new effect reaches the board."""
        for name in render.RAINBOW_CHOICES:
            values = dict(pegboard.DEFAULTS, EFFECT=name)
            self.assertEqual(pegboard.validate(values)["EFFECT"], name)

    def test_an_effect_that_does_not_exist_is_refused(self):
        with self.assertRaises(pegboard.PegboardError):
            pegboard.read(self._write("EFFECT=disco\n"))

    def test_the_idle_rate_cannot_exceed_the_active_one(self):
        with self.assertRaises(pegboard.PegboardError):
            pegboard.read(self._write("FPS=10\nIDLE_FPS=20\n"))

    def test_what_it_writes_it_can_read_again(self):
        values = dict(pegboard.DEFAULTS, SHAPE=pegboard.SHAPE_CHAIN,
                      EFFECT="ooze", ENABLED=False)
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

    def test_each_shape_fills_the_whole_board(self):
        for shape in pegboard.SHAPES:
            board = self._run(dict(pegboard.DEFAULTS, SHAPE=shape,
                                   EFFECT="ooze"))
            self.assertEqual(len(board.sent[0]) - 3, 3 * 64, shape)

    def test_it_sends_a_dark_frame_when_it_stops(self):
        """The board holds the last frame. A service that stops without this
        leaves it lit and nothing on the machine can turn it off."""
        board = self._run(dict(pegboard.DEFAULTS))
        self.assertEqual(board.sent[-1], "blank")

    def test_the_mirror_really_is_symmetrical_on_the_wire(self):
        board = self._run(dict(pegboard.DEFAULTS, SHAPE=pegboard.SHAPE_MIRROR,
                               EFFECT="fire"))
        wire = triples(board.sent[0][3:])
        self.assertEqual(wire[0], wire[-1])
        self.assertEqual(wire[31], wire[32])

    def test_it_waits_for_the_board_between_frames(self):
        """The wait is what paces this, and it is why the LEDs stopped
        flashing at nothing: four reports a frame, sent with no pause, made
        the board lose its place in the stream."""
        board = self.Fake()
        ticks = iter([n * 0.01 for n in range(40)])
        seen = []
        pegboard.run(dict(pegboard.DEFAULTS, FPS=60),
                     board=board, now=lambda: next(ticks),
                     stop=lambda: (seen.append(1), len(seen) > 2)[1])
        self.assertTrue(board.settles)
        for settle in board.settles:
            self.assertGreater(settle, 0)
            # Under one frame, so a board that says nothing still draws at
            # the rate that was asked for.
            self.assertLess(settle, 1.0 / 60)

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


class InstallerTest(unittest.TestCase):
    """What install.sh and uninstall.sh do with it."""

    def setUp(self):
        with open(os.path.join(REPO, "install.sh")) as handle:
            self.install = handle.read()
        with open(os.path.join(REPO, "uninstall.sh")) as handle:
            self.uninstall = handle.read()

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
