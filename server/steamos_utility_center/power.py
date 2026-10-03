# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""How the CPU balances speed against power, and how to change it.

There are two settings, and they are not independent.

The *governor* controls the clock. The *EPP*, the energy performance
preference, is a hint to the firmware about the position in its range. The
cpufreq driver decides which of the two exists. The two families behave in the
same way:

    amd-pstate / intel_pstate, active   performance and powersave, plus an EPP
    amd-pstate / intel_cpufreq, passive the classic governors, usually no EPP
    acpi-cpufreq and older              the classic governors, no EPP at all

No part of this module is written for one manufacturer. Each line except
driver_mode uses the generic cpufreq files, and driver_mode reads a file that
only AMD publishes.

It keeps no list of its own. It reads each available value from sysfs at the
moment of the question, so a machine with neither setting gets a page that
says so.

One interaction is important. Under the `performance` governor the firmware is
at its highest preference and the EPP file refuses each other value. See
epp_applies.

Nothing here writes. To apply a setting needs root, and that is in
steamos-utility-center-power. `text()` builds the text of the file for a
caller that stages it, and opens no file itself.
"""

from __future__ import annotations

import glob
import os

CPUFREQ = "/sys/devices/system/cpu/cpu*/cpufreq"
PSTATE_STATUS = "/sys/devices/system/cpu/amd_pstate/status"

DRIVER = "scaling_driver"
GOVERNOR = "scaling_governor"
GOVERNORS_AVAILABLE = "scaling_available_governors"
EPP = "energy_performance_preference"
EPP_AVAILABLE = "energy_performance_available_preferences"

# How this project writes "leave it alone". It is the absence of a setting and
# not a value that the setting can take. The keyboard layout uses the same
# method. A machine with nothing set here is the normal machine, and this
# project must have no opinion about the CPU until a person asks for one.
UNSET = ""

# The governor that fixes the firmware at its highest preference. The EPP file
# refuses a write while this governor is set. It has a name because two places
# must agree about it: the panel, which makes the EPP menu grey, and the
# program that applies the setting, which does not count that refusal as a
# failure.
PINNED_GOVERNOR = "performance"

# The values that the drivers with an EPP give, for the one moment when the
# machine does not answer.
#
# While the fixing governor is set, the kernel reduces
# energy_performance_available_preferences to that one value. A change away
# from that governor in the same session would then select from a list of one.
#
# These five are the values of amd-pstate and of intel_pstate together. This
# list is used only while the reported one is wrong.
PINNED_FALLBACK = ("default", "performance", "balance_performance",
                   "balance_power", "power")

DEFAULTS = {
    "CPU_GOVERNOR": UNSET,
    # Not UNSET. This project writes the preference only with a governor. See
    # epp_in_play. There is thus no case in which "leave the file alone" has a
    # meaning here. Either this project manages the CPU and sets both values,
    # or it does not and writes neither.
    "CPU_EPP": "default",
}

# The words for the values of these files, for a display to a person. This
# table has an entry only where the kernel's own word is not clear.
#
# "powersave" reads as a mode for a battery. On amd-pstate in active mode it is
# the normal mode: it is the setting that lets the firmware use its full range.
# `performance` is the setting that fixes the firmware at one point.
LABELS = {
    "powersave": "Powersave - the firmware picks the clock",
    "performance": "Performance - hold the top of the range",
    "default": "Driver's default",
    "balance_performance": "Lean towards performance",
    "balance_power": "Lean towards power saving",
    "power": "Power saving",
}


CONFIG_PATH = "/etc/steamos-utility-center-power.conf"


def read(path=CONFIG_PATH):
    """The settings file as {key: value}, with a default for what it omits.

    A file that is not there is not an error. It is a machine on which nobody
    set the CPU, and the defaults say exactly that.

    The parser is small on purpose. This file is also an EnvironmentFile of a
    systemd unit, so its shape is KEY=value and nothing more.
    """
    values = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sign, value = line.partition("=")
        if sign and name.strip() in values:
            values[name.strip()] = value.strip().strip("\"'")
    return values


def text(values):
    """Those settings as the text of the file, in a fixed order.

    A fixed order, so that two writes of the same settings give the same file
    and a difference in it is a difference of the settings.
    """
    lines = ["%s=%s" % (key, values.get(key, DEFAULTS[key]))
             for key in sorted(DEFAULTS)]
    return "\n".join(lines) + "\n"


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def policies(root=""):
    """Returns each cpufreq policy directory, sorted. Empty with no cpufreq.

    It returns each CPU and not the first CPU. There is one set of files for
    each policy. A machine with a write to cpu0 only would run its cores under
    different governors, and the screen would not say so.
    """
    return sorted(glob.glob(root + CPUFREQ))


def driver(root=""):
    """Returns the cpufreq driver: intel_pstate, amd-pstate-epp, and others.

    This is the generic answer and the first line of a report. Each machine
    with cpufreq has this file. amd_pstate/status exists on one family only. A
    report from that file alone told an Intel machine what it was not.
    """
    found = policies(root)
    if not found:
        return ""
    return _read(os.path.join(found[0], DRIVER))


def driver_mode(root=""):
    """Returns the amd_pstate mode, or "" on a machine without amd_pstate.

    AMD alone publishes its mode under this name. On Intel the difference is
    in the name of the driver: intel_pstate is active, intel_cpufreq is the
    same driver in passive mode. So this is reported beside driver() and not
    in place of it.

    Worth a report: the two modes give different governors, and only one of
    them has an EPP.
    """
    return _read(root + PSTATE_STATUS)


def _offered(name, root=""):
    """Returns the values that one cpufreq file accepts, from policy 0."""
    found = policies(root)
    if not found:
        return ()
    return tuple(_read(os.path.join(found[0], name)).split())


def governors(root=""):
    return _offered(GOVERNORS_AVAILABLE, root)


def epp_values(root=""):
    """Returns the values that the preference accepts under a governor.

    Not the current content of the file. While the fixing governor runs, the
    kernel reduces that list to one value, and a read of it answers "what can
    I select now".

    The question here is "what can I select after I apply the governor I am
    about to apply".
    """
    reported = _offered(EPP_AVAILABLE, root)
    if not reported:
        return ()                       # no EPP on this machine at all
    if epp_applies(current(root).get("CPU_GOVERNOR", "")):
        return reported
    return PINNED_FALLBACK


def epp_in_play(values, root=""):
    """Returns whether the preference is a setting, for these values.

    Three conditions make it not a setting, and each means the same to every
    caller: do not offer it, do not validate it, do not write it.

    A machine with no governor of ours, because this project must not set one
    half of the CPU. The fixing governor, under which the kernel refuses the
    file. A driver that has no such file.
    """
    if values.get("CPU_GOVERNOR", UNSET) == UNSET:
        return False
    if not epp_applies(values.get("CPU_GOVERNOR", UNSET)):
        return False
    return bool(epp_values(root))


def current(root=""):
    """Returns the current settings as {key: value}. "" if unreadable."""
    found = policies(root)
    if not found:
        return {"CPU_GOVERNOR": UNSET, "CPU_EPP": UNSET}
    return {"CPU_GOVERNOR": _read(os.path.join(found[0], GOVERNOR)),
            "CPU_EPP": _read(os.path.join(found[0], EPP))}


def available(root=""):
    """Returns each value that a page needs, in one read of the machine."""
    return {
        "driver": driver(root),
        "mode": driver_mode(root),
        "governors": governors(root),
        "epp": epp_values(root),
        "policies": len(policies(root)),
        "current": current(root),
    }


def epp_applies(governor):
    """Returns whether the EPP reaches the firmware under this governor.

    It returns False under `performance`. The kernel then fixes the preference
    and refuses a write to the file. A page that offered the menu would offer a
    setting that the machine does not accept.
    """
    return governor != PINNED_GOVERNOR


def validate(values, root=""):
    """Refuses a value that this machine does not offer.

    The check is against the machine and not against a list in this file,
    because the list depends on the mode of the driver. A configuration file
    from a machine in a different mode is how a governor that does not exist
    reaches sysfs.

    A machine with no cpufreq accepts "leave it alone" only, and that is what
    an unset setting already is.
    """
    governor = values.get("CPU_GOVERNOR", UNSET)
    if governor != UNSET and governor not in governors(root):
        offered = governors(root)
        raise ValueError(
            "CPU_GOVERNOR=%s is not one this machine offers%s"
            % (governor, (": " + ", ".join(offered)) if offered
               else " - it has no cpufreq at all"))

    # Only when it is a setting. The check uses the values that are available
    # after the governor above is applied. That is not what the file reports
    # while a fixing governor still runs. See epp_values.
    if not epp_in_play(values, root):
        return
    epp = values.get("CPU_EPP", UNSET)
    if epp != UNSET and epp not in epp_values(root):
        raise ValueError(
            "CPU_EPP=%s is not one this machine offers: %s"
            % (epp, ", ".join(epp_values(root))))


# -- the profiles of the wall panel -----------------------------------------
#
# The wall panel has room for a few buttons, and no words for each value that
# a kernel knows. So it offers profiles: a governor and a preference together,
# under a name that means something to a person. The control panel and the
# plugin in Game Mode keep each value.
#
# A profile is the first of its candidates that this machine offers. With a
# preference, "balanced" and "powersave" are the powersave governor, which
# lets the firmware pick the clock, with the preference that leans one way or
# the other. Without a preference, "balanced" is a governor that follows the
# load. The classic powersave governor holds the lowest clock. That is no
# profile for a machine that plays games, so "powersave" needs a preference.
# A candidate with no preference asks for none: performance pins it, and the
# classic governors have none.
PROFILE_STEAMOS = "steamos"
PROFILE_CUSTOM = "custom"
PROFILES = (
    ("powersave", (("powersave", "power"),)),
    ("balanced", (("powersave", "balance_performance"),
                  ("schedutil", UNSET), ("ondemand", UNSET))),
    ("performance", ((PINNED_GOVERNOR, UNSET),)),
)


def profile_settings(name, root=""):
    """The settings of one profile on this machine, or None.

    None for a name that is no profile, and for a profile that has none of
    its candidates here.

    "steamos" is no setting at all. It puts the governor back to unset, and
    the program that applies it then leaves the CPU alone: SteamOS has the
    CPU again at the next start, and not before. Nothing knows the governor
    that SteamOS had before this project changed it.
    """
    if name == PROFILE_STEAMOS:
        return {"CPU_GOVERNOR": UNSET}
    offered = governors(root)
    preferences = epp_values(root)
    for profile, candidates in PROFILES:
        if profile != name:
            continue
        for governor, epp in candidates:
            if governor not in offered:
                continue
            if epp == UNSET:
                return {"CPU_GOVERNOR": governor}
            if epp in preferences:
                return {"CPU_GOVERNOR": governor, "CPU_EPP": epp}
    return None


def profiles(root=""):
    """The names of the profiles this machine offers, in the order of the
    panel: the three from the least power to the most, then "steamos"."""
    return [name for name, _candidates in PROFILES
            if profile_settings(name, root)] + [PROFILE_STEAMOS]


def profile_of(values, root=""):
    """The profile that these settings are, or "custom" for none of them.

    The settings come from the file, which is what a person asked for. The
    sysfs files say what runs, and the two can differ: the profile "steamos"
    leaves the last governor in force until the next start.
    """
    governor = values.get("CPU_GOVERNOR", UNSET)
    if governor == UNSET:
        return PROFILE_STEAMOS
    for name, _candidates in PROFILES:
        wanted = profile_settings(name, root)
        if not wanted or wanted["CPU_GOVERNOR"] != governor:
            continue
        if "CPU_EPP" not in wanted or wanted["CPU_EPP"] == values.get("CPU_EPP"):
            return name
    return PROFILE_CUSTOM
