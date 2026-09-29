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


def without_comments(text):
    """The C with its comments taken out.

    Every rule below reads calls. This file explains itself at length, and
    three checks in this project gave their answer from a word in a comment
    rather than from the code beside it.
    """
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


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

    def test_nothing_here_touches_the_backlight_pin(self):
        """The fault this rule exists for.

        A read of the pin needs its input buffer on, so the version that
        measured it called gpio_set_direction. That call routes the pad to
        the simple GPIO output and takes it away from LEDC, and after one
        sleep the backlight was on no PWM at all: the brightness slider
        moved nothing and the dimming did nothing.

        The board support owns that pin. This file asks it for a
        brightness and touches nothing else.
        """
        code = without_comments(self.source())
        found = sorted(set(re.findall(r"\b(gpio_\w+|esp_rom_gpio_\w+|"
                                      r"ledc_\w+)\s*\(", code)))
        self.assertEqual(found, [], "these take the pin away from the board "
                                    "support that owns it")

    def test_the_rule_above_reads_calls_and_not_comments(self):
        """This file explains itself at length, and a rule a comment can
        break is not a rule."""
        self.assertIn("gpio_set_direction", self.source())
        self.assertNotIn("gpio_set_direction",
                         without_comments(self.source()))

    def test_sleep_dims_and_does_not_try_to_switch_off(self):
        """Measured on the board: the pin held low is full brightness, the
        pin held high swings, and the board support names no rail and no
        backlight enable. A level is not a request this driver answers."""
        body = self.part("static void backlight_off")
        self.assertIn("BACKLIGHT_SLEEP_PERCENT", body)
        self.assertIn("bsp_display_brightness_set", body)
        # The names it found, and not the file it found them in. An
        # assertion that puts the whole of panel_display.c into a failure
        # hides the one word that matters.
        text = self.source()
        found = [gone for gone in ("ledc_stop(", "ledc_set_duty(",
                                   "gpio_reset_pin(",
                                   "esp_rom_gpio_pad_select_gpio(")
                 if gone in text]
        self.assertEqual(found, [], "these were tried and measured, and the "
                                    "board said no")

    def test_the_sleeping_brightness_is_above_zero_and_low(self):
        """Zero is the state that swings. The slider on the settings page
        already stops at five, so five is the floor this shares."""
        percent = self.constant("BACKLIGHT_SLEEP_PERCENT")
        self.assertGreater(percent, 0)
        self.assertLessEqual(percent, 20)

    def test_the_log_names_the_reading_and_what_was_asked_for(self):
        body = self.part("static void backlight_off")
        self.assertIn("BACKLIGHT_SLEEP_PERCENT", body)
        self.assertIn("esp_err_to_name(err)", body)

    def test_the_window_says_the_screen_dims_rather_than_goes_dark(self):
        """A wall that glows with no explanation is a fault report waiting
        to happen."""
        body = self.part("esp_err_t panel_display_standby")
        self.assertIn("as dark", body)

    def test_waking_needs_nothing_given_back(self):
        """The pin never leaves LEDC, so there is no pad to hand over and no
        warning that LEDC cannot have it."""
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
        """They came out of the board support and off the board, and neither
        is in this repository. Somebody reading this file has to see them
        without a build and without the hardware."""
        text = self.source()
        for number in ("GPIO_NUM_4", "LEDC_TIMER_10_BIT", "5000", "1023",
                       "1024"):
            self.assertIn(number, text, number)

    def test_the_build_still_prints_what_it_reasons_from(self):
        """Or the numbers in that note become a claim nobody can check."""
        text = self.source(WORKFLOW)
        self.assertIn("LCD_backlight_timer", text)
        self.assertIn("brightness_set", text)


class SleepingScreenTest(unittest.TestCase):
    """What a sleeping panel shows, since it cannot go dark.

    Stopping the drawing keeps the last frame, and a dimmed page of buttons
    at five percent is a panel that looks switched on. A black object over
    the whole screen, painted before the drawing stops, is one that looks
    switched off.
    """

    def source(self, name):
        with open(os.path.join(FIRMWARE, name)) as handle:
            return handle.read()

    def sleeping(self):
        text = without_comments(self.source("panel_ui_sleep.c"))
        start = text.index("void panel_ui_sleep(")
        body = text[start:]
        return body[body.index("if(sleep){"):body.index("}else{")]

    def test_the_cover_goes_on_before_the_drawing_stops(self):
        """After the pause, nothing reaches the screen."""
        body = self.sleeping()
        self.assertLess(body.index("lv_refr_now"),
                        body.index("lv_display_enable_invalidation"))

    def test_the_cover_is_black_and_covers_everything(self):
        text = without_comments(self.source("panel_ui_sleep.c"))
        self.assertIn("lv_color_black()", text)
        self.assertIn("LV_OPA_COVER", text)
        self.assertIn("lv_display_get_horizontal_resolution", text)
        self.assertIn("lv_display_get_vertical_resolution", text)

    def test_it_is_made_one_time_and_kept(self):
        """An allocation at each sleep is one on a path that has to work
        when memory is short.

        The guard and not the count of the calls. Counting "lv_obj_create("
        passed a version with the guard taken out, because taking it out
        changes how often the one call runs and not how often it is
        written.
        """
        text = without_comments(self.source("panel_ui_sleep.c"))
        start = text.index("cover_for")
        body = text[start:text.index("\n}", start)]
        guard = re.search(r"if\s*\(\s*cover\s*\)\s*return\s+cover\s*;",
                          body)
        self.assertTrue(guard, "nothing stops a second cover being made")
        self.assertLess(guard.start(), body.index("lv_obj_create("))
        self.assertIn("LV_OBJ_FLAG_HIDDEN", text)

    def test_a_cleaned_screen_forgets_the_cover(self):
        """A change of language cleans the screen, and the cover is a child
        of it. Keeping the pointer is a use of a deleted object."""
        self.assertIn("panel_ui_sleep_reset",
                      without_comments(self.source("panel_ui_sleep.c")))
        ui = without_comments(self.source("ui.c"))
        self.assertIn("panel_ui_sleep_reset()", ui)
        self.assertLess(ui.index("lv_obj_clean(s)"),
                        ui.index("panel_ui_sleep_reset()"))

    def test_the_check_that_runs_it_asks_about_the_cover(self):
        with open(os.path.join(REPO, "firmware", "companion", "preview",
                               "check_power.c")) as handle:
            check = without_comments(handle.read())
        self.assertIn("covered(screen)", check)
        self.assertIn("assert(!covered(screen))", check)
        self.assertIn("panel_ui_sleep_reset()", check)

    def test_the_build_runs_those_checks(self):
        """They link against the LVGL the firmware build downloads, so CI
        is the one place that can build them. Nothing ran them before, and
        two of them did not link."""
        with open(WORKFLOW) as handle:
            flow = handle.read()
        for one in ("check_power", "check_idle", "check_navigation"):
            self.assertIn("./preview-build/" + one, flow, one)

    def test_the_preview_build_knows_what_ui_needs(self):
        """ui.c calls into panel_text.c and panel_ui_sleep.c. A target that
        links ui.c without them does not link at all."""
        with open(os.path.join(REPO, "firmware", "companion", "preview",
                               "CMakeLists.txt")) as handle:
            cmake = handle.read()
        for one in ("panel_text.c", "panel_ui_sleep.c"):
            self.assertIn(one, cmake, one)


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
