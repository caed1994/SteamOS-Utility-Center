# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The service that answers the Smart 86 Box panel.

The tests of the sensors build a /sys/class/hwmon in a directory. That is
the only way to check the choice between two graphics chips on a machine
that has one.

The structural test at the end is the one that matters over time. This
module came from a separate project with a hwmon reader of its own, and the
merge is what makes the LED bar and the panel report the same degrees. A
second reader here would pass every test above it.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "server"))
sys.path.insert(0, os.path.join(REPO, "gui"))

from steamos_utility_center import companion, screen, temperature  # noqa: E402
import ledpanel                                                 # noqa: E402

TOKEN = "x" * 32
# A machine with no input devices, for the tests of the batteries alone.
NO_INPUTS = "/does/not/exist"
# The key capabilities of a pad and of a touchpad, as /sys writes them on a
# 64 bit machine: BTN_GAMEPAD is bit 0x130, in the fifth word from the end.
PAD_KEYS = "7fdb000000000000 0 0 0 0"
TOUCHPAD_KEYS = "2420000 0 0 0 0"


def machine(self, chips):
    """A /sys/class/hwmon with those chips in it.

    Each chip is a name and its files, and a file with a slash in it makes
    the directory under it. amdgpu keeps its memory size one level down.
    """
    root = tempfile.mkdtemp()
    self.addCleanup(__import__("shutil").rmtree, root, ignore_errors=True)
    for index, (name, files) in enumerate(chips):
        place = os.path.join(root, "hwmon%d" % index)
        os.makedirs(place, exist_ok=True)
        with open(os.path.join(place, "name"), "w") as handle:
            handle.write(name + "\n")
        for leaf, value in files.items():
            path = os.path.join(place, leaf)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(str(value) + "\n")
    return root


class ControllerTest(unittest.TestCase):
    def machine(self, entries):
        root = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, root, ignore_errors=True)
        for name, files in entries:
            place = os.path.join(root, name)
            os.makedirs(place)
            for leaf, value in files.items():
                with open(os.path.join(place, leaf), "w") as handle:
                    handle.write(str(value) + "\n")
        return root

    def test_a_controller_battery_is_reported_and_a_laptop_one_is_not(self):
        root = self.machine([
            ("ps-controller-battery-01", {"type": "Battery",
                                          "capacity": "78",
                                          "status": "Discharging"}),
            ("BAT0", {"type": "Battery", "capacity": "50"}),
        ])
        self.assertEqual(companion.controllers(root, NO_INPUTS),
                         [{"name": "PlayStation Controller", "percent": 78,
                           "status": "Discharging"}])

    def test_a_capacity_that_is_not_a_number_drops_the_entry(self):
        """The firmware invents no battery, so neither does this."""
        root = self.machine([("ps-controller-battery-01",
                              {"type": "Battery", "capacity": "invalid"})])
        self.assertEqual(companion.controllers(root, NO_INPUTS), [])

    def test_a_controller_that_is_not_present_is_left_out(self):
        root = self.machine([("steam-controller-battery",
                              {"type": "Battery", "capacity": "40",
                               "present": "0"})])
        self.assertEqual(companion.controllers(root, NO_INPUTS), [])

    def test_a_missing_directory_is_no_controllers_and_no_error(self):
        self.assertEqual(companion.controllers("/does/not/exist", NO_INPUTS), [])


class GamepadTest(unittest.TestCase):
    """The controllers with no battery, from /sys/class/input.

    The tree is the one the kernel makes: /sys/class/input holds links to
    the devices, a pad is a child of its HID device, and a battery of that
    HID device has a link back to it.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.inputs = os.path.join(self.root, "class", "input")
        self.power = os.path.join(self.root, "class", "power_supply")
        os.makedirs(self.inputs)
        os.makedirs(self.power)

    def hid(self, place):
        where = os.path.join(self.root, "devices", place)
        os.makedirs(where, exist_ok=True)
        return where

    def pad(self, number, hid, name, vendor, keys=PAD_KEYS):
        where = os.path.join(hid, "input", "input%d" % number)
        os.makedirs(os.path.join(where, "id"))
        os.makedirs(os.path.join(where, "capabilities"))
        for leaf, value in (("name", name), ("id/vendor", vendor),
                            ("capabilities/key", keys)):
            with open(os.path.join(where, leaf), "w") as handle:
                handle.write(value + "\n")
        os.symlink(hid, os.path.join(where, "device"))
        os.symlink(where, os.path.join(self.inputs, "input%d" % number))

    def battery(self, name, hid, capacity, status="Discharging"):
        where = os.path.join(hid, "power_supply", name)
        os.makedirs(where)
        for leaf, value in (("type", "Battery"), ("capacity", capacity),
                            ("status", status)):
            with open(os.path.join(where, leaf), "w") as handle:
                handle.write(value + "\n")
        if hid:
            os.symlink(hid, os.path.join(where, "device"))
        os.symlink(where, os.path.join(self.power, name))

    def found(self):
        return companion.controllers(self.power, self.inputs)

    def test_a_pad_and_its_battery_are_one_controller(self):
        """A DualShock 4 has a pad, a touchpad and a battery on one HID
        device. The touchpad is not a second controller."""
        ds4 = self.hid("pci0/bt/0005:054C:09CC.0003")
        self.pad(20, ds4, "Wireless Controller", "054c")
        self.pad(21, ds4, "Wireless Controller Touchpad", "054c",
                 TOUCHPAD_KEYS)
        self.battery("ps-controller-battery-01", ds4, "78")
        self.assertEqual(self.found(), [{"name": "PlayStation Controller",
                                         "percent": 78,
                                         "status": "Discharging"}])

    def test_a_pad_on_a_cable_has_no_battery_and_is_listed(self):
        xbox = self.hid("pci0/usb3/3-2/3-2:1.0")
        self.pad(7, xbox, "Microsoft X-Box One pad", "045e")
        self.assertEqual(self.found(), [{"name": "Xbox Controller",
                                         "percent": None,
                                         "status": "Unknown"}])

    def test_an_unknown_vendor_keeps_the_name_of_its_pad(self):
        pad = self.hid("pci0/usb3/3-1/3-1:1.0")
        self.pad(8, pad, "8BitDo Pro 2", "2dc8")
        self.assertEqual(self.found()[0]["name"], "8BitDo Pro 2")

    def test_two_pads_of_one_device_are_one_controller(self):
        """A device that adds a second pad for its motion keys is one
        controller in a hand, and one line on the page."""
        pad = self.hid("pci0/usb3/3-4/3-4:1.0")
        self.pad(5, pad, "Pro Controller", "057e")
        self.pad(6, pad, "Pro Controller (IMU)", "057e")
        self.assertEqual(len(self.found()), 1)

    def test_a_keyboard_is_no_controller(self):
        keyboard = self.hid("pci0/usb3/3-3/3-3:1.0")
        self.pad(3, keyboard, "Logitech USB Keyboard", "046d", TOUCHPAD_KEYS)
        self.assertEqual(self.found(), [])

    def test_the_pads_that_steam_makes_are_left_out(self):
        """Steam drives a controller through a pad of its own, an Xbox 360
        pad that the kernel log names. The board had one."""
        virtual = self.hid("virtual/input")
        self.pad(47, virtual, "Microsoft X-Box 360 pad 1", "045e")
        self.assertEqual(self.found(), [])

    def test_the_slots_of_the_puck_are_left_out(self):
        """steamcontroller.py reads those, and an empty slot is no pad."""
        slot = self.hid("pci0/usb1/1-1/1-1:1.3/0003:28DE:1304.0015")
        self.pad(44, slot, "Valve Software Steam Controller Puck", "28de")
        self.assertEqual(self.found(), [])

    def test_the_pads_come_in_the_order_they_arrived(self):
        first = self.hid("pci0/usb3/3-1/3-1:1.0")
        later = self.hid("pci0/usb3/3-2/3-2:1.0")
        self.pad(9, first, "Pad A", "1234")
        self.pad(10, later, "Pad B", "1234")
        self.assertEqual([one["name"] for one in self.found()],
                         ["Pad A", "Pad B"])

    def test_a_battery_with_no_pad_comes_first(self):
        """That is the Steam Controller while Steam is not running: its pad
        is a pad of Valve, and the panel shows the first two."""
        steam = self.hid("pci0/usb1/1-1/1-1:1.2/0003:28DE:1304.0014")
        self.battery("steam-ABC", steam, "64")
        xbox = self.hid("pci0/usb3/3-2/3-2:1.0")
        self.pad(7, xbox, "Microsoft X-Box One pad", "045e")
        self.assertEqual([one["name"] for one in self.found()],
                         ["Steam Controller", "Xbox Controller"])

    def test_the_bits_are_read_from_the_end(self):
        self.assertTrue(companion._has_key(PAD_KEYS, 0x130))
        self.assertFalse(companion._has_key(TOUCHPAD_KEYS, 0x130))
        self.assertFalse(companion._has_key("", 0x130))
        self.assertFalse(companion._has_key("zz 0 0 0 0", 0x130))


class NumberedTest(unittest.TestCase):
    def test_two_of_one_name_get_a_number_each(self):
        pads = [{"name": "Steam Controller", "percent": 93},
                {"name": "PlayStation Controller", "percent": 60},
                {"name": "Steam Controller", "percent": 8}]
        self.assertEqual([one["name"] for one in companion.numbered(pads)],
                         ["Steam Controller 1", "PlayStation Controller",
                          "Steam Controller 2"])

    def test_one_of_a_name_keeps_it(self):
        pads = [{"name": "Steam Controller", "percent": 93}]
        self.assertEqual(companion.numbered(pads), pads)

    def test_the_status_numbers_across_both_lists(self):
        """One Steam Controller on the puck and one the kernel reports are
        two of one name on the page."""
        steam = {"name": "Steam Controller", "percent": 93,
                 "status": "Discharging"}
        with mock.patch.object(companion.steamcontroller, "batteries",
                               return_value=[steam]), \
                mock.patch.object(companion, "controllers",
                                  return_value=[dict(steam, percent=40)]):
            answer = companion.status()
        self.assertEqual([one["name"] for one in answer["controllers"]],
                         ["Steam Controller 1", "Steam Controller 2"])


class AnswerSizeTest(unittest.TestCase):
    """The answer of the status against the buffer the panel reads it into.

    The panel reads the answer into one buffer, and an answer past its end
    is no answer at all: the panel then says that the PC does not answer.
    So every list stops where the panel stops reading, and the largest
    answer this service gives fills half the buffer at the most.
    """

    machine = machine

    @staticmethod
    def firmware(name):
        with open(os.path.join(REPO, "firmware", "companion", "main", name),
                  encoding="utf-8") as handle:
            return handle.read()

    def test_the_lists_stop_where_the_panel_stops(self):
        header = self.firmware("ui.h")
        for name in ("PANEL_PADS", "PANEL_SENSORS", "PANEL_DRIVES"):
            found = re.search(r"#define %s (\d+)" % name, header)
            self.assertIsNotNone(found, name)
            self.assertEqual(int(found.group(1)), getattr(companion, name),
                             name)
        kept = re.search(r"char playing\[(\d+)\];", header)
        self.assertEqual(int(kept.group(1)) - 1, companion.PLAYING_CHARS)

    def test_a_sensor_for_each_core_is_six_for_the_panel(self):
        """coretemp reports the package and then every core. The best one
        stays first."""
        files = {"temp1_input": 61000, "temp1_label": "Package id 0"}
        for core in range(24):
            files["temp%d_input" % (core + 2)] = 50000 + core
            files["temp%d_label" % (core + 2)] = "Core %d" % core
        said = companion.telemetry(self.machine([("coretemp", files)]))
        self.assertEqual(len(said["cpu_sensors"]), companion.PANEL_SENSORS)
        self.assertEqual(said["cpu_c"], said["cpu_sensors"][0]["c"])

    def largest(self):
        """The status with every list full and every text at its end."""
        cores = {}
        for chip in range(2):
            for core in range(40):
                cores["temp%d_input" % (core + 1)] = 99000
                cores["temp%d_label" % (core + 1)] = "Core %d" % (core + 100)
        card = {"device/mem_info_vram_total": 1 << 40,
                "device/mem_info_vram_used": 1 << 40,
                "device/gpu_busy_percent": 100,
                "freq1_input": companion.SANE_MHZ * companion.HERTZ_PER_MHZ,
                "freq1_label": "sclk", "power1_average": 1999000000}
        for sensor in range(12):
            card["temp%d_input" % (sensor + 1)] = 99000
            card["temp%d_label" % (sensor + 1)] = "junction%d" % sensor
        root = self.machine([("coretemp", cores), ("coretemp", cores),
                             ("amdgpu", card)])
        real = companion.telemetry
        pad = {"name": "P" * 63, "percent": 100, "status": "Discharging"}
        drive = {"name": "D" * 63, "total": 1 << 50, "free": 1 << 50}
        sha = "f" * 64
        offer = mock.Mock()
        offer.signed.return_value = {"build": 99999999, "version": "V" * 31,
                                     "size": companion.SLOT_BYTES,
                                     "sha256": sha, "sign": sha}
        name = mock.Mock(nodename="H" * 64)
        longest = max(companion.config_module.DESKTOP_SCENES
                      + companion.config_module.RAINBOW_CHOICES, key=len)
        with mock.patch.object(companion.steamcontroller, "batteries",
                               return_value=[pad] * 8), \
                mock.patch.object(companion, "controllers",
                                  return_value=[pad] * 8), \
                mock.patch.object(companion, "audio",
                                  return_value={"percent": 100,
                                                "muted": False}), \
                mock.patch.object(companion, "telemetry",
                                  side_effect=lambda: real(root)), \
                mock.patch.object(companion, "wake_target",
                                  return_value={"interface": "I" * 15,
                                                "mac": "ff:" * 5 + "ff"}), \
                mock.patch.object(companion.steamapps, "now_playing",
                                  return_value="G" * 300), \
                mock.patch.object(companion.steamapps,
                                  "now_playing_achievements",
                                  return_value={"achieved": 99999,
                                                "total": 99999}), \
                mock.patch.object(companion, "drives",
                                  return_value=[drive] * 12), \
                mock.patch.object(companion, "led",
                                  return_value={"desktop": longest,
                                                "game": longest,
                                                "desktop_color": "#ffffff",
                                                "desktop_brightness": 255,
                                                "mirror": {
                                                    "state": max(
                                                        screen.STATES,
                                                        key=len),
                                                    "detail": "D" * screen
                                                    .DETAIL_CHARS,
                                                    "fps": 999.9,
                                                    "cpu": 9999.9,
                                                    "source":
                                                    "65535x65535"}}), \
                mock.patch.object(companion, "_boost", mock.Mock(
                    read=mock.Mock(return_value=False),
                    zero_rpm=mock.Mock(return_value=False))), \
                mock.patch.object(companion, "cpu",
                                  return_value={
                                      "profile": "performance",
                                      "offers": ["powersave", "balanced",
                                                 "performance", "steamos"],
                                      "governor": "G" * companion.CPU_WORD,
                                      "epp": "E" * companion.CPU_WORD,
                                      "driver": "D" * companion.CPU_WORD}), \
                mock.patch.object(companion.pcinfo, "system",
                                  return_value={"os": "O" * 31,
                                                "build": "B" * 23,
                                                "channel": "C" * 15,
                                                "kernel": "K" * 47}), \
                mock.patch.object(companion.pcinfo, "uptime",
                                  return_value=10 * 366 * 24 * 3600), \
                mock.patch.object(companion.pcinfo, "cpu_model",
                                  return_value="C" * 47), \
                mock.patch.object(companion._cpu_load, "percent",
                                  return_value=100), \
                mock.patch.object(companion.pcinfo, "gpu_model",
                                  return_value="G" * 47), \
                mock.patch.object(companion.pcinfo, "memory",
                                  return_value={"used": 1 << 40,
                                                "total": 1 << 40}), \
                mock.patch.object(companion, "fans",
                                  return_value={"fan": 99999,
                                                "gpu_fan": 99999}), \
                mock.patch.object(companion.pcinfo, "network",
                                  return_value={"ip": "255.255.255.255",
                                                "kind": "wireless",
                                                "speed": 100000,
                                                "mac": "ff:" * 5 + "ff"}), \
                mock.patch.object(companion.os, "uname", return_value=name):
            return companion.status("255.255.255.255", "t" * 64, offer)

    def test_the_largest_answer_fills_half_the_buffer_at_most(self):
        """Half, so a field added later has room before it breaks the
        panel. This test then says how close it came."""
        answer = self.largest()
        self.assertEqual(len(answer["controllers"]), companion.PANEL_PADS)
        self.assertEqual(len(answer["drives"]), companion.PANEL_DRIVES)
        self.assertEqual(len(answer["telemetry"]["cpu_sensors"]),
                         companion.PANEL_SENSORS)
        self.assertEqual(len(answer["telemetry"]["gpu_sensors"]),
                         companion.PANEL_SENSORS)
        self.assertEqual(len(answer["playing"]), companion.PLAYING_CHARS)
        self.assertEqual(answer["telemetry"]["gpu_mhz"], companion.SANE_MHZ)
        size = len(json.dumps(answer, separators=(",", ":")).encode())
        buffer = int(re.search(r"typedef struct \{ char data\[(\d+)\];",
                               self.firmware("main.c")).group(1))
        self.assertLessEqual(size, buffer // 2,
                             "the largest answer is %d bytes" % size)


class TelemetryTest(unittest.TestCase):
    machine = machine

    def test_every_sensor_of_the_processor_and_the_card_to_choose(self):
        """The board: a Ryzen 7 7800X3D with Tctl and one CCD, and a card
        with edge, junction and memory. The best answer comes first, and
        an NVMe drive is neither."""
        root = self.machine([
            ("k10temp", {"temp1_input": 49500, "temp1_label": "Tctl",
                         "temp3_input": 47000, "temp3_label": "Tccd1"}),
            ("nvme", {"temp1_input": 38000, "temp1_label": "Composite"}),
            ("amdgpu", {"temp1_input": 52000, "temp1_label": "edge",
                        "temp2_input": 68000, "temp2_label": "junction",
                        "temp3_input": 60000, "temp3_label": "mem",
                        "device/mem_info_vram_total": 16384}),
        ])
        said = companion.telemetry(root)
        self.assertEqual(said["cpu_sensors"], [
            {"id": "k10temp/Tctl", "name": "Tctl", "c": 50},
            {"id": "k10temp/Tccd1", "name": "CCD 1", "c": 47}])
        self.assertEqual([(one["id"], one["name"]) for one in
                          said["gpu_sensors"]],
                         [("amdgpu/edge", "Edge"),
                          ("amdgpu/junction", "Junction (Hotspot)"),
                          ("amdgpu/mem", "VRAM")])
        self.assertEqual(said["cpu_c"], said["cpu_sensors"][0]["c"])

    def test_a_sensor_with_no_label_is_named_by_its_file(self):
        root = self.machine([("k10temp", {"temp1_input": 49500})])
        self.assertEqual(companion.telemetry(root)["cpu_sensors"],
                         [{"id": "k10temp/temp1", "name": "temp1", "c": 50}])

    def test_a_broken_sensor_is_offered_with_no_reading(self):
        root = self.machine([("k10temp", {"temp1_input": 4000000,
                                          "temp1_label": "Tctl"})])
        self.assertIsNone(companion.telemetry(root)["cpu_sensors"][0]["c"])

    def test_the_units_and_the_card_with_the_most_memory(self):
        """A Ryzen with a graphics part and a card gives two amdgpu chips."""
        root = self.machine([
            ("k10temp", {"temp1_input": 49500}),
            ("amdgpu", {"temp1_input": 35000, "power1_average": 5000000,
                        "device/mem_info_vram_total": 512}),
            ("amdgpu", {"temp1_input": 56000, "power1_average": 78000000,
                        "device/mem_info_vram_total": 16384}),
        ])
        said = companion.telemetry(root)
        self.assertEqual({key: said[key] for key in ("cpu_c", "gpu_c",
                                                     "gpu_w")},
                         {"cpu_c": 50, "gpu_c": 56, "gpu_w": 78})
        # The choice of the card is the card of the answer: its sensors
        # alone, and not the graphics part of the Ryzen.
        self.assertEqual([one["c"] for one in said["gpu_sensors"]], [56])

    def test_power1_input_answers_where_there_is_no_average(self):
        root = self.machine([
            ("amdgpu", {"temp1_input": 40000, "power1_input": 30000000,
                        "device/mem_info_vram_total": 16384}),
        ])
        self.assertEqual(companion.telemetry(root)["gpu_w"], 30)

    def test_a_machine_with_no_sensors_reports_a_dash_for_each(self):
        self.assertEqual(companion.telemetry("/does/not/exist"),
                         {"cpu_c": None, "gpu_c": None, "gpu_w": None,
                          "gpu_load": None, "vram_used": None,
                          "vram_total": None, "gpu_mhz": None,
                          "gpu_mhz_max": None,
                          "cpu_sensors": [], "gpu_sensors": []})

    # The board: an RX 9070 XT at work, with 9.8 of 16 GB in use and the
    # shader clock at 2450 MHz. amdgpu writes the clock in hertz.
    CARD = {"temp1_input": 56000, "power1_average": 245000000,
            "freq1_input": 2450000000, "freq1_label": "sclk",
            "freq2_input": 1258000000, "freq2_label": "mclk",
            "device/gpu_busy_percent": 87,
            "device/mem_info_vram_used": 10522460160,
            "device/mem_info_vram_total": 17163091968,
            "device/pp_dpm_sclk": "0: 500Mhz\n1: 2450Mhz *\n2: 2970Mhz"}

    def test_the_load_the_memory_and_the_clock_of_the_card(self):
        said = companion.telemetry(self.machine([("amdgpu", self.CARD)]))
        self.assertEqual({key: said[key] for key in
                          ("gpu_load", "vram_used", "vram_total", "gpu_mhz",
                           "gpu_mhz_max")},
                         {"gpu_load": 87, "vram_used": 10522460160,
                          "vram_total": 17163091968, "gpu_mhz": 2450,
                          "gpu_mhz_max": 2970})

    def test_the_top_of_the_clock_is_its_highest_level(self):
        """The level in use has a star, and a card in deep sleep reports a
        level "S" under the numbered ones. Neither changes the top."""
        levels = "S: 19Mhz\n0: 500Mhz *\n1: 3100Mhz\n2: 2615Mhz"
        card = dict(self.CARD, **{"device/pp_dpm_sclk": levels})
        said = companion.telemetry(self.machine([("amdgpu", card)]))
        self.assertEqual(said["gpu_mhz_max"], 3100)
        for levels in ("", "S: 19Mhz *", "0: fast"):
            card = dict(self.CARD, **{"device/pp_dpm_sclk": levels})
            said = companion.telemetry(self.machine([("amdgpu", card)]))
            self.assertIsNone(said["gpu_mhz_max"], levels)
        card = {key: value for key, value in self.CARD.items()
                if key != "device/pp_dpm_sclk"}
        said = companion.telemetry(self.machine([("amdgpu", card)]))
        self.assertIsNone(said["gpu_mhz_max"])

    def test_they_come_from_the_card_and_not_the_graphics_part(self):
        """The Ryzen has its own amdgpu chip, busy with nothing. The values
        are the ones of the card that the temperature comes from."""
        small = {"temp1_input": 35000, "freq1_input": 400000000,
                 "freq1_label": "sclk", "device/gpu_busy_percent": 3,
                 "device/mem_info_vram_used": 100,
                 "device/mem_info_vram_total": 512}
        said = companion.telemetry(self.machine([("amdgpu", small),
                                                 ("amdgpu", self.CARD)]))
        self.assertEqual((said["gpu_load"], said["gpu_mhz"],
                          said["vram_total"]), (87, 2450, 17163091968))

    def test_the_clock_is_the_one_named_sclk(self):
        """freq2 is the memory clock. A first freq that is not sclk is no
        shader clock, and the panel gets a dash and not the wrong one."""
        card = dict(self.CARD, freq1_label="mclk")
        said = companion.telemetry(self.machine([("amdgpu", card)]))
        self.assertIsNone(said["gpu_mhz"])
        card = {key: value for key, value in self.CARD.items()
                if key != "freq1_label"}
        said = companion.telemetry(self.machine([("amdgpu", card)]))
        self.assertIsNone(said["gpu_mhz"])

    def test_what_cannot_be_is_no_reading(self):
        card = dict(self.CARD, **{"device/gpu_busy_percent": 140,
                                  "device/mem_info_vram_used": 17163091969,
                                  "freq1_input": 20000000000,
                                  "device/pp_dpm_sclk": "0: 20000Mhz"})
        said = companion.telemetry(self.machine([("amdgpu", card)]))
        self.assertEqual((said["gpu_load"], said["vram_used"],
                          said["vram_total"], said["gpu_mhz"],
                          said["gpu_mhz_max"]),
                         (None, None, None, None, None))

    def test_a_reading_outside_the_possible_is_no_reading(self):
        root = self.machine([("k10temp", {"temp1_input": 4000000})])
        self.assertIsNone(companion.telemetry(root)["cpu_c"])

    def test_zenpower_answers_where_the_kernel_has_no_k10temp(self):
        """It replaces k10temp on a Ryzen, and this machine then has one CPU
        chip under another name. Without it the answer was acpitz."""
        root = self.machine([
            ("acpitz", {"temp1_input": 27000}),
            ("zenpower", {"temp1_input": 61000}),
        ])
        self.assertEqual(companion.telemetry(root)["cpu_c"], 61)

    def test_the_label_inside_a_chip_decides_which_sensor(self):
        """k10temp publishes Tctl and Tdie. temperature.py ranks them, and
        this test fails if the ranking stops being asked."""
        root = self.machine([("k10temp", {"temp1_input": 90000,
                                          "temp1_label": "Tccd1",
                                          "temp2_input": 55000,
                                          "temp2_label": "Tctl"})])
        self.assertEqual(companion.telemetry(root)["cpu_c"], 55)


class ServiceTest(unittest.TestCase):
    """The service, asked the way the panel asks."""

    def serve(self):
        self.nonces = companion.Nonces()
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), companion.make_handler(TOKEN, self.nonces))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.conn = HTTPConnection("127.0.0.1", httpd.server_port)
        self.addCleanup(self.conn.close)
        return self.conn

    def ask(self, method, path, body=b"", nonce=None, auth=None,
            headers=None):
        """One signed request. Each part is a parameter, so a test can put
        one of them wrong and leave the others right."""
        nonce = self.nonces.issue() if nonce is None else nonce
        sent = {companion.NONCE_HEADER: nonce,
                companion.AUTH_HEADER: auth if auth is not None
                else companion.signature(TOKEN, method, path, nonce, body)}
        sent.update(headers or {})
        self.conn.request(method, path, body, sent)
        answer = self.conn.getresponse()
        answer.read()
        return answer

    def action(self, name, **kw):
        return self.ask("POST", "/v1/action",
                        json.dumps({"action": name}).encode(), **kw)

    def test_a_signed_read_is_answered(self):
        self.serve()
        self.assertEqual(self.ask("GET", "/v1/status").status, 200)

    def test_nothing_at_all_reaches_nothing(self):
        conn = self.serve()
        conn.request("GET", "/v1/status")
        answer = conn.getresponse()
        answer.read()
        self.assertEqual(answer.status, 401)

    def test_the_bare_token_in_a_header_reaches_nothing(self):
        """The scheme this replaced. A panel with old firmware is refused,
        rather than quietly keeping the weaker of the two."""
        conn = self.serve()
        conn.request("GET", "/v1/status", headers={"X-Panel-Token": TOKEN})
        answer = conn.getresponse()
        answer.read()
        self.assertEqual(answer.status, 401)

    def test_the_same_request_a_second_time_is_refused(self):
        """The point of the whole scheme. Somebody who reads one request off
        the network holds a suspend for as long as the token lasts."""
        self.serve()
        nonce = self.nonces.issue()
        auth = companion.signature(TOKEN, "GET", "/v1/status", nonce, b"")
        self.assertEqual(self.ask("GET", "/v1/status", nonce=nonce,
                                  auth=auth).status, 200)
        self.assertEqual(self.ask("GET", "/v1/status", nonce=nonce,
                                  auth=auth).status, 401)

    def test_a_signature_for_one_path_does_not_fit_another(self):
        self.serve()
        nonce = self.nonces.issue()
        auth = companion.signature(TOKEN, "GET", "/v1/status", nonce, b"")
        self.assertEqual(self.ask("GET", "/v1/other", nonce=nonce,
                                  auth=auth).status, 401)

    def test_a_captured_press_cannot_be_re_addressed(self):
        """mute and poweroff go to the same path with the same method. The
        body is under the signature, which is what tells them apart."""
        self.serve()
        nonce = self.nonces.issue()
        mute = json.dumps({"action": "mute"}).encode()
        auth = companion.signature(TOKEN, "POST", "/v1/action", nonce, mute)
        with mock.patch.object(companion.subprocess, "run") as ran:
            self.assertEqual(
                self.ask("POST", "/v1/action",
                         json.dumps({"action": "poweroff"}).encode(),
                         nonce=nonce, auth=auth).status, 401)
            ran.assert_not_called()

    def test_a_wrong_signature_leaves_the_nonce_alone(self):
        """Or a stranger burns the nonce of the panel by guessing at it."""
        self.serve()
        nonce = self.nonces.issue()
        self.assertEqual(self.ask("GET", "/v1/status", nonce=nonce,
                                  auth="0" * 64).status, 401)
        self.assertEqual(self.ask("GET", "/v1/status", nonce=nonce).status,
                         200)

    def test_every_answer_carries_the_next_nonce(self):
        """Including the 401, which is how a panel that lost its nonce comes
        back with no help from anybody."""
        conn = self.serve()
        conn.request("GET", "/v1/status")
        answer = conn.getresponse()
        answer.read()
        offered = answer.getheader(companion.NONCE_HEADER)
        self.assertTrue(offered)
        auth = companion.signature(TOKEN, "GET", "/v1/status", offered, b"")
        self.assertEqual(self.ask("GET", "/v1/status", nonce=offered,
                                  auth=auth).status, 200)

    def test_an_unknown_path_answers_the_same_to_a_stranger(self):
        conn = self.serve()
        for path in ("/v1/status", "/v1/nothing", "/"):
            conn.request("GET", path)
            answer = conn.getresponse()
            answer.read()
            self.assertEqual(answer.status, 401, path)

    def test_an_action_that_is_not_in_the_table_runs_nothing(self):
        self.serve()
        with mock.patch.object(companion.subprocess, "run") as ran:
            self.assertEqual(self.action("shell").status, 400)
            ran.assert_not_called()

    def test_a_known_action_runs_and_answers(self):
        self.serve()
        with mock.patch.object(companion.subprocess, "run") as ran:
            self.assertEqual(self.action("mute").status, 200)
            ran.assert_called_once()
            self.assertEqual(ran.call_args[0][0], companion.ACTIONS["mute"])

    def test_a_refused_command_comes_back_as_a_refusal(self):
        self.serve()
        with mock.patch.object(companion.subprocess, "run") as ran:
            ran.side_effect = companion.subprocess.CalledProcessError(
                1, ["systemctl"])
            self.assertEqual(self.action("suspend").status, 502)

    def test_a_body_that_is_too_long_is_not_read(self):
        conn = self.serve()
        conn.request("POST", "/v1/action", b"x" * (companion.BODY_LIMIT + 1))
        answer = conn.getresponse()
        answer.read()
        self.assertEqual(answer.status, 400)

    def test_every_action_is_a_tuple_and_never_a_string(self):
        """A string goes to a shell. Each of these goes to execve."""
        for name, command in companion.ACTIONS.items():
            self.assertIsInstance(command, tuple, name)
            self.assertTrue(all(isinstance(one, str) for one in command), name)

    def led(self, request, **kw):
        return self.ask("POST", companion.LED_PATH,
                        json.dumps(request).encode(), **kw)

    def test_a_signed_change_of_the_led_bar_is_applied(self):
        self.serve()
        with mock.patch.object(companion.ctl, "strip_write") as wrote:
            self.assertEqual(self.led({"desktop": "fire"}).status, 200)
        wrote.assert_called_once_with({"DESKTOP_SCENE": "fire"})

    def test_a_signed_change_of_the_colour_is_applied(self):
        self.serve()
        with mock.patch.object(companion.ctl, "strip_write") as wrote:
            self.assertEqual(self.led({"desktop_color": "#ff0000",
                                       "desktop_brightness": 200}).status,
                             200)
        wrote.assert_called_once_with({"DESKTOP_COLOR": "#ff0000",
                                       "DESKTOP_BRIGHTNESS": 200})

    def test_an_unsigned_change_of_the_led_bar_reaches_nothing(self):
        conn = self.serve()
        with mock.patch.object(companion.ctl, "strip_write") as wrote:
            conn.request("POST", companion.LED_PATH,
                         json.dumps({"desktop": "off"}).encode())
            answer = conn.getresponse()
            answer.read()
        self.assertEqual(answer.status, 401)
        wrote.assert_not_called()

    def test_a_captured_change_cannot_carry_another_effect(self):
        """The body is under the signature, as it is for a press."""
        self.serve()
        nonce = self.nonces.issue()
        off = json.dumps({"desktop": "off"}).encode()
        auth = companion.signature(TOKEN, "POST", companion.LED_PATH, nonce,
                                   off)
        with mock.patch.object(companion.ctl, "strip_write") as wrote:
            self.assertEqual(self.led({"desktop": "fire"}, nonce=nonce,
                                      auth=auth).status, 401)
        wrote.assert_not_called()

    def test_a_press_is_not_a_change_of_the_led_bar(self):
        """Each path reads its own keys. A press sent to the path of the
        LED bar changes nothing, and runs nothing."""
        self.serve()
        with mock.patch.object(companion.ctl, "strip_write") as wrote, \
                mock.patch.object(companion.subprocess, "run") as ran:
            self.assertEqual(self.led({"action": "poweroff"}).status, 400)
            self.assertEqual(self.action("fire").status, 400)
        wrote.assert_not_called()
        ran.assert_not_called()

    def test_a_signed_change_of_the_cpu_is_applied(self):
        self.serve()
        with mock.patch.object(companion, "cpu_change",
                               return_value=(200, {"ok": True})) as changed:
            answer = self.ask("POST", companion.CPU_PATH,
                              json.dumps({"profile": "balanced"}).encode())
        self.assertEqual(answer.status, 200)
        changed.assert_called_once_with({"profile": "balanced"})

    def test_an_unsigned_change_of_the_cpu_reaches_nothing(self):
        conn = self.serve()
        with mock.patch.object(companion, "cpu_change") as changed:
            conn.request("POST", companion.CPU_PATH,
                         json.dumps({"profile": "performance"}).encode())
            answer = conn.getresponse()
            answer.read()
        self.assertEqual(answer.status, 401)
        changed.assert_not_called()

    def test_the_status_carries_the_cpu(self):
        conn = self.serve()
        profile = {"profile": "balanced", "offers": ["balanced", "steamos"],
                   "governor": "powersave", "epp": "balance_performance",
                   "driver": "amd-pstate-epp"}
        with mock.patch.object(companion, "cpu", return_value=profile):
            nonce = self.nonces.issue()
            conn.request("GET", "/v1/status", headers={
                companion.NONCE_HEADER: nonce,
                companion.AUTH_HEADER: companion.signature(
                    TOKEN, "GET", "/v1/status", nonce, b"")})
            answer = conn.getresponse()
            said = json.loads(answer.read())
        self.assertEqual(said["cpu"], profile)

    def test_the_status_carries_the_led_bar(self):
        conn = self.serve()
        effects = {"desktop": "aurora", "game": "load"}
        with mock.patch.object(companion, "led", return_value=effects):
            nonce = self.nonces.issue()
            conn.request("GET", "/v1/status", headers={
                companion.NONCE_HEADER: nonce,
                companion.AUTH_HEADER: companion.signature(
                    TOKEN, "GET", "/v1/status", nonce, b"")})
            answer = conn.getresponse()
            said = json.loads(answer.read())
        self.assertEqual(said["led"], effects)


class BoostTest(unittest.TestCase):
    """Cooling Boost and zero RPM: their state in the status, and their
    presses."""

    BOOSTED = {"fan_control_enabled": True,
               "fan_control_settings": {"mode": "static",
                                        "static_speed": 1.0}}
    CARD = {"fan_control_enabled": False}

    @staticmethod
    def stats(zero_rpm):
        """What the card reports of its firmware fan settings."""
        return {"fan": {"pmfw_info": {"zero_rpm_enable": zero_rpm}}}

    def daemon(self, config=None, devices=None, refuse=None, stats=None):
        """A LACT daemon that answers each question, and the questions it
        got."""
        asked = []

        def talk(name, path=None, args=None, timeout=None):
            asked.append((name, timeout))
            if refuse:
                raise companion.lact.LactError(refuse)
            if name == "list_devices":
                return [{"id": "1002:744C"}] if devices is None else devices
            if name == "device_stats":
                return {} if stats is None else stats
            return self.BOOSTED if config is None else config

        for patcher in (mock.patch.object(companion.lact, "available",
                                          return_value=True),
                        mock.patch.object(companion.lact, "talk",
                                          side_effect=talk)):
            patcher.start()
            self.addCleanup(patcher.stop)
        return asked

    def test_the_fan_of_the_card_is_the_answer(self):
        self.daemon()
        self.assertIs(companion.BoostState().read(), True)

    def test_a_fan_that_the_boost_does_not_hold_is_off(self):
        self.daemon(config=self.CARD)
        self.assertIs(companion.BoostState().read(), False)

    def test_no_lact_no_card_and_no_answer_are_no_switch(self):
        with mock.patch.object(companion.lact, "available",
                               return_value=False):
            self.assertIsNone(companion.BoostState().read())
        for devices in ([], [{}], "not a list", [{"id": ""}]):
            with self.subTest(devices=devices):
                with mock.patch.object(companion.lact, "available",
                                       return_value=True), \
                        mock.patch.object(companion.lact, "talk",
                                          return_value=devices):
                    self.assertIsNone(companion.BoostState().read())

    def test_a_daemon_that_does_not_answer_is_no_switch(self):
        asked = self.daemon(refuse="LACT did not answer within 0.5 seconds")
        self.assertIsNone(companion.BoostState().read())
        self.assertEqual(asked, [("list_devices", companion.BOOST_WAIT)])

    def test_each_question_waits_a_moment_and_not_the_status(self):
        """The panel waits four seconds for the whole status."""
        asked = self.daemon()
        companion.BoostState().read()
        self.assertEqual([wait for _, wait in asked],
                         [companion.BOOST_WAIT] * 3)
        self.assertLess(3 * companion.BOOST_WAIT, 4)

    def test_one_set_of_questions_in_its_time_at_the_most(self):
        """For both answers: zero RPM comes from the same questions."""
        asked = self.daemon()
        now = [100.0]
        state = companion.BoostState(clock=lambda: now[0])
        state.read()
        now[0] += companion.BOOST_EVERY - 0.1
        state.read()
        state.zero_rpm()
        self.assertEqual(len(asked), 3)
        now[0] += 0.1
        state.zero_rpm()
        state.read()
        self.assertEqual(len(asked), 6)

    def test_a_press_makes_the_next_status_ask_again(self):
        asked = self.daemon()
        state = companion.BoostState(clock=lambda: 100.0)
        state.read()
        with mock.patch.object(companion, "_boost", state):
            self.assertEqual(companion.boost_press("gpu-zero-rpm-on",
                                                   run=lambda: None)[0], 200)
        state.read()
        self.assertEqual(len(asked), 6)

    def test_zero_rpm_is_the_setting_of_lact_or_the_card(self):
        """LACT holds zero RPM off on the card for a static speed and puts
        its setting back after it. So the setting is the answer, and the
        card answers where LACT has none."""
        self.daemon(config=self.CARD, stats=self.stats(True))
        self.assertIs(companion.BoostState().zero_rpm(), True)
        held = dict(self.BOOSTED, pmfw_options={"zero_rpm": True})
        self.daemon(config=held, stats=self.stats(False))
        self.assertIs(companion.BoostState().zero_rpm(), True)
        self.daemon(config=dict(self.CARD, pmfw_options={"zero_rpm": False}),
                    stats=self.stats(True))
        self.assertIs(companion.BoostState().zero_rpm(), False)

    def test_a_card_without_zero_rpm_has_no_button(self):
        """The card reports the setting where its file exists. A setting in
        the config of LACT does not make a card that has none."""
        self.daemon(config=dict(self.CARD, pmfw_options={"zero_rpm": True}))
        self.assertIsNone(companion.BoostState().zero_rpm())

    def test_no_stats_take_zero_rpm_away_and_not_the_boost(self):
        asked = []

        def talk(name, path=None, args=None, timeout=None):
            asked.append(name)
            if name == "list_devices":
                return [{"id": "1002:744C"}]
            if name == "device_stats":
                raise companion.lact.LactError("no stats")
            return self.BOOSTED

        with mock.patch.object(companion.lact, "available", return_value=True), \
                mock.patch.object(companion.lact, "talk", side_effect=talk):
            state = companion.BoostState()
            self.assertIs(state.read(), True)
            self.assertIsNone(state.zero_rpm())
        self.assertEqual(asked, ["list_devices", "get_gpu_config", "device_stats"])

    def test_each_press_names_where_to_go(self):
        """Not a toggle: the status the panel has is up to three seconds
        old."""
        ran = []
        actions = {name: (lambda name=name: ran.append(name))
                   for name in ("gpu-boost-on", "gpu-boost-off",
                                "gpu-zero-rpm-on", "gpu-zero-rpm-off")}
        with mock.patch.dict(companion.ctl.ACTION, actions):
            self.assertEqual(companion.press("gpu_boost_on"), (200, {"ok": True}))
            self.assertEqual(companion.press("gpu_boost_off")[0], 200)
            self.assertEqual(companion.press("gpu_zero_rpm_on")[0], 200)
            self.assertEqual(companion.press("gpu_zero_rpm_off")[0], 200)
        self.assertEqual(ran, ["gpu-boost-on", "gpu-boost-off",
                               "gpu-zero-rpm-on", "gpu-zero-rpm-off"])
        self.assertEqual(companion.press("gpu_boost"), (400, {"error": "unsupported action"}))
        self.assertEqual(companion.press("gpu_zero_rpm"), (400, {"error": "unsupported action"}))

    def test_a_refusal_comes_back_as_its_own_code(self):
        def refuse(error):
            def run():
                raise error
            return run

        for error, code in ((companion.ctl.CtlError("no card"), 501),
                            (companion.lact.LactError("refused"), 503)):
            with mock.patch.object(companion.sys, "stderr"):
                self.assertEqual(
                    companion.boost_press("gpu-boost-on", run=refuse(error))[0],
                    code, error)

    def test_the_status_carries_it(self):
        with mock.patch.object(companion._boost, "read", return_value=True), \
                mock.patch.object(companion._boost, "zero_rpm", return_value=False):
            said = companion.status("127.0.0.1", TOKEN)
        self.assertIs(said["boost"], True)
        self.assertIs(said["zero_rpm"], False)

    def test_a_refusal_of_zero_rpm_says_why(self):
        def run():
            raise companion.ctl.CtlError("the card has no zero RPM")
        self.assertEqual(companion.boost_press("gpu-zero-rpm-on", run=run),
                         (501, {"error": "the card has no zero RPM"}))

    def test_every_press_the_panel_sends_is_one_the_service_knows(self):
        """Two ends of one wire. A press with a name only the panel knows
        is a switch that answers 400."""
        with open(os.path.join(REPO, "firmware", "companion", "main",
                               "main.c"), encoding="utf-8") as handle:
            main = handle.read()
        table = re.search(r"const char \*names\[\]=\{(.*?)\};", main, re.S)
        self.assertIsNotNone(table)
        names = re.findall(r'"([a-z_]+)"', table.group(1))
        self.assertIn("gpu_boost_on", names)
        self.assertIn("gpu_boost_off", names)
        self.assertIn("gpu_zero_rpm_on", names)
        self.assertIn("gpu_zero_rpm_off", names)
        for name in names:
            self.assertTrue(name in companion.ACTIONS
                            or name in companion.BOOST_PRESSES, name)


class CpuTest(unittest.TestCase):
    """The CPU profile, as the status reports it and a change sets it."""

    def machine(self, governors="performance powersave",
                preferences="default performance balance_performance "
                            "balance_power power",
                running=("powersave", "balance_performance")):
        """A sysfs with two policies of amd-pstate in its active mode."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for cpu in range(2):
            where = os.path.join(root,
                                 "sys/devices/system/cpu/cpu%d/cpufreq" % cpu)
            os.makedirs(where)
            files = {"scaling_driver": "amd-pstate-epp",
                     "scaling_available_governors": governors,
                     "scaling_governor": running[0]}
            if preferences:
                files["energy_performance_available_preferences"] = preferences
                files["energy_performance_preference"] = running[1]
            for name, text in files.items():
                with open(os.path.join(where, name), "w") as handle:
                    handle.write(text + "\n")
        return root

    def status(self, root, settings=None, present=True):
        with mock.patch.object(companion.power, "read",
                               return_value=dict(companion.power.DEFAULTS,
                                                 **(settings or {}))):
            return companion.cpu(present=lambda path: present, root=root)

    def test_a_machine_without_the_power_module_has_no_page(self):
        self.assertIsNone(self.status(self.machine(), present=False))

    def test_the_power_module_is_known_by_its_applier(self):
        looked = []
        companion.cpu(present=lambda path: looked.append(path),
                      root=self.machine())
        self.assertEqual(looked, [companion.ctl.APPLY_POWER])

    def test_a_machine_without_cpufreq_has_no_page(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        self.assertIsNone(self.status(empty))

    def test_the_profile_of_the_file_and_what_runs(self):
        said = self.status(self.machine(), {"CPU_GOVERNOR": "powersave",
                                            "CPU_EPP": "power"})
        self.assertEqual(said, {"profile": "powersave",
                                "offers": ["powersave", "balanced",
                                           "performance", "steamos"],
                                "governor": "powersave",
                                "epp": "balance_performance",
                                "driver": "amd-pstate-epp"})

    def test_no_setting_is_steamos_and_another_setting_is_custom(self):
        root = self.machine()
        self.assertEqual(self.status(root)["profile"], "steamos")
        self.assertEqual(self.status(root, {"CPU_GOVERNOR": "powersave",
                                            "CPU_EPP": "balance_power"})
                         ["profile"], "custom")

    def test_a_machine_without_a_preference_offers_less(self):
        root = self.machine(governors="ondemand performance powersave",
                            preferences="", running=("ondemand", ""))
        said = self.status(root)
        self.assertEqual(said["offers"], ["balanced", "performance",
                                          "steamos"])
        self.assertEqual(said["epp"], "")

    def test_a_word_of_the_kernel_is_cut_to_the_room_of_the_panel(self):
        root = self.machine(governors="performance " + "g" * 40,
                            running=("g" * 40, "balance_performance"))
        said = self.status(root)
        self.assertEqual(len(said["governor"]), companion.CPU_WORD)

    def change(self, request, root, refusal=None):
        wrote = []

        def write(updates):
            wrote.append(updates)
            if refusal:
                raise refusal

        return companion.cpu_change(request, write=write, root=root), wrote

    def test_each_profile_reaches_its_settings(self):
        root = self.machine()
        for name in companion.power.profiles(root):
            (code, _), wrote = self.change({"profile": name}, root)
            self.assertEqual((code, wrote),
                             (200, [companion.power.profile_settings(name,
                                                                     root)]),
                             name)
        self.assertEqual(self.change({"profile": "steamos"}, root)[1],
                         [{"CPU_GOVERNOR": ""}])

    def test_anything_else_reaches_nothing(self):
        root = self.machine(governors="ondemand performance powersave",
                            preferences="", running=("ondemand", ""))
        for request in (None, [], "balanced", {}, {"profile": "turbo"},
                        {"profile": "powersave"}, {"profile": "custom"},
                        {"profile": 3}, {"profile": "balanced", "epp": "x"},
                        {"CPU_GOVERNOR": "performance"}):
            (code, _), wrote = self.change(request, root)
            self.assertEqual((code, wrote), (400, []), request)

    def test_a_refusal_comes_back_as_its_own_code(self):
        root = self.machine()
        for refusal, wanted in (
                (companion.ctl.NotInstalled("no module"), 501),
                (companion.ctl.NotPermitted("no rule"), 403),
                (companion.ctl.CtlError("refused"), 502),
                (ValueError("not offered"), 502)):
            with mock.patch.object(companion.sys, "stderr"):
                (code, _), _ = self.change({"profile": "balanced"}, root,
                                           refusal)
            self.assertEqual(code, wanted, refusal)

    def test_a_second_change_during_the_first_waits_its_turn(self):
        root = self.machine()
        started, release = threading.Event(), threading.Event()
        answers = []

        def slow(updates):
            started.set()
            release.wait(5)

        first = threading.Thread(target=lambda: answers.append(
            companion.cpu_change({"profile": "balanced"}, write=slow,
                                 root=root)))
        first.start()
        self.assertTrue(started.wait(5))
        (code, _), wrote = self.change({"profile": "powersave"}, root)
        self.assertEqual((code, wrote), (409, []))
        # The LED bar has a lock of its own.
        self.assertEqual(companion.led_change({"desktop": "off"},
                                              write=lambda updates: None)[0],
                         200)
        release.set()
        first.join(5)
        self.assertEqual(answers[0][0], 200)


class LedTest(unittest.TestCase):
    """The two effects of the LED bar, as the status reports them."""

    def settings(self, text):
        """The path of a configuration file with that text, or of no file
        for None."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        path = os.path.join(root, "steamos-utility-center.conf")
        if text is not None:
            with open(path, "w") as handle:
                handle.write(text)
        return path

    def test_a_machine_without_the_led_module_has_no_effects(self):
        reader = companion.LedSettings(self.settings("DESKTOP_SCENE=fire\n"))
        self.assertIsNone(companion.led(reader, present=lambda path: False))

    def test_the_led_module_is_known_by_its_applier(self):
        looked = []
        reader = companion.LedSettings(self.settings(None))
        companion.led(reader, present=lambda path: looked.append(path))
        self.assertEqual(looked, [companion.ctl.APPLY_CONFIG])

    def test_the_two_effects_come_from_the_file(self):
        reader = companion.LedSettings(
            self.settings("DESKTOP_SCENE=fire\nRAINBOW_SHOWS=ooze\n"
                          "DESKTOP_COLOR=#ff8000\nDESKTOP_BRIGHTNESS=200\n"))
        self.assertEqual(companion.led(reader, present=lambda path: True),
                         {"desktop": "fire", "game": "ooze",
                          "desktop_color": "#ff8000",
                          "desktop_brightness": 200,
                          "mirror_profile": "pop",
                          "desktop_mirror_profile": "pop"})

    def test_the_profile_of_the_mirror_comes_from_the_file(self):
        reader = companion.LedSettings(self.settings(
            "RAINBOW_SHOWS=mirror\nMIRROR_PROFILE=cinematic\n"
            "DESKTOP_MIRROR_PROFILE=solid\n"))
        found = companion.led(reader, present=lambda path: True,
                              mirror=lambda: {"state": "idle"})
        # Each mode has its own.
        self.assertEqual(found["mirror_profile"], "cinematic")
        self.assertEqual(found["desktop_mirror_profile"], "solid")

    def test_the_mirror_says_what_it_does(self):
        """Only with the mirror in Game Mode: the panel shows it below that
        effect, and the status of each other effect stays small."""
        said = {"state": "running", "fps": 15.0, "cpu": 1.2}
        reader = companion.LedSettings(self.settings("RAINBOW_SHOWS=mirror\n"))
        found = companion.led(reader, present=lambda path: True,
                              mirror=lambda: said)
        self.assertEqual(found["game"], "mirror")
        self.assertEqual(found["mirror"], said)
        reader = companion.LedSettings(self.settings("RAINBOW_SHOWS=fire\n"))
        found = companion.led(reader, present=lambda path: True,
                              mirror=lambda: said)
        self.assertNotIn("mirror", found)

    def test_the_mirror_status_comes_from_the_runtime_directory(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        with open(os.path.join(root, screen.STATUS_NAME), "w") as handle:
            json.dump({"state": "busy", "detail": "steam",
                       "at": time.time()}, handle)
        reader = companion.LedSettings(self.settings("RAINBOW_SHOWS=mirror\n"))
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": root}):
            found = companion.led(reader, present=lambda path: True)
        self.assertEqual(found["mirror"], {"state": "busy", "detail": "steam"})

    def test_what_the_file_leaves_out_is_the_default(self):
        for text in ("LED_COUNT=17\n", None):
            reader = companion.LedSettings(self.settings(text))
            self.assertEqual(reader.read(),
                             {"desktop": "steam", "game": "rainbow",
                              "desktop_color": "#ffffff",
                              "desktop_brightness": 128,
                              "mirror_profile": screen.DEFAULT_PROFILE,
                              "desktop_mirror_profile":
                                  screen.DEFAULT_PROFILE},
                             text)

    def test_each_form_of_a_colour_comes_in_the_form_of_the_panel(self):
        """The file takes "#RRGGBB", "r,g,b" and the name of a kind of
        notification. The panel compares "#rrggbb" with its list."""
        for text, colour in (("#FF8000", "#ff8000"), ("ff8000", "#ff8000"),
                             ("255, 128, 0", "#ff8000"),
                             ("message", "#%02x%02x%02x"
                              % companion.notify.KINDS["message"])):
            reader = companion.LedSettings(
                self.settings("DESKTOP_COLOR=%s\n" % text))
            self.assertEqual(reader.read()["desktop_color"], colour, text)

    def test_a_file_that_the_service_refuses_has_no_effects(self):
        """The service does not start with such a file, so the bar shows
        none of its effects."""
        for text in ("DESKTOP_SCENE=plasma\n", "NOT_A_SETTING=1\n",
                     "no equals sign\n", "DESKTOP_COLOR=chartreuse\n",
                     "DESKTOP_BRIGHTNESS=300\n"):
            self.assertIsNone(
                companion.LedSettings(self.settings(text)).read(), text)

    def test_the_file_is_read_again_only_when_it_changes(self):
        """Each read of a file with a retired setting writes a warning,
        and the panel asks every three seconds."""
        path = self.settings("DESKTOP_SCENE=fire\n")
        reader = companion.LedSettings(path)
        with mock.patch.object(companion.config_module, "parse_file",
                               wraps=companion.config_module.parse_file) \
                as parsed:
            reader.read()
            reader.read()
            self.assertEqual(parsed.call_count, 1)
            with open(path, "w") as handle:
                handle.write("DESKTOP_SCENE=ooze\n")
            stamp = os.stat(path).st_mtime_ns + 1000000
            os.utime(path, ns=(stamp, stamp))
            self.assertEqual(reader.read()["desktop"], "ooze")
            self.assertEqual(parsed.call_count, 2)

    def test_a_caller_cannot_change_what_the_reader_keeps(self):
        reader = companion.LedSettings(self.settings("DESKTOP_SCENE=fire\n"))
        reader.read()["desktop"] = "off"
        self.assertEqual(reader.read()["desktop"], "fire")


class LedChangeTest(unittest.TestCase):
    """A change from the page of the LED bar."""

    def change(self, request, refusal=None):
        """The answer to one request, and what reached the applier."""
        wrote = []

        def write(updates):
            wrote.append(updates)
            if refusal:
                raise refusal

        return companion.led_change(request, write=write), wrote

    def test_each_choice_reaches_its_own_setting(self):
        (code, _), wrote = self.change({"desktop": "fire"})
        self.assertEqual((code, wrote), (200, [{"DESKTOP_SCENE": "fire"}]))
        (code, _), wrote = self.change({"game": "ooze"})
        self.assertEqual((code, wrote), (200, [{"RAINBOW_SHOWS": "ooze"}]))
        (code, _), wrote = self.change({"desktop": "off", "game": "load"})
        self.assertEqual(wrote, [{"DESKTOP_SCENE": "off",
                                  "RAINBOW_SHOWS": "load"}])

    def test_each_profile_of_the_mirror_can_be_chosen(self):
        for key, name in (("mirror_profile", "MIRROR_PROFILE"),
                          ("desktop_mirror_profile", "DESKTOP_MIRROR_PROFILE")):
            for profile in screen.PROFILES:
                (code, _), wrote = self.change({key: profile})
                self.assertEqual((code, wrote), (200, [{name: profile}]),
                                 profile)
            (code, _), wrote = self.change({key: "disco"})
            self.assertEqual((code, wrote), (400, []))
            self.assertEqual(companion.LED_MIRROR[key], (name, screen.PROFILES))

    def test_every_effect_of_the_service_can_be_chosen(self):
        for key, (name, allowed) in companion.LED_CHOICES.items():
            for value in allowed:
                (code, _), wrote = self.change({key: value})
                self.assertEqual((code, wrote), (200, [{name: value}]),
                                 (key, value))

    def test_the_lists_are_the_lists_of_the_service(self):
        self.assertEqual(
            companion.LED_CHOICES,
            {"desktop": ("DESKTOP_SCENE",
                         companion.config_module.DESKTOP_SCENES),
             "game": ("RAINBOW_SHOWS",
                      companion.config_module.RAINBOW_CHOICES)})

    def test_each_colour_and_brightness_reaches_its_setting(self):
        for colour in companion.LED_COLOURS:
            (code, _), wrote = self.change({"desktop_color": colour})
            self.assertEqual((code, wrote),
                             (200, [{"DESKTOP_COLOR": colour}]), colour)
        for level in (0, 1, 128, 255):
            (code, _), wrote = self.change({"desktop_brightness": level})
            self.assertEqual((code, wrote),
                             (200, [{"DESKTOP_BRIGHTNESS": level}]), level)
        (code, _), wrote = self.change({"desktop": "breath",
                                        "desktop_color": "#00ffff",
                                        "desktop_brightness": 64})
        self.assertEqual(wrote, [{"DESKTOP_SCENE": "breath",
                                  "DESKTOP_COLOR": "#00ffff",
                                  "DESKTOP_BRIGHTNESS": 64}])

    def test_the_colours_are_the_colours_of_the_control_panel(self):
        """The panel offers what the control panel offers for the desktop
        colour, and the service takes those and no other."""
        self.assertEqual(
            companion.LED_COLOURS,
            tuple(value for _, value in ledpanel.NOTIFICATION_COLOURS))

    def test_the_service_takes_each_colour_and_each_limit(self):
        """A change that passes here and fails in the LED service is a
        refusal on the panel for a choice the panel offered."""
        values = dict(companion.config_module.DEFAULTS)
        for colour in companion.LED_COLOURS:
            companion.config_module.validate(
                dict(values, DESKTOP_COLOR=colour))
        low, high = companion.LED_BRIGHTNESS
        for level in (low, high):
            companion.config_module.validate(
                dict(values, DESKTOP_BRIGHTNESS=level))
        for level in (low - 1, high + 1):
            with self.assertRaises(companion.config_module.ConfigError):
                companion.config_module.validate(
                    dict(values, DESKTOP_BRIGHTNESS=level))

    def test_anything_else_reaches_nothing(self):
        for request in (None, [], "fire", {}, {"desktop": "plasma"},
                        {"game": "off"}, {"desktop": 3},
                        {"desktop": ["fire"]}, {"DESKTOP_SCENE": "fire"},
                        {"desktop": "fire", "LED_COUNT": 1},
                        {"desktop": "fire", "game": "steam"},
                        {"desktop_color": "#123456"},
                        {"desktop_color": "#FF0000"},
                        {"desktop_color": "red"}, {"desktop_color": 0xff0000},
                        {"desktop_color": ["#ff0000"]},
                        {"desktop_brightness": -1},
                        {"desktop_brightness": 256},
                        {"desktop_brightness": True},
                        {"desktop_brightness": 12.5},
                        {"desktop_brightness": "128"},
                        {"DESKTOP_COLOR": "#ff0000"},
                        {"desktop_color": "#ff0000", "desktop": "plasma"},
                        {"desktop": "fire", "desktop_brightness": 300}):
            (code, _), wrote = self.change(request)
            self.assertEqual((code, wrote), (400, []), request)

    def test_a_refusal_comes_back_as_its_own_code(self):
        for refusal, wanted in (
                (companion.ctl.NotInstalled("no module"), 501),
                (companion.ctl.NotPermitted("no rule"), 403),
                (companion.ctl.CtlError("the service said no"), 502),
                (companion.config_module.ConfigError("bad file"), 502)):
            with mock.patch.object(companion.sys, "stderr"):
                (code, _), _ = self.change({"desktop": "fire"}, refusal)
            self.assertEqual(code, wanted, refusal)

    def test_a_second_change_during_the_first_waits_its_turn(self):
        """Each change starts the service again. The panel sends the second
        one again after the answer to the first."""
        started, release = threading.Event(), threading.Event()
        answers = []

        def slow(updates):
            started.set()
            release.wait(5)

        first = threading.Thread(target=lambda: answers.append(
            companion.led_change({"desktop": "fire"}, write=slow)))
        first.start()
        self.assertTrue(started.wait(5))
        (code, _), wrote = self.change({"desktop": "off"})
        self.assertEqual((code, wrote), (409, []))
        release.set()
        first.join(5)
        self.assertEqual(answers[0][0], 200)
        (code, _), wrote = self.change({"desktop": "off"})
        self.assertEqual(code, 200)

    def test_the_lock_is_free_again_after_a_refusal(self):
        with mock.patch.object(companion.sys, "stderr"):
            self.change({"desktop": "fire"}, companion.ctl.CtlError("no"))
        (code, _), _ = self.change({"desktop": "fire"})
        self.assertEqual(code, 200)


def _net(self, cards, routes=()):
    """A /sys/class/net holding the cards given, and a /proc/net/route.

    Each card is (name, kind, mac, carrier). kind is "wired", "wireless" or
    "virtual", and it decides which files are there rather than being read
    anywhere: that is the whole point of the reader.
    """
    root = tempfile.mkdtemp()
    self.addCleanup(shutil.rmtree, root, ignore_errors=True)
    for name, kind, mac, carrier in cards:
        where = os.path.join(root, name)
        os.makedirs(where)
        with open(os.path.join(where, "address"), "w") as handle:
            handle.write(mac + "\n")
        with open(os.path.join(where, "carrier"), "w") as handle:
            handle.write("%d\n" % carrier)
        with open(os.path.join(where, "type"), "w") as handle:
            handle.write("772\n" if name == "lo" else "1\n")
        if kind != "virtual":
            os.makedirs(os.path.join(where, "device"))
        if kind == "wireless":
            os.makedirs(os.path.join(where, "wireless"))
    table = os.path.join(root, "route")
    with open(table, "w") as handle:
        handle.write("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\t"
                     "Metric\tMask\n")
        for name, metric in routes:
            handle.write("%s\t00000000\t0102000A\t0003\t0\t0\t%d\t"
                         "00000000\n" % (name, metric))
    return root, table


class WakeTargetTest(unittest.TestCase):
    """The card a magic packet has to name.

    Wake on LAN is a thing wired cards do. Everything here is about not
    naming the wrong one, because a packet sent to a radio that sleeps wakes
    nothing and leaves no trace of why.
    """

    def test_it_finds_the_one_wired_card(self):
        root, table = _net(self, [("eth0", "wired", "a4:bb:6d:1f:0e:27", 1)])
        self.assertEqual(companion.wake_target(root, table),
                         {"interface": "eth0", "mac": "a4:bb:6d:1f:0e:27"})

    def test_a_radio_is_not_a_wake_target(self):
        root, table = _net(self, [("wlan0", "wireless", "aa:bb:cc:dd:ee:ff", 1)])
        self.assertIsNone(companion.wake_target(root, table))

    def test_a_virtual_card_is_not_one_either(self):
        """A bridge, a veth or a tunnel has no hardware behind it."""
        root, table = _net(self, [("docker0", "virtual", "02:42:aa:bb:cc:dd", 1),
                                  ("lo", "virtual", "00:00:00:00:00:00", 1)])
        self.assertIsNone(companion.wake_target(root, table))

    def test_the_radio_carrying_the_route_does_not_win(self):
        """The case this exists for.

        A machine with a cable and a radio routes over whichever it prefers,
        and that is often the radio. Reading the default route on its own
        gives the wrong card, and the packet goes nowhere.
        """
        root, table = _net(self,
                           [("eth0", "wired", "a4:bb:6d:1f:0e:27", 1),
                            ("wlan0", "wireless", "aa:bb:cc:dd:ee:ff", 1)],
                           routes=[("wlan0", 600)])
        found = companion.wake_target(root, table)
        self.assertEqual(found["interface"], "eth0")

    def test_of_two_wired_cards_the_routing_one_wins(self):
        root, table = _net(self,
                           [("eth0", "wired", "a4:bb:6d:1f:0e:27", 1),
                            ("eth1", "wired", "b8:27:eb:00:11:22", 1)],
                           routes=[("eth1", 100)])
        self.assertEqual(companion.wake_target(root, table)["interface"], "eth1")

    def test_a_cable_beats_an_empty_socket_when_neither_routes(self):
        root, table = _net(self,
                           [("eth0", "wired", "a4:bb:6d:1f:0e:27", 0),
                            ("eth1", "wired", "b8:27:eb:00:11:22", 1)])
        self.assertEqual(companion.wake_target(root, table)["interface"], "eth1")

    def test_the_lowest_metric_is_the_default_route(self):
        root, table = _net(self,
                           [("eth0", "wired", "a4:bb:6d:1f:0e:27", 1),
                            ("eth1", "wired", "b8:27:eb:00:11:22", 1)],
                           routes=[("eth0", 900), ("eth1", 50)])
        self.assertEqual(companion.wake_target(root, table)["interface"], "eth1")

    def test_an_address_of_nothing_is_no_answer(self):
        """What a card reports before it is ready. A packet naming it wakes
        nothing, and an empty field on the panel is the honest answer."""
        root, table = _net(self, [("eth0", "wired", "00:00:00:00:00:00", 1)])
        self.assertIsNone(companion.wake_target(root, table))

    def test_a_scrambled_address_is_no_answer(self):
        root, table = _net(self, [("eth0", "wired", "not an address", 1)])
        self.assertIsNone(companion.wake_target(root, table))

    def test_a_machine_with_no_cards_answers_nothing(self):
        root, table = _net(self, [])
        self.assertIsNone(companion.wake_target(root, table))

    def test_a_missing_directory_is_not_an_error(self):
        """This fills a field on a screen. It does not stop the service."""
        self.assertIsNone(companion.wake_target("/no/such/place",
                                                "/no/such/route"))

    def test_the_status_carries_it(self):
        """The panel learns the address from an ordinary status answer, so
        it has one when the PC is off and cannot be asked."""
        self.assertIn("wake", companion.status())


class NonceTest(unittest.TestCase):
    def test_one_spend_for_each(self):
        room = companion.Nonces()
        value = room.issue()
        self.assertTrue(room.spend(value))
        self.assertFalse(room.spend(value))

    def test_one_that_nobody_gave_out_is_refused(self):
        self.assertFalse(companion.Nonces().spend("made up"))

    def test_the_room_is_bounded_and_the_oldest_leaves(self):
        """A stranger asks for as many as they like, and memory is not a
        thing to hand to a stranger."""
        room = companion.Nonces(room=4)
        first = room.issue()
        for _ in range(4):
            room.issue()
        self.assertFalse(room.spend(first))
        self.assertLessEqual(len(room._open), 4)

    def test_two_are_never_the_same(self):
        room = companion.Nonces(room=500)
        values = {room.issue() for _ in range(400)}
        self.assertEqual(len(values), 400)


class PairServiceTest(unittest.TestCase):
    """A new panel pairs over HTTP, and its new secret then signs."""

    PANEL = bytes(range(1, 33))
    PC = bytes(range(101, 133))

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "config", "companion-token")
        self.secret = companion.Secret(TOKEN, self.path)
        self.nonces = companion.Nonces()
        self.pair = companion.pairing.Pairing(
            folder=self.folder, random=lambda size: self.PC, name="deck")
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            companion.make_handler(self.secret, self.nonces, pair=self.pair))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.conn = HTTPConnection("127.0.0.1", httpd.server_port)
        self.addCleanup(self.conn.close)

    def send(self, method, path, body=b"", headers=None):
        self.conn.request(method, path, body, headers or {})
        answer = self.conn.getresponse()
        return answer.status, json.loads(answer.read() or b"null")

    def signed(self, token, path="/v1/status"):
        nonce = self.nonces.issue()
        return self.send("GET", path, headers={
            companion.NONCE_HEADER: nonce,
            companion.AUTH_HEADER: companion.signature(token, "GET", path,
                                                       nonce, b"")})[0]

    def ask(self):
        key = companion.pairing.public_key(self.PANEL).hex()
        return self.send("POST", companion.PAIR_PATH, json.dumps(
            {"name": "SteamOS-Panel-A1B2", "key": key}).encode(),
            {"Content-Type": "application/json"})

    def expected(self):
        panel_key = companion.pairing.public_key(self.PANEL)
        pc_key = companion.pairing.public_key(self.PC)
        shared = companion.pairing.shared_secret(self.PANEL, pc_key)
        return companion.pairing.derive(shared, panel_key, pc_key)

    def test_a_panel_pairs_and_its_new_secret_signs(self):
        code, said = self.ask()
        self.assertEqual(code, 200)
        self.assertEqual(said["key"],
                         companion.pairing.public_key(self.PC).hex())
        path = "%s/%s" % (companion.PAIR_PATH, said["id"])
        self.assertEqual(self.send("GET", path), (200, {"state": "waiting"}))
        companion.pairing.answer(said["id"], True, folder=self.folder)
        self.assertEqual(self.send("GET", path), (200, {"state": "accepted"}))
        new, _code = self.expected()
        with open(self.path) as handle:
            self.assertEqual(handle.read().strip(), new)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(self.signed(new), 200)
        self.assertEqual(self.signed(TOKEN), 401)

    def test_a_refusal_keeps_the_old_secret(self):
        _, said = self.ask()
        companion.pairing.answer(said["id"], False, folder=self.folder)
        self.assertEqual(
            self.send("GET", "%s/%s" % (companion.PAIR_PATH, said["id"])),
            (200, {"state": "refused"}))
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.signed(TOKEN), 200)

    def test_only_the_paths_of_the_pairing_need_no_signature(self):
        self.assertEqual(self.send("GET", "/v1/status")[0], 401)
        self.assertEqual(self.send("GET", companion.PAIR_PATH + "/x")[0], 401)
        self.assertEqual(
            self.send("GET", companion.PAIR_PATH + "/" + "0" * 16)[0], 404)

    def test_a_bad_request_to_pair_is_refused(self):
        for body in (b"{", b"[]", json.dumps({"key": "00"}).encode()):
            self.assertEqual(self.send("POST", companion.PAIR_PATH, body)[0],
                             400, body)
        self.assertEqual(self.send("POST", companion.PAIR_PATH,
                                   b"x" * (companion.BODY_LIMIT + 1))[0], 400)

    def test_a_service_with_no_token_refuses_each_signature(self):
        """An HMAC with an empty key is still an HMAC. A panel that knows
        that the PC has no secret yet must not get in with one."""
        empty = companion.make_handler("", self.nonces, pair=self.pair)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), empty)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.conn = HTTPConnection("127.0.0.1", httpd.server_port)
        self.assertEqual(self.signed(""), 401)


class TokenTest(unittest.TestCase):
    def test_a_missing_file_gives_a_sentence_and_not_a_traceback(self):
        """And the service runs: a pairing writes the file."""
        with mock.patch.object(companion.sys, "stderr") as said:
            self.assertEqual(companion.read_token("/does/not/exist"), "")
        self.assertIn("Pair a panel", "".join(
            str(call.args[0]) for call in said.write.call_args_list))

    def test_a_short_token_is_refused(self):
        with tempfile.NamedTemporaryFile("w", suffix=".token",
                                         delete=False) as handle:
            handle.write("short\n")
        self.addCleanup(os.unlink, handle.name)
        with self.assertRaises(SystemExit):
            companion.read_token(handle.name)

    def test_the_token_lives_in_the_home_directory(self):
        """Not in /etc. It belongs to one person and one panel, it needs no
        root to read, and a SteamOS update leaves a home directory alone."""
        self.assertTrue(companion.token_path("/home/deck").startswith(
            "/home/deck/.config/"))


class FirmwareImageTest(unittest.TestCase):
    """The image in the repository, against the firmware beside it.

    Build output in a repository is a thing to be careful with, and this is
    the care: CI writes the fingerprint of the source it built from, and the
    page refuses an image whose fingerprint does not match. Without the
    check, an update that changed the firmware and a flash from the old
    image give a board that talks to a service it does not match, and a wall
    that says "no PC" with nothing to explain it.
    """

    def tree(self):
        """A machine with a firmware source in it, and nothing else."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        where = os.path.join(root, companion.FIRMWARE_DIR)
        os.makedirs(os.path.join(where, "main"))
        for name in ("CMakeLists.txt", "partitions.csv",
                     "sdkconfig.defaults", "dependencies.lock"):
            with open(os.path.join(where, name), "w") as handle:
                handle.write(name + "\n")
        with open(os.path.join(where, "main", "main.c"), "w") as handle:
            handle.write("int main(void){return 0;}\n")
        return root

    def image(self, root, where, stamp=None):
        place = os.path.join(root, where)
        for part in companion.IMAGE_PARTS:
            path = os.path.join(place, part)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"\x00")
        if stamp is not None:
            with open(os.path.join(place, companion.STAMP_NAME), "w") as h:
                h.write(stamp + "\n")
        return place

    def test_the_same_source_gives_the_same_fingerprint(self):
        root = self.tree()
        self.assertEqual(companion.firmware_fingerprint(root),
                         companion.firmware_fingerprint(root))

    def test_a_changed_source_file_changes_it(self):
        root = self.tree()
        before = companion.firmware_fingerprint(root)
        path = os.path.join(root, companion.FIRMWARE_DIR, "main", "main.c")
        with open(path, "a") as handle:
            handle.write("// one more line\n")
        self.assertNotEqual(companion.firmware_fingerprint(root), before)

    def test_a_file_that_moves_changes_it(self):
        """The path is in the hash beside the bytes. Without it, a rename
        gives the same answer as no change at all."""
        root = self.tree()
        before = companion.firmware_fingerprint(root)
        main = os.path.join(root, companion.FIRMWARE_DIR, "main")
        os.rename(os.path.join(main, "main.c"),
                  os.path.join(main, "start.c"))
        self.assertNotEqual(companion.firmware_fingerprint(root), before)

    def test_a_note_beside_the_firmware_does_not_change_it(self):
        """A licence or a README is not a reason to build again."""
        root = self.tree()
        before = companion.firmware_fingerprint(root)
        with open(os.path.join(root, companion.FIRMWARE_DIR, "NOTES.md"),
                  "w") as handle:
            handle.write("# notes\n")
        self.assertEqual(companion.firmware_fingerprint(root), before)

    def test_an_image_is_all_four_parts_or_none(self):
        root = self.tree()
        place = self.image(root, companion.PREBUILT_DIR)
        self.assertTrue(companion.image_is_complete(place))
        os.unlink(os.path.join(place, "steamos_companion.bin"))
        self.assertFalse(companion.image_is_complete(place),
                         "a build that stopped is not an image")

    def test_a_missing_stamp_reads_as_no_stamp(self):
        root = self.tree()
        place = self.image(root, companion.PREBUILT_DIR)
        self.assertEqual(companion.image_stamp(place), "")
        self.assertEqual(companion.image_stamp("/does/not/exist"), "")

    def test_the_stamp_the_job_writes_is_the_one_the_page_reads(self):
        """The whole chain, with the fingerprint in the middle."""
        root = self.tree()
        place = self.image(root, companion.PREBUILT_DIR,
                           stamp=companion.firmware_fingerprint(root))
        self.assertEqual(companion.image_stamp(place),
                         companion.firmware_fingerprint(root))


class WorkflowTest(unittest.TestCase):
    """The job that builds the image, read rather than run.

    Nothing here can run GitHub Actions, so this holds the two facts that a
    reader of the file cannot check for themselves: it builds at the version
    the lock names, and it writes the stamp with the same function the page
    reads.
    """

    def source(self):
        with open(os.path.join(
                REPO, ".github", "workflows",
                "companion-firmware.yml")) as handle:
            return handle.read()

    def locked_version(self):
        with open(os.path.join(REPO, companion.FIRMWARE_DIR,
                               "dependencies.lock")) as handle:
            lines = handle.read().splitlines()
        for index, line in enumerate(lines):
            if line.strip() == "idf:":
                for after in lines[index:index + 5]:
                    if after.strip().startswith("version:"):
                        return after.split(":", 1)[1].strip()
        raise AssertionError("dependencies.lock names no idf version")

    def test_it_builds_at_the_version_the_lock_names(self):
        """A container of another version is a build nobody measured."""
        self.assertIn("espressif/idf:v%s" % self.locked_version(),
                      self.source())

    def test_it_writes_the_stamp_with_the_function_the_page_reads(self):
        text = self.source()
        self.assertIn("firmware_fingerprint", text)
        self.assertIn(companion.STAMP_NAME, text)

    def test_it_does_not_start_itself_again(self):
        """It commits under firmware/companion, which is what starts it."""
        self.assertIn("'!firmware/companion/prebuilt/**'", self.source())


class OneSensorReaderTest(unittest.TestCase):
    """This module reads no hwmon file of its own.

    It came from a separate project that walked /sys/class/hwmon itself.
    Two readers become two answers on the day one of them learns about a new
    chip, and the LED bar and the panel then disagree about the temperature
    of the same machine. So the reads go through temperature.py, and this
    test refuses a second reader.
    """

    def tree(self):
        path = os.path.join(REPO, "server", "steamos_utility_center",
                            "companion.py")
        with open(path) as handle:
            return ast.parse(handle.read())

    def written(self, tree):
        """Every string in the code, and none of the ones in the prose.

        The first version of this read the docstrings too, and the paragraph
        that explains why the reads belong to temperature.py failed the test
        that asks for it. A rule about code that a comment can break is not
        a rule about code.
        """
        prose = set()
        holders = (ast.Module, ast.ClassDef, ast.FunctionDef,
                   ast.AsyncFunctionDef)
        for node in ast.walk(tree):
            if not isinstance(node, holders) or not node.body:
                continue
            first = node.body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                prose.add(id(first.value))
        return [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str) and id(node) not in prose]

    def test_it_names_no_hwmon_path_of_its_own(self):
        said = [one for one in self.written(self.tree()) if "hwmon" in one]
        self.assertEqual(said, [], "the hwmon path belongs to temperature.py")

    def test_that_rule_reads_the_code_and_not_the_prose(self):
        """Or the test above passes by deleting a paragraph."""
        tree = ast.parse('"""A hwmon docstring."""\nX = "/sys/class/hwmon"\n')
        self.assertEqual(self.written(tree), ["/sys/class/hwmon"])

    def test_it_does_not_divide_a_reading_by_a_thousand(self):
        """That conversion is read_celsius. A copy of it here is the second
        reader arriving one number at a time."""
        found = [node.value for node in ast.walk(self.tree())
                 if isinstance(node, ast.Constant)
                 and node.value in (1000, 1000.0)]
        self.assertEqual(found, [])

    def test_the_sensors_come_from_the_module_that_ranks_them(self):
        names = {node.attr for node in ast.walk(self.tree())
                 if isinstance(node, ast.Attribute)
                 and isinstance(node.value, ast.Name)
                 and node.value.id == "temperature"}
        for wanted in ("find_sensors", "pick_sensor", "read_celsius"):
            self.assertIn(wanted, names)


if __name__ == "__main__":
    unittest.main()
