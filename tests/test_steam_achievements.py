# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""How many achievements of the game that runs are unlocked.

The Steam client keeps what the library page of a game shows in one JSON
file for each account and game, and its "achievements" entry carries two
counts. Read off a real machine, for DragonSword : Awakening:

    json  : {'vecHighlight': 12, 'vecUnachieved': 7,
             'vecAchievedHidden': 12, 'nTotal': 60, 'nAchieved': 49}

and the schema of the same game in appcache/stats counted 60 as well. The
same file held a second entry whose name holds the word "achiev" and whose
data is a string, and the first probe tripped on it. These rules keep that
case, because it is the one the machine really has.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

from steamos_utility_center import steamapps    # noqa: E402

from test_steamapps import fake_proc            # noqa: E402

GAME = 4570720


def page(achieved=49, total=60, extra=True):
    """A library page in the shape the machine has: a list of pairs."""
    entries = [
        ["achievements", {"version": 3, "data": {
            "vecHighlight": [{"strID": "A"}] * 12,
            "vecUnachieved": [{"strID": "B"}] * 7,
            "vecAchievedHidden": [{"strID": "C"}] * 12,
            "nTotal": total, "nAchieved": achieved}}],
        ["friends", {"version": 1, "data": {"in_game": []}}],
    ]
    if extra:
        # The entry that tripped the first probe. Its name holds the word,
        # and its data is a string.
        entries.append(["achievementmap", {"version": 2,
                                           "data": "[[\"A\",{}]]"}])
    return entries


def write(home, content, account="12345", appid=GAME, raw=None):
    where = os.path.join(home, ".local", "share", "Steam", "userdata",
                         account, "config", "librarycache")
    os.makedirs(where, exist_ok=True)
    path = os.path.join(where, "%d.json" % appid)
    with open(path, "wb" if raw is not None else "w") as handle:
        if raw is not None:
            handle.write(raw)
        else:
            json.dump(content, handle)
    return path


class CountTest(unittest.TestCase):
    def setUp(self):
        steamapps._page_cache.clear()

    def test_the_two_numbers_come_out_of_the_page(self):
        with tempfile.TemporaryDirectory() as home:
            write(home, page())
            self.assertEqual(steamapps.achievements(GAME, home), (49, 60))

    def test_the_entry_with_a_string_for_data_does_not_get_in_the_way(self):
        """The first probe read every name that held "achiev", and the
        second of those carried a string."""
        with tempfile.TemporaryDirectory() as home:
            entries = page()
            entries.insert(0, entries.pop())      # the trap in front
            write(home, entries)
            self.assertEqual(steamapps.achievements(GAME, home), (49, 60))

    def test_a_page_written_as_a_dict_reads_the_same(self):
        with tempfile.TemporaryDirectory() as home:
            write(home, dict(page()))
            self.assertEqual(steamapps.achievements(GAME, home), (49, 60))

    def test_everything_unlocked_and_nothing_unlocked_are_both_counts(self):
        with tempfile.TemporaryDirectory() as home:
            write(home, page(60, 60))
            self.assertEqual(steamapps.achievements(GAME, home), (60, 60))
        steamapps._page_cache.clear()
        with tempfile.TemporaryDirectory() as home:
            write(home, page(0, 60))
            self.assertEqual(steamapps.achievements(GAME, home), (0, 60))


class NothingToCountTest(unittest.TestCase):
    """None, for everything the panel draws as a dash."""

    def setUp(self):
        steamapps._page_cache.clear()

    def test_no_game(self):
        self.assertIsNone(steamapps.achievements(None))

    def test_a_game_whose_page_the_client_never_wrote(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertIsNone(steamapps.achievements(GAME, home))

    def test_a_game_without_achievements(self):
        with tempfile.TemporaryDirectory() as home:
            write(home, [["friends", {"data": {}}]])
            self.assertIsNone(steamapps.achievements(GAME, home))

    def test_numbers_that_cannot_be_counts(self):
        for achieved, total in ((61, 60), (-1, 60), (0, 0), (True, 60),
                                ("49", 60), (49, None), (4.5, 60)):
            steamapps._page_cache.clear()
            with tempfile.TemporaryDirectory() as home:
                write(home, page(achieved, total))
                self.assertIsNone(steamapps.achievements(GAME, home),
                                  (achieved, total))

    def test_a_file_that_is_not_json(self):
        with tempfile.TemporaryDirectory() as home:
            write(home, None, raw=b"\xff\xfe not json at all")
            self.assertIsNone(steamapps.achievements(GAME, home))

    def test_a_file_far_too_large_is_not_read(self):
        with tempfile.TemporaryDirectory() as home:
            write(home, None, raw=b" " * (steamapps.PAGE_LIMIT + 1))
            self.assertIsNone(steamapps.achievements(GAME, home))

    def test_the_path_is_built_and_never_taken_from_a_caller(self):
        with self.assertRaises(ValueError):
            steamapps.achievements("../../../../etc/passwd")


class WhichFileTest(unittest.TestCase):
    def setUp(self):
        steamapps._page_cache.clear()

    def test_the_newest_page_across_the_accounts_is_the_one(self):
        """The account that uses the machine is the one whose client last
        wrote a page. A second one that played the same game long ago
        leaves an older file."""
        with tempfile.TemporaryDirectory() as home:
            old = write(home, page(3, 60), account="1111")
            os.utime(old, (time.time() - 86400, time.time() - 86400))
            write(home, page(49, 60), account="2222")
            self.assertEqual(steamapps.achievements(GAME, home), (49, 60))

    def test_a_page_written_again_is_read_again(self):
        """Kept between polls, but not past a change of the file."""
        with tempfile.TemporaryDirectory() as home:
            path = write(home, page(49, 60))
            self.assertEqual(steamapps.achievements(GAME, home), (49, 60))
            write(home, page(50, 60))
            later = time.time() + 5
            os.utime(path, (later, later))
            self.assertEqual(steamapps.achievements(GAME, home), (50, 60))


class _CountCase(unittest.TestCase):
    def setUp(self):
        steamapps._page_cache.clear()
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        # The runtime directory of the person that runs the tests is not
        # read: a watcher there can hold counts of its own.
        self.live = os.path.join(runtime.name, steamapps.LIVE_NAME)

    def count(self, where, home):
        return steamapps.now_playing_achievements(where, home, live=self.live)


class RunningGameTest(_CountCase):
    def test_the_game_that_runs_is_the_one_counted(self):
        with tempfile.TemporaryDirectory() as where:
            with tempfile.TemporaryDirectory() as home:
                fake_proc(where, [(900, "reaper", [
                    "reaper", "SteamLaunch", "AppId=%d" % GAME, "--", "x"])])
                write(home, page())
                self.assertEqual(self.count(where, home),
                                 {"achieved": 49, "total": 60})

    def test_no_game_is_none_and_not_a_zero(self):
        """0 / 60 is a real answer about a game, and nothing running is
        not that answer."""
        with tempfile.TemporaryDirectory() as where:
            with tempfile.TemporaryDirectory() as home:
                fake_proc(where, [(1, "systemd", ["/sbin/init"])])
                steamapps.publish_live(GAME, 50, 60, path=self.live)
                self.assertIsNone(self.count(where, home))


class LiveCountTest(_CountCase):
    """The counts of the achievement watcher, which follow each unlock.

    The page is written when Steam lays it out, which is at the start of
    the game. An unlock in the game thus did not change the panel.
    """

    def running(self, where):
        fake_proc(where, [(900, "reaper", [
            "reaper", "SteamLaunch", "AppId=%d" % GAME, "--", "x"])])

    def test_the_live_count_comes_before_the_page(self):
        with tempfile.TemporaryDirectory() as where:
            with tempfile.TemporaryDirectory() as home:
                self.running(where)
                write(home, page(49, 60))
                steamapps.publish_live(GAME, 50, 60, path=self.live)
                self.assertEqual(self.count(where, home),
                                 {"achieved": 50, "total": 60})

    def test_a_live_count_with_no_page_is_still_shown(self):
        with tempfile.TemporaryDirectory() as where:
            with tempfile.TemporaryDirectory() as home:
                self.running(where)
                steamapps.publish_live(GAME, 1, 60, path=self.live)
                self.assertEqual(self.count(where, home),
                                 {"achieved": 1, "total": 60})

    def test_the_count_of_a_different_game_is_not_used(self):
        with tempfile.TemporaryDirectory() as where:
            with tempfile.TemporaryDirectory() as home:
                self.running(where)
                write(home, page(49, 60))
                steamapps.publish_live(GAME + 1, 5, 10, path=self.live)
                self.assertEqual(self.count(where, home),
                                 {"achieved": 49, "total": 60})

    def test_with_the_counts_removed_the_page_is_the_answer(self):
        with tempfile.TemporaryDirectory() as where:
            with tempfile.TemporaryDirectory() as home:
                self.running(where)
                write(home, page(49, 60))
                steamapps.publish_live(GAME, 50, 60, path=self.live)
                steamapps.clear_live(path=self.live)
                self.assertFalse(os.path.exists(self.live))
                self.assertEqual(self.count(where, home),
                                 {"achieved": 49, "total": 60})
                # A second removal finds no file, and that is not a fault.
                steamapps.clear_live(path=self.live)

    def test_a_file_that_is_not_counts_gives_the_page(self):
        bad = [b"", b"{", b"[1, 2]", b"\xff\xfe",
               b'{"appid": %d, "achieved": 61, "total": 60}' % GAME,
               b'{"appid": %d, "achieved": -1, "total": 60}' % GAME,
               b'{"appid": %d, "achieved": 1, "total": 0}' % GAME,
               b'{"appid": %d, "achieved": true, "total": 60}' % GAME,
               b'{"appid": %d, "achieved": 1.0, "total": 60}' % GAME,
               b'{"appid": "%d", "achieved": 1, "total": 60}' % GAME,
               b'{"appid": %d.0, "achieved": 1, "total": 60}' % GAME,
               b'{"achieved": 1, "total": 60}',
               b'{"appid": %d, "achieved": 1, "total": 60}' % GAME
               + b" " * steamapps.LIVE_LIMIT]
        with tempfile.TemporaryDirectory() as where:
            with tempfile.TemporaryDirectory() as home:
                self.running(where)
                write(home, page(49, 60))
                for raw in bad:
                    with open(self.live, "wb") as handle:
                        handle.write(raw)
                    self.assertEqual(self.count(where, home),
                                     {"achieved": 49, "total": 60}, raw[:60])

    def test_the_file_is_in_the_runtime_directory_of_the_user(self):
        """The watcher and the panel service are user services of one
        user, and systemd gives both the same XDG_RUNTIME_DIR."""
        with tempfile.TemporaryDirectory() as runtime:
            original = os.environ.get("XDG_RUNTIME_DIR")
            os.environ["XDG_RUNTIME_DIR"] = runtime
            try:
                self.assertEqual(steamapps.live_path(),
                                 os.path.join(runtime, steamapps.LIVE_NAME))
                steamapps.publish_live(GAME, 2, 3)
                self.assertEqual(steamapps.live_achievements(GAME), (2, 3))
                self.assertEqual(os.listdir(runtime), [steamapps.LIVE_NAME])
            finally:
                if original is None:
                    del os.environ["XDG_RUNTIME_DIR"]
                else:
                    os.environ["XDG_RUNTIME_DIR"] = original


if __name__ == "__main__":
    unittest.main()
