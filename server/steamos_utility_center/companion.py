# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the Smart 86 Box panel reads from this machine, and what it can press.

The panel is an ESP32-S3 with a 4 inch touch screen on the wall. It has no
cable to this machine. It asks over the network every three seconds, and it
sends a press as a second request. firmware/companion holds its side.

This service answers five paths and nothing else:

    GET  /v1/status     the controllers, the audio and the sensors
    POST /v1/action     one of the named presses, Cooling Boost among them
    POST /v1/led        the effect of the LED bar, on the desktop and in the
                        rainbow slot of Game Mode, and the colour and the
                        brightness of the desktop scenes
    POST /v1/cpu        the energy profile of the CPU
    GET  /v1/firmware   the firmware of the panel, for its update

It runs in the session of the desktop user and never as root. That is not a
limitation to work around, it is the design: `systemctl suspend` and `wpctl`
both belong to a session, and a service with no root cannot lose more than
that session holds. The panel therefore reaches exactly what the person at
the keyboard reaches.

The LED bar and the CPU are no exception. Their settings are files of root,
and a change goes through the applier of its module with `sudo -n`. The rule
that permits this is the rule the installer writes for the plugin in Game
Mode. It names one program and one file for each module, so the panel gets
no right that the person at the keyboard does not have already. See
led_change and cpu_change.

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
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config as config_module
from . import ctl, desktop, lact, modules, notify, pairing, pcinfo, power
from . import render, screen, steamapps, steamcontroller
from . import temperature

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

# The pairing of a new panel. These two paths need no signature, because a
# new panel has no secret yet. See pairing.py.
PAIR_PATH = "/v1/pair"
PAIR_ID = re.compile(r"^%s/([0-9a-f]{16})$" % PAIR_PATH)

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

# The fan of the graphics card, the column on the page of the card: Cooling
# Boost, which holds the fan at full speed, and zero RPM, which lets it stop
# on a cool card. Two presses for each and not one, for the reason that
# desktop_mode and game_mode give above: where to go, and not "the other
# one".
#
# Each one is a call of ctl and not a command: the call that the plugin in
# Game Mode makes. It speaks to the LACT daemon over its socket as this user,
# and the socket is open to the group of the desktop user. See lact.py.
BOOST_PRESSES = {"gpu_boost_on": "gpu-boost-on",
                 "gpu_boost_off": "gpu-boost-off",
                 "gpu_zero_rpm_on": "gpu-zero-rpm-on",
                 "gpu_zero_rpm_off": "gpu-zero-rpm-off"}

# How old the answer about the boost in the status can be, and how long one
# question to LACT can take. The panel waits four seconds for the whole
# status, and a daemon that is slow to answer must not make the panel say that
# the PC is gone. See BoostState.
BOOST_EVERY = 5.0
BOOST_WAIT = 0.5

# The path of a change of the LED bar, and what a change can be. Each key of
# a request names one setting of the LED service, and its value must be in
# the list of that setting. The lists come from the service, so this table
# keeps no copy of them.
#
# "desktop" is the effect on the desktop, where Steam sets nothing. "game"
# is what the rainbow entry of the LED menu of Steam shows in Game Mode.
# Steam keeps the other entries of that menu, and nothing here changes them.
# See RAINBOW_SHOWS in the configuration file.
LED_PATH = "/v1/led"
# The path of a change of the CPU profile. Its one key is "profile", and the
# value is a profile that this machine offers. See power.PROFILES.
CPU_PATH = "/v1/cpu"
# What the panel keeps of the governor, the preference and the driver that
# run: 23 characters. The longest a kernel of 2026 writes is
# "balance_performance", at 19.
CPU_WORD = 23
LED_CHOICES = {"desktop": ("DESKTOP_SCENE", config_module.DESKTOP_SCENES),
               "game": ("RAINBOW_SHOWS", config_module.RAINBOW_CHOICES)}
# The profile of the mirror in each mode. It is not in LED_CHOICES, because
# the panel has one card for each key of that table.
LED_MIRROR = {"mirror_profile": ("MIRROR_PROFILE",
                                 config_module.MIRROR_PROFILES),
              "desktop_mirror_profile": ("DESKTOP_MIRROR_PROFILE",
                                         config_module.MIRROR_PROFILES)}
# The colour and the brightness of the scenes on the desktop. The same key is
# in the status and in a change, and the value is the setting of the LED
# service that the key names. desktop.SCENES_WITH_COLOUR and
# desktop.SCENES_LIT say which scenes use each one.
LED_LOOK = {"desktop_color": "DESKTOP_COLOR",
            "desktop_brightness": "DESKTOP_BRIGHTNESS"}
# The colours that a change can set: the nine colours that the control panel
# offers for DESKTOP_COLOR, in its order. The file accepts each colour, and
# the panel offers these and no others. tests/test_companion.py holds this
# list equal to the list of the control panel.
LED_COLOURS = ("#ff0000", "#ff8000", "#ffff00", "#00ff00", "#00ffff",
               "#0000ff", "#8000ff", "#ff00ff", "#ffffff")
# The limits of DESKTOP_BRIGHTNESS. config.validate has the same two.
LED_BRIGHTNESS = (0, 255)

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

# The clock of the card. amdgpu names the clock of its shader engine sclk
# in hwmon and counts it in hertz. A reading past SANE_MHZ is no clock.
SCLK_LABEL = "sclk"
HERTZ_PER_MHZ = 1000000
SANE_MHZ = 10000

# The levels of that clock, a file of the PCI device: one level on each
# line, as "1: 2450Mhz *", with a star at the level in use. The highest
# level is the top of the bar of the clock on the panel.
SCLK_LEVELS = "pp_dpm_sclk"
SCLK_LEVEL = re.compile(r"^\s*\d+:\s*(\d+)\s*mhz", re.IGNORECASE | re.MULTILINE)

# What the panel keeps of each list: PANEL_PADS, PANEL_SENSORS and
# PANEL_DRIVES in its ui.h. The answer stops there. An Intel processor
# reports a sensor for each core, and two of them on one board made an
# answer that the buffer of the panel did not hold. The panel reads such
# an answer as no answer at all.
PANEL_PADS = 4
PANEL_SENSORS = 6
PANEL_DRIVES = 3
# The name of the game, as long as the panel keeps it. It keeps 63 bytes,
# and those are inside the first 63 characters.
PLAYING_CHARS = 63

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

# The four parts of an image, at the names an ESP-IDF build gives them.
# ota_data_initial.bin is the empty otadata, which makes the first slot the
# one that boots after a flash over USB.
IMAGE_PARTS = (os.path.join("bootloader", "bootloader.bin"),
               os.path.join("partition_table", "partition-table.bin"),
               "ota_data_initial.bin",
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
    """Whether that directory holds all four parts of an image.

    All four or none. A directory with one of them is a build that stopped,
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


# The update of the panel over the network.
#
# The service offers the image that a flash over USB would write: the one CI
# built, in the copy of the toolbox the installer keeps, and only while its
# stamp matches the source beside it. A clone that runs this service from
# its own tree offers the image of that tree.
#
# The panel takes it only when the number of the build is higher than its
# own, and only when the offer carries a signature with the token: the
# answer to a status crosses the network unsigned, and the signature is what
# keeps a stranger on that network from offering an image of their own. The
# panel checks the SHA-256 of what it downloaded against the offer before it
# boots it. See firmware/companion/main/panel_update.c.
FIRMWARE_PATH = "/v1/firmware"
# esp_app_desc_t, which an ESP-IDF image carries after its header of 24
# bytes and the header of its first segment of 8. Its version is the
# PROJECT_VER of the build, "61-1eec536", at 16 bytes into it.
IMAGE_MAGIC = 0xE9
APP_DESC_OFFSET = 32
APP_DESC_MAGIC = 0xABCD5432
VERSION_AT = 16
VERSION_BYTES = 32
# A slot of the partition table. An image larger than that fits no slot.
SLOT_BYTES = 0x700000
# Where the installer keeps its copy of the toolbox, beside this package.
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
OFFER_ROOTS = (os.path.join(os.path.dirname(PACKAGE_DIR), "source"),
               os.path.dirname(os.path.dirname(PACKAGE_DIR)))


def image_version(path):
    """The version an ESP-IDF image carries, or None for no such image."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(APP_DESC_OFFSET + VERSION_AT + VERSION_BYTES)
    except OSError:
        return None
    if len(head) < APP_DESC_OFFSET + VERSION_AT + VERSION_BYTES:
        return None
    if head[0] != IMAGE_MAGIC:
        return None
    magic = int.from_bytes(head[APP_DESC_OFFSET:APP_DESC_OFFSET + 4],
                           "little")
    if magic != APP_DESC_MAGIC:
        return None
    raw = head[APP_DESC_OFFSET + VERSION_AT:]
    return raw.split(b"\0")[0].decode("ascii", errors="replace")


def build_number(version):
    """The number of a build, out of its version: 61 for "61-1eec536".

    0 for a version with no number in front, which is a build made by hand
    and lower than every build of the job.
    """
    found = re.match(r"\d+", version or "")
    return int(found.group(0)) if found else 0


def offer_signature(token, build, size, sha256):
    """What the panel checks an offer against. See panel_update.c."""
    message = "firmware\n%d\n%d\n%s" % (build, size, sha256)
    return hmac.new(token.encode(), message.encode(),
                    hashlib.sha256).hexdigest()


class FirmwareOffer:
    """The image the service offers, read once for each image.

    The fingerprint of the source and the SHA-256 of the image take a moment
    each, and the panel asks every three seconds. So both are read again
    only when the image on the disk changes.
    """

    def __init__(self, roots=OFFER_ROOTS):
        self.roots = roots
        self._seen = None
        self._found = None
        self._lock = threading.Lock()

    def _image(self):
        for root in self.roots:
            where = os.path.join(root, PREBUILT_DIR)
            if not image_is_complete(where):
                continue
            path = os.path.join(where, "steamos_companion.bin")
            return root, where, path
        return None

    def current(self):
        """{"build", "version", "size", "sha256", "path"}, or None."""
        found = self._image()
        if not found:
            return None
        root, where, path = found
        try:
            info = os.stat(path)
        except OSError:
            return None
        seen = (path, info.st_mtime_ns, info.st_size,
                image_stamp(where))
        with self._lock:
            if seen == self._seen:
                return self._found
        offer = None
        version = image_version(path)
        if (version is not None and 0 < info.st_size <= SLOT_BYTES
                and image_stamp(where) == firmware_fingerprint(root)):
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1 << 16), b""):
                    digest.update(block)
            offer = {"build": build_number(version), "version": version,
                     "size": info.st_size, "sha256": digest.hexdigest(),
                     "path": path}
        with self._lock:
            self._seen, self._found = seen, offer
        return offer

    def signed(self, token):
        """The offer as the status carries it: no path, and signed."""
        offer = self.current()
        if not offer or not token:
            return None
        return {"build": offer["build"], "version": offer["version"],
                "size": offer["size"], "sha256": offer["sha256"],
                "sign": offer_signature(token, offer["build"], offer["size"],
                                        offer["sha256"])}


_firmware = FirmwareOffer()


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


def card_state(place):
    """How busy the card is, its memory and its clock, or None for each.

    The load, the memory and the levels of the clock are files of the PCI
    device of the card. The clock is a file of its hwmon chip, which is the
    place that telemetry found, as the power is. amdgpu writes all five. A
    card of another driver writes none of them, and the panel then shows a
    dash.
    """
    out = {"gpu_load": None, "vram_used": None, "vram_total": None,
           "gpu_mhz": None, "gpu_mhz_max": None}
    if not place:
        return out
    device = os.path.join(place, "device")
    out["gpu_load"] = _sane(_read_number(
        os.path.join(device, "gpu_busy_percent")), 100)
    used = _read_number(os.path.join(device, "mem_info_vram_used"))
    total = _read_number(os.path.join(device, "mem_info_vram_total"))
    if total and used is not None and 0 <= used <= total:
        out["vram_used"], out["vram_total"] = int(used), int(total)
    if (_read_text(os.path.join(place, "freq1_label")) or "").lower() \
            == SCLK_LABEL:
        out["gpu_mhz"] = _sane(_read_number(
            os.path.join(place, "freq1_input"), HERTZ_PER_MHZ), SANE_MHZ)
    levels = [int(level) for level in SCLK_LEVEL.findall(
        _read_text(os.path.join(device, SCLK_LEVELS)) or "")]
    if levels:
        out["gpu_mhz_max"] = _sane(max(levels), SANE_MHZ)
    return out


# Names a person reads for the labels the drivers give their sensors. A
# label not here is shown as the driver writes it.
SENSOR_NAMES = {"edge": "Edge", "junction": "Junction (Hotspot)",
                "mem": "VRAM", "tctl": "Tctl", "tdie": "Tdie"}


def _sensor_name(sensor):
    label = sensor["label"]
    ccd = re.fullmatch(r"Tccd(\d+)", label)
    if ccd:
        return "CCD %s" % ccd.group(1)
    if not label:
        return os.path.basename(sensor["path"]).replace("_input", "")
    return SENSOR_NAMES.get(label.lower(), label)[:23]


def sensor_list(sensors):
    """Each sensor of one kind, as the panel offers it to choose from.

    The id is the chip and the label, and not the path: hwmon numbers its
    chips in the order they come up, and that order is not the same after
    each start. The panel stores the id it was given. The best answer comes
    first, which is the one the panel shows when nobody chose.
    """
    out = []
    for sensor in sorted(sensors, key=lambda one: (one["rank"],
                                                    one["path"])):
        name = (sensor["label"] or
                os.path.basename(sensor["path"]).replace("_input", ""))
        out.append({
            "id": ("%s/%s" % (sensor["chip"], name))[:31],
            "name": _sensor_name(sensor),
            "c": _sane(temperature.read_celsius(sensor["path"]),
                       SANE_CELSIUS),
        })
    return out


def telemetry(root=temperature.HWMON_ROOT):
    """The two temperatures, the power of the card and the rest of the
    card, or a None for each.

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
        # The rest of the card, for the page of its history. See card_state.
        **card_state(place),
        # Every sensor of the processor and of the card, for the choice on
        # the panel. The two above stay the answer when nobody chose.
        "cpu_sensors": sensor_list(
            [one for one in sensors
             if one["chip"].lower() in CPU_CHIPS])[:PANEL_SENSORS],
        "gpu_sensors": sensor_list(
            [one for one in sensors
             if os.path.dirname(one["path"]) == place])[:PANEL_SENSORS],
    }


# The load of the processor between two answers. See pcinfo.CpuLoad.
_cpu_load = pcinfo.CpuLoad()


def fans(root=temperature.HWMON_ROOT):
    """The fastest fan of the graphics card and of the rest, in rpm.

    None where no chip of that kind reports a fan, which is the case on a
    board whose fan chip has no driver loaded. The card is the one that
    telemetry reads, and the rest is every other chip.
    """
    place = _graphics_card(temperature.find_sensors(root))
    gpu, other = [], []
    for fan in temperature.find_fans(root):
        if fan["place"] == place:
            gpu.append(fan["rpm"])
        elif fan["chip"].lower() not in GPU_CHIPS:
            other.append(fan["rpm"])
    return {"fan": max(other) if other else None,
            "gpu_fan": max(gpu) if gpu else None}


def pc(address=None, root=temperature.HWMON_ROOT):
    """The page of the PC: the system, the hardware and the network.

    address is the one the panel connected to. See pcinfo.network.
    """
    place = _graphics_card(temperature.find_sensors(root))
    card = os.path.realpath(os.path.join(place, "device")) if place else None
    out = dict(pcinfo.system())
    out.update({
        "uptime": pcinfo.uptime(),
        "cpu": pcinfo.cpu_model(),
        "cpu_load": _cpu_load.percent(),
        "gpu": pcinfo.gpu_model(card),
        "memory": pcinfo.memory(),
    })
    out.update(fans(root))
    out["network"] = pcinfo.network(address)
    return out


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


def status(address=None, token=None, offer=None):
    """Everything one GET answers with.

    address is the one of this machine that the panel connected to, for the
    page of the PC. token signs the offer of a firmware: see FirmwareOffer.
    """
    offer = _firmware if offer is None else offer
    return {
        "host": os.uname().nodename,
        # The Steam Controller of 2026 first, because the panel shows the
        # first two and the kernel never reports that controller while Steam
        # runs. See steamcontroller.py.
        "controllers": numbered(steamcontroller.batteries() +
                                controllers())[:PANEL_PADS],
        "audio": audio(),
        "telemetry": telemetry(),
        # For the Wake button. None where this machine has no wired card,
        # and the panel then shows no such button. See wake_target.
        "wake": wake_target(),
        # What the panel shows on the page beside the first one.
        "session": session_mode(),
        # "" most of the time, and that is not a fault: most of the time
        # no game runs and the panel then shows nothing.
        "playing": (steamapps.now_playing() or "")[:PLAYING_CHARS],
        # {"achieved": 49, "total": 60}, or None for no game and for a
        # game with nothing to count. See steamapps.achievements.
        "achievements": steamapps.now_playing_achievements(),
        "drives": drives()[:PANEL_DRIVES],
        "pc": pc(address),
        # The two effects of the LED bar for its page, and the colour and
        # the brightness of the desktop scenes, or None where this machine
        # has no LED module. See led.
        "led": led(),
        # Whether Cooling Boost has the fan of the card, or None for no
        # switch. See BoostState.
        "boost": _boost.read(),
        # Whether zero RPM is on, or None for a card without it.
        "zero_rpm": _boost.zero_rpm(),
        # The energy profile of the CPU for its page, or None where this
        # machine has no power module. See cpu.
        "cpu": cpu(),
        # The firmware for the panel, or None. See FirmwareOffer.
        "firmware": offer.signed(token),
    }


def press(name):
    """Runs one named action. Returns (HTTP code, body) for the panel.

    A refusal comes back as a code and not as silence. The panel draws it,
    and somebody who presses "Suspend" and sees nothing happen otherwise has
    no way to tell a rejected press from a lost one.
    """
    if isinstance(name, str) and name in BOOST_PRESSES:
        return boost_press(BOOST_PRESSES[name])
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


class BoostState:
    """Whether Cooling Boost has the fan of the card, and whether zero RPM is
    on: True, False or None for each.

    None where this machine has no LACT, no card in it, or no answer in
    BOOST_WAIT. The panel shows no switch for None. Zero RPM is also None
    for a card without it.

    Three questions to the daemon, and one set in BOOST_EVERY seconds at the
    most, because the status comes every three seconds. A press makes the
    next status ask again, so the switch shows the press at once. The answer
    is the card and LACT and not a flag of ours, as for the plugin: somebody
    can set the same speed in LACT. See ctl.boosting and lact.zero_rpm.
    """

    def __init__(self, path=None, clock=time.monotonic):
        self.path = path
        self.clock = clock
        self._value = None
        self._zero_rpm = None
        self._at = None
        # ThreadingHTTPServer answers each request in a thread of its own.
        self._lock = threading.Lock()

    def read(self):
        """Whether Cooling Boost has the fan."""
        with self._lock:
            self._fresh()
            return self._value

    def zero_rpm(self):
        """Whether zero RPM is on, from the same answers as read."""
        with self._lock:
            self._fresh()
            return self._zero_rpm

    def _fresh(self):
        now = self.clock()
        if self._at is None or now - self._at >= BOOST_EVERY:
            self._value, self._zero_rpm = self._ask()
            self._at = now

    def forget(self):
        """The next read asks the daemon again."""
        with self._lock:
            self._at = None

    def _ask(self):
        if not lact.available(self.path):
            return None, None
        try:
            devices = lact.talk("list_devices", self.path, timeout=BOOST_WAIT)
            first = devices[0] if isinstance(devices, list) and devices else {}
            gpu = first.get("id", "") if isinstance(first, dict) else ""
            if not gpu:
                return None, None
            config = lact.talk("get_gpu_config", self.path, {"id": gpu},
                               timeout=BOOST_WAIT)
        except lact.LactError:
            return None, None
        config = config if isinstance(config, dict) else {}
        # The stats only for zero RPM. A daemon that does not give them
        # takes the button of zero RPM away, and not the boost.
        try:
            stats = lact.talk("device_stats", self.path, {"id": gpu},
                              timeout=BOOST_WAIT)
        except lact.LactError:
            stats = None
        return (ctl.boosting(lact.fan(config)),
                lact.zero_rpm(config, stats if isinstance(stats, dict) else {}))


_boost = BoostState()


def boost_press(action, run=None):
    """Runs one press of the fan of the card. Returns (HTTP code, body).

    The plugin in Game Mode holds its own switch while a change of the card
    waits for Keep it, because the boost keeps whatever waits. The panel
    cannot see that wait. It lasts five seconds, and a press of the panel in
    those seconds keeps the change of the plugin with the boost.
    """
    try:
        (ctl.ACTION[action] if run is None else run)()
    except ctl.CtlError as exc:
        return 501, {"error": str(exc)}
    except (lact.LactError, ValueError) as exc:
        sys.stderr.write("%s was refused: %s\n" % (action, exc))
        return 503, {"error": "LACT did not take the change"}
    finally:
        _boost.forget()
    return 200, {"ok": True}


class LedSettings:
    """The two effects of the LED bar, and the colour and the brightness of
    the desktop scenes, out of the file of the LED service.

    The panel asks every three seconds, and the file changes only when
    somebody changes a setting. So this reads the file again only when its
    time of change is new. The parser also writes a warning for each
    retired setting in the file, and with a read at each poll that was a
    line in the journal every three seconds.
    """

    def __init__(self, path=config_module.DEFAULT_CONFIG_PATH):
        self.path = path
        self._stamp = None
        self._values = None
        self._read = False
        # ThreadingHTTPServer answers each request in a thread of its own.
        self._lock = threading.Lock()

    def read(self):
        """{"desktop": scene, "game": effect of the rainbow slot,
        "desktop_color": "#rrggbb", "desktop_brightness": 0 to 255}, or
        None.

        None for a file with an error. The LED service does not start with
        such a file, so there is no effect to show.
        """
        try:
            stamp = os.stat(self.path).st_mtime_ns
        except OSError:
            stamp = None
        with self._lock:
            if not self._read or stamp != self._stamp:
                self._values = self._parse()
                self._stamp = stamp
                self._read = True
            return None if self._values is None else dict(self._values)

    def _parse(self):
        values = dict(config_module.DEFAULTS)
        try:
            if os.path.exists(self.path):
                values.update(config_module.parse_file(self.path))
            # The same check as the service does at its start. A value
            # outside its list is in no list of the panel either.
            config_module.validate(values)
        except (OSError, ValueError):
            return None
        found = {key: values[name] for key, (name, _) in LED_CHOICES.items()}
        # The file can name a colour as "#RRGGBB", "r,g,b" or the name of a
        # notification. The panel compares the colour with its own list, so
        # the status gives each colour in the one form of that list.
        found["desktop_color"] = "#%02x%02x%02x" % notify.parse_color(
            values[LED_LOOK["desktop_color"]])
        found["desktop_brightness"] = int(
            values[LED_LOOK["desktop_brightness"]])
        for key, (name, _) in LED_MIRROR.items():
            found[key] = values[name]
        return found


_led_settings = LedSettings()


def led(settings=None, present=None, mirror=screen.read_status):
    """The effects, the colour and the brightness for the page of the LED
    bar, or None.

    None where the LED module is not on this machine, or where its file has
    an error. The panel then shows a sentence in place of the buttons.

    With the mirror in Game Mode, also what the service that reads the
    screen does. It runs as this user, so its file is in the same runtime
    directory. The panel shows it below the effect.
    """
    if not modules.installed(modules.LED, present=present):
        return None
    values = (_led_settings if settings is None else settings).read()
    if values is not None and values.get("game") == render.SHOWS_MIRROR:
        values = dict(values, mirror=mirror())
    return values


# One change at a time for each module. A change of the LED bar starts the
# LED service again, and a second change that comes during the first must not
# overtake it.
_led_change = threading.Lock()
_cpu_change = threading.Lock()


def _change(write, updates, lock, what):
    """Gives one change to the applier of a module. Returns (code, body).

    Each refusal has a code of its own, which the panel names: 409 for a
    change while one runs, 501 for no module, 403 for no sudo rule, and 502
    for a change that the module refused.
    """
    if not lock.acquire(blocking=False):
        return 409, {"error": "a change is in progress"}
    try:
        write(updates)
    except ctl.NotInstalled:
        return 501, {"error": "the %s module is not installed" % what}
    except ctl.NotPermitted:
        # The installer ran with --no-sudoers, or before the module came.
        return 403, {"error": "no sudo rule permits the change"}
    except ValueError as exc:
        # CtlError and ConfigError are both a ValueError. The sentence goes
        # to the journal, where a person can read it, and the panel says
        # that the change did not come through.
        sys.stderr.write("The %s change was refused: %s\n" % (what, exc))
        return 502, {"error": "the change was refused"}
    finally:
        lock.release()
    return 200, {"ok": True}


def _led_look_takes(key, value):
    """Whether a change can set this value of LED_LOOK."""
    if key == "desktop_color":
        return isinstance(value, str) and value in LED_COLOURS
    # A JSON true is an int to Python, and it is no brightness.
    return (isinstance(value, int) and not isinstance(value, bool)
            and LED_BRIGHTNESS[0] <= value <= LED_BRIGHTNESS[1])


def led_change(request, write=None):
    """Applies one change from the page of the LED bar.

    Returns (HTTP code, body) for the panel. request is the JSON of the
    body: {"desktop": "fire"}, {"game": "ooze"}, {"desktop_color":
    "#ff0000"}, {"desktop_brightness": 200}, {"mirror_profile": "solid"},
    or more than one of these keys together. A key that is not in
    LED_CHOICES, LED_LOOK or LED_MIRROR, or a value that is not in its list
    or its limits, reaches nothing.

    The change goes through ctl.strip_write, as a change from the plugin in
    Game Mode does. The LED service checks the new file before the applier
    replaces the old one, and then the service starts again. That takes a
    second or two, and the panel waits for this answer.
    """
    if (not isinstance(request, dict) or not request
            or not set(request) <= (set(LED_CHOICES) | set(LED_LOOK)
                                    | set(LED_MIRROR))):
        return 400, {"error": "invalid request"}
    updates = {}
    for key, value in request.items():
        if key in LED_LOOK:
            if not _led_look_takes(key, value):
                return 400, {"error": "unsupported colour or brightness"}
            updates[LED_LOOK[key]] = value
            continue
        name, allowed = LED_CHOICES.get(key) or LED_MIRROR[key]
        if not isinstance(value, str) or value not in allowed:
            return 400, {"error": "unsupported effect"}
        updates[name] = value
    return _change(ctl.strip_write if write is None else write, updates,
                   _led_change, "LED")


def cpu(present=None, root=""):
    """The CPU for the page of the panel, or None.

    None where the power module is not on this machine, and where the
    machine has no cpufreq. The panel then shows a sentence in place of the
    buttons.

    "profile" is the profile of the settings file: a name of
    power.PROFILES, "steamos" for no setting, or "custom" for a setting of
    the control panel that no profile is. "offers" holds the profiles of
    this machine. "governor" and "epp" are what runs, which can differ from
    the file: "steamos" leaves the last governor in force until the next
    start. Files in sysfs and one in /etc, and no process.
    """
    if not modules.installed(modules.POWER, present=present):
        return None
    if not power.policies(root):
        return None
    running = power.current(root)
    return {"profile": power.profile_of(power.read(), root),
            "offers": power.profiles(root),
            "governor": running.get("CPU_GOVERNOR", "")[:CPU_WORD],
            "epp": running.get("CPU_EPP", "")[:CPU_WORD],
            "driver": power.driver(root)[:CPU_WORD]}


def cpu_change(request, write=None, root=""):
    """Applies one profile from the page of the CPU. Returns (code, body).

    request is the JSON of the body: {"profile": "balanced"}. A profile that
    this machine does not offer reaches nothing, and a key beside "profile"
    neither. The change goes through ctl.power_write, as a change from the
    plugin in Game Mode does: the applier checks it against the machine,
    writes sysfs and keeps it for the next start.
    """
    if not isinstance(request, dict) or set(request) != {"profile"}:
        return 400, {"error": "invalid request"}
    name = request["profile"]
    if not isinstance(name, str) or name not in power.profiles(root):
        return 400, {"error": "unsupported profile"}
    return _change(ctl.power_write if write is None else write,
                   power.profile_settings(name, root), _cpu_change, "CPU")


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


class Secret:
    """The token of the service, which a pairing can replace while it runs.

    A replacement goes into the file first, with mode 0600, and then into
    the memory. With no file, a replacement stays in the memory.
    """

    def __init__(self, value, path=None):
        self.path = path
        self._value = value or ""
        self._lock = threading.Lock()

    @property
    def value(self):
        with self._lock:
            return self._value

    def replace(self, value):
        with self._lock:
            if self.path:
                folder = os.path.dirname(self.path)
                os.makedirs(folder, mode=0o700, exist_ok=True)
                temporary = self.path + ".new"
                descriptor = os.open(temporary,
                                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                                     0o600)
                with os.fdopen(descriptor, "w") as handle:
                    handle.write(value + "\n")
                os.replace(temporary, self.path)
            self._value = value


def make_handler(token, nonces=None, offer=None, pair=None):
    """The request handler for one token, or for a Secret that holds it."""
    secret = token if isinstance(token, Secret) else Secret(token)
    nonces = Nonces() if nonces is None else nonces
    offer = _firmware if offer is None else offer
    pair = pairing.Pairing() if pair is None else pair

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
            token = secret.value
            if not nonce or not given or len(token) < TOKEN_MINIMUM:
                return False
            wanted = signature(token, self.command, self.path, nonce, body)
            # The signature first and the spend second. The other order lets
            # a stranger burn the nonce of the panel by guessing at it.
            if not hmac.compare_digest(given, wanted):
                return False
            return nonces.spend(nonce)

        def do_GET(self):
            # A new panel asks for the answer to its pairing. Each other
            # path needs the signature.
            asked = PAIR_ID.match(self.path)
            if asked:
                code, said, new = pair.check(asked.group(1))
                if new:
                    try:
                        secret.replace(new)
                    except OSError as exc:
                        sys.stderr.write("The new token cannot be saved: %s\n"
                                         % exc)
                        return self.reply(500, {"error": "not saved"})
                return self.reply(code, said)
            # The check comes before the path, so a stranger cannot learn
            # which paths exist by reading the codes that come back.
            if not self.authorized():
                return self.reply(401, {"error": "unauthorized"})
            if self.path == "/v1/status":
                return self.reply(200,
                                  status(self.connection.getsockname()[0],
                                         secret.value, offer))
            if self.path == FIRMWARE_PATH:
                return self.send_firmware()
            self.reply(404, {"error": "not found"})

        def send_firmware(self):
            """The image of the offer, as it is on the disk.

            The panel compares its SHA-256 with the signed offer before it
            boots it, so what goes out here needs no signature of its own.
            The socket waits five seconds on each block at most, which the
            panel meets: it erases its slot before it asks.
            """
            found = offer.current()
            if not found:
                return self.reply(404, {"error": "no firmware"})
            try:
                handle = open(found["path"], "rb")
            except OSError:
                return self.reply(404, {"error": "no firmware"})
            with handle:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(found["size"]))
                self.send_header(NONCE_HEADER, nonces.issue())
                self.end_headers()
                for block in iter(lambda: handle.read(1 << 14), b""):
                    self.wfile.write(block)

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
            if self.path == PAIR_PATH:
                try:
                    asked = json.loads(body)
                except ValueError:
                    return self.reply(400, {"error": "invalid request"})
                return self.reply(*pair.ask(asked, self.client_address[0]))
            if not self.authorized(body):
                return self.reply(401, {"error": "unauthorized"})
            if self.path not in ("/v1/action", LED_PATH, CPU_PATH):
                return self.reply(404, {"error": "not found"})
            try:
                request = json.loads(body)
            except ValueError:
                return self.reply(400, {"error": "invalid request"})
            if self.path == LED_PATH:
                return self.reply(*led_change(request))
            if self.path == CPU_PATH:
                return self.reply(*cpu_change(request))
            if not isinstance(request, dict) or "action" not in request:
                return self.reply(400, {"error": "invalid request"})
            self.reply(*press(request["action"]))

    return Handler


def read_token(path):
    """The secret from its file, or "" with no file.

    With no file the service still runs, because a pairing writes the file.
    Until then it refuses each request that needs the secret. A token that
    is too short is an error that a person must see.
    """
    try:
        token = Path(path).read_text().strip()
    except FileNotFoundError:
        sys.stderr.write("No token in %s yet. Pair a panel to write one.\n"
                         % path)
        return ""
    except OSError as exc:
        raise SystemExit("cannot read %s: %s" % (path, exc))
    if len(token) < TOKEN_MINIMUM:
        raise SystemExit("the token in %s is shorter than %d characters"
                         % (path, TOKEN_MINIMUM))
    return token


def serve(host="0.0.0.0", port=PORT, home=None):
    """Answers until the service stops.

    It also answers a panel that looks for the PC, on the same port number
    with UDP. See pairing.Responder.
    """
    path = token_path(home)
    secret = Secret(read_token(path), path)
    pairing.Responder(port).start()
    ThreadingHTTPServer((host, port), make_handler(secret)).serve_forever()
