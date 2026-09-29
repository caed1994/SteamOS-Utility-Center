# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The backlight of the wall panel, read out of the firmware.

Reported from the board: while the panel sleeps its display swings between
dark and dim, for as long as it sleeps.

The reason is in the board support, which the build prints. The backlight
input is inverted, the timer is ten bits, and brightness_set(0) writes a
duty of 1023 out of 1024. That leaves one LOW slot in every period, which
is an enable pulse of about 200 ns at five thousand a second, and the boost
converter behind the LEDs takes it as a request to start.

None of that is testable here: this container has no ESP-IDF and no board.
What these tests hold is the shape of the answer, so a later change cannot
give the pin back to the hardware that puts those pulses on it, without
failing here first.

The numbers come from the board support and are repeated in panel_display.c
as a note. tests read that note against the log the build prints, so the two
cannot drift apart in silence.
"""

from __future__ import annotations

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
WORKFLOW = os.path.join(REPO, ".github", "workflows",
                        "companion-firmware.yml")


class BacklightTest(unittest.TestCase):
    def source(self, name=None):
        with open(name or os.path.join(FIRMWARE, "panel_display.c")) as handle:
            return handle.read()

    def part(self, name):
        """The body of one function of that file."""
        text = self.source()
        start = text.index(name)
        return text[start:text.index("\n}", start)]

    def constant(self, name):
        found = re.search(r"#define %s (\d+)" % name, self.source())
        self.assertTrue(found, name)
        return int(found.group(1))

    def test_the_pin_is_read_more_than_one_time(self):
        """A single read lands at one point of a 200 us period. A duty of
        1023 of 1024 reads high on all but one try in a thousand, which is
        the fault here and looks exactly like a pin that is held."""
        self.assertGreaterEqual(self.constant("BACKLIGHT_SAMPLES"), 100)
        self.assertIn("backlight_high_reads", self.source())

    def test_the_step_does_not_divide_the_period(self):
        """Or every sample lands at the same point of it and the walk across
        the phase never happens. The period is 1/5000 s, which is 200 us."""
        step = self.constant("BACKLIGHT_SAMPLE_STEP_US")
        self.assertNotEqual(200 % step, 0, "the step divides the period")
        self.assertLess(step, 200, "a step past the period reads one point")

    def test_the_samples_cover_more_than_one_period(self):
        samples = self.constant("BACKLIGHT_SAMPLES")
        step = self.constant("BACKLIGHT_SAMPLE_STEP_US")
        self.assertGreater(samples * step, 200 * 5, "fewer than five periods")

    def test_the_reads_come_from_a_pin_whose_input_is_on(self):
        """GPIO_MODE_OUTPUT switches the input buffer off, so gpio_get_level
        gave 0 for every state of the pad. The log then said the pin was not
        held, and no read of it took place."""
        text = self.source()
        self.assertIn("GPIO_MODE_INPUT_OUTPUT", text)
        self.assertNotIn("GPIO_MODE_OUTPUT", text)

    def test_it_holds_the_pin_the_way_the_board_said_works(self):
        """240 of 240 after ledc_stop, and 240 of 240 as a plain output. The
        two are the same at the pin, so the pad never needed taking away and
        the takeover only made LEDC warn on the next wake."""
        body = self.part("static void backlight_off")
        self.assertIn("ledc_stop", body)
        self.assertEqual(body.count("backlight_high_reads()"), 1)
        text = self.source()
        self.assertNotIn("gpio_reset_pin", text)
        self.assertNotIn("esp_rom_gpio_pad_select_gpio", text)

    def test_the_log_names_the_reading_and_the_dark_level(self):
        body = self.part("static void backlight_off")
        self.assertIn("held", body)
        self.assertIn("esp_err_to_name(err)", body)
        self.assertIn("BACKLIGHT_OFF_LEVEL", body)

    def test_the_measurement_stays(self):
        """It is seven milliseconds once per sleep, and it is the one thing
        in this file that the board agrees with."""
        self.assertIn("backlight_high_reads", self.part(
            "static void backlight_off"))

    def test_waking_needs_nothing_given_back(self):
        """The pin never leaves LEDC now, so there is no pad to hand over
        and no warning that LEDC cannot have it."""
        body = self.part("static esp_err_t backlight_on")
        self.assertIn("bsp_display_brightness_set(brightness)", body)
        self.assertNotIn("ledc_channel_config", body)

    def test_the_drawing_stops_before_the_light_does(self):
        """The backlight fades over some milliseconds, and a half-drawn
        frame during that fade is visible."""
        body = self.part("esp_err_t panel_display_standby")
        sleeping = body[body.index("if(sleep){"):body.index("}else{")]
        self.assertLess(sleeping.index("panel_ui_sleep"),
                        sleeping.index("backlight_off"))

    def test_the_note_gives_the_numbers_it_reasons_from(self):
        """They came out of the board support, which is in no repository.
        Somebody reading this file has to see them without a build."""
        text = self.source()
        for number in ("GPIO_NUM_4", "LEDC_TIMER_10_BIT", "5000", "1023"):
            self.assertIn(number, text, number)

    def test_the_build_still_prints_what_it_reasons_from(self):
        """Or the numbers in that note become a claim nobody can check."""
        text = self.source(WORKFLOW)
        self.assertIn("LCD_backlight_timer", text)
        self.assertIn("brightness_set", text)


class StandbyOrderTest(unittest.TestCase):
    """What a failed wake leaves behind.

    A wake that cannot reach the hardware has to put the panel back to
    sleep, or the window says awake while the screen stays dark.
    """

    def test_a_failed_wake_goes_back_to_sleep(self):
        with open(os.path.join(FIRMWARE, "panel_display.c")) as handle:
            text = handle.read()
        start = text.index("esp_err_t panel_display_standby")
        body = text[start:text.index("\n}\n", start)]
        waking = body[body.index("}else{"):]
        self.assertIn("backlight_off", waking)
        self.assertIn("return err", waking)

    def test_the_state_changes_only_after_the_hardware_agreed(self):
        with open(os.path.join(FIRMWARE, "main.c")) as handle:
            text = handle.read()
        found = re.search(r"panel_display_standby\(sleep,[^)]*\);\s*"
                          r"if\(err==ESP_OK\)\{", text)
        self.assertTrue(found, "the standby result is not checked in main.c")


if __name__ == "__main__":
    unittest.main()
