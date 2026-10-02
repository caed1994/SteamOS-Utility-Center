# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The clock chip of the board, a PCF85063, and the time after a restart.

Asked for: the panel has the time right after a restart, also without
Wi-Fi. SNTP still sets it once the network is there.

firmware/companion/main/panel_rtc.c reads and writes the chip, and the
harness in tests/c/panel-rtc-harness.c drives it here against a chip made
of its registers. panel_time.c gives the time of the chip to the ESP at
the start and the time of each answer of SNTP to the chip. The rules
below hold where and when that happens.
"""

from __future__ import annotations

import calendar
import datetime
import os
import random
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
STUBS = os.path.join(REPO, "tests", "c", "stubs")
HARNESS = os.path.join(REPO, "tests", "c", "panel-rtc-harness.c")

FIRST = calendar.timegm((2000, 1, 1, 0, 0, 0))
LAST = calendar.timegm((2099, 12, 31, 23, 59, 59))
# A time somebody set: 2026-10-02 14:37:05 UTC, a Friday.
SET = calendar.timegm((2026, 10, 2, 14, 37, 5))
SET_BYTES = "05 37 14 02 05 10 26"


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


def code(name):
    with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
        text = handle.read()
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def bcd(value):
    return "%02x" % ((value // 10) << 4 | value % 10)


def chip_bytes(seconds):
    """The registers 04h to 0Ah for a time, as the datasheet has them."""
    date = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc)
    return " ".join([bcd(date.second), bcd(date.minute), bcd(date.hour), bcd(date.day),
                     "%02x" % ((date.weekday() + 1) % 7), bcd(date.month),
                     bcd(date.year - 2000)])


def function(text, name):
    found = re.search(r"\n[^\n]*\b%s\([^)]*\)\s*\{(.*?)\n\}" % re.escape(name), text, re.S)
    if not found:
        raise AssertionError("no function " + name)
    return found.group(1)


@unittest.skipUnless(compiler(), "no C compiler here")
class ClockChipTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-rtc")
        build = [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
                 "-I", STUBS, "-I", FIRMWARE, "-o", cls.program, HARNESS,
                 os.path.join(FIRMWARE, "panel_rtc.c")]
        # With the sanitizers where this machine has them: a date the
        # checks let through reads past the table of the months, and that
        # read then ends the harness and does not give a time by chance.
        done = subprocess.run(build + ["-fsanitize=address,undefined",
                                       "-fno-sanitize-recover=all"],
                              capture_output=True, text=True)
        if done.returncode != 0:
            done = subprocess.run(build, capture_output=True, text=True)
        # A failure and not a skip: the file is plain C against the stubs,
        # so a build that fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_rtc.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def run_lines(self, *commands):
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def answers(self, *commands):
        """What each command printed, without the transfers, the log and
        the end."""
        return [line for line in self.run_lines(*commands)
                if not re.match(r"(r|w|I|W) |x( |$)|writes:", line)]

    def transfers(self, *commands):
        return [line for line in self.run_lines(*commands)
                if re.match(r"(r|w) |x( |$)", line)]

    def written(self, *commands):
        return self.run_lines(*commands)[-1]

    def chip_set(self, seconds=SET, control="00"):
        """The commands for a chip that holds that time, OS clear."""
        values = chip_bytes(seconds).split()
        return ["set 00 " + control] + ["set %02x %s" % (4 + i, value)
                                        for i, value in enumerate(values)]

    # The time in the registers and back.

    def test_the_registers_of_a_time_are_those_of_the_datasheet(self):
        self.assertEqual(chip_bytes(SET), SET_BYTES)
        self.assertEqual(self.answers("encode %d" % SET), ["bytes " + SET_BYTES])

    def test_every_time_from_2000_to_2099_comes_back(self):
        draw = random.Random(85063)
        times = [FIRST, LAST, SET,
                 calendar.timegm((2024, 2, 29, 12, 0, 0)),
                 calendar.timegm((2028, 2, 29, 23, 59, 59)),
                 calendar.timegm((2028, 3, 1, 0, 0, 0)),
                 calendar.timegm((2027, 2, 28, 23, 59, 59)),
                 calendar.timegm((2026, 3, 29, 1, 0, 0)),
                 calendar.timegm((2026, 10, 25, 1, 0, 0))]
        times += [draw.randint(FIRST, LAST) for _ in range(2000)]
        encoded = self.answers(*["encode %d" % one for one in times])
        for one, answer in zip(times, encoded):
            self.assertEqual(answer, "bytes " + chip_bytes(one), one)
        decoded = self.answers(*["decode 00 " + chip_bytes(one) for one in times])
        self.assertEqual(decoded, ["time %d" % one for one in times])

    def test_a_time_the_chip_cannot_hold_is_refused(self):
        self.assertEqual(self.answers("encode %d" % (FIRST - 1), "encode %d" % (LAST + 1),
                                      "encode 0"), ["none"] * 3)

    def test_the_unused_bits_are_left_out(self):
        # Minutes bit 7, hours and days bits 7 and 6, the weekday, months
        # bits 7 to 5.
        self.assertEqual(self.answers("decode 00 05 b7 d4 c2 ff f0 26"), ["time %d" % SET])

    def test_a_time_the_chip_does_not_vouch_for_is_no_time(self):
        cases = {
            "the flag OS": "decode 00 85 37 14 02 05 10 26",
            "a clock that stands still": "decode 20 05 37 14 02 05 10 26",
            "hours of twelve": "decode 02 05 37 14 02 05 10 26",
            "an external clock": "decode 80 05 37 14 02 05 10 26",
        }
        for why, command in cases.items():
            self.assertEqual(self.answers(command), ["none"], why)
        # The interrupt of the correction and the load of the crystal say
        # nothing about the time.
        self.assertEqual(self.answers("decode 05 05 37 14 02 05 10 26"), ["time %d" % SET])

    def test_a_date_that_does_not_exist_is_no_time(self):
        cases = {
            "seconds 60": "decode 00 60 37 14 02 05 10 26",
            "a digit that is no digit": "decode 00 0a 37 14 02 05 10 26",
            "minutes 60": "decode 00 05 60 14 02 05 10 26",
            "hour 24": "decode 00 05 37 24 02 05 10 26",
            "day nought": "decode 00 05 37 14 00 05 10 26",
            "day 32": "decode 00 05 37 14 32 05 10 26",
            "month nought": "decode 00 05 37 14 02 05 00 26",
            "month 13": "decode 00 05 37 14 02 05 13 26",
            "year 9A": "decode 00 05 37 14 02 05 10 9a",
            "year A0": "decode 00 05 37 14 02 05 10 a0",
            "the 31st of April": "decode 00 05 37 14 31 05 04 26",
            "the 30th of February": "decode 00 05 37 14 30 05 02 28",
            "the 29th of February 2027": "decode 00 05 37 14 29 05 02 27",
        }
        for why, command in cases.items():
            self.assertEqual(self.answers(command), ["none"], why)
        self.assertEqual(self.answers("decode 00 00 00 00 29 00 02 28"),
                         ["time %d" % calendar.timegm((2028, 2, 29, 0, 0, 0))])

    # The chip on the bus.

    def test_a_chip_after_a_power_on_holds_no_time(self):
        self.assertEqual(self.answers("init", "read"), ["init ESP_OK", "none"])

    def test_a_read_is_one_transfer_from_control_1_to_the_years(self):
        commands = self.chip_set() + ["init", "read"]
        self.assertEqual(self.answers(*commands), ["init ESP_OK", "time %d" % SET])
        self.assertEqual(self.transfers(*commands), ["r 00 11"])
        self.assertEqual(self.written(*commands), "writes: none")

    def test_a_write_is_one_transfer_of_the_seven_registers(self):
        commands = ["init", "write %d" % SET, "read", "show"]
        self.assertEqual(self.answers(*commands)[:3],
                         ["init ESP_OK", "write ESP_OK", "time %d" % SET])
        # Control_1 is read and left alone, and the flag OS is cleared.
        self.assertEqual(self.transfers(*commands),
                         ["r 00 1", "w 04 " + SET_BYTES, "r 00 11"])
        self.assertEqual(self.written(*commands),
                         "writes: 04*1 05*1 06*1 07*1 08*1 09*1 0a*1")

    def test_a_write_makes_the_clock_count_again_and_keeps_the_rest(self):
        # STOP, hours of twelve, an external clock, and the two bits that
        # stay: the interrupt of the correction and the load of the
        # crystal. Control_1 goes first, or the chip reads the hour of the
        # write as one of twelve.
        commands = ["set 00 a7", "init", "write %d" % SET, "read"]
        self.assertEqual(self.answers(*commands)[1:],
                         ["write ESP_OK", "time %d" % SET])
        self.assertEqual(self.transfers(*commands),
                         ["r 00 1", "w 00 05", "w 04 " + SET_BYTES, "r 00 11"])

    def test_each_bit_that_stops_the_count_is_cleared_alone(self):
        for control in ("80", "20", "02"):
            commands = ["set 00 " + control, "init", "write %d" % SET, "read"]
            self.assertEqual(self.transfers(*commands),
                             ["r 00 1", "w 00 00", "w 04 " + SET_BYTES, "r 00 11"], control)

    def test_nothing_but_control_1_and_the_time_is_ever_written(self):
        draw = random.Random(51)
        for control in (0x00, 0x02, 0x20, 0x22, 0xA7, 0xFF):
            commands = ["set 00 %02x" % control, "init"]
            commands += ["write %d" % draw.randint(FIRST, LAST) for _ in range(20)]
            written = self.written(*commands)
            registers = re.findall(r"([0-9a-f]{2})\*", written)
            self.assertTrue(set(registers) <= {"00", "04", "05", "06", "07", "08", "09", "0a"},
                            written)
            # A reset of the chip needs bit 4 of Control_1, and no write
            # sets it, whatever the chip answered.
            for line in self.transfers(*commands):
                if line.startswith("w 00 "):
                    self.assertFalse(int(line.split()[2], 16) & 0x10, line)

    def test_a_time_the_chip_cannot_hold_is_not_written(self):
        commands = ["init", "write %d" % (LAST + 1), "write %d" % (FIRST - 1)]
        self.assertEqual(self.answers(*commands)[1:],
                         ["write ESP_ERR_INVALID_ARG"] * 2)
        self.assertEqual(self.transfers(*commands), [])

    def test_an_error_on_the_bus_leaves_the_time_alone(self):
        # The read of Control_1 fails: nothing is written.
        commands = ["set 00 22", "init", "fail 1", "write %d" % SET]
        self.assertEqual(self.answers(*commands)[1:], ["write ESP_FAIL"])
        self.assertEqual(self.written(*commands), "writes: none")
        # The write of Control_1 fails: the time is not written either.
        commands = ["set 00 22", "init", "fail 2", "write %d" % SET]
        self.assertEqual(self.answers(*commands)[1:], ["write ESP_FAIL"])
        self.assertEqual(self.written(*commands), "writes: none")
        # A read that fails is no time.
        commands = self.chip_set() + ["init", "fail 1", "read"]
        self.assertEqual(self.answers(*commands)[1:], ["none"])

    def test_without_a_chip_nothing_happens_on_the_bus(self):
        commands = ["absent", "init", "read", "write %d" % SET]
        self.assertEqual(self.answers(*commands),
                         ["init ESP_ERR_NOT_FOUND", "none", "write ESP_ERR_INVALID_STATE"])
        self.assertEqual(self.transfers(*commands), [])


class StartTest(unittest.TestCase):

    def test_the_time_of_the_chip_is_there_before_the_screen_is_built(self):
        main = code("main.c")
        start = main.index("panel_time_start();")
        self.assertLess(main.index("panel_motion_init();"), start)
        self.assertLess(main.index("panel_battery_init();"), start)
        self.assertLess(start, main.index("panel_ui_create(action_send"))
        self.assertLess(start, main.index("ui_tick(NULL);"))

    def test_the_zone_is_set_once_and_before_the_screen(self):
        time = code("panel_time.c")
        self.assertEqual(time.count("setenv(\"TZ\""), 1)
        self.assertIn("setenv(\"TZ\"", function(time, "panel_time_start"))
        self.assertNotIn("setenv", function(time, "panel_time_init"))

    def test_only_a_time_to_trust_sets_the_clock(self):
        start = function(code("panel_time.c"), "panel_time_start")
        # A chip that gives no time ends it there.
        self.assertRegex(start, r"if \(!panel_rtc_read\(&utc\)\) \{[^}]*return;\s*\}")
        self.assertRegex(start, r"if \(panel_rtc_init\(\) != ESP_OK\) return;")
        read = start.index("panel_rtc_read(&utc)")
        year = start.index("PANEL_TIME_SET_YEAR")
        self.assertLess(read, year)
        self.assertLess(year, start.index("settimeofday"))
        self.assertEqual(start.count("settimeofday"), 1)

    def test_the_chip_takes_the_time_in_the_task_of_the_network(self):
        time = code("panel_time.c")
        # The answer of SNTP comes in the task of lwIP, which a stall on
        # the bus must not hold: it only leaves a mark.
        synced = function(time, "synced")
        self.assertNotIn("panel_rtc_", synced)
        self.assertIn("atomic_store(&answered, true)", synced)
        keep = function(time, "panel_time_keep")
        self.assertIn("atomic_exchange(&answered, false)", keep)
        self.assertIn("panel_rtc_write(time(NULL))", keep)
        self.assertIn("panel_time_keep();", function(code("main.c"), "network_task"))

    def test_nothing_that_draws_talks_to_the_chip(self):
        self.assertNotIn("panel_rtc_", code("ui.c"))
        self.assertNotIn("panel_rtc_", function(code("main.c"), "ui_tick"))

    def test_the_firmware_builds_it(self):
        with open(os.path.join(FIRMWARE, "CMakeLists.txt"), encoding="utf-8") as handle:
            self.assertIn('"panel_rtc.c"', handle.read())


if __name__ == "__main__":
    unittest.main()
