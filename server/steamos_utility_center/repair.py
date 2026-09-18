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

Everything it reads belongs to root. The toolbox copy in
/var/lib/steamos-utility-center/source belongs to the desktop user, because
git refuses a clone that somebody else owns and the update page has to fetch
into it. So nothing here reads that directory: this runs as root at a boot,
with nobody to look at the file first, and a udev rule names a program that
udev then runs as root.

What it writes back:

- the unit files, from the templates in /var/lib/steamos-utility-center/units
- the links in the .wants directories, which are what starts them
- the udev rule, from the copy in /var/lib/steamos-utility-center/udev
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

# The account the Nanoleaf units run as, written down at install time.
#
# A unit reads the record of the paired devices from the home directory of
# that account. At a boot there is nobody to ask, so the installer writes the
# answer here. See install.sh.
WATCHER_PATH = os.path.join(INSTALL_DIR, "watcher-user")

# The udev rule, and the copy of it that the installer keeps.
#
# It is beside the unit templates and not in the toolbox copy. The copy
# belongs to the desktop user, because git refuses a clone that somebody else
# owns and the update page has to fetch. This file is installed into /etc by
# root, at a boot, with nobody to read it first, and a udev rule names a
# program that udev then runs as root. So it comes from a directory that
# belongs to root.
UDEV_RULE = "/etc/udev/rules.d/99-steamos-utility-center.rules"
UDEV_TEMPLATE_DIR = os.path.join(INSTALL_DIR, "udev")
UDEV_TEMPLATE = os.path.join(UDEV_TEMPLATE_DIR,
                             os.path.basename(UDEV_RULE))

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


def _drive_trouble(root=""):
    """Why the record of the drives cannot be written, or "".

    The keep-list is written from that record, by the same call that
    scripts/apply-mounts.sh makes. A record that the rules refuse raises, and
    a plan that asked for the keep-list anyway would ask for it again at the
    next boot. See `needed`.

    The two checks are the ones mounts.write_units makes before it writes
    anything. A record it refuses leaves every file as it was.
    """
    entries = mounts.read(root + mounts.STATE_PATH)
    try:
        for entry in entries:
            mounts.validate(entry)
    except mounts.MountError as exc:
        return str(exc)
    twice = mounts.duplicates(entries)
    if twice:
        return "two drives ask for %s" % ", ".join(twice)
    return ""


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
    why = {}
    user = watcher(root)
    for path in [one for one in named if ".wants/" not in one]:
        if not _needs(path, root):
            continue
        source = template(path, root)
        if not source:
            orphans.append(path)
            why[path] = "no template in %s" % TEMPLATE_DIR
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
    #
    # And only where the switch behind it is on. Two of these links are
    # written by a switch and not by an installation.
    #
    # Measured on a machine that a repair ran on three times, with the links
    # taken away as a fresh installation leaves them: the first boot wrote
    # both and switched both features on. The person then switched controller
    # wake off, and the next boot wrote the link again and switched it back
    # on. The unit of that switch says the same in its own words: "a unit
    # that enables itself at each boot is a unit that fights the switch which
    # turned it off".
    #
    # See checkup.switched_on, which the check on the page asks as well.
    lost = set(os.path.basename(one) for one in orphans + skipped)
    links = [path for path in named
             if ".wants/" in path and _needs(path, root)
             and os.path.basename(path) not in lost
             and checkup.switched_on(path, root)]

    # A command name is linked where the program behind it is there. The
    # Power module brings one of the three, and a link to a program that is
    # not installed is the dangling link this file is against.
    commands = [path for path in checkup.COMMANDS
                if _needs(path, root)
                and os.path.exists(os.path.join(root + INSTALL_DIR,
                                                os.path.basename(path)))]

    # Each of the three below goes into the plan only where this can write
    # it. Every one of them broke that rule once, and each break was the same
    # machine: it unlocked its filesystem at every boot and wrote nothing.
    udev = []
    if UDEV_RULE in want and _needs(UDEV_RULE, root):
        if os.path.isfile(root + UDEV_TEMPLATE):
            udev.append(UDEV_RULE)
        else:
            orphans.append(UDEV_RULE)
            why[UDEV_RULE] = "there is no %s" % UDEV_TEMPLATE

    keep = []
    if _needs(mounts.KEEP_LIST, root):
        trouble = _drive_trouble(root)
        if trouble:
            orphans.append(mounts.KEEP_LIST)
            why[mounts.KEEP_LIST] = "the record of the drives is refused: %s" \
                % trouble
        else:
            keep.append(mounts.KEEP_LIST)

    rule = []
    if checkup.SUDO_RULE in want and _needs(checkup.SUDO_RULE, root):
        (rule if user else skipped).append(checkup.SUDO_RULE)

    return {"units": units, "links": links, "commands": commands,
            "udev": udev, "keep": keep, "rule": rule,
            "orphans": orphans, "skipped": skipped, "why": why, "user": user}


def _wants_user(source):
    """Whether one template asks for the name of the desktop user."""
    try:
        with open(source, encoding="utf-8") as handle:
            return WATCHER_MARK in handle.read()
    except OSError:
        return False


def needed(found):
    """Whether a plan asks for any work at all.

    One rule holds this whole file together: after a repair, this reads
    False. scripts/repair.sh unlocks the read-only filesystem when it reads
    True, so a plan that asks for something it cannot write is a machine that
    unlocks its filesystem at every boot and writes nothing.

    So the names that nothing can write are in `orphans` and in `skipped`,
    and neither is counted here. Three of them were counted here once: the
    udev rule with no copy of the toolbox to take it from, the sudoers rule
    with no account recorded, and the keep-list on a record of the drives
    that the rules refuse. NeedTest holds the rule for every one of them.
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
    """Copies the udev rule back, from the copy the installer keeps."""
    done = []
    for path in found["udev"]:
        source = root + UDEV_TEMPLATE
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

    `run` is how ctl runs visudo and install. It is a parameter because
    neither of those takes a root that a test builds: a caller that gives one
    answers for the root itself, and a root with no runner gets no rule. That
    seam is what lets NeedTest run this part rather than step over it.

    ctl is imported here and not at the top of the file. ctl reaches every
    area of the project, and the check at a boot must not pay for that on a
    machine where nothing is gone.
    """
    if not found["rule"] or not found["user"]:
        return []
    if root and run is None:
        return []
    from . import ctl
    # The rule names one program for each installed module, and ctl reads the
    # machine for that list. With a root it has to read the machine the test
    # built, or it writes the rule of a machine with no module at all, which
    # is no rule. On a machine the root is empty and this is what ctl does by
    # itself.
    ctl.permit(found["user"], run=run,
               present=lambda path: os.path.exists(root + path))
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
    why = found.get("why", {})
    out.extend("cannot write %s: %s" % (path, why.get(path, "no source"))
               for path in found["orphans"])
    out.extend("%s needs a desktop user, and none is recorded in %s"
               % (path, WATCHER_PATH) for path in found["skipped"])
    return out
