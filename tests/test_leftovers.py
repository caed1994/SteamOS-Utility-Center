# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""What a removal leaves behind, against what it is meant to leave behind.

Taking a module off is four or five lines in install.sh, and a file that one
of them forgets stays on the machine for ever. Nothing reports it: the module
reads as removed, its page offers to install it again, and the leftover is
found by somebody who looks into /etc by hand.

So this reads the removal of each module and asks whether it reaches every
file that checkup says the module owns. What stays is written down here, by
name and with the reason, and a file that stays for no reason is a fault.

The shell variables are resolved rather than matched by name. A first attempt
looked for the file name in the removal block, and reported ten leftovers
that are not there: `rm -f "$UNIT_PATH"` holds no file name at all.
"""

import io
import os
import re
import shutil
import subprocess
import tempfile
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import checkup, modules, mounts  # noqa: E402

# What a removal keeps, and why. Each of these is a decision and not an
# oversight, and each one is said on the screen while it happens.
# It is empty, and that is the point: every file a module owns is reachable
# by taking that module off.
#
# The settings files were here. They are reached now, under --purge, and a
# removal without it says on the screen that they stay. Which of the two is
# the default is a question for PurgeTest below, not for this one: here the
# question is whether a file can be got rid of at all.
KEPT = {}

# Where each module is taken off the machine.
REMOVERS = {modules.LED: "remove_led",
            modules.PEGBOARD: "remove_pegboard",
            modules.POWER: "remove_power",
            modules.SYSTEM: "remove_system"}


def shell_values():
    """Every VAR="..." of the shared script, with the names resolved.

    $ROOT is empty on a real machine, and every path here is built from it,
    $NAME and one directory. Eight rounds is far more than the deepest of
    them needs.

    ${VAR:-default} is read, and a value that names itself that way takes the
    default. ROOT="${ROOT:-}" is that idiom, and a reader without it grows
    the value by four characters a round and matches nothing at all.
    """
    text = io.open(os.path.join(REPO, "scripts", "user-unit.sh")).read()
    raw = dict(re.findall(r'^([A-Z_][A-Z0-9_]*)="([^"\n]*)"', text, re.M))
    for name, value in list(raw.items()):
        raw[name] = re.sub(r"\$\{%s:-([^}]*)\}" % re.escape(name),
                           lambda m: m.group(1), value)
    raw.setdefault("ROOT", "")

    def fill(text, out):
        text = re.sub(r"\$\{([A-Z_][A-Z0-9_]*):-([^}]*)\}",
                      lambda m: out.get(m.group(1), m.group(2)), text)
        return re.sub(r"\$\{?([A-Z_][A-Z0-9_]*)\}?",
                      lambda m: out.get(m.group(1), m.group(0)), text)

    out = dict(raw)
    for _ in range(8):
        out = dict((name, fill(value, out)) for name, value in raw.items())
    return out


def block(name):
    """The body of one shell function of the installer."""
    text = io.open(os.path.join(REPO, "install.sh")).read()
    assert "%s()" % name in text, "no function %s in install.sh" % name
    return text.split("%s()" % name, 1)[1].split("\n}", 1)[0]


class ResolveTest(unittest.TestCase):
    """The reading of the shell, which the tests below stand on."""

    def test_the_paths_come_out_whole(self):
        said = shell_values()
        self.assertEqual(said["UNIT_PATH"],
                         "/etc/systemd/system/steamos-utility-center.service")
        self.assertEqual(said["UDEV_PATH"],
                         "/etc/udev/rules.d/99-steamos-utility-center.rules")
        self.assertEqual(
            said["SLEEP_HELPER_PATH"],
            "/var/lib/steamos-utility-center/steamos-utility-center-sleep")

    def test_no_name_is_left_unresolved(self):
        """A value with a $ in it matches nothing, and every check below then
        reports a leftover that is not there."""
        for name, value in shell_values().items():
            if value.startswith(("/etc", "/var", "/usr")):
                self.assertNotIn("$", value, name)


class Reader(unittest.TestCase):
    """The shared reading of a removal. It carries no test of its own."""

    def setUp(self):
        self.value = shell_values()
        # path -> the variables that name it
        self.named = {}
        for name, value in self.value.items():
            self.named.setdefault(value, []).append(name)

    def owned(self, module):
        """The files of one module: the keep-list, and the programs."""
        out = [path for path in mounts.PROJECT_FILES
               if checkup.owner(path) == module]
        out += [os.path.join(checkup.INSTALL_DIR, name)
                for name, who in checkup.PROGRAMS.items() if who == module]
        return sorted(set(out))

    @staticmethod
    def orders(body):
        """The lines of a removal that take something off the machine.

        A line that only names a file does not remove it. The first version
        of this test read the whole block, so `say "the settings stay"` made
        the settings count as removed, and a --purge that stopped removing
        them passed.

        The continued lines are joined first: every `rm -f` here runs over
        two lines with a backslash between them.

        purge_config is a removal as well. It takes one settings file under
        every name it ever had, because a purge that left the name from
        before the rename was undone by the next install. See
        scripts/user-unit.sh.
        """
        whole = body.replace("\\\n", " ")
        return [line for line in whole.splitlines()
                if re.search(r"\brm\s+-[rf]", line)
                or "systemctl disable" in line
                or "purge_config" in line]

    def reached(self, path, body):
        """Whether this removal takes this file off the machine.

        Three ways. By a variable that holds the path, by the file name
        itself, or, for a link in a .wants directory, by a `systemctl
        disable` of the unit it points at: that is what takes the link.
        """
        lines = self.orders(body)
        for name in self.named.get(path, []):
            if any("$" + name in line for line in lines):
                return True
        base = os.path.basename(path)
        if any(base in line for line in lines):
            return True
        if ".wants/" in path:
            short = base.replace("steamos-utility-center", "$NAME")
            return any("disable" in line and (short in line or base in line)
                       for line in lines)
        return False

    def under(self, path, lines):
        """Whether an `rm -r` of a directory above this path takes it.

        uninstall.sh ends with one `rm -rf` of /var/lib/steamos-utility-center
        and that reaches every program, every template and the copy of the
        toolbox. A test that asked for each of those by name would ask for a
        line that is right to leave out.
        """
        for name, value in self.value.items():
            if not value or not path.startswith(value.rstrip("/") + "/"):
                continue
            if any(re.search(r"\brm\s+-[a-z]*r", line) and "$" + name in line
                   for line in lines):
                return True
        return False


class LeftoverTest(Reader):
    """Every file a module owns is reached when the module is taken off."""

    def test_every_module_takes_its_own_files_with_it(self):
        missed = []
        for module, where in REMOVERS.items():
            body = block(where)
            for path in self.owned(module):
                if path in KEPT or self.reached(path, body):
                    continue
                missed.append("%s leaves %s" % (where, path))
        self.assertEqual(missed, [])

    def test_what_stays_is_written_down_and_no_more(self):
        """A file in KEPT that no removal leaves is a note about nothing, and
        it hides the day somebody starts removing it."""
        stays = set()
        for module, where in REMOVERS.items():
            body = block(where)
            for path in self.owned(module):
                if not self.reached(path, body):
                    stays.add(path)
        self.assertEqual(sorted(stays), sorted(KEPT))

    def test_the_removals_exist_for_every_module(self):
        """A module with no removal cannot be taken off at all."""
        for module in modules.ORDER:
            if module == modules.CEC:
                continue            # its own installer, in cec-toolkit
            self.assertIn(module, REMOVERS, module)


class UninstallTest(Reader):
    """Every file of this project is reached by uninstall.sh.

    LeftoverTest above asks the same question of each module removal, and it
    asks it only about the files that module owns. The core owns files as
    well: the units of the Nanoleaf devices, the boot-time repair, the
    sudoers rule and the entry points. Nothing read those at all.

    A mutation found it. The line that disables the repair unit was taken
    out of uninstall.sh and the whole suite passed, which left a machine with
    a unit in /etc and a link in multi-user.target.wants after a removal that
    said "Removed."
    """

    def everything(self):
        """Every file this project writes outside a home directory."""
        out = list(mounts.PROJECT_FILES)
        out += [os.path.join(checkup.INSTALL_DIR, name)
                for name in checkup.PROGRAMS]
        out += [mounts.KEEP_LIST, checkup.SOURCE_COPY,
                self.value["UNIT_TEMPLATE_DIR"],
                self.value["UDEV_TEMPLATE_DIR"],
                self.value["PYTHON_DIR"],
                self.value["PYTHON_VERSIONS"],
                self.value["WATCHER_RECORD_PATH"]]
        return sorted(set(out))

    def test_it_reaches_every_file_of_this_project(self):
        with io.open(os.path.join(REPO, "uninstall.sh")) as handle:
            body = handle.read()
        lines = self.orders(body)
        missed = [path for path in self.everything()
                  if not self.reached(path, body) and not self.under(path, lines)]
        self.assertEqual(missed, [])


class InstallTest(Reader):
    """Every program the diagnosis asks for is one the installer writes.

    checkup.PROGRAMS is the list that card reads a machine against. A name in
    it that install.sh never writes is a red line on every machine, for ever,
    and the repair button does not clear it. The two lists were never read
    against each other.
    """

    def destinations(self):
        """Where each `install -m 07..` line of the installer puts a file."""
        with io.open(os.path.join(REPO, "install.sh")) as handle:
            text = handle.read().replace("\\\n", " ")
        out = []
        for line in text.splitlines():
            if not re.search(r"\binstall\s+-m\s+07", line):
                continue
            out.append(re.sub(r"\$\{?([A-Z_][A-Z0-9_]*)\}?",
                              lambda m: self.value.get(m.group(1), m.group(0)),
                              line))
        return out

    def test_the_installer_writes_every_program(self):
        where = self.destinations()
        missed = [name for name in checkup.PROGRAMS
                  if not any(os.path.join(checkup.INSTALL_DIR, name) in line
                             for line in where)]
        self.assertEqual(missed, [])

    def test_it_copies_units_and_nothing_else_into_the_template_directory(self):
        """server/ holds three .conf files beside the unit templates.

        A copy of every file there would put the settings of a person within
        reach of a repair, and a repair writes a template back without
        asking. repair.plan looks at the unit directory alone, and this is
        the other half of that promise.
        """
        with io.open(os.path.join(REPO, "install.sh")) as handle:
            lines = handle.read().splitlines()
        copies = [line for line in lines if "$UNIT_TEMPLATE_DIR" in line
                  and "install " in line and "install -d" not in line]
        self.assertEqual(len(copies), 1)
        self.assertIn("/server/*.service", copies[0])

    def test_the_udev_rule_is_kept_outside_the_toolbox_copy(self):
        """A repair installs it into /etc as root at a boot, unread.

        A udev rule names a program and udev runs that program as root. The
        toolbox copy belongs to the desktop user, so a rule taken from there
        is a way to become root at the next boot with no password. The
        template directory belongs to root, as the unit templates do.
        """
        self.assertTrue(self.value["UDEV_TEMPLATE_DIR"].startswith(
            checkup.INSTALL_DIR + "/"))
        self.assertFalse(self.value["UDEV_TEMPLATE_DIR"].startswith(
            checkup.SOURCE_COPY))
        with io.open(os.path.join(REPO, "install.sh")) as handle:
            text = handle.read()
        self.assertIn('install -m 0644 "$SOURCE_DIR/udev/99-$NAME.rules" '
                      '"$UDEV_TEMPLATE_DIR/"', text)

    def test_the_copy_goes_to_the_person_who_updates_it(self):
        """git refuses a repository that belongs to somebody else.

        It says "detected dubious ownership" and stops, so a copy owned by
        root gave the update page no fetch and no fast-forward. The parent
        directory stays with root: the appliers are in it, and the sudoers
        rule names them and asks for no password.
        """
        with io.open(os.path.join(REPO, "install.sh")) as handle:
            text = handle.read()
        chowns = [line.strip() for line in text.splitlines()
                  if "chown -R" in line and "SOURCE_COPY" in line]
        self.assertTrue(chowns)
        self.assertTrue(any("$WATCHER_USER" in line for line in chowns),
                        "nothing gives the copy to the desktop user")
        # And the mend runs from inside the copy as well, or the remedy that
        # the update page names does nothing.
        body = block("copy_toolbox")
        early = body[:body.index("return 0")]
        self.assertIn("give_away_toolbox", early)

    def test_it_writes_down_the_account_the_units_run_as(self):
        """A repair at a boot reads that record to fill in @WATCHER_USER@.

        Without it every unit that runs as the desktop user is skipped, and
        the Nanoleaf devices stop following the machine after an update.

        The line has to be inside `if watcher_user_dirs`, because that is
        what sets the name. Outside it the record is an empty file, which
        reads as no record at all.
        """
        with io.open(os.path.join(REPO, "install.sh")) as handle:
            lines = handle.read().splitlines()
        wrote = [i for i, line in enumerate(lines)
                 if "$WATCHER_RECORD_PATH" in line and ">" in line]
        self.assertEqual(len(wrote), 1, "one line writes the record")
        self.assertIn("$WATCHER_USER", lines[wrote[0]])
        above = [line for line in lines[:wrote[0]]
                 if re.match(r"\s*(if|fi)\b", line)]
        self.assertEqual(above[-1].strip(), "if watcher_user_dirs; then")


class ClonePycTest(unittest.TestCase):
    """An install leaves no bytecode in the clone.

    install.sh and uninstall.sh run as root, and three of their steps import
    the package from the clone to read it. Python writes __pycache__ beside
    the source it imports, so each install left root-owned .pyc files in a
    directory that belongs to a person. `rm -rf` on their own clone then
    failed on every one of them.

    The clone is a thing this project tells people to throw away, and that
    promise breaks on a file its owner cannot remove.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.source = os.path.join(self.root, "clone")
        os.makedirs(os.path.join(self.source, "server"))
        shutil.copytree(
            os.path.join(REPO, "server", "steamos_utility_center"),
            os.path.join(self.source, "server", "steamos_utility_center"),
            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(REPO, "scripts"),
                        os.path.join(self.source, "scripts"))

    def _bytecode(self):
        found = []
        for where, dirs, names in os.walk(self.source):
            found += [os.path.join(where, name) for name in names
                      if name.endswith(".pyc")]
        return found

    def test_reading_the_modules_writes_none(self):
        """module_states in scripts/user-unit.sh, which both scripts call."""
        answer = subprocess.run(
            ["bash", "-c",
             'set -e\nSOURCE_DIR="%s"\nsource "%s/scripts/user-unit.sh"\n'
             "module_states\n" % (self.source, self.source)],
            capture_output=True, text=True,
            cwd=self.root, env=dict(os.environ, ROOT=self.root))
        self.assertEqual(answer.returncode, 0, answer.stderr)
        self.assertIn("led ", answer.stdout)
        self.assertEqual(self._bytecode(), [])

    def test_describing_a_module_writes_none(self):
        answer = subprocess.run(
            ["bash", "-c",
             'set -e\nSOURCE_DIR="%s"\nsource "%s/scripts/user-unit.sh"\n'
             "module_says led\n" % (self.source, self.source)],
            capture_output=True, text=True,
            cwd=self.root, env=dict(os.environ, ROOT=self.root))
        self.assertEqual(answer.returncode, 0, answer.stderr)
        self.assertEqual(self._bytecode(), [])

    def test_every_python_run_against_the_clone_says_so(self):
        """The rule, for a call that somebody adds later.

        The two tests above run the calls that exist today. This one holds
        the rule itself, so a fourth call does not bring the fault back.
        """
        missed = []
        for name in ("install.sh", "uninstall.sh",
                     os.path.join("scripts", "user-unit.sh"),
                     os.path.join("scripts", "update.sh")):
            with io.open(os.path.join(REPO, name)) as handle:
                text = handle.read().replace("\\\n", " ")
            for number, line in enumerate(text.splitlines(), 1):
                if "python3" not in line or "$SOURCE_DIR" not in line:
                    continue
                if "PYTHONDONTWRITEBYTECODE" in line:
                    continue
                missed.append("%s:%d %s" % (name, number, line.strip()))
        self.assertEqual(missed, [])


class PurgeTest(unittest.TestCase):
    """The option that takes the settings as well."""

    def test_each_removal_offers_it(self):
        for module, where in REMOVERS.items():
            body = block(where)
            if not any(path in body for path in
                       ("CONFIG_PATH", "MOUNTS_RECORD_PATH")):
                continue
            self.assertIn("PURGE", body, where)

    def test_the_installer_knows_the_option(self):
        text = io.open(os.path.join(REPO, "install.sh")).read()
        self.assertIn("--purge)", text)
        self.assertIn("--purge         with --without", text)

    def test_the_panel_asks_before_it_purges(self):
        """It is off by default, and the dialog names it.

        The dialog is in gui/dialogs.py, where the window's modal windows
        live: a page of the window needs them, and a page cannot import the
        window back. The seam that opens it is in gui/page_modules.py, which
        holds the half of every module page that is about the module.

        The window's code is read wherever it lives: it is cut into one
        module per page, and a test that named one file stopped reading the
        thing it asks about at each cut.
        """
        gui = os.path.join(REPO, "gui")
        panel = "\n".join(
            io.open(os.path.join(gui, name)).read()
            for name in ["steamos-utility-center-panel"]
            + sorted(one for one in os.listdir(gui)
                     if one.startswith("page_") and one.endswith(".py")))
        dialogs = io.open(os.path.join(gui, "dialogs.py")).read()
        body = dialogs.split("class RemoveDialog")[1].split("\nclass ")[0]
        self.assertIn("BooleanVar(value=False)", body)
        self.assertIn("Remove its settings as well", body)
        # The dialog is behind a seam, so that a test can answer for a
        # person. See _ask_remove.
        seam = panel.split("def _ask_remove")[1].split("\n    def ")[0]
        self.assertIn("RemoveDialog", seam)
        self.assertIn("purge.get()", seam)
        said = panel.split("def _remove_module")[1].split("\n    def ")[0]
        self.assertIn("_ask_remove", said)
        self.assertIn("purge=purge", said)

    def test_the_command_carries_it_only_on_a_removal(self):
        """On an install it means nothing, and an option that means nothing
        on half the calls ends up on the wrong one."""
        sys.path.insert(0, os.path.join(REPO, "gui"))
        import ledpanel
        self.assertNotIn("--purge",
                         ledpanel.module_command("/x", "led", purge=True))
        self.assertIn("--purge",
                      ledpanel.module_command("/x", "led", remove=True,
                                              purge=True))


class RunPurgeTest(unittest.TestCase):
    """Each removal run against a machine, and not read.

    Every test above this one reads install.sh. That is right for a step
    which needs root, and it left one question open: "--purge removes the
    settings" was a grep for the word PURGE.

    It passed while a purge left the settings on the machine. Each of these
    files had a name before this project was renamed, and migrate_old_install
    leaves the old file where both names are present. A purge took the new
    name, the next install moved the old one back, and "Remove its settings
    as well" gave the same settings again. See purge_config.
    """

    # The function, the settings file it owns, and the name that file had
    # before the rename. See OLD_CONFIGS in scripts/user-unit.sh.
    CASES = {
        "remove_led": ("/etc/steamos-utility-center.conf",
                       "/etc/steamos-led-serial.conf"),
        "remove_power": ("/etc/steamos-utility-center-power.conf",
                         "/etc/steamos-led-power.conf"),
        "remove_pegboard": ("/etc/steamos-utility-center-pegboard.conf", None),
        "remove_system": ("/var/lib/steamos-utility-center/mounts.conf", None),
    }

    HARNESS = os.path.join(REPO, "tests", "shell", "run-remove.sh")

    def machine(self, paths):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for path in paths:
            os.makedirs(os.path.dirname(root + path), exist_ok=True)
            with open(root + path, "w") as handle:
                handle.write("SETTING=mine\n")
        return root

    def remove(self, func, purge, root, works=True):
        done = subprocess.run(["bash", self.HARNESS, func, str(purge), root],
                              capture_output=True, text=True)
        if works:
            self.assertEqual(done.returncode, 0,
                             "%s exited %d: %s" % (func, done.returncode,
                                                   done.stderr))
        return done

    def stuck(self, path):
        """A machine where that settings file cannot be removed.

        A directory in its place, because rm -f fails on one and leaves it
        there. The machine this reproduces is a different one: a locked root
        filesystem, where every write and every removal under /etc fails and
        the installer goes on. What the two have in common is the part under
        test, which is rm -f reporting nothing and the file staying.
        """
        root = self.machine([])
        os.makedirs(root + path)
        with open(os.path.join(root + path, "in-the-way"), "w") as handle:
            handle.write("x\n")
        return root

    def test_the_harness_runs_the_real_function(self):
        """A harness that ran nothing would pass every test below it."""
        with open(os.path.join(REPO, "install.sh")) as handle:
            source = handle.read()
        for func in self.CASES:
            self.assertIn("\n%s()" % func, source)
        root = self.machine(["/etc/steamos-utility-center.conf"])
        self.remove("remove_led", 1, root)
        self.assertFalse(
            os.path.exists(root + "/etc/steamos-utility-center.conf"))

    def test_without_the_option_the_settings_stay(self):
        """The default, and the sentence the dialog puts under the box."""
        for func, (new, old) in self.CASES.items():
            with self.subTest(func):
                paths = [one for one in (new, old) if one]
                root = self.machine(paths)
                self.remove(func, 0, root)
                for path in paths:
                    self.assertTrue(os.path.exists(root + path),
                                    "%s took %s with no --purge"
                                    % (func, path))

    def test_with_the_option_they_go(self):
        for func, (new, _old) in self.CASES.items():
            with self.subTest(func):
                root = self.machine([new])
                self.remove(func, 1, root)
                self.assertFalse(os.path.exists(root + new),
                                 "%s left %s" % (func, new))

    def test_the_name_from_before_the_rename_goes_as_well(self):
        """Or the next install moves it back and the purge did nothing."""
        for func, (new, old) in self.CASES.items():
            if not old:
                continue
            with self.subTest(func):
                root = self.machine([new, old])
                self.remove(func, 1, root)
                self.assertFalse(os.path.exists(root + old),
                                 "%s left %s, which the next install moves "
                                 "to %s" % (func, old, new))

    def test_a_purge_that_removed_nothing_says_so(self):
        """Reported: "Remove its settings as well", and the settings stayed.

        rm -f says nothing about a file it could not remove, so the line
        after it named the file either way. A purge that did nothing read
        exactly like a purge that worked, on the screen and in the log.
        """
        for func, (new, _old) in self.CASES.items():
            with self.subTest(func):
                root = self.stuck(new)
                done = self.remove(func, 1, root, works=False)
                self.assertIn("could not remove", done.stderr,
                              "%s said nothing about %s" % (func, new))
                self.assertNotIn("and the settings in", done.stdout,
                                 "%s claimed the purge it did not do" % func)
                self.assertNotIn("and the drives in", done.stdout,
                                 "%s claimed the purge it did not do" % func)

    def test_a_purge_that_worked_still_says_so(self):
        """Or the test above passes on a line that nobody ever prints."""
        for func, (new, _old) in self.CASES.items():
            with self.subTest(func):
                root = self.machine([new])
                done = self.remove(func, 1, root)
                self.assertRegex(done.stdout, r"and the (settings|drives) in",
                                 "%s removed %s and said nothing"
                                 % (func, new))
                self.assertNotIn("could not remove", done.stderr)

    def test_only_that_module_loses_its_settings(self):
        """A purge on one module is not a purge on the machine."""
        every = [new for new, _old in self.CASES.values()]
        for func, (new, _old) in self.CASES.items():
            with self.subTest(func):
                root = self.machine(every)
                self.remove(func, 1, root)
                for path in every:
                    self.assertEqual(
                        os.path.exists(root + path), path != new,
                        "%s changed %s" % (func, path))


class SwitchedLinkTest(unittest.TestCase):
    """Which .wants links the installer writes, and which a switch writes.

    checkup.SWITCHED holds the second kind. Absent is what "off" looks like
    on the disk for those, so the Status page must not call them a fault and
    the boot repair must not write them back.

    Nothing held the *list*. Two were in it, the third was not, and a fresh
    install of the power module reported "1 never start" until somebody set
    a governor. So this reads the installer and refuses a link that neither
    side claims.
    """

    def enables(self):
        """Each `systemctl enable` of install.sh: (line number, unit names).

        Line continuations are joined first: one `systemctl enable` carries
        two unit names across a backslash, and a reader that took one line at
        a time called the second one unclaimed.

        `systemctl enable "$(basename "$X_UNIT_PATH")"` is resolved through
        the shared script, which is where that path is spelled. Two of the
        five enables are written that way.
        """
        values = shell_values()
        lines = io.open(os.path.join(REPO, "install.sh")).read().splitlines()
        out = []
        for index, first in enumerate(lines):
            if "systemctl enable" not in first:
                continue
            # The whole statement, and the number of the line it starts on.
            # Joining the file first would give the numbers of the joined
            # text, and the context read below would come from elsewhere.
            whole, step = first, index
            while whole.rstrip().endswith("\\") and step + 1 < len(lines):
                step += 1
                whole = whole.rstrip()[:-1] + " " + lines[step]
            plain = whole.replace("$NAME", "steamos-utility-center")
            names = set(re.findall(r"[\w.-]*\.service", plain))
            for var in re.findall(r'basename "\$(\w+)"', whole):
                if var in values:
                    names.add(os.path.basename(values[var]))
            out.append((index + 1, names))
        return out

    def enabled(self):
        """Every unit that install.sh enables, by name."""
        return set().union(*(names for _number, names in self.enables()))

    def test_the_reader_finds_the_units_it_is_meant_to(self):
        """A reader that found nothing would call every link switched."""
        found = self.enabled()
        self.assertIn("steamos-utility-center.service", found)
        # The one behind a $(basename "$VAR"), and the one on a continuation
        # line. Both were missed by the first version of this reader.
        self.assertIn("steamos-utility-center-pegboard.service", found)
        self.assertIn("steamos-utility-center-pegboard-resume.service", found)

    def test_each_link_is_claimed_by_the_installer_or_by_a_switch(self):
        found = self.enabled()
        loose = [path for path in mounts.PROJECT_FILES
                 if ".wants/" in path
                 and path not in checkup.SWITCHED
                 and os.path.basename(path) not in found]
        self.assertEqual(loose, [], "no installer enables these and no "
                                    "switch writes them, so the page calls "
                                    "them a fault for ever")

    def test_an_installer_enable_of_a_switched_one_asks_first(self):
        """Otherwise the installer is the switch, and the switch is not.

        One of the three is enabled by install.sh: the drives unit, where a
        record of the drives is already on the machine. That record is the
        switch itself, so the line is inside a condition on it. A line with
        no condition would turn the feature on at each install.
        """
        switched = set(os.path.basename(one) for one in checkup.SWITCHED)
        lines = io.open(os.path.join(REPO, "install.sh")).read().splitlines()
        checked = []
        for number, names in self.enables():
            for name in sorted(names & switched):
                before = "\n".join(lines[max(0, number - 6):number - 1])
                self.assertIn("if [[", before,
                              "%s is enabled with no condition, at line %d"
                              % (name, number))
                checked.append(name)
        self.assertEqual(checked, ["steamos-utility-center-mounts.service"],
                         "the drives unit is the one case")


class RunCopyToolboxTest(unittest.TestCase):
    """The copy made, and not the source of install.sh read.

    The update page offered one branch on an installed machine and four in
    the clone it came from. `git clone --depth 1 --branch X` implies
    --single-branch, so remote.origin.fetch in the copy named that one
    branch and no fetch could ever bring another.

    Every test above this one is a grep, and "the copy is a clone" passed
    while the copy was a clone of one branch.
    """

    HARNESS = os.path.join(REPO, "tests", "shell", "run-copy-toolbox.sh")

    def git(self, where, *args):
        done = subprocess.run(("git", "-C", where) + args,
                              capture_output=True, text=True)
        return done.stdout.strip()

    def source(self):
        """A clone shaped like a person's: one branch out, the rest as
        origin/*. That is what `git clone` leaves behind, and the copy takes
        the local branches only."""
        where = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, where, ignore_errors=True)
        src = os.path.join(where, "source")
        done = subprocess.run(["git", "clone", "--quiet", REPO, src],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return src, os.path.join(where, "copy")

    def branches(self, where):
        return sorted(
            set(self.git(where, "for-each-ref",
                         "--format=%(refname:strip=3)",
                         "refs/remotes/origin").split()) - {"HEAD"})

    def copy(self):
        src, dest = self.source()
        done = subprocess.run(["bash", self.HARNESS, src, dest],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return src, dest

    def test_the_harness_runs_the_real_function(self):
        """A harness that ran nothing would pass every test below it."""
        with open(os.path.join(REPO, "install.sh")) as handle:
            self.assertIn("\ncopy_toolbox()", handle.read())
        _src, dest = self.copy()
        self.assertTrue(os.path.isdir(os.path.join(dest, ".git")),
                        "the copy is not a clone at all")
        self.assertTrue(os.path.exists(os.path.join(dest, "install.sh")))

    def test_the_copy_knows_every_branch_its_source_knows(self):
        src, dest = self.copy()
        self.assertGreater(len(self.branches(src)), 1,
                           "this test needs a source with several branches")
        self.assertEqual(self.branches(dest), self.branches(src))

    def test_the_copy_is_not_pinned_to_one_branch(self):
        """The list above is right at the moment of the install. This is what
        keeps it right: a fetch from the remote brings every branch."""
        _src, dest = self.copy()
        self.assertEqual(self.git(dest, "config", "remote.origin.fetch"),
                         "+refs/heads/*:refs/remotes/origin/*")

    def test_the_menu_of_the_panel_reads_the_same_list(self):
        """The page asks ledpanel, so the test asks ledpanel."""
        sys.path.insert(0, os.path.join(REPO, "gui"))
        import ledpanel
        src, dest = self.copy()
        self.assertEqual(ledpanel.known_branches(dest),
                         ledpanel.known_branches(src))
        self.assertIn("experimental", ledpanel.known_branches(dest))

    def test_the_copy_still_points_at_the_remote_of_its_source(self):
        """A clone of the clone points at the directory a person deletes."""
        src, dest = self.copy()
        self.assertEqual(self.git(dest, "remote", "get-url", "origin"),
                         self.git(src, "remote", "get-url", "origin"))

    def test_the_copy_stays_shallow(self):
        """The whole point of the copy is that it is small."""
        _src, dest = self.copy()
        self.assertEqual(self.git(dest, "rev-parse",
                                  "--is-shallow-repository"), "true")

    def pinned(self):
        """A copy as an older installer left it, and a remote with branches.

        The remote is bare, which is the shape of the one on the network.
        The refs of a clone of a clone are its source's local branches, and
        that is not the case this is about.
        """
        where = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, where, ignore_errors=True)
        hub = os.path.join(where, "hub.git")
        for command in (["git", "clone", "--quiet", "--bare", REPO, hub],
                        ["git", "-C", hub, "branch", "-f", "debug",
                         "experimental"],
                        ["git", "clone", "--quiet", "--depth", "1",
                         "--branch", "experimental", "file://" + hub,
                         os.path.join(where, "copy")]):
            done = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
        return os.path.join(where, "copy")

    def test_a_copy_from_an_older_installer_is_mended_in_place(self):
        """install.sh runs from the copy once the clone is gone, and
        copy_toolbox returns before the clone in that case. So a reinstall
        cannot mend the refspec by making the copy again."""
        copy = self.pinned()
        self.assertNotEqual(self.git(copy, "config", "remote.origin.fetch"),
                            "+refs/heads/*:refs/remotes/origin/*")
        done = subprocess.run(["bash", self.HARNESS, copy, copy],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.git(copy, "config", "remote.origin.fetch"),
                         "+refs/heads/*:refs/remotes/origin/*")

    def test_a_pinned_copy_reaches_no_other_branch_before_that(self):
        """The refspec and not a missing fetch. Measured: a fetch on the
        pinned copy brings nothing new, however often it runs."""
        copy = self.pinned()
        subprocess.run(["git", "-C", copy, "fetch", "--quiet", "origin"],
                       capture_output=True, text=True)
        self.assertEqual(self.branches(copy), ["experimental"])

    def test_and_the_branches_arrive_at_the_next_check(self):
        copy = self.pinned()
        subprocess.run(["bash", self.HARNESS, copy, copy],
                       capture_output=True, text=True)
        done = subprocess.run(["git", "-C", copy, "fetch", "--quiet",
                               "--depth", "1", "origin"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("debug", self.branches(copy))
        self.assertIn("experimental", self.branches(copy))


class ToolboxCopyTest(unittest.TestCase):
    """The copy of this project that makes the clone something to throw away.

    The menu entry pointed into the clone, because the repair button re-runs
    install.sh and that only existed there. Everything the panel reaches for
    at run time is in the copy now.
    """

    def setUp(self):
        self.install = io.open(os.path.join(REPO, "install.sh")).read()
        self.shell = io.open(os.path.join(REPO, "scripts",
                                          "user-unit.sh")).read()

    def test_the_core_makes_the_copy(self):
        core = self.install.split("# --- the modules ---")[0]
        self.assertIn("copy_toolbox", core)
        self.assertIn('SOURCE_COPY="$INSTALL_DIR/source"', self.shell)

    def test_the_menu_entry_points_into_the_copy(self):
        """Into the copy and not into the clone, or deleting the clone takes
        the window with it."""
        said = self.install.split("install_control_panel()")[1]
        said = said.split("\n}")[0]
        self.assertIn("s|@SOURCE_DIR@|$SOURCE_COPY|g", said)
        self.assertNotIn("s|@SOURCE_DIR@|$SOURCE_DIR|g", said)

    def test_it_leaves_out_what_nothing_reads(self):
        """node_modules is 130 megabytes of another project's build, and the
        plugin ships the built dist beside it."""
        said = self.install.split("copy_toolbox()")[1].split("\n}")[0]
        for word in ("node_modules", ".git", "__pycache__"):
            self.assertIn("--exclude=%s" % word, said)

    def test_it_does_not_copy_the_copy_onto_itself(self):
        """install.sh runs from the copy after the clone is gone, and a
        remove of the copy from inside it would take the running script."""
        said = self.install.split("copy_toolbox()")[1].split("\n}")[0]
        self.assertIn('"$SOURCE_DIR" -ef "$SOURCE_COPY"', said)
        guard = said.split('-ef "$SOURCE_COPY"')[1].split("fi")[0]
        self.assertIn("return 0", guard)

    def test_the_copy_keeps_its_own_remote(self):
        """A clone of the clone points at the clone, which is the directory a
        person is about to delete. Updates would then find nothing."""
        said = self.install.split("copy_toolbox()")[1].split("\n}")[0]
        self.assertIn("remote set-url origin", said)
        self.assertIn("remote get-url origin", said)

    def test_the_uninstaller_takes_it(self):
        gone = io.open(os.path.join(REPO, "uninstall.sh")).read()
        self.assertIn('rm -rf "${INSTALL_DIR:?}"', gone)


if __name__ == "__main__":
    unittest.main()
