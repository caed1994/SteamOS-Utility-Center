# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The writing back of what a SteamOS update takes away.

checkup.py reads a machine and names the differences. This is the half that
writes them, so the tests here are about the two ways such a program does
damage:

- it writes a file that holds the answers of a person, and those answers are
  gone with no message. The settings files are that file.
- it writes half of a pair and reports success. A link in a .wants directory
  with no unit behind it is that half, and systemd reports it at every boot
  to nobody.

The rest is the placeholders. A template carries @INSTALL_DIR@ and
@WATCHER_USER@, and two programs answer them: write_unit in
scripts/user-unit.sh for an install, and repair.fill for a repair. A mark
that one of the two answers and the other does not leaves its own text in a
unit file, and systemd reads that as a path.
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import checkup, modules, mounts  # noqa: E402
from steamos_utility_center import power, repair, service, wake  # noqa: E402

ALL = list(modules.ORDER)

# The templates of the repository, which the installer copies into /var.
TEMPLATES = os.path.join(REPO, "server")

SCRIPT = os.path.join(REPO, "scripts", "repair.sh")


class Room(unittest.TestCase):
    """A machine in a temporary directory, built to order."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def templates(self):
        """The unit templates, as install.sh copies them into /var."""
        where = self.root + repair.TEMPLATE_DIR
        os.makedirs(where, exist_ok=True)
        for name in os.listdir(TEMPLATES):
            if name.endswith(".service"):
                shutil.copyfile(os.path.join(TEMPLATES, name),
                                os.path.join(where, name))

    def user(self, name="deck"):
        """The record of the desktop user that install.sh writes."""
        whole = self.root + repair.WATCHER_PATH
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        with open(whole, "w") as handle:
            handle.write(name + "\n")

    def carried(self):
        """The python modules the installer keeps, and the record of them.

        Not something a repair writes: they are in /var, which an update does
        not touch, and the installer is the answer to a copy that is gone.
        The machine a test builds needs them so that checkup reads it as one
        that is in order. See checkup.carried.
        """
        for name, where in checkup.CARRIED.items():
            os.makedirs(os.path.join(self.root + checkup.PYTHON_DIR, name),
                        exist_ok=True)
            said = os.path.join(self.root + checkup.SOURCE_COPY, where)
            os.makedirs(said, exist_ok=True)
            with open(os.path.join(said, "VERSION"), "w") as handle:
                handle.write("1.2.3\n")
        whole = self.root + checkup.PYTHON_VERSIONS
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        with open(whole, "w") as handle:
            for name in checkup.CARRIED:
                handle.write("%s 1.2.3\n" % name)

    def toolbox(self):
        """The copy of this project, and the udev rule beside the templates.

        The rule is not in the copy. A repair installs it into /etc as root
        at a boot, and the copy belongs to the desktop user.
        """
        for name in checkup.TOOLBOX:
            whole = os.path.join(self.root + checkup.SOURCE_COPY, name)
            os.makedirs(os.path.dirname(whole), exist_ok=True)
            with open(whole, "w") as handle:
                handle.write("# built for a test\n")
            os.chmod(whole, 0o755)
        whole = self.root + repair.UDEV_TEMPLATE
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        with open(whole, "w") as handle:
            handle.write('ACTION=="add", SUBSYSTEM=="tty"\n')

    def build(self, here=ALL, skip=()):
        """A machine with everything on it, less the names of `skip`."""
        self.templates()
        self.user()
        self.toolbox()
        self.carried()
        for path in checkup.wanted(here):
            if os.path.basename(path) in skip:
                continue
            self.write(path)
        for name in checkup.PROGRAMS:
            whole = os.path.join(self.root + repair.INSTALL_DIR, name)
            os.makedirs(os.path.dirname(whole), exist_ok=True)
            with open(whole, "w") as handle:
                handle.write("#!/bin/sh\n")
            os.chmod(whole, 0o755)
        for path in checkup.COMMANDS:
            self.write(path)
        self.write(mounts.KEEP_LIST)

    def write(self, path, text="# built for a test\n"):
        whole = self.root + path
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        with open(whole, "w") as handle:
            handle.write(text)
        return whole

    def take(self, path):
        """Remove one file, as an update does."""
        os.unlink(self.root + path)

    def plan(self, here=ALL):
        return repair.plan(here=here, root=self.root)

    def run_it(self, here=ALL, runner=None):
        return repair.run(root=self.root, here=here, runner=runner)

    def runner(self, command):
        """visudo and install, against the machine this test built.

        ctl.permit runs those two as root and writes /etc/sudoers.d. Without
        this the rule is the one part of a repair that no test runs, and it
        is the part that takes sudo away from a machine when it is wrong.
        """
        verb = command[0]
        if verb == "visudo":
            return 0, ""
        if verb == "rm":
            for path in command[2:]:
                if os.path.lexists(self.root + path):
                    os.unlink(self.root + path)
            return 0, ""
        if verb == "install" and "-d" in command:
            os.makedirs(self.root + command[-1], exist_ok=True)
            return 0, ""
        if verb == "install":
            whole = self.root + command[-1]
            os.makedirs(os.path.dirname(whole), exist_ok=True)
            shutil.copyfile(command[-2], whole)
            return 0, ""
        raise AssertionError("the rule ran %r" % (command,))


class PlanTest(Room):
    """What the repair says is gone."""

    def test_a_machine_in_order_asks_for_nothing(self):
        self.build()
        found = self.plan()
        self.assertFalse(repair.needed(found))
        self.assertEqual(repair.lines(found), [])

    def test_it_names_a_unit_that_is_gone(self):
        self.build(skip=("steamos-utility-center.service",))
        found = self.plan()
        self.assertIn("/etc/systemd/system/steamos-utility-center.service",
                      found["units"])
        self.assertTrue(repair.needed(found))

    def test_it_asks_for_nothing_of_a_module_that_is_not_here(self):
        """The Pegboard units belong to a machine that has that module.

        A repair that writes them everywhere gives each machine a service
        for a board that is not connected.
        """
        self.build(here=[])
        for name in self.plan(here=[])["units"]:
            self.assertNotIn("pegboard", name)

    def test_it_leaves_a_command_name_alone_with_no_program_behind_it(self):
        """/usr/local/bin/…-power belongs to a machine with that module.

        The link is written for a program that is there. A link to a program
        that is not there is the dangling link this whole file is against.
        """
        self.build()
        os.unlink(os.path.join(self.root + repair.INSTALL_DIR,
                               "steamos-utility-center-power"))
        self.take("/usr/local/bin/steamos-utility-center-power")
        self.take("/usr/local/bin/steamos-utility-centerctl")
        found = self.plan()
        self.assertEqual(found["commands"],
                         ["/usr/local/bin/steamos-utility-centerctl"])


class WriteTest(Room):
    """What the repair writes, and what it leaves alone."""

    def test_it_writes_a_unit_back_with_the_paths_answered(self):
        self.build(skip=("steamos-utility-center-repair.service",))
        self.run_it()
        whole = (self.root
                 + "/etc/systemd/system/steamos-utility-center-repair.service")
        with open(whole) as handle:
            text = handle.read()
        self.assertIn("ExecStart=%s/steamos-utility-center-repair"
                      % repair.INSTALL_DIR, text)
        self.assertNotIn("@", text.split("[Service]")[1])

    def test_it_writes_the_name_of_the_desktop_user_into_the_unit(self):
        self.build(skip=("steamos-utility-center-nanoleaf.service",))
        self.run_it()
        with open(self.root + "/etc/systemd/system/"
                  "steamos-utility-center-nanoleaf.service") as handle:
            self.assertIn("User=deck", handle.read())

    def test_the_link_it_makes_reaches_the_unit(self):
        link = ("/etc/systemd/system/multi-user.target.wants/"
                "steamos-utility-center.service")
        self.build()
        self.take(link)
        self.run_it()
        whole = self.root + link
        self.assertTrue(os.path.islink(whole))
        self.assertTrue(os.path.exists(whole),
                        "the link names a unit that is not there")

    def test_it_never_writes_a_settings_file(self):
        """The answers of a person. A default over them is a silent loss.

        checkup reports the file as gone and marks it as nothing to repair,
        and this is the other end of that promise.
        """
        self.build()
        for path in mounts.PROJECT_FILES:
            if path.endswith(".conf") and "/systemd/" not in path:
                self.take(path)
        done = self.run_it()
        for path in mounts.PROJECT_FILES:
            if path.endswith(".conf") and "/systemd/" not in path:
                self.assertFalse(os.path.exists(self.root + path),
                                 "%s was written over" % path)
                self.assertNotIn(path, done["units"] + done["links"])

    def test_a_template_for_a_settings_file_is_still_not_written(self):
        """Two guards, and this one is the first of them.

        A plan looks at the unit directory and at nothing else.
        server/steamos-utility-center.conf sits beside the templates in the
        repository, so a copy that took every file rather than every
        .service would put it within reach.
        """
        self.build()
        for name in ("steamos-utility-center.conf",
                     "steamos-utility-center-power.conf"):
            with open(os.path.join(self.root + repair.TEMPLATE_DIR,
                                   name), "w") as handle:
                handle.write("# a template that must not be used\n")
            self.take("/etc/" + name)
        done = self.run_it()
        for name in ("steamos-utility-center.conf",
                     "steamos-utility-center-power.conf"):
            self.assertFalse(os.path.exists(self.root + "/etc/" + name))
            self.assertNotIn("/etc/" + name, done["units"])

    def test_it_writes_the_keep_list_with_every_file_in_it(self):
        self.build()
        self.take(mounts.KEEP_LIST)
        self.run_it()
        with open(self.root + mounts.KEEP_LIST) as handle:
            text = handle.read()
        for path in mounts.PROJECT_FILES:
            self.assertIn(path, text)

    def test_it_writes_the_udev_rule_from_the_copy_beside_the_templates(self):
        rule = repair.UDEV_RULE
        self.build()
        self.take(rule)
        self.run_it()
        with open(self.root + rule) as handle:
            self.assertIn("SUBSYSTEM", handle.read())

    def test_it_reads_nothing_from_the_toolbox_copy(self):
        """The copy belongs to the desktop user, and this runs as root.

        A repair installs a udev rule into /etc with nobody to read it first,
        and a udev rule names a program that udev runs as root. A file from a
        directory that the desktop session can write is thus a way to become
        root at the next boot with no password. So the whole copy is taken
        away here and a repair still writes everything.
        """
        self.build()
        shutil.rmtree(self.root + checkup.SOURCE_COPY)
        for path in checkup.wanted(ALL) + [mounts.KEEP_LIST]:
            if os.path.lexists(self.root + path) \
                    and not (path.endswith(".conf")
                             and "/systemd/" not in path):
                self.take(path)
        self.run_it(runner=self.runner)
        left = repair.plan(here=ALL, root=self.root)
        self.assertFalse(repair.needed(left))
        with open(self.root + repair.UDEV_RULE) as handle:
            self.assertIn("SUBSYSTEM", handle.read())

    def test_it_links_the_short_command_names_again(self):
        self.build()
        for path in checkup.COMMANDS:
            self.take(path)
        self.run_it()
        for path in checkup.COMMANDS:
            self.assertEqual(
                os.readlink(self.root + path),
                os.path.join(self.root + repair.INSTALL_DIR,
                             os.path.basename(path)))

    def test_a_repaired_machine_reports_no_fault(self):
        """The whole of it, against the program that reads a machine.

        Every file of the keep-list is taken away and written back, and then
        checkup says what is left. The settings files are the exception and
        they are named here, because a repair that wrote them is the fault
        above.
        """
        self.build()
        for path in checkup.wanted(ALL):
            if path.endswith(".conf") and "/systemd/" not in path:
                continue
            if path == checkup.SUDO_RULE:
                continue
            self.take(path)
        self.take(mounts.KEEP_LIST)
        self.run_it()
        trouble = checkup.trouble(checkup.look(root=self.root, here=ALL))
        self.assertEqual([one["name"] for one in trouble], [])


class MissingUserTest(Room):
    """A machine with no record of the account the units run as."""

    def setUp(self):
        super().setUp()
        self.build(skip=("steamos-utility-center-nanoleaf.service",))
        os.unlink(self.root + repair.WATCHER_PATH)

    def test_it_leaves_a_unit_of_that_user_alone(self):
        """`User=root` reads the pairing record of root, which is empty.

        The devices then stop following the machine and nothing says why.
        The installer says the same on a machine with no desktop user.
        """
        found = self.plan()
        self.assertIn(
            "/etc/systemd/system/steamos-utility-center-nanoleaf.service",
            found["skipped"])
        self.assertEqual(found["units"], [])

    def test_it_says_which_one_it_left(self):
        said = " ".join(repair.lines(self.plan()))
        self.assertIn("nanoleaf", said)
        self.assertIn(repair.WATCHER_PATH, said)

    def test_it_makes_no_link_for_a_unit_it_did_not_write(self):
        link = ("/etc/systemd/system/multi-user.target.wants/"
                "steamos-utility-center-nanoleaf.service")
        self.assertFalse(os.path.lexists(self.root + link))
        self.run_it()
        self.assertFalse(os.path.lexists(self.root + link),
                         "a link with no unit behind it")

    def test_a_record_that_is_not_a_name_is_no_record(self):
        for bad in ("", "  ", "deck root", "../root", "Deck\nroot", "-deck"):
            with open(self.root + repair.WATCHER_PATH, "w") as handle:
                handle.write(bad)
            self.assertEqual(repair.watcher(self.root), "",
                             "%r was read as an account" % bad)

    def test_a_name_is_a_record(self):
        for good in ("deck", "_x", "gamer-1", "steam$"):
            with open(self.root + repair.WATCHER_PATH, "w") as handle:
                handle.write(good + "\n")
            self.assertEqual(repair.watcher(self.root), good)


class OrphanTest(Room):
    """A unit of the keep-list with no template to write it from."""

    def setUp(self):
        super().setUp()
        self.build(skip=("steamos-utility-center-power.service",))
        os.unlink(os.path.join(self.root + repair.TEMPLATE_DIR,
                               "steamos-utility-center-power.service"))

    def test_it_names_the_unit_it_cannot_write(self):
        found = self.plan()
        self.assertIn("/etc/systemd/system/steamos-utility-center-power"
                      ".service", found["orphans"])
        self.assertEqual(found["units"], [])

    def test_it_makes_no_link_for_it(self):
        link = ("/etc/systemd/system/multi-user.target.wants/"
                "steamos-utility-center-power.service")
        self.assertFalse(os.path.lexists(self.root + link))
        self.run_it()
        self.assertFalse(os.path.lexists(self.root + link))

    def test_such_a_machine_asks_for_no_unlock(self):
        """`needed` leaves out what nothing can write.

        Without that, a machine with one orphan unlocks its filesystem at
        every boot and writes nothing at all.
        """
        found = self.plan()
        self.assertTrue(found["orphans"])
        self.assertFalse(repair.needed(found))


class NeedTest(Room):
    """The one rule that holds this module together.

    scripts/repair.sh unlocks the read-only filesystem when `needed` reads
    True. So after a repair it has to read False, whatever was wrong with the
    machine. A plan that asks for something nothing can write is a machine
    that unlocks its filesystem at every boot and writes nothing at all.

    Three faults of exactly that shape were in the first version: the udev
    rule with no copy of the toolbox to take it from, the sudoers rule with
    no account recorded, and the keep-list on a record of the drives that the
    rules refuse. Each one was found by running a repair twice, which is what
    this does for every machine below.
    """

    def broken(self):
        """One damaged machine for each name, built fresh each time."""
        def gone(*paths):
            def make():
                self.build()
                for path in paths:
                    if os.path.lexists(self.root + path):
                        self.take(path)
            return make

        def no_user():
            self.build()
            os.unlink(self.root + repair.WATCHER_PATH)
            self.take(checkup.SUDO_RULE)

        def no_udev_source():
            self.build()
            os.unlink(self.root + repair.UDEV_TEMPLATE)
            self.take(repair.UDEV_RULE)

        def bad_record():
            self.build()
            self.take(mounts.KEEP_LIST)
            # A mount point this project refuses, as a hand edit leaves it.
            self.write(mounts.STATE_PATH,
                       json.dumps([{"uuid": "1234-ABCD", "where": "/etc",
                                    "type": "ext4", "options": "defaults"}]))

        def no_templates():
            self.build()
            shutil.rmtree(self.root + repair.TEMPLATE_DIR)
            for path in checkup.wanted(ALL):
                if path.endswith(".service"):
                    self.take(path)

        def no_switch_on():
            self.build()
            for path in checkup.SWITCHED:
                self.take(path)

        def everything():
            self.build()
            for path in checkup.wanted(ALL) + [mounts.KEEP_LIST]:
                if os.path.lexists(self.root + path):
                    self.take(path)

        return {"an untouched machine": self.build,
                "no record of the user": no_user,
                "no udev rule in the toolbox": no_udev_source,
                "a record of the drives that is refused": bad_record,
                "no unit templates at all": no_templates,
                "every file of /etc gone": everything,
                "the units gone": gone(
                    "/etc/systemd/system/steamos-utility-center.service",
                    "/etc/systemd/system/steamos-utility-center-power.service"),
                "the links gone": gone(
                    "/etc/systemd/system/multi-user.target.wants/"
                    "steamos-utility-center.service"),
                "the command names gone": gone(*checkup.COMMANDS),
                "the keep-list gone": gone(mounts.KEEP_LIST),
                # Not damage at all: the machine a fresh installation
                # leaves behind, with no drive added and controller wake off.
                # It is here for the second test of this class, which runs a
                # repair on every machine and lets nothing raise.
                #
                # It holds no rule of its own. A repair that wrote the two
                # links wrote them once and then asked for nothing, so this
                # test passed both before the fix and after it. SwitchTest is
                # where that fault is held.
                "a fresh installation with no switch on": no_switch_on}

    def test_one_repair_is_enough_on_every_machine(self):
        left = []
        for name, build in self.broken().items():
            with self.subTest(name):
                self.setUp()        # a fresh directory for each machine
                build()
                self.run_it(runner=self.runner)
                if repair.needed(repair.plan(here=ALL, root=self.root)):
                    left.append(name)
        self.assertEqual(left, [], "these unlock the filesystem for ever")

    def test_a_repair_raises_nothing_on_any_of_them(self):
        """The unit runs at a boot and nobody reads a stack trace there."""
        for name, build in self.broken().items():
            with self.subTest(name):
                self.setUp()
                build()
                self.run_it(runner=self.runner)

    def test_the_rule_it_writes_names_the_account_and_no_wildcard(self):
        """The one file a repair builds rather than copies.

        A rule with a `*` in it permits every argument of the programs it
        names, which is every file on the machine.
        """
        self.setUp()
        self.build()
        self.take(checkup.SUDO_RULE)
        self.run_it(runner=self.runner)
        with open(self.root + checkup.SUDO_RULE) as handle:
            rules = [line for line in handle.read().splitlines()
                     if line and not line.startswith("#")]
        self.assertTrue(rules, "the rule is empty")
        for line in rules:
            self.assertTrue(line.startswith("deck ALL=(root) NOPASSWD: "), line)
            # The comment above the rules says the word, so only the rules
            # themselves are read here.
            self.assertNotIn("*", line)
            self.assertIn(repair.INSTALL_DIR, line)

    def test_what_it_cannot_write_is_named_with_a_reason(self):
        """A line that says a file is missing and not why is a line that
        sends a person to read the source of this."""
        self.setUp()
        self.build()
        os.unlink(self.root + repair.UDEV_TEMPLATE)
        self.take(repair.UDEV_RULE)
        said = " ".join(repair.lines(self.plan()))
        self.assertIn(repair.UDEV_RULE, said)
        self.assertIn(repair.UDEV_TEMPLATE, said)


class SwitchTest(Room):
    """The two links that a switch writes, and no installation.

    A repair reads a file that is gone and writes it back. That is right for
    every file of an installation and wrong for these two: absent is what
    "the switch is off" looks like on the disk.

    Measured on a machine that a repair ran on three times: the first boot
    wrote both links and switched both features on. The person then switched
    controller wake off, and the next boot wrote the link again and switched
    it back on.

    The switch is read from /var, which is its own partition and which an
    update keeps. See checkup.switched_on.
    """

    def switch_on(self, path):
        """Put that switch on, the way the machine records it. One record for
        each of the three, because each switch is a different feature."""
        if "mounts" in path:
            self.write(mounts.STATE_PATH, "")
        elif "wake" in path:
            self.write(wake.STATE_PATH, "")
        else:
            self.write(power.CONFIG_PATH, "CPU_GOVERNOR=performance\n")

    def test_it_writes_neither_where_the_switch_is_off(self):
        self.build()
        for path in checkup.SWITCHED:
            self.take(path)
        self.assertEqual(self.plan()["links"], [])

    def test_it_writes_one_where_that_switch_is_on(self):
        for path in checkup.SWITCHED:
            with self.subTest(path=path):
                self.setUp()
                self.build()
                for one in checkup.SWITCHED:
                    self.take(one)
                self.switch_on(path)
                self.assertEqual(self.plan()["links"], [path])

    def test_a_link_that_no_switch_writes_is_written_back(self):
        """The behaviour this change had to leave alone."""
        self.build()
        other = ("/etc/systemd/system/multi-user.target.wants/"
                 "steamos-utility-center-nanoleaf.service")
        self.assertNotIn(other, checkup.SWITCHED)
        self.take(other)
        self.assertIn(other, self.plan()["links"])

    def test_a_repair_leaves_a_switch_that_is_off_off(self):
        """The whole point, read from the machine after a run."""
        self.build()
        for path in checkup.SWITCHED:
            self.take(path)
        self.run_it(runner=self.runner)
        for path in checkup.SWITCHED:
            self.assertFalse(os.path.lexists(self.root + path),
                             "%s was switched on by a repair" % path)

    def test_a_repair_puts_back_a_switch_that_is_on(self):
        """An update that ignores the keep-list takes the link away.

        The record in /var says the person wants the feature, so this is the
        case a repair is for.
        """
        self.build()
        for path in checkup.SWITCHED:
            self.take(path)
            self.switch_on(path)
        self.run_it(runner=self.runner)
        for path in checkup.SWITCHED:
            self.assertTrue(os.path.lexists(self.root + path), path)


class TemplateTest(unittest.TestCase):
    """The marks of a template, and the two programs that answer them."""

    def marks(self, text):
        return set(re.findall(r"@[A-Z_]+@", text))

    def test_every_unit_of_this_project_has_a_template(self):
        """A unit of the keep-list with no file behind it cannot be written.

        The plan reports such a unit rather than writing nothing, and this
        test is what keeps that list empty in the repository.
        """
        names = set(name for name in os.listdir(TEMPLATES)
                    if name.endswith(".service"))
        for path in mounts.PROJECT_FILES:
            if not path.endswith(".service") or ".wants/" in path:
                continue
            self.assertIn(os.path.basename(path), names)

    def test_the_marks_of_every_template_are_answered(self):
        found = set()
        for name in os.listdir(TEMPLATES):
            if name.endswith(".service"):
                with open(os.path.join(TEMPLATES, name)) as handle:
                    found |= self.marks(handle.read())
        self.assertEqual(found - set(repair.MARKS), set(),
                         "a mark that repair.fill leaves in the unit")

    def test_the_installer_answers_the_same_marks(self):
        """write_unit in scripts/user-unit.sh does this for an install.

        Two programs write the same file from the same template. A mark that
        one of them answers and the other does not is a path in a unit that
        systemd reads as the text @INSTALL_DIR@.
        """
        with open(os.path.join(REPO, "scripts", "user-unit.sh")) as handle:
            text = handle.read()
        body = text.split("write_unit() {")[1].split("\n}")[0]
        self.assertEqual(self.marks(body), set(repair.MARKS))

    def test_fill_answers_both(self):
        text = "%s and %s" % (repair.INSTALL_MARK, repair.WATCHER_MARK)
        self.assertEqual(repair.fill(text, "deck"),
                         "%s and deck" % repair.INSTALL_DIR)

    def test_no_user_reads_as_root(self):
        """The same default as write_unit, which uses ${WATCHER_USER:-root}.

        Nothing reaches this on a machine: a template that asks for the user
        is skipped where there is no record. It is here so the two programs
        answer alike whatever calls them.
        """
        self.assertEqual(repair.fill(repair.WATCHER_MARK, ""), "root")


class OwnerTest(unittest.TestCase):
    """The repair unit itself, against the lists that carry it."""

    def test_the_keep_list_carries_it(self):
        self.assertIn(
            "/etc/systemd/system/steamos-utility-center-repair.service",
            mounts.PROJECT_FILES)

    def test_the_link_that_starts_it_is_carried_too(self):
        self.assertIn("/etc/systemd/system/multi-user.target.wants/"
                      "steamos-utility-center-repair.service",
                      mounts.PROJECT_FILES)

    def test_it_belongs_to_every_machine(self):
        self.assertEqual(
            checkup.owner("steamos-utility-center-repair.service"),
            checkup.CORE)


class EntryPointTest(unittest.TestCase):
    """--repair-check and --repair, which are what the script calls.

    Six lines of glue, and the shell reads their output to decide whether to
    unlock the read-only filesystem. So what they print and what they return
    is the contract between the two halves.
    """

    def setUp(self):
        self.asked = []
        self.found = {"units": [], "links": [], "commands": [], "udev": [],
                      "keep": [], "rule": [], "orphans": [], "skipped": [],
                      "why": {}, "user": "deck"}
        self.addCleanup(setattr, repair, "plan", repair.plan)
        self.addCleanup(setattr, repair, "run", repair.run)
        repair.plan = lambda *a, **k: self.found
        repair.run = lambda found, *a, **k: self.asked.append(found) or found

    def go(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = service.main(list(argv))
        return code, out.getvalue()

    def test_a_machine_in_order_prints_nothing_at_all(self):
        """The shell reads empty output as "leave the filesystem alone"."""
        code, said = self.go("--repair-check")
        self.assertEqual((code, said), (0, ""))

    def test_the_check_writes_nothing(self):
        self.found["units"] = ["/etc/systemd/system/x.service"]
        code, said = self.go("--repair-check")
        self.assertEqual(self.asked, [])
        self.assertIn("missing /etc/systemd/system/x.service", said)

    def test_the_repair_writes_and_says_so(self):
        self.found["units"] = ["/etc/systemd/system/x.service"]
        code, said = self.go("--repair")
        self.assertEqual(len(self.asked), 1)
        self.assertIn("wrote /etc/systemd/system/x.service", said)
        self.assertEqual(code, 0)

    def test_it_writes_nothing_when_nothing_is_gone(self):
        code, said = self.go("--repair")
        self.assertEqual(self.asked, [])
        self.assertIn("nothing to write back", said)

    def test_what_it_cannot_write_is_an_exit_of_one(self):
        """A person who runs this by hand is told the machine needs them.

        The unit does not fail on it: scripts/repair.sh ends with exit 0, or
        a machine with no desktop user would be degraded at every boot.
        """
        self.found["orphans"] = ["/etc/systemd/system/x.service"]
        self.found["why"] = {"/etc/systemd/system/x.service": "no template"}
        code, said = self.go("--repair-check")
        self.assertEqual(code, 1)
        self.assertIn("cannot write /etc/systemd/system/x.service: "
                      "no template", said)

    def test_a_refusal_is_a_sentence_and_not_a_stack_trace(self):
        def refuse(*a, **k):
            raise mounts.MountError("/etc belongs to SteamOS")
        repair.run = refuse
        self.found["units"] = ["/etc/systemd/system/x.service"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = service.main(["--repair"])
        self.assertEqual(code, 1)
        self.assertIn("/etc belongs to SteamOS", err.getvalue())


class ScriptTest(unittest.TestCase):
    """The part a test cannot reach any other way: the branches of the shell.

    The script unlocks a read-only filesystem and starts services. So it is
    run here against a directory this test builds, with a program that prints
    what the test wants and writes nothing, and with systemctl and the rest
    on a PATH of stubs. What is checked is which of them ran.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.log = os.path.join(self.root, "log")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        for name in ("systemctl", "udevadm", "steamos-readonly"):
            self.stub(name)

    def stub(self, name, says=""):
        whole = os.path.join(self.bin, name)
        with open(whole, "w") as handle:
            handle.write('#!/bin/sh\necho "%s $*" >> "%s"\n%s\n'
                         % (name, self.log, says))
        os.chmod(whole, 0o755)

    def wanted(self, name):
        """A link in multi-user.target.wants, which is what starts a unit."""
        whole = self.root + ("/etc/systemd/system/multi-user.target.wants/"
                             + name)
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        open(whole, "w").close()

    def program(self, check="", said=""):
        """The entry point, which prints what this test wants."""
        whole = os.path.join(self.root + repair.INSTALL_DIR,
                             "steamos-utility-center")
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        with open(whole, "w") as handle:
            handle.write("#!/bin/sh\n"
                         'case "$1" in\n'
                         '--repair-check) printf "%s" "$CHECK" ;;\n'
                         '--repair) printf "%s" "$SAID" ;;\n'
                         "esac\n")
        os.chmod(whole, 0o755)
        self.check, self.said = check, said

    def go(self):
        answer = subprocess.run(
            ["bash", SCRIPT], capture_output=True, text=True,
            env={"PATH": self.bin + ":" + os.environ["PATH"],
                 "ROOT": self.root, "CHECK": self.check, "SAID": self.said})
        try:
            with open(self.log) as handle:
                ran = handle.read()
        except OSError:
            ran = ""
        return answer, ran

    def test_a_machine_in_order_keeps_its_filesystem_read_only(self):
        self.program(check="")
        answer, ran = self.go()
        self.assertEqual(answer.returncode, 0)
        self.assertNotIn("steamos-readonly", ran)
        self.assertNotIn("systemctl", ran)
        self.assertIn("Nothing to write back", answer.stdout)

    def test_it_unlocks_and_locks_again_when_something_is_gone(self):
        self.stub("steamos-readonly", says="echo enabled")
        self.program(check="missing /etc/systemd/system/x.service",
                     said="wrote /etc/systemd/system/x.service")
        answer, ran = self.go()
        self.assertEqual(answer.returncode, 0)
        self.assertIn("steamos-readonly disable", ran)
        self.assertIn("steamos-readonly enable", ran)

    def test_it_reloads_systemd_and_starts_what_came_back(self):
        # Rooted paths, because a program that writes under a root prints
        # what it wrote. On a machine the root is empty and these read as
        # the absolute paths of that machine.
        unit = self.root + ("/etc/systemd/system/multi-user.target.wants/"
                            "steamos-utility-center.service")
        os.makedirs(os.path.dirname(unit))
        open(unit, "w").close()
        self.program(
            check="missing x",
            said=("wrote " + self.root
                  + "/etc/systemd/system/steamos-utility-center.service"))
        answer, ran = self.go()
        self.assertIn("systemctl daemon-reload", ran)
        self.assertIn("systemctl start --no-block "
                      "steamos-utility-center.service", ran)

    def test_it_does_not_wait_for_what_it_starts(self):
        """Three of these units carry `After=multi-user.target`.

        This one runs before that target. A start that waited for such a job
        would wait for the target, and the target waits for this unit. The
        boot then stops until systemd gives up on the job.
        """
        after = [name for name in os.listdir(TEMPLATES)
                 if name.endswith(".service")
                 and "After=multi-user.target" in
                 open(os.path.join(TEMPLATES, name)).read()]
        self.assertTrue(after, "no unit is ordered after that target")
        with open(SCRIPT) as handle:
            self.assertIn("systemctl start --no-block", handle.read())

    def test_it_starts_no_unit_that_nothing_wants(self):
        """A sleep unit is a moment and not a service.

        To start one at a boot is that moment happening for no reason: the
        strip goes dark, or the devices on the network go off.
        """
        self.wanted("steamos-utility-center.service")
        self.program(
            check="missing x",
            said="wrote " + self.root + "/etc/systemd/system/"
                 "steamos-utility-center-sleep.service")
        answer, ran = self.go()
        self.assertNotIn("systemctl start", ran)

    def test_it_starts_no_link(self):
        """The .wants entries come through the same test as the units.

        A * matches a / in a bash pattern, so the path of a link reads as a
        unit file without the second test.
        """
        self.wanted("steamos-utility-center.service")
        self.program(
            check="missing x",
            said="wrote " + self.root + "/etc/systemd/system/"
                 "multi-user.target.wants/steamos-utility-center.service")
        answer, ran = self.go()
        self.assertNotIn("systemctl start", ran)

    def test_it_reloads_udev_only_for_the_udev_rule(self):
        self.program(check="missing x",
                     said="wrote /etc/systemd/system/x.service")
        answer, ran = self.go()
        self.assertNotIn("udevadm", ran)
        self.program(check="missing x",
                     said="wrote /etc/udev/rules.d/99-x.rules")
        answer, ran = self.go()
        self.assertIn("udevadm control", ran)

    def test_it_reports_a_line_of_several_words_whole(self):
        """The check prints sentences as well as paths.

        An unquoted expansion splits "no template for /etc/…" into four
        lines, and the journal then reads as four faults.
        """
        self.program(check="no template for /etc/systemd/system/x.service",
                     said="")
        answer, ran = self.go()
        self.assertIn("  no template for /etc/systemd/system/x.service",
                      answer.stdout)

    def test_a_stack_trace_does_not_unlock_the_filesystem(self):
        """The check reports missing files on its own output.

        A program that stops with a trace writes that trace to the error
        stream. Read as a list of missing files it unlocks the read-only
        filesystem for work that nothing can do, at every boot.
        """
        whole = os.path.join(self.root + repair.INSTALL_DIR,
                             "steamos-utility-center")
        os.makedirs(os.path.dirname(whole), exist_ok=True)
        with open(whole, "w") as handle:
            handle.write('#!/bin/sh\necho "Traceback (most recent call last)"'
                         ' >&2\nexit 1\n')
        os.chmod(whole, 0o755)
        self.check, self.said = "", ""
        answer, ran = self.go()
        self.assertEqual(answer.returncode, 0)
        self.assertNotIn("steamos-readonly", ran)
        self.assertIn("Nothing to write back", answer.stdout)

    def test_it_does_nothing_without_the_program(self):
        self.check, self.said = "", ""
        answer, ran = self.go()
        self.assertEqual(answer.returncode, 0)
        self.assertEqual(ran, "")


if __name__ == "__main__":
    unittest.main()
