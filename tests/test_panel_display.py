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
        """Zero is the state that swings. Five is the lowest brightness the
        board held steady when the slider went down to one."""
        percent = self.constant("BACKLIGHT_SLEEP_PERCENT")
        self.assertGreater(percent, 0)
        self.assertLessEqual(percent, 20)

    def test_the_slider_stops_where_the_sleep_does(self):
        """The settings page, the start of the panel and a sleeping panel
        share one floor. A slider under it reaches a brightness that does
        not hold steady, and a panel set there gets lighter as it sleeps.
        A stored value under it is thrown away at the start."""
        header = self.source(os.path.join(FIRMWARE, "ui.h"))
        found = re.search(r"#define PANEL_BRIGHTNESS_MIN (\d+)", header)
        self.assertTrue(found)
        self.assertEqual(int(found.group(1)),
                         self.constant("BACKLIGHT_SLEEP_PERCENT"))
        ui = without_comments(self.source(os.path.join(FIRMWARE, "ui.c")))
        self.assertIn("slider_at(display,88,PANEL_BRIGHTNESS_MIN,"
                      "local.brightness,PANEL_BRIGHTNESS)", ui)
        main = without_comments(self.source(os.path.join(FIRMWARE, "main.c")))
        self.assertIn('nvs_get_u8(h,"brightness",&value)==ESP_OK && '
                      'value>=PANEL_BRIGHTNESS_MIN && value<=100', main)

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


class StandbyClockTest(unittest.TestCase):
    """The clock on the black cover of a sleeping panel.

    It has to cost a sleep almost nothing. A tick of a sleep asks for it
    five times a second, and a minute it has shown is answered at once. A
    new minute draws the line that changed and nothing else, and the
    sleeping display takes no invalidation after that. check_power counts
    the draws and the areas, and these hold the order of the calls.
    """

    def source(self, name):
        with open(os.path.join(FIRMWARE, name)) as handle:
            return without_comments(handle.read())

    def function(self, text, head):
        start = text.index(head)
        return text[start:text.index("\n}", start)]

    def test_a_minute_it_has_shown_costs_a_comparison(self):
        body = self.function(self.source("main.c"),
                             "static void standby_clock(")
        self.assertIn("time(NULL)/60", body)
        self.assertLess(body.index("minute==shown)return;"),
                        body.index("panel_time_now("))

    def test_the_clock_is_on_the_cover_before_the_cover_is_drawn(self):
        body = self.function(self.source("main.c"),
                             "static void display_sleeping(")
        self.assertLess(body.index("if(sleep)standby_clock(true);"),
                        body.index("panel_display_standby("))

    def test_each_tick_of_a_sleep_asks_for_it(self):
        body = self.function(self.source("main.c"), "static void ui_tick(")
        ask = body.index("if(atomic_load(&display_asleep))standby_clock(false);")
        self.assertLess(ask, body.index(
            "if(atomic_load(&display_asleep)&&!due)return;"))

    def test_the_same_text_draws_nothing(self):
        body = self.function(self.source("panel_ui_sleep.c"),
                             "void panel_ui_sleep_clock(")
        same = body.index("strcmp(lv_label_get_text(cover_alarm_text), alarm) == 0)) return;")
        self.assertLess(same, body.index("lv_display_enable_invalidation"))

    def test_a_sleeping_display_gets_its_invalidation_back(self):
        """On for the change, and off again after the one draw."""
        body = self.function(self.source("panel_ui_sleep.c"),
                             "void panel_ui_sleep_clock(")
        on = body.index("if (sleeping) lv_display_enable_invalidation(screen, true);")
        draw = body.index("lv_refr_now(screen);")
        off = body.index("lv_display_enable_invalidation(screen, false);")
        self.assertLess(on, draw)
        self.assertLess(draw, off)

    def test_a_second_call_the_same_way_does_nothing(self):
        """LVGL counts each switch of the invalidation, so a second wake
        would leave the next sleep with it on."""
        body = self.function(self.source("panel_ui_sleep.c"),
                             "void panel_ui_sleep(")
        self.assertLess(body.index("if(sleep==sleeping)return;"),
                        body.index("lv_display_enable_invalidation"))

    def test_it_holds_no_font_of_its_own(self):
        """The font of the clock page and one of the band: nothing new in
        flash."""
        text = self.source("panel_ui_sleep.c")
        self.assertIn("&panel_clock_font", text)
        self.assertIn("&panel_font_24", text)
        with open(os.path.join(REPO, "firmware", "companion", "preview",
                               "CMakeLists.txt")) as handle:
            cmake = handle.read()
        start = cmake.index("add_executable(check_power")
        target = cmake[start:cmake.index(")", start)]
        for one in ("panel_ui_sleep.c", "panel_clock_font.c", "panel_font_24.c"):
            self.assertIn(one, target)

    def test_the_check_counts_what_it_draws(self):
        with open(os.path.join(REPO, "firmware", "companion", "preview",
                               "check_power.c")) as handle:
            check = without_comments(handle.read())
        self.assertIn("panel_ui_sleep_clock(screen,", check)
        self.assertIn("LV_EVENT_INVALIDATE_AREA", check)
        self.assertIn("LV_DISPLAY_RENDER_MODE_PARTIAL", check)


class WhiteFlashTest(unittest.TestCase):
    """The flash of white the board showed before the startup animation.

    bsp_display_new sets up the LEDC channel with a duty of 0. The input of
    this backlight is inverted, so a duty of 0 is full brightness, and from
    that moment the panel is lit at its maximum over a frame buffer that
    holds whatever the memory held.

    Two lines answer it and the order of both is the whole of the fix: the
    light goes down as early as the code can reach, and it comes back up
    only once a frame worth seeing is on the screen.
    """

    def read(self, name):
        with open(os.path.join(FIRMWARE, name)) as handle:
            return handle.read()

    def test_the_light_goes_down_the_moment_the_panel_exists(self):
        """The next statement, and not a few lines later. Everything
        between the two is time the board spends showing white."""
        code = without_comments(self.read("panel_display.c"))
        found = re.search(r"bsp_display_new\([^;]*\);\s*"
                          r"bsp_display_brightness_set\(", code)
        self.assertTrue(found,
                        "something runs between the panel coming up and the "
                        "light going down")

    def test_it_goes_down_to_a_brightness_this_board_holds_steady(self):
        """Nought writes a duty of 1023, which leaves one LOW slot in every
        period and makes the converter hiccup. See backlight_off."""
        code = without_comments(self.read("panel_display.c"))
        self.assertIn("bsp_display_brightness_set(BACKLIGHT_SLEEP_PERCENT)",
                      code)

    def test_the_screen_is_painted_black_before_anything_else(self):
        """The brightness makes the white dim. This makes it black."""
        code = without_comments(self.read("panel_display.c"))
        start = code.index("panel_display_start")
        body = code[start:code.index("\n}", start)]
        self.assertIn("lv_color_black()", body)
        self.assertIn("lv_refr_now", body)

    def test_the_light_comes_up_after_the_first_frame_and_not_before(self):
        """Without the draw, the LVGL task gets to the frame at some later
        moment and the brightness beats it there, which is the flash
        again."""
        code = without_comments(self.read("main.c"))
        shown = code.index("panel_boot_show(")
        drawn = code.index("lv_refr_now", shown)
        lit = code.index("setting_set(PANEL_BRIGHTNESS", shown)
        self.assertLess(drawn, lit,
                        "the light comes up before the frame is drawn")

    def test_nothing_sets_the_brightness_before_the_screen_is_built(self):
        """It was on the line after the settings were read, which is before
        the screen exists at all."""
        code = without_comments(self.read("main.c"))
        built = code.index("panel_ui_create(action_send")
        first = code.index("setting_set(PANEL_BRIGHTNESS")
        self.assertGreater(first, built,
                           "the brightness is set before there is anything "
                           "to show")


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
        """Written against the order and not against the spelling. The
        early return and the wrapping if say the same thing, and a rule
        that knows only one of them fails the next time somebody turns
        the condition round."""
        with open(os.path.join(FIRMWARE, "main.c")) as handle:
            text = handle.read()
        door = re.search(r"static void display_sleeping\(.*?\n\}", text, re.S)
        self.assertIsNotNone(door, "nothing in main.c changes the standby")
        body = door.group(0)
        self.assertIn("panel_display_standby(sleep,", body)
        looked = body.index("err")
        changed = body.index("atomic_store(&display_asleep")
        self.assertLess(looked, changed,
                        "the state is changed before the hardware answered")
        self.assertIn("return", body[looked:changed],
                      "a standby that failed has to leave the state alone")


if __name__ == "__main__":
    unittest.main()


class TearingTest(unittest.TestCase):
    """The pair that keeps the display swapping buffers instead of copying.

    Reported from the board: small tears ran through the startup animation.
    The answer was two frame buffers and a flush that swaps them at a frame
    boundary, which esp_lvgl_port calls avoid_tearing.

    None of it can run here. What these hold is the shape, because every way
    this breaks is quiet: the panel draws a correct picture and tears again,
    and nothing says so.
    """

    def source(self):
        with open(os.path.join(FIRMWARE, "panel_display.c"),
                  encoding="utf-8") as handle:
            return without_comments(handle.read())

    def test_the_swap_is_asked_for(self):
        self.assertRegex(self.source(), r"\.avoid_tearing\s*=\s*true")

    def test_it_is_asked_for_beside_one_of_the_two_modes_it_needs(self):
        """avoid_tearing alone is a display that tears.

        esp_lvgl_port takes the panel's frame buffers whatever the mode is.
        The flush swaps them only for direct_mode or full_refresh: read
        lvgl_port_flush_callback, which asks for those two by name. Without
        either it falls through its chain to partial mode over a
        screen-sized buffer, and the driver copies again.
        """
        code = self.source()
        if not re.search(r"\.avoid_tearing\s*=\s*true", code):
            self.skipTest("nothing asks for the swap")
        self.assertRegex(code, r"\.(direct_mode|full_refresh)\s*=\s*true",
                         "avoid_tearing without direct_mode or full_refresh "
                         "draws a correct picture and tears again")

    def test_the_panel_holds_more_than_one_frame_buffer(self):
        """One buffer makes the request for the second fail, and the whole
        display comes back NULL. The count is a Kconfig, so it lives in
        sdkconfig.defaults, and a _Static_assert here fails the build when
        it stops taking effect."""
        defaults = os.path.join(os.path.dirname(FIRMWARE),
                                "sdkconfig.defaults")
        with open(defaults, encoding="utf-8") as handle:
            self.assertRegex(handle.read(),
                             r"(?m)^CONFIG_BSP_LCD_RGB_BUFFER_NUMS=([2-9]|\d\d)")
        self.assertRegex(self.source(),
                         r"_Static_assert\(\s*CONFIG_BSP_LCD_RGB_BUFFER_NUMS"
                         r"\s*>=\s*2")

    def test_the_draw_buffer_is_checked_against_the_panel_buffers(self):
        """The one guard that catches a flush gone back to copying."""
        code = self.source()
        self.assertIn("esp_lcd_rgb_panel_get_frame_buffer", code)
        self.assertRegex(code, r"ESP_RETURN_ON_FALSE\(\s*own\s*,")

    def test_the_log_says_which_mode_it_ended_up_in(self):
        """A person reading a serial log has no other way to tell."""
        code = self.source()
        # The text is split over several C string literals, so this takes
        # the whole call and not the first piece of it.
        said = re.search(r'ESP_LOGI\([^;]*?"RGB: .*?\);', code, re.S)
        self.assertIsNotNone(said, "nothing logs how the display came up")
        self.assertRegex(said.group(0), r"direct mode|full refresh")


class LogFloodTest(unittest.TestCase):
    """One complaint from the draw path, repeated thirty times a second.

    LVGL writes a line when it cannot draw something, and it tries again at
    every refresh. Every line goes to ESP_LOG from the task that draws, and
    that task has a frame to fill before the panel asks for the next one.
    A serial port at 115200 baud is slow enough that this shows as a torn
    screen, and then as a watchdog.

    The picture of the game found this: a JPEG that LVGL refused sat on the
    card and complained once per frame for as long as it was up.
    """

    def source(self):
        with open(os.path.join(FIRMWARE, "panel_display.c"),
                  encoding="utf-8") as handle:
            return without_comments(handle.read())

    def routing(self):
        code = self.source()
        found = re.search(r"static void lvgl_log\(.*?\n\}", code, re.S)
        self.assertIsNotNone(found, "nothing hands LVGL's lines to ESP_LOG")
        return found.group(0)

    def test_a_repeat_is_counted_and_not_written(self):
        body = self.routing()
        self.assertIn("last_line", body)
        self.assertRegex(body, r"strncmp\(text,last_line,keep\)==0")
        self.assertRegex(body, r"repeats%LOG_REPEATS\)return")

    def test_the_line_still_comes_out_now_and_then(self):
        """A fault that never stops must not go quiet either. The count
        stands behind the line that does get through."""
        body = self.routing()
        self.assertIn("and again", body)
        code = self.source()
        every = re.search(r"#define LOG_REPEATS (\d+)", code)
        self.assertIsNotNone(every)
        # Thirty a second, so this is a line every two seconds or so.
        self.assertLessEqual(int(every.group(1)), 128)

    def test_a_reading_is_not_logged_as_a_fault(self):
        """USER stands above ERROR in the order LVGL uses, so a test of
        "at least ERROR" catches it too. The board showed the timing of
        the startup animation, which panel_boot.c writes with LV_LOG_USER,
        arriving in the log as an error."""
        body = self.routing()
        user = body.index("LV_LOG_LEVEL_USER")
        error = body.index("LV_LOG_LEVEL_ERROR")
        self.assertLess(user, error,
                        "USER has to be answered before the test that "
                        "catches everything at ERROR and above")

    def test_the_first_one_is_never_held_back(self):
        """A fault nobody sees at all is worse than a loud one."""
        body = self.routing()
        # repeats is zeroed on a line that differs, and the write below
        # runs for every line that reaches it.
        self.assertRegex(body, r"repeats=0;")


class SliderDragTest(unittest.TestCase):
    """A slider that somebody drags, and the work that runs under it.

    Reported from the board: the sliders of brightness and volume stopped
    for a moment now and then, with the PC on and with it off. Two things
    ran in the task that draws while a finger was down:

    - the board support writes a line at each new brightness, and a drag
      sets one at each read of the touch
    - panel_ui_update wrote every label again at each new state, and with
      no PC the state is new every 5 s: the power chip and the uptime

    Measured on the host with the screen of this firmware and no PC, each
    of those updates drew 14 areas again, 14 % of the screen. After the
    change it draws none. check_idle holds that number.
    """

    UPDATE_PARTS = ("temperatures_show", "esp_power_show", "pads_head",
                    "pads_show", "card_show", "name_show", "history_show",
                    "pc_show", "self_show", "update_layer_show")
    RAW = re.compile(r"lv_label_set_text(?:_fmt)?\(|"
                     r"lv_obj_remove_flag\([^;]*LV_OBJ_FLAG_HIDDEN|"
                     r"lv_obj_add_flag\([^;]*LV_OBJ_FLAG_HIDDEN|"
                     r"lv_obj_set_style_(?:bg|text)_color\(")

    def source(self, name):
        with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
            return without_comments(handle.read())

    def function(self, code, name):
        found = re.search(r"^(?:static )?void %s\([^;{]*\)\s*\{.*?\n\}" % name,
                          code, re.S | re.M)
        self.assertIsNotNone(found, name)
        return found.group(0)

    def test_the_board_support_writes_no_line_per_brightness(self):
        code = self.source("main.c")
        start = code.index("if (!panel_display_start())")
        quiet = code.index('esp_log_level_set("ESP32-S3-Touch-LCD-4B",ESP_LOG_WARN);')
        self.assertLess(start, quiet)

    def test_the_update_writes_through_the_helpers(self):
        code = self.source("ui.c")
        update = self.function(code, "panel_ui_update")
        # The setup page writes its long text itself and returns.
        update = update[update.index("set_text(connection,"):]
        self.assertEqual(self.RAW.findall(update), [])
        for name in self.UPDATE_PARTS:
            self.assertEqual(self.RAW.findall(self.function(code, name)), [], name)

    def test_the_helpers_write_a_change_only(self):
        code = self.source("ui.c")
        text = self.function(code, "set_text")
        self.assertLess(text.index("strcmp(lv_label_get_text(label),text)!=0"),
                        text.index("lv_label_set_text(label,text)"))
        self.assertIn("set_text(label,text);", self.function(code, "set_textf"))
        self.assertIn("lv_color_eq(", self.function(code, "set_bg"))
        self.assertIn("lv_color_eq(", self.function(code, "set_text_colour"))
        self.assertIn("lv_obj_has_flag(o,LV_OBJ_FLAG_HIDDEN)!=shown)return;",
                      self.function(code, "set_shown"))

    def test_a_check_counts_what_an_update_with_no_pc_draws(self):
        with open(os.path.join(REPO, "firmware", "companion", "preview",
                               "check_idle.c"), encoding="utf-8") as handle:
            check = without_comments(handle.read())
        loop = check[check.index("off.self.uptime_s+=5;"):]
        self.assertIn("assert(invalidations==0);", loop)


class TouchZoneTest(unittest.TestCase):
    """The place that takes each tap, 48 px each way.

    Reported from the board: taps that did not land on some places. The hit
    test of LVGL over every screen found zones of 28 to 46 px, most of them
    the 44 of a button with no room past its edge. check_touch walks every
    screen with that hit test and holds the size. These hold that the check
    runs, and the rule that most of the buttons take their room from.
    """

    def read(self, *parts):
        with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
            return handle.read()

    def test_every_button_takes_a_press_past_its_edge(self):
        code = without_comments(self.read("firmware", "companion", "main", "ui.c"))
        reach = re.search(r"#define BUTTON_REACH (\d+)", code)
        self.assertIsNotNone(reach)
        # 44 high, the height of most of them, and 48 with the room.
        self.assertGreaterEqual(44 + 2 * int(reach.group(1)), 48)
        button = re.search(r"static lv_obj_t \*button\(.*?\n\}", code, re.S).group(0)
        self.assertIn("lv_obj_set_ext_click_area(b,BUTTON_REACH);", button)

    def test_the_check_holds_48_and_runs_in_the_build(self):
        check = self.read("firmware", "companion", "preview", "check_touch.c")
        self.assertIn("#define ZONE 48", check)
        self.assertIn("#define EDGE_ZONE 44", check)
        self.assertIn("lv_indev_search_obj(", check)
        cmake = self.read("firmware", "companion", "preview", "CMakeLists.txt")
        self.assertIn("add_executable(check_touch check_touch.c ${PANEL_UI_SOURCES})", cmake)
        with open(WORKFLOW, encoding="utf-8") as handle:
            workflow = handle.read()
        self.assertIn("./preview-build/check_touch", workflow)


class DrawingStackTest(unittest.TestCase):
    """The stack of the task that draws.

    The board reported it in one line and then kept restarting:

        ***ERROR*** A stack overflow in task taskLVGL has been detected.

    It fell over at the end of the startup animation and again the moment
    the screen went to standby, and every restart ran into the next one.

    Two things follow. The size is said here rather than taken from
    ESP_LVGL_PORT_INIT_CONFIG, which carries a number of its own and
    Espressif raised that number once before. What is left of it is
    measured too,
    because a size nobody checks is a guess.
    """

    def source(self):
        with open(os.path.join(FIRMWARE, "panel_display.c"),
                  encoding="utf-8") as handle:
            return without_comments(handle.read())

    def main(self):
        with open(os.path.join(FIRMWARE, "main.c"), encoding="utf-8") as h:
            return without_comments(h.read())

    def test_the_size_is_said_and_not_taken(self):
        code = self.source()
        self.assertRegex(code, r"port\.task_stack\s*=")
        said = re.search(r"#define PANEL_LVGL_STACK \(?(\d+)\s*\*\s*1024", code)
        self.assertIsNotNone(said, "the stack has no size of its own here")
        # Twelve kilobytes is the least that ran on the board without the
        # overflow coming back. The readings that raised it to sixteen and
        # then twenty-four were of the start task: see the next rule.
        self.assertGreaterEqual(int(said.group(1)) * 1024, 12 * 1024)
        # The health lines of the board read 15548 and 15452 of 24576
        # bytes left, so the task used 9124 at the most. The stack holds
        # that and 6 KB over it.
        self.assertGreaterEqual(int(said.group(1)) * 1024, 9124 + 6 * 1024)

    def test_one_place_holds_the_number(self):
        """The health line prints the headroom against the whole. Two
        copies of the whole would drift apart and the reading would then
        say nothing."""
        self.assertIn("panel_display_stack_bytes", self.source())
        self.assertIn("panel_display_stack_bytes", self.main())

    def test_the_reading_is_taken_on_the_task_that_draws(self):
        """uxTaskGetStackHighWaterMark(NULL) answers about the caller. The
        health line runs on the network task, so a reading taken there is
        about the task that did not run out."""
        code = self.main()
        watch = re.search(r"static void watch_stack\(void\).*?\n\}", code, re.S)
        self.assertIsNotNone(watch, "nothing watches the drawing stack")
        self.assertIn("uxTaskGetStackHighWaterMark(NULL)", watch.group(0))
        tick = re.search(r"static void ui_tick\(lv_timer_t \*timer\).*?\n\}",
                         code, re.S)
        self.assertIsNotNone(tick)
        self.assertIn("watch_stack()", tick.group(0),
                      "the reading has to be taken from the LVGL timer, "
                      "which is the drawing task")

    def test_the_call_from_app_main_is_not_read(self):
        """app_main calls ui_tick once itself, on the start task. Read off
        the board: that one call put 716 of 24576 on the health line, the
        stack of the start task against the size of this one, and the
        number only ever goes down."""
        code = self.main()
        tick = re.search(r"static void ui_tick\(lv_timer_t \*timer\).*?\n\}",
                         code, re.S).group(0)
        self.assertIn("if(timer)watch_stack();", tick)
        start = re.search(r"void app_main\(void\).*?\n\}", code, re.S).group(0)
        self.assertIn("ui_tick(NULL);", start,
                      "the rule above is about this call; without it, it "
                      "guards nothing")

    def test_the_start_task_has_room_and_says_what_it_used(self):
        """3584 bytes had about 700 left. It is freed when app_main
        returns, so a larger one costs nothing after the start."""
        with open(os.path.join(os.path.dirname(FIRMWARE), "sdkconfig.defaults"),
                  encoding="utf-8") as handle:
            defaults = handle.read()
        found = re.search(r"(?m)^CONFIG_ESP_MAIN_TASK_STACK_SIZE=(\d+)$", defaults)
        self.assertIsNotNone(found)
        self.assertGreaterEqual(int(found.group(1)), 3584 + 2048)
        start = re.search(r"void app_main\(void\).*?\n\}", self.main(),
                          re.S).group(0)
        tail = start[start.index("xTaskCreatePinnedToCore(network_task"):]
        self.assertIn("uxTaskGetStackHighWaterMark(NULL)", tail)
        self.assertIn("CONFIG_ESP_MAIN_TASK_STACK_SIZE", tail)

    def test_the_headroom_reaches_the_health_line(self):
        code = self.main()
        said = re.search(r'ESP_LOGI\("panel_health"[^;]*;', code, re.S)
        self.assertIsNotNone(said)
        self.assertIn("ui_stack=", said.group(0))

    def test_a_deeper_stack_says_where_the_panel_was(self):
        """The health line said how deep, never when. Each new low by a
        step goes to the log with what the screen showed, so the place
        that needs the stack can be found."""
        code = self.main()
        watch = re.search(r"static void watch_stack\(void\).*?\n\}", code,
                          re.S).group(0)
        self.assertRegex(code, r"#define PANEL_STACK_STEP \d+")
        self.assertIn("PANEL_STACK_STEP", watch)
        self.assertEqual(watch.count("panel_place()"), 2,
                         "the warning and the line above the floor both "
                         "name the place")
        place = re.search(r"static const char \*panel_place\(void\).*?\n\}",
                          code, re.S)
        self.assertIsNotNone(place)
        for source in ("panel_boot_playing()", "display_asleep",
                       "panel_ui_where()"):
            self.assertIn(source, place.group(0))

    def test_it_says_so_before_it_runs_out(self):
        """A floor above nought. FreeRTOS reports an overflow once the
        stack is gone, and by then the panel restarts."""
        code = self.main()
        floor = re.search(r"#define PANEL_STACK_FLOOR (\d+)", code)
        self.assertIsNotNone(floor)
        self.assertGreater(int(floor.group(1)), 0)
        self.assertIn("ESP_LOGW", re.search(
            r"static void watch_stack\(void\).*?\n\}", code, re.S).group(0))


class SleepClockTest(unittest.TestCase):
    """The pixel clock of the display, lower in a sleep.

    Read off the board: in a button sleep the CPU spent only about 55 % of
    the time at the low speed. An interrupt on the CPU still copies every
    frame into the bounce buffers, and a lower pixel clock is fewer frames
    to copy.

    It cannot go as low as it once did. At 4 MHz the panel showed each line
    twice, which a black cover hid and the clock on the cover did not. The
    lowest clock this panel was seen to show right is the 12 MHz of the
    startup animation. 8 MHz was tried on the board after it, and the clock
    of the standby stood in the middle with its date."""

    def source(self):
        with open(os.path.join(FIRMWARE, "panel_display.c"),
                  encoding="utf-8") as handle:
            return without_comments(handle.read())

    def standby(self):
        return re.search(r"esp_err_t panel_display_standby\(bool sleep,int "
                         r"brightness\).*?\n\}", self.source(), re.S).group(0)

    def number(self, name):
        found = re.search(r"#define %s\s+(\d+)" % name, self.source())
        self.assertIsNotNone(found, name)
        return int(found.group(1))

    def test_the_sleep_clock_is_lower_and_the_awake_one_is_where_it_was(self):
        # 12 MHz for the startup animation, whose 40 ms frames land on two
        # frames of the panel there, and 16 MHz after it, where a scroll
        # frame of 29 ms lands on two frames of 16.6 ms.
        self.assertEqual(self.number("PANEL_PCLK_BOOT_HZ"), 12000000)
        self.assertEqual(self.number("PANEL_PCLK_HZ"), 16000000)
        self.assertLess(self.number("PANEL_PCLK_SLEEP_HZ"),
                        self.number("PANEL_PCLK_HZ"))
        self.assertIn("esp_lcd_rgb_panel_set_pclk(panel,PANEL_PCLK_BOOT_HZ)",
                      self.source())
        self.assertIn("static uint32_t pclk_awake=PANEL_PCLK_BOOT_HZ;", self.source())
        self.assertIn("panel_rgb=panel;", self.source())

    def test_the_sleep_clock_is_above_the_one_that_failed(self):
        """4 MHz put the clock of the standby at twice its height, cut off
        at the bottom of the screen. 12 MHz was seen right, and 8 MHz, with
        a line of 65 us against the 130 us that failed, is on trial."""
        self.assertGreaterEqual(self.number("PANEL_PCLK_SLEEP_HZ"), 8000000)
        self.assertEqual(self.number("PANEL_PCLK_BOOT_HZ"), 12000000)

    def test_the_note_gives_the_measurement_and_the_way_back(self):
        """The clock was chosen by a look at the board, and the note says
        what was seen, how to look again, and which clock to go back to."""
        with open(os.path.join(FIRMWARE, "panel_display.c"),
                  encoding="utf-8") as handle:
            note = handle.read()
        self.assertIn("Read off the board after a trial", note)
        self.assertIn("between a line of 65 us, which", note)
        self.assertIn("12 MHz is the one to go back to", note)
        self.assertEqual(self.number("PANEL_PCLK_SLEEP_HZ"), 8000000)

    def test_the_scroll_clock_comes_after_the_animation(self):
        over = re.search(r"void panel_display_boot_over\(void\)\s*\{(.*?)\n\}",
                         self.source(), re.S)
        self.assertIsNotNone(over)
        self.assertIn("pclk_awake=PANEL_PCLK_HZ;", over.group(1))
        # A sleeping panel keeps the clock of the sleep.
        self.assertIn("if(panel_rgb && !is_asleep)esp_lcd_rgb_panel_set_pclk(panel_rgb,pclk_awake);",
                      over.group(1))
        with open(os.path.join(FIRMWARE, "main.c"), encoding="utf-8") as handle:
            main = without_comments(handle.read())
        tick = re.search(r"static void ui_tick\(lv_timer_t \*timer\).*?\n\}",
                         main, re.S).group(0)
        # Not from the call of app_main, which comes before the animation.
        self.assertIn("if(timer && !panel_boot_playing())panel_display_boot_over();", tick)

    def test_down_after_the_cover_and_up_before_the_first_frame(self):
        """The slow frames are black ones, and the first frame after a
        wake is drawn at the full rate."""
        code = self.standby()
        going = code[code.index("if(sleep){"):code.index("}else{")]
        coming = code[code.index("}else{"):]
        cover = going.index("panel_ui_sleep(panel_screen,panel_input,true);")
        down = going.index("esp_lcd_rgb_panel_set_pclk(panel_rgb,PANEL_PCLK_SLEEP_HZ)")
        self.assertLess(cover, down)
        up = coming.index("esp_lcd_rgb_panel_set_pclk(panel_rgb,pclk_awake)")
        self.assertLess(up, coming.index("panel_ui_sleep(panel_screen,panel_input,false);"))

    def test_a_wake_that_fails_goes_back_to_the_sleep_clock(self):
        failed = re.search(r"if\(err!=ESP_OK\)\{(.*?)return err;", self.standby(),
                           re.S)
        self.assertIsNotNone(failed)
        self.assertIn("PANEL_PCLK_SLEEP_HZ", failed.group(1))


class SleepTimeoutTest(unittest.TestCase):
    """The display that goes dark by itself, and comes back at a touch.

    The panel hangs on a wall and nobody wants it lit at night. A timeout
    puts it down, and a touch brings it back, which is the whole point of
    a timeout: a panel that needs the button to come back is a panel
    somebody walks to twice.

    The button is the other case and has to stay the other case. A display
    switched off by hand that woke at any touch would come back at the
    sleeve of whoever walks past, which is the opposite of what the button
    was pressed for. So the reason is kept beside the state.
    """

    def main(self):
        with open(os.path.join(FIRMWARE, "main.c"), encoding="utf-8") as h:
            return without_comments(h.read())

    def tick(self):
        code = self.main()
        found = re.search(r"static void ui_tick\(lv_timer_t \*timer\).*?\n\}",
                          code, re.S)
        self.assertIsNotNone(found)
        return found.group(0)

    def test_the_timeout_reads_the_time_since_the_last_touch(self):
        """LVGL keeps that time itself. A count of its own in this panel
        would be a second answer to a question already answered."""
        tick = self.tick()
        self.assertIn("lv_display_get_inactive_time(NULL)", tick)
        # Minutes, because that is what the setting holds.
        self.assertRegex(tick, r"display_sleep_after\s*\*\s*60u?\s*\*\s*1000u?")

    def test_nought_minutes_leaves_the_display_on(self):
        """Off by itself is what somebody asks for, not what they get."""
        self.assertRegex(self.tick(), r"display_sleep_after\s*>\s*0")

    def test_a_touch_wakes_a_display_that_went_down_on_its_own(self):
        tick = self.tick()
        self.assertIn("panel_display_touched()", tick)

    def test_a_touch_leaves_a_display_the_button_switched_off(self):
        """The touch, and since a later firmware the lift, stand inside
        the test of the reason."""
        tick = self.tick()
        guarded = re.search(r"if\(!atomic_load\(&asleep_by_hand\)\)\{(.*?)\n        \}",
                            tick, re.S)
        self.assertIsNotNone(guarded,
                             "the reason has to be read before a touch wakes anything")
        self.assertIn("panel_display_touched()", guarded.group(1))
        self.assertEqual(tick.count("panel_display_touched()"), 1)

    def test_the_button_says_it_was_the_button(self):
        """One door for both, so the state and the reason cannot drift.
        The press goes to a timer that rings first, and to the display
        when none rings: see tests/test_panel_time.py."""
        tick = self.tick()
        press = tick[tick.index("if(panel_power_take_toggle()){"):]
        self.assertRegex(press[:press.index("\n    }")],
                         r"else display_sleeping\(!atomic_load\(&display_asleep\),true\);")

    def test_the_clock_starts_again_at_the_moment_of_waking(self):
        """Without this the panel counts the whole sleep as time with no
        touch and goes straight back down."""
        code = self.main()
        door = re.search(r"static void display_sleeping\(bool sleep,bool by_hand\)"
                         r".*?\n\}", code, re.S)
        self.assertIsNotNone(door)
        self.assertIn("lv_display_trigger_activity(NULL)", door.group(0))

    def test_the_sleeping_panel_is_the_only_one_that_reads_the_touch(self):
        """LVGL reads the same controller on its own timer while the panel
        is awake, and two readers share one bus."""
        with open(os.path.join(FIRMWARE, "panel_display.c"),
                  encoding="utf-8") as handle:
            code = without_comments(handle.read())
        found = re.search(r"bool panel_display_touched\(void\).*?\n\}",
                          code, re.S)
        self.assertIsNotNone(found)
        self.assertIn("!is_asleep", found.group(0))

    def test_the_minutes_survive_a_restart(self):
        code = self.main()
        self.assertIn('nvs_get_u8(h,"sleep_after"', code)
        self.assertRegex(code, r'key==PANEL_SLEEP_AFTER\?"sleep_after"')
