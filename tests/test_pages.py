# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pages of the window that live in their own module.

The window was one class of five thousand lines. It is cut one page at a
time, and each page is a mixin: Panel inherits it, so every method stays a
method of the window and `self` stays the window. The tests that call those
methods on the panel thus need no change at all, which is what makes a cut
checkable by running the tests that already exist.

The shape has two ways of going wrong quietly, and both are read here:

- two mixins that define one name. Python takes the first in the list and
  says nothing, so a page silently loses a method to another page.
- a page that the window does not inherit. Its methods are then in a file
  that nothing reads, and the page is gone from the window.

The third thing is the import. A page cannot import the window, because the
window imports the page. gui/panelbase.py exists for what they share.
"""

import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GUI = os.path.join(REPO, "gui")
PANEL = os.path.join(GUI, "steamos-utility-center-panel")


def tree_of(path):
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def page_modules():
    """Every gui/page_*.py, as (name, the class in it)."""
    out = []
    for name in sorted(os.listdir(GUI)):
        if not name.startswith("page_") or not name.endswith(".py"):
            continue
        tree = tree_of(os.path.join(GUI, name))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        out.append((name, tree, classes))
    return out


def methods(node):
    return [n.name for n in node.body if isinstance(n, ast.FunctionDef)]


def panel_class():
    return next(n for n in tree_of(PANEL).body
                if isinstance(n, ast.ClassDef) and n.name == "Panel")


class PageModuleTest(unittest.TestCase):
    """What a page module has to look like to be a page of this window."""

    def test_there_is_at_least_one(self):
        """Without this the rest of the file passes by saying nothing."""
        self.assertTrue(page_modules(), "no gui/page_*.py at all")

    def test_each_holds_one_class(self):
        for name, _tree, classes in page_modules():
            self.assertEqual(len(classes), 1, "%s holds %d classes"
                             % (name, len(classes)))

    def test_each_class_is_one_the_window_inherits(self):
        """A page the window does not inherit is a page that is not there."""
        bases = set()
        for base in panel_class().bases:
            bases.add(ast.unparse(base))
        for name, _tree, classes in page_modules():
            want = "%s.%s" % (name[:-3], classes[0].name)
            self.assertIn(want, bases, "Panel does not inherit %s" % want)

    def test_no_two_pages_define_the_same_name(self):
        """Python takes the first mixin in the list and says nothing.

        So a name in two pages is a method that one of them loses, with no
        message at the moment it happens and none at the moment it matters.
        """
        seen = {}
        clash = []
        for name, _tree, classes in page_modules():
            for one in methods(classes[0]):
                if one in seen:
                    clash.append("%s: %s and %s" % (one, seen[one], name))
                seen[one] = name
        self.assertEqual(clash, [])

    def test_no_page_name_is_also_in_the_window(self):
        """The window is the last of the bases, so its own copy would win.

        A method left behind in Panel after a cut thus hides the one that
        moved, and the page reads as moved on every other measure.
        """
        mine = set(methods(panel_class()))
        for name, _tree, classes in page_modules():
            both = sorted(mine & set(methods(classes[0])))
            self.assertEqual(both, [], "%s and Panel both define %s"
                             % (name, both))

    def test_no_page_imports_the_window(self):
        """The window imports the page, so the page cannot import it back.

        What they share is in gui/panelbase.py.
        """
        for name, tree, _classes in page_modules():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("steamos-utility-center",
                                         alias.name, name)
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn("steamos-utility-center",
                                     node.module or "", name)

    def test_the_window_reads_its_measurements_from_panelbase(self):
        """One answer to how wide a card is, for the window and the pages."""
        panel = tree_of(PANEL)
        taken = set()
        for node in panel.body:
            if isinstance(node, ast.ImportFrom) and node.module == "panelbase":
                taken.update(alias.name for alias in node.names)
        self.assertIn("GROUP_GAP", taken)
        assigned = {node.targets[0].id for node in panel.body
                    if isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Name)}
        self.assertEqual(sorted(taken & assigned), [],
                         "the window assigns what it imports")


class CecPageTest(unittest.TestCase):
    """The first page that moved, and what it took with it."""

    def setUp(self):
        self.tree = tree_of(os.path.join(GUI, "page_cec.py"))
        self.cls = next(n for n in self.tree.body
                        if isinstance(n, ast.ClassDef))

    def test_it_took_the_whole_page(self):
        """Every method of the window with cec in its name is in it."""
        left = [one for one in methods(panel_class()) if "cec" in one.lower()]
        self.assertEqual(left, [])
        self.assertGreaterEqual(len(methods(self.cls)), 20)

    def test_it_makes_no_object_of_its_own(self):
        """A mixin. `self` is the window, and the window builds it."""
        self.assertNotIn("__init__", methods(self.cls))


class SystemPageTest(unittest.TestCase):
    """The second page that moved: the drives, controller wake and Decky.

    These are settings of the machine and not of a device this project
    drives. The LED bar has a strip and HDMI CEC has a television; this page
    has the computer.
    """

    def setUp(self):
        self.tree = tree_of(os.path.join(GUI, "page_system.py"))
        self.cls = next(n for n in self.tree.body
                        if isinstance(n, ast.ClassDef))

    def test_it_took_the_whole_page(self):
        """Every method of the three parts is in it, and none is left over."""
        left = [one for one in methods(panel_class())
                if any(word in one.lower()
                       for word in ("drive", "decky", "wake"))
                # The window keeps the switch for the wake after a resume.
                # That is a setting of the Power page and another feature:
                # it wakes the television and not the machine. See
                # cec-toolkit and scripts/resume-wake.sh.
                and "resume" not in one.lower()]
        self.assertEqual(left, [])
        self.assertGreaterEqual(len(methods(self.cls)), 19)

    def test_it_makes_no_object_of_its_own(self):
        self.assertNotIn("__init__", methods(self.cls))

    def test_the_columns_of_a_drive_moved_with_it(self):
        """A grid that one file lays out and another names is a grid that
        two files have to agree about."""
        assigned = {node.targets[0].id for node in self.tree.body
                    if isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Name)}
        for name in ("DRIVE_WHERE", "DRIVE_TYPE", "DRIVE_STATE",
                     "DRIVE_OWN", "DRIVE_REMOVE", "DRIVE_SPACER"):
            self.assertIn(name, assigned)
        with open(PANEL, encoding="utf-8") as handle:
            self.assertNotIn("\nDRIVE_WHERE = ", handle.read())

    def test_what_needs_root_stayed_in_the_window(self):
        """_run_privileged belongs to no page. The settings pages apply the
        LED and the CPU through it, and this page applies the drives."""
        self.assertIn("_run_privileged", methods(panel_class()))
        self.assertNotIn("_run_privileged", methods(self.cls))
        # And the page still reaches it, which the mixin is what makes true.
        with open(os.path.join(GUI, "page_system.py"), encoding="utf-8") as f:
            self.assertIn("self._run_privileged(", f.read())


if __name__ == "__main__":
    unittest.main()
