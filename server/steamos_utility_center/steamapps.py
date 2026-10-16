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

import glob
import json
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


# What the library page of a game shows, as the Steam client keeps it: one
# JSON file for each account and each game, under the account.
#
# Read off a real machine: the "achievements" entry carries nAchieved and
# nTotal, and the total there agrees with the count of achievements in
# appcache/stats/UserGameStatsSchema_<appid>.bin, which is a second file
# written by a different part of the client. The panel shows these two
# numbers and nothing else out of the file.
#
# It is the cache of a page. Steam writes it when it lays that page out,
# so an achievement unlocked a minute ago can be missing until the page is
# built again. The counts of the achievement watcher fill that gap: see
# live_path. The binary stats file next to the schema is what the client
# updates at an unlock, but which of its entries hold achievements could
# not be read off the machine, so it is not used.
LIBRARY_PAGES = os.path.join("config", "librarycache")
ACHIEVEMENTS_KEY = "achievements"

# A page of a game is tens of kilobytes. A file far past that is not one
# of these, and it is not read into memory to find out.
PAGE_LIMIT = 4 * 1024 * 1024

# The last page read, by its path, its time and its size. status() asks
# every three seconds and the file changes a few times a day.
_page_cache = {}


def _page_of(appid, home):
    """The newest page of that game across the accounts on this machine.

    The newest, because the account that uses this machine is the one
    whose client last wrote a page. A second account that played the same
    game a year ago leaves a file that is older.
    """
    newest = None
    for root in STEAM_ROOTS:
        pattern = os.path.join(home, root, "userdata", "*", LIBRARY_PAGES,
                               "%d.json" % appid)
        for path in glob.glob(pattern):
            try:
                stamp = os.stat(path)
            except OSError:
                continue
            if newest is None or stamp.st_mtime > newest[1].st_mtime:
                newest = (path, stamp)
    return newest


def _numbers(achieved, total):
    """(achieved, total) if the two are counts that agree, or None."""
    # bool is an int in Python, and True is not a count.
    numbers = all(isinstance(n, int) and not isinstance(n, bool)
                  for n in (achieved, total))
    if not numbers or total <= 0 or not 0 <= achieved <= total:
        return None
    return achieved, total


def _counts(page):
    """(achieved, total) out of a parsed page, or None.

    The page is a list of pairs, a name and an entry, and a dict is taken
    as well. Only the entry called exactly "achievements" counts: the same
    file carries other entries whose names hold that word and whose data is
    a string, which a looser match once tripped on.
    """
    entries = page.items() if isinstance(page, dict) else page
    if not isinstance(entries, (list, type({}.items()))):
        return None
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        name, value = entry
        if name != ACHIEVEMENTS_KEY or not isinstance(value, dict):
            continue
        data = value.get("data", value)
        if not isinstance(data, dict):
            return None
        return _numbers(data.get("nAchieved"), data.get("nTotal"))
    return None


def achievements(appid, home=None):
    """(achieved, total) for that game, or None where it is not known.

    None covers a game with no achievements, a game whose page the client
    never wrote, and a file that is not a page of this kind. The panel
    draws those the same way.

    The path is built from a number and names of this module's own, the
    same rule the rest of this module keeps.
    """
    if appid is None:
        return None
    appid = int(appid)
    home = os.path.expanduser("~") if home is None else home
    found = _page_of(appid, home)
    if found is None:
        return None
    path, stamp = found
    key = (path, stamp.st_mtime_ns, stamp.st_size)
    if _page_cache.get("key") == key:
        return _page_cache["value"]
    value = None
    if stamp.st_size <= PAGE_LIMIT:
        try:
            with open(path, "rb") as handle:
                raw = handle.read(PAGE_LIMIT + 1)
            if len(raw) <= PAGE_LIMIT:
                value = _counts(json.loads(raw.decode("utf-8")))
        except (OSError, UnicodeDecodeError, ValueError):
            value = None
    _page_cache["key"], _page_cache["value"] = key, value
    return value


# The counts that the achievement watcher reads through Steamworks while a
# game runs. The watcher sees an unlock within a second, and the page above
# does not. It writes the counts into this file for the panel service. Both
# are user services of the same user, so both find the same runtime
# directory.
#
# The file names its game, so the counts of a different game are not used.
# The watcher removes the file at its start and at its end. With no file,
# the page above is the answer, for example on a machine with no LED module.
LIVE_NAME = "steamos-utility-center-achievements.json"

# The file holds three numbers. A file far past that is not one of these.
LIVE_LIMIT = 4096


def live_path():
    """The file of the live counts, in the runtime directory of the user."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return os.path.join(runtime, LIVE_NAME)


def publish_live(appid, achieved, total, path=None):
    """Writes the live counts of that game for the panel service.

    The data goes into a second file that then replaces the first. A read
    thus never gets half a file.
    """
    path = live_path() if path is None else path
    temporary = path + ".new"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"appid": int(appid), "achieved": int(achieved),
                   "total": int(total)}, handle)
    os.replace(temporary, path)


def clear_live(path=None):
    """Removes the live counts. No file is not a fault."""
    path = live_path() if path is None else path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def live_achievements(appid, path=None):
    """(achieved, total) that the watcher wrote for that game, or None."""
    if appid is None:
        return None
    path = live_path() if path is None else path
    try:
        with open(path, "rb") as handle:
            raw = handle.read(LIVE_LIMIT + 1)
        if len(raw) > LIVE_LIMIT:
            return None
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    # Not a bool and not a float, which Python also takes as equal.
    if type(data.get("appid")) is not int or data["appid"] != int(appid):
        return None
    return _numbers(data.get("achieved"), data.get("total"))


def now_playing_achievements(root=PROC, home=None, live=None):
    """The achievements of the game that runs, as a dict, or None.

    The live counts of the watcher come first, because they follow each
    unlock. The page of the game is the answer where no watcher runs.
    """
    appid = running_appid(root)
    counts = live_achievements(appid, path=live)
    if counts is None:
        counts = achievements(appid, home=home)
    if counts is None:
        return None
    return {"achieved": counts[0], "total": counts[1]}
