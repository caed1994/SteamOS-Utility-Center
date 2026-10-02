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
        for built in ("pc_area=head_area(s,", "pad_area=head_area(s,",
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
                     "playing_name", "no_drives", "drive_rows",
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


class AchievementParseTest(unittest.TestCase):
    """The two counts, read off the answer of the service."""

    def main(self):
        with open(os.path.join(FIRMWARE, "main.c"), encoding="utf-8") as h:
            return without_comments(h.read())

    def test_both_or_neither(self):
        """A count without its total, or past it, is not drawn. The
        service holds the same rules; this is the second reader of them."""
        code = self.main()
        self.assertIn('cJSON_GetObjectItemCaseSensitive(root,"achievements")',
                      code)
        self.assertRegex(code, r"of->valueint>0")
        self.assertRegex(code, r"got->valueint>=0")
        self.assertRegex(code, r"got->valueint<=of->valueint")
        self.assertRegex(code, r"state\.achievements_total=counts\?of->valueint:0")

    def test_the_names_of_the_service_are_the_ones_read(self):
        """The panel reads "achieved" and "total", which is what
        steamapps.now_playing_achievements writes."""
        code = self.main()
        self.assertIn('"achieved"', code)
        self.assertIn('"total"', code)


if __name__ == "__main__":
    unittest.main()

