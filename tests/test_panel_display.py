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

    def test_the_pin_leaves_the_matrix_that_was_pulsing_it(self):
        """The whole fix. ledc_stop alone did not hold on the board, and
        this makes the reason for that beside the point."""
        text = self.source()
        self.assertIn("gpio_config", text)
        self.assertIn("GPIO_MODE_OUTPUT", text)

    def test_the_level_it_is_held_at_is_the_dark_one(self):
        """Inverted: a HIGH is dark. A pull-up therefore pulls towards dark,
        which is why one is enabled."""
        text = self.source()
        self.assertIn("#define BACKLIGHT_OFF_LEVEL 1", text)
        self.assertIn("GPIO_PULLUP_ENABLE", text)

    def test_waking_gives_the_pin_back_before_the_brightness_is_set(self):
        """brightness_set writes a duty, and a duty reaches nothing while
        the pin belongs to the GPIO matrix.

        The call and not the name. The first version of this looked for
        "ledc_channel_config", which is also the first half of the type in
        the declaration above the call, so it passed whichever order the
        two were in. Measured: the mutation went through.
        """
        text = self.source()
        start = text.index("static esp_err_t backlight_on")
        body = text[start:text.index("\n}", start)]
        self.assertLess(body.index("ledc_channel_config(&channel)"),
                        body.index("bsp_display_brightness_set(brightness)"))

    def test_the_drawing_stops_before_the_light_does(self):
        """The backlight fades over some milliseconds, and a half-drawn
        frame during that fade is visible."""
        body = self.standby()
        sleeping = body[body.index("if(sleep){"):body.index("}else{")]
        self.assertLess(sleeping.index("panel_ui_sleep"),
                        sleeping.index("backlight_off"))

    def test_the_channel_it_restores_is_the_one_the_board_support_made(self):
        """A different timer or resolution is a different brightness curve."""
        text = self.source()
        for named in ("BSP_LCD_BACKLIGHT",
                      "CONFIG_BSP_DISPLAY_BRIGHTNESS_LEDC_CH",
                      "LEDC_TIMER_1"):
            self.assertIn(named, text, named)

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
