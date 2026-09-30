# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The battery of the panel, read off its power chip.

The 4B carries an AXP2101, and nothing in the board support speaks to it.
firmware/companion/main/panel_battery.c does, and none of this can run
here: the rules hold the shape, because each way this breaks is quiet or
worse.

The first rule is the one that matters most. A power chip decides which
rails of the board have power, and a wrong write to it can switch off the
rail the panel runs on. So the reader reads and never writes.
"""

from __future__ import annotations

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")


def without_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def read(name):
    with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
        return without_comments(handle.read())


class ReadOnlyTest(unittest.TestCase):
    def test_nothing_is_ever_written_to_the_chip(self):
        """transmit_receive sends the number of a register and reads it
        back, which is a read. A transmit on its own is a write."""
        code = read("panel_battery.c")
        calls = re.findall(r"\bi2c_master_\w+\(", code)
        self.assertTrue(calls, "the reader reads nothing at all")
        allowed = {"i2c_master_transmit_receive(", "i2c_master_probe(",
                   "i2c_master_bus_add_device(", "i2c_master_bus_rm_device("}
        for call in calls:
            self.assertIn(call, allowed,
                          "%s is not a read, and this chip decides which "
                          "rails of the board have power" % call)

    def test_each_transfer_sends_one_byte_the_number_of_a_register(self):
        """A longer send in a transmit_receive would carry a value after
        the register, which is a write dressed as a read."""
        code = read("panel_battery.c")
        for found in re.finditer(r"i2c_master_transmit_receive\(([^;]*)\);",
                                 code):
            args = [part.strip() for part in found.group(1).split(",")]
            self.assertEqual(args[2], "1", found.group(0))


class RegisterTest(unittest.TestCase):
    """The numbers of XPowersLib, which the makers of these boards use."""

    def test_the_numbers_are_those_of_the_reference_driver(self):
        code = read("panel_battery.c")
        for name, value in (("AXP2101_ADDRESS", "0x34"),
                            ("AXP2101_STATUS1", "0x00"),
                            ("AXP2101_STATUS2", "0x01"),
                            ("AXP2101_IC_TYPE", "0x03"),
                            ("AXP2101_CHIP_ID", "0x4A"),
                            ("AXP2101_PERCENT", "0xA4")):
            self.assertRegex(code, r"#define %s\s+%s\b" % (name, value))

    def test_a_cell_is_bit_three_and_charging_is_one_in_the_top_bits(self):
        code = read("panel_battery.c")
        self.assertRegex(code, r"status1\s*&\s*\(1u?\s*<<\s*3\)")
        self.assertRegex(code, r"\(status2\s*>>\s*5\)\s*==\s*0x01")

    def test_nothing_is_read_before_the_type_says_which_chip_it_is(self):
        """Something answers at 0x34. Whether it is the chip these numbers
        belong to is what the type register says, and a different chip
        has nothing read from it."""
        code = read("panel_battery.c")
        start = re.search(r"esp_err_t panel_battery_init\(void\).*?\n\}",
                          code, re.S)
        self.assertIsNotNone(start)
        body = start.group(0)
        typed = body.index("AXP2101_IC_TYPE")
        checked = body.index("AXP2101_CHIP_ID")
        first_read = body.index("panel_battery_read(")
        self.assertLess(typed, checked)
        self.assertLess(checked, first_read)

    def test_a_board_without_the_chip_is_asked_quietly(self):
        """A probe says "nobody here" without the driver writing an error
        of its own about a read of an empty address."""
        code = read("panel_battery.c")
        self.assertLess(code.index("i2c_master_probe("),
                        code.index("i2c_master_bus_add_device("))


class WhereTest(unittest.TestCase):
    def test_it_is_read_by_the_network_task_and_not_the_one_that_draws(self):
        """An I2C read on a shared bus can stall. A stall in the drawing
        task is a frozen screen."""
        code = read("main.c")
        tick = re.search(r"static void ui_tick\(lv_timer_t \*timer\).*?\n\}",
                         code, re.S)
        self.assertIsNotNone(tick)
        self.assertNotIn("panel_battery_read", tick.group(0))
        network = code[code.index("static void network_task"):]
        self.assertIn("panel_battery_read(", network)

    def test_the_chip_is_found_before_the_task_that_reads_it_starts(self):
        code = read("main.c")
        self.assertLess(code.index("panel_battery_init();"),
                        code.index("xTaskCreate(network_task"))

    def test_the_build_knows_the_file(self):
        with open(os.path.join(FIRMWARE, "CMakeLists.txt"),
                  encoding="utf-8") as handle:
            build = handle.read()
        self.assertIn('"panel_battery.c"', build)
        self.assertIn("esp_driver_i2c", build)


if __name__ == "__main__":
    unittest.main()
