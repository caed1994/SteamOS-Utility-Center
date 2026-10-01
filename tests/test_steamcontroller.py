# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The battery of the Steam Controller of 2026, from its hidraw node.

The tree of each test is the one the board showed: the puck on hid-steam,
five hidraw nodes on the interfaces 2 to 6, and the controller on the first
one. The reports are sockets that keep each write as one message, which is
what a hidraw node does with a report.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import companion, steamcontroller  # noqa: E402

# The battery report the board sent, at 95 percent and off its charger.
BOARD = bytes.fromhex("43015f08101810780000000000ac5d")
# An input report: 54 bytes under ID 0x42, 265 of them each second.
INPUT = bytes([0x42]) + bytes(53)


def battery(level, state):
    return bytes([0x43, state, level]) + BOARD[3:]


class ParseTest(unittest.TestCase):
    def test_the_report_of_the_board(self):
        self.assertEqual(steamcontroller.parse(BOARD),
                         {"name": "Steam Controller", "percent": 95,
                          "status": "Discharging"})

    def test_the_charge_states_are_the_words_of_the_kernel(self):
        """hid-steam maps 2 to charging and 4 to full, and the panel
        reads the word "Charging" for its symbol."""
        for state, word in ((1, "Discharging"), (2, "Charging"),
                            (4, "Full"), (0, "Unknown"), (3, "Unknown")):
            self.assertEqual(steamcontroller.parse(battery(50, state))
                             ["status"], word)

    def test_a_report_that_is_not_the_battery_is_none(self):
        self.assertIsNone(steamcontroller.parse(INPUT))
        self.assertIsNone(steamcontroller.parse(BOARD[:14]))
        self.assertIsNone(steamcontroller.parse(BOARD + b"\0"))
        self.assertIsNone(steamcontroller.parse(b""))

    def test_a_charge_over_a_hundred_is_no_battery(self):
        """The firmware invents no battery, so neither does this."""
        self.assertIsNone(steamcontroller.parse(battery(101, 1)))
        self.assertEqual(steamcontroller.parse(battery(100, 4))["percent"],
                         100)


class NodesTest(unittest.TestCase):
    """The places under /sys that tell one node from another."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.hidraw = os.path.join(self.root, "class", "hidraw")
        self.power = os.path.join(self.root, "class", "power_supply")
        os.makedirs(self.hidraw)
        os.makedirs(self.power)

    def device(self, place, name, hid_id, interface=None):
        """A HID device under a USB interface, as the kernel lays it out."""
        where = os.path.join(self.root, "devices", place)
        os.makedirs(os.path.join(where, name), exist_ok=True)
        if interface is not None:
            with open(os.path.join(where, "bInterfaceNumber"), "w") as handle:
                handle.write("%02x\n" % interface)
        with open(os.path.join(where, name, "uevent"), "w") as handle:
            handle.write("DRIVER=hid-steam\nHID_ID=%s\nHID_NAME=x\n" % hid_id)
        return os.path.join(where, name)

    def node(self, number, place, hid_id, interface=None):
        device = self.device(place, "0003:28DE:1304.%04X" % number, hid_id,
                             interface)
        os.makedirs(os.path.join(self.hidraw, "hidraw%d" % number))
        os.symlink(device, os.path.join(self.hidraw, "hidraw%d" % number,
                                        "device"))

    def puck(self):
        for interface in range(2, 7):
            self.node(16 + interface, "usb1/1-1/1-1:1.%d" % interface,
                      "0003:000028DE:00001304", interface)

    def found(self):
        return steamcontroller.nodes(self.hidraw, self.power, "/dev")

    def test_the_puck_gives_its_four_slots_and_not_its_pogo_pins(self):
        self.puck()
        self.assertEqual(self.found(), ["/dev/hidraw18", "/dev/hidraw19",
                                        "/dev/hidraw20", "/dev/hidraw21"])

    def test_other_devices_are_left_alone(self):
        """A DualShock and a Steam Controller of 2015 have batteries of
        their own, in other reports. The kernel reads those."""
        self.node(3, "bt/0005:054C:09CC.0003", "0005:0000054C:000009CC")
        self.node(4, "usb2/2-1/2-1:1.1", "0003:000028DE:00001142", 1)
        self.assertEqual(self.found(), [])

    def test_the_wired_one_has_one_node_whatever_its_interface(self):
        self.node(5, "usb3/3-1/3-1:1.0", "0003:000028DE:00001302", 0)
        self.assertEqual(self.found(), ["/dev/hidraw5"])

    def test_a_controller_the_kernel_reports_stays_closed(self):
        """A power supply means that nobody holds the node open, and a
        first reader takes the gamepad of hid-steam away. See nodes."""
        self.puck()
        physical = self.device("usb1/1-1/1-1:1.2", "0003:28DE:1304.0014",
                               "0003:000028DE:00001304")
        os.makedirs(os.path.join(self.power, "steam-ABC"))
        os.symlink(physical, os.path.join(self.power, "steam-ABC", "device"))
        self.assertEqual(self.found(), ["/dev/hidraw19", "/dev/hidraw20",
                                        "/dev/hidraw21"])

    def test_a_machine_with_no_hidraw_is_no_nodes_and_no_error(self):
        self.assertEqual(steamcontroller.nodes("/no/such", "/no/such"), [])


class LookTest(unittest.TestCase):
    """One look, with sockets in place of the nodes."""

    def setUp(self):
        self.ends = {}

    def socket(self, path, *reports):
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.addCleanup(ours.close)
        for report in reports:
            ours.send(report)
        self.ends[path] = theirs
        return ours

    def opener(self, path):
        if path not in self.ends:
            raise PermissionError(path)
        return self.ends.pop(path).detach()

    def look(self, paths, window=2.0, settle=0.05):
        return steamcontroller.look(paths, window, settle, self.opener)

    def test_it_ends_at_the_battery_and_does_not_wait_out_the_window(self):
        self.socket("/dev/hidraw18", INPUT, INPUT, BOARD, INPUT)
        self.socket("/dev/hidraw19")
        began = time.monotonic()
        found, alive = self.look(["/dev/hidraw18", "/dev/hidraw19"])
        self.assertLess(time.monotonic() - began, 1.0)
        self.assertEqual(found, {"/dev/hidraw18":
                                 steamcontroller.parse(BOARD)})
        self.assertEqual(alive, {"/dev/hidraw18"})

    def test_the_last_battery_of_a_look_wins(self):
        self.socket("/dev/hidraw18", battery(95, 1), battery(94, 2))
        found, _ = self.look(["/dev/hidraw18"])
        self.assertEqual(found["/dev/hidraw18"]["percent"], 94)
        self.assertEqual(found["/dev/hidraw18"]["status"], "Charging")

    def test_input_with_no_battery_waits_for_the_whole_window(self):
        self.socket("/dev/hidraw18", INPUT)
        began = time.monotonic()
        found, alive = self.look(["/dev/hidraw18"], window=0.3)
        self.assertGreaterEqual(time.monotonic() - began, 0.3)
        self.assertEqual((found, alive), ({}, {"/dev/hidraw18"}))

    def test_a_node_this_user_cannot_open_is_left_out(self):
        self.socket("/dev/hidraw18", BOARD)
        found, _ = self.look(["/dev/hidraw17", "/dev/hidraw18"])
        self.assertEqual(list(found), ["/dev/hidraw18"])

    def test_a_node_that_goes_away_ends_its_part_of_the_look(self):
        """An empty read on a socket is a closed peer. On hidraw a node
        that goes away answers with an error, and both close the node."""
        ours = self.socket("/dev/hidraw18", INPUT)
        ours.close()
        began = time.monotonic()
        found, alive = self.look(["/dev/hidraw18"], window=2.0)
        self.assertLess(time.monotonic() - began, 1.0)
        self.assertEqual(found, {})
        self.assertEqual(alive, {"/dev/hidraw18"})

    def test_every_node_is_closed_after_the_look(self):
        self.socket("/dev/hidraw18", BOARD)
        self.socket("/dev/hidraw19")
        opened = []

        def opener(path):
            fd = self.opener(path)
            opened.append(fd)
            return fd

        steamcontroller.look(["/dev/hidraw18", "/dev/hidraw19"], 2.0, 0.05,
                             opener)
        for fd in opened:
            with self.assertRaises(OSError):
                os.fstat(fd)


class BatteriesTest(unittest.TestCase):
    """The cache between the panel and the looks."""

    def setUp(self):
        self.now = 1000.0
        self.looks = []
        self.answer = ({}, set())

    def peek(self, paths):
        self.looks.append(paths)
        return self.answer

    def batteries(self, spawn=None):
        return steamcontroller.Batteries(
            every=30.0, find=lambda: ["/dev/hidraw18"], peek=self.peek,
            spawn=spawn or (lambda work: work()), clock=lambda: self.now)

    def test_an_answer_carries_the_look_before_it(self):
        later = []
        cache = self.batteries(spawn=later.append)
        self.answer = ({"/dev/hidraw18": steamcontroller.parse(BOARD)},
                       {"/dev/hidraw18"})
        self.assertEqual(cache.current(), [])
        later.pop()()
        self.assertEqual(cache.current(), [steamcontroller.parse(BOARD)])

    def test_one_look_each_thirty_seconds_however_often_the_panel_asks(self):
        cache = self.batteries()
        for _ in range(10):
            cache.current()
            self.now += 3.0
        self.assertEqual(len(self.looks), 1)
        cache.current()
        self.assertEqual(len(self.looks), 2)

    def test_no_second_look_while_one_runs(self):
        later = []
        cache = self.batteries(spawn=later.append)
        cache.current()
        self.now += 60.0
        cache.current()
        self.assertEqual(len(later), 1)
        later.pop()()
        cache.current()
        self.assertEqual(len(later), 1)

    def test_a_look_that_missed_the_battery_keeps_the_last_one(self):
        """The report comes about every 3.5 seconds, and a look can end
        between two. Input in the look means the controller is still on."""
        cache = self.batteries()
        self.answer = ({"/dev/hidraw18": steamcontroller.parse(BOARD)},
                       {"/dev/hidraw18"})
        cache.refresh()
        self.answer = ({}, {"/dev/hidraw18"})
        cache.refresh()
        self.assertEqual(cache.current(), [steamcontroller.parse(BOARD)])

    def test_a_controller_that_sent_nothing_goes_at_once(self):
        cache = self.batteries()
        self.answer = ({"/dev/hidraw18": steamcontroller.parse(BOARD)},
                       {"/dev/hidraw18"})
        cache.refresh()
        self.answer = ({}, set())
        cache.refresh()
        self.assertEqual(cache.current(), [])

    def test_a_look_that_fails_does_not_stop_the_next_one(self):
        cache = self.batteries()

        def broken(paths):
            raise RuntimeError("the look broke")

        cache._peek = broken
        with self.assertRaises(RuntimeError):
            cache.current()
        cache._peek = self.peek
        self.now += 30.0
        cache.current()
        self.assertEqual(len(self.looks), 1)


class StatusTest(unittest.TestCase):
    def test_the_steam_controller_comes_first(self):
        """The panel shows the first controller of the list."""
        kernel = [{"name": "PlayStation Controller", "percent": 60,
                   "status": "Discharging"}]
        with mock.patch.object(steamcontroller, "batteries",
                               return_value=[steamcontroller.parse(BOARD)]), \
                mock.patch.object(companion, "controllers",
                                  return_value=kernel):
            answer = companion.status()
        self.assertEqual(answer["controllers"],
                         [steamcontroller.parse(BOARD)] + kernel)


class OnlyReadsTest(unittest.TestCase):
    """The docstring promises that nothing goes to the controller."""

    def test_it_opens_for_reading_and_writes_nothing(self):
        path = os.path.join(REPO, "server", "steamos_utility_center",
                            "steamcontroller.py")
        with open(path) as handle:
            source = handle.read()
        for word in ("os.write", "O_RDWR", "O_WRONLY", ".write(", "ioctl"):
            self.assertNotIn(word, source)
        self.assertIn("os.O_RDONLY", source)


if __name__ == "__main__":
    unittest.main()
