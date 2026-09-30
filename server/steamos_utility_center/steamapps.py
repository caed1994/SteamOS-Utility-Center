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

# Where Steam keeps the pictures it downloads, and which of them the
# panel draws.
#
# One directory for each game, read off the machine:
#
#     librarycache/1840/header.jpg              460 x 215
#     librarycache/1840/library_hero.jpg       1920 x 620
#     librarycache/1840/library_600x900.jpg     a portrait
#     librarycache/1840/logo.png
#     librarycache/1840/<a long hash>.jpg
#
# header.jpg is 460 across and the card on the panel is 460 across, so it
# goes up with nothing scaled. The hero is the same shape and far larger,
# and it is here as the answer for a game that has no header.
#
# Names and not a search. Steam has laid this directory out differently
# before, and a game with none of these gets no picture at all: a portrait
# stretched across a wide card looks worse than a card with a name on it.
ART_DIR = os.path.join("appcache", "librarycache")
ART_NAMES = ("header.jpg", "library_hero.jpg")

# What the panel carries over the network and decodes. A header is 30 to
# 60 KB. A hero above this leaves a game with a name and no picture, which
# is the lesser fault.
ART_LIMIT = 256 * 1024

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


# The frame header of a baseline JPEG, and the ones that are not a frame
# header at all although they sit in the same range.
BASELINE = 0xC0
NOT_A_FRAME = (0xC4, 0xC8, 0xCC)


def baseline_jpeg(path, read=512):
    """True for a JPEG the panel can decode.

    The panel decodes with TJPGD, and TJPGD reads baseline JPEG alone.
    Every other frame header, progressive among them, comes back
    JDR_FMT3. A picture that fails there costs the panel a transfer and
    leaves the card empty, so it is better not sent.

    Only the front of the file is read. The frame header stands in front
    of the entropy data, which is the rest of it.
    """
    try:
        with open(path, "rb") as handle:
            front = handle.read(read)
    except OSError:                                     # pragma: no cover
        return False
    if len(front) < 4 or front[0] != 0xFF or front[1] != 0xD8:
        return False
    at = 2
    while at + 3 < len(front):
        if front[at] != 0xFF:
            return False
        kind = front[at + 1]
        if kind == 0xFF:                    # padding in front of a marker
            at += 1
            continue
        if kind == 0xD8 or kind == 0x01 or 0xD0 <= kind <= 0xD7:
            at += 2                         # the ones that carry no length
            continue
        if kind == BASELINE:
            return True
        if 0xC0 <= kind <= 0xCF and kind not in NOT_A_FRAME:
            return False                    # a frame header of another kind
        at += 2 + ((front[at + 2] << 8) | front[at + 3])
    return False


def artwork(appid, home=None):
    """The picture for that number, or "" where there is none.

    A path built from a number and a name of this module's own. Nothing
    from the network reaches it, so there is no way to ask this for a file
    somewhere else.

    A picture the panel cannot decode counts as none. See baseline_jpeg.
    """
    if appid is None:
        return ""
    home = os.path.expanduser("~") if home is None else home
    for root in STEAM_ROOTS:
        where = os.path.join(home, root, ART_DIR, str(int(appid)))
        for name in ART_NAMES:
            path = os.path.join(where, name)
            try:
                if os.path.getsize(path) > ART_LIMIT:
                    continue
            except OSError:
                continue
            if baseline_jpeg(path):
                return path
    return ""


def now_playing_art(root=PROC, home=None):
    """The picture of the game that runs, or "" for none.

    Two reasons for nothing, and the panel draws both the same way: no
    game, or a game whose picture Steam never fetched.
    """
    return artwork(running_appid(root), home=home)
