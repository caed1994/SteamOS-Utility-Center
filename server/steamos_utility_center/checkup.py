# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""What this machine carries, against what this project expects of it.

Every fault of the last months had one shape: the machine drifted from what
the repository believes about it, and nothing said so. A unit stayed enabled
after it stopped working. A SteamOS update took a file and the feature was
simply gone. A link in a .wants directory named a unit that was no longer
there. Each of them was found because a person noticed a symptom days later.

This is the half that a program can do: read the machine and name every
difference. It writes nothing and it runs nothing. Re-running the installer
is the repair, and that stays a decision of a person.

Three states, because two are not enough:

    True   the file is where this project puts it
    False  it belongs on this machine and it is gone
    None   this cannot be looked at, or it belongs to a module that is not
           installed here

The middle state is the whole point, and the third is what keeps it honest.
A machine without the Pegboard module has none of its units, and a red line
about it is a red line for ever. See modules.py.

Enabled is not asked of systemd here. A unit is enabled when a link to it is
in a .wants directory, and the keep-list names every one of those links. So
reading the links reads the enabled state, with no program to run.
"""

from __future__ import annotations

import os

from . import cec
from . import modules
from . import mounts

# Where the programs that need root are installed. Spelled here rather than
# imported from ctl, which imports modules, which this file imports.
INSTALL_DIR = "/var/lib/steamos-utility-center"

# The file that lets the control command apply a change with no password.
SUDO_RULE = "/etc/sudoers.d/zz-steamos-utility-center"

# The copy of the toolbox, which the menu entry points into.
#
# The clone is something a person can throw away, so everything the panel
# reaches for at run time lives here: the panel, the installer it re-runs for
# a repair, the appliers and the firmware project. A machine that lost this
# has an installation that runs and a panel that does not open.
SOURCE_COPY = os.path.join(INSTALL_DIR, "source")

# The python modules this project carries and did not write, and where the
# installer puts them.
#
# One directory for the machine, with no version of Python in its name. The
# user site directory is .local/lib/python3.14/site-packages, and a SteamOS
# update that raises Python leaves a copy there behind. Three services of the
# CEC toolkit then die at their first import, for ever, with every switch on
# the page still saying "on". See dbus-next/ORIGIN.
PYTHON_DIR = cec.PYTHON_DIR
PYTHON_VERSIONS = os.path.join(PYTHON_DIR, "versions")

# Each carried module: the name it is imported by, and the directory of the
# toolbox that holds it with its VERSION.
CARRIED = {"dbus_next": "dbus-next"}

# What has to be in that copy for the window to open and its buttons to work.
TOOLBOX = ("gui/steamos-utility-center-panel",
           "gui/ledpanel.py",
           "install.sh",
           "scripts/update.sh",
           "server/steamos_utility_center/__init__.py")

# A name that belongs on every machine, whatever modules it carries.
CORE = ""

# Which module each file of the keep-list belongs to.
#
# The longest name that a file begins with wins, so the Nanoleaf units do not
# read as the LED strip's. OwnerTest holds that every file of the keep-list
# is claimed here: a unit that nobody claims is a unit this cannot judge, and
# a guess about it is a red line on a machine that is in order.
OWNERS = {
    "steamos-utility-center-pegboard": modules.PEGBOARD,
    "steamos-utility-center-power": modules.POWER,
    "steamos-utility-center-mounts": modules.SYSTEM,
    "steamos-utility-center-wake": modules.SYSTEM,
    # The devices on the network are part of the core. An effect on one of
    # them is an HTTP call to an address on the LAN, and pairing one needs no
    # rights at all. See nanoleaf.py.
    "steamos-utility-center-nanoleaf": CORE,
    # What writes the rest of this list back at a boot. Core, because every
    # installation has files that a SteamOS update takes.
    "steamos-utility-center-repair": CORE,
    "steamos-utility-center-sleep": modules.LED,
    "steamos-utility-center-resume": modules.LED,
    "steamos-utility-center.service": modules.LED,
    "steamos-utility-center.conf": modules.LED,
    "99-steamos-utility-center": modules.LED,
    "zz-steamos-utility-center": CORE,
}

# The programs of an installation, and the module that brings each one.
#
# The entry points are the core. An applier belongs to its module, and
# modules.MARK names the same file for three of them: the marker of a module
# is one of its own programs.
PROGRAMS = {
    "steamos-utility-center": CORE,
    "steamos-utility-centerctl": CORE,
    "steamos-utility-center-nanoleaf": CORE,
    "steamos-utility-center-nanoleaf-watch": CORE,
    "steamos-utility-center-repair": CORE,
    "steamos-utility-center-config-apply": modules.LED,
    "steamos-utility-center-sleep": modules.LED,
    "steamos-utility-center-power": modules.POWER,
    "steamos-utility-center-power-apply": modules.POWER,
    "steamos-utility-center-pegboard": modules.PEGBOARD,
    "steamos-utility-center-pegboard-apply": modules.PEGBOARD,
    "steamos-utility-center-pegboard-sleep": modules.PEGBOARD,
    "steamos-utility-center-mounts-apply": modules.SYSTEM,
    "steamos-utility-center-wake-apply": modules.SYSTEM,
}

# The names a person can type, which are links on the read-only filesystem.
#
# A SteamOS update removes each of them, and that is not a fault worth a red
# light: the full path under INSTALL_DIR works either way, and the installer
# says so when it cannot write them. See install.sh.
COMMANDS = ("/usr/local/bin/steamos-utility-center",
            "/usr/local/bin/steamos-utility-centerctl",
            "/usr/local/bin/steamos-utility-center-power")


def owner(path):
    """Which module a file of the keep-list belongs to, or CORE.

    Returns None for a name that nobody claims, which OwnerTest refuses.
    """
    name = os.path.basename(path)
    best = None
    for start, who in OWNERS.items():
        if name.startswith(start):
            if best is None or len(start) > len(best):
                best = start
    return OWNERS[best] if best is not None else None


def wanted(here):
    """The files of the keep-list that this machine is meant to carry.

    A file that the table above does not claim is kept rather than dropped.
    OwnerTest catches such a file at the moment somebody writes it, and on
    a machine
    it is better checked against the wrong module than checked by nobody: a
    file nobody looks at is the fault this whole file exists for.
    """
    return [path for path in mounts.PROJECT_FILES
            if owner(path) in (CORE, None) or owner(path) in here]


def _missing(paths, root=""):
    """The paths of this list that are not on the machine.

    os.path.lexists and not exists: a link in a .wants directory that names a
    unit which is gone is itself still there. That link is the fault this
    looks for, so the two cases are told apart below rather than here.
    """
    return [path for path in paths if not os.path.lexists(root + path)]


def _dangling(paths, root=""):
    """The links of this list that name a file which is not there.

    systemd reports such a link at every boot and nobody reads that. The
    feature is off and the machine looks complete.
    """
    out = []
    for path in paths:
        whole = root + path
        if os.path.islink(whole) and not os.path.exists(whole):
            out.append(path)
    return out


def _say(names, limit=3):
    """A few names for a sentence, and a count for the rest."""
    names = sorted(os.path.basename(one) for one in names)
    if len(names) <= limit:
        return ", ".join(names)
    return "%s and %d more" % (", ".join(names[:limit]), len(names) - limit)


def _finding(name, ok, detail="", repairable=True):
    return {"name": name, "ok": ok, "detail": detail, "repairable": repairable}


def units(here, root=""):
    """The unit files, and the links that make systemd start them."""
    named = [path for path in wanted(here)
             if path.startswith(mounts.UNIT_DIR + "/")]
    files = [path for path in named if ".wants/" not in path]
    links = [path for path in named if ".wants/" in path]

    gone = _missing(files, root)
    out = [_finding(
        "The units of this installation",
        not gone,
        "%d of %d are gone: %s" % (len(gone), len(files), _say(gone))
        if gone else "All %d are here." % len(files))]

    lost = _missing(links, root)
    loose = _dangling(links, root)
    if lost or loose:
        trouble = []
        if lost:
            trouble.append("%d never start: %s" % (len(lost), _say(lost)))
        if loose:
            trouble.append("%d name a unit that is gone: %s"
                           % (len(loose), _say(loose)))
        out.append(_finding("What starts them", False, "; ".join(trouble)))
    else:
        out.append(_finding("What starts them", True,
                            "All %d links are here." % len(links)))
    return out


def keep_list(here, root=""):
    """The file that asks SteamOS to carry this project into the next image.

    Without it an update takes the installation and nothing reports it. The
    file itself is the one thing on the list that the list cannot protect.
    """
    whole = root + mounts.KEEP_LIST
    if not os.path.exists(whole):
        return [_finding(
            "The keep-list for a SteamOS update", False,
            "%s is gone, so the next update takes this installation."
            % mounts.KEEP_LIST)]
    try:
        with open(whole, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        return [_finding("The keep-list for a SteamOS update", None,
                         "%s cannot be read: %s" % (mounts.KEEP_LIST, exc),
                         repairable=False)]
    absent = [path for path in wanted(here) if path not in text]
    return [_finding(
        "The keep-list for a SteamOS update",
        not absent,
        "%d files are not named in it: %s" % (len(absent), _say(absent))
        if absent else "It names all %d files." % len(wanted(here)))]


def programs(here, root=""):
    """The entry points and the appliers, under INSTALL_DIR.

    /var is its own partition, so a SteamOS update keeps these. One that is
    gone means an installer that did not finish, or a person who removed it.
    """
    named = [name for name, who in PROGRAMS.items()
             if who == CORE or who in here]
    gone = []
    dull = []
    for name in named:
        whole = os.path.join(root + INSTALL_DIR, name)
        if not os.path.exists(whole):
            gone.append(name)
        elif not os.access(whole, os.X_OK):
            dull.append(name)
    if gone or dull:
        trouble = []
        if gone:
            trouble.append("%d are gone: %s" % (len(gone), _say(gone)))
        if dull:
            trouble.append("%d cannot run: %s" % (len(dull), _say(dull)))
        return [_finding("The programs of this installation", False,
                         "; ".join(trouble))]
    return [_finding("The programs of this installation", True,
                     "All %d are here." % len(named))]


def settings(here, root=""):
    """The configuration files, which hold what a person chose.

    These are read and never written back by a repair. A default over the top
    of them is the LED count, the serial port and the effect of a person,
    gone without a word.
    """
    named = [path for path in wanted(here) if path.endswith(".conf")
             and not path.startswith(mounts.UNIT_DIR)]
    gone = _missing(named, root)
    return [_finding(
        "The settings files", not gone,
        "%d are gone, and a repair writes defaults over nothing: %s"
        % (len(gone), _say(gone)) if gone
        else "All %d are here." % len(named),
        repairable=False)]


def commands(root=""):
    """The names a person can type, which live on the read-only filesystem."""
    gone = _missing(COMMANDS, root)
    return [_finding(
        "The short command names", None if gone else True,
        "%s is gone. A SteamOS update takes these, and the full path under "
        "%s works either way." % (_say(gone), INSTALL_DIR) if gone
        else "All %d are here." % len(COMMANDS),
        repairable=False)]


def password_rule(root=""):
    """The sudoers rule, which only root can read.

    The directory is closed to everybody else, so "not there" and "not mine
    to look at" are the same answer from here. They are not the same thing,
    and a red light on the second one is a red light on every machine where
    the panel runs as a person.
    """
    whole = root + SUDO_RULE
    try:
        there = os.path.exists(whole)
        os.listdir(os.path.dirname(whole))
    except OSError:
        return [_finding("The rule for a change with no password", None,
                         "Only root can look at %s."
                         % os.path.dirname(SUDO_RULE), repairable=False)]
    return [_finding(
        "The rule for a change with no password", there,
        "%s is gone, so a change from Game Mode asks for a password that "
        "Game Mode cannot ask for." % SUDO_RULE if not there
        else "It is here.")]


def toolbox(root=""):
    """The copy of this project that the menu entry points into.

    Without it the machine keeps every service and loses the window: the
    entry names a program that is not there, and a press does nothing at all.
    """
    where = root + SOURCE_COPY
    if not os.path.isdir(where):
        return [_finding(
            "The toolbox the menu entry opens", False,
            "%s is gone, so the panel does not open. The services keep "
            "running." % SOURCE_COPY)]
    gone = [name for name in TOOLBOX
            if not os.path.exists(os.path.join(where, name))]
    panel = os.path.join(where, TOOLBOX[0])
    if not gone and not os.access(panel, os.X_OK):
        return [_finding("The toolbox the menu entry opens", False,
                         "%s cannot run." % TOOLBOX[0])]
    return [_finding(
        "The toolbox the menu entry opens",
        not gone,
        "%d parts are gone: %s" % (len(gone), _say(gone)) if gone
        else "It is here, and the panel can run.")]


def _number(said):
    """A version as a tuple of numbers, for a comparison that 0.10 survives.

    "0.10.0" is newer than "0.2.3" and reads as older to a comparison of two
    strings. A value this cannot read comes back as an empty tuple, and the
    caller then compares the text and says "different" rather than "older".
    """
    parts = said.strip().lstrip("v").split(".")
    try:
        return tuple(int(one) for one in parts)
    except ValueError:
        return ()


def installed_versions(root=""):
    """What the installer recorded about the carried modules.

    The file is "<name> <version>", one module to a line. An empty answer
    means no record, which is an installation from before this existed as
    much as it is a directory that is gone.
    """
    out = {}
    try:
        with open(root + PYTHON_VERSIONS, encoding="utf-8") as handle:
            for line in handle:
                words = line.split()
                if len(words) == 2:
                    out[words[0]] = words[1]
    except OSError:
        return {}
    return out


def toolbox_versions(root=""):
    """What the copy of the toolbox carries, from each module's VERSION."""
    out = {}
    for name, where in CARRIED.items():
        try:
            with open(os.path.join(root + SOURCE_COPY, where, "VERSION"),
                      encoding="utf-8") as handle:
                out[name] = handle.read().strip()
        except OSError:
            continue
    return out


def carried(root=""):
    """The python modules this project carries, against what is installed.

    Three services of the CEC toolkit import dbus_next at their first line.
    A copy that is gone kills all three at once, and each of their units
    carries Restart=on-failure, so they stay in "activating" and never reach
    "failed". Nothing on the machine says a word. See cec.NEEDS_DBUS.
    """
    gone = [name for name in CARRIED
            if not os.path.isdir(os.path.join(root + PYTHON_DIR, name))]
    if gone:
        return [_finding(
            "The python modules this project carries", False,
            "%s is not in %s. Reinstalling puts it back."
            % (_say(gone), PYTHON_DIR))]

    have, want = installed_versions(root), toolbox_versions(root)
    if not want:
        return [_finding("The python modules this project carries", None,
                         "All %d are here. This copy of the toolbox does not "
                         "say which version it carries." % len(CARRIED),
                         repairable=False)]
    # A copy that is newer than the toolbox is not a fault of this card. It
    # says the toolbox is old, and the update page is where that is reported.
    old = []
    for name, wanted in want.items():
        mine = have.get(name, "")
        said = "%s %s is installed, and the toolbox carries %s" % (
            name, mine, wanted)
        if mine == wanted:
            continue
        if not mine:
            old.append("%s is installed with no version recorded" % name)
        elif _number(mine) and _number(wanted):
            if _number(mine) < _number(wanted):
                old.append(said)
        else:
            old.append(said)
    return [_finding(
        "The python modules this project carries", not old,
        "; ".join(old) + ". Reinstalling writes the newer one." if old
        else "All %d are here: %s." % (
            len(want), ", ".join("%s %s" % pair
                                 for pair in sorted(want.items()))))]


def look(root="", here=None, home=None, present=None):
    """Every difference between this machine and what this project expects.

    `here` is the list of installed modules. It is a parameter so that a test
    can describe a machine it did not build, and so that a caller which has
    the list already does not read the disk twice.
    """
    if here is None:
        here = modules.here(home=home, present=present)
    found = []
    found.extend(units(here, root))
    found.extend(keep_list(here, root))
    found.extend(programs(here, root))
    found.extend(toolbox(root))
    found.extend(carried(root))
    found.extend(settings(here, root))
    found.extend(commands(root))
    found.extend(password_rule(root))
    return found


def trouble(found):
    """The findings that name a fault. A None is not one."""
    return [one for one in found if one["ok"] is False]
