# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The battery of a Steam Controller of 2026, read the way Steam reads it.

The kernel driver for this controller is hid-steam, since Linux 7.3 and
SteamOS 3.8.28. It gives the controller a power supply, but only while no
program holds the hidraw node of the controller open:

    if (connected && !opened)
        ret = steam_register(steam);
    else
        steam_unregister(steam);

Steam holds that node open for as long as it runs, and on SteamOS it always
runs. The board showed the result: the puck on hid-steam, the controller on
the puck, and an empty /sys/class/power_supply.

So this reads what Steam reads. The controller sends its battery in an input
report of its own, about every 3.5 seconds. Every program that holds the node
open gets a copy. The layout is struct steam_ibex_battery_status of
hid-steam.c, after the report ID:

    byte 0   the report ID, 0x43
    byte 1   the charge state: 1 discharging, 2 charging, 4 full
    byte 2   the charge in percent

The board sent this one, at 95 percent and away from its charger:

    43 01 5f 08 10 18 10 78 00 00 00 00 00 ac 5d

This only reads. It sends nothing to the controller.
"""

from __future__ import annotations

import os
import select
import threading
import time

HIDRAW_ROOT = "/sys/class/hidraw"
POWER_ROOT = "/sys/class/power_supply"
DEV_ROOT = "/dev"

# Valve, and the four controllers of 2026 in the table of hid-steam: on a
# cable, on Bluetooth, on the puck, and on the receiver inside a Steam
# Machine. The driver reads the battery of all four with the same code.
VENDOR = "000028DE"
PRODUCTS = ("00001302", "00001303", "00001304", "00001305")

# The puck and the receiver have one node for each of four controllers, on
# the interfaces 2 to 5. Interface 6 is the pogo pins of the puck, and
# hid-steam and SDL both leave it alone. The board gave the same five nodes,
# and only the one on interface 2 sent anything.
RECEIVERS = ("00001304", "00001305")
SLOTS = (2, 3, 4, 5)

BATTERY_REPORT = 0x43
BATTERY_SIZE = 15
# The words of /sys/class/power_supply, because the panel reads the word
# "Charging" and the kernel controllers already send these.
CHARGE = {1: "Discharging", 2: "Charging", 4: "Full"}
NAME = "Steam Controller"

# How often this looks, and for how long at the most.
#
# The board sent nine battery reports in 30 seconds, so two fit in one look
# of eight. A controller sends its input all the time, 7956 reports in the
# same 30 seconds. A node that sends nothing for a second thus holds no
# controller, and the look does not wait for it.
EVERY = 30.0
WINDOW = 8.0
SETTLE = 1.0


def _read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def _hid_id(uevent):
    """(bus, vendor, product) from the HID_ID line of a uevent, or None."""
    for line in uevent.splitlines():
        if line.startswith("HID_ID="):
            parts = line[len("HID_ID="):].strip().upper().split(":")
            if len(parts) == 3:
                return tuple(parts)
    return None


def _interface(place):
    """The number of a USB interface, or None for a place that is not one."""
    try:
        return int(_read(os.path.join(place, "bInterfaceNumber")).strip(), 16)
    except ValueError:
        return None


def _reported(power_root):
    """The places of each controller whose battery the kernel reports.

    The power supply of hid-steam is under the HID device of the controller.
    The hidraw node is under a second HID device beside it, which the driver
    makes for Steam. So the two have one parent.
    """
    places = set()
    names = os.listdir(power_root) if os.path.isdir(power_root) else []
    for name in names:
        device = os.path.join(power_root, name, "device")
        if os.path.exists(device):
            places.add(os.path.dirname(os.path.realpath(device)))
    return places


def nodes(hidraw_root=HIDRAW_ROOT, power_root=POWER_ROOT, dev_root=DEV_ROOT):
    """The hidraw node of each controller of 2026 that the kernel leaves out.

    A controller that the kernel reports stays closed, and not only to keep
    it off the list twice. Its power supply means that no program holds it
    open. A first program to open it is Steam to hid-steam, and the driver
    then takes its own gamepad away until that program closes it again.
    """
    reported = _reported(power_root)
    found = []
    names = os.listdir(hidraw_root) if os.path.isdir(hidraw_root) else []
    for name in sorted(names):
        device = os.path.join(hidraw_root, name, "device")
        ident = _hid_id(_read(os.path.join(device, "uevent")))
        if ident is None or ident[1] != VENDOR or ident[2] not in PRODUCTS:
            continue
        place = os.path.dirname(os.path.realpath(device))
        if ident[2] in RECEIVERS and _interface(place) not in SLOTS:
            continue
        if place in reported:
            continue
        found.append(os.path.join(dev_root, name))
    return found


def parse(report):
    """The battery in one report, or None for a report that is not one."""
    if len(report) != BATTERY_SIZE or report[0] != BATTERY_REPORT:
        return None
    if report[2] > 100:
        return None
    return {"name": NAME, "percent": report[2],
            "status": CHARGE.get(report[1], "Unknown")}


def _open(path):
    return os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)


def look(paths, window=WINDOW, settle=SETTLE, opener=_open,
         clock=time.monotonic):
    """One look at the nodes: {path: battery}, and the paths that sent data.

    A node keeps 64 reports for each reader, and when that is full it drops
    the new ones. So this reads every report while it looks, the input too.
    Otherwise the battery report arrives at a full queue and never reaches
    this reader.
    """
    open_fds = {}
    for path in paths:
        try:
            open_fds[opener(path)] = path
        except OSError:
            continue
    found, alive = {}, set()
    start = clock()
    try:
        while open_fds:
            spent = clock() - start
            if spent >= window:
                break
            if spent >= settle and alive <= set(found):
                break
            ready, _, _ = select.select(list(open_fds), [], [],
                                        min(0.25, window - spent))
            for fd in ready:
                path = open_fds[fd]
                try:
                    report = os.read(fd, 64)
                except BlockingIOError:
                    continue
                except OSError:
                    report = b""
                if not report:
                    # The puck or the controller went away. hidraw then
                    # answers with an error, and it never answers empty.
                    os.close(fd)
                    del open_fds[fd]
                    continue
                alive.add(path)
                battery = parse(report)
                if battery is not None:
                    found[path] = battery
    finally:
        for fd in open_fds:
            os.close(fd)
    return found, alive


def _thread(work):
    threading.Thread(target=work, daemon=True).start()


class Batteries:
    """What the last look found, and a new look when that one is old.

    The panel asks every three seconds, and a look takes up to eight. So a
    look runs in a thread of its own, and an answer carries the look before
    it. A service that the panel does not ask does not look at all.
    """

    def __init__(self, every=EVERY, find=nodes, peek=look, spawn=_thread,
                 clock=time.monotonic):
        self.every = every
        self._find, self._peek = find, peek
        self._spawn, self._clock = spawn, clock
        # ThreadingHTTPServer answers each request in a thread of its own.
        self._lock = threading.Lock()
        self._found = {}
        self._when = None
        self._busy = False

    def current(self):
        """Each controller of the last look, in the order of its node."""
        now = self._clock()
        with self._lock:
            start = not self._busy and (self._when is None or
                                        now - self._when >= self.every)
            if start:
                self._busy, self._when = True, now
            found = [self._found[path] for path in sorted(self._found)]
        if start:
            self._spawn(self.refresh)
        return found

    def refresh(self):
        """One look, and its result in place of the last one.

        A controller that sent input but no battery in this look keeps the
        battery of the last look. A controller that sent nothing is off, and
        it goes from the list at once.
        """
        fresh, alive = {}, set()
        try:
            fresh, alive = self._peek(self._find())
        finally:
            with self._lock:
                kept = {path: self._found[path]
                        for path in alive - set(fresh) if path in self._found}
                self._found = {**fresh, **kept}
                self._busy = False


_batteries = Batteries()


def batteries():
    """Each Steam Controller of 2026 and its battery. See Batteries."""
    return _batteries.current()
