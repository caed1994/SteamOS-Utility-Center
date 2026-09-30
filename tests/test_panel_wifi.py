# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""How the wall panel joins the network, read out of the firmware.

Reported from the board, over three starts: the panel took between 9 and
27 seconds to reach the PC. Two separate things are in that, and the log
named neither of them.

The join failed four times in the worst start, with reasons 202, 4, 202
and 15, and it associated on channel 9 before it settled on channel 6 with
the same name at -58 dBm. That is a first match and not a best match,
which is what WIFI_FAST_SCAN does.

And esp_wifi_init took 2.9, 6.8 and 7.2 seconds in the three runs, where a
tenth of a second is the usual figure. Nothing here can say why. What it
can do is stop the next reader from guessing which call it was.

None of this runs here: the container has no radio. These hold the shape.
"""

from __future__ import annotations

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")


def read(name):
    with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
        return handle.read()


def without_comments(text):
    """The C with its comments taken out, because these read calls."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


class ScanTest(unittest.TestCase):
    """Which AP the panel picks when more than one answers to the name."""

    def source(self):
        return without_comments(read("main.c"))

    def test_it_reads_every_channel(self):
        """The default ends at the first AP of this name.

        esp_wifi_types_generic.h says of WIFI_FAST_SCAN: "scan will end
        after find SSID match AP". The board showed what that costs. A
        zeroed wifi_config_t is a fast scan, so leaving this out is not a
        neutral choice, it is a choice.
        """
        self.assertRegex(self.source(),
                         r"scan_method\s*=\s*WIFI_ALL_CHANNEL_SCAN")

    def test_it_takes_the_strongest_and_not_the_first(self):
        self.assertRegex(self.source(),
                         r"sort_method\s*=\s*WIFI_CONNECT_AP_BY_SIGNAL")

    def test_the_two_that_need_the_full_scan_do_not_go_without_it(self):
        """sort_method and failure_retry_cnt do nothing on their own.

        The header says it at both of them. A change that drops the full
        scan and keeps these leaves two lines that read as though they
        work, and a panel back on first match.
        """
        code = self.source()
        needs = re.search(r"sort_method|failure_retry_cnt", code)
        if not needs:
            self.skipTest("neither is asked for")
        self.assertRegex(code, r"scan_method\s*=\s*WIFI_ALL_CHANNEL_SCAN",
                         "these two do nothing without a scan of every "
                         "channel, so they must not stand without one")

    def test_it_gives_up_on_an_AP_that_does_not_finish(self):
        """The start that failed four times kept going back to the same
        AP. A count here moves on to the next one instead."""
        self.assertRegex(self.source(), r"failure_retry_cnt\s*=\s*[1-9]")


class ReasonTest(unittest.TestCase):
    """The log says what a number means."""

    def test_the_disconnect_carries_a_name(self):
        code = without_comments(read("main.c"))
        said = re.search(r'ESP_LOGW\("panel_wifi","Disconnected[^;]*;', code)
        self.assertIsNotNone(said, "nothing logs a disconnect")
        self.assertIn("wifi_reason_name", said.group(0),
                      "a bare number sends every reader to a header")

    def test_the_table_holds_the_ones_the_board_reported(self):
        """201, 202, 4 and 15 all came off this panel."""
        code = without_comments(read("main.c"))
        table = re.search(r"wifi_reason_name\(uint8_t reason\)\s*\{.*?\n\}",
                          code, re.S)
        self.assertIsNotNone(table)
        for number in ("4", "15", "201", "202"):
            self.assertRegex(table.group(0), r"case\s+%s\s*:" % number,
                             "reason %s came off the board and has no "
                             "name here" % number)

    def test_a_number_it_does_not_know_still_says_something(self):
        code = without_comments(read("main.c"))
        table = re.search(r"wifi_reason_name\(uint8_t reason\)\s*\{.*?\n\}",
                          code, re.S)
        self.assertIn("default:", table.group(0))


class StepTimingTest(unittest.TestCase):
    """Which call takes the seconds."""

    def source(self):
        return without_comments(read("main.c"))

    def test_every_step_of_the_bring_up_is_timed(self):
        """The one that was slow is inside esp_wifi_init, and that was
        read off two lines the driver prints for itself. Ours were never
        timed at all."""
        code = self.source()
        for call in ("esp_netif_init", "esp_wifi_init", "esp_wifi_start",
                     "esp_wifi_connect", "esp_wifi_set_config"):
            self.assertRegex(code, r'WIFI_STEP\("%s"' % call,
                             "%s is not timed" % call)

    def test_it_stays_quiet_when_nothing_is_wrong(self):
        """A line for each step at every start is a wall of log that
        nobody reads. Only a step that is slow says so."""
        code = self.source()
        self.assertRegex(code, r"spent__\s*>=\s*WIFI_STEP_LOUD_MS")
        said = re.search(r"#define WIFI_STEP_LOUD_MS (\d+)", code)
        self.assertIsNotNone(said)
        self.assertGreaterEqual(int(said.group(1)), 10)

    def test_the_whole_bring_up_is_timed_too(self):
        """So a start that is slow in no single step still shows it."""
        self.assertRegex(self.source(),
                         r"network brought up in %u ms")


if __name__ == "__main__":
    unittest.main()
