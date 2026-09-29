# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Whether a magic packet on the network can wake this machine.

Not the same thing as wake.py, which is whether a controller can wake it
over the USB bus. The names sit next to each other, so: this one is about
the network card, and the panel on the wall is what sends the packet. See
firmware/companion/main/panel_wol.c.

The whole setting is one property of one NetworkManager connection:

    802-3-ethernet.wake-on-lan <- magic

NetworkManager keeps that in the connection file, so unlike controller wake
it needs no unit that writes it again at each boot. What it does need is the
connection brought up again, because the property reaches the card then.
scripts/wol-apply.sh does that.

Reading it needs no rights at all, which is worth saying because the first
attempt at this went the other way. The ethtool call that asks the card
directly wants CAP_NET_ADMIN and answers "operation not permitted" to a
service running as a person. The NetworkManager property is an ordinary
question, and /sys/class/net/<card>/device/power/wakeup is an ordinary file,
so the page can show the state without asking for a password.
"""

from __future__ import annotations

import json
import os

# The same directory as ctl.INSTALL_DIR, spelled here for the reason wake.py
# gives: ctl imports this file.
INSTALL_DIR = "/var/lib/steamos-utility-center"
APPLIER = os.path.join(INSTALL_DIR, "steamos-utility-center-wol-apply")

# What the connection says when the card is told to listen. NetworkManager
# writes "default" for a connection that was never set, and a default that
# means "off" on every machine this runs on.
ARMED = "magic"


def installed(present=None):
    """Whether the program is on this machine."""
    present = os.path.exists if present is None else present
    return bool(present(APPLIER))


def switch_command(state):
    """The command that turns waking over the network on or off.

    Two words and no more, the same rule the other switches follow. ctl.py
    permits exactly these two, so a third word here is a command that asks
    for a password in Game Mode, where nothing can give one.

    The connection is not among them. A rule that took a connection name
    would need a wildcard, and the program finds the connection itself.
    """
    if state not in ("on", "off"):
        raise ValueError("state must be \"on\" or \"off\"")
    return ["sudo", "-n", APPLIER, state]


def status_command():
    """The command that asks what the connection and the card say.

    No sudo. Both questions are ones that anybody can ask, and a question
    that asks for a password is a question a person does not ask.
    """
    return [APPLIER, "status"]


def state(text):
    """Reads that answer.

    Returns a dictionary with:

        found       whether there is a wired connection to set this on
        on          whether the connection is set to wake on a magic packet
        connection  the name NetworkManager gives it
        device      the card
        card        what the card says about waking, as sysfs spells it

    `on` is None where nothing answered, because "the switch is off" and
    "nothing answered" are different states and the page says different
    things about them.
    """
    empty = {"found": False, "on": None, "connection": "", "device": "",
             "card": ""}
    try:
        said = json.loads(text)
        if not isinstance(said, dict):
            raise TypeError
    except (ValueError, TypeError):
        return empty
    if not said.get("found"):
        return empty
    stored = said.get("stored")
    return {
        "found": True,
        "on": stored == ARMED if isinstance(stored, str) else None,
        "connection": str(said.get("connection") or ""),
        "device": str(said.get("device") or ""),
        "card": str(said.get("card") or ""),
    }


def says(answer):
    """One line for the page about what the machine really holds.

    The connection and the card are two different answers. A person who
    switched this on and still cannot wake the machine wants the
    difference between them.
    """
    if not answer.get("found"):
        return "No wired card. Waking over the network needs a cable."
    where = answer.get("connection") or "the wired connection"
    if answer.get("on") is None:
        return "Cannot tell what %s is set to." % where
    if not answer["on"]:
        return "%s is not set to wake this machine." % where
    if answer.get("card") and answer["card"] != "enabled":
        # The connection holds the wish and the card holds whether it was
        # told. They disagree after a change that never reached the hardware.
        return ("%s asks for it, and the card says \"%s\". Restart to let "
                "NetworkManager tell it again." % (where, answer["card"]))
    return "%s wakes this machine on a magic packet." % where
