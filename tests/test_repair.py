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

from steamos_utility_center import checkup, modules, mounts, repair  # noqa: E402

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

    def toolbox(self):
        """The copy of this project, which carries the udev rule."""
        for name in (repair.UDEV_SOURCE,) + checkup.TOOLBOX:
            whole = os.path.join(self.root + repair.SOURCE_COPY, name)
            os.makedirs(os.path.dirname(whole), exist_ok=True)
            with open(whole, "w") as handle:
                handle.write('ACTION=="add", SUBSYSTEM=="tty"\n')
            os.chmod(whole, 0o755)

    def build(self, here=ALL, skip=()):
        """A machine with everything on it, less the names of `skip`."""
        self.templates()
        self.user()
        self.toolbox()
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

    def run_it(self, here=ALL):
        return repair.run(root=self.root, here=here)


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

    def test_it_writes_the_udev_rule_from_the_copy_of_the_toolbox(self):
        rule = repair.UDEV_RULE
        self.build()
        self.take(rule)
        self.run_it()
        with open(self.root + rule) as handle:
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

    def test_it_does_nothing_without_the_program(self):
        self.check, self.said = "", ""
        answer, ran = self.go()
        self.assertEqual(answer.returncode, 0)
        self.assertEqual(ran, "")


if __name__ == "__main__":
    unittest.main()
