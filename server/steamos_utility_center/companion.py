# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the Smart 86 Box panel reads from this machine, and what it can press.

The panel is an ESP32-S3 with a 4 inch touch screen on the wall. It has no
cable to this machine. It asks over the network every three seconds, and it
sends a press as a second request. firmware/companion holds its side.

This service answers two paths and nothing else:

    GET  /v1/status     the controllers, the audio and the sensors
    POST /v1/action     one of the named presses

It runs in the session of the desktop user and never as root. That is not a
limitation to work around, it is the design: `systemctl suspend` and `wpctl`
both belong to a session, and a service with no root cannot lose more than
that session holds. The panel therefore reaches exactly what the person at
the keyboard reaches.

The sensors come from temperature.py, which this project already uses for the
LED bar. Two readers of /sys/class/hwmon become two answers on the day one of
them learns about a new chip.
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import desktop, steamapps, steamcontroller, temperature

# The port, and the file that holds the shared secret.
#
# The token is in the home directory and not in /etc. It belongs to one
# person and one panel, it needs no root to read, and a SteamOS update leaves
# a home directory alone. install.sh writes it with mode 0600.
PORT = 8765
TOKEN_DIR = os.path.join(".config", "steamos-utility-center")
TOKEN_FILE = "companion-token"

# Below this length a token is a password, and a password on a network is a
# token that somebody guesses. install.sh writes 32 bytes of secrets.token_urlsafe.
TOKEN_MINIMUM = 32

# A request body carries one short JSON object. Anything longer is not one.
BODY_LIMIT = 256

# How the panel proves that it knows the secret without sending it.
#
# The first version put the token in a header on every request, and the panel
# asks every three seconds. That is the secret on the air 28,800 times a day,
# over plain HTTP on a home network. One reader of one of those requests then
# holds Suspend, Reboot and Power off for as long as the token lasts.
#
# So the secret stays on both ends and never moves. This service hands out a
# nonce, the panel signs with it, and the signature covers the method, the
# path and the body. A captured request is then worth nothing: its nonce is
# spent, and the signature does not fit another path or another action.
#
# No clock is needed at either end. That matters, because the board has no
# battery clock and asks no time server.
NONCE_HEADER = "X-Panel-Nonce"
AUTH_HEADER = "X-Panel-Auth"
NONCE_BYTES = 16

# How many nonces stay open at one time.
#
# Anybody on the network can ask for one, because every answer carries one.
# So the room is bounded and the oldest leaves. A panel whose nonce is pushed
# out gets a 401 with a fresh one and signs again, which costs one round trip
# and needs nobody to do anything.
NONCE_ROOM = 64

# What a press is allowed to be. A name from this table, never a string from
# the network. Each command is a tuple and goes to subprocess without a
# shell, so a name that is not here reaches nothing at all.
ACTIONS = {
    "volume_up": ("wpctl", "set-volume", "-l", "1.0",
                  "@DEFAULT_AUDIO_SINK@", "5%+"),
    "volume_down": ("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"),
    "mute": ("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"),
    "suspend": ("systemctl", "suspend"),
    "reboot": ("systemctl", "reboot"),
    "poweroff": ("systemctl", "poweroff"),
    # Where to go, and not "the other one". The panel knows the mode from
    # the last status, which is up to three seconds old, so a toggle would
    # now and then switch to the side it is already on. A target says what
    # it means whatever happened in between.
    #
    # The session goes away and comes back, which is why this service is
    # ordered After the graphical session and deliberately not PartOf it.
    # The unit file says so.
    #
    # The way to the desktop goes through steamosctl and names no session.
    # It went through `steamos-session-select plasma` first, and the board
    # reported what that does: Game Mode ended and nothing came up, a
    # black screen, and the way back worked. The script says why. Its own
    # branch for that word is
    #
    #     plasma) steamosctl switch-to-desktop-mode plasmax11.desktop ;;
    #
    # which asks for X11 by name, whether or not this machine has it. The
    # same script names steamosctl as what replaces it, and its branch for
    # a persistent desktop calls switch-to-desktop-mode with no session at
    # all. With none, the machine starts the desktop it is set up for, so
    # nothing here has to know whether that is X11 or Wayland.
    "desktop_mode": ("steamosctl", "switch-to-desktop-mode"),
    # This one is left as it is, because it works. The same script also
    # sets the default login mode here, so the way to Game Mode makes
    # itself the mode this machine starts in and the way to the desktop
    # does not. That is the script's asymmetry and not this table's, and
    # changing the half that works to match the half that did not is how
    # a fix takes a second thing with it.
    "game_mode": ("steamos-session-select", "gamescope"),
}

# Where a person of this machine looks for a drive.
#
# The list the kernel keeps, and not a guess at the paths. The first
# version of this read "/" and called it the internal drive, which is
# wrong on the machine it was written for: SteamOS keeps "/" as a read
# only 5 GiB partition for its A and B updates, and everything a person
# stores goes on /home. The panel showed 0.6 GB free of 5.0 and the
# machine had 920 GiB. It missed a second NVMe drive of 4 TB altogether,
# because that is mounted at neither of the two paths it looked at.
#
# So the filesystems come from the kernel now, and the ones a person means
# are picked out of them by what they are rather than by where they sit.
MOUNTS = "/proc/mounts"

# Compressed memory is not a drive. It rarely carries a filesystem at all,
# and where it does it is swap that looks like one.
NOT_A_DRIVE = ("/dev/zram",)

# Below this a filesystem belongs to the operating system and not to
# anybody's games. The read only root of SteamOS is 5 GiB, /var is 256
# MiB, and the two EFI partitions are smaller again. The smallest card
# anybody puts in a slot is well above it.
DRIVE_FLOOR = 16 * 1024 ** 3

# The battery of a controller, which the kernel publishes as a power supply
# beside the one of a laptop. The name tells them apart.
CONTROLLER_ROOT = "/sys/class/power_supply"
CONTROLLER_KINDS = ("battery", "gaming input")
CONTROLLER_NAMES = ("controller", "dualsense", "ps-controller", "steam",
                    "xpad")
CONTROLLER_LABELS = (("ps-controller", "PlayStation Controller"),
                     ("sony_controller", "PlayStation Controller"),
                     ("steam", "Steam Controller"),
                     ("xpad", "Xbox Controller"))

# Each game controller that the kernel knows, with a battery or without.
# The page of the controllers lists one on a cable too, with "--" for its
# battery.
INPUT_ROOT = "/sys/class/input"
# BTN_GAMEPAD and BTN_JOYSTICK of linux/input-event-codes.h. A pad has the
# first and a stick the second. A keyboard, a mouse and the touchpad of a
# DualShock have neither.
GAMEPAD_KEYS = (0x130, 0x120)
# The bits of one word in a capabilities file: the kernel writes each
# unsigned long, and userspace on this machine has the same long.
LONG_BITS = struct.calcsize("l") * 8
# A name a person knows, for the vendors whose pads name the chip. A
# DualShock 4 calls itself "Wireless Controller".
PAD_VENDORS = {"054c": "PlayStation Controller", "045e": "Xbox Controller"}
# Valve. steamcontroller.py reads the Steam Controller, and the puck adds an
# input of its own for each of its four slots, with or without a controller.
VALVE_VENDOR = "28de"

# The chips that answer "how hot is the processor" and "how hot is the card".
# temperature.py ranks the sensors inside a chip, and this says which chips
# belong to which of the two numbers on the panel.
CPU_CHIPS = ("k10temp", "coretemp", "zenpower")
GPU_CHIPS = ("amdgpu",)

# hwmon reports microwatts for power and thousandths of a degree for heat.
MICROWATTS = 1000000

# What a reading has to be under to be a reading. A card that reports 4000
# degrees reports a broken sensor, and a dash on the panel is the honest
# answer to that.
SANE_CELSIUS = 150
SANE_WATTS = 2000

# The card a magic packet has to name, and where to read it.
#
# Wake on LAN is a thing wired cards do. A radio that sleeps hears nothing,
# and the few cards that claim otherwise are not worth the panel showing a
# button that does nothing. So the default route is not the answer on its
# own: a machine with a cable and a radio routes over whichever it prefers,
# and that is often the radio.
#
# This reads sysfs and /proc and runs nothing. A virtual card (a bridge, a
# veth, a tunnel) has no device link. A radio has a wireless directory or a
# phy80211 link. ARPHRD_ETHER is 1, and the loopback is 772.
NET_ROOT = "/sys/class/net"
ROUTE_TABLE = "/proc/net/route"
ARPHRD_ETHER = "1"


def token_path(home=None):
    """Where the shared secret of this machine and its panel is."""
    return os.path.join(home or os.path.expanduser("~"), TOKEN_DIR,
                        TOKEN_FILE)


# The firmware of the panel, and the image built from it.
#
# The image is in this repository, and it arrives with an update like every
# other file. That is the whole point: a person presses Flash on the page and
# the board is written, with nothing to fetch and nothing to put anywhere.
#
# It is build output in a repository, which is a thing to be careful with. So
# it never sits there unchecked: CI builds it from the source beside it and
# writes the fingerprint of that source next to it, and the page refuses an
# image whose fingerprint does not match. A stale image is then a sentence on
# the screen and not a panel that says "no PC" on the wall.
FIRMWARE_DIR = os.path.join("firmware", "companion")
PREBUILT_DIR = os.path.join(FIRMWARE_DIR, "prebuilt")
BUILD_DIR = os.path.join(FIRMWARE_DIR, "build")
STAMP_NAME = "built-from"

# The three parts of an image, at the names an ESP-IDF build gives them.
IMAGE_PARTS = (os.path.join("bootloader", "bootloader.bin"),
               os.path.join("partition_table", "partition-table.bin"),
               "steamos_companion.bin")

# What the build reads. Everything else under firmware/companion is a note or
# a licence, and a change to one of those is not a reason to build again.
FIRMWARE_SOURCE = ("main", "CMakeLists.txt", "partitions.csv",
                   "sdkconfig.defaults", "dependencies.lock")


def firmware_fingerprint(root="."):
    """One hash of every file the firmware build reads.

    The path is in the hash beside the bytes. Without it, a file that moves
    to another name gives the same answer as a file that did not move.

    The same function answers in three places: the CI job that writes the
    stamp, the page that compares it, and the test that holds the two equal.
    """
    digest = hashlib.sha256()
    for name in sorted(FIRMWARE_SOURCE):
        start = os.path.join(root, FIRMWARE_DIR, name)
        if os.path.isfile(start):
            found = [start]
        else:
            found = sorted(os.path.join(base, one)
                           for base, _dirs, names in os.walk(start)
                           for one in names)
        for path in found:
            digest.update(os.path.relpath(path, root).encode())
            digest.update(b"\0")
            with open(path, "rb") as handle:
                digest.update(handle.read())
            digest.update(b"\0")
    return digest.hexdigest()


def image_is_complete(where):
    """Whether that directory holds all three parts of an image.

    All three or none. A directory with one of them is a build that stopped,
    and a flash from it leaves a board that does not start.
    """
    return all(os.path.isfile(os.path.join(where, part))
               for part in IMAGE_PARTS)


def image_stamp(where):
    """The fingerprint the build of that image recorded, or "" for none."""
    try:
        with open(os.path.join(where, STAMP_NAME)) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def addresses():
    """The addresses of this machine on the network, as the panel needs them.

    The form on the phone asks for http://<address>:8765, and reading it off
    this page beats reading it off a router. hostname -I gives every address
    this machine answers on, and the first is the one to try.
    """
    said = run("hostname", "-I")
    return tuple(one for one in said.split() if one and ":" not in one)


def run(*args):
    """One command, and its output, or nothing at all when it fails.

    Nothing rather than an exception: this is called to fill a field on a
    screen, and a missing field is a better answer than a service that stops.
    """
    try:
        done = subprocess.run(args, capture_output=True, text=True,
                              timeout=3, check=True)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()


def _read_text(path):
    try:
        with open(path, "r", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _read_number(path, scale=1):
    text = _read_text(path)
    try:
        return int(text) / scale
    except (TypeError, ValueError):
        return None


def _label_for(name):
    for term, label in CONTROLLER_LABELS:
        if term in name:
            return label
    return "Controller"


def _has_key(capabilities, code, bits=LONG_BITS):
    """Whether a capabilities file of the kernel sets one bit.

    The file is words of hex, the highest first, as /sys writes a bitmap.
    """
    words = capabilities.split()
    index, bit = divmod(code, bits)
    if index >= len(words):
        return False
    try:
        return bool(int(words[-1 - index], 16) >> bit & 1)
    except ValueError:
        return False


def _number_in(name):
    found = re.search(r"(\d+)$", name)
    return int(found.group(1)) if found else -1


def gamepads(root=INPUT_ROOT):
    """Each game pad that the kernel knows, in the order it arrived.

    Two kinds stay out. A device under /devices/virtual is one a program
    made, and Steam makes an Xbox pad for each controller it drives. A pad
    of Valve is the Steam Controller or its puck, and steamcontroller.py
    reads those. Each entry carries its device, the HID device of the pad,
    which is also the parent of its battery.
    """
    found, seen = [], set()
    names = os.listdir(root) if os.path.isdir(root) else []
    for name in sorted((one for one in names if one.startswith("input")),
                       key=_number_in):
        path = os.path.join(root, name)
        if "/devices/virtual/" in os.path.realpath(path):
            continue
        vendor = (_read_text(os.path.join(path, "id", "vendor")) or "").lower()
        if vendor == VALVE_VENDOR:
            continue
        keys = _read_text(os.path.join(path, "capabilities", "key")) or ""
        if not any(_has_key(keys, code) for code in GAMEPAD_KEYS):
            continue
        device = os.path.realpath(os.path.join(path, "device"))
        if device in seen:
            continue
        seen.add(device)
        found.append({
            "device": device,
            "name": PAD_VENDORS.get(vendor) or
            (_read_text(os.path.join(path, "name")) or "")[:63] or
            "Controller",
        })
    return found


def controllers(root=CONTROLLER_ROOT, inputs=INPUT_ROOT):
    """Every game controller that the kernel knows, with its battery.

    A battery and a pad with one device are one controller. A pad with no
    battery is a controller all the same, with None for its percent. A
    battery with no pad comes first: that is the Steam Controller while
    Steam is not running, and the panel shows the first two.
    """
    batteries = _batteries(root)
    found = []
    for pad in gamepads(inputs):
        battery = batteries.pop(pad["device"], None)
        found.append({
            "name": pad["name"],
            "percent": battery["percent"] if battery else None,
            "status": battery["status"] if battery else "Unknown",
        })
    return list(batteries.values()) + found


def _batteries(root):
    """Each controller battery under root, by the device it belongs to.

    A battery with no device link keeps a key of its own, so it stays on
    the list and matches no pad.
    """
    found = {}
    for name in sorted(os.listdir(root) if os.path.isdir(root) else []):
        path = os.path.join(root, name)
        kind = (_read_text(os.path.join(path, "type")) or "").lower()
        lowered = name.lower()
        if kind not in CONTROLLER_KINDS:
            continue
        if not any(term in lowered for term in CONTROLLER_NAMES):
            continue
        if _read_text(os.path.join(path, "present")) == "0":
            continue
        capacity = _read_number(os.path.join(path, "capacity"))
        if capacity is None:
            continue
        model = _read_text(os.path.join(path, "model_name"))
        device = os.path.join(path, "device")
        key = os.path.realpath(device) if os.path.exists(device) else path
        found[key] = {
            "name": (model or "")[:63] or _label_for(lowered),
            "percent": max(0, min(100, int(capacity))),
            "status": _read_text(os.path.join(path, "status")) or "Unknown",
        }
    return found


def numbered(pads):
    """Two controllers of one name become that name with 1 and with 2.

    The page of the controllers shows the names, and two lines that read
    "Steam Controller" do not say which one is low.
    """
    counts = collections.Counter(pad["name"] for pad in pads)
    seen = collections.Counter()
    out = []
    for pad in pads:
        if counts[pad["name"]] > 1:
            seen[pad["name"]] += 1
            pad = dict(pad, name="%s %d" % (pad["name"], seen[pad["name"]]))
        out.append(pad)
    return out


def audio():
    """The volume of the default output, as a percentage, and its mute."""
    said = run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
    found = re.search(r"Volume:\s*([0-9.]+)", said)
    return {
        "percent": max(0, min(100, round(float(found.group(1)) * 100)))
        if found else None,
        "muted": "[MUTED]" in said,
    }


def _best(sensors, chips):
    """The sensor of those chips that answers best. See temperature.py."""
    wanted = [one for one in sensors if one["chip"].lower() in chips]
    return temperature.pick_sensor(wanted)


def _graphics_card(sensors):
    """The directory of the graphics card, where more than one answers.

    A Ryzen with a graphics part and a card in the slot gives two amdgpu
    chips. The card is the one a person means by "the GPU", and the size of
    its memory is what tells the two apart.
    """
    places = {os.path.dirname(one["path"]) for one in sensors
              if one["chip"].lower() in GPU_CHIPS}
    if not places:
        return None
    return max(places, key=lambda place: _read_number(
        os.path.join(place, "device", "mem_info_vram_total")) or 0)


def _sane(value, limit):
    if value is None or not 0 <= value <= limit:
        return None
    return round(value)


def telemetry(root=temperature.HWMON_ROOT):
    """The two temperatures and the power of the card, or a None for each.

    The reads are temperature.py's. This file says which chip is the
    processor and which is the card, and temperature.py says which sensor
    inside a chip is the one to show.
    """
    sensors = temperature.find_sensors(root)
    cpu = _best(sensors, CPU_CHIPS)
    place = _graphics_card(sensors)
    gpu = _best([one for one in sensors
                 if os.path.dirname(one["path"]) == place], GPU_CHIPS)

    watts = None
    if place:
        watts = _read_number(os.path.join(place, "power1_average"),
                             MICROWATTS)
        if watts is None:
            watts = _read_number(os.path.join(place, "power1_input"),
                                 MICROWATTS)
    return {
        "cpu_c": _sane(temperature.read_celsius(cpu["path"]) if cpu else None,
                       SANE_CELSIUS),
        "gpu_c": _sane(temperature.read_celsius(gpu["path"]) if gpu else None,
                       SANE_CELSIUS),
        "gpu_w": _sane(watts, SANE_WATTS),
    }


def _is_wired(name, root=NET_ROOT):
    """Whether that card is one a magic packet can reach."""
    path = os.path.join(root, name)
    if not os.path.exists(os.path.join(path, "device")):
        return False
    if os.path.isdir(os.path.join(path, "wireless")):
        return False
    if os.path.exists(os.path.join(path, "phy80211")):
        return False
    return _read_text(os.path.join(path, "type")) == ARPHRD_ETHER


def _routing_interface(path=ROUTE_TABLE):
    """The card the default route leaves by, or nothing.

    The lowest metric wins, which is the rule the kernel uses. A machine
    with two ways out lists both.
    """
    best = None
    lowest = None
    for line in (_read_text(path) or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 7 or parts[1] != "00000000":
            continue
        try:
            metric = int(parts[6])
        except ValueError:
            metric = 0
        if lowest is None or metric < lowest:
            best, lowest = parts[0], metric
    return best


def wake_target(root=NET_ROOT, route=ROUTE_TABLE):
    """The wired card the panel sends a magic packet to, or nothing.

    The panel keeps this and uses it when this machine is off, which is the
    one moment it cannot ask. So it is read while the machine is up and sent
    with every status.

    Of several wired cards, the one the default route leaves by. Of the
    rest, one that has a cable in it. A card with no cable is still an
    answer, because a machine that is off has no carrier either and the card
    somebody unplugged is not the one they will plug back in.
    """
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None
    wired = [name for name in names if _is_wired(name, root)]
    if not wired:
        return None
    routing = _routing_interface(route)
    ordered = sorted(wired, key=lambda name: (
        name != routing,
        _read_text(os.path.join(root, name, "carrier")) != "1",
    ))
    name = ordered[0]
    mac = (_read_text(os.path.join(root, name, "address")) or "").lower()
    # A card with no address, or the all-zero one a device reports before it
    # is ready, names nothing.
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        return None
    if mac == "00:00:00:00:00:00":
        return None
    return {"interface": name, "mac": mac}


def mounted(path=MOUNTS):
    """Every filesystem on a real drive that anybody can write to.

    A device under /dev and not a name: that alone leaves out proc, sysfs,
    every tmpfs and the overlays. Writable, because a filesystem nobody can
    write to is not a place for a game, and the root of SteamOS is exactly
    that.
    """
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:                                     # pragma: no cover
        return out
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        device, point, options = parts[0], parts[1], parts[3]
        if not device.startswith("/dev/"):
            continue
        if device.startswith(NOT_A_DRIVE):
            continue
        if "rw" not in options.split(","):
            continue
        # /proc/mounts writes a space in a path as \040.
        out.append((device, point.replace("\\040", " ")))
    return out


def drive_name(point):
    """A short word for that mount, as the panel prints it.

    The last part of the path: /home reads as home and a card at
    /run/media/deck/Games reads as Games. The root of a machine that has
    no last part gets a word of its own.
    """
    if point == "/":
        return "System"
    return os.path.basename(point.rstrip("/")) or point


def drives(path=MOUNTS, floor=DRIVE_FLOOR):
    """How full each drive is, biggest first, as the panel draws it.

    Bytes and not percent: the panel has the room to write "212 of 916 GB"
    and a percentage alone answers the wrong question. A drive that cannot
    be read is left out rather than shown as empty, because an empty bar
    reads as plenty of room.

    One entry for each device. A btrfs with subvolumes is mounted several
    times over, and three rows of the same drive tell nobody anything.
    """
    seen, out = set(), []
    for device, point in mounted(path):
        if device in seen:
            continue
        seen.add(device)
        try:
            space = os.statvfs(point)
        except OSError:
            continue
        total = space.f_blocks * space.f_frsize
        if total < floor:
            continue
        out.append({
            "name": drive_name(point),
            "total": total,
            # f_bavail and not f_bfree: the second counts the blocks the
            # filesystem keeps for root, which nobody can fill a game into.
            "free": space.f_bavail * space.f_frsize,
        })
    # The panel has room for three. The big ones are the ones a person
    # means, so those come first and a small one falls off the end.
    out.sort(key=lambda one: one["total"], reverse=True)
    return out


def session_mode():
    """"game" while a Game Mode session runs, otherwise "desktop".

    desktop.running_game_mode answers by the compositor of Game Mode,
    which is the one thing that is there in the one and not the other.
    """
    return "game" if desktop.running_game_mode() else "desktop"


def status():
    """Everything one GET answers with."""
    return {
        "host": os.uname().nodename,
        # The Steam Controller of 2026 first, because the panel shows the
        # first two and the kernel never reports that controller while Steam
        # runs. See steamcontroller.py.
        "controllers": numbered(steamcontroller.batteries() + controllers()),
        "audio": audio(),
        "telemetry": telemetry(),
        # For the Wake button. None where this machine has no wired card,
        # and the panel then shows no such button. See wake_target.
        "wake": wake_target(),
        # What the panel shows on the page beside the first one.
        "session": session_mode(),
        # "" most of the time, and that is not a fault: most of the time
        # no game runs and the panel then shows nothing.
        "playing": steamapps.now_playing(),
        # {"achieved": 49, "total": 60}, or None for no game and for a
        # game with nothing to count. See steamapps.achievements.
        "achievements": steamapps.now_playing_achievements(),
        "drives": drives(),
    }


def press(name):
    """Runs one named action. Returns (HTTP code, body) for the panel.

    A refusal comes back as a code and not as silence. The panel draws it,
    and somebody who presses "Suspend" and sees nothing happen otherwise has
    no way to tell a rejected press from a lost one.
    """
    if not isinstance(name, str) or name not in ACTIONS:
        return 400, {"error": "unsupported action"}
    try:
        subprocess.run(ACTIONS[name], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=3, check=True)
    except subprocess.CalledProcessError:
        return 502, {"error": "command rejected"}
    except subprocess.TimeoutExpired:
        # No retry: a suspend that answers late is a suspend that happened.
        return 504, {"error": "command result unknown; do not retry"}
    except (FileNotFoundError, PermissionError):
        # The command is not on this machine, or this user cannot run it.
        # Before this the exception left the handler, the panel got a 500
        # with a traceback in the log, and the person at the panel got
        # nothing that says what to install.
        return 501, {"error": "command not available on this machine"}
    except OSError:
        return 503, {"error": "command unavailable"}
    return 200, {"ok": True}


def signature(token, method, path, nonce, body):
    """What the panel sends in place of the secret.

    The method, the path and the body are all under the signature. Without
    them a captured "mute" is a "poweroff" that somebody re-addresses, and a
    captured status read is an action.
    """
    message = "\n".join((method, path, nonce,
                          hashlib.sha256(body).hexdigest())).encode()
    return hmac.new(token.encode(), message, hashlib.sha256).hexdigest()


class Nonces:
    """The nonces this service gave out and nobody has spent.

    One spend for each nonce, which is what makes a captured request useless.
    The room is bounded, because a stranger on the network can ask for as
    many as they like. See NONCE_ROOM.
    """

    def __init__(self, room=NONCE_ROOM):
        self.room = room
        self._open = collections.OrderedDict()
        # ThreadingHTTPServer answers each request in a thread of its own.
        self._lock = threading.Lock()

    def issue(self):
        value = secrets.token_hex(NONCE_BYTES)
        with self._lock:
            self._open[value] = True
            while len(self._open) > self.room:
                self._open.popitem(last=False)
        return value

    def spend(self, value):
        """True one time for each nonce, and False for every time after."""
        with self._lock:
            return self._open.pop(value, None) is not None


def make_handler(token, nonces=None):
    """The request handler for one token."""
    nonces = Nonces() if nonces is None else nonces

    class Handler(BaseHTTPRequestHandler):
        # The log of BaseHTTPRequestHandler goes to stderr, which is the
        # journal here. One line for every poll is one line every three
        # seconds, and it buries everything else.
        def log_message(self, fmt, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def reply(self, code, obj):
            body = json.dumps(obj, separators=(",", ":")).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            # Every answer carries the next nonce, so the panel always holds
            # one and the ordinary poll stays at one round trip. A 401
            # carries one too, which is how a panel that lost its nonce
            # comes back without anybody doing anything.
            self.send_header(NONCE_HEADER, nonces.issue())
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, body=b""):
            nonce = self.headers.get(NONCE_HEADER, "")
            given = self.headers.get(AUTH_HEADER, "")
            if not nonce or not given:
                return False
            wanted = signature(token, self.command, self.path, nonce, body)
            # The signature first and the spend second. The other order lets
            # a stranger burn the nonce of the panel by guessing at it.
            if not hmac.compare_digest(given, wanted):
                return False
            return nonces.spend(nonce)

        def do_GET(self):
            # The check comes before the path, so a stranger cannot learn
            # which paths exist by reading the codes that come back.
            if not self.authorized():
                return self.reply(401, {"error": "unauthorized"})
            if self.path == "/v1/status":
                return self.reply(200, status())
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            # The body is read before the check, because the signature
            # covers it. BODY_LIMIT is what keeps that read small.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= BODY_LIMIT:
                    raise ValueError
                body = self.rfile.read(length)
            except (ValueError, TypeError):
                return self.reply(400, {"error": "invalid request"})
            if not self.authorized(body):
                return self.reply(401, {"error": "unauthorized"})
            if self.path != "/v1/action":
                return self.reply(404, {"error": "not found"})
            try:
                name = json.loads(body)["action"]
            except (ValueError, KeyError, TypeError):
                return self.reply(400, {"error": "invalid request"})
            self.reply(*press(name))

    return Handler


def read_token(path):
    """The secret from its file, or a message that says what to do.

    A missing file is the ordinary state before the first install, so it
    gives a sentence and not a traceback in the journal.
    """
    try:
        token = Path(path).read_text().strip()
    except OSError as exc:
        raise SystemExit("cannot read %s: %s\n"
                         "Install the companion module to write one."
                         % (path, exc))
    if len(token) < TOKEN_MINIMUM:
        raise SystemExit("the token in %s is shorter than %d characters"
                         % (path, TOKEN_MINIMUM))
    return token


def serve(host="0.0.0.0", port=PORT, home=None):
    """Answers until the service stops."""
    token = read_token(token_path(home))
    ThreadingHTTPServer((host, port), make_handler(token)).serve_forever()
