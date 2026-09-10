# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Letting a controller wake this machine: scripts/wake-apply.sh and wake.py.

This was a switch on the HDMI CEC page, in the toolkit under cec-toolkit/,
because that toolkit needed it: the Steam button cannot reach a machine that
sleeps. The work is one value in sysfs and sends no CEC, so it is part of the
System module of this project now.

The tests on which radios it accepts came with it. The fault they are about is
in the class check, and it is worth keeping the record here: on a machine that
is not a Steam Deck all three of the methods can fail. A measurement on an AM5
board gave this:

    0e8d:0616 MediaTek Inc. Wireless_Device
    class=ef sub=02 proto=01

That id is not the Intel id in the list. The name of that Bluetooth radio does
not hold the word Bluetooth. And ef/02/01 is Interface Association, which
means "the classes are in the interfaces". Each combination wifi and Bluetooth
chip reports that class, so a check of the *device* class never matched one.
The program printed "matched":0 and gave no reason.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
PROGRAM = os.path.join(REPO, "scripts", "wake-apply.sh")
UNIT = os.path.join(REPO, "server", "steamos-utility-center-wake.service")

sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import ctl                       # noqa: E402
from steamos_utility_center import mounts                    # noqa: E402
from steamos_utility_center import wake                      # noqa: E402


class BusTest(unittest.TestCase):
    """A fake /sys/bus/usb/devices, and what the program does to it."""

    BLUETOOTH = ("e0", "01", "01")
    KEYBOARD = ("03", "01", "01")
    HUB = ("09", "00", "00")

    def _machine(self, where, devices, wakeup="disabled"):
        """A bus from {id: (name, [(class, sub, proto)])}.

        Interfaces are children of the device, which is where they really
        live: /sys/bus/usb/devices/1-12:1.0 is a symlink to a directory inside
        the one 1-12 points at. Interfaces as siblings would pass a test that
        the real bus fails.

        Every device gets the ef/02/01 device class, so nothing here matches
        by that class and the interfaces are what decide.
        """
        usb = os.path.join(where, "usb")
        for index, (usb_id, (name, interfaces)) in enumerate(devices.items()):
            port = "1-%d" % (index + 1)
            at = os.path.join(usb, port)
            os.makedirs(os.path.join(at, "power"), exist_ok=True)
            vendor, product = usb_id.split(":")
            written = {"idVendor": vendor, "idProduct": product,
                       "product": name, "manufacturer": "",
                       "bDeviceClass": "ef", "bDeviceSubClass": "02",
                       "bDeviceProtocol": "01", "power/wakeup": wakeup}
            for leaf, value in written.items():
                with open(os.path.join(at, leaf), "w") as handle:
                    handle.write(value + "\n")
            for number, (klass, sub, proto) in enumerate(interfaces):
                inside = os.path.join(at, "%s:1.%d" % (port, number))
                os.makedirs(inside, exist_ok=True)
                for leaf, value in (("bInterfaceClass", klass),
                                    ("bInterfaceSubClass", sub),
                                    ("bInterfaceProtocol", proto)):
                    with open(os.path.join(inside, leaf), "w") as handle:
                        handle.write(value + "\n")
        return usb

    def _run(self, word, usb, where, root=""):
        done = subprocess.run(
            ["bash", PROGRAM, word], capture_output=True, text=True,
            env=dict(os.environ, WAKE_SYSFS=usb, ROOT=root,
                     WAKE_STATE_FILE=os.path.join(where, "state")))
        return done

    def _ask(self, devices, word="status"):
        with tempfile.TemporaryDirectory() as where:
            usb = self._machine(where, devices)
            done = self._run(word, usb, where)
            self.assertEqual(done.returncode, 0, done.stderr)
            said = json.loads(done.stdout)
            return said["found"] if word == "status" else said


class MatchTest(BusTest):
    """Which radios it accepts."""

    def test_a_combo_chip_is_found_by_its_interface(self):
        """The whole point: the class it hides is one level down."""
        said = self._ask({"0e8d:0616": ("Wireless_Device", [self.BLUETOOTH])})
        self.assertEqual(said["matched"], 1)
        self.assertIn("0e8d:0616", said["devices"][0]["label"])

    def test_two_bluetooth_interfaces_on_one_chip_are_one_device(self):
        """A radio usually has several. It is still one thing to allow."""
        said = self._ask({"0e8d:0616": ("Wireless_Device",
                                        [self.BLUETOOTH, self.BLUETOOTH])})
        self.assertEqual(said["matched"], 1)

    def test_an_interface_that_is_not_bluetooth_is_not_enough(self):
        """A keyboard that wakes the machine is a machine that wakes itself."""
        said = self._ask({"24ae:9db6": ("Keyboard", [self.KEYBOARD])})
        self.assertEqual(said["matched"], 0)

    def test_a_hub_is_not_a_radio(self):
        said = self._ask({"1d6b:0002": ("xHCI Host Controller", [self.HUB])})
        self.assertEqual(said["matched"], 0)

    def test_a_machine_with_no_radio_says_so_rather_than_nothing(self):
        said = self._ask({})
        self.assertEqual(said["matched"], 0)
        self.assertEqual(said["devices"], [])

    def test_the_bus_it_reads_can_be_pointed_somewhere_else(self):
        """Which is the only reason any of the above can be tested at all."""
        with open(PROGRAM) as handle:
            self.assertIn('WAKE_SYSFS="${WAKE_SYSFS:-/sys/bus/usb/devices}"',
                          handle.read())

    def test_it_looks_at_the_interfaces_and_not_the_device_class_only(self):
        with open(PROGRAM) as handle:
            program = handle.read()
        self.assertIn("bInterfaceClass", program)
        self.assertIn("has_bluetooth_interface", program)


class WritingTest(BusTest):
    """What it writes, and what it puts back."""

    def test_asking_writes_nothing(self):
        """A question that changes the machine is not a question.

        The page asks this to say which radios were found, and it asks before
        a person turns anything on.
        """
        with tempfile.TemporaryDirectory() as where:
            usb = self._machine(
                where, {"0e8d:0616": ("Wireless_Device", [self.BLUETOOTH])})
            wakeup = os.path.join(usb, "1-1", "power", "wakeup")
            done = self._run("status", usb, where)
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(wakeup) as handle:
                self.assertEqual(handle.read().strip(), "disabled")
            self.assertFalse(os.path.exists(os.path.join(where, "state")))

    def test_applying_allows_the_radio_to_wake_the_machine(self):
        with tempfile.TemporaryDirectory() as where:
            usb = self._machine(
                where, {"0e8d:0616": ("Wireless_Device", [self.BLUETOOTH])})
            wakeup = os.path.join(usb, "1-1", "power", "wakeup")
            done = self._run("apply", usb, where)
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(wakeup) as handle:
                self.assertEqual(handle.read().strip(), "enabled")

    def test_switching_it_off_puts_the_setting_back(self):
        """`off` restores what was there. It does not force "disabled".

        A person can have a radio with wake permission from before this
        module. To switch this off is not a reason to take that away.
        """
        with tempfile.TemporaryDirectory() as where:
            usb = self._machine(
                where, {"0e8d:0616": ("Wireless_Device", [self.BLUETOOTH])},
                wakeup="enabled")
            wakeup = os.path.join(usb, "1-1", "power", "wakeup")
            self.assertEqual(self._run("apply", usb, where).returncode, 0)
            self.assertEqual(self._run("off", usb, where).returncode, 0)
            with open(wakeup) as handle:
                self.assertEqual(handle.read().strip(), "enabled")

    def test_switching_it_off_takes_away_what_it_gave(self):
        with tempfile.TemporaryDirectory() as where:
            usb = self._machine(
                where, {"0e8d:0616": ("Wireless_Device", [self.BLUETOOTH])})
            wakeup = os.path.join(usb, "1-1", "power", "wakeup")
            self.assertEqual(self._run("apply", usb, where).returncode, 0)
            self.assertEqual(self._run("off", usb, where).returncode, 0)
            with open(wakeup) as handle:
                self.assertEqual(handle.read().strip(), "disabled")

    def test_switching_it_off_twice_is_not_an_error(self):
        """The uninstaller runs this, and it can run on a machine that is off."""
        with tempfile.TemporaryDirectory() as where:
            usb = self._machine(where, {})
            self.assertEqual(self._run("off", usb, where).returncode, 0)
            self.assertEqual(self._run("off", usb, where).returncode, 0)

    def test_turning_it_on_without_the_unit_says_so(self):
        """Rather than write sysfs values that the next boot forgets."""
        with tempfile.TemporaryDirectory() as where:
            usb = self._machine(
                where, {"0e8d:0616": ("Wireless_Device", [self.BLUETOOTH])})
            done = self._run("on", usb, where, root=where)
            self.assertEqual(done.returncode, 1)
            self.assertIn("System module", done.stderr)
            with open(os.path.join(usb, "1-1", "power", "wakeup")) as handle:
                self.assertEqual(handle.read().strip(), "disabled")

    def test_a_word_it_does_not_know_is_refused(self):
        with tempfile.TemporaryDirectory() as where:
            done = self._run("sideways", self._machine(where, {}), where)
            self.assertEqual(done.returncode, 2)


class UnitTest(unittest.TestCase):
    """The unit that writes the values again at each boot."""

    def setUp(self):
        with open(UNIT) as handle:
            self.text = handle.read()

    def test_it_applies_and_does_not_switch_itself_on(self):
        """A unit that enables itself fights the switch that turned it off."""
        self.assertIn("steamos-utility-center-wake-apply apply", self.text)
        self.assertNotIn("-wake-apply on", self.text)

    def test_the_values_it_wrote_outlive_it(self):
        self.assertIn("RemainAfterExit=yes", self.text)

    def test_the_installer_fills_in_where_the_program_is(self):
        self.assertIn("@INSTALL_DIR@", self.text)

    def test_a_steamos_update_keeps_it(self):
        """/etc is rebuilt from the new image. See mounts.keep_list_text.

        The link is what says the switch is on, so an update that keeps the
        unit and loses the link is a machine that no longer wakes.
        """
        self.assertIn("/etc/systemd/system/steamos-utility-center-wake.service",
                      mounts.PROJECT_FILES)
        self.assertIn("/etc/systemd/system/multi-user.target.wants/"
                      "steamos-utility-center-wake.service",
                      mounts.PROJECT_FILES)


class ModuleTest(unittest.TestCase):
    """What the panel asks, and what it makes of the answer."""

    def test_the_switch_takes_two_words_and_no_others(self):
        self.assertEqual(wake.switch_command("on")[-2:],
                         [wake.APPLIER, "on"])
        with self.assertRaises(ValueError):
            wake.switch_command("apply")

    def test_the_switch_asks_for_no_password(self):
        """Game Mode has nobody to ask for one. See ctl.sudoers_text."""
        self.assertEqual(wake.switch_command("off")[:2], ["sudo", "-n"])

    def test_the_question_does_not_ask_for_a_password_at_all(self):
        """It reads sysfs and asks systemd. Neither needs rights."""
        self.assertNotIn("sudo", wake.status_command())

    def test_an_answer_that_is_not_an_answer_reads_as_nothing(self):
        self.assertEqual(wake.state("not json"), (None, []))
        self.assertIn("did not answer", wake.said(""))

    def _answer(self, on, radios):
        return json.dumps({"unit": wake.UNIT, "enabled": "enabled",
                           "is_enabled": on,
                           "found": {"matched": len(radios), "changed": 0,
                                     "devices": radios}})

    def test_a_radio_that_wakes_the_machine_is_said_so(self):
        said = wake.said(self._answer(True, [{"label": "Intel BT",
                                              "after": "enabled"}]))
        self.assertIn("Intel BT", said)
        self.assertIn("allowed to wake", said)

    def test_no_radio_at_all_is_a_different_answer(self):
        said = wake.said(self._answer(False, []))
        self.assertIn("No radio", said)

    def test_some_of_them_is_a_third_answer(self):
        said = wake.said(self._answer(True, [
            {"label": "Intel BT", "after": "enabled"},
            {"label": "MediaTek", "after": "disabled"}]))
        self.assertIn("1 of 2", said)

    def test_none_of_them_points_at_the_switch(self):
        said = wake.said(self._answer(False, [{"label": "Intel BT",
                                               "after": "disabled"}]))
        self.assertIn("Let a controller wake the machine", said)


class RuleTest(unittest.TestCase):
    """The sudoers rule for it."""

    def _lines(self):
        text = ctl.sudoers_text("deck", present=lambda path: True)
        return [line for line in text.splitlines()
                if line.startswith("deck") and "wake-apply" in line]

    def test_it_permits_the_two_words_and_no_more(self):
        lines = self._lines()
        self.assertEqual(len(lines), 2)
        words = sorted(line.split()[-1] for line in lines)
        self.assertEqual(words, ["off", "on"])

    def test_there_is_no_wildcard_in_it(self):
        """The rule this replaced named the program and a `*`."""
        for line in self._lines():
            self.assertNotIn("*", line)

    def test_a_machine_without_the_program_gets_no_line(self):
        text = ctl.sudoers_text("deck", present=lambda path: False)
        self.assertNotIn("wake-apply", text)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
