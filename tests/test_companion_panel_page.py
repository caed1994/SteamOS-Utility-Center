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
    """Which filesystems count as a drive.

    Reported from the board: the panel said 0.6 GB free of 5.0, and the
    machine holds 920 GiB on /home and a second NVMe of 4 TB. The first
    version read "/" and called it the internal drive. On SteamOS "/" is
    a read only 5 GiB partition that carries the A and B of an update, and
    the second drive was at neither of the two paths it looked at.

    So the list comes from the kernel now. These hold the rules that pick
    a drive out of it, against a /proc/mounts written here.
    """

    def mounts(self, where, lines):
        path = os.path.join(where, "mounts")
        with open(path, "w") as handle:
            handle.write("".join(line + "\n" for line in lines))
        return path

    def test_a_filesystem_on_no_drive_is_not_a_drive(self):
        """proc, sysfs, every tmpfs and the overlays. A device under /dev
        is what tells a drive from those."""
        with tempfile.TemporaryDirectory() as where:
            path = self.mounts(where, [
                "proc /proc proc rw,nosuid 0 0",
                "tmpfs /run tmpfs rw,nosuid 0 0",
                "overlay /var/lib/x overlay rw,relatime 0 0",
            ])
            self.assertEqual(companion.mounted(path), [])

    def test_compressed_memory_is_not_a_drive(self):
        with tempfile.TemporaryDirectory() as where:
            path = self.mounts(where, ["/dev/zram0 /swap ext4 rw,relatime 0 0"])
            self.assertEqual(companion.mounted(path), [])

    def test_one_nobody_can_write_to_is_not_a_place_for_a_game(self):
        """Which is what the root of SteamOS is."""
        with tempfile.TemporaryDirectory() as where:
            path = self.mounts(where, [
                "/dev/nvme0n1p4 / btrfs ro,relatime,subvol=/ 0 0",
                "/dev/nvme0n1p8 /home ext4 rw,relatime 0 0",
            ])
            self.assertEqual([point for _d, point in companion.mounted(path)],
                             ["/home"])

    def test_a_space_in_a_path_comes_back_as_a_space(self):
        """/proc/mounts writes one as \\040."""
        with tempfile.TemporaryDirectory() as where:
            path = self.mounts(where, [
                "/dev/sda1 /run/media/deck/My\\040Games ext4 rw 0 0"])
            self.assertEqual(companion.mounted(path)[0][1],
                             "/run/media/deck/My Games")

    def test_one_drive_is_one_row_however_often_it_is_mounted(self):
        """A btrfs with subvolumes is mounted several times over, and
        three rows of the same drive tell nobody anything."""
        with tempfile.TemporaryDirectory() as where:
            path = self.mounts(where, [
                "/dev/nvme0n1p8 %s ext4 rw,relatime 0 0" % where,
                "/dev/nvme0n1p8 %s ext4 rw,relatime,subvol=/a 0 0" % where,
                "/dev/nvme0n1p8 %s ext4 rw,relatime,subvol=/b 0 0" % where,
            ])
            self.assertEqual(len(companion.drives(path, floor=0)), 1)

    def test_a_filesystem_of_the_operating_system_is_left_out(self):
        """/var is 256 MiB and the root of SteamOS is 5 GiB. Neither is a
        place anybody installs a game into."""
        with tempfile.TemporaryDirectory() as where:
            path = self.mounts(where, [
                "/dev/nvme0n1p6 %s ext4 rw,relatime 0 0" % where])
            self.assertEqual(companion.drives(path, floor=1 << 60), [])
            self.assertEqual(len(companion.drives(path, floor=0)), 1)

    def test_the_big_ones_come_first(self):
        """The panel has room for three, and the big ones are the ones a
        person means."""
        with tempfile.TemporaryDirectory() as where:
            found = companion.drives(floor=0)
            sizes = [one["total"] for one in found]
            self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_the_name_is_the_end_of_the_path(self):
        self.assertEqual(companion.drive_name("/home"), "home")
        self.assertEqual(companion.drive_name("/run/media/deck/Games"),
                         "Games")
        self.assertEqual(companion.drive_name("/"), "System")

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

    def test_a_mount_it_cannot_read_is_left_out_and_not_shown_empty(self):
        """An empty bar reads as plenty of room."""
        with tempfile.TemporaryDirectory() as where:
            path = self.mounts(where, [
                "/dev/sda1 /nowhere/at/all ext4 rw,relatime 0 0"])
            self.assertEqual(companion.drives(path, floor=0), [])


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
