# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The battery of the panel, read off its power chip.

The 4B carries an AXP2101, and nothing in the board support speaks to it.
firmware/companion/main/panel_battery.c does, and none of this can run
here: the rules hold the shape, because each way this breaks is quiet or
worse.

The first rules are the ones that matter most. A power chip decides which
rails of the board have power, and a wrong write to it can switch off the
rail the panel runs on. So the reader reads, and writes four fields and
nothing else: bit 4 of 0x50, which sets the TS pin apart from the charger,
0x62, the charge current, bits 2:0 of 0x69, the CHG LED, and bits 4:2 of
0x30, the channels of the ADC for the input, the system rail and the die.
Its owner allowed the first two after the panel charged a cell of 5000 mAh
far too slowly, the third for the LED, which stayed dark, and the fourth
for the page of the panel, which shows those three readings.
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
HARNESS = os.path.join(REPO, "tests", "c", "panel-battery-harness.c")
STUBS = os.path.join(REPO, "tests", "c", "stubs")


def without_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def read(name):
    with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
        return without_comments(handle.read())


class WriteTest(unittest.TestCase):
    """Four fields are written, and nothing else is."""

    def body(self, code, start):
        found = re.search(re.escape(start) + r".*?\n\}", code, re.S)
        self.assertIsNotNone(found, start)
        return found.group(0)

    def test_the_calls_are_reads_and_one_write(self):
        """transmit_receive sends the number of a register and reads it
        back, which is a read. A transmit on its own is a write, and there
        is one, in write_register."""
        code = read("panel_battery.c")
        calls = re.findall(r"\bi2c_master_\w+\(", code)
        self.assertTrue(calls, "the reader reads nothing at all")
        allowed = {"i2c_master_transmit_receive(", "i2c_master_transmit(",
                   "i2c_master_probe(", "i2c_master_bus_add_device(",
                   "i2c_master_bus_rm_device("}
        for call in calls:
            self.assertIn(call, allowed, call)
        self.assertEqual(calls.count("i2c_master_transmit("), 1)
        writer = self.body(code, "static esp_err_t write_register(")
        self.assertIn("i2c_master_transmit(", writer)

    def test_only_set_field_writes_and_only_for_the_four_fields(self):
        """A rail of the board is a register too. One more call of
        set_field with another register would switch it as easily."""
        code = read("panel_battery.c")
        self.assertEqual(len(re.findall(r"\bwrite_register\(", code)), 2,
                         "the definition and the one call in set_field")
        self.assertIn("write_register(",
                      self.body(code, "static void set_field("))
        fields = re.findall(r"\bset_field\(\s*(\w+),\s*(\w+),\s*(\w+),",
                            code)
        self.assertEqual(sorted(fields), [
            ("AXP2101_ADC_ON", "ADC_MEASURE_MASK", "ADC_MEASURE"),
            ("AXP2101_CHARGE_CURRENT", "CHARGE_CURRENT_MASK",
             "CHARGE_CURRENT_CODE"),
            ("AXP2101_CHGLED", "CHGLED_MASK", "CHGLED_TYPE_A"),
            ("AXP2101_TS_CONTROL", "TS_APART_MASK", "TS_APART")])

    def test_the_fields_are_the_ones_allowed(self):
        code = read("panel_battery.c")
        for name, value in (("TS_APART_MASK", "0x10"), ("TS_APART", "0x10"),
                            ("CHARGE_CURRENT_MASK", "0x1F"),
                            ("CHARGE_CURRENT_CODE", "0x10"),
                            ("CHARGE_CURRENT_MA", "1000"),
                            ("PANEL_CELL_MAH", "5000"),
                            ("CHGLED_MASK", "0x07"),
                            ("CHGLED_TYPE_A", "0x01"),
                            ("ADC_MEASURE_MASK", "0x1C"),
                            ("ADC_MEASURE", "0x1C")):
            self.assertRegex(code, r"#define %s\s+%s\b" % (name, value))

    def test_the_writes_come_once_at_the_start_after_the_type(self):
        """Not at every reading, and never to a chip that is not this
        one."""
        code = read("panel_battery.c")
        start = self.body(code, "esp_err_t panel_battery_init(void)")
        self.assertLess(start.index("AXP2101_CHIP_ID"),
                        start.index("charger_set();"))
        self.assertLess(start.index("charger_set();"),
                        start.index("panel_battery_read("))
        self.assertEqual(code.count("charger_set();"), 1,
                         "one call, at the start")

    def test_each_transfer_has_the_size_of_its_kind(self):
        """One byte out for a read: a longer send in a transmit_receive
        would carry a value after the register, which is a write dressed as
        a read. Two bytes for the write: a register and its value."""
        code = read("panel_battery.c")
        for found in re.finditer(r"i2c_master_transmit_receive\(([^;]*)\);",
                                 code):
            args = [part.strip() for part in found.group(1).split(",")]
            self.assertEqual(args[2], "1", found.group(0))
        for found in re.finditer(r"i2c_master_transmit\(([^;]*)\);", code):
            args = [part.strip() for part in found.group(1).split(",")]
            self.assertEqual(args[2], "2", found.group(0))


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

    def test_the_detail_is_read_there_too(self):
        """The page of the panel reads the voltages and the die, which are
        a dozen reads on the same shared bus."""
        code = read("main.c")
        tick = re.search(r"static void ui_tick\(lv_timer_t \*timer\).*?\n\}",
                         code, re.S)
        self.assertNotIn("panel_battery_detail", tick.group(0))
        network = code[code.index("static void network_task"):]
        self.assertIn("panel_battery_detail(&detail);", network)
        self.assertIn("state.esp_detail=detail;", network)
        self.assertNotIn("panel_battery_detail", read("ui.c"))

    def test_the_chip_is_found_before_the_task_that_reads_it_starts(self):
        code = read("main.c")
        self.assertLess(code.index("panel_battery_init();"),
                        code.index("panel_psram_task(network_task"))

    def test_the_build_knows_the_file(self):
        with open(os.path.join(FIRMWARE, "CMakeLists.txt"),
                  encoding="utf-8") as handle:
            build = handle.read()
        self.assertIn('"panel_battery.c"', build)
        self.assertIn("esp_driver_i2c", build)



def compiler():
    return shutil.which("cc") or shutil.which("gcc")


# A cell that charges at constant current on a good input: STATUS1 with
# "input good" and "cell present", STATUS2 with "charge" and "CC".
CHARGING = ("set 00 28", "set 01 22")


@unittest.skipUnless(compiler(), "no C compiler here")
class ChargerReportTest(unittest.TestCase):
    """The line about the charger, built and driven on this machine.

    Asked about on the board: the panel charges slowly, with a charger and
    a cable that charge a Switch 2 fast, and off as slowly as on. Which
    setting of the chip holds it back is a reading, and this line is that
    reading. These hold that it says what the registers hold, in the units
    of the AXP2101 datasheet V1.4, and that it writes nothing.
    """

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-battery")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", STUBS, "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_battery.c")],
            capture_output=True, text=True)
        # A failure and not a skip. The stubs are plain C, so a build that
        # fails is a fault in the file, and a skip would hide every rule
        # below behind it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_battery.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def output(self, *commands):
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def charger(self, *commands):
        return [line for line in self.output(*commands)
                if line.startswith("I panel_battery: charger:")]

    def one(self, *commands):
        """The line at the start, with the two registers the start writes
        locked, so the line shows the values the test set."""
        lines = self.charger(*CHARGING, "lock 50", "lock 62", "lock 69",
                             *commands, "init")
        self.assertEqual(len(lines), 1)
        return lines[0]

    def test_the_charge_current_reads_as_the_datasheet_counts(self):
        """REG 62: 25 mA a step up to 200 mA, then 100 mA a step up to
        1000 mA. Anything above is reserved, and says so."""
        for code, current in ((0, 0), (1, 25), (4, 100), (8, 200), (9, 300),
                              (11, 500), (16, 1000), (17, -1), (31, -1)):
            with self.subTest(code=code):
                self.assertIn("icc=%d mA" % current,
                              self.one("set 62 %x" % code))

    def test_the_input_limit_reads_as_the_datasheet_counts(self):
        for code, current in ((0, 100), (1, 500), (2, 900), (3, 1000),
                              (4, 1500), (5, 2000), (6, -1)):
            with self.subTest(code=code):
                self.assertIn("iin=%d mA" % current,
                              self.one("set 16 %x" % code))

    def test_the_voltages_read_as_the_datasheet_counts(self):
        line = self.one("set 15 06", "set 64 03", "set 34 0f", "set 35 0a")
        self.assertIn("vindpm=4360 mV", line)
        self.assertIn("cv=4200 mV", line)
        self.assertIn("vbat=3850 mV", line)
        self.assertIn("cv=4350 mV", self.one("set 64 04"))

    def test_the_small_currents_count_in_steps_of_25(self):
        line = self.one("set 61 05", "set 63 15")
        self.assertIn("pre=125 mA term=125 mA cv", line)
        self.assertIn("term=125 mA (off)", self.one("set 63 05"))

    def test_the_ts_pin_says_what_it_does_to_the_charger(self):
        """The suspect. A TS pin that can stop the charger, with no sensor
        on it, reads as open."""
        line = self.one("set 50 0a", "set 30 03", "set 36 20", "set 37 00")
        self.assertIn("ts=open, a sensor that can stop the charger", line)
        line = self.one("set 50 10", "set 30 03", "set 36 03", "set 37 e8")
        self.assertIn("ts=500 mV, apart from the charger", line)
        self.assertIn("ts=not measured", self.one("set 30 01"))

    def test_it_says_what_holds_the_current_down(self):
        self.assertIn("held by nothing", self.one())
        line = self.charger("set 00 2b", "set 01 2a", "init")[0]
        self.assertIn("held by heat, input current, input voltage;", line)

    def test_the_state_is_named(self):
        for code, name in ((0, "trickle"), (1, "pre-charge"),
                           (2, "constant current"), (3, "constant voltage"),
                           (4, "done"), (5, "not charging")):
            with self.subTest(code=code):
                line = self.charger("set 00 28", "set 01 %x" % (0x20 | code),
                                    "init")[0]
                self.assertIn("charger: %s," % name, line)

    def test_a_change_is_written_once_and_not_at_every_reading(self):
        """The reading runs every five seconds. A line each time would bury
        everything else in the log, and so would a state that flickers.
        Here it flickers every two seconds: one line at the start, one at
        the end of the hold with the state of that moment, and the next
        one a hold after that."""
        commands = list(CHARGING) + ["init"]
        for second in range(2, 20, 2):
            state = "23" if second % 4 == 2 else "22"
            commands += ["at %d" % second, "set 01 %s" % state, "read"]
        commands += ["at 31", "read",
                     "at 33", "set 01 22", "read",
                     "at 45", "read",
                     "at 62", "read",
                     "at 70", "read",
                     "at 95", "read"]
        lines = self.charger(*commands)
        self.assertEqual(len(lines), 3, lines)
        self.assertIn("charger: constant current,", lines[0])
        self.assertIn("charger: constant voltage,", lines[1])
        self.assertIn("charger: constant current,", lines[2])

    def test_without_a_cell_there_is_no_line_about_a_charge(self):
        self.assertEqual(self.charger("set 00 20", "init", "read"), [])

    def writes(self, *commands):
        output = self.output(*commands)
        self.assertEqual(output[-1], "not a read: 0")
        self.assertTrue(output[-2].startswith("writes:"), output[-2])
        return output[-2][len("writes:"):].split()

    def test_the_start_writes_the_four_fields_and_keeps_the_rest(self):
        """0x0a in 0x50 is the current source of the TS pin, and it stays.
        The top three bits of 0x62 are read only in the chip, and stay.
        Bits 5:4 of 0x69 drive the LED only in the mode this leaves, and
        stay as well. Bits 1:0 of 0x30 measure the TS pin and the cell from
        the reset, and bit 5 is the channel for general use: all three
        stay."""
        self.assertEqual(self.writes(*CHARGING, "set 50 0a", "set 62 e9",
                                     "set 69 35", "set 30 23", "init"),
                         ["30=3f*1", "50=1a*1", "62=f0*1", "69=31*1"])

    def test_a_field_that_holds_its_value_is_not_written(self):
        """Which is every start after the first, until the cell is
        unplugged."""
        self.assertEqual(self.writes(*CHARGING, "set 50 1a", "set 62 10",
                                     "set 69 01", "set 30 1f", "init"),
                         ["none"])

    def test_readings_write_nothing(self):
        """The writes come at the start, once, and the reading every five
        seconds after that only reads."""
        commands = list(CHARGING) + ["init"]
        for second in range(5, 300, 5):
            commands += ["at %d" % second, "read"]
        commands += ["set 01 23", "at 400", "read", "detail"]
        self.assertEqual(self.writes(*commands),
                         ["30=1c*1", "50=10*1", "62=10*1", "69=01*1"])

    def test_another_chip_gets_nothing_written(self):
        """Something else at 0x34 is not the chip these numbers belong
        to."""
        self.assertEqual(self.writes(*CHARGING, "type 47", "init"), ["none"])

    def test_a_write_that_does_not_take_says_so_and_is_not_repeated(self):
        output = self.output(*CHARGING, "lock 62", "init", "at 40", "read",
                             "at 80", "read")
        warnings = [line for line in output if line.startswith("W ")]
        self.assertEqual(len(warnings), 1, output)
        self.assertIn("charge current 1000 mA: 0x62 did not take it",
                      warnings[0])
        self.assertIn("62=00*1", output[-2])

    def test_the_line_shows_the_values_the_start_wrote(self):
        line = self.charger(*CHARGING, "set 50 0a", "set 62 09", "set 69 04",
                            "init")[0]
        self.assertIn("icc=1000 mA", line)
        self.assertIn("apart from the charger", line)
        self.assertIn("; led shows the charge (type A)", line)

    # The board on its cable, charging at constant current: 4038 mV on the
    # cell, 5011 mV on the input, 3714 mV on the system rail, and a die at
    # 38 degrees. That is 6954 counts of the ADC, 320 below the 7274 of
    # 22 degrees.
    DETAIL = ("set 00 29", "set 01 22", "set 30 1f",
              "set 34 0f", "set 35 c6", "set 38 13", "set 39 93",
              "set 3a 0e", "set 3b 82", "set 3c 1b", "set 3d 2a",
              "set 62 10", "set 64 03", "set 16 04")

    def detail(self, *commands):
        lines = [line for line in self.output(*commands)
                 if line.startswith("detail ")]
        self.assertEqual(len(lines), 1)
        return dict(part.split("=") for part in lines[0].split()[2:])

    def test_the_detail_reads_as_the_datasheet_counts(self):
        said = self.detail(*self.DETAIL, "init", "detail")
        self.assertEqual(said, {"vbat": "4038", "vbus": "5011",
                                "vsys": "3714", "die": "38", "phase": "2",
                                "held": "010", "icc": "1000", "cv": "4200",
                                "iin": "1500"})

    def test_a_channel_the_adc_does_not_measure_is_no_reading(self):
        """0 in those registers is what a channel that is off reads, and 0
        counts in the die are 385 degrees. A 0x30 that does not take the
        write keeps the three off."""
        said = self.detail(*self.DETAIL, "set 30 03", "lock 30", "set 38 00",
                           "set 39 00", "set 3a 00", "set 3b 00", "set 3c 00",
                           "set 3d 00", "init", "detail")
        self.assertEqual((said["vbus"], said["vsys"], said["die"]),
                         ("-1", "-1", "-128"))
        self.assertEqual(said["vbat"], "4038")

    def test_the_input_counts_only_while_it_is_good(self):
        said = self.detail(*self.DETAIL, "init", "set 00 08", "detail")
        self.assertEqual(said["vbus"], "-1")

    def test_without_a_cell_there_is_no_cell_and_no_phase(self):
        said = self.detail(*self.DETAIL, "init", "set 00 20", "detail")
        self.assertEqual((said["vbat"], said["phase"]), ("-1", "-1"))
        self.assertEqual(said["vsys"], "3714")

    def test_a_die_past_what_a_chip_reaches_is_no_reading(self):
        """7274 counts are 22 degrees. 4000 counts are 185, past the 150 a
        die shuts down at long before."""
        said = self.detail(*self.DETAIL, "set 3c 1c", "set 3d 6a", "init",
                           "detail")
        self.assertEqual(said["die"], "22")
        said = self.detail(*self.DETAIL, "set 3c 0f", "set 3d a0", "init",
                           "detail")
        self.assertEqual(said["die"], "-128")

    def test_the_holds_are_the_three_of_the_line(self):
        said = self.detail(*self.DETAIL, "set 00 2b", "set 01 2a", "init",
                           "detail")
        self.assertEqual(said["held"], "111")

    def test_a_chip_that_was_not_found_gives_nothing(self):
        line = [one for one in self.output("type 47", "init", "detail")
                if one.startswith("detail ")][0]
        self.assertTrue(line.startswith("detail none vbat=-1 vbus=-1"), line)

    def test_the_line_names_what_the_led_does(self):
        """Read before the write, the line says why the LED was dark; the
        log line of the write says the value it found."""
        for code, name in ((0x00, "off"), (0x04, "off"),
                           (0x01, "shows the charge (type A)"),
                           (0x03, "type B"), (0x05, "for software to switch"),
                           (0x07, "reserved"), (0x31, "shows the charge")):
            with self.subTest(code=code):
                self.assertIn("; led %s" % name,
                              self.one("set 69 %x" % code))


class ChargerRegisterTest(unittest.TestCase):
    """The numbers of the charger, against the datasheet V1.4, 6.13.2."""

    def test_the_numbers_are_those_of_the_datasheet(self):
        code = read("panel_battery.c")
        for name, value in (("AXP2101_VINDPM", "0x15"),
                            ("AXP2101_INPUT_LIMIT", "0x16"),
                            ("AXP2101_CHARGER_ON", "0x18"),
                            ("AXP2101_ADC_ON", "0x30"),
                            ("AXP2101_VBAT_HIGH", "0x34"),
                            ("AXP2101_VBAT_LOW", "0x35"),
                            ("AXP2101_TS_HIGH", "0x36"),
                            ("AXP2101_TS_LOW", "0x37"),
                            ("AXP2101_VBUS_HIGH", "0x38"),
                            ("AXP2101_VBUS_LOW", "0x39"),
                            ("AXP2101_VSYS_HIGH", "0x3A"),
                            ("AXP2101_VSYS_LOW", "0x3B"),
                            ("AXP2101_TDIE_HIGH", "0x3C"),
                            ("AXP2101_TDIE_LOW", "0x3D"),
                            ("AXP2101_TS_CONTROL", "0x50"),
                            ("AXP2101_JEITA", "0x58"),
                            ("AXP2101_PRECHARGE", "0x61"),
                            ("AXP2101_CHARGE_CURRENT", "0x62"),
                            ("AXP2101_TERMINATION", "0x63"),
                            ("AXP2101_CHARGE_VOLTAGE", "0x64"),
                            ("AXP2101_CHGLED", "0x69")):
            self.assertRegex(code, r"#define %s\s+%s\b" % (name, value))


if __name__ == "__main__":
    unittest.main()
