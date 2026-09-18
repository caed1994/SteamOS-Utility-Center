# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Whether a controller can wake this machine from sleep.

This is a setting of the machine and not of the television. The work is one
value in sysfs, on the USB device that receives the controller:

    /sys/bus/usb/devices/<device>/power/wakeup <- enabled

It came from the SteamOS CEC Toolkit. The toolkit needed it, because the
Steam button of a controller cannot reach a machine that sleeps, and so the
switch sat on the HDMI CEC page. There is no CEC in the work. A person with
no television can want a controller that wakes the machine, and a person who
removes HDMI CEC must not lose it.

It is part of the System module now. See scripts/wake-apply.sh for the
program, and modules.py for what a module is.
"""

from __future__ import annotations

import json
import os

# The same directory as ctl.INSTALL_DIR. It is spelled here and not imported,
# because ctl imports this file and a circle between the two is a circle for
# one string.
INSTALL_DIR = "/var/lib/steamos-utility-center"
APPLIER = os.path.join(INSTALL_DIR, "steamos-utility-center-wake-apply")
UNIT = "steamos-utility-center-wake.service"

# Where the applier records the values it changed, and what that record also
# says.
#
# scripts/wake-apply.sh writes one line for each USB device it changed, so
# that "off" can put the value back. The file is thus on the machine for
# exactly as long as the switch is on: "on" writes it and "off" removes it.
#
# That makes it the one answer in /var about a switch whose state is in /etc
# alone. /var is its own partition and a SteamOS update keeps it. See on().
STATE_PATH = os.path.join(INSTALL_DIR, "wake-state")


def on(root=""):
    """Whether the switch is on, from the record in /var.

    `systemctl is-enabled` answers the same question on a running machine and
    cannot answer it at a boot repair. It reads the link in /etc, and that
    link is the thing an update takes away.

    So a repair that read the link wrote it back: it could not tell "a person
    switched this off" from "an update took it", and it chose "on" both
    times. A switch that turns itself on again is worse than a switch that
    stays off. See checkup.SWITCHED.

    `root` is a directory in the tests and empty on a machine.
    """
    return os.path.exists(root + STATE_PATH)


def installed(present=None):
    """Whether the program is on this machine."""
    present = os.path.exists if present is None else present
    return bool(present(APPLIER))


def switch_command(state):
    """The command that turns controller wake on or off.

    Two words and no more. ctl.py permits exactly these two, so a third word
    here is a command that asks for a password in Game Mode, where nothing
    can give one. See ctl.sudoers_text.
    """
    if state not in ("on", "off"):
        raise ValueError("state must be \"on\" or \"off\"")
    return ["sudo", "-n", APPLIER, state]


def status_command():
    """The command that asks what the switch is, and what it matched.

    No sudo. It reads sysfs, which everybody can read, and asks systemd a
    question that needs no rights. A question that asks for a password is a
    question a person does not ask.
    """
    return [APPLIER, "status"]


def state(text):
    """Reads that answer. Returns (on, radios) and (None, []) for no answer.

    None and not False: "the switch is off" and "nothing answered" are
    different states, and the page says different things about them.
    """
    try:
        said = json.loads(text)
        radios = said["found"]["devices"]
        if not isinstance(radios, list):
            raise TypeError
        return bool(said["is_enabled"]), radios
    except (ValueError, TypeError, KeyError):
        return None, []


def said(text):
    """What that answer means, in one sentence for the page.

    Four answers, separated. "Found nothing" and "found a radio that already
    wakes the machine" are not one answer to "did it find my radio?".
    """
    on, radios = state(text)
    if on is None:
        return ("The controller wake program did not answer. Install the "
                "System module first, or look at what the command printed "
                "above.")
    if not radios:
        return ("No radio on the USB bus matched. One built into the board "
                "and not wired through USB cannot be switched on from here.")
    named = ", ".join(str(radio.get("label", "")).strip() or "an unnamed radio"
                      for radio in radios)
    waking = [radio for radio in radios if radio.get("after") == "enabled"]
    if len(waking) == len(radios):
        return "Found %s, allowed to wake this machine." % named
    if not waking:
        return ("Found %s. Nothing there can wake this machine yet - turn on "
                "\u201cLet a controller wake the machine\u201d above." % named)
    return ("Found %s, of which %d of %d can wake this machine."
            % (named, len(waking), len(radios)))
