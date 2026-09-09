# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Controller wake: cec-toolkit/bin/steamos-cec-steam-button.

This program sends One Touch Play to the television. That message tells a set
to come on, and the program has good reasons to send it: a person pressed the
Steam button, or a controller spoke again after it was quiet.

A suspend makes both of those look true. The sleep hook makes the television
dark, the controller goes quiet with the machine, and a last report from it
then reads as "a person picked this up". The wake goes out, the television
comes on again, and the machine stays asleep.

The tests below are on the bar that stops that.
"""

import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "..", "cec-toolkit", "bin",
                       "steamos-cec-steam-button")


def load():
    """The toolkit's program, imported despite having no .py on the end.

    sys.modules first: the program has a dataclass in it, and a dataclass
    reads the module of its own class while it is built.
    """
    loader = importlib.machinery.SourceFileLoader("steamos_cec_steam_button",
                                                  PROGRAM)
    spec = importlib.util.spec_from_loader("steamos_cec_steam_button", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["steamos_cec_steam_button"] = module
    loader.exec_module(module)
    return module


button = load()


class ButtonTest(unittest.TestCase):
    """A machine that is awake, and a marker no other test can reach.

    The marker matters: tests/test_cec_toolkit.py runs the real sleep hook,
    and that hook makes the real /run file. A test that reads the real path
    thus answers differently on its own and in the suite.
    """

    def setUp(self):
        button.SUSPENDING.clear()
        self.addCleanup(button.SUSPENDING.clear)
        self.folder = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, self.folder)
        self.marker = os.path.join(self.folder, "local-suspend")
        self.addCleanup(setattr, button, "LOCAL_SUSPEND_MARKER",
                        button.LOCAL_SUSPEND_MARKER)
        button.LOCAL_SUSPEND_MARKER = self.marker

    def _write_marker(self, age=0.0):
        with open(self.marker, "w"):
            pass
        self.addCleanup(os.unlink, self.marker)
        when = time.time() - age
        os.utime(self.marker, (when, when))


class SuspendBarTest(ButtonTest):
    """What the program answers when it is asked to wake the set."""

    def test_a_quiet_machine_lets_a_wake_through(self):
        self.assertFalse(button.suspend_in_progress())

    def test_logind_saying_sleep_stops_a_wake(self):
        button.SUSPENDING.set()
        self.assertTrue(button.suspend_in_progress())

    def test_logind_saying_awake_lets_a_wake_through_again(self):
        button.SUSPENDING.set()
        button.SUSPENDING.clear()
        self.assertFalse(button.suspend_in_progress())

    def test_the_file_of_the_sleep_hook_stops_a_wake(self):
        """The fallback for a machine with no dbus_next."""
        self._write_marker()
        self.assertTrue(button.suspend_in_progress())

    def test_an_old_file_does_not_stop_a_wake(self):
        """The window expires by itself, so nothing has to delete the file.

        A machine that wakes an hour later must get its television back.
        """
        self._write_marker(age=button.LOCAL_SUSPEND_WINDOW_SECONDS + 1)
        self.assertFalse(button.suspend_in_progress())

    def test_no_file_and_no_folder_is_not_an_error(self):
        button.LOCAL_SUSPEND_MARKER = os.path.join(self.folder, "no", "such")
        self.assertFalse(button.local_suspend_in_progress())


class ActivationTest(ButtonTest):
    """The bar, in the function that sends the messages."""

    def setUp(self):
        super().setUp()
        self.sent = []
        for name in ("raw_wake", "raw_active_source"):
            self.addCleanup(setattr, button, name, getattr(button, name))
        self.addCleanup(setattr, button, "cec_wake", button.cec_wake)
        self.addCleanup(setattr, button, "source_is_active",
                        button.source_is_active)
        self.addCleanup(setattr, button, "CEC_WAKE_RETRY_DELAYS",
                        button.CEC_WAKE_RETRY_DELAYS)
        button.raw_wake = lambda: self.sent.append("wake")
        button.raw_active_source = lambda: self.sent.append("active-source")
        button.source_is_active = lambda: False
        button.CEC_WAKE_RETRY_DELAYS = (0,)

    def _no_answer(self):
        """A cecd that fails, which is what makes the program keep trying."""
        class Result:
            returncode = 1
            stdout = ""
        button.cec_wake = lambda: Result()

    def test_a_wake_sends_nothing_while_the_machine_goes_to_sleep(self):
        self._no_answer()
        button.SUSPENDING.set()
        button.activate_source("short Steam-button press")
        self.assertEqual(self.sent, [])

    def test_a_wake_sends_its_messages_on_an_awake_machine(self):
        """A cecd that answers, and a set that comes on at the first try."""
        class Result:
            returncode = 0
            stdout = ""
        button.cec_wake = lambda: Result()
        answers = iter((False, True))
        button.source_is_active = lambda: next(answers, True)
        button.activate_source("short Steam-button press")
        self.assertEqual(self.sent, ["wake", "active-source"])

    def test_a_sleep_in_the_middle_stops_the_ladder(self):
        """The ladder runs for tens of seconds, so a suspend can start in it.

        A bar at the front only is not enough: the messages after the suspend
        are the ones that put the television back on.
        """
        self._no_answer()
        button.CEC_WAKE_RETRY_DELAYS = (0, 0, 0)

        def wake_then_sleep():
            self.sent.append("wake")
            button.SUSPENDING.set()

        button.raw_wake = wake_then_sleep
        button.activate_source("controller connected or resumed")
        self.assertEqual(self.sent.count("wake"), 1)
        self.assertNotIn("active-source", self.sent)


if __name__ == "__main__":
    unittest.main()
