# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The measurement of the touch screen of the wall panel.

panel_taps.c counts what happens to each press: a tap, a swipe, or a lost
tap. It also counts the reads that came late, the reads that the bus
refused, and the configuration of the touch controller. The functions run
on the machine of the tests through a small harness, as the functions of
panel_led.c do.

The reader in panel_display.c replaces the reader of esp_lvgl_port. These
tests hold what it must and must not do: it gives each read to the count,
a refused read does not restart the panel, and nothing writes to the
controller.
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
PREVIEW = os.path.join(REPO, "firmware", "companion", "preview")
HARNESS = os.path.join(REPO, "tests", "c", "panel-taps-harness.c")

# Where the configuration of the GT911 starts, and the place of each value
# in it, from its register map.
CONFIG_START = 0x8047
CHECKSUM = 0x80FF
TOUCH_LEVEL = 0x8053
LEAVE_LEVEL = 0x8054
REFRESH_RATE = 0x8056


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def code(name):
    """A source file of the firmware, with no comments in it."""
    text = read(os.path.join(FIRMWARE, name))
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def body(text, start):
    """The body of the function that starts with that text."""
    at = text.index(start)
    return text[at:text.index("\n}", at)]


def config(version="A", touch=80, leave=50, refresh=0x05, checksum=None):
    """The bytes of a configuration from CONFIG_START up to and with its
    checksum, as a hex string for the harness."""
    data = bytearray(CHECKSUM - CONFIG_START)
    data[0] = ord(version)
    data[TOUCH_LEVEL - CONFIG_START] = touch
    data[LEAVE_LEVEL - CONFIG_START] = leave
    data[REFRESH_RATE - CONFIG_START] = refresh
    if checksum is None:
        checksum = (-sum(data)) & 0xFF
    data.append(checksum)
    return data.hex()


class SourceTest(unittest.TestCase):
    """The reader in panel_display.c, and the builds."""

    def test_the_reader_of_the_port_is_replaced(self):
        display = code("panel_display.c")
        self.assertIn("lv_indev_set_read_cb(panel_input,touch_read)", display)
        self.assertIn(
            "lv_indev_add_event_cb(panel_input,touch_event,LV_EVENT_ALL,NULL)",
            display)

    def test_a_refused_read_does_not_restart_the_panel(self):
        """The reader of the port wraps the read in ESP_ERROR_CHECK. One
        read that the shared bus refused then restarted the panel."""
        reader = body(code("panel_display.c"), "static void touch_read")
        self.assertNotIn("ESP_ERROR_CHECK", reader)
        self.assertNotIn("abort", reader)
        self.assertIn("panel_taps_read(&panel_taps,now,false,", reader)

    def test_each_read_and_each_event_goes_to_the_count(self):
        display = code("panel_display.c")
        reader = body(display, "static void touch_read")
        self.assertIn("panel_taps_read(&panel_taps,now,true,", reader)
        events = body(display, "static void touch_event")
        for name in ("panel_taps_pressed", "panel_taps_released",
                     "panel_taps_clicked"):
            self.assertIn(name, events)
        self.assertIn("lv_indev_get_scroll_obj(panel_input)!=NULL", events)

    def test_nothing_writes_to_the_controller(self):
        """Its configuration is read for the page and nothing more. A
        configuration written in error can leave the touch unusable."""
        display = code("panel_display.c")
        self.assertIn("esp_lcd_panel_io_rx_param(panel_touch->io,", display)
        self.assertNotIn("esp_lcd_panel_io_tx_param", display)

    def test_a_sleep_of_the_panel_is_no_late_read(self):
        """LVGL reads no touch while the panel sleeps. Without the break,
        the first read after a sleep counted the whole sleep as one gap."""
        standby = body(code("panel_display.c"),
                       "esp_err_t panel_display_standby")
        self.assertEqual(standby.count("panel_taps_break(&panel_taps);"), 2)

    def test_the_page_holds_the_count_and_starts_it_again(self):
        ui = code("ui.c")
        self.assertIn("panel_taps_hold(&panel_taps,true);", ui)
        self.assertIn("panel_taps_reset(&panel_taps);", ui)

    def test_both_builds_carry_the_file(self):
        self.assertIn('"panel_taps.c"',
                      read(os.path.join(FIRMWARE, "CMakeLists.txt")))
        self.assertIn("../main/panel_taps.c",
                      read(os.path.join(PREVIEW, "CMakeLists.txt")))

    def test_the_configuration_is_the_register_map_of_the_gt911(self):
        header = code("panel_taps.h")
        self.assertIn("#define PANEL_TAPS_CHIP_START 0x8047", header)
        self.assertIn("#define PANEL_TAPS_CHIP_LENGTH (0x80FF - 0x8047 + 1)",
                      header)


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


@unittest.skipUnless(compiler(), "no C compiler here")
class HarnessTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-taps")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_taps.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_taps.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def ask(self, *commands):
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    @staticmethod
    def press(at, moved=2, strength=40, target=True, swipe=False,
              click=True, gap=15):
        """One press as the reader and LVGL give it: down at "at", the
        finger "moved" px along, up, and the read after it."""
        lines = ["read %d 1 1 100 100 %d" % (at, strength),
                 "pressed %d" % target,
                 "read %d 1 1 %d 100 %d" % (at + gap, 100 + moved,
                                            strength + 3),
                 "read %d 1 0 0 0 -1" % (at + gap + 15),
                 "released %d" % swipe]
        if click:
            lines.append("clicked")
        lines.append("read %d 1 0 0 0 -1" % (at + gap + 30))
        return lines

    def counts(self, *commands):
        return self.ask(*commands, "counts")[-1].split()

    def test_a_press_is_over_at_the_read_after_its_release(self):
        """LVGL sends its events for a release in the read that saw it, so
        what the press became is known only at the next one."""
        answers = self.ask(*self.press(1000))
        self.assertEqual(answers[:-1], ["-", "ok", "-", "-", "ok", "ok"])
        self.assertEqual(answers[-1], "tap 30 2 40")

    def test_each_press_becomes_what_lvgl_made_of_it(self):
        self.assertEqual(self.ask(*self.press(1000))[-1].split()[0], "tap")
        self.assertEqual(
            self.ask(*self.press(1000, moved=90, swipe=True,
                                 click=False))[-1].split()[0], "swipe")
        self.assertEqual(
            self.ask(*self.press(1000, click=False))[-1].split()[0], "lost")
        self.assertEqual(
            self.ask(*self.press(1000, target=False,
                                 click=False))[-1].split()[0], "nothing")

    def test_a_swipe_that_ends_on_a_button_is_still_a_swipe(self):
        """LVGL sends no CLICKED after a scroll, but a swipe is a swipe
        whatever it ends on."""
        answer = self.ask(*self.press(1000, swipe=True, click=True))[-1]
        self.assertEqual(answer.split()[0], "swipe")

    def test_the_numbers_of_a_press(self):
        """The time from the first read with the finger to the first one
        without, the farthest the finger went along either axis, and the
        weakest contact."""
        answer = self.ask("read 1000 1 1 100 100 40", "pressed 1",
                          "read 1015 1 1 90 120 35",
                          "read 1030 1 1 110 105 38",
                          "read 1045 1 0 0 0 -1", "released 0", "clicked",
                          "read 1060 1 0 0 0 -1")[-1]
        self.assertEqual(answer, "tap 45 20 35")

    def test_the_finger_counts_as_far_whichever_way_it_went(self):
        answer = self.ask("read 1000 1 1 100 100 40", "pressed 1",
                          "read 1015 1 1 70 105 40", "read 1030 1 0 0 0 -1",
                          "released 0", "clicked", "read 1045 1 0 0 0 -1")[-1]
        self.assertEqual(answer, "tap 30 30 40")

    def test_a_read_with_no_contact_keeps_the_weakest_one(self):
        """The controller reports the size of a contact, and -1 is none:
        not a weaker contact than any."""
        answer = self.ask("read 1000 1 1 100 100 40", "pressed 1",
                          "read 1015 1 1 100 100 -1", "read 1030 1 0 0 0 -1",
                          "released 0", "clicked", "read 1045 1 0 0 0 -1")[-1]
        self.assertEqual(answer, "tap 30 0 40")
        answer = self.counts(*self.press(1000, strength=33),
                             "read 2000 1 1 100 100 -1", "pressed 1",
                             "read 2015 1 0 0 0 -1", "released 0", "clicked",
                             "read 2030 1 0 0 0 -1")
        self.assertEqual(answer[8], "33")

    def test_a_press_on_nothing_after_one_on_a_button_is_on_nothing(self):
        """LVGL sends no PRESSED for a press on nothing that takes a tap,
        so each press starts with nothing to tap."""
        answers = self.ask(*self.press(1000), "read 2000 1 1 100 100 40",
                           "read 2015 1 0 0 0 -1", "read 2030 1 0 0 0 -1")
        self.assertEqual(answers[-1], "nothing 15 0 40")

    def test_a_contact_the_controller_does_not_report_is_no_contact(self):
        answer = self.ask("read 1000 1 1 100 100 -1", "pressed 1",
                          "read 1015 1 0 0 0 -1", "released 0", "clicked",
                          "read 1030 1 0 0 0 -1")[-1]
        self.assertEqual(answer, "tap 15 0 -1")
        self.assertEqual(self.counts("read 1000 1 1 1 1 -1", "pressed 1",
                                     "read 1015 1 0 0 0 -1", "released 0",
                                     "read 1030 1 0 0 0 -1")[8], "-1")

    def test_the_counts_add_up(self):
        commands = (self.press(1000) + self.press(2000, moved=90, swipe=True,
                                                  click=False)
                    + self.press(3000, click=False, strength=31)
                    + self.press(4000, target=False, click=False))
        presses, taps, swipes, lost = self.counts(*commands)[:4]
        self.assertEqual((presses, taps, swipes, lost), ("4", "1", "1", "1"))

    def test_the_shortest_press_and_the_weakest_contact(self):
        commands = (self.press(1000, gap=40, strength=50)
                    + self.press(2000, gap=15, strength=33)
                    + self.press(3000, gap=25, strength=60))
        answer = self.counts(*commands)
        self.assertEqual((answer[7], answer[8]), ("30", "33"))

    def test_a_late_read_and_the_longest_gap(self):
        """A read more than PANEL_TAPS_LATE_MS after the one before it. A
        tap shorter than such a gap is never seen."""
        late = int(re.search(r"#define PANEL_TAPS_LATE_MS (\d+)",
                             code("panel_taps.h")).group(1))
        answer = self.counts("read 1000 1 0 0 0 -1",
                             "read %d 1 0 0 0 -1" % (1000 + late),
                             "read %d 1 0 0 0 -1" % (1001 + 2 * late),
                             "read %d 1 0 0 0 -1" % (1020 + 2 * late))
        self.assertEqual((answer[4], answer[6]), ("1", str(late + 1)))

    def test_a_refused_read_counts_and_changes_no_press(self):
        """The finger stays where the read before it put it: a refused
        read in the middle of a press does not end it."""
        answers = self.ask("read 1000 1 1 100 100 40", "pressed 1",
                           "read 1015 0 0 0 0 -1",
                           "read 1030 1 1 101 100 40",
                           "read 1045 1 0 0 0 -1", "released 0", "clicked",
                           "read 1060 1 0 0 0 -1", "counts")
        self.assertEqual(answers[2], "-")
        self.assertEqual(answers[-2], "tap 45 1 40")
        counted = answers[-1].split()
        self.assertEqual((counted[0], counted[5]), ("1", "1"))

    def test_after_a_break_the_gap_is_no_late_read(self):
        answer = self.counts("read 1000 1 0 0 0 -1", "break",
                             "read 90000 1 0 0 0 -1",
                             "read 90015 1 0 0 0 -1")
        self.assertEqual((answer[4], answer[6]), ("0", "15"))

    def test_a_break_drops_the_press_on_its_way(self):
        answers = self.ask("read 1000 1 1 100 100 40", "pressed 1", "break",
                           "read 90000 1 0 0 0 -1", "read 90015 1 0 0 0 -1",
                           "counts")
        self.assertEqual(answers[3:5], ["-", "-"])
        self.assertEqual(answers[-1].split()[0], "0")
        answers = self.ask("read 1000 1 1 100 100 40", "pressed 1",
                           "read 1015 1 0 0 0 -1", "released 0", "clicked",
                           "break", "read 90000 1 0 0 0 -1", "counts")
        self.assertEqual(answers[-2], "-")
        self.assertEqual(answers[-1].split()[0], "0")

    def test_nothing_counts_while_the_page_holds_the_count(self):
        answer = self.counts("hold 1", *self.press(1000),
                             "read 1500 0 0 0 0 -1",
                             "read 1600 1 0 0 0 -1")
        self.assertEqual(answer, ["0", "0", "0", "0", "0", "0", "0", "0",
                                  "-1", "1"])
        answer = self.counts("hold 1", "hold 0", *self.press(1000))
        self.assertEqual(answer[:2], ["1", "1"])

    def test_a_reset_starts_from_nothing(self):
        answer = self.counts(*self.press(1000, strength=30), "hold 1",
                             "reset", "read 9000 1 0 0 0 -1")
        self.assertEqual(answer, ["0", "0", "0", "0", "0", "0", "0", "0",
                                  "-1", "0"])

    def test_the_configuration_of_the_controller(self):
        self.assertEqual(self.ask("chip " + config()), ["A 80 50 10"])
        self.assertEqual(
            self.ask("chip " + config(version="B", touch=120, leave=70,
                                      refresh=0x0F)),
            ["B 120 70 20"])

    def test_the_high_bits_of_the_report_rate_are_another_setting(self):
        """Bits 7 to 4 of Refresh_Rate are the width of the pulse on INT."""
        self.assertEqual(self.ask("chip " + config(refresh=0xF5)),
                         ["A 80 50 10"])

    def test_a_configuration_that_does_not_hold_is_unknown(self):
        whole = config()
        broken = whole[:-2] + "%02x" % ((int(whole[-2:], 16) + 1) & 0xFF)
        self.assertEqual(self.ask("chip " + broken, "chip " + whole[:-2],
                                  "chip 41"),
                         ["unknown"] * 3)


if __name__ == "__main__":
    unittest.main()
