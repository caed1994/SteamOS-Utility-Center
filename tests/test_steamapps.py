# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which game runs, read off the machine.

Steam publishes nothing that names it. What it does, is start every game
through a wrapper whose command line carries the number, and write the name
of that number into a manifest. Both are files, both are
read only, and neither needs Steam to answer anything.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

from steamos_utility_center import steamapps       # noqa: E402


def fake_proc(where, entries):
    """Builds a /proc with the processes given, as (pid, comm, cmdline)."""
    for pid, comm, cmdline in entries:
        directory = os.path.join(where, str(pid))
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "comm"), "w") as handle:
            handle.write(comm + "\n")
        with open(os.path.join(directory, "cmdline"), "wb") as handle:
            handle.write(b"\0".join(part.encode() for part in cmdline) + b"\0")
    return where


class RunningTest(unittest.TestCase):
    def test_it_reads_the_number_out_of_the_wrapper(self):
        with tempfile.TemporaryDirectory() as where:
            fake_proc(where, [
                (1, "systemd", ["/sbin/init"]),
                (900, "reaper", ["reaper", "SteamLaunch", "AppId=1245620",
                                 "--", "/game/eldenring.exe"]),
            ])
            self.assertEqual(steamapps.running_appid(where), 1245620)

    def test_a_command_that_merely_says_AppId_is_not_a_game(self):
        """The rule this is here for.

        A first version searched every command line for AppId= on its own.
        The first thing it found on the machine that wrote it was the shell
        that wrote the file, because the example in the comment sat in its
        arguments. The name of the process is what decides.
        """
        with tempfile.TemporaryDirectory() as where:
            fake_proc(where, [
                (500, "bash", ["/bin/bash", "-c",
                               "echo reaper SteamLaunch AppId=1234"]),
                (501, "grep", ["grep", "-r", "SteamLaunch AppId=", "/home"]),
            ])
            self.assertIsNone(steamapps.running_appid(where))

    def test_the_wrapper_without_a_launch_is_not_a_game_either(self):
        with tempfile.TemporaryDirectory() as where:
            fake_proc(where, [(900, "reaper", ["reaper", "--", "/bin/true"])])
            self.assertIsNone(steamapps.running_appid(where))

    def test_steam_itself_is_not_a_game(self):
        """A panel that reads "Steam" while somebody sits in the library
        has learnt nothing."""
        with tempfile.TemporaryDirectory() as where:
            fake_proc(where, [(900, "reaper", ["reaper", "SteamLaunch",
                                               "AppId=7", "--", "steam"])])
            self.assertIsNone(steamapps.running_appid(where))

    def test_a_process_that_exits_mid_walk_is_stepped_over(self):
        with tempfile.TemporaryDirectory() as where:
            os.makedirs(os.path.join(where, "777"))      # no comm, no cmdline
            fake_proc(where, [(900, "reaper", ["reaper", "SteamLaunch",
                                               "AppId=620", "--", "portal2"])])
            self.assertEqual(steamapps.running_appid(where), 620)


class LibraryTest(unittest.TestCase):
    def build(self, home, extra=None):
        steam = os.path.join(home, ".local", "share", "Steam", "steamapps")
        os.makedirs(steam)
        text = '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n' % (
            os.path.join(home, ".local", "share", "Steam"))
        if extra:
            os.makedirs(os.path.join(extra, "steamapps"), exist_ok=True)
            text += '\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n' % extra
        text += "}\n"
        with open(os.path.join(steam, "libraryfolders.vdf"), "w") as handle:
            handle.write(text)
        return steam

    def test_it_finds_the_card_beside_the_internal_drive(self):
        with tempfile.TemporaryDirectory() as home:
            with tempfile.TemporaryDirectory() as card:
                steam = self.build(home, card)
                found = steamapps.libraries(home)
                self.assertIn(steam, found)
                self.assertIn(os.path.join(card, "steamapps"), found)

    def test_a_machine_with_no_steam_answers_with_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(steamapps.libraries(home), [])

    def test_the_name_comes_out_of_the_manifest(self):
        with tempfile.TemporaryDirectory() as home:
            steam = self.build(home)
            with open(os.path.join(steam, "appmanifest_620.acf"), "w") as f:
                f.write('"AppState"\n{\n\t"appid"\t\t"620"\n'
                        '\t"name"\t\t"Portal 2"\n}\n')
            self.assertEqual(steamapps.app_name(620, home), "Portal 2")

    def test_every_library_is_read_and_not_only_the_first(self):
        """A game moved to the card has its manifest only there."""
        with tempfile.TemporaryDirectory() as home:
            with tempfile.TemporaryDirectory() as card:
                self.build(home, card)
                with open(os.path.join(card, "steamapps",
                                       "appmanifest_570.acf"), "w") as f:
                    f.write('"AppState"\n{\n\t"name"\t\t"Dota 2"\n}\n')
                self.assertEqual(steamapps.app_name(570, home), "Dota 2")

    def test_a_number_nobody_holds_is_empty_and_not_a_crash(self):
        with tempfile.TemporaryDirectory() as home:
            self.build(home)
            self.assertEqual(steamapps.app_name(999999, home), "")


class NowPlayingTest(unittest.TestCase):
    def test_nothing_playing_is_an_empty_word(self):
        with tempfile.TemporaryDirectory() as where:
            with tempfile.TemporaryDirectory() as home:
                fake_proc(where, [(1, "systemd", ["/sbin/init"])])
                self.assertEqual(steamapps.now_playing(where, home), "")

    def test_a_game_with_no_manifest_still_says_something(self):
        """It runs. The number is worth more than an empty card, and it is
        what somebody types into a search."""
        with tempfile.TemporaryDirectory() as where:
            with tempfile.TemporaryDirectory() as home:
                fake_proc(where, [(900, "reaper", ["reaper", "SteamLaunch",
                                                   "AppId=42", "--", "x"])])
                self.assertEqual(steamapps.now_playing(where, home), "App 42")


if __name__ == "__main__":
    unittest.main()
