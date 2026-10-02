# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the page of the PC on the panel shows, read from files in a folder.

Each test writes the files the kernel and SteamOS keep, in the shape the
board's machine has them, and reads them back through pcinfo.py.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import companion, pcinfo, temperature  # noqa: E402

OS_RELEASE = '''NAME="SteamOS"
PRETTY_NAME="SteamOS"
VERSION_CODENAME=holo
ID=steamos
ID_LIKE=arch
VARIANT_ID=steamdeck
VERSION_ID=3.9.2
BUILD_ID=20260925.100
'''

PCI_IDS = '''# a comment
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t7550  Navi 48 [Radeon RX 9070/9070 XT/9070 GRE]
\t\t1da2 e490  Sapphire Pulse Radeon RX 9070 XT
\t7551  Navi 48 GL
10de  NVIDIA Corporation
\t2684  AD102 [GeForce RTX 4090]
'''


# libdrm's list, in its own shape: a version line, then device, revision and
# name, split by a comma and a tab.
AMDGPU_IDS = """# List of AMDGPU IDs
#
# Syntax:
# device_id,\trevision_id,\tproduct_name        <-- single tab after comma

1.0.0
7550,\tC0,\tAMD Radeon RX 9070 XT
7550,\tC3,\tAMD Radeon RX 9070
"""


class Folder(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        pcinfo.system.cache_clear()
        pcinfo.cpu_model.cache_clear()
        pcinfo.gpu_model.cache_clear()
        self.addCleanup(pcinfo.system.cache_clear)
        self.addCleanup(pcinfo.cpu_model.cache_clear)
        self.addCleanup(pcinfo.gpu_model.cache_clear)

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
        return path


class SystemTest(Folder):
    def test_steamos_its_version_and_its_build(self):
        path = self.write("os-release", OS_RELEASE)
        with mock.patch.object(pcinfo, "channel", return_value="Beta"):
            found = pcinfo.system(path)
        self.assertEqual(found["os"], "SteamOS 3.9.2")
        self.assertEqual(found["build"], "20260925.100")
        self.assertEqual(found["channel"], "Beta")
        self.assertEqual(found["kernel"],
                         pcinfo.short_kernel(os.uname().release)[:47])

    def test_the_kernel_is_its_version_and_not_its_build(self):
        """The board showed 7.2.7-valve1-1-neptune-72-gc8730d37f9c6, which
        ended in dots. The parts after the version are the build."""
        for release, short in (
                ("7.2.7-valve1-1-neptune-72-gc8730d37f9c6", "7.2.7-valve1-1"),
                ("6.8.0-45-generic", "6.8.0-45"),
                ("6.10.3-arch1-2", "6.10.3-arch1-2"),
                ("6.12.0-rc1", "6.12.0-rc1"),
                ("6.18.44-fc-v51", "6.18.44"),
                ("no number", "no number")):
            self.assertEqual(pcinfo.short_kernel(release), short, release)

    def test_a_system_with_no_build_says_none(self):
        path = self.write("os-release", 'NAME="Ubuntu"\nVERSION_ID="24.04"\n')
        with mock.patch.object(pcinfo, "channel", return_value=None):
            found = pcinfo.system(path)
        self.assertEqual((found["os"], found["build"]), ("Ubuntu 24.04", None))

    def test_the_branch_becomes_the_word_of_the_menu(self):
        for printed, shown in (("rel\n", "Stable"), ("beta\n", "Beta"),
                               ("preview\n", "Preview"), ("main\n", "Main"),
                               ("rc\n", "RC"), ("", None)):
            done = mock.Mock(stdout=printed)
            with mock.patch.object(pcinfo.subprocess, "run",
                                   return_value=done):
                self.assertEqual(pcinfo.channel(), shown, printed)

    def test_no_steamos_select_branch_is_no_channel(self):
        with mock.patch.object(pcinfo.subprocess, "run",
                               side_effect=FileNotFoundError):
            self.assertIsNone(pcinfo.channel())

    def test_the_uptime_in_whole_seconds(self):
        path = self.write("uptime", "187981.62 2948374.11\n")
        self.assertEqual(pcinfo.uptime(path), 187981)
        self.assertIsNone(pcinfo.uptime(self.write("empty", "")))


class HardwareTest(Folder):
    def test_the_processor_without_its_noise(self):
        for said, name in (
                ("AMD Ryzen 7 9800X3D 8-Core Processor", "AMD Ryzen 7 9800X3D"),
                ("Intel(R) Core(TM) i7-14700K", "Intel Core i7-14700K"),
                ("AMD Ryzen 7 7840HS w/ Radeon 780M Graphics",
                 "AMD Ryzen 7 7840HS")):
            pcinfo.cpu_model.cache_clear()
            path = self.write("cpuinfo", "processor\t: 0\nmodel name\t: %s\n"
                              % said)
            self.assertEqual(pcinfo.cpu_model(path), name)

    def test_the_load_between_two_answers(self):
        path = self.write("stat", "cpu  100 0 100 800 0 0 0 0 0 0\n")
        load = pcinfo.CpuLoad(path)
        self.assertIsNone(load.percent(), "one reading says nothing")
        self.write("stat", "cpu  150 0 150 900 0 0 0 0 0 0\n")
        self.assertEqual(load.percent(), 50)

    def test_waiting_for_a_disk_is_not_load(self):
        path = self.write("stat", "cpu  0 0 0 0 0 0 0 0 0 0\n")
        load = pcinfo.CpuLoad(path)
        load.percent()
        self.write("stat", "cpu  10 0 0 40 50 0 0 0 0 0\n")
        self.assertEqual(load.percent(), 10)

    def test_memory_is_what_mem_available_leaves(self):
        path = self.write("meminfo", "MemTotal:       32768000 kB\n"
                          "MemFree:         1000000 kB\n"
                          "MemAvailable:   22768000 kB\n")
        self.assertEqual(pcinfo.memory(path),
                         {"used": 10000000 * 1024, "total": 32768000 * 1024})
        self.assertIsNone(pcinfo.memory(self.write("none", "")))

    def card(self, vendor, device, revision="0xc0", sub_vendor="0x1da2",
             sub_device="0x3490"):
        """The board's card: a Sapphire Pure RX 9070 XT, as LACT showed."""
        card = os.path.join(self.root, "card")
        for leaf, value in (("vendor", vendor), ("device", device),
                            ("revision", revision),
                            ("subsystem_vendor", sub_vendor),
                            ("subsystem_device", sub_device)):
            self.write(os.path.join("card", leaf), value + "\n")
        return card

    def lists(self):
        return ((self.write("pci.ids", PCI_IDS),),
                (self.write("amdgpu.ids", AMDGPU_IDS),))

    def test_the_model_of_libdrm_by_its_revision(self):
        """What LACT showed: AMD Radeon RX 9070 XT, for 0x1002:0x7550:0xC0.
        The model and not the board, which was asked for."""
        pci, amd = self.lists()
        self.assertEqual(pcinfo.gpu_model(self.card("0x1002", "0x7550"),
                                          pci, amd), "AMD Radeon RX 9070 XT")
        pcinfo.gpu_model.cache_clear()
        self.assertEqual(pcinfo.gpu_model(
            self.card("0x1002", "0x7550", "0xc3"), pci, amd),
            "AMD Radeon RX 9070")

    def test_a_revision_libdrm_does_not_know_takes_the_brackets(self):
        pci, amd = self.lists()
        self.assertEqual(pcinfo.gpu_model(
            self.card("0x1002", "0x7550", "0xc9"), pci, amd),
            "Radeon RX 9070/9070 XT/9070 GRE")

    def test_a_chip_with_no_brackets_keeps_its_name(self):
        pci, amd = self.lists()
        self.assertEqual(pcinfo.gpu_model(self.card("0x1002", "0x7551"),
                                          pci, amd), "Navi 48 GL")

    def test_a_card_of_another_vendor_has_the_list_of_pci_names(self):
        """libdrm's list is AMD's alone, so 7550 of NVIDIA is not in it."""
        pci, amd = self.lists()
        self.assertEqual(pcinfo.gpu_model(self.card("0x10de", "0x2684"),
                                          pci, amd), "GeForce RTX 4090")
        pcinfo.gpu_model.cache_clear()
        self.assertIsNone(pcinfo.gpu_model(self.card("0x10de", "0x7550"),
                                           pci, amd))

    def test_no_card_and_no_list_are_none(self):
        self.assertIsNone(pcinfo.gpu_model(None))
        nowhere = (os.path.join(self.root, "x"),)
        self.assertIsNone(pcinfo.gpu_model(self.card("0x1002", "0x7550"),
                                           nowhere, nowhere))


class NetworkTest(Folder):
    def interface(self, name, address, wireless=False, speed="1000"):
        self.write(os.path.join("net", name, "address"), address + "\n")
        self.write(os.path.join("net", name, "speed"), speed + "\n")
        if wireless:
            os.makedirs(os.path.join(self.root, "net", name, "wireless"))

    def test_the_card_that_holds_the_address_of_the_answer(self):
        self.interface("enp5s0", "a8:a1:59:3c:21:7e", speed="2500")
        self.interface("wlan0", "40:ec:99:00:11:22", wireless=True, speed="")
        addresses = {"enp5s0": "192.168.178.42", "wlan0": "192.168.178.43"}
        found = pcinfo.network("192.168.178.42",
                               os.path.join(self.root, "net"), addresses.get)
        self.assertEqual(found, {"ip": "192.168.178.42", "kind": "wired",
                                 "speed": 2500, "mac": "a8:a1:59:3c:21:7e"})
        found = pcinfo.network("192.168.178.43",
                               os.path.join(self.root, "net"), addresses.get)
        self.assertEqual((found["kind"], found["speed"]), ("wireless", None))

    def test_a_card_with_no_cable_has_no_speed(self):
        self.interface("enp5s0", "a8:a1:59:3c:21:7e", speed="-1")
        found = pcinfo.network("10.0.0.2", os.path.join(self.root, "net"),
                               {"enp5s0": "10.0.0.2"}.get)
        self.assertIsNone(found["speed"])

    def test_an_address_no_card_holds_keeps_only_the_address(self):
        self.interface("enp5s0", "a8:a1:59:3c:21:7e")
        found = pcinfo.network("10.0.0.9", os.path.join(self.root, "net"),
                               {"enp5s0": "10.0.0.2"}.get)
        self.assertEqual(found, {"ip": "10.0.0.9", "kind": None,
                                 "speed": None, "mac": None})


class FanTest(unittest.TestCase):
    """The fans, through temperature.py and nothing else."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def chip(self, index, name, files):
        place = os.path.join(self.root, "hwmon%d" % index)
        for leaf, value in dict(files, name=name).items():
            path = os.path.join(place, leaf)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(str(value) + "\n")

    def test_the_card_and_the_rest_apart(self):
        self.chip(0, "k10temp", {"temp1_input": 49000})
        self.chip(1, "nct6799", {"fan1_input": 820, "fan2_input": 1180,
                                 "fan3_input": 0})
        self.chip(2, "amdgpu", {"temp1_input": 56000, "fan1_input": 0,
                                "device/mem_info_vram_total": 16384})
        self.assertEqual(companion.fans(self.root),
                         {"fan": 1180, "gpu_fan": 0})

    def test_a_second_graphics_chip_is_not_a_fan_of_the_board(self):
        """A machine with two cards: the one with less memory is not the
        card of the page, and its fan is no fan of the board either."""
        self.chip(0, "amdgpu", {"temp1_input": 56000, "fan1_input": 1500,
                                "device/mem_info_vram_total": 16384})
        self.chip(1, "amdgpu", {"temp1_input": 40000, "fan1_input": 900,
                                "device/mem_info_vram_total": 512})
        self.assertEqual(companion.fans(self.root),
                         {"fan": None, "gpu_fan": 1500})

    def test_a_board_with_no_fan_driver_says_none(self):
        self.chip(0, "k10temp", {"temp1_input": 49000})
        self.assertEqual(companion.fans(self.root),
                         {"fan": None, "gpu_fan": None})

    def test_a_reading_that_is_not_a_number_is_left_out(self):
        self.chip(0, "nct6799", {"fan1_input": "x", "fan2_input": 900})
        self.assertEqual([one["rpm"] for one in
                          temperature.find_fans(self.root)], [900])


class StatusTest(unittest.TestCase):
    def test_the_answer_carries_the_page_of_the_pc(self):
        page = companion.status("127.0.0.1")["pc"]
        for key in ("os", "build", "channel", "kernel", "uptime", "cpu",
                    "cpu_load", "gpu", "memory", "fan", "gpu_fan",
                    "network"):
            self.assertIn(key, page)
        self.assertEqual(page["network"]["ip"], "127.0.0.1")

    def test_the_handler_gives_the_address_the_panel_reached(self):
        source = open(os.path.join(REPO, "server", "steamos_utility_center",
                                   "companion.py")).read()
        self.assertIn("status(self.connection.getsockname()[0])", source)


if __name__ == "__main__":
    unittest.main()
