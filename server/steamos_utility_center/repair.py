# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes back what a SteamOS update takes away, at the next boot.

checkup.py names every difference between this machine and what this project
expects. This is the other half: it writes the differences it knows how to
write, with no person in front of the screen.

A SteamOS update builds the new image in the other partition slot. /usr comes
from that image every time, so the three short command names in
/usr/local/bin are gone after every update. /etc comes from the image as well,
and /etc/atomic-update.conf.d/steamos-utility-center.conf asks SteamOS to
carry this project across. That file is the official way and it works, and it
is a request to another program. This module is what answers for the update
that does not honour it.

What it writes back:

- the unit files, from the templates in /var/lib/steamos-utility-center/units
- the links in the .wants directories, which are what starts them
- the udev rule, from the copy of the toolbox in /var
- the keep-list itself, and the sudoers rule (ctl and mounts write those two)
- the short command names in /usr/local/bin

What it never writes:

- the settings files. /etc/steamos-utility-center.conf holds the LED count,
  the serial port and the effect of a person. A default over the top of those
  is a loss with no message, and a repair that loses answers is worse than a
  repair that reports a gap. checkup.py marks them accordingly.
- the programs under /var/lib/steamos-utility-center. /var is its own
  partition and no update touches it. One that is gone means an installer
  that stopped, and the installer is the answer to that.
- the kernel module, the firmware of the board and the CEC toolkit.

One hole stays, and it is written here rather than hidden. The unit that runs
this is itself in /etc. An image that ignores the keep-list takes that unit
too, and then nothing runs at the next boot. The panel is the answer in that
case: the toolbox is in /var, so the window still opens, the diagnosis button
still reads the machine, and the repair button re-runs the installer.

The placeholders below have a second reader: write_unit in
scripts/user-unit.sh does the same substitution for the installer. A
placeholder that one of the two answers and the other does not leaves the
text of it in a unit file. tests/test_repair.py holds them equal.
"""

from __future__ import annotations

import os
import re
import shutil

from . import checkup
from . import modules
from . import mounts

# Where the programs and the copy of the toolbox are. /var is its own
# partition, so everything a repair reads is on it.
INSTALL_DIR = checkup.INSTALL_DIR

# The unit files as the installer copied them, before any substitution.
TEMPLATE_DIR = os.path.join(INSTALL_DIR, "units")

# The copy of this project, which carries the udev rule.
SOURCE_COPY = checkup.SOURCE_COPY

# The account the Nanoleaf units run as, written down at install time.
#
# A unit reads the record of the paired devices from the home directory of
# that account. At a boot there is nobody to ask, so the installer writes the
# answer here. See install.sh.
WATCHER_PATH = os.path.join(INSTALL_DIR, "watcher-user")

# The udev rule, and where the copy of the toolbox carries it.
UDEV_RULE = "/etc/udev/rules.d/99-steamos-utility-center.rules"
UDEV_SOURCE = "udev/99-steamos-utility-center.rules"

# The mark in a template, and what answers it.
#
# INSTALL_DIR is a choice of the installer, and a test gives it a directory of
# its own. WATCHER_USER is the account above.
INSTALL_MARK = "@INSTALL_DIR@"
WATCHER_MARK = "@WATCHER_USER@"
MARKS = (INSTALL_MARK, WATCHER_MARK)

# A name that a unit file and a sudoers rule can carry.
#
# The value goes into `User=` and into the rule that permits a change with no
# password. A record with a space in it writes a rule for two names, so
# anything but this is read as no answer at all.
USER_NAME = re.compile(r"^[a-z_][a-z0-9_-]{0,30}\$?$")


def watcher(root=""):
    """The account the units run as, or "" when there is no usable record."""
    try:
        with open(root + WATCHER_PATH, encoding="utf-8") as handle:
            name = handle.read().strip()
    except OSError:
        return ""
    return name if USER_NAME.match(name) else ""


def template(path, root=""):
    """The template of one unit of /etc, or "" when there is none.

    A unit with no template is one this cannot write. It is named in the plan
    so that the journal says which, rather than reporting a repair that left
    the machine as it was.
    """
    whole = os.path.join(root + TEMPLATE_DIR, os.path.basename(path))
    return whole if os.path.isfile(whole) else ""


def _needs(path, root=""):
    """Whether one path of the project is gone from this machine."""
    return not os.path.lexists(root + path)


def plan(here=None, root="", home=None, present=None):
    """What is gone from this machine, in the order a repair writes it.

    Every list holds paths as they read on a machine, with no root in front
    of them. The caller puts the root back on. `here` is the list of
    installed modules, so a machine without the Pegboard module asks for none
    of its units.
    """
    if here is None:
        here = modules.here(home=home, present=present)
    want = checkup.wanted(here)
    named = [path for path in want if path.startswith(mounts.UNIT_DIR + "/")]

    units, orphans, skipped = [], [], []
    user = watcher(root)
    for path in [one for one in named if ".wants/" not in one]:
        if not _needs(path, root):
            continue
        source = template(path, root)
        if not source:
            orphans.append(path)
        elif not user and _wants_user(source):
            # A unit that runs as the desktop user, on a machine that has no
            # record of one. `User=root` there reads the pairing record of
            # root, which is empty, and the devices stop following with no
            # message. The installer says the same on a machine with no
            # desktop user.
            skipped.append(path)
        else:
            units.append(path)

    # A link is worth making only where the unit behind it is there, or where
    # this run writes it. systemd reports a link with no unit at every boot,
    # and a repair that leaves one behind reports a fault it made itself.
    lost = set(os.path.basename(one) for one in orphans + skipped)
    links = [path for path in named
             if ".wants/" in path and _needs(path, root)
             and os.path.basename(path) not in lost]

    commands = [path for path in checkup.COMMANDS
                if _needs(path, root)
                and os.path.exists(os.path.join(root + INSTALL_DIR,
                                                os.path.basename(path)))]
    udev = [UDEV_RULE] if (UDEV_RULE in want and _needs(UDEV_RULE, root)) else []
    keep = [mounts.KEEP_LIST] if _needs(mounts.KEEP_LIST, root) else []
    rule = [checkup.SUDO_RULE] if (checkup.SUDO_RULE in want
                                   and _needs(checkup.SUDO_RULE, root)) else []
    return {"units": units, "links": links, "commands": commands,
            "udev": udev, "keep": keep, "rule": rule,
            "orphans": orphans, "skipped": skipped, "user": user}


def _wants_user(source):
    """Whether one template asks for the name of the desktop user."""
    try:
        with open(source, encoding="utf-8") as handle:
            return WATCHER_MARK in handle.read()
    except OSError:
        return False


def needed(found):
    """Whether a plan asks for any work at all.

    The names that nothing can write are left out. A machine that reports one
    of those at every boot repairs nothing and unlocks the filesystem for it.
    """
    return any(found[key] for key in ("units", "links", "commands",
                                      "udev", "keep", "rule"))


def fill(text, user, install_dir=INSTALL_DIR):
    """One template with its marks answered."""
    return (text.replace(INSTALL_MARK, install_dir)
                .replace(WATCHER_MARK, user or "root"))


def write_units(found, root=""):
    """Writes the unit files of the plan, from their templates."""
    done = []
    directory = root + mounts.UNIT_DIR
    os.makedirs(directory, exist_ok=True)
    for path in found["units"]:
        with open(template(path, root), encoding="utf-8") as handle:
            text = handle.read()
        whole = root + path
        with open(whole, "w", encoding="utf-8") as handle:
            handle.write(fill(text, found["user"]))
        os.chmod(whole, 0o644)
        done.append(path)
    return done


def write_links(found, root=""):
    """Makes the links in the .wants directories, which start the units.

    The link holds the path it resolves to, which is the absolute path on a
    machine and a path inside the root that a test builds. `systemctl enable`
    writes the same text, so a repaired machine reads as a fresh install.
    """
    done = []
    for path in found["links"]:
        whole = root + path
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        target = os.path.join(root + mounts.UNIT_DIR, os.path.basename(path))
        if os.path.lexists(whole):
            os.unlink(whole)
        os.symlink(target, whole)
        done.append(path)
    return done


def write_commands(found, root=""):
    """Links the short command names, which every update takes away."""
    done = []
    for path in found["commands"]:
        whole = root + path
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        target = os.path.join(root + INSTALL_DIR, os.path.basename(path))
        if os.path.lexists(whole):
            os.unlink(whole)
        os.symlink(target, whole)
        done.append(path)
    return done


def write_udev(found, root=""):
    """Copies the udev rule back, from the copy of the toolbox in /var."""
    done = []
    for path in found["udev"]:
        source = os.path.join(root + SOURCE_COPY, UDEV_SOURCE)
        if not os.path.isfile(source):
            continue
        whole = root + path
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        shutil.copyfile(source, whole)
        os.chmod(whole, 0o644)
        done.append(path)
    return done


def write_keep_list(found, root=""):
    """Writes the keep-list again, from the record of the drives.

    The same call as scripts/apply-mounts.sh, so both write one text. A
    machine with no drive reads an empty record and gets a list of the
    project's own files. See mounts.write_units.
    """
    if not found["keep"]:
        return []
    mounts.write_units(mounts.read(root + mounts.STATE_PATH), root=root)
    return list(found["keep"])


def write_rule(found, root="", run=None):
    """Writes the sudoers rule again, for the account that was permitted.

    ctl builds that rule rather than copying a file: it names one program for
    each installed module, and there is no wildcard in it. So the rule is the
    one file here that a repair has to build.

    ctl is imported here and not at the top of the file. ctl reaches every
    area of the project, and the check at a boot must not pay for that on a
    machine where nothing is gone.
    """
    if not found["rule"] or not found["user"]:
        return []
    from . import ctl
    if root:
        # ctl writes /etc/sudoers.d and runs visudo. Neither takes a root
        # that a test builds, so a test root gets no rule.
        return []
    ctl.permit(found["user"], run=run)
    return list(found["rule"])


def run(found=None, root="", here=None, home=None, present=None, runner=None):
    """Writes back everything of one plan, and reports what it wrote.

    The order is the order of the dependencies: a unit before the link that
    starts it, and both before the keep-list that carries them.
    """
    if found is None:
        found = plan(here=here, root=root, home=home, present=present)
    done = dict(found)
    done["units"] = write_units(found, root)
    done["links"] = write_links(found, root)
    done["commands"] = write_commands(found, root)
    done["udev"] = write_udev(found, root)
    done["keep"] = write_keep_list(found, root)
    done["rule"] = write_rule(found, root, run=runner)
    return done


def lines(found, did=False):
    """The plan as one line for each path, for the journal.

    A boot writes this and nobody reads it until something is wrong. So each
    line names the file and what happened to it, and no line is a count.
    """
    verb = "wrote" if did else "missing"
    out = []
    for key in ("units", "links", "commands", "udev", "keep", "rule"):
        out.extend("%s %s" % (verb, path) for path in found[key])
    out.extend("no template for %s" % path for path in found["orphans"])
    out.extend("%s needs a desktop user, and none is recorded in %s"
               % (path, WATCHER_PATH) for path in found["skipped"])
    return out
