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

    def standby(self):
        """The body of panel_display_standby, and nothing around it."""
        text = self.source()
        start = text.index("esp_err_t panel_display_standby")
        return text[start:text.index("\n}", start)]

    def test_off_means_the_full_scale_and_not_one_below_it(self):
        """The whole fault. The board support writes 1023 for off and full
        scale at ten bits is 1024, so one LOW slot stays in every period."""
        text = self.source()
        self.assertIn("#define BACKLIGHT_DUTY_BITS 10", text)
        self.assertIn("#define BACKLIGHT_FULL_DUTY (1 << BACKLIGHT_DUTY_BITS)",
                      text)
        start = text.index("static void backlight_off")
        body = text[start:text.index("\n}", start)]
        self.assertIn("ledc_set_duty", body)
        self.assertIn("BACKLIGHT_FULL_DUTY", body)
        self.assertIn("ledc_update_duty", body)

    def test_the_duty_is_one_more_than_the_board_support_ever_writes(self):
        """Arithmetic, so the two numbers cannot drift apart in a comment."""
        text = self.source()
        bits = int(re.search(r"#define BACKLIGHT_DUTY_BITS (\d+)",
                             text).group(1))
        self.assertEqual(1 << bits, 1024)
        self.assertEqual((1 << bits) - 1, 1023)

    def test_the_pin_stays_with_the_driver_that_owns_it(self):
        """Taking the pad away was tried on the board. It left the swinging,
        and the next wake logged "GPIO 4 is not usable, maybe conflict with
        others", because a pad a driver reserved does not come back
        quietly."""
        text = self.source()
        self.assertNotIn("esp_rom_gpio_pad_select_gpio", text)
        self.assertNotIn("gpio_config(", text)

    def test_the_read_back_comes_from_a_pin_whose_input_is_on(self):
        """GPIO_MODE_OUTPUT switches the input buffer off, so gpio_get_level
        gave 0 for every state of the pad. The log then said the pin was not
        held, and no read of it took place."""
        text = self.source()
        self.assertIn("GPIO_MODE_INPUT_OUTPUT", text)
        self.assertNotIn("GPIO_MODE_OUTPUT,", text)
        self.assertIn("gpio_get_level(BACKLIGHT_PIN)", text)

    def test_the_log_says_what_it_set_and_whether_it_worked(self):
        """A report of "it still flickers" has to arrive with the duty, the
        result of setting it, and the level the pin reads."""
        text = self.source()
        start = text.index("static void backlight_off")
        body = text[start:text.index("\n}", start)]
        self.assertIn("esp_err_to_name(err)", body)
        self.assertIn("gpio_get_level", body)

    def test_waking_needs_nothing_given_back(self):
        text = self.source()
        start = text.index("static esp_err_t backlight_on")
        body = text[start:text.index("\n}", start)]
        self.assertIn("bsp_display_brightness_set(brightness)", body)
        self.assertNotIn("ledc_channel_config", body)

    def test_the_drawing_stops_before_the_light_does(self):
        """The backlight fades over some milliseconds, and a half-drawn
        frame during that fade is visible."""
        body = self.standby()
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
