# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The clock page: the time of day, and the timer that wakes the display.

Asked for: a page with a digital clock and a timer. The clock takes its
time from the network and keeps it without; the timer runs on in a sleep,
and at its end it beeps and wakes the display, from the sleep of the
button as well. None of the firmware runs here. The time zone does: its
rule is a POSIX TZ string, and Python reads the same strings.
"""

from __future__ import annotations

import calendar
import os
import re
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(REPO, "firmware", "companion")
FIRMWARE = os.path.join(COMPANION, "main")


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


def zone():
    found = re.search(r'#define PANEL_TIME_ZONE "([^"]+)"',
                      read("main", "panel_time.c"))
    assert found
    return found.group(1)


class ZoneTest(unittest.TestCase):
    """Berlin, with the change to summer time and back, read with the
    rules of the C library that newlib follows too."""

    def local(self, utc):
        keep = os.environ.get("TZ")
        os.environ["TZ"] = zone()
        time.tzset()
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(
                calendar.timegm(time.strptime(utc, "%Y-%m-%d %H:%M:%S"))))
        finally:
            if keep is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = keep
            time.tzset()

    def test_winter_is_an_hour_ahead_of_utc(self):
        self.assertEqual(self.local("2026-01-15 12:00:00"),
                         "2026-01-15 13:00:00 CET")

    def test_summer_time_starts_on_the_last_sunday_of_march(self):
        self.assertEqual(self.local("2026-03-29 00:59:59"),
                         "2026-03-29 01:59:59 CET")
        self.assertEqual(self.local("2026-03-29 01:00:00"),
                         "2026-03-29 03:00:00 CEST")

    def test_and_ends_on_the_last_sunday_of_october(self):
        self.assertEqual(self.local("2026-10-25 00:59:59"),
                         "2026-10-25 02:59:59 CEST")
        self.assertEqual(self.local("2026-10-25 01:00:00"),
                         "2026-10-25 02:00:00 CET")


class NetworkTimeTest(unittest.TestCase):
    def test_the_router_names_the_first_server_and_the_pool_the_second(self):
        code = without_comments(read("main", "panel_time.c"))
        init = body(code, "void panel_time_init(void)")
        for said in ("config.server_from_dhcp = true;",
                     "config.renew_servers_after_new_IP = true;",
                     "config.index_of_first_server = 1;",
                     "config.wait_for_sync = false;",
                     'setenv("TZ", PANEL_TIME_ZONE, 1);', "tzset();"):
            self.assertIn(said, init)
        self.assertIn('#define PANEL_TIME_SERVER "pool.ntp.org"',
                      read("main", "panel_time.c"))

    def test_lwip_has_room_for_two_and_lets_dhcp_fill_one(self):
        defaults = read("sdkconfig.defaults")
        self.assertRegex(defaults, r"(?m)^CONFIG_LWIP_SNTP_MAX_SERVERS=2$")
        self.assertRegex(defaults, r"(?m)^CONFIG_LWIP_DHCP_GET_NTP_SRV=y$")

    def test_it_is_set_up_before_the_radio_joins(self):
        """DHCP names a time server only in an answer to a request it has
        not made yet, and esp_netif_sntp hangs a handler on the event
        loop."""
        start = body(without_comments(read("main", "main.c")),
                     "void app_main(void)")
        self.assertLess(start.index("esp_event_loop_create_default()"),
                        start.index("panel_time_init();"))
        self.assertLess(start.index("panel_time_init();"),
                        start.index("esp_wifi_connect()"))

    def test_a_clock_that_was_never_set_says_so(self):
        """The chip starts at 1970."""
        code = without_comments(read("main", "panel_time.c"))
        self.assertRegex(code, r"#define PANEL_TIME_SET_YEAR 20\d\d")
        now = body(code, "bool panel_time_now(struct tm *now)")
        self.assertIn("now->tm_year + 1900 >= PANEL_TIME_SET_YEAR", now)

    def test_the_build_knows_the_files(self):
        cmake = read("main", "CMakeLists.txt")
        for name in ("panel_time.c", "panel_timer.c", "panel_clock_font.c"):
            self.assertIn('"%s"' % name, cmake)
        preview = read("preview", "CMakeLists.txt")
        for name in ("panel_timer.c", "panel_clock_font.c"):
            self.assertIn("../main/%s" % name, preview)


class AlarmTest(unittest.TestCase):
    """What main.c does with what the timer says."""

    def tick(self):
        code = without_comments(read("main", "main.c"))
        return body(code, "static void ui_tick(lv_timer_t *timer)")

    def test_the_timer_is_asked_in_a_sleep_too(self):
        tick = self.tick()
        self.assertLess(tick.index("panel_ui_timer_tick()"),
                        tick.index("if(atomic_load(&display_asleep))return;"))

    def test_its_end_wakes_the_display_from_any_sleep(self):
        """display_sleeping(false,...) clears asleep_by_hand, which ends the
        rest of the radio as well."""
        tick = self.tick()
        went = tick[tick.index("if(news.went_off){"):]
        went = went[:went.index("}")]
        self.assertIn("display_sleeping(false,false);", went)

    def test_it_beeps_at_the_volume_of_the_alarm(self):
        self.assertIn("if(news.beep)sound_send(panel_ui_alarm_volume());",
                      self.tick())

    def test_nobody_there_puts_the_display_back_where_it_was(self):
        tick = self.tick()
        gave = tick[tick.index("if(news.gave_up){"):]
        self.assertIn("if(alarm_woke)display_sleeping(true,alarm_woke_by_hand);",
                      gave[:gave.index("alarm_woke=false;")])

    def test_the_button_stops_the_alarm_before_it_toggles_anything(self):
        tick = self.tick()
        press = tick[tick.index("if(panel_power_take_toggle()){"):]
        self.assertLess(press.index("panel_ui_timer_stop()"),
                        press.index("display_sleeping(!atomic_load(&display_asleep),true)"))

    def test_the_display_does_not_time_out_under_the_alarm(self):
        self.assertRegex(self.tick(),
                         r"display_sleep_after>0 && !panel_ui_timer_ringing\(\)")

    def test_the_time_reaches_the_page_from_the_chip(self):
        tick = self.tick()
        self.assertIn("copy.clock_set=panel_time_now(&now);", tick)
        self.assertIn("copy.month=now.tm_mon+1;", tick)
        self.assertLess(tick.index("copy.clock_set=panel_time_now(&now);"),
                        tick.index("panel_ui_update(&copy);"))


if __name__ == "__main__":
    unittest.main()
