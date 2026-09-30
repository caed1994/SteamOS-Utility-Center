# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The middle band of the panel, which scrolls sideways.

What the three pages draw is checked where it can really be drawn:
firmware/companion/preview/check_pages.c builds the screens on a host LVGL
and reads the words off them. That needs a compiler, so it runs in the job.

What these hold is what that check cannot see. The table of names in main.c
is the one that matters: it is indexed by the action, and a name added to
the enum and not to the table makes every button under it send the name of
another one. That failure is silent on both ends.
"""

from __future__ import annotations

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(REPO, "firmware", "companion")
FIRMWARE = os.path.join(COMPANION, "main")
PREVIEW = os.path.join(COMPANION, "preview")


def read(name, where=FIRMWARE):
    with open(os.path.join(where, name), encoding="utf-8") as handle:
        return handle.read()


def without_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def actions():
    """The names in panel_action_t, in order."""
    order = re.search(r"typedef enum \{(.*?)\} panel_action_t;",
                      read("ui.h"), re.S).group(1)
    return re.findall(r"PANEL_[A-Z_]+", without_comments(order))


class ActionTableTest(unittest.TestCase):
    def test_the_table_holds_a_name_for_every_action_it_is_asked_for(self):
        """main.c guards the table with `action < PANEL_SETUP` and indexes
        it by the number. So the table has to be exactly as long as the
        run of actions before PANEL_SETUP, and no shorter."""
        names = actions()
        performed = names.index("PANEL_SETUP")
        table = re.search(r"const char \*names\[\]=\{(.*?)\};",
                          without_comments(read("main.c")), re.S).group(1)
        self.assertEqual(len(re.findall(r'"[a-z_]+"', table)), performed,
                         "the table and the actions below PANEL_SETUP have "
                         "drifted apart, so a button sends another name")

    def test_the_two_local_ones_stay_at_the_end(self):
        """Everything before PANEL_SETUP is a name the service performs.
        One put in the middle shifts every action under it."""
        names = actions()
        self.assertEqual(names[-1], "PANEL_WAKE")
        self.assertEqual(names[-2], "PANEL_SETUP")

    def test_the_session_presses_name_where_to_go(self):
        names = actions()
        self.assertIn("PANEL_DESKTOP_MODE", names)
        self.assertIn("PANEL_GAME_MODE", names)
        table = without_comments(read("main.c"))
        self.assertIn('"desktop_mode"', table)
        self.assertIn('"game_mode"', table)

    def test_the_service_answers_to_those_same_names(self):
        """Two ends of one wire. A rename on one side is a press that the
        other side answers with 400 and nobody reads."""
        with open(os.path.join(REPO, "server", "steamos_utility_center",
                               "companion.py"), encoding="utf-8") as handle:
            service = handle.read()
        for name in ("desktop_mode", "game_mode"):
            self.assertIn('"%s":' % name, service)

    def test_switching_the_session_asks_first(self):
        """It closes what is open, the way standby and switch off do. The
        guard is a range, so the two have to sit inside it."""
        names = actions()
        code = without_comments(read("ui.c"))
        self.assertRegex(code, r"action\s*>=\s*PANEL_SUSPEND\s*&&\s*"
                               r"action\s*<=\s*PANEL_SETUP")
        first = names.index("PANEL_SUSPEND")
        last = names.index("PANEL_SETUP")
        for name in ("PANEL_DESKTOP_MODE", "PANEL_GAME_MODE"):
            self.assertTrue(first <= names.index(name) <= last,
                            "%s falls outside the range that asks" % name)


class BandTest(unittest.TestCase):
    """What stays still while the middle moves."""

    def source(self):
        return without_comments(read("ui.c"))

    def test_the_head_and_the_sensors_are_not_on_a_page(self):
        """Those are the numbers somebody reads without touching anything.
        A page that can carry them away is a page that hides them."""
        code = self.source()
        for built in ("connection=text_at(s,", "battery=text_at(s,",
                      "lv_obj_t *foot=panel(s,"):
            self.assertIn(built, code,
                          "this belongs to the screen and not to a page")

    def test_the_band_snaps_so_there_is_no_place_between_two_pages(self):
        code = self.source()
        self.assertIn("LV_SCROLL_SNAP_CENTER", code)
        self.assertIn("LV_OBJ_FLAG_SCROLL_ONE", code)

    def test_the_band_does_not_take_the_press_meant_for_a_button(self):
        """lv_obj_create makes a clickable object, and a band that takes a
        press swallows the one meant for a button standing on it."""
        code = self.source()
        self.assertRegex(code,
                         r"lv_obj_remove_flag\(band,\s*LV_OBJ_FLAG_CLICKABLE\)")

    def test_every_pointer_of_a_new_page_is_dropped_on_a_clean(self):
        """panel_ui_create runs again when the language changes, and the
        clean takes every object with it. A pointer kept past it is freed
        memory that a touch reaches. panel_ui_sleep had that bug."""
        code = self.source()
        kept = re.search(r"lv_obj_clean\(s\);(.*?)panel_ui_sleep_reset\(\)",
                         code, re.S)
        self.assertIsNotNone(kept)
        for name in ("band", "mode_now", "mode_button", "mode_caption",
                     "playing_name", "no_drives", "dots", "drive_rows",
                     "drive_names", "drive_bars", "drive_free"):
            self.assertIn(name, kept.group(1),
                          "%s outlives the clean that freed it" % name)


class DriveTest(unittest.TestCase):
    def test_the_bar_fills_with_what_is_used(self):
        """A bar that fills as a drive empties reads backwards."""
        code = without_comments(read("ui.c"))
        self.assertRegex(code, r"used\s*=\s*total\s*>\s*s->drives\[i\]\.free")

    def test_a_size_is_not_an_int(self):
        """A drive passes four thousand million bytes a long way."""
        self.assertRegex(without_comments(read("ui.h")),
                         r"uint64_t total,\s*free;")

    def test_the_firmware_reads_a_large_number_as_one(self):
        """cJSON keeps a number past an int in the double, and valueint
        then comes back truncated."""
        code = without_comments(read("main.c"))
        drives = re.search(r"cJSON_ArrayForEach\(one,drives\).*?\n    \}",
                           code, re.S)
        self.assertIsNotNone(drives)
        self.assertIn("valuedouble", drives.group(0))
        self.assertNotIn("total->valueint", drives.group(0))


class TheJobRunsItTest(unittest.TestCase):
    def test_the_preview_build_knows_the_check(self):
        self.assertIn("add_executable(check_pages check_pages.c",
                      read("CMakeLists.txt", PREVIEW))

    def test_the_job_builds_and_runs_it(self):
        with open(os.path.join(REPO, ".github", "workflows",
                               "companion-firmware.yml"),
                  encoding="utf-8") as handle:
            job = handle.read()
        self.assertIn("check_pages", job)
        self.assertIn("./preview-build/check_pages", job)


if __name__ == "__main__":
    unittest.main()


class BannerTest(unittest.TestCase):
    """The picture of the game, and who owns its bytes.

    What it looks like is checked where it can be drawn:
    firmware/companion/preview/check_pages.c takes a picture, replaces it,
    drops it, keeps it over a rebuild, and then takes two hundred of a
    quarter of a megabyte each and reads /proc/self/statm to see that the
    memory really went back. That needs a compiler, so it runs in the job.

    What these hold is the shape around it.
    """

    def main(self):
        return without_comments(read("main.c"))

    def test_the_decoder_is_on(self):
        defaults = os.path.join(COMPANION, "sdkconfig.defaults")
        with open(defaults, encoding="utf-8") as handle:
            text = handle.read()
        self.assertRegex(text, r"(?m)^CONFIG_LV_USE_TJPGD=y")

    def test_no_image_cache_is_asked_for(self):
        """A quarter of a megabyte stood here to keep the decoded
        picture, and it kept nothing.

        TJPGD hands LVGL one block at a time through get_area and never
        calls lv_image_decoder_add_to_cache, which is the one thing that
        puts a decode in the cache. Every other decoder in LVGL calls it.

        lv_malloc is the C library here, so the memory would have come
        out of internal RAM, where the Wi-Fi stack lives. check_pages
        draws the picture with no cache and passes."""
        defaults = os.path.join(COMPANION, "sdkconfig.defaults")
        with open(defaults, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotRegex(text, r"(?m)^CONFIG_LV_CACHE_DEF_SIZE=")
        with open(os.path.join(PREVIEW, "lv_conf.h"), encoding="utf-8") as h:
            self.assertNotRegex(h.read(), r"(?m)^#define LV_CACHE_DEF_SIZE")

    def test_the_decoder_never_asks_the_cache_to_hold_a_decode(self):
        """The rule above rests on this. If a later LVGL teaches TJPGD to
        cache, the reason for leaving the cache out is gone and somebody
        has to weigh it again."""
        decoder = os.path.join(COMPANION, "managed_components", "lvgl__lvgl",
                               "src", "libs", "tjpgd", "lv_tjpgd.c")
        if not os.path.exists(decoder):
            self.skipTest("the LVGL component is not checked out here")
        with open(decoder, encoding="utf-8") as handle:
            self.assertNotIn("lv_image_decoder_add_to_cache", handle.read())

    def test_the_decoder_is_allowed_to_read_bytes_in_memory(self):
        """TJPGD reads a file. LV_USE_FS_MEMFS is the driver that makes a
        block of memory look like one, and it carries no default in the
        Kconfig of the component, the same hole LV_USE_LOG had.

        Without it the decoder refuses the picture, the built-in decoder
        takes the bytes as a bitmap, and the card fills with the file read
        as pixels. The panel showed that and then died."""
        defaults = os.path.join(COMPANION, "sdkconfig.defaults")
        with open(defaults, encoding="utf-8") as handle:
            text = handle.read()
        self.assertRegex(text, r"(?m)^CONFIG_LV_USE_FS_MEMFS=y")
        letter = re.search(r"(?m)^CONFIG_LV_FS_MEMFS_LETTER=(\d+)", text)
        self.assertIsNotNone(letter, "the driver answers for no letter")
        self.assertTrue(chr(int(letter.group(1))).isupper())

    def test_only_a_baseline_picture_reaches_the_screen(self):
        """TJPGD reads SOF0 and nothing else: SOF1 to SOF15 come back
        JDR_FMT3. A progressive picture that gets past the door is one
        LVGL fails to open at every refresh."""
        code = without_comments(read("ui.c"))
        self.assertIn("kind==0xC0", code)
        gate = re.search(r"static bool jpeg_size\(.*?\n\}", code, re.S)
        self.assertIsNotNone(gate)
        # Every other frame header is turned away rather than walked past.
        self.assertRegex(gate.group(0),
                         r"(?s)kind>=0xC1&&kind<=0xCF.*?return false")

    def test_the_preview_is_built_the_same_way(self):
        """A preview configured differently from the board watches a
        screen the board never shows. The colour depth taught that once."""
        with open(os.path.join(PREVIEW, "lv_conf.h"), encoding="utf-8") as h:
            text = h.read()
        self.assertRegex(text, r"(?m)^#define LV_USE_TJPGD 1")
        self.assertRegex(text, r"(?m)^#define LV_USE_FS_MEMFS 1")

    def test_the_preview_shows_what_lvgl_complains_about(self):
        """LV_LOG_LEVEL_USER hides LV_LOG_ERROR, because USER is above
        ERROR in the order. The preview ran that way while LVGL was
        writing "Failed to open image" at every refresh, and nothing
        printed it."""
        with open(os.path.join(PREVIEW, "lv_conf.h"), encoding="utf-8") as h:
            text = h.read()
        level = re.search(r"(?m)^#define LV_LOG_LEVEL (\w+)", text)
        self.assertIsNotNone(level)
        self.assertIn(level.group(1),
                      ("LV_LOG_LEVEL_TRACE", "LV_LOG_LEVEL_INFO",
                       "LV_LOG_LEVEL_WARN"))

    def test_the_picture_is_fetched_when_the_game_changes(self):
        """Every three seconds would be 40 KB over the air every three
        seconds for a picture that did not change, at a machine somebody
        plays a game on."""
        code = self.main()
        self.assertRegex(code, r"strcmp\(playing_now,art_for\)\s*!=\s*0")
        fetch = re.search(r"if \(strcmp\(playing_now,art_for\).*?\n {12}\}",
                          code, re.S)
        self.assertIsNotNone(fetch)
        self.assertIn("fetch_artwork", fetch.group(0))

    def test_the_bytes_reach_the_screen_on_the_thread_that_draws(self):
        """panel_ui_banner touches LVGL objects. The network task must not
        call it, so the bytes are left under the lock and ui_tick takes
        them."""
        code = self.main()
        tick = re.search(r"static void ui_tick\(lv_timer_t \*timer\).*?\n\}",
                         code, re.S)
        self.assertIsNotNone(tick)
        self.assertIn("panel_ui_banner", tick.group(0))
        network = re.search(r"static void network_task\(void \*arg\).*\Z",
                            code, re.S)
        self.assertIsNotNone(network)
        self.assertNotIn("panel_ui_banner", network.group(0),
                         "the network task must not draw")

    def test_one_nobody_collected_is_freed_and_not_stacked(self):
        """Two games in a row inside one turn of the drawing timer. The
        older picture would otherwise be held until the panel restarts."""
        code = self.main()
        hand = re.search(r"static void hand_over_artwork\(.*?\n\}", code, re.S)
        self.assertIsNotNone(hand)
        self.assertRegex(hand.group(0), r"if \(pending_art\)\s*heap_caps_free")

    def test_the_buffer_is_given_back_down_to_what_arrived(self):
        """A picture is held for as long as a game runs. A quarter of a
        megabyte kept to hold forty thousand bytes is a quarter of a
        megabyte nobody else can have."""
        code = self.main()
        self.assertIn("heap_caps_realloc", code)

    def test_both_ends_name_the_same_ceiling(self):
        """A change at one end has to show as a picture that does not
        arrive, never as a buffer that overflows."""
        said = re.search(r"#define PANEL_ART_LIMIT \((\d+) \* 1024\)",
                         self.main())
        self.assertIsNotNone(said)
        with open(os.path.join(REPO, "server", "steamos_utility_center",
                               "steamapps.py"), encoding="utf-8") as handle:
            service = handle.read()
        theirs = re.search(r"ART_LIMIT = (\d+) \* 1024", service)
        self.assertIsNotNone(theirs)
        self.assertEqual(said.group(1), theirs.group(1))
