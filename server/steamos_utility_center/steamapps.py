# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which game Steam runs now, read from the machine and not from Steam.

The panel shows the name of the game. Steam publishes no such thing: there
is no socket to ask and no file that names the game. What there is, is the
way Steam starts one, and that leaves two tracks.

The first is the process. Steam wraps every launch in `reaper`, and the
command line of that process carries `AppId=` and the number. So a walk of
/proc says which game runs, and it says it for a native game and a Proton
one alike, because the wrapper is the same.

The second is the name. The number alone is no use on a wall panel, and the
name of it sits in appmanifest_<number>.acf in the library that holds the
game. libraryfolders.vdf lists those libraries, which is how a game on the
SD card is found as easily as one on the internal drive.

Neither track needs the network, a login, or anything of Steam's beyond the
files it already writes. Both are read only.
"""

from __future__ import annotations

import os
import re

PROC = "/proc"

# Where Steam keeps itself. Two paths for one directory: the second is the
# symbolic link that older installations still carry, and a machine that has
# been through an upgrade can have either.
STEAM_ROOTS = (os.path.join(".local", "share", "Steam"),
               os.path.join(".steam", "steam"))

# The file that lists every library, including the one on a card. Steam
# writes it in the steamapps directory of the first library.
LIBRARY_LIST = os.path.join("steamapps", "libraryfolders.vdf")

# The wrapper Steam puts in front of every launch, and the shape of its
# command line. Both are needed, and finding that out cost a false alarm:
# a first version searched every command line for AppId= alone, and the
# first thing it found was the shell that wrote this file, because the
# text of this comment sat in its arguments.
#
# So the name of the process decides and the command line confirms it. A
# tuple for the name, the way desktop.py holds the names of a Game Mode
# session. Steam gave this wrapper another name once before.
WRAPPERS = ("reaper",)
LAUNCH = re.compile(r"SteamLaunch\s+AppId=(\d+)")

# A line of a VDF file: a quoted key, then a quoted value.
VDF_PAIR = re.compile(r'"([^"]+)"\s+"([^"]*)"')

# Numbers that are not a game. 0 is what a launch with no app carries, and
# Steam itself is 7. A panel that reads "Steam" while somebody sits in the
# library has learnt nothing.
NOT_A_GAME = frozenset((0, 7))


def running_appid(root=PROC):
    """The number of the game that runs, or None.

    A walk of /proc and not a question to Steam. The name of the process
    has to be the wrapper and the command line has to carry the launch, so
    a command that merely mentions an AppId is not a game.
    """
    try:
        entries = os.listdir(root)
    except OSError:                                     # pragma: no cover
        return None
    for entry in sorted(entries, key=lambda name: int(name)
                        if name.isdigit() else 0):
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(root, entry, "comm")) as handle:
                name = handle.read().strip()
        except OSError:
            continue            # it exited between the listing and the read
        if not any(name.startswith(front) for front in WRAPPERS):
            continue
        try:
            with open(os.path.join(root, entry, "cmdline"), "rb") as handle:
                line = handle.read().replace(b"\0", b" ")
        except OSError:
            continue
        found = LAUNCH.search(line.decode("utf-8", "replace"))
        if not found:
            continue
        appid = int(found.group(1))
        if appid not in NOT_A_GAME:
            return appid
    return None


def libraries(home=None):
    """Every steamapps directory this machine holds, first one first.

    The list in libraryfolders.vdf and the directory that holds it. A card
    that is out of the slot leaves a path that is not there, and that is
    left in: the caller opens files and a missing directory answers by
    itself.
    """
    home = os.path.expanduser("~") if home is None else home
    found, seen = [], set()
    for root in STEAM_ROOTS:
        base = os.path.join(home, root)
        here = os.path.join(base, "steamapps")
        if here not in seen and os.path.isdir(here):
            seen.add(here)
            found.append(here)
        try:
            with open(os.path.join(base, LIBRARY_LIST),
                      encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        for key, value in VDF_PAIR.findall(text):
            if key != "path":
                continue
            other = os.path.join(value, "steamapps")
            if other not in seen:
                seen.add(other)
                found.append(other)
    return found


def app_name(appid, home=None, where=None):
    """The name of that number, or "" if no library holds it.

    A game that was moved to a card leaves its manifest behind in neither
    place, so every library is read and not only the first.
    """
    if appid is None:
        return ""
    where = libraries(home) if where is None else where
    for directory in where:
        path = os.path.join(directory, "appmanifest_%d.acf" % appid)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        for key, value in VDF_PAIR.findall(text):
            if key == "name" and value.strip():
                return value.strip()
    return ""


def now_playing(root=PROC, home=None, where=None):
    """The name of the game that runs, or "".

    An empty answer is the ordinary case and not a fault: most of the time
    no game runs. The panel then shows nothing rather than a word that
    means nothing.
    """
    appid = running_appid(root)
    if appid is None:
        return ""
    name = app_name(appid, home=home, where=where)
    # A game whose manifest is gone still runs. The number is worth more
    # than an empty card, and it is what somebody types into a search.
    return name or ("App %d" % appid)
