# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The reading of a machine against what this project expects of it.

Every fault this file is for was silent. A unit stayed enabled after it
stopped working. An update took a file and the feature was gone. A link named
a unit that was no longer there, and systemd said so at a boot that nobody
reads.

So the tests here are mostly about the ways a check itself goes quiet: a file
nobody claims and therefore nobody looks at, a module that is not installed
and is reported as broken anyway, and a directory that only root can read
being called empty.
"""

import ast
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))

from steamos_utility_center import (checkup, ctl, modules, mounts,  # noqa: E402
                                    power, wake)

ALL = list(modules.ORDER)


class Room(unittest.TestCase):
    """A machine in a temporary directory, built to order."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def build(self, without=(), skip=()):
        """Write a machine: every file of the keep-list and every program.

        `without` leaves out every name that holds one of these words, which
        is how a machine with a module missing is described. `skip` leaves
        out one file by its own name.

        It does not ask checkup which files belong here. The first version
        did, and that made four tests below say nothing: a fault in wanted()
        built itself the machine that matches it. A fixture that shares a
        function with the thing it tests agrees with it whatever it says.
        """
        def leave(path):
            return (any(word in path for word in without)
                    or os.path.basename(path) in skip)

        written = []
        for path in mounts.PROJECT_FILES:
            if leave(path):
                continue
            written.append(path)
            whole = self.root + path
            os.makedirs(os.path.dirname(whole), exist_ok=True)
            with open(whole, "w") as handle:
                handle.write("# built for a test\n")
        for name in checkup.PROGRAMS:
            if leave(name):
                continue
            whole = os.path.join(self.root + checkup.INSTALL_DIR, name)
            os.makedirs(os.path.dirname(whole), exist_ok=True)
            with open(whole, "w") as handle:
                handle.write("#!/bin/sh\n")
            os.chmod(whole, 0o755)
        keep = self.root + mounts.KEEP_LIST
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        with open(keep, "w") as handle:
            handle.write("\n".join(written) + "\n")
        for path in checkup.COMMANDS:
            whole = self.root + path
            os.makedirs(os.path.dirname(whole), exist_ok=True)
            with open(whole, "w") as handle:
                handle.write("")
        # The python modules this project carries, and the record of what is
        # installed. Both are part of an installation that is in order.
        for name, where in checkup.CARRIED.items():
            if leave(name):
                continue
            os.makedirs(os.path.join(self.root + checkup.PYTHON_DIR, name),
                        exist_ok=True)
            said = os.path.join(self.root + checkup.SOURCE_COPY, where)
            os.makedirs(said, exist_ok=True)
            with open(os.path.join(said, "VERSION"), "w") as handle:
                handle.write("1.2.3\n")
        versions = self.root + checkup.PYTHON_VERSIONS
        os.makedirs(os.path.dirname(versions), exist_ok=True)
        with open(versions, "w") as handle:
            for name in checkup.CARRIED:
                if not leave(name):
                    handle.write("%s 1.2.3\n" % name)
        for name in checkup.TOOLBOX:
            if leave(name):
                continue
            whole = os.path.join(self.root + checkup.SOURCE_COPY, name)
            os.makedirs(os.path.dirname(whole), exist_ok=True)
            with open(whole, "w") as handle:
                handle.write("# built for a test\n")
            os.chmod(whole, 0o755)

    def named(self, found, start):
        """The one finding whose name begins with this."""
        for one in found:
            if one["name"].startswith(start):
                return one
        raise AssertionError("no finding named %r in %r"
                             % (start, [one["name"] for one in found]))


class OwnerTest(unittest.TestCase):
    """Every file of the keep-list is claimed by the table.

    A file that nobody claims is a file that this cannot judge. It is still
    looked at, because wanted() keeps an unclaimed name rather than dropping
    it, but the module it belongs to is a guess. This test is the place that
    catches it at the moment somebody adds the file, and not a year later.
    """

    def test_every_file_of_the_keep_list_has_an_owner(self):
        orphans = sorted(set(os.path.basename(path)
                             for path in mounts.PROJECT_FILES
                             if checkup.owner(path) is None))
        self.assertEqual(orphans, [])

    def test_the_longest_name_wins(self):
        """Against a table of its own, because the real one has no pair that
        overlaps today.

        The first version of this test asked the real table and passed with
        the rule removed. The rule is here for the unit that somebody adds
        next: a name like "...-nanoleaf-sleep" begins with "...-nanoleaf",
        and with a shorter match winning it lands on the wrong module. A
        machine without that module then stops looking at it.
        """
        kept = checkup.OWNERS
        checkup.OWNERS = {"a-thing": modules.LED,
                          "a-thing-of-its-own": modules.PEGBOARD}
        try:
            self.assertEqual(checkup.owner("/etc/a-thing.service"),
                             modules.LED)
            self.assertEqual(checkup.owner("/etc/a-thing-of-its-own.service"),
                             modules.PEGBOARD)
        finally:
            checkup.OWNERS = kept

    def test_the_units_of_this_project_land_where_they_belong(self):
        """And the real table, read the ordinary way."""
        for name, who in (
                ("steamos-utility-center-nanoleaf.service", checkup.CORE),
                ("steamos-utility-center-nanoleaf-watch.service",
                 checkup.CORE),
                ("steamos-utility-center.service", modules.LED),
                ("steamos-utility-center-sleep.service", modules.LED),
                ("steamos-utility-center-pegboard.service",
                 modules.PEGBOARD),
                ("steamos-utility-center-power.service", modules.POWER),
                ("steamos-utility-center-mounts.service", modules.SYSTEM),
                ("steamos-utility-center-wake.service", modules.SYSTEM)):
            self.assertEqual(checkup.owner("/etc/systemd/system/" + name),
                             who, name)

    def test_every_owner_is_a_module_of_this_project_or_the_core(self):
        for start, who in checkup.OWNERS.items():
            self.assertTrue(who == checkup.CORE or who in modules.ORDER,
                            "%s is owned by %r" % (start, who))
        for name, who in checkup.PROGRAMS.items():
            self.assertTrue(who == checkup.CORE or who in modules.ORDER,
                            "%s is owned by %r" % (name, who))

    def test_the_marker_of_each_module_is_a_program_it_owns(self):
        """modules.installed reads a marker file, and that marker is one of
        the module's own programs. Two lists of one fact drift apart."""
        for name, where in modules.MARK.items():
            said = checkup.PROGRAMS.get(os.path.basename(where))
            self.assertEqual(said, name, os.path.basename(where))


class CarriedTest(Room):
    """The python modules this project carries, against what is installed.

    Three services of the CEC toolkit import dbus_next at their first line.
    A copy that is gone kills all three at once, and each unit carries
    Restart=on-failure, so they sit in "activating" and never reach "failed".
    Nothing on the machine said a word about it, which is why this card has
    to.

    SteamOS ships no pip, so the copy a person installs by hand lands under
    .local/lib/python3.14/site-packages. The name of that directory holds the
    version of Python, so an update that raises Python takes it away. That is
    what happened on a machine, and it is why the installer keeps its own
    copy at a path with no version in it.
    """

    def version(self, installed=None, toolbox=None):
        """Rewrite the two records for one module."""
        if installed is not None:
            with open(self.root + checkup.PYTHON_VERSIONS, "w") as handle:
                handle.write("dbus_next %s\n" % installed)
        if toolbox is not None:
            where = os.path.join(self.root + checkup.SOURCE_COPY, "dbus-next")
            os.makedirs(where, exist_ok=True)
            with open(os.path.join(where, "VERSION"), "w") as handle:
                handle.write("%s\n" % toolbox)

    def said(self):
        return checkup.carried(self.root)[0]

    def test_a_machine_with_it_is_in_order(self):
        self.build()
        self.assertIs(self.said()["ok"], True)

    def test_a_copy_that_is_gone_is_a_fault_a_repair_mends(self):
        self.build()
        shutil.rmtree(os.path.join(self.root + checkup.PYTHON_DIR,
                                   "dbus_next"))
        found = self.said()
        self.assertIs(found["ok"], False)
        self.assertIn("dbus_next", found["detail"])
        self.assertTrue(found["repairable"])

    def test_an_older_copy_is_reported_with_both_versions(self):
        self.build()
        self.version(installed="0.2.3", toolbox="0.3.0")
        found = self.said()
        self.assertIs(found["ok"], False)
        self.assertIn("0.2.3", found["detail"])
        self.assertIn("0.3.0", found["detail"])

    def test_ten_is_newer_than_two(self):
        """A comparison of two strings reads 0.10.0 as older than 0.2.3."""
        self.build()
        self.version(installed="0.2.3", toolbox="0.10.0")
        self.assertIs(self.said()["ok"], False)
        self.version(installed="0.10.0", toolbox="0.2.3")
        self.assertIs(self.said()["ok"], True)

    def test_a_newer_copy_is_not_a_fault_of_this_card(self):
        """It says the toolbox is old, and the update page reports that."""
        self.build()
        self.version(installed="0.9.0", toolbox="0.2.3")
        self.assertIs(self.said()["ok"], True)

    def test_a_copy_with_no_record_is_reported(self):
        """An installation from before the record existed."""
        self.build()
        os.unlink(self.root + checkup.PYTHON_VERSIONS)
        found = self.said()
        self.assertIs(found["ok"], False)
        self.assertIn("no version recorded", found["detail"])

    def test_a_toolbox_that_says_nothing_is_not_a_fault(self):
        """Nothing to compare against is not the same as out of date."""
        self.build()
        os.unlink(os.path.join(self.root + checkup.SOURCE_COPY,
                               "dbus-next", "VERSION"))
        found = self.said()
        self.assertIsNone(found["ok"])
        self.assertFalse(found["repairable"])

    def test_the_whole_reading_carries_it(self):
        self.build()
        names = [one["name"] for one in checkup.look(self.root, here=ALL)]
        self.assertIn("The python modules this project carries", names)


class SwitchedTest(Room):
    """The two files that a switch writes, and no installation.

    A fresh installation leaves both out, because nobody added a drive and
    nobody switched controller wake on. The page called that "2 never start"
    and showed a red light that no reinstallation could clear.

    Room.build writes every file of the keep-list, so every other test here
    describes a machine that a fresh installation never is. These tests take
    the two away again.
    """

    def switches_off(self):
        """The machine that a fresh installation really leaves behind."""
        self.build()
        for path in checkup.SWITCHED:
            os.unlink(self.root + path)

    def switch_on(self, path):
        """Put that switch on, the way the machine records it.

        Each of the three is a different record, because each switch is a
        different feature. A helper that wrote one file for all of them would
        answer for a machine that cannot exist.
        """
        if "mounts" in path:
            where, text = mounts.STATE_PATH, ""
        elif "wake" in path:
            where, text = wake.STATE_PATH, ""
        else:
            where, text = power.CONFIG_PATH, "CPU_GOVERNOR=performance\n"
        os.makedirs(os.path.dirname(self.root + where), exist_ok=True)
        with open(self.root + where, "w") as handle:
            handle.write(text)

    def test_every_one_of_them_is_on_the_keep_list(self):
        """A key that names no file of the keep-list excuses nothing.

        The table is read against the paths that units() looks at. A rename
        on one side alone makes each entry dead and quietly brings the red
        light back.
        """
        for path in checkup.SWITCHED:
            self.assertIn(path, mounts.PROJECT_FILES)

    def test_every_one_of_them_is_a_link_and_not_a_unit(self):
        for path in checkup.SWITCHED:
            self.assertIn(".wants/", path)

    def test_a_fresh_installation_with_no_switch_on_is_in_order(self):
        self.switches_off()
        found = self.named(checkup.units(ALL, self.root), "What starts them")
        self.assertIs(found["ok"], True)

    def test_it_says_which_switch_each_one_waits_for(self):
        """Silence would hide two links that systemd never starts."""
        self.switches_off()
        found = self.named(checkup.units(ALL, self.root), "What starts them")
        self.assertIn("wait for a switch", found["detail"])
        self.assertIn("controller wake", found["detail"])
        self.assertIn("a drive on the System page", found["detail"])

    def test_the_count_of_the_links_leaves_them_out(self):
        """"All 20 links are here" with 17 of them there is a lie."""
        self.switches_off()
        found = self.named(checkup.units(ALL, self.root), "What starts them")
        links = [path for path in checkup.wanted(ALL) if ".wants/" in path]
        self.assertIn(
            "All %d links are here." % (len(links) - len(checkup.SWITCHED)),
            found["detail"])

    def test_one_that_is_gone_with_its_switch_on_is_a_fault(self):
        """The other half, and the reason the switch is asked at all.

        An update that ignores the keep-list takes the link. The feature then
        says it is on and systemd starts nothing. A check that reads "absent"
        as "off" for every machine reports nothing on the machine that this
        whole file is for.
        """
        for path in checkup.SWITCHED:
            with self.subTest(path=path):
                self.switches_off()
                self.switch_on(path)
                found = self.named(checkup.units(ALL, self.root),
                                   "What starts them")
                self.assertIs(found["ok"], False)
                self.assertIn(os.path.basename(path), found["detail"])
                self.assertIn("never start", found["detail"])

    def test_a_link_that_no_switch_writes_is_still_a_fault(self):
        """The check this change had to leave alone."""
        self.switches_off()
        other = (mounts.UNIT_DIR + "/multi-user.target.wants/"
                 "steamos-utility-center-nanoleaf.service")
        self.assertNotIn(other, checkup.SWITCHED)
        os.unlink(self.root + other)
        found = self.named(checkup.units(ALL, self.root), "What starts them")
        self.assertIs(found["ok"], False)
        self.assertIn("steamos-utility-center-nanoleaf.service",
                      found["detail"])

    def test_a_link_that_names_a_unit_which_is_gone_is_still_a_fault(self):
        """A dangling link is a fault whatever the switch says."""
        self.switches_off()
        path = list(checkup.SWITCHED)[0]
        self.switch_on(path)
        os.symlink(self.root + "/nowhere", self.root + path)
        found = self.named(checkup.units(ALL, self.root), "What starts them")
        self.assertIs(found["ok"], False)

    def test_a_path_that_no_switch_writes_is_always_on(self):
        self.assertIs(checkup.switched_on("/etc/systemd/system/anything",
                                          self.root), True)

    def test_the_question_reads_var_and_not_the_link(self):
        """/etc is what an update rebuilds, so the link cannot answer this.

        The link is there and the record is not. A question that read the
        link would answer "on" and a repair would then leave a machine with
        its feature off.
        """
        self.build()
        for path in checkup.SWITCHED:
            with self.subTest(path=path):
                self.assertTrue(os.path.exists(self.root + path))
                self.assertIs(checkup.switched_on(path, self.root), False)


class PasswordRuleTest(Room):
    """The rule that only root can read, on a machine with no module.

    ctl.permit removes the rule where there is nothing to permit, because
    each line of it names one applier and the rule holds no wildcard. The
    check asked only whether the file was there, so a core installation on
    its own reported a fault that no reinstallation repaired.
    """

    def look(self):
        """The one finding, answered for this machine and not for this one."""
        return checkup.password_rule(
            self.root,
            present=lambda path: os.path.exists(self.root + path))[0]

    def core_only(self):
        """Take every applier away, which is what a core installation is."""
        self.build()
        for name, who in checkup.PROGRAMS.items():
            if who == checkup.CORE:
                continue
            whole = os.path.join(self.root + checkup.INSTALL_DIR, name)
            if os.path.exists(whole):
                os.unlink(whole)

    def test_a_machine_with_no_module_needs_no_rule(self):
        self.core_only()
        os.unlink(self.root + checkup.SUDO_RULE)
        found = self.look()
        self.assertIs(found["ok"], True)
        self.assertIn("No module", found["detail"])

    def test_a_machine_with_a_module_and_no_rule_is_a_fault(self):
        self.build()
        os.unlink(self.root + checkup.SUDO_RULE)
        self.assertTrue(ctl.permits(
            lambda path: os.path.exists(self.root + path)))
        found = self.look()
        self.assertIs(found["ok"], False)
        self.assertIn("Game Mode", found["detail"])

    def test_a_machine_with_a_module_and_the_rule_is_in_order(self):
        self.build()
        found = self.look()
        self.assertIs(found["ok"], True)

    def test_a_directory_that_only_root_can_read_answers_neither(self):
        """The check that this change had to leave alone."""
        self.build()
        shutil.rmtree(self.root + os.path.dirname(checkup.SUDO_RULE))
        found = self.look()
        self.assertIsNone(found["ok"])
        self.assertIs(found["repairable"], False)


class WholeTest(Room):
    """A machine with nothing missing says so."""

    def test_a_complete_machine_has_no_fault(self):
        self.build()
        found = checkup.look(self.root, here=ALL)
        self.assertEqual(checkup.trouble(found), [])

    def test_it_looks_at_every_part(self):
        """A check that silently stops looking passes the test above."""
        self.build()
        found = checkup.look(self.root, here=ALL)
        for start in ("The units", "What starts them", "The keep-list",
                      "The programs", "The toolbox", "The settings",
                      "The short command", "The rule for"):
            self.named(found, start)


class ModuleTest(Room):
    """A module that is not installed is not a fault."""

    # What a machine carries for each module it does not have. Written out
    # here rather than asked of checkup, so that this test describes the
    # machine and checkup judges it.
    GONE = {modules.PEGBOARD: ["pegboard"],
            modules.POWER: ["-power"],
            modules.SYSTEM: ["-mounts", "-wake"]}

    def test_a_machine_without_a_module_is_not_told_it_is_broken(self):
        """Its units are not there, and that is correct rather than wrong.

        A red line about the Pegboard on a machine with no Pegboard is a red
        line for ever, and a person learns to read past the whole page.
        """
        away = sum(self.GONE.values(), [])
        self.build(without=away)
        found = checkup.look(self.root, here=[modules.LED])
        self.assertEqual(checkup.trouble(found), [])

    def test_the_units_of_a_module_that_is_here_are_looked_at(self):
        """The other half. Without it the test above passes with a checkup
        that looks at nothing at all."""
        self.build(skip=["steamos-utility-center-pegboard.service"])
        found = checkup.look(self.root,
                             here=[modules.LED, modules.PEGBOARD])
        said = self.named(found, "The units")
        self.assertIs(said["ok"], False)
        self.assertIn("pegboard", said["detail"])


class UnitTest(Room):
    """The units, and the links that make systemd start them."""

    def test_a_unit_that_is_gone_is_named(self):
        self.build(skip=["steamos-utility-center-nanoleaf-watch.service"])
        said = self.named(checkup.look(self.root, here=ALL), "The units")
        self.assertIs(said["ok"], False)
        self.assertIn("nanoleaf-watch", said["detail"])

    def test_a_unit_with_no_link_never_starts(self):
        """The file is there and the feature is off. Nothing reports it, and
        every list of files says the installation is complete."""
        self.build()
        os.unlink(self.root + mounts.UNIT_DIR
                  + "/multi-user.target.wants/"
                    "steamos-utility-center-nanoleaf.service")
        said = self.named(checkup.look(self.root, here=ALL),
                          "What starts them")
        self.assertIs(said["ok"], False)
        self.assertIn("never start", said["detail"])

    def test_a_link_that_names_a_unit_that_is_gone_is_told_apart(self):
        """systemd reports this at every boot, into a log nobody reads."""
        self.build()
        where = (self.root + mounts.UNIT_DIR + "/multi-user.target.wants/"
                 "steamos-utility-center-nanoleaf.service")
        os.unlink(where)
        os.symlink("/nowhere/steamos-utility-center-nanoleaf.service", where)
        said = self.named(checkup.look(self.root, here=ALL),
                          "What starts them")
        self.assertIs(said["ok"], False)
        self.assertIn("name a unit that is gone", said["detail"])


class KeepListTest(Room):
    """The one file on the list that the list cannot protect."""

    def test_a_keep_list_that_is_gone_is_a_fault(self):
        self.build()
        os.unlink(self.root + mounts.KEEP_LIST)
        said = self.named(checkup.look(self.root, here=ALL), "The keep-list")
        self.assertIs(said["ok"], False)
        self.assertIn("next update", said["detail"])

    def test_a_file_that_the_keep_list_does_not_name_is_a_fault(self):
        """It is on the machine now and gone after the next update."""
        self.build()
        keep = self.root + mounts.KEEP_LIST
        with open(keep) as handle:
            lines = [one for one in handle.read().splitlines()
                     if "nanoleaf-watch" not in one]
        with open(keep, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        said = self.named(checkup.look(self.root, here=ALL), "The keep-list")
        self.assertIs(said["ok"], False)
        self.assertIn("nanoleaf-watch", said["detail"])


class ProgramTest(Room):
    """The entry points and the appliers under INSTALL_DIR."""

    def test_a_program_that_is_gone_is_named(self):
        """By the word "gone" and not only by its name.

        os.access answers False for a file that is not there at all, so a
        checkup with no test for existence puts it under "cannot run"
        instead. The name appears either way, and a test that asks only for
        the name cannot tell a missing file from an unreadable one.
        """
        self.build()
        os.unlink(os.path.join(self.root + checkup.INSTALL_DIR,
                               "steamos-utility-centerctl"))
        said = self.named(checkup.look(self.root, here=ALL), "The programs")
        self.assertIs(said["ok"], False)
        self.assertIn("centerctl", said["detail"])
        self.assertIn("are gone", said["detail"])
        self.assertNotIn("cannot run", said["detail"])

    def test_a_program_that_cannot_run_is_named(self):
        """An applier with no execute bit is a unit that fails at a moment
        nobody looks at."""
        self.build()
        os.chmod(os.path.join(self.root + checkup.INSTALL_DIR,
                              "steamos-utility-center-nanoleaf-watch"), 0o644)
        said = self.named(checkup.look(self.root, here=ALL), "The programs")
        self.assertIs(said["ok"], False)
        self.assertIn("cannot run", said["detail"])


class SettingsTest(Room):
    """The files that hold what a person chose."""

    def test_a_missing_settings_file_is_never_offered_a_repair(self):
        """A repair writes the defaults of this project. Over these, that is
        the LED count, the serial port and the effect of a person, gone."""
        self.build(skip=["steamos-utility-center.conf"])
        said = self.named(checkup.look(self.root, here=ALL), "The settings")
        self.assertIs(said["ok"], False)
        self.assertFalse(said["repairable"])


class QuietTest(Room):
    """The two answers that must not be red, and the reason for each."""

    def test_a_missing_short_command_is_not_a_fault(self):
        """It is a link on the read-only filesystem that every SteamOS
        update removes, and the full path works either way."""
        self.build()
        os.unlink(self.root + checkup.COMMANDS[0])
        said = self.named(checkup.look(self.root, here=ALL),
                          "The short command")
        self.assertIsNone(said["ok"])
        self.assertNotIn(said, checkup.trouble(checkup.look(self.root,
                                                            here=ALL)))

    def test_a_rule_that_cannot_be_read_is_not_called_gone(self):
        """Only root can look into /etc/sudoers.d. The panel runs as a
        person, and "not mine to look at" is not "not there"."""
        said = checkup.password_rule("/nowhere-at-all")
        self.assertIsNone(said[0]["ok"])
        self.assertIn("root", said[0]["detail"])

    def test_a_rule_that_is_really_gone_is_a_fault(self):
        """The other half, or the answer above hides a real one."""
        self.build()
        # The directory stays, so this is "looked and found nothing" and not
        # "could not look". The two answers differ and the test above holds
        # the other one.
        os.unlink(self.root + checkup.SUDO_RULE)
        said = self.named(checkup.look(self.root, here=ALL), "The rule for")
        self.assertIs(said["ok"], False)
        self.assertIn("password", said["detail"])


class ToolboxTest(Room):
    """The copy that the menu entry opens.

    The clone is something a person can throw away now, so this copy is what
    the panel is. A machine that lost it keeps every service and has no
    window, and nothing else on the Status page would say why.
    """

    def test_a_copy_that_is_gone_is_a_fault(self):
        self.build()
        shutil.rmtree(self.root + checkup.SOURCE_COPY)
        said = self.named(checkup.look(self.root, here=ALL), "The toolbox")
        self.assertIs(said["ok"], False)
        self.assertIn("does not open", said["detail"])

    def test_a_part_of_it_that_is_gone_is_named(self):
        self.build(skip=["install.sh"])
        said = self.named(checkup.look(self.root, here=ALL), "The toolbox")
        self.assertIs(said["ok"], False)
        self.assertIn("install.sh", said["detail"])

    def test_a_panel_that_cannot_run_is_a_fault(self):
        """The file is there and the entry does nothing when it is pressed."""
        self.build()
        os.chmod(os.path.join(self.root + checkup.SOURCE_COPY,
                              checkup.TOOLBOX[0]), 0o644)
        said = self.named(checkup.look(self.root, here=ALL), "The toolbox")
        self.assertIs(said["ok"], False)
        self.assertIn("cannot run", said["detail"])

    def test_the_named_parts_are_the_ones_the_panel_reaches_for(self):
        """Each one is a file the window or one of its buttons needs."""
        for name in ("gui/steamos-utility-center-panel", "install.sh",
                     "scripts/update.sh"):
            self.assertIn(name, checkup.TOOLBOX)


class NoWriteTest(unittest.TestCase):
    """It reads the machine and changes nothing.

    A check that repairs on its own is a check a person cannot run to find
    out where they stand. The repair is the installer, and pressing it is a
    decision.
    """

    SOURCE = os.path.join(HERE, "..", "server", "steamos_utility_center",
                          "checkup.py")

    def _tree(self):
        with open(self.SOURCE) as handle:
            return ast.parse(handle.read())

    def test_it_runs_no_program(self):
        names = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Import):
                names.update(one.name for one in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        for banned in ("subprocess", "shutil", "os.system"):
            self.assertNotIn(banned, names, banned)

    def test_it_opens_no_file_for_writing(self):
        for node in ast.walk(self._tree()):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", "") != "open":
                continue
            for arg in node.args[1:]:
                self.assertNotIn("w", getattr(arg, "value", ""),
                                 "checkup opens a file for writing")


if __name__ == "__main__":
    unittest.main()
