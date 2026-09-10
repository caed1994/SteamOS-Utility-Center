# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The CEC module: the work of another project, forked, and kept complete.

This tree was a copy at one time, and the test here proved that the copy was
unchanged. It is no longer a copy, because this project corrected five faults
in it. See cec-toolkit/README.md. So the question is different now. Two
faults can occur with no message, and this file checks both.

A file goes missing. This project took the tree as a subtree, and the tree
installs itself from inside. A file that the installer needs, and that nobody
copied, looks correct here. It gives a broken install on a machine of a user.

The licence becomes difficult to find. This project cannot change the MIT
licence, and a fork with no record of its source is code with no history. The
record is ORIGIN. That file also makes "take the corrections of the source
project" a diff and not a guess.

No test here needs the network. The current state of the source project is
not available offline. The state of this tree is available, and this tree is
the half with the faults.
"""

import getpass
import json
import os
import re
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
CEC = os.path.join(REPO, "cec-toolkit")


def record(where=CEC):
    """The ORIGIN file, read the way a shell would read it."""
    values = {}
    with open(os.path.join(where, "ORIGIN")) as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
    return values


class ProvenanceTest(unittest.TestCase):
    """Where it came from, in a form somebody can act on."""

    def setUp(self):
        self.record = record()

    def test_it_names_where_it_came_from(self):
        self.assertTrue(self.record["ORIGIN_URL"].startswith("https://"))
        self.assertIn("steamos-cec-toolkit", self.record["ORIGIN_URL"])

    def test_it_names_a_commit_and_not_a_branch(self):
        # A branch name moves, so a fork recorded against one has no fixed
        # thing to be diffed from. Tags can be moved too, which is why the
        # commit is recorded beside the tag rather than instead of it.
        self.assertRegex(self.record["ORIGIN_COMMIT"], r"^[0-9a-f]{40}$")

    def test_the_version_says_it_is_not_upstream_any_more(self):
        # VERSION is what this tree calls itself, and it is installed and
        # reported as the toolkit's version. Reporting a bare upstream tag
        # would say this is a copy of a release it no longer is, which is the
        # one thing a bug report must not be wrong about.
        with open(os.path.join(CEC, "VERSION")) as handle:
            said = handle.read().strip()
        self.assertTrue(said.startswith(self.record["ORIGIN_TAG"]), said)
        self.assertNotEqual(said, self.record["ORIGIN_TAG"], said)

    def test_it_keeps_the_licence_it_arrived_under(self):
        # MIT, and it stays MIT. This project is GPL-3.0-or-later, and that
        # licence can hold MIT code. It cannot change the licence of another
        # copyright holder, and a fork does not change that rule.
        with open(os.path.join(CEC, "LICENSE")) as handle:
            said = handle.read()
        self.assertIn("MIT License", said)
        self.assertIn("contributors", said)     # upstream's, still there
        self.assertIn("caed1994", said)         # and ours, for the changes

    def test_its_readme_says_it_is_a_fork_and_whose(self):
        with open(os.path.join(CEC, "README.md")) as handle:
            said = handle.read()
        self.assertIn("fork", said.lower())
        self.assertIn("Twsts/steamos-cec-toolkit", said)
        self.assertIn("MIT", said)


class CompleteTest(unittest.TestCase):
    """Taking a subtree is where files get lost."""

    def _installers(self):
        for name in ("install.sh", "uninstall.sh"):
            with open(os.path.join(CEC, name)) as handle:
                yield name, handle.read()

    def test_every_file_the_installer_reaches_for_is_here(self):
        """The failure this is about happens on somebody else's machine.

        This project left out decky/ and assets/ on purpose. The plugin is a
        second front end for the same helper, and the assets are screenshots of
        that plugin. A file that the installer installs, and that this tree does
        not have, looks correct at the fork and gives a broken install later.
        """
        wanted = set()
        for _name, text in self._installers():
            wanted.update(re.findall(r"\$PROJECT_DIR/([A-Za-z0-9_./-]+)", text))
        self.assertTrue(wanted, "found no files to check - has the "
                                "installer stopped using $PROJECT_DIR?")
        for each in sorted(wanted):
            self.assertTrue(os.path.exists(os.path.join(CEC, each)),
                            "the installer installs %s and it is not here"
                            % each)

    def test_nothing_here_refers_to_what_was_left_out(self):
        for where, _dirs, files in os.walk(CEC):
            for name in files:
                if name in ("ORIGIN", "README.md"):
                    continue            # the two files whose job is to say so
                path = os.path.join(where, name)
                with open(path, "rb") as handle:
                    text = handle.read().decode("utf-8", "replace")
                for gone in ("$PROJECT_DIR/decky", "$PROJECT_DIR/assets"):
                    self.assertNotIn(gone, text, "%s wants %s" % (path, gone))

    def test_nothing_here_sends_people_to_upstreams_installer(self):
        """It would put the unfixed programs back.

        The docs said "repair by rerunning the latest installer" and pointed
        at upstream's release. That was right while this was an unmodified
        copy and is now a way to undo every fix in here.
        """
        for where, _dirs, files in os.walk(CEC):
            for name in files:
                if name == "ORIGIN":
                    continue            # names the URL, tells nobody to run it
                path = os.path.join(where, name)
                with open(path, "rb") as handle:
                    text = handle.read().decode("utf-8", "replace")
                self.assertNotIn("steamos-cec-toolkit-installer.sh", text,
                                 "%s sends people to upstream's installer"
                                 % path)

    def test_the_programs_it_installs_can_be_run(self):
        # install.sh copies these with `install -m 0755`, so this mode is not
        # the mode on disk. But a file in this tree with no execute bit cannot
        # run here. A developer must be able to run it here, and that is the
        # reason this tree is in the repository.
        for name in sorted(os.listdir(os.path.join(CEC, "bin"))):
            self.assertTrue(os.access(os.path.join(CEC, "bin", name), os.X_OK),
                            "%s is not executable" % name)

    def test_the_shell_in_it_parses(self):
        for name, _text in self._installers():
            done = subprocess.run(["bash", "-n", os.path.join(CEC, name)],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)


class InstalledAndRemovedTest(unittest.TestCase):
    """Every user file the installer writes, the uninstaller takes away.

    A unit left behind is not inert: it is enabled, so systemd goes on
    starting it at every login with the program it names already deleted.
    Both halves of that were true of boot-wake before the fork.
    """

    def setUp(self):
        with open(os.path.join(CEC, "install.sh")) as handle:
            self.install = handle.read()
        with open(os.path.join(CEC, "uninstall.sh")) as handle:
            self.uninstall = handle.read()

    def _installed_into_home(self, under, suffix=""):
        # Ends with the suffix, so `install -d` of a drop-in *directory*
        # called cec-audio-control.service.d is not mistaken for a unit.
        return set(name for name
                   in re.findall(r'"\$HOME/%s/([A-Za-z0-9_.-]+)"' % under,
                                 self.install)
                   if name.endswith(suffix))

    def test_every_user_program_is_removed_again(self):
        for name in sorted(self._installed_into_home(r"\.local/bin")):
            self.assertIn('rm -f "$HOME/.local/bin/%s"' % name,
                          self.uninstall, name)

    def test_every_user_unit_is_removed_again(self):
        for name in sorted(self._installed_into_home(r"\.config/systemd/user",
                                          ".service")):
            self.assertIn('rm -f "$HOME/.config/systemd/user/%s"' % name,
                          self.uninstall, name)

    def test_every_user_unit_is_disabled_before_it_is_deleted(self):
        # A deleted unit file leaves its enable symlink behind, and systemd
        # goes on trying to start something that is not there.
        for name in sorted(self._installed_into_home(r"\.config/systemd/user",
                                          ".service")):
            self.assertIn("systemctl --user disable --now %s" % name,
                          self.uninstall, name)


class SleepCostTest(unittest.TestCase):
    """What the sleep hook costs, run rather than read.

    systemd waits for steamos-cec-before-sleep on every suspend and on every
    shutdown, so each second in it is a second of both. The television it is
    slowest with is the one that answers nothing: nothing it asks comes back,
    and it used to wait for those answers anyway.

    This runs the real script against a cec-ctl that behaves that way. It is
    a clock test, so its limit is generous: the measurement was 1.6 seconds
    and the version before it took 3.3.
    """

    SILENT = """#!/bin/sh
for arg in "$@"; do
  case "$arg" in
    -S) printf '    Logical Address              : 4\\n'; exit 0 ;;
    --give-device-power-status) sleep 5; exit 0 ;;
  esac
done
exit 0
"""

    def _cost(self, stub):
        """Seconds one "pre" run takes with this cec-ctl standing in."""
        with tempfile.TemporaryDirectory() as room:
            fake = os.path.join(room, "cec-ctl")
            with open(fake, "w") as handle:
                handle.write(stub)
            os.chmod(fake, 0o755)
            # The script names the path, so the copy names the stand-in.
            with open(os.path.join(CEC, "bin",
                                   "steamos-cec-before-sleep")) as handle:
                text = handle.read().replace("/usr/bin/cec-ctl", fake)
            script = os.path.join(room, "before-sleep")
            with open(script, "w") as handle:
                handle.write(text)
            device = os.path.join(room, "cec0")
            open(device, "w").close()
            place = dict(os.environ)
            place.update({"STEAMOS_CEC_CONFIG": os.path.join(room, "none"),
                          # The script asks id -u for this name. Whoever
                          # runs the suite is a name that exists.
                          "STEAMOS_CEC_USER": getpass.getuser(),
                          "CEC_DEVICE": device})
            started = time.monotonic()
            subprocess.run(["bash", script, "pre"], env=place,
                           capture_output=True, timeout=60)
            return time.monotonic() - started

    def test_a_television_that_answers_nothing_is_not_waited_for(self):
        self.assertLess(self._cost(self.SILENT), 2.5)


class FixedHereTest(unittest.TestCase):
    """The six fixes, each of which was a workaround somewhere else first.

    Checked because each one is a single line or two in a file nobody reads
    often, and each one silently un-breaks a whole feature. A revert that
    passes every other test in this repository would be caught only here.
    """

    def _read(self, *parts):
        with open(os.path.join(CEC, *parts)) as handle:
            return handle.read()

    def test_something_puts_the_adapter_on_the_bus(self):
        program = self._read("bin", "steamos-cec-register")
        self.assertIn("--playback", program)
        self.assertIn("Logical Address Mask", program)
        unit = self._read("systemd", "user", "steamos-cec-register.service")
        # Before the wake paths. After them, the registration is too late.
        self.assertIn("Before=steamos-cec-boot-wake.service", unit)
        # oneshot, or Before= does not mean "finished before".
        self.assertIn("Type=oneshot", unit)
        # And installed and enabled for everybody: it is not a feature.
        install = self._read("install.sh")
        self.assertIn("systemctl --user enable steamos-cec-register.service",
                      install)

    def test_the_boot_wake_does_not_hold_the_session_up(self):
        unit = self._read("systemd", "user", "steamos-cec-boot-wake.service")
        self.assertIn("Type=simple", unit)
        self.assertNotIn("Type=oneshot", unit)

    def test_the_permissions_helper_waits_for_the_device(self):
        helper = self._read("bin", "steamos-cec-permissions-apply")
        self.assertIn("--wait", helper)
        unit = self._read("systemd", "system",
                          "steamos-cec-permissions.service")
        self.assertIn("--wait", unit)
        # But not as a oneshot: waiting there would hold multi-user.target.
        self.assertIn("Type=simple", unit)
        # The udev rule must not pass it, because udev stops a slow RUN+=.
        self.assertNotIn("--wait", self._read("udev",
                                              "70-steamos-cec-toolkit.rules"))

    def test_the_installer_works_out_where_the_machine_is_plugged_in(self):
        # CEC_PHYSICAL_ADDRESS is what lets a wake broadcast <Active Source>,
        # which is the message that switches the television's input over.
        # Nothing used to write it, so waking turned the set on and left it
        # where it was.
        self.assertIn("CEC_PHYSICAL_ADDRESS",
                      self._read("bin", "steamos-cec-register"))
        self.assertIn("steamos-cec-register", self._read("install.sh"))

    def test_the_standby_before_sleep_runs_once(self):
        """The unit or the system-sleep hook, and never both.

        The switch installed both, and both run the same helper. systemd ran
        the unit before sleep.target and then the hook from
        systemd-suspend.service, so each suspend sent the standby twice and
        cost twice the time. A shutdown ran the unit only, because systemd
        runs no system-sleep hook there.
        """
        control = self._read("bin", "steamos-cec-power-standby-control")
        # The unit is the one that stays: it covers a suspend and a shutdown.
        self.assertIn('systemctl enable "$UNIT"', control)
        self.assertNotIn('ln -sf "$HELPER" "$HOOK"', control)
        unit = self._read("systemd", "system",
                          "steamos-cec-before-sleep.service")
        self.assertIn("WantedBy=sleep.target shutdown.target", unit)

    def test_a_hook_from_an_earlier_install_is_taken_away(self):
        """Or the second run continues on a machine that updates.

        Three places remove it: the switch, so turning the feature on repairs
        the machine; the installer, so an update repairs it without the
        switch; and the uninstaller, which named a path this toolkit never
        wrote and left the hook as a symlink to a helper that was gone.
        """
        hook = "/etc/systemd/system-sleep/steamos-cec-before-sleep"
        control = self._read("bin", "steamos-cec-power-standby-control")
        self.assertEqual(control.count('rm -f "$HOOK"'), 2, "on and off")
        self.assertIn('HOOK="%s"' % hook, control)
        for name in ("install.sh", "uninstall.sh"):
            self.assertIn("rm -f %s" % hook, self._read(name), name)

    def test_the_settle_time_is_not_two_seconds_on_every_suspend(self):
        """It is on each suspend and each shutdown, so it is short.

        cec-ctl returns once the adapter sent the message, and a television
        acknowledges CEC in milliseconds. The wait is for the set to act on
        it before the HDMI link goes away.
        """
        helper = self._read("bin", "steamos-cec-before-sleep")
        self.assertIn("TV_STANDBY_SETTLE_SECONDS:-0.5", helper)
        # And named in the file, or nobody can raise it for a slow set.
        self.assertIn("TV_STANDBY_SETTLE_SECONDS",
                      self._read("config",
                                 "steamos-cec-toolkit.conf.example"))

    def test_the_bus_calls_cannot_hold_the_suspend(self):
        """busctl waits 25 seconds for a method call by default.

        Two calls go to the cecd of Steam. A daemon that is not there fails at
        once, and a daemon that stopped answering held the suspend for 50
        seconds. The calls are an attempt: the cec-ctl messages below them do
        the same work.
        """
        helper = self._read("bin", "steamos-cec-before-sleep")
        self.assertEqual(helper.count("busctl --user --timeout="), 2)
        self.assertNotIn("busctl --user call", helper)
        # Half a second each, and not the two it was. A daemon that is there
        # answers in milliseconds, so a working machine pays nothing for this.
        self.assertIn("BUSCTL_TIMEOUT=0.5", helper)

    def test_the_bus_calls_are_skipped_with_no_session_to_call(self):
        """On a shutdown the session of that user is often gone. Each call is
        then a runuser and a busctl that start, find nothing and stop, and
        that is a tenth of a second for an answer one path already holds.
        """
        helper = self._read("bin", "steamos-cec-before-sleep")
        self.assertIn("session_bus_is_there", helper)
        self.assertIn('[[ -S "/run/user/$STEAMOS_CEC_UID/bus" ]]', helper)
        self.assertIn('&& session_bus_is_there; then', helper)

    def test_the_standby_stops_when_the_television_says_it_is_off(self):
        """It sent standby six times over about three seconds whatever the
        set did, because different sets listen to different ones of the six.
        A set that answers GIVE_DEVICE_POWER_STATUS can end that at the first
        one: one measured television answered in 23 milliseconds.
        """
        helper = self._read("bin", "steamos-cec-before-sleep")
        self.assertIn("--give-device-power-status", helper)
        self.assertIn("television_is_off", helper)
        # The code and not the word. cec-ctl prints "standby (0x01)", and a
        # code does not change with the wording of a release.
        self.assertIn('(0x01)', helper)
        self.assertIn('(0x03)', helper)

    def test_the_broadcast_goes_out_before_anything_can_stop_early(self):
        """A television that is off is not a receiver that is off. The
        broadcast is what an AV receiver listens to.
        """
        helper = self._read("bin", "steamos-cec-before-sleep")
        broadcast = helper.index("send_native_standby 15")
        asking = helper.index("television_is_off || said=")
        self.assertLess(broadcast, asking)

    def test_a_set_that_says_nothing_is_asked_one_time_only(self):
        """cec-ctl waits about a second for a reply that is not coming, and
        this is on each suspend and each shutdown. Such a set must pay that
        one time and then get the ladder it always got.
        """
        helper = self._read("bin", "steamos-cec-before-sleep")
        self.assertIn("asking=0", helper)
        self.assertIn("POWER_STATUS_TIMEOUT", helper)
        # And a way to stop asking at all, for a set that never answers.
        self.assertIn('[[ "$POWER_STATUS_TIMEOUT" != "0" ]] || return 2',
                      helper)
        self.assertIn("POWER_STATUS_TIMEOUT",
                      self._read("config", "steamos-cec-toolkit.conf.example"))

    def test_every_message_has_a_limit_on_it(self):
        """The suspend and the shutdown wait for this script, so a call that
        does not return holds the machine for the whole limit of the unit.

        The question about the power state was the one call with a limit.
        Each other one went straight to cec-ctl. See cec_ctl.
        """
        helper = self._read("bin", "steamos-cec-before-sleep")
        loose = [line.strip() for line in helper.split("\n")
                 if "/usr/bin/cec-ctl" in line and "timeout" not in line]
        self.assertEqual(loose, [], "these calls have no limit")

    def test_a_set_that_says_nothing_does_not_wait_for_an_answer(self):
        """The ladder waits before each further try, and it waits to leave
        the television time to answer. A set that answers nothing has no
        answer coming, so those waits bought two seconds of nothing on each
        suspend and each shutdown.
        """
        helper = self._read("bin", "steamos-cec-before-sleep")
        self.assertIn('[[ "$asking" == "1" ]] || rounds="0"', helper)
        self.assertIn("for delay in $rounds; do", helper)

    def test_the_question_cannot_end_the_script_by_itself(self):
        """This file runs under `set -e`, where a command that returns
        non-zero on a line of its own ends the script. A television that
        answers "on" would then stop the suspend before the ladder ran.
        """
        helper = self._read("bin", "steamos-cec-before-sleep")
        called = [line.strip() for line in helper.split("\n")
                  if line.strip().startswith("television_is_off")
                  and not line.strip().endswith("() {")]
        self.assertTrue(called, "nothing calls it")
        for line in called:
            self.assertIn("||", line, line)

    def test_the_unit_cannot_hold_the_machine_for_a_minute_and_a_half(self):
        """The suspend and the shutdown wait for this unit, and without a
        limit of its own it gets the default of the machine. One cec-ctl that
        does not return then holds the machine for that long.
        """
        unit = self._read("systemd", "system",
                          "steamos-cec-before-sleep.service")
        found = re.search(r"^TimeoutStartSec=(\d+)$", unit, re.M)
        self.assertIsNotNone(found, "the unit has no limit of its own")
        # Room for the messages it sends, which take about three seconds, and
        # not room for a minute of nothing.
        self.assertLessEqual(int(found.group(1)), 30)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
