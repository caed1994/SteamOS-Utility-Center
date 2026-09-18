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


class LeftoverTest(unittest.TestCase):
    """Every file a module owns is reached when the module is taken off."""

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
        """
        whole = body.replace("\\\n", " ")
        return [line for line in whole.splitlines()
                if re.search(r"\brm\s+-[rf]", line)
                or "systemctl disable" in line]

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
        """It is off by default, and the dialog names it."""
        panel = io.open(os.path.join(REPO, "gui",
                                     "steamos-utility-center-panel")).read()
        body = panel.split("class RemoveDialog")[1].split("\nclass ")[0]
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


if __name__ == "__main__":
    unittest.main()
