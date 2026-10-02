# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the page of the PC on the panel shows about this machine.

Three groups, in the order of the page: the system, the hardware and the
network. Everything here is read from /proc, /sys and /etc, with one command
for the update channel, and nothing here needs root.

The parts that do not change while the machine runs are read once: the
system, the names of the processor and the graphics card. The load, the
memory, the uptime and the network are read for each answer. The fans are
hwmon, so companion.py adds those through temperature.py.
"""

from __future__ import annotations

import fcntl
import functools
import os
import re
import socket
import struct
import subprocess
import threading

OS_RELEASE = "/etc/os-release"
CPUINFO = "/proc/cpuinfo"
STAT = "/proc/stat"
MEMINFO = "/proc/meminfo"
UPTIME = "/proc/uptime"
NET_ROOT = "/sys/class/net"
# The list of PCI names. SteamOS has it from hwdata, other systems keep it
# in /usr/share/misc.
PCI_IDS = ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids")
# The names AMD gives its cards, by device and revision, from libdrm. The
# list of PCI names calls 7550 "Navi 48 [Radeon RX 9070/9070 XT/9070 GRE]";
# this one tells the three apart by the revision, C0 for the 9070 XT. LACT
# shows the same name, and the board showed LACT.
AMDGPU_IDS = ("/usr/share/libdrm/amdgpu.ids",)
AMD_VENDOR = "1002"

# The update channel. The command prints the branch, and the branch is the
# word the menu of Steam shows for three of them.
BRANCH_COMMAND = ("steamos-select-branch", "-c")
CHANNELS = {"rel": "Stable", "stable": "Stable", "beta": "Beta",
            "preview": "Preview", "main": "Main"}

# What a processor calls itself past its name: "AMD Ryzen 7 9800X3D 8-Core
# Processor" is a Ryzen 7 9800X3D to a person.
CPU_NOISE = (r"\(R\)", r"\(TM\)", r"\s+\d+-Core Processor$",
             r"\s+Processor$", r"\s+w/ Radeon.*$", r"\s+with Radeon.*$")

# SIOCGIFADDR of linux/sockios.h: the IPv4 address of one interface.
SIOCGIFADDR = 0x8915


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def os_release(path=OS_RELEASE):
    """The pairs of /etc/os-release, with the quotes taken off."""
    found = {}
    for line in _read(path).splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def channel(command=BRANCH_COMMAND):
    """The update channel, or None where there is no SteamOS to ask."""
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=3, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [line.strip() for line in done.stdout.splitlines()
             if line.strip()]
    if not lines:
        return None
    branch = lines[-1].lower()
    return CHANNELS.get(branch, branch.upper()[:15])


@functools.lru_cache(maxsize=1)
def system(path=OS_RELEASE):
    """The operating system, its build and its update channel.

    Read once: these change with an update, and an update restarts the
    machine and this service with it.
    """
    release = os_release(path)
    name = release.get("NAME") or release.get("PRETTY_NAME") or "Linux"
    version = release.get("VERSION_ID", "")
    return {
        "os": ("%s %s" % (name, version)).strip()[:31],
        "build": release.get("BUILD_ID", "")[:23] or None,
        "channel": channel(),
        "kernel": short_kernel(os.uname().release)[:47],
    }


def short_kernel(release):
    """The version of a kernel, without the name of its build.

    "7.2.7-valve1-1-neptune-72-gc8730d37f9c6" is 7.2.7-valve1-1 to a person:
    the numbers, and each part after them that has a number in it, up to the
    first part that has none.
    """
    found = re.match(r"\d+(?:\.\d+)+(?:-[a-z]*\d[a-z0-9]*)*", release)
    return found.group(0) if found else release


def uptime(path=UPTIME):
    """Seconds since the machine started, or None."""
    try:
        return int(float(_read(path).split()[0]))
    except (IndexError, ValueError):
        return None


@functools.lru_cache(maxsize=1)
def cpu_model(path=CPUINFO):
    """The processor as a person names it, or None."""
    for line in _read(path).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "model name":
            name = value.strip()
            for noise in CPU_NOISE:
                name = re.sub(noise, "", name)
            return re.sub(r"\s+", " ", name).strip()[:47] or None
    return None


class CpuLoad:
    """The share of the processor in use since the last answer.

    /proc/stat counts the time of every processor since the start, so one
    reading says nothing and two say what happened between them. The panel
    asks every three seconds, which makes this the load of those seconds.
    The first answer has no reading before it, and says None.
    """

    def __init__(self, path=STAT):
        self.path = path
        self._last = None
        # ThreadingHTTPServer answers each request in a thread of its own.
        self._lock = threading.Lock()

    def _counts(self):
        first = _read(self.path).splitlines()[:1]
        if not first or not first[0].startswith("cpu "):
            return None
        try:
            values = [int(one) for one in first[0].split()[1:]]
        except ValueError:
            return None
        # user nice system idle iowait irq softirq steal: idle and iowait
        # are the time nothing ran.
        idle = sum(values[3:5])
        return sum(values[:8]), idle

    def percent(self):
        counts = self._counts()
        with self._lock:
            last, self._last = self._last, counts
        if counts is None or last is None:
            return None
        total, idle = counts[0] - last[0], counts[1] - last[1]
        if total <= 0:
            return None
        return max(0, min(100, round(100 * (total - idle) / total)))


def memory(path=MEMINFO):
    """{"used", "total"} in bytes, or None.

    Used is what MemAvailable leaves: the page cache is memory that a game
    gets back the moment it asks, and counting it as used makes a machine
    that idles look full.
    """
    found = {}
    for line in _read(path).splitlines():
        key, _, value = line.partition(":")
        parts = value.split()
        if parts and parts[0].isdigit():
            found[key.strip()] = int(parts[0]) * 1024
    total, free = found.get("MemTotal"), found.get("MemAvailable")
    if not total or free is None:
        return None
    return {"used": max(0, total - free), "total": total}


def _hex(path):
    text = _read(path).strip().lower()
    return text[2:] if text.startswith("0x") else text


def _amdgpu_name(device, revision, paths=AMDGPU_IDS):
    """The name of an AMD card in the list of libdrm, or None.

    A line is "7550,\tC0,\tAMD Radeon RX 9070 XT": the device, the
    revision and the name.
    """
    for path in paths:
        for line in _read(path).splitlines():
            parts = [part.strip() for part in line.split(",", 2)]
            if (len(parts) == 3 and parts[0].lower() == device
                    and parts[1].lower() == revision):
                return parts[2]
    return None


def _pci_name(vendor, device, paths=PCI_IDS):
    """The name of a PCI device in the list of PCI names, or None."""
    for path in paths:
        in_vendor = False
        for line in _read(path).splitlines():
            if not line or line.startswith("#"):
                continue
            if not line.startswith("\t"):
                if in_vendor:
                    break
                in_vendor = line[:4].lower() == vendor
                continue
            if in_vendor and not line.startswith("\t\t") \
                    and line[1:5].lower() == device:
                return line[5:].strip()
    return None


@functools.lru_cache(maxsize=4)
def gpu_model(card, paths=PCI_IDS, amd_paths=AMDGPU_IDS):
    """The model of the graphics chip at that PCI device.

    The model and not the board: "AMD Radeon RX 9070 XT", which is what
    LACT calls the model of the GPU. An AMD card has it in the list of
    libdrm. Any other card, and an AMD card that list does not know, has
    the list of PCI names, which names a chip and its models: "Navi 48
    [Radeon RX 9070/9070 XT/9070 GRE]". A person means the part in
    brackets.
    """
    if not card:
        return None
    vendor, device = _hex(os.path.join(card, "vendor")), _hex(
        os.path.join(card, "device"))
    if not vendor or not device:
        return None
    if vendor == AMD_VENDOR:
        name = _amdgpu_name(device, _hex(os.path.join(card, "revision")),
                            amd_paths)
        if name:
            return name[:47]
    name = _pci_name(vendor, device, paths)
    if not name:
        return None
    bracket = re.search(r"\[([^\]]+)\]\s*$", name)
    return (bracket.group(1) if bracket else name).strip()[:47]


def _address_of(name):
    """The IPv4 address of one interface, or None."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            packed = fcntl.ioctl(probe.fileno(), SIOCGIFADDR,
                                 struct.pack("256s", name[:15].encode()))
        except OSError:
            return None
    return socket.inet_ntoa(packed[20:24])


def network(address, root=NET_ROOT, lookup=_address_of):
    """The card that the panel reached this machine through.

    The address is the one the panel connected to, which the request knows.
    The card is the one that holds that address: wired or wireless, its
    speed where the kernel says one, and its hardware address.
    """
    out = {"ip": address, "kind": None, "speed": None, "mac": None}
    names = sorted(os.listdir(root)) if os.path.isdir(root) else []
    for name in names:
        if name == "lo" or not address or lookup(name) != address:
            continue
        place = os.path.join(root, name)
        wireless = (os.path.isdir(os.path.join(place, "wireless")) or
                    os.path.exists(os.path.join(place, "phy80211")))
        out["kind"] = "wireless" if wireless else "wired"
        try:
            speed = int(_read(os.path.join(place, "speed")).strip())
        except ValueError:
            speed = None
        # A card with no cable says -1, and a wireless card says nothing.
        out["speed"] = speed if speed and speed > 0 else None
        mac = _read(os.path.join(place, "address")).strip().lower()
        out["mac"] = mac if re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}",
                                         mac) else None
        break
    return out
