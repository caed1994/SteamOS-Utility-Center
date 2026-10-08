# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The alarm clock of the clock page, built and driven on this machine.

Asked for: a small button on the page of the clock and the timer, and a
layer behind it that sets an alarm. One alarm, with a choice of weekdays,
and with no weekday it rings one time. It rings as the timer does, and a
key or a tap gives a snooze of five minutes. Off is a button of its own.
An alarm that nobody answers rings for five minutes. The cover of a sleep
shows the next ring, and nothing when no alarm is set.

firmware/companion/main/panel_alarm.c is the alarm without a screen. The
harness in tests/c/panel-alarm-harness.c drives it with a clock of its
own. The weekdays count as struct tm counts them: Sunday is 0.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(REPO, "firmware", "companion")
FIRMWARE = os.path.join(COMPANION, "main")
HARNESS = os.path.join(REPO, "tests", "c", "panel-alarm-harness.c")

MINUTE = 60 * 1000
SUNDAY, MONDAY, TUESDAY, FRIDAY, SATURDAY = 0, 1, 2, 5, 6
WORKDAYS = 0x1F
EVERY_DAY = 0x7F


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


def read(*parts):
    with open(os.path.join(COMPANION, *parts), encoding="utf-8") as handle:
        return handle.read()


def without_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def body(code, start):
    found = re.search(re.escape(start) + r".*?\n\}", code, re.S)
    assert found, start
    return found.group(0)


def constant(name):
    found = re.search(r"^#define %s \(?([\d *]+)\)?" % name,
                      read("main", "panel_alarm.h"), re.M)
    assert found, name
    return eval(found.group(1))  # digits and * only, see the pattern


@unittest.skipUnless(compiler(), "no C compiler here")
class AlarmTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-alarm")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_alarm.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_alarm.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def run_alarm(self, *commands):
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def rings(self, *commands):
        """The went_off and gave_up lines of a run, without the beeps."""
        return [line for line in self.run_alarm(*commands)
                if line.startswith(("went_off", "gave_up"))]

    def test_the_numbers_are_the_ones_asked_for(self):
        self.assertEqual(constant("PANEL_ALARM_SNOOZE_MS"), 5 * MINUTE)
        self.assertEqual(constant("PANEL_ALARM_RING_MS"), 5 * MINUTE)

    def test_it_rings_in_its_minute_on_its_day_and_gives_up_after_five(self):
        out = self.run_alarm("init 1 7 0 %d" % WORKDAYS,
                             "clock 10 %d 6 59 0" % MONDAY, "walk 600 200")
        self.assertEqual(out, ["went_off 10 07:00:00", "gave_up 10 07:05:00",
                               "beeps 900"])

    def test_it_beeps_with_the_rhythm_of_the_timer(self):
        """Three beeps and a pause, once a second, from the first tick."""
        out = self.run_alarm("init 1 7 0 %d" % WORKDAYS,
                             "clock 10 %d 6 59 59" % MONDAY, "walk 2 200")
        self.assertEqual(out, ["went_off 10 07:00:00", "beeps 4"])

    def test_it_does_not_ring_on_a_day_it_does_not_have(self):
        for weekday in (SATURDAY, SUNDAY):
            self.assertEqual(self.rings("init 1 7 0 %d" % WORKDAYS,
                                        "clock 10 %d 6 59 0" % weekday,
                                        "walk 600 200"), [])

    def test_an_alarm_that_is_off_does_not_ring(self):
        self.assertEqual(self.rings("init 0 7 0 %d" % EVERY_DAY,
                                    "clock 10 %d 6 59 0" % MONDAY,
                                    "walk 600 200"), [])

    def test_with_no_day_it_rings_one_time_and_switches_off(self):
        out = self.run_alarm("init 1 7 0 0", "clock 10 %d 6 59 0" % SATURDAY,
                             "walk 600 200", "show", "next",
                             "walk 86400 1000")
        self.assertEqual(out, ["went_off 10 07:00:00", "gave_up 10 07:05:00",
                               "beeps 900", "waiting 0 7 0 0", "next none",
                               "beeps 0"])

    def test_with_days_it_stays_on_for_the_next_one(self):
        out = self.run_alarm("init 1 7 0 %d" % WORKDAYS,
                             "clock 10 %d 6 59 0" % FRIDAY, "walk 600 200",
                             "show", "next")
        self.assertEqual(out[-2:], ["waiting 1 7 0 %d" % WORKDAYS,
                                    "next %d 07:00" % MONDAY])

    def test_it_rings_again_the_next_day(self):
        rings = self.rings("init 1 7 0 %d" % EVERY_DAY,
                           "clock 10 %d 6 59 0" % MONDAY, "walk 90000 1000")
        self.assertEqual(rings, ["went_off 10 07:00:00", "gave_up 10 07:05:00",
                                 "went_off 11 07:00:00", "gave_up 11 07:05:00"])

    def test_a_snooze_rings_again_after_five_minutes(self):
        out = self.run_alarm("init 1 7 0 %d" % WORKDAYS,
                             "clock 10 %d 6 59 0" % MONDAY, "walk 90 200",
                             "snooze", "show", "next", "walk 330 200")
        # 30 seconds of ringing and the tick that ends them: 30 times three
        # beeps, and the first beep of the next second.
        self.assertEqual(out, ["went_off 10 07:00:00", "beeps 91", "snooze yes",
                               "snoozing 1 7 0 %d" % WORKDAYS,
                               "next %d 07:05" % MONDAY,
                               "went_off 10 07:05:30", "beeps 91"])

    def test_a_snooze_needs_a_ring(self):
        self.assertEqual(self.run_alarm("init 1 7 0 0", "snooze"),
                         ["snooze no"])

    def test_off_ends_a_ring(self):
        out = self.run_alarm("init 1 7 0 %d" % WORKDAYS,
                             "clock 10 %d 6 59 0" % MONDAY, "walk 61 200",
                             "off", "show", "walk 600 200", "off")
        self.assertEqual(out[2:], ["off yes", "waiting 1 7 0 %d" % WORKDAYS,
                                   "beeps 0", "off no"])

    def test_off_ends_a_snooze_and_a_once_alarm(self):
        out = self.run_alarm("init 1 7 0 0", "clock 10 %d 6 59 0" % MONDAY,
                             "walk 61 200", "snooze", "off", "show", "next",
                             "walk 600 200")
        self.assertEqual(out[2:], ["snooze yes", "off yes", "waiting 0 7 0 0",
                                   "next none", "beeps 0"])

    def test_a_setting_for_the_minute_now_waits_for_the_next_day(self):
        out = self.run_alarm("clock 10 %d 7 0 20" % MONDAY, "set 1 7 0 0",
                             "next", "walk 120 200",
                             "clock 11 %d 6 59 50" % TUESDAY, "walk 20 200")
        self.assertEqual(out, ["next %d 07:00" % TUESDAY, "beeps 0",
                               "went_off 11 07:00:00", "beeps 31"])

    def test_a_setting_for_a_later_minute_rings_today(self):
        out = self.rings("clock 10 %d 6 0 0" % MONDAY, "set 1 6 30 0",
                         "walk 1900 1000")
        self.assertEqual(out[0], "went_off 10 06:30:00")

    def test_a_new_setting_ends_a_ring_and_a_snooze(self):
        out = self.run_alarm("init 1 7 0 %d" % WORKDAYS,
                             "clock 10 %d 6 59 0" % MONDAY, "walk 61 200",
                             "set 1 8 0 %d" % WORKDAYS, "show",
                             "walk 600 200")
        self.assertEqual(out[2:], ["waiting 1 8 0 %d" % WORKDAYS, "beeps 0"])

    def test_the_hour_that_winter_time_gives_twice_rings_one_time(self):
        """The clock goes back from 3:00 to 2:00 on the same day."""
        rings = self.rings("init 1 2 30 %d" % EVERY_DAY,
                           "clock 10 %d 2 29 0" % SUNDAY, "walk 1860 1000",
                           "clock 10 %d 2 0 0" % SUNDAY, "walk 3600 1000")
        self.assertEqual(rings, ["went_off 10 02:30:00", "gave_up 10 02:35:00"])

    def test_the_hour_that_summer_time_leaves_out_does_not_ring(self):
        """The clock goes on from 2:00 to 3:00."""
        out = self.run_alarm("init 1 2 30 %d" % EVERY_DAY,
                             "clock 10 %d 1 59 0" % SUNDAY, "walk 60 1000",
                             "clock 10 %d 3 0 0" % SUNDAY, "walk 3600 1000",
                             "next")
        self.assertEqual(out, ["beeps 0", "beeps 0", "next %d 02:30" % MONDAY])

    def test_nothing_rings_before_the_clock_is_set(self):
        out = self.run_alarm("init 1 7 0 %d" % EVERY_DAY,
                             "clock 10 %d 6 59 0" % MONDAY, "unknown", "next",
                             "walk 600 200")
        self.assertEqual(out, ["next none", "beeps 0"])

    def test_it_is_right_across_the_turn_of_the_counter(self):
        out = self.rings("init 1 7 0 %d" % WORKDAYS, "ms 4294967000",
                         "clock 10 %d 6 59 59" % MONDAY, "walk 400 200")
        self.assertEqual(out, ["went_off 10 07:00:00", "gave_up 10 07:05:00"])

    def test_the_next_ring_is_today_before_the_time(self):
        self.assertEqual(self.run_alarm("init 1 7 0 %d" % WORKDAYS,
                                        "clock 10 %d 6 0 0" % MONDAY, "next"),
                         ["next %d 07:00" % MONDAY])

    def test_the_next_ring_skips_the_days_without_it(self):
        self.assertEqual(self.run_alarm("init 1 7 0 %d" % WORKDAYS,
                                        "clock 10 %d 8 0 0" % FRIDAY, "next"),
                         ["next %d 07:00" % MONDAY])

    def test_one_day_a_week_comes_again_in_seven_days(self):
        self.assertEqual(self.run_alarm("init 1 7 0 1",
                                        "clock 10 %d 8 0 0" % MONDAY, "next"),
                         ["next %d 07:00" % MONDAY])

    def test_a_once_alarm_after_its_time_is_tomorrow(self):
        self.assertEqual(self.run_alarm("init 1 7 0 0",
                                        "clock 10 %d 8 0 0" % SATURDAY, "next"),
                         ["next %d 07:00" % SUNDAY])

    def test_an_alarm_that_is_off_has_no_next_ring(self):
        self.assertEqual(self.run_alarm("init 0 7 0 %d" % EVERY_DAY,
                                        "clock 10 %d 6 0 0" % MONDAY, "next"),
                         ["next none"])

    def test_a_snooze_over_midnight_ends_the_next_day(self):
        out = self.run_alarm("init 1 23 58 %d" % EVERY_DAY,
                             "clock 10 %d 23 57 59" % MONDAY, "walk 11 200",
                             "snooze", "next")
        self.assertEqual(out[-1], "next %d 00:03" % TUESDAY)

    def test_the_setting_goes_into_one_number_and_back(self):
        for setting in ("1 7 0 31", "0 23 59 127", "1 0 0 0", "1 12 30 64"):
            packed = self.run_alarm("pack %s" % setting)[0]
            self.assertEqual(self.run_alarm("unpack %s" % packed),
                             [setting])

    def test_a_number_this_firmware_did_not_write_reads_as_off(self):
        """Off, at seven, one time: the default."""
        for packed in ("0", "ffffffff", "a10007c0", "a1080000", "00000000",
                       "b10001c0"):
            self.assertEqual(self.run_alarm("unpack %s" % packed),
                             ["0 7 0 0"], packed)


class WiringTest(unittest.TestCase):
    """What main.c and ui.c do with what the alarm says."""

    def tick(self):
        code = without_comments(read("main", "main.c"))
        return body(code, "static void ui_tick(lv_timer_t *timer)")

    def test_the_alarm_is_asked_in_a_sleep_too(self):
        tick = self.tick()
        self.assertLess(tick.index("panel_ui_alarm_clock_tick(&wall)"),
                        tick.index("if(atomic_load(&display_asleep))return;"))

    def test_a_ring_wakes_the_display_from_any_sleep(self):
        tick = self.tick()
        went = tick[tick.index("if(news.went_off||wake.went_off){"):]
        self.assertIn("display_sleeping(false,false);",
                      went[:went.index("ESP_LOGI")])

    def test_it_beeps_at_the_volume_of_the_alarm(self):
        self.assertIn("if(news.beep||wake.beep)sound_send(panel_ui_alarm_volume());",
                      self.tick())

    def test_a_snooze_and_a_ring_nobody_answers_put_the_display_back(self):
        code = without_comments(read("main", "main.c"))
        quiet = body(code, "static void ring_quiet(void)")
        self.assertLess(quiet.index("panel_ui_alarm_clock_ringing())return;"),
                        quiet.index("if(alarm_woke)display_sleeping(true,alarm_woke_by_hand);"))
        tick = self.tick()
        gave = tick[tick.index("if(news.gave_up||wake.gave_up){"):]
        self.assertIn("ring_quiet();", gave[:gave.index("}")])
        touched = tick[tick.index("if(panel_ui_alarm_clock_take_snooze()){"):]
        self.assertIn("ring_quiet();", touched[:touched.index("}")])

    def test_both_keys_snooze_before_they_do_anything_else(self):
        tick = self.tick()
        press = tick[tick.index("if(panel_power_take_toggle()){"):]
        self.assertLess(press.index("panel_ui_alarm_clock_snooze()"),
                        press.index("display_sleeping(!atomic_load(&display_asleep),true)"))
        home = tick[tick.index("if(panel_power_take_home()){"):]
        self.assertLess(home.index("panel_ui_alarm_clock_snooze()"),
                        home.index("panel_ui_home()"))

    def test_the_display_does_not_time_out_under_the_alarm(self):
        self.assertRegex(self.tick(),
                         r"!panel_ui_alarm_clock_ringing\(\) && !atomic_load\(&updating\)")

    def test_the_setting_is_stored_as_one_number(self):
        code = without_comments(read("main", "main.c"))
        self.assertIn('if(nvs_get_u32(h,"alarm",&key)==ESP_OK)settings.alarm=key;',
                      code)
        store = body(code, "static void setting_set(")
        self.assertIn('key==PANEL_ALARM?"alarm"', store)
        self.assertRegex(store, r"bool wide=[^;]*key==PANEL_ALARM;")

    def test_the_cover_shows_the_next_ring(self):
        code = without_comments(read("main", "main.c"))
        clock = body(code, "static void standby_clock(bool now)")
        self.assertIn("panel_ui_alarm_clock_next(alarm,sizeof alarm);", clock)
        self.assertIn("panel_display_sleep_clock(hours,date,alarm);", clock)

    def test_a_tap_on_the_ring_snoozes_and_off_is_a_button(self):
        code = without_comments(read("main", "ui.c"))
        ring = body(code, "static void alarm_clock_ring_show(void)")
        self.assertIn("lv_obj_add_event_cb(alarm_clock_ring_layer,"
                      "alarm_clock_snooze_touched,LV_EVENT_CLICKED,NULL);", ring)
        self.assertIn("button(box,panel_text(TXT_ALARM_OFF),", ring)
        self.assertIn("alarm_clock_off_touched", ring)

    def test_the_layer_sets_nothing_until_it_closes(self):
        """The wheels, the days and the switch change the draft only."""
        code = without_comments(read("main", "ui.c"))
        for name in ("static void alarm_clock_rolled(",
                     "static void alarm_clock_day_clicked(",
                     "static void alarm_clock_switched("):
            self.assertNotIn("panel_alarm_change(&alarm_clock",
                             body(code, name), name)
        self.assertIn("panel_alarm_change(&alarm_clock,alarm_clock_draft,",
                      body(code, "static void alarm_clock_close(void)\n{"))

    def test_the_alarm_outlives_a_new_screen(self):
        code = without_comments(read("main", "ui.c"))
        create = body(code, "void panel_ui_create(")
        self.assertIn("if(!alarm_clock_ready){", create)
        self.assertIn("if(alarm_clock.phase==PANEL_ALARM_RINGING)alarm_clock_ring_show();",
                      code)

    def test_the_builds_know_the_file(self):
        self.assertIn('"panel_alarm.c"', read("main", "CMakeLists.txt"))
        preview = read("preview", "CMakeLists.txt")
        self.assertIn("../main/panel_alarm.c", preview)
        start = preview.index("add_executable(check_power")
        self.assertIn("../main/icons.c", preview[start:preview.index(")", start)])

    def test_the_icon_is_a_lucide_drawing(self):
        drawing = read("main", "assets", "alarm-clock.svg")
        self.assertIn("@license lucide-static", drawing)
        self.assertIn("extern const lv_image_dsc_t icon_alarm_clock;",
                      read("main", "icons.h"))


if __name__ == "__main__":
    unittest.main()
