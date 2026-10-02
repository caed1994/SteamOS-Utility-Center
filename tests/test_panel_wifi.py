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


class ResetReasonTest(unittest.TestCase):
    """Why the panel started, in the first line of the log.

    A person reaches for the serial cable after a fault and not before it,
    so the line that matters is the one about the boot that already
    happened. It said reset_reason=4, which nobody can read.

    Four answers point at four different places. A panic is a fault in
    this firmware. A watchdog is work that ran too long. A brownout is the
    power supply and not the code at all, and this panel has form there:
    plugged in beside the LED board, it took that one down with it.
    """

    def table(self):
        code = without_comments(read("main.c"))
        found = re.search(r"reset_reason_name\(esp_reset_reason_t reason\)"
                          r"\s*\{.*?\n\}", code, re.S)
        self.assertIsNotNone(found, "the reason has no name")
        return found.group(0)

    def test_the_first_line_says_why_in_words(self):
        code = without_comments(read("main.c"))
        said = re.search(r'ESP_LOGI\("panel_boot","version[^;]*;', code)
        self.assertIsNotNone(said, "nothing logs the start")
        self.assertIn("reset_reason_name", said.group(0),
                      "a bare number sends every reader to a header")
        # The number stays beside the word. A reader who knows the header
        # loses nothing.
        self.assertIn("reset_reason=%d", said.group(0))

    def test_the_four_that_point_at_different_places_are_named(self):
        table = self.table()
        for reason in ("ESP_RST_PANIC", "ESP_RST_TASK_WDT",
                       "ESP_RST_BROWNOUT", "ESP_RST_POWERON"):
            self.assertIn(reason, table,
                          "%s is one of the answers and has no name" % reason)

    def test_one_it_does_not_know_still_says_something(self):
        self.assertIn("default:", self.table())


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



class WeakAPTest(unittest.TestCase):
    """The far AP behind the same name, and why it is not an answer.

    Four starts off the board named two of them:

        3c:37:12:35:dd:95   channel 6   -51 to -55 dBm
        2c:91:ab:94:1c:9e   channel 9   -85 to -86 dBm

    All four began on channel 6, so sorting by signal does work. Three
    were refused there, and the retry count then sent them to the far one.
    Two joined it, and one of those never got an address at all.
    """

    def source(self):
        return without_comments(read("main.c"))

    def test_a_signal_this_weak_is_not_a_candidate(self):
        """The header reads nought or more as -127, so leaving it out is
        the same as no floor. The floor has to be a negative number."""
        said = re.search(r"threshold\.rssi\s*=\s*(-\d+)", self.source())
        self.assertIsNotNone(said, "nothing keeps the far AP out of the list")
        self.assertLess(int(said.group(1)), 0)

    def test_the_floor_clears_the_near_AP_and_stops_the_far_one(self):
        """-55 joined and worked. -85 associated and got no address. A
        floor between them is the whole point, and one outside that range
        either locks the panel out or lets the far AP back in."""
        said = re.search(r"threshold\.rssi\s*=\s*(-\d+)", self.source())
        floor = int(said.group(1))
        self.assertLess(floor, -55, "this would refuse the AP that works")
        self.assertGreater(floor, -85, "this lets the AP back in that "
                                       "associates and gets no address")


class LogSharingTest(unittest.TestCase):
    """One wire, two writers.

    Read off the board: a line of LVGL's arrived inside the middle of a
    line of the Wi-Fi driver's. LV_LOG_PRINTF writes with printf from the
    LVGL task, ESP_LOG writes from whichever task has something to say,
    and nothing holds them apart.
    """

    def display(self):
        with open(os.path.join(FIRMWARE, "panel_display.c"),
                  encoding="utf-8") as handle:
            return without_comments(handle.read())

    def test_lvgl_lines_go_through_the_one_that_locks(self):
        self.assertIn("lv_log_register_print_cb", self.display())

    def test_printf_is_not_the_way_out(self):
        defaults = os.path.join(os.path.dirname(FIRMWARE),
                                "sdkconfig.defaults")
        with open(defaults, encoding="utf-8") as handle:
            text = handle.read()
        self.assertRegex(text, r"(?m)^CONFIG_LV_USE_LOG=y",
                         "without the log module the callback is never "
                         "called and the panel says nothing")
        self.assertNotRegex(text, r"(?m)^CONFIG_LV_LOG_PRINTF=y",
                            "printf and ESP_LOG share a UART and no lock")

    def test_the_callback_is_registered_after_lvgl_exists(self):
        """lv_log_register_print_cb before lv_init is a write into
        nothing. lvgl_port_init is what calls lv_init here."""
        code = self.display()
        started = code.index("lvgl_port_init(&port)")
        registered = code.index("lv_log_register_print_cb")
        self.assertLess(started, registered)


class RadioRestTest(unittest.TestCase):
    """The radio off while the display sleeps by the button.

    Asked for: a panel switched off with the button spends nothing on the
    network, and one that went dark after the set time stays on it, so its
    numbers are current when a touch brings it back. None of this runs
    here. Each rule below is one way the change breaks without a word.
    """

    def source(self):
        return without_comments(read("main.c"))

    def body(self, start):
        found = re.search(re.escape(start) + r".*?\n\}", self.source(), re.S)
        self.assertIsNotNone(found, start)
        return found.group(0)

    def test_the_reason_of_the_sleep_decides_and_the_setup_keeps_its_radio(
            self):
        """The button and not the sleep. And not during the setup: a phone
        talks to the access point of the setup, whatever the screen
        does."""
        task = self.body("static void network_task(void *arg)")
        self.assertRegex(task, r"bool setup=state\.setup;")
        self.assertRegex(
            task, r"bool rest=atomic_load\(&asleep_by_hand\)\s*&&\s*!setup;")
        self.assertRegex(task, r"if \(rest!=rest_wanted\) \{ rest_wanted=rest; "
                               r"radio_rest\(rest\); \}")

    def test_only_the_network_task_stops_and_starts_the_radio(self):
        """esp_wifi_stop waits for the driver. In the task that draws, that
        wait freezes the screen and the key with it."""
        code = self.source()
        rest = self.body("static void radio_rest(bool rest)")
        self.assertEqual(code.count("esp_wifi_stop("), 1)
        self.assertIn("esp_wifi_stop(", rest)
        self.assertIn("esp_wifi_start(", rest)
        callers = re.findall(r"\bradio_rest\(rest\)", code)
        self.assertEqual(len(callers), 1)
        self.assertIn("radio_rest(rest)",
                      self.body("static void network_task(void *arg)"))
        for start in ("static void ui_tick(lv_timer_t *timer)",
                      "static void display_sleeping(bool sleep,bool by_hand)"):
            self.assertNotIn("esp_wifi_", self.body(start), start)

    def test_a_stop_is_no_reason_to_connect_again(self):
        """The stop disconnects, and the handler of a disconnect connects
        again. So the rest is marked before the stop, and the handler
        reads the mark."""
        handler = self.body("static void wifi_event(")
        self.assertRegex(handler,
                         r"bool reconnect=!state\.setup && "
                         r"!atomic_load\(&radio_resting\);")
        rest = self.body("static void radio_rest(bool rest)")
        self.assertLess(rest.index("atomic_store(&radio_resting,true)"),
                        rest.index("esp_wifi_stop()"))

    def test_nothing_is_asked_of_the_pc_while_the_radio_rests(self):
        self.assertRegex(
            self.body("static void network_task(void *arg)"),
            r"if \(!atomic_load\(&radio_resting\) &&\s*"
            r"xTaskGetTickCount\(\)-last_poll>=pdMS_TO_TICKS\(3000\)\)")

    def test_the_driver_keeps_what_it_was_given(self):
        """A deinit drops the configuration: the scan of every channel, the
        floor under the signal, the retries. A start after it would join
        with none of them, if it joined at all."""
        self.assertNotIn("esp_wifi_deinit", self.source())

    def test_the_pc_is_asked_as_soon_as_the_network_is_there(self):
        """And not up to three seconds later. After a rest that is the
        wait somebody stands in front of."""
        self.assertRegex(
            self.body("static void network_task(void *arg)"),
            r"if \(now_connected && !was_connected\)\s*"
            r"last_poll=xTaskGetTickCount\(\)-pdMS_TO_TICKS\(3000\);")

    def test_the_disconnect_of_a_rest_is_not_a_warning(self):
        """Read off the board: the rest wrote "Disconnected, reason=8" as a
        warning, and a warning for what the panel did on purpose teaches
        a reader to skip warnings."""
        handler = self.body("static void wifi_event(")
        rest = handler.index("if (atomic_load(&radio_resting))")
        self.assertLess(rest, handler.index(
            'ESP_LOGI("panel_wifi","Disconnected for the radio rest'))
        self.assertLess(rest, handler.index(
            'ESP_LOGW("panel_wifi","Disconnected, reason'))
        table = re.search(r"wifi_reason_name\(uint8_t reason\)\s*\{.*?\n\}",
                          self.source(), re.S).group(0)
        self.assertNotIn("the AP is leaving", table,
                         "reason 8 is the sender leaving, and on the board "
                         "the sender was the panel")

    def test_the_log_says_how_long_the_join_after_a_rest_took(self):
        """The few seconds this costs are a guess until the board says."""
        handler = self.body("static void wifi_event(")
        self.assertIn("atomic_exchange(&radio_back_ms,0u)", handler)
        self.assertIn("Joined again %u ms after the radio came back", handler)
        self.assertIn("radio_rest=%d", self.source())


class AnswerTest(unittest.TestCase):
    """What the PC said, as the panel reads it.

    Read off the board: two lines of esp_http_client at the first poll of
    every start, "This request requires authentication" and "Error
    response". That is the service handing out its first nonce with a 401.
    esp_http_client takes a 401 for HTTP authentication of its own, finds
    no header for that and fails the request, so the 401 reached the panel
    as "no answer": the retry with the fresh nonce never ran, and a token
    the PC refuses never reached the screen as one."""

    def source(self):
        return without_comments(read("main.c"))

    def body(self, start):
        found = re.search(re.escape(start) + r".*?\n\}", self.source(), re.S)
        self.assertIsNotNone(found, start)
        return found.group(0)

    def test_a_401_counts_although_the_client_failed_the_request(self):
        attempt = self.body("static int attempt(")
        self.assertIn("int status=esp_http_client_get_status_code(client);",
                      attempt)
        self.assertRegex(attempt, r"err==ESP_OK \|\| status==401 \? status : 0")

    def test_the_401_is_tried_again_with_the_fresh_nonce(self):
        self.assertIn("if (code==401) code=attempt(path,action,out);",
                      self.body("static int request("))

    def test_the_client_is_quiet_and_the_panel_says_it_instead(self):
        start = self.body("void app_main(void)")
        self.assertLess(start.index('esp_log_level_set("HTTP_CLIENT",ESP_LOG_NONE);'),
                        start.index("panel_psram_task(network_task"))
        task = self.body("static void network_task(void *arg)")
        self.assertIn("if (code!=answered) {", task)
        for said in ('"The PC answers"', "The PC refuses this panel",
                     "No network, so no question to the PC",
                     "The PC does not answer: %s"):
            self.assertIn(said, task)
        self.assertIn("esp_err_to_name(last_http_error)", task)


if __name__ == "__main__":
    unittest.main()
