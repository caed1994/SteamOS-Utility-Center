# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the second page of the panel reads, and what its one button sends.

The panel scrolls sideways now. The page beside the first one shows which
session runs, which game runs, and how full each drive is. The first two
come from files this machine already writes; the third is a statvfs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

from steamos_utility_center import companion       # noqa: E402


class DrivesTest(unittest.TestCase):
    def test_it_reads_the_root_and_calls_it_by_a_name(self):
        found = companion.drives()
        self.assertTrue(found, "no drive at all, not even the root")
        self.assertEqual(found[0]["name"], "SSD")
        self.assertGreater(found[0]["total"], 0)
        self.assertGreaterEqual(found[0]["free"], 0)
        self.assertLessEqual(found[0]["free"], found[0]["total"])

    def test_it_counts_the_room_a_person_can_fill(self):
        """f_bavail and not f_bfree. The second counts the blocks the
        filesystem keeps back for root, and nobody installs a game into
        those."""
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "server",
                "steamos_utility_center", "companion.py")) as handle:
            code = handle.read()
        # The field and not the word. The note beside it names f_bfree to
        # say why it is not used, and a rule that reads that note fails on
        # the file it is meant to pass.
        self.assertIn("space.f_bavail", code)
        self.assertNotIn("space.f_bfree", code)

    def test_a_path_it_cannot_read_is_left_out_and_not_shown_empty(self):
        """An empty bar reads as plenty of room."""
        self.assertEqual(companion.drives(root="/nowhere/at/all",
                                          removable="/nowhere/either"), [])

    def test_a_card_under_the_media_root_comes_with_it(self):
        with tempfile.TemporaryDirectory() as where:
            os.makedirs(os.path.join(where, "deck", "SDCARD"))
            # Nothing there is a mount, so nothing is a drive. The walk
            # still has to come back rather than raise.
            self.assertEqual(companion.drives(root="/nowhere",
                                              removable=where), [])


class SessionTest(unittest.TestCase):
    def test_it_answers_one_of_two_words(self):
        self.assertIn(companion.session_mode(), ("game", "desktop"))

    def test_the_two_presses_name_where_to_go(self):
        """And not "the other one". The panel knows the mode from a status
        that is up to three seconds old, so a toggle would now and then
        switch to the side it is already on."""
        self.assertIn("desktop_mode", companion.ACTIONS)
        self.assertIn("game_mode", companion.ACTIONS)
        self.assertEqual(companion.ACTIONS["desktop_mode"][0],
                         "steamos-session-select")
        self.assertEqual(companion.ACTIONS["game_mode"][-1], "gamescope")

    def test_every_press_is_a_name_from_the_table(self):
        """The panel sends a name, never a command."""
        code, body = companion.press("rm -rf /")
        self.assertEqual(code, 400)
        self.assertIn("error", body)


class MissingCommandTest(unittest.TestCase):
    """A machine without the command answers, rather than falling over.

    steamos-session-select is on SteamOS and on nothing else. Before this
    the exception left the handler, the panel got a 500 with a traceback
    in the log, and the person at the panel got nothing.
    """

    def test_it_comes_back_with_a_code_and_not_an_exception(self):
        keep = companion.ACTIONS.get("desktop_mode")
        companion.ACTIONS["desktop_mode"] = ("/nowhere/at/all/please",)
        try:
            code, body = companion.press("desktop_mode")
        finally:
            companion.ACTIONS["desktop_mode"] = keep
        self.assertEqual(code, 501)
        self.assertIn("error", body)


class StatusTest(unittest.TestCase):
    def test_the_answer_carries_what_the_second_page_draws(self):
        answer = companion.status()
        for key in ("session", "playing", "drives"):
            self.assertIn(key, answer, "the panel reads %s" % key)
        self.assertIsInstance(answer["playing"], str)
        self.assertIsInstance(answer["drives"], list)

    def test_it_still_carries_what_the_first_page_draws(self):
        answer = companion.status()
        for key in ("host", "controllers", "audio", "telemetry", "wake"):
            self.assertIn(key, answer)


if __name__ == "__main__":
    unittest.main()
