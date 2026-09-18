# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The python module this project carries, and the path that keeps it alive.

Three services of cec-toolkit import dbus_next at their first line: the two
that put the machine to sleep with the television, and the one that repairs
Gamescope after a wake. The module belongs neither to this project nor to
SteamOS, and SteamOS ships no pip.

A copy that a person installs by hand lands in the user site directory, and
the name of that directory holds the version of Python:
.local/lib/python3.14/site-packages. A SteamOS update that raises Python
leaves it behind. The three services then die at their first line, and each
of their units carries Restart=on-failure, so they sit in "activating" and
never reach "failed". Every switch on the HDMI CEC page goes on saying "on",
and nothing on the machine says a word.

That was measured: SteamOS went from Python 3.13 to 3.14 and all three
stopped. So the installer carries its own copy at a path with no version of
Python in it, and the tests here hold that path and the three scripts that
read it.
"""

import ast
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CARRIED = os.path.join(REPO, "dbus-next")

sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import cec, checkup  # noqa: E402

# The three that import it at their first line. steam-button is not one of
# them: it imports the module inside a try and has a path without it.
READERS = {"tv-standby": "steamos-cec-tv-standby-suspend",
           "input-away-suspend": "steamos-cec-input-away-suspend",
           "gamescope-recovery": "steamos-cec-gamescope-recovery"}


def record():
    """The values of dbus-next/ORIGIN, which is written as a shell file."""
    with open(os.path.join(CARRIED, "ORIGIN"), encoding="utf-8") as handle:
        return dict(re.findall(r"^([A-Z_][A-Z0-9_]*)=(.*)$",
                               handle.read(), re.M))


class ProvenanceTest(unittest.TestCase):
    """Where it came from, in a form somebody can act on."""

    def setUp(self):
        self.record = record()

    def test_it_names_the_file_it_came_from(self):
        """A wheel has no commit, so the record is the file and its sum."""
        self.assertTrue(self.record["ORIGIN_WHEEL"].startswith("https://"))
        self.assertTrue(self.record["ORIGIN_WHEEL"].endswith(".whl"))
        self.assertRegex(self.record["ORIGIN_SHA256"], r"^[0-9a-f]{64}$")

    def test_the_version_is_the_one_it_says(self):
        with open(os.path.join(CARRIED, "VERSION"), encoding="utf-8") as one:
            self.assertEqual(one.read().strip(),
                             self.record["ORIGIN_VERSION"])

    def test_the_wheel_it_names_is_the_version_it_names(self):
        self.assertIn(self.record["ORIGIN_VERSION"],
                      self.record["ORIGIN_WHEEL"])

    def test_it_keeps_the_licence_it_arrived_under(self):
        """MIT, and nothing here is changed, so no second copyright line."""
        with open(os.path.join(CARRIED, "LICENSE"), encoding="utf-8") as one:
            said = one.read()
        self.assertIn("MIT", said)
        self.assertIn("Tony Crisci", said)
        self.assertNotIn("caed1994", said)

    def test_the_module_is_there_and_imports(self):
        sys.path.insert(0, CARRIED)
        self.addCleanup(sys.path.remove, CARRIED)
        for module in ("dbus_next", "dbus_next.aio"):
            __import__(module)

    def test_it_carries_nothing_compiled(self):
        """One copy serves every Python 3 only while it is pure Python."""
        found = []
        for where, _dirs, names in os.walk(CARRIED):
            found += [name for name in names
                      if name.endswith((".so", ".pyd", ".dylib"))]
        self.assertEqual(found, [])


class InstalledPathTest(unittest.TestCase):
    """Where the installer puts it, and why that path and no other."""

    def test_the_path_holds_no_version_of_python(self):
        """That is the whole point of carrying it.

        .local/lib/python3.14/site-packages is the directory that the copy of
        a person lands in, and its name is why a raised Python loses it.
        """
        self.assertNotRegex(checkup.PYTHON_DIR, r"python\d")
        self.assertTrue(checkup.PYTHON_DIR.startswith(checkup.INSTALL_DIR))

    def test_the_installer_copies_it_there(self):
        with open(os.path.join(REPO, "install.sh"), encoding="utf-8") as one:
            body = one.read()
        self.assertIn('cp -r "$SOURCE_DIR/dbus-next/dbus_next" '
                      '"$PYTHON_DIR/"', body)

    def test_the_installer_records_the_version(self):
        """The Status page compares it with what the toolbox carries."""
        with open(os.path.join(REPO, "install.sh"), encoding="utf-8") as one:
            body = one.read()
        self.assertIn('"$SOURCE_DIR/dbus-next/VERSION"', body)
        self.assertIn('> "$PYTHON_VERSIONS"', body)

    def test_the_core_does_it_and_not_the_cec_module(self):
        """Where the modules go is a property of the machine.

        A module that arrives later finds them there. The copy is thus
        written before the first `install_led` of the script, which is where
        the modules begin.
        """
        with open(os.path.join(REPO, "install.sh"), encoding="utf-8") as one:
            body = one.read()
        self.assertLess(body.index('cp -r "$SOURCE_DIR/dbus-next/dbus_next"'),
                        body.index("install_led() {"))

    def test_the_two_names_agree_with_the_shell(self):
        with open(os.path.join(REPO, "scripts", "user-unit.sh"),
                  encoding="utf-8") as one:
            body = one.read()
        self.assertIn('PYTHON_DIR="$INSTALL_DIR/python"', body)
        self.assertIn('PYTHON_VERSIONS="$PYTHON_DIR/versions"', body)


class ReaderTest(unittest.TestCase):
    """The three scripts that have to find it."""

    def script(self, name):
        with open(os.path.join(REPO, "cec-toolkit", "bin", name),
                  encoding="utf-8") as handle:
            return handle.read()

    def appends(self, tree):
        """The line number of each sys.path.append and what it appends."""
        out = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            where = node.func
            if not isinstance(where, ast.Attribute) or where.attr != "append":
                continue
            if not isinstance(where.value, ast.Attribute) \
                    or where.value.attr != "path":
                continue
            if node.args and isinstance(node.args[0], ast.Constant):
                out[node.args[0].value] = node.lineno
        return out

    def imports_dbus(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) \
                    and (node.module or "").startswith("dbus_next"):
                return node.lineno
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("dbus_next"):
                        return node.lineno
        return None

    def test_each_one_adds_the_installed_path(self):
        for feature, name in READERS.items():
            tree = ast.parse(self.script(name))
            self.assertIn(checkup.PYTHON_DIR, self.appends(tree), feature)

    def test_it_adds_it_before_the_import(self):
        """After the import it is a line that runs too late to help."""
        for feature, name in READERS.items():
            tree = ast.parse(self.script(name))
            added = self.appends(tree)[checkup.PYTHON_DIR]
            self.assertLess(added, self.imports_dbus(tree), feature)

    def test_it_appends_and_does_not_insert(self):
        """A real installation of the module still wins.

        Somebody who installs a newer dbus_next gets that one, and the copy
        here is the floor and not the ceiling.
        """
        for feature, name in READERS.items():
            body = self.script(name)
            self.assertIn("sys.path.append", body, feature)
            self.assertNotIn("sys.path.insert", body, feature)

    def test_they_are_the_three_that_cec_names(self):
        """cec.NEEDS_DBUS and this list answer the same question."""
        self.assertEqual(sorted(READERS), sorted(cec.NEEDS_DBUS))

    def test_the_one_with_a_way_out_is_not_among_them(self):
        self.assertNotIn("steam-button", READERS)


class RunTest(unittest.TestCase):
    """The import, from the path the installer writes.

    A text test says the line is there. This says the line works.
    """

    def test_the_module_is_found_through_that_path(self):
        said = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.append(%r); import dbus_next;"
             "from dbus_next.aio import MessageBus; print(dbus_next.__file__)"
             % CARRIED],
            capture_output=True, text=True,
            env={"PATH": os.environ.get("PATH", ""),
                 "PYTHONPATH": "", "HOME": os.environ.get("HOME", "/root")})
        self.assertEqual(said.returncode, 0, said.stderr)
        self.assertIn("dbus_next", said.stdout)


if __name__ == "__main__":
    unittest.main()


class PanelSeesItTest(unittest.TestCase):
    """The panel reports the module as present when the services find it.

    cec.missing() is what puts "python dbus_next" on the HDMI CEC page as
    something the machine needs. It runs under the panel's own Python, and
    the panel does not append the carried directory the way the three
    services do. An import alone thus answers for the wrong program: it
    reports the module as missing on a machine where all three have it.
    """

    def setUp(self):
        self.where = os.path.join(checkup.PYTHON_DIR, "dbus_next")

    def test_the_two_names_are_one_answer(self):
        self.assertEqual(cec.PYTHON_DIR, checkup.PYTHON_DIR)

    def test_the_carried_copy_counts_as_present(self):
        said = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r);"
             "from steamos_utility_center import cec;"
             "import os;"
             "cec.os.path.isdir = lambda path: path == %r;"
             "print(cec._has_dbus_next())"
             % (os.path.join(REPO, "server"), self.where)],
            capture_output=True, text=True)
        self.assertEqual(said.returncode, 0, said.stderr)
        self.assertEqual(said.stdout.strip(), "True")

    def test_it_looks_at_the_directory_rather_than_importing_it(self):
        """The panel has no reason to load another project's module.

        The question is about three other programs, and an import here is a
        cost with nothing behind it.
        """
        with open(os.path.join(REPO, "server", "steamos_utility_center",
                               "cec.py"), encoding="utf-8") as handle:
            body = handle.read()
        where = body.index("def _has_dbus_next(")
        head = body[where:where + 1200]
        self.assertLess(head.index("os.path.isdir"), head.index("import dbus_next"))
