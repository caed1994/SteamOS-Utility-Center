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
PANEL_NAME = "steamos-utility-center-panel"
PANEL = os.path.join(GUI, PANEL_NAME)


def tree_of(path):
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def inherited():
    """What the window names as its bases, as {module: class}."""
    out = {}
    for base in panel_class().bases:
        said = ast.unparse(base)
        if "." in said:
            module, name = said.split(".", 1)
            out[module + ".py"] = name
    return out


def page_modules():
    """Every gui/page_*.py, as (name, its tree, [the mixin] + its widgets).

    The mixin is first, and it is the class the window inherits. A page can
    hold widget classes of its own beside it: page_gpu.py draws a fan curve
    and nothing else in the window has a curve to edit.
    """
    bases = inherited()
    out = []
    for name in sorted(os.listdir(GUI)):
        if not name.startswith("page_") or not name.endswith(".py"):
            continue
        tree = tree_of(os.path.join(GUI, name))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        mixin = [n for n in classes if n.name == bases.get(name)]
        rest = [n for n in classes if n.name != bases.get(name)]
        out.append((name, tree, mixin + rest))
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

    def test_each_holds_a_mixin_that_the_window_inherits(self):
        """A page the window does not inherit is a page that is not there."""
        bases = set()
        for base in panel_class().bases:
            bases.add(ast.unparse(base))
        for name, _tree, classes in page_modules():
            self.assertTrue(classes, "%s holds no class at all" % name)
            want = "%s.%s" % (name[:-3], classes[0].name)
            self.assertIn(want, bases, "Panel does not inherit %s" % want)

    def test_a_widget_class_beside_it_belongs_to_that_page(self):
        """A page keeps a widget class only where nothing else draws one.

        A second reader would make it a widget of the window, and a widget
        of the window belongs where the window can reach it without
        importing a page.
        """
        loose = []
        for name, _tree, classes in page_modules():
            for one in classes[1:]:
                for other in sorted(os.listdir(GUI)):
                    if other == name or not (other.endswith(".py")
                                             or other == PANEL_NAME):
                        continue
                    with open(os.path.join(GUI, other),
                              encoding="utf-8") as handle:
                        if "%s(" % one.name in handle.read():
                            loose.append("%s uses %s.%s"
                                         % (other, name, one.name))
        self.assertEqual(loose, [])

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


class NetworkPageTest(unittest.TestCase):
    """The third page that moved: the Nanoleaf devices on the network.

    Part of the core and not a module: an effect on one of them is an HTTP
    call to an address on the LAN, and pairing one needs no rights.
    """

    def setUp(self):
        self.tree = tree_of(os.path.join(GUI, "page_network.py"))
        self.cls = next(n for n in self.tree.body
                        if isinstance(n, ast.ClassDef))

    def test_it_took_the_whole_card(self):
        left = [one for one in methods(panel_class())
                if "nanoleaf" in one.lower() or "network" in one.lower()]
        self.assertEqual(left, [])
        self.assertGreaterEqual(len(methods(self.cls)), 16)

    def test_it_makes_no_object_of_its_own(self):
        self.assertNotIn("__init__", methods(self.cls))

    def test_every_call_to_a_device_stays_off_the_drawing_thread(self):
        """The reason this card has a method that no other page needs.

        One call costs a timeout of some seconds. _in_background moved with
        the card, because nothing else on the window calls a device.
        """
        self.assertIn("_in_background", methods(self.cls))
        self.assertNotIn("_in_background", methods(panel_class()))

    def test_the_columns_of_a_device_moved_with_it(self):
        assigned = {node.targets[0].id for node in self.tree.body
                    if isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Name)}
        for name in ("NET_NAME", "NET_WHERE", "NET_STATE", "NET_EFFECT",
                     "NET_SWITCH", "NET_SPACER", "NET_REMOVE"):
            self.assertIn(name, assigned)
        with open(PANEL, encoding="utf-8") as handle:
            self.assertNotIn("\nNET_NAME = ", handle.read())


class StatusPageTest(unittest.TestCase):
    """The fourth page that moved: what this machine has, and what is wrong.

    Every other page sets something. This one reads, and it is the page a
    person opens when something stopped working.
    """

    def setUp(self):
        self.tree = tree_of(os.path.join(GUI, "page_status.py"))
        self.cls = next(n for n in self.tree.body
                        if isinstance(n, ast.ClassDef))

    def test_it_took_the_whole_page(self):
        left = [one for one in methods(panel_class())
                if "status" in one.lower() or "part" in one.lower()]
        self.assertEqual(left, [])
        self.assertGreaterEqual(len(methods(self.cls)), 12)

    def test_it_makes_no_object_of_its_own(self):
        self.assertNotIn("__init__", methods(self.cls))

    def test_the_one_name_that_the_rest_of_the_window_calls(self):
        """refresh_status is called from the window and from two pages. A
        mixin is what keeps it one name on one object for all of them."""
        self.assertIn("refresh_status", methods(self.cls))
        said = []
        for name in sorted(os.listdir(GUI)):
            if not (name.endswith(".py") or name == "steamos-utility-center-panel"):
                continue
            if name == "page_status.py":
                continue
            with open(os.path.join(GUI, name), encoding="utf-8") as handle:
                if "self.refresh_status(" in handle.read():
                    said.append(name)
        self.assertIn("steamos-utility-center-panel", said)
        self.assertGreater(len(said), 1, "only the window calls it")

    def test_the_light_and_its_size_moved_together(self):
        """A size that one file names and another draws with is a size that
        two files have to agree about."""
        assigned = {node.targets[0].id for node in self.tree.body
                    if isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Name)}
        self.assertIn("STATUS_DOT", assigned)
        self.assertIn("_light", methods(self.cls))
        with open(PANEL, encoding="utf-8") as handle:
            self.assertNotIn("\nSTATUS_DOT = ", handle.read())

    def test_what_the_window_keeps_is_what_another_page_needs(self):
        """_forget_dead_labels is the graphics card's as well, and the three
        that fit the window are the window's layout and not this page's."""
        mine = methods(self.cls)
        for name in ("_forget_dead_labels", "_fit_window", "_refit",
                     "_ask_for_the_open_page"):
            self.assertIn(name, methods(panel_class()), name)
            self.assertNotIn(name, mine, name)


class GpuPageTest(unittest.TestCase):
    """The fifth page that moved: the graphics card, through LACT.

    The one page of this window that sets nothing of its own. LACT is
    another project's daemon and it owns the card.
    """

    def setUp(self):
        self.tree = tree_of(os.path.join(GUI, "page_gpu.py"))
        self.classes = [n for n in self.tree.body
                        if isinstance(n, ast.ClassDef)]
        self.cls = next(n for n in self.classes if n.name == "GpuPage")

    def test_it_took_the_whole_page(self):
        left = [one for one in methods(panel_class()) if "gpu" in one.lower()]
        self.assertEqual(left, [])
        self.assertGreaterEqual(len(methods(self.cls)), 14)

    def test_it_makes_no_object_of_its_own(self):
        self.assertNotIn("__init__", methods(self.cls))

    def test_the_curve_it_draws_came_with_it(self):
        """Nothing else in the window has a curve to edit, and a page cannot
        take a class out of the window.

        By the names in the tree and not by the text of the file: a search
        of the window's code puts six thousand lines into the failure.
        """
        self.assertIn("FanCurve", [n.name for n in self.classes])
        left = [node.name for node in tree_of(PANEL).body
                if isinstance(node, ast.ClassDef) and node.name == "FanCurve"]
        self.assertEqual(left, [])

    def test_the_width_it_shares_went_to_panelbase(self):
        """BRANCH_WIDTH was the name, and two of its three readers are not a
        branch. The window reads it as well, so it is a measurement."""
        base = tree_of(os.path.join(GUI, "panelbase.py"))
        assigned = {node.targets[0].id for node in base.body
                    if isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Name)}
        self.assertIn("ROW_FIELD_WIDTH", assigned)
        old, new = [], []
        for name in (PANEL, os.path.join(GUI, "page_gpu.py")):
            with open(name, encoding="utf-8") as handle:
                said = handle.read()
            if "BRANCH_WIDTH" in said:
                old.append(os.path.basename(name))
            if "ROW_FIELD_WIDTH" not in said:
                new.append(os.path.basename(name))
        self.assertEqual(old, [], "these still name the old width")
        self.assertEqual(new, [], "these do not read the new one")


class DialogModuleTest(unittest.TestCase):
    """The modal windows, which a page needs and cannot take from the window.

    The window imports each page, so a page that imported the window back
    would be a circle. gui/dialogs.py is what makes the Nanoleaf card
    possible: it opens two of them.
    """

    def setUp(self):
        self.tree = tree_of(os.path.join(GUI, "dialogs.py"))
        self.classes = [n for n in self.tree.body
                        if isinstance(n, ast.ClassDef)]

    def test_it_holds_the_base_and_the_ones_built_on_it(self):
        names = [n.name for n in self.classes]
        self.assertIn("Dialog", names)
        for one in self.classes:
            if one.name == "Dialog":
                self.assertEqual(one.bases, [])
            else:
                self.assertEqual([ast.unparse(b) for b in one.bases],
                                 ["Dialog"], one.name)

    def test_none_of_them_knows_what_the_window_is(self):
        """Each takes a widget as its parent and reads nothing else.

        The names in the code and not the words in the comments. The first
        version of this read the file as text and failed on the line of the
        docstring that says the same thing.
        """
        named = {node.id for node in ast.walk(self.tree)
                 if isinstance(node, ast.Name)}
        named |= {node.attr for node in ast.walk(self.tree)
                  if isinstance(node, ast.Attribute)}
        self.assertNotIn("Panel", named)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("steamos-utility-center", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("steamos-utility-center", node.module or "")

    def test_nothing_takes_a_name_out_of_this_module(self):
        """`import dialogs`, and never `from dialogs import Dialog`.

        A name taken out of the module is a copy that the file holds for
        itself. A test then has to replace it in each file that took one,
        and a replacement in the wrong file lets the real window open and
        wait for a press that no test makes. That is a suite that hangs
        instead of failing, and it cost forty minutes to find.

        Measured: the Nanoleaf card moved to a page of its own and two live
        tests went on replacing Dialog in the window. Both hung.
        """
        gui = os.path.join(GUI)
        bad = []
        for name in sorted(os.listdir(gui)):
            if not (name.endswith(".py")
                    or name == "steamos-utility-center-panel"):
                continue
            if name == "dialogs.py":
                continue
            for node in ast.walk(tree_of(os.path.join(gui, name))):
                if isinstance(node, ast.ImportFrom) and node.module == "dialogs":
                    bad.append("%s takes %s out of dialogs"
                               % (name, ", ".join(a.name for a in node.names)))
        self.assertEqual(bad, [])

    def test_the_window_holds_none_of_them_any_more(self):
        """A class left behind would be the one the window opens, and the
        module would be a file that nothing reads.

        By name and not by content: assertNotIn on the window's code puts
        six thousand lines into the failure, and the one name that matters
        is not in the part a terminal shows.
        """
        mine = {one.name for one in self.classes}
        left = sorted(node.name for node in tree_of(PANEL).body
                      if isinstance(node, ast.ClassDef) and node.name in mine)
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
