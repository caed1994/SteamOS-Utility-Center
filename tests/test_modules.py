# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The modules, and the one answer to "is this one installed".

install.sh installs the core. The LED bar, the CPU and GPU power, HDMI CEC and
the drives are modules, and three places ask about them: the installer, the
uninstaller and the control panel. This file examines the answer they share.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "gui"))

from steamos_utility_center import ctl                      # noqa: E402
from steamos_utility_center import modules                  # noqa: E402

INSTALLER = os.path.join(HERE, "..", "install.sh")
UNINSTALLER = os.path.join(HERE, "..", "uninstall.sh")
USER_UNIT = os.path.join(HERE, "..", "scripts", "user-unit.sh")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class RegistryTest(unittest.TestCase):
    """What the list holds, and what each entry says."""

    def test_every_module_has_the_three_sentences(self):
        """A person decides from these, so each module has all three.

        The page of the module and `./install.sh --modules` print the same
        text. A module with one of them missing is a page with a gap in it.
        """
        for name in modules.ORDER:
            said = modules.SAYS[name]
            for key in ("title", "does", "brings", "needs"):
                self.assertTrue(said.get(key), "%s has no %s" % (name, key))

    def test_the_words_are_in_one_place_only(self):
        """The installer prints them from here and does not carry a copy."""
        for said in modules.SAYS.values():
            self.assertNotIn(said["does"], _read(INSTALLER))

    def test_nothing_is_named_twice(self):
        self.assertEqual(len(set(modules.ORDER)), len(modules.ORDER))
        self.assertEqual(set(modules.SAYS), set(modules.ORDER))


class MarkTest(unittest.TestCase):
    """A module is present when its applier is present, and nothing else."""

    def test_the_mark_of_a_module_is_its_applier(self):
        """The same file the sudoers rule names.

        That is what makes the rule the list of installed modules. A mark of
        its own, beside the rule, would be a second answer that can disagree
        with the first.
        """
        self.assertEqual(modules.MARK[modules.LED], ctl.APPLY_CONFIG)
        self.assertEqual(modules.MARK[modules.POWER], ctl.APPLY_POWER)
        self.assertEqual(modules.MARK[modules.SYSTEM], ctl.APPLY_MOUNTS)

    def test_it_reads_the_machine_and_keeps_no_record(self):
        """No file says "the person asked for this".

        A record and a machine can disagree, and this project met that shape
        twice: the LACT status and the handover out of Game Mode. Both cost an
        evening.
        """
        self.assertNotIn("modules", _read(USER_UNIT).split("MODULE_DIR")[0:0]
                         or [""])
        self.assertNotIn("MODULE_DIR", _read(USER_UNIT))
        self.assertNotIn("MODULE_DIR", _read(INSTALLER))

    def test_a_present_hook_answers_for_a_machine_the_test_did_not_build(self):
        self.assertTrue(modules.installed(modules.LED,
                                          present=lambda path: True))
        self.assertFalse(modules.installed(modules.LED,
                                           present=lambda path: False))

    def test_here_gives_them_in_the_order_of_the_pages(self):
        answer = modules.here(present=lambda path: True)
        # HDMI CEC is not in it: it has no applier, and its own toolkit
        # answers for it. See installed().
        self.assertEqual(answer, tuple(name for name in modules.ORDER
                                       if name != modules.CEC))

    def test_hdmi_cec_answers_through_its_own_toolkit(self):
        """One answer and not two. See cec.installed."""
        with tempfile.TemporaryDirectory() as home:
            self.assertFalse(modules.installed(modules.CEC, home=home))
            where = os.path.join(home, ".local", "bin")
            os.makedirs(where)
            control = os.path.join(where, "steamos-cec-toolkitctl")
            with open(control, "w") as handle:
                handle.write("#!/bin/sh\n")
            os.chmod(control, 0o755)
            self.assertTrue(modules.installed(modules.CEC, home=home))


class StatusTest(unittest.TestCase):
    """The JSON surface reports which parts this machine has."""

    def test_the_cheap_half_carries_the_modules(self):
        """A front end asks for this again and again while a page is open.

        Each answer is one file that is there or is not, so it costs no
        process and belongs in the half that runs without one.
        """
        answer = ctl.status()
        self.assertIn("modules", answer)
        self.assertIsInstance(answer["modules"], list)
        for name in answer["modules"]:
            self.assertIn(name, modules.ORDER)

    def test_it_is_a_list_and_not_a_map_of_four_booleans(self):
        """A fifth module must not need a change in every front end."""
        self.assertIsInstance(ctl.status()["modules"], list)


class KnownTest(unittest.TestCase):
    """What the installer does with a name a person typed."""

    def test_a_name_that_is_not_a_module_comes_back_named(self):
        good, bad = modules.known(["led", "nope", "power"])
        self.assertEqual(good, ("led", "power"))
        self.assertEqual(bad, ("nope",))

    def test_one_name_twice_is_one_module(self):
        good, _bad = modules.known(["led", "led"])
        self.assertEqual(good, ("led",))

    def test_the_answer_reads_in_the_order_of_the_pages(self):
        good, _bad = modules.known(["system", "led"])
        self.assertEqual(good, ("led", "system"))


class InstallerTest(unittest.TestCase):
    """The installer's half: one pair of functions for each module."""

    def setUp(self):
        self.text = _read(INSTALLER)

    def test_each_module_has_an_install_and_a_remove(self):
        for name in modules.ORDER:
            self.assertIn("\ninstall_%s() {" % name, self.text, name)
            self.assertIn("\nremove_%s() {" % name, self.text, name)

    def test_the_loop_calls_them_by_name(self):
        """One loop, so a fifth module needs no fifth branch."""
        self.assertIn('"install_$name"', self.text)
        self.assertIn('"remove_$name"', self.text)

    def test_a_run_that_names_no_module_keeps_what_is_there(self):
        """The panel repairs an installation by running this script.

        A repair that started from an empty list would take every module off
        every machine that has one.
        """
        self.assertIn('MODULE_WANT["$name"]="${MODULE_ON[$name]}"', self.text)

    def test_a_run_that_names_one_module_touches_that_one(self):
        """Adding HDMI CEC must not stop and start the LED service."""
        self.assertIn("MODULE_TOUCH", self.text)
        self.assertIn('installing() { touching "$1" && want "$1"; }',
                      self.text)

    def test_the_led_questions_are_asked_by_the_led_module_only(self):
        """A core-only install asks nothing at all."""
        self.assertIn("if installing led; then", self.text)
        head = self.text[:self.text.index("if installing led; then")]
        self.assertNotIn("Number of LEDs on the strip", head)

    def test_the_sudoers_rule_is_written_after_the_modules(self):
        """It names one program for each installed module.

        A rule written before them would name the modules of the run before
        this one.
        """
        self.assertLess(self.text.index('"install_$name"'),
                        self.text.index("permit \"$WATCHER_USER\""))

    def test_the_module_list_comes_from_the_one_place_that_holds_it(self):
        """The scripts ask modules.py rather than keeping four paths of their
        own. This file exists because two copies of seven paths drifted."""
        shared = _read(USER_UNIT)
        self.assertIn("from steamos_utility_center import modules", shared)
        for name in modules.ORDER:
            self.assertNotIn('MODULE_ORDER=("%s"' % name, shared)

    def test_it_says_what_the_modules_are_with_no_root(self):
        """A question about the modules is not a change to the machine."""
        done = subprocess.run(["bash", INSTALLER, "--modules"],
                              capture_output=True, text=True,
                              cwd=os.path.join(HERE, ".."))
        self.assertEqual(done.returncode, 0, done.stderr)
        for name in modules.ORDER:
            self.assertIn(name, done.stdout)
            self.assertIn(modules.SAYS[name]["title"], done.stdout)

    def test_the_root_check_comes_after_that_question(self):
        self.assertLess(self.text.index("if [[ $LIST_MODULES -eq 1 ]]"),
                        self.text.index('[[ $EUID -eq 0 ]] || die'))


class WantedModulesTest(unittest.TestCase):
    """Which modules a set of options asks for, from the installer itself.

    Reported: removing the LED bar worked, and removing any other module
    afterwards put it back. The panel passes --flash 0 on every command it
    runs, which says "never touch the board". The installer read a value in
    --flash as a request for the LED module, so every such command asked for
    the module the person had just taken off.

    The same fault made "Rebuild and reinstall" reach the LED module and no
    other, because a run that names a module touches that module alone.

    This runs the real lines. A shape test on the text of the condition
    passes for a condition that reads the wrong variable.
    """

    def _wants(self, *options):
        """Runs the installer's option handling and returns its two answers.

        The copy ends where the decisions are made, before the first change
        to the machine, and its one test for root is taken out. Root is not
        needed to answer a question about the options, and a test that needed
        it would not run.

        It stands in a directory that carries the clone's own files, because
        the installer reads them from beside itself.
        """
        text = _read(INSTALLER)
        cut = text.index('dropping()   {')
        head = text[:text.index("\n", cut) + 1]
        head = head.replace('[[ $EUID -eq 0 ]] || die "run as root: '
                            'sudo ./install.sh"', ':')
        # if, and a last line that succeeds. The installer stops at the
        # first command that fails, and a module it does not touch is a
        # command that fails.
        head += ('\nfor name in "${MODULE_ORDER[@]}"; do\n'
                 '    if want "$name"; then printf \'want %s\\n\' "$name"; fi\n'
                 '    if touching "$name"; then printf \'touch %s\\n\' "$name"; fi\n'
                 'done\n'
                 'exit 0\n')
        root = os.path.join(HERE, "..")
        with tempfile.TemporaryDirectory() as room:
            for name in ("scripts", "server"):
                os.symlink(os.path.abspath(os.path.join(root, name)),
                           os.path.join(room, name))
            copy = os.path.join(room, "install.sh")
            with open(copy, "w", encoding="utf-8") as handle:
                handle.write(head)
            done = subprocess.run(["bash", copy] + list(options),
                                  capture_output=True, text=True, cwd=room)
        self.assertEqual(done.returncode, 0, done.stderr)
        said = done.stdout.split()
        return (set(said[at + 1] for at, word in enumerate(said)
                    if word == "want"),
                set(said[at + 1] for at, word in enumerate(said)
                    if word == "touch"))

    def test_removing_one_module_asks_for_no_other(self):
        wanted, touched = self._wants("--yes", "--flash", "0",
                                      "--without", "cec")
        self.assertNotIn("led", wanted)
        self.assertEqual(touched, {"cec"})

    def test_the_repair_reaches_every_module(self):
        """A bare run is the panel's "Rebuild and reinstall"."""
        wanted, touched = self._wants("--yes", "--flash", "0",
                                      "--rebuild-module")
        self.assertEqual(touched, set(modules.ORDER))
        self.assertNotIn("led", wanted)

    def test_a_firmware_name_still_asks_for_the_led_module(self):
        wanted, touched = self._wants("--yes", "--flash", "nodemcuv2",
                                      "--without", "cec")
        self.assertIn("led", wanted)

    def test_a_strip_length_still_asks_for_the_led_module(self):
        wanted, touched = self._wants("--yes", "--leds", "60")
        self.assertIn("led", wanted)
        self.assertIn("led", touched)

    def test_adding_one_module_asks_for_that_one(self):
        wanted, touched = self._wants("--yes", "--flash", "0", "--with", "led")
        self.assertIn("led", wanted)
        self.assertEqual(touched, {"led"})


class UninstallerTest(unittest.TestCase):
    """It removes every part, and the module state does not change that."""

    def setUp(self):
        self.text = _read(UNINSTALLER)

    def test_it_asks_nothing_about_the_modules(self):
        """"uninstall" is the word that means every part.

        A machine whose LED module was removed a year ago still has the
        kernel module and the settings, and this script takes them.
        """
        for word in ("MODULE_WANT", "installing ", "touching ", "--without"):
            self.assertNotIn(word, self.text, word)

    def test_it_removes_what_each_module_installs(self):
        for marker in ('rm -f "$UNIT_PATH"', 'rm -f "$POWER_UNIT_PATH"',
                       'rm -f "$MOUNTS_UNIT_PATH"', "remove_cec_toolkit",
                       "remove_decky_plugin", "remove_user_units",
                       'rm -f "$UDEV_PATH"', 'rm -f "$SLEEP_HELPER_PATH"',
                       'rm -f "$SUDO_RULE_PATH"'):
            self.assertIn(marker, self.text, marker)

    def test_the_appliers_go_with_the_install_directory(self):
        """One rm -rf covers each of them, whichever modules were there."""
        self.assertIn('rm -rf "${INSTALL_DIR:?}"', self.text)

    def test_the_shared_removals_have_one_body(self):
        """A module removal and this script take the same files off.

        A copy in each script is the copy that stops at a different point.
        """
        shared = _read(USER_UNIT)
        installer = _read(INSTALLER)
        for name in ("remove_user_units", "remove_mount_units",
                     "remove_cec_toolkit", "remove_decky_plugin"):
            self.assertIn("%s() {" % name, shared, name)
            self.assertNotIn("%s() {" % name, self.text, name)
            self.assertNotIn("%s() {" % name, installer, name)


if __name__ == "__main__":
    unittest.main()
