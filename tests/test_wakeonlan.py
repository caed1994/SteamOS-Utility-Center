# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The switch that lets a magic packet wake this machine.

Two halves, and they are checked apart because they fail apart.

scripts/wol-apply.sh runs against a /sys/class/net built in a directory and
an nmcli that this file writes, so the card it picks and the words it hands
NetworkManager are read rather than believed. Nothing here touches the
network of the machine it runs on.

wakeonlan.py turns that answer into a sentence and a switch. Its own rule is
the one that matters over time: the command it hands sudo is two words, the
connection is not one of them, and a rule that took a connection name would
need a wildcard, because "Wired connection 1" has spaces in it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import ctl, wakeonlan  # noqa: E402

APPLIER = os.path.join(REPO, "scripts", "wol-apply.sh")

# An nmcli that holds one value in a file, so the applier can be run without
# a NetworkManager and without a network.
FAKE_NMCLI = '''#!/usr/bin/env bash
STORE="${FAKE_STORE:?}"
[[ -f "$STORE" ]] || echo default > "$STORE"
echo "$*" >> "${FAKE_LOG:-/dev/null}"
case "$*" in
  "-t -f NAME,DEVICE connection show --active")
     cat "${FAKE_ACTIVE:?}" ;;
  "-t -f 802-3-ethernet.wake-on-lan connection show "*)
     printf '802-3-ethernet.wake-on-lan:%s\\n' "$(cat "$STORE")" ;;
  "connection modify "*" 802-3-ethernet.wake-on-lan "*)
     echo "${@: -1}" > "$STORE" ;;
  "connection down "*|"connection up "*) ;;
  *) echo "unexpected: $*" >&2; exit 9 ;;
esac
'''


class ApplierTest(unittest.TestCase):
    """The program, run against a machine made up in a directory."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.net = os.path.join(self.root, "net")
        self.nmcli = os.path.join(self.root, "nmcli")
        self.store = os.path.join(self.root, "store")
        self.log = os.path.join(self.root, "log")
        with open(self.nmcli, "w") as handle:
            handle.write(FAKE_NMCLI)
        os.chmod(self.nmcli, 0o755)
        self.active = os.path.join(self.root, "active")
        self.set_active("Wired connection 1:enp8s0", "lo:lo")

    def set_active(self, *lines):
        """What nmcli lists, one connection to a line.

        A file and not a word list. The name of an ordinary wired
        connection is "Wired connection 1", and anything that splits on
        whitespace asks NetworkManager for a connection called "Wired".
        """
        with open(self.active, "w") as handle:
            handle.write("".join(line + "\n" for line in lines))

    def card(self, name, kind="wired", wakeup="enabled"):
        where = os.path.join(self.net, name)
        os.makedirs(where, exist_ok=True)
        with open(os.path.join(where, "type"), "w") as handle:
            handle.write("772\n" if name == "lo" else "1\n")
        if kind != "virtual":
            os.makedirs(os.path.join(where, "device", "power"), exist_ok=True)
            with open(os.path.join(where, "device", "power", "wakeup"),
                      "w") as handle:
                handle.write(wakeup + "\n")
        if kind == "wireless":
            os.makedirs(os.path.join(where, "wireless"), exist_ok=True)

    def run_applier(self, word):
        place = dict(os.environ,
                     WOL_NET_SYSFS=self.net, WOL_NMCLI=self.nmcli,
                     FAKE_STORE=self.store, FAKE_LOG=self.log,
                     FAKE_ACTIVE=self.active)
        done = subprocess.run(["bash", APPLIER, word], capture_output=True,
                              text=True, env=place, timeout=30)
        return done

    def asked(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as handle:
            return [line.strip() for line in handle if line.strip()]

    def test_it_reports_a_card_that_is_not_armed(self):
        self.card("enp8s0")
        self.card("lo", kind="virtual")
        said = json.loads(self.run_applier("status").stdout)
        self.assertEqual(said["connection"], "Wired connection 1")
        self.assertEqual(said["device"], "enp8s0")
        self.assertEqual(said["stored"], "default")
        self.assertEqual(said["card"], "enabled")

    def test_on_sets_the_property_and_brings_the_connection_up(self):
        """The property alone does nothing until the connection comes up.

        NetworkManager writes it into the connection file and hands it to
        the card when the connection is activated. Somebody who switches
        this on and shuts the machine down right away would otherwise find a
        card that was never told.
        """
        self.card("enp8s0")
        self.assertEqual(self.run_applier("on").returncode, 0)
        with open(self.store) as handle:
            self.assertEqual(handle.read().strip(), "magic")
        asked = self.asked()
        self.assertTrue(any(one.startswith("connection modify") for one in asked))
        self.assertIn("connection down Wired connection 1", asked)
        self.assertIn("connection up Wired connection 1", asked)
        self.assertLess(asked.index("connection down Wired connection 1"),
                        asked.index("connection up Wired connection 1"))

    def test_off_puts_it_back(self):
        self.card("enp8s0")
        self.run_applier("on")
        self.assertEqual(self.run_applier("off").returncode, 0)
        with open(self.store) as handle:
            self.assertEqual(handle.read().strip(), "default")

    def test_a_radio_is_never_the_card_it_picks(self):
        """Waking over radio is not something these cards do, and a switch
        that says it does is a switch that lies."""
        self.card("wlan0", kind="wireless")
        self.set_active("Home wifi:wlan0")
        said = json.loads(self.run_applier("status").stdout)
        self.assertFalse(said["found"])

    def test_a_machine_with_no_cable_says_so_and_changes_nothing(self):
        self.card("wlan0", kind="wireless")
        self.set_active("Home wifi:wlan0")
        done = self.run_applier("on")
        self.assertNotEqual(done.returncode, 0)
        # Asking is how it finds out there is nothing to set this on.
        # Changing is what it must not do.
        changed = [one for one in self.asked()
                   if one.startswith(("connection modify", "connection down",
                                      "connection up"))]
        self.assertEqual(changed, [],
                         "it changed something on a machine with no cable")

    def test_it_takes_no_other_word(self):
        self.card("enp8s0")
        for word in ("", "magic", "apply", "on off"):
            done = self.run_applier(word)
            self.assertEqual(done.returncode, 2, "it accepted %r" % word)

    def test_a_connection_name_with_spaces_survives(self):
        """The name NetworkManager gives is "Wired connection 1" on an
        ordinary machine. A program that splits on whitespace would ask for
        a connection called "Wired"."""
        self.card("enp8s0")
        self.run_applier("on")
        self.assertTrue(any('"Wired connection 1"' in one or
                            "Wired connection 1" in one
                            for one in self.asked()))


class SwitchCommandTest(unittest.TestCase):
    """What is handed to sudo, which is the part a rule has to match."""

    def test_it_is_two_words(self):
        for state in ("on", "off"):
            said = wakeonlan.switch_command(state)
            self.assertEqual(said[:2], ["sudo", "-n"])
            self.assertEqual(said[2:], [wakeonlan.APPLIER, state])

    def test_no_other_word_is_offered(self):
        for state in ("status", "magic", "", None):
            with self.assertRaises(ValueError):
                wakeonlan.switch_command(state)

    def test_asking_needs_no_password(self):
        """Reading is an ordinary question. The first attempt at this asked
        the card through ethtool, which wants CAP_NET_ADMIN and answers a
        service running as a person with "operation not permitted"."""
        self.assertNotIn("sudo", wakeonlan.status_command())


class SudoersTest(unittest.TestCase):
    """The rule, which is the part that cannot have a wildcard in it."""

    def rule(self):
        here = {ctl.APPLY_WOL}
        return ctl.sudoers_text("deck", present=lambda path: path in here)

    def test_it_permits_the_two_words_and_nothing_else(self):
        lines = [one for one in self.rule().splitlines()
                 if one.startswith("deck ")]
        self.assertEqual(
            lines,
            ["deck ALL=(root) NOPASSWD: %s on" % ctl.APPLY_WOL,
             "deck ALL=(root) NOPASSWD: %s off" % ctl.APPLY_WOL])

    def test_there_is_no_wildcard_in_it(self):
        """A connection name in the rule would need one, because the name
        holds spaces. The program finds the connection itself instead.

        The lines that permit, and not the whole text: the comment above
        them explains that there is no wildcard and holds the character
        while doing so.
        """
        for line in self.rule().splitlines():
            if line.startswith("deck "):
                self.assertNotIn("*", line)

    def test_a_machine_without_the_module_gets_no_line(self):
        self.assertEqual(ctl.sudoers_text("deck", present=lambda path: False),
                         "")


class SentenceTest(unittest.TestCase):
    """What the page says, which is the difference a person wants."""

    def test_it_reads_the_answer(self):
        said = wakeonlan.state(json.dumps(
            {"found": True, "connection": "Wired connection 1",
             "device": "enp8s0", "stored": "magic", "card": "enabled"}))
        self.assertTrue(said["on"])
        self.assertEqual(said["device"], "enp8s0")

    def test_nothing_answering_is_not_the_same_as_off(self):
        """The page says different things about them."""
        self.assertIsNone(wakeonlan.state("")["on"])
        self.assertIsNone(wakeonlan.state("not json")["on"])
        self.assertIsNone(wakeonlan.state("[1,2,3]")["on"])
        self.assertIs(wakeonlan.state(json.dumps(
            {"found": True, "stored": "default"}))["on"], False)

    def test_the_connection_and_the_card_can_disagree(self):
        """The connection holds the wish and the card holds whether it was
        told. A person who switched this on and still cannot wake the
        machine wants exactly that."""
        said = wakeonlan.state(json.dumps(
            {"found": True, "connection": "Wired connection 1",
             "device": "enp8s0", "stored": "magic", "card": "disabled"}))
        sentence = wakeonlan.says(said)
        self.assertIn("disabled", sentence)
        self.assertIn("Restart", sentence)

    def test_no_cable_says_what_is_missing(self):
        sentence = wakeonlan.says(wakeonlan.state('{"found":false}'))
        self.assertIn("cable", sentence)


if __name__ == "__main__":
    unittest.main()
