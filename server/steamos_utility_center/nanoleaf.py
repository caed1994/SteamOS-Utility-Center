# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Nanoleaf devices on the network, and the effects they already hold.

These are the devices with the Open API: the Light Panels, Canvas, Shapes,
Elements, Lines and Skylight. The Essentials range has none, and the Pegboard
Desk Dock has none either. That board is USB only, and pegboard.py drives it.

This module plays the effects that a person put on the device with the app of
Nanoleaf. It draws no frame of its own.

-- why it draws none -------------------------------------------------------

The device takes a stream of frames as well, one colour for each panel, over
UDP on port 60222. Two measurements on a Lines said that route is not the one
to take for this project.

The first is the rate. Nanoleaf recommends no more than ten frames a second,
and ten is a quarter of what the LED bar and the Pegboard take.

The second is the shape. Each effect of this project draws a line of LEDs,
and a device of Nanoleaf is a surface: the Lines reported 81 panels with an x
and a y each. A line through a surface is a choice, and the first choice
tried was the angle of each panel around the middle of the shape. A walk over
that order on the real device jumped about instead of following the figure,
because the layout is two clusters and not a ring. A mapping that works needs
the shape of each model, and that is a project of its own.

So the effects of the device are the effects. It holds twenty-one of them on
the Lines here, and a person picks them in the app of Nanoleaf.

-- what this needs from the machine ----------------------------------------

Nothing. No root, no unit, no applier and no line in the sudoers file: an
effect on one of these is one HTTP call to an address on the LAN. This is
thus part of the core of this project and not a module, for the same reason
the keyboard layout is.

The record of the paired devices is in the home directory of the person who
paired them, beside the settings of the panel. The token in it needs no root,
and it is therefore not in /etc where every program on the machine reads it.

-- the protocol, from the documentation and one device ----------------------

Discovery is mDNS, the service `_nanoleafapi._tcp`, and the TXT record of an
answer carries the model in `md` and the firmware in `srcvers`.

The API is HTTP on port 16021 and has no HTTPS. That is safe on a LAN and it
must never face the internet.

A token comes from a POST to /api/v1/new, and the device gives one out for 30
seconds after a person holds its power button. A DELETE on /api/v1/<token>
takes that token back, and the device keeps its other tokens.

A name between asterisks is not an effect. *Solid*, *Dynamic* and *ExtControl*
are the modes of the device, and a select of one of those does nothing.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time
import urllib.error
import urllib.request

MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353
SERVICE = "_nanoleafapi._tcp.local"

API_PORT = 16021

# The records this reads out of an answer.
PTR, TXT, A, SRV = 12, 16, 1, 33

# How long one call waits.
#
# Short, because the window makes these calls and a person watches it. A
# device that is off or away must cost a moment and not a freeze.
TIMEOUT = 2.5

# How long a device gives a token out after the button. Nanoleaf documents 30.
PAIR_SECONDS = 30.0

# How many times follow() asks a device that did not answer, and the wait
# between two of those.
#
# For the way up only. The machine reaches its targets before a switch has
# learnt where a lamp is, so the first call to a device one second after a
# boot fails and the same call a moment later works. Five tries three seconds
# apart is fifteen seconds in the worst case, and nothing waits for it: the
# unit is wanted by multi-user.target and ordered before nothing.
#
# On the way down there is one try. The machine is on its way to off, and a
# lamp that missed the message is a lamp that stays lit until the next boot,
# which is better than a shutdown that waits fifteen seconds for it.
FOLLOW_TRIES = 5
FOLLOW_GAP = 3.0

CONFIG_DIR = ".config"
CONFIG_FILE = "steamos-utility-center-nanoleaf.json"

# The fields of one device in the record. Nothing else is written.
FIELDS = ("name", "model", "ip", "token")


class NanoleafError(Exception):
    """A device that refused, or a record that is not usable."""


# -- the names on the wire ---------------------------------------------------

def _name_bytes(text):
    """A dotted name as the labels that a DNS question carries."""
    out = bytearray()
    for label in text.split("."):
        if label:
            out.append(len(label))
            out += label.encode("ascii")
    out.append(0)
    return bytes(out)


def _read_name(data, at):
    """A name from a message, and where it ends.

    A name is a list of labels, and a label can be a pointer to a label
    earlier in the same message. The end to report is the end of this name
    and not the end of the name it points at.
    """
    labels = []
    after = None
    for _step in range(64):                     # a guard against a loop
        if at >= len(data):
            break
        length = data[at]
        if length == 0:
            at += 1
            break
        if length & 0xC0 == 0xC0:
            if after is None:
                after = at + 2
            at = struct.unpack_from("!H", data, at)[0] & 0x3FFF
            continue
        at += 1
        labels.append(data[at:at + length].decode("ascii", "replace"))
        at += length
    return ".".join(labels), (at if after is None else after)


def _records(data):
    """Every record of an answer, as (name, type, body, whole, at)."""
    counts = struct.unpack_from("!HHHH", data, 4)
    at = 12
    for _question in range(counts[0]):
        _asked, at = _read_name(data, at)
        at += 4
    out = []
    for _record in range(sum(counts[1:])):
        name, at = _read_name(data, at)
        if at + 10 > len(data):
            break
        rtype, _rclass, _ttl, length = struct.unpack_from("!HHIH", data, at)
        at += 10
        out.append((name, rtype, data[at:at + length], data, at))
        at += length
    return out


def _texts(body):
    """The key=value pairs of a TXT record."""
    out = {}
    at = 0
    while at < len(body):
        length = body[at]
        at += 1
        piece = body[at:at + length].decode("ascii", "replace")
        at += length
        key, sign, value = piece.partition("=")
        if sign:
            out[key] = value
    return out


def find(seconds=3.0):
    """The devices that answer the service query of Nanoleaf.

    The question carries the bit that asks for a unicast answer, and this
    listens on the port it sent from. A query from port 5353 needs that port,
    and on a desktop the mDNS daemon already holds it.

    Silence is not proof of an empty network: a router that drops multicast
    gives the same silence. So the window takes an address by hand as well.
    """
    question = (struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
                + _name_bytes(SERVICE)
                + struct.pack("!HH", PTR, 0x8001))
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    except OSError:
        return []
    sock.settimeout(0.4)
    found = {}
    hosts = {}
    ends = time.monotonic() + seconds
    asked = 0.0
    try:
        while time.monotonic() < ends:
            if time.monotonic() >= asked:
                try:
                    sock.sendto(question, (MDNS_GROUP, MDNS_PORT))
                except OSError:
                    break
                asked = time.monotonic() + 1.0
            try:
                data, _where = sock.recvfrom(9000)
            except (socket.timeout, OSError):
                continue
            for name, rtype, body, whole, at in _records(data):
                if rtype == A and len(body) == 4:
                    hosts[name] = socket.inet_ntoa(body)
                elif rtype == SRV:
                    target, _end = _read_name(whole, at + 6)
                    found.setdefault(name, {})["host"] = target
                elif rtype == TXT and SERVICE in name:
                    found.setdefault(name, {}).update(_texts(body))
    finally:
        sock.close()
    out = []
    for name, what in sorted(found.items()):
        where = hosts.get(what.get("host", ""), "")
        if not where:
            continue
        out.append({"name": name.split("." + SERVICE)[0],
                    "model": what.get("md", ""),
                    "firmware": what.get("srcvers", ""),
                    "ip": where})
    return out


# -- the calls ---------------------------------------------------------------

def call(ip, path, method="GET", body=None, timeout=TIMEOUT):
    """One call to the Open API, with the answer parsed if it is JSON.

    Every caller of this module is a window or a control command, so a device
    that refuses raises NanoleafError with the reason in it and never a
    traceback from urllib.
    """
    url = "http://%s:%d%s" % (ip, API_PORT, path)
    data = None if body is None else json.dumps(body).encode("utf-8")
    ask = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(ask, timeout=timeout) as answer:
            raw = answer.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise NanoleafError("%s does not know that token any more" % ip)
        raise NanoleafError("%s refused: %s %s" % (ip, exc.code, exc.reason))
    except (urllib.error.URLError, OSError) as exc:
        raise NanoleafError("%s did not answer: %s" % (ip, exc))
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}


def pair_once(ip):
    """Asks one device for a token. None means it is not in the window."""
    try:
        said = call(ip, "/api/v1/new", method="POST")
    except NanoleafError:
        return None
    return said.get("auth_token") or None


def pair(ips, seconds=PAIR_SECONDS, now=None, rest=None):
    """Asks each of those devices for a token until one answers.

    A device gives a token out for 30 seconds after a person holds its power
    button, so this asks and asks rather than asking one time. A person then
    holds the button on the device they want and that device answers, and the
    window needs no list to pick from and no address typed.

    `now` and `rest` are parameters so a test can run this with no clock.
    """
    now = time.monotonic if now is None else now
    rest = time.sleep if rest is None else rest
    ends = now() + seconds
    while now() < ends:
        for ip in ips:
            token = pair_once(ip)
            if token:
                return ip, token
        rest(1.0)
    return None, None


def forget(ip, token):
    """Takes that token back. The device keeps its other tokens.

    The button that removes a device calls this. A removal that left the
    token on the device would leave a key to it on every machine that ever
    paired with it.
    """
    call(ip, "/api/v1/%s" % token, method="DELETE")


def document(ip, token):
    """Everything the device says about itself, in one call."""
    return call(ip, "/api/v1/%s/" % token)


def look(device):
    """The state of that device now, and what it can do.

    It never raises. The window draws one row for each device of the record,
    and a device that is off or away is a row with a reason on it and not a
    window that stops.
    """
    out = dict(device)
    out.update({"ok": False, "on": None, "brightness": None,
                "effect": "", "effects": (), "error": ""})
    try:
        said = document(device["ip"], device["token"])
    except NanoleafError as exc:
        out["error"] = str(exc)
        return out
    state = said.get("state", {})
    effects = said.get("effects", {})
    chosen = effects.get("select", "")
    out.update({
        "ok": True,
        "on": bool(state.get("on", {}).get("value")),
        "brightness": state.get("brightness", {}).get("value"),
        # A mode is not an effect, so it is reported as no effect at all.
        # See the note at the top of this file.
        "effect": "" if chosen.startswith("*") else chosen,
        "effects": tuple(effects.get("effectsList", ())),
        "name": said.get("name") or device.get("name", ""),
        "model": said.get("model") or device.get("model", ""),
    })
    return out


def select(device, effect):
    """Plays one of the effects that the device holds."""
    if effect.startswith("*"):
        raise NanoleafError("%s is a mode of the device and not an effect"
                            % effect)
    call(device["ip"], "/api/v1/%s/effects" % device["token"], method="PUT",
         body={"select": effect})


def switch(device, on):
    """Turns the device on or off."""
    call(device["ip"], "/api/v1/%s/state" % device["token"], method="PUT",
         body={"on": {"value": bool(on)}})


def dim(device, level):
    """Sets the brightness, which the device counts from 0 to 100."""
    level = max(0, min(int(level), 100))
    call(device["ip"], "/api/v1/%s/state" % device["token"], method="PUT",
         body={"brightness": {"value": level}})


def follow(state, home=None, tries=None, rest=None):
    """Turns every paired device on, or off, and says what it did.

    This is what makes the lights follow the machine: on at a boot and at a
    wake, off at a suspend and at a shutdown. The units call it. See
    server/steamos-utility-center-nanoleaf.

    It never raises. A device that is away must not stop the others, and a
    unit that failed while the machine went off is a message that nobody
    reads.

    A device that did not answer is asked again, and only that one. That is
    for the way up: see FOLLOW_TRIES.
    """
    rest = time.sleep if rest is None else rest
    if tries is None:
        tries = FOLLOW_TRIES if state else 1
    left = read(home)
    done = []
    trouble = []
    for turn in range(max(1, int(tries))):
        if not left:
            break
        if turn:
            rest(FOLLOW_GAP)
        again = []
        trouble = []
        for one in left:
            try:
                switch(one, state)
            except NanoleafError as exc:
                again.append(one)
                trouble.append("%s: %s" % (one.get("name") or one["ip"], exc))
            else:
                done.append(one.get("name") or one["ip"])
        left = again
    return {"state": bool(state), "done": done, "trouble": trouble}


def main(argv=None):
    """The three units call this with "on" or "off".

    See server/steamos-utility-center-nanoleaf.service, which turns the
    lights on at a boot and off at a shutdown, and the sleep and resume units
    beside it, which hold the two sides of a suspend.

    It returns zero either way. A lamp that did not answer is not a fault of
    this machine, and a unit that fails at every suspend is a red line in
    `systemctl status` for ever. What happened is in the journal.
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 1 or argv[0] not in ("on", "off"):
        print("usage: steamos-utility-center-nanoleaf on|off",
              file=sys.stderr)
        return 2
    said = follow(argv[0] == "on")
    if not said["done"] and not said["trouble"]:
        print("no Nanoleaf device on the network is paired here")
        return 0
    if said["done"]:
        print("%s: %s" % ("on" if said["state"] else "off",
                          ", ".join(said["done"])))
    for line in said["trouble"]:
        print(line, file=sys.stderr)
    return 0


# -- the record --------------------------------------------------------------

def path(home=None):
    """Where the record lives. `home` is a parameter so a test can move it.

    The home directory of the person who paired the devices. A token needs
    no root, so it is not in /etc where every program on the machine reads
    it, and the control command reads the same file in Game Mode because
    the plugin gives it the HOME of the session.
    """
    return os.path.join(home or os.path.expanduser("~"), CONFIG_DIR,
                        CONFIG_FILE)


def validate(devices):
    """Refuses a record that the rest of this module cannot use."""
    if not isinstance(devices, list):
        raise NanoleafError("the record is not a list of devices")
    seen = set()
    for one in devices:
        if not isinstance(one, dict):
            raise NanoleafError("a device in the record is not an object")
        for field in ("ip", "token"):
            if not str(one.get(field, "")).strip():
                raise NanoleafError("a device in the record has no %s"
                                    % field)
        if one["token"] in seen:
            raise NanoleafError("two devices in the record share a token")
        seen.add(one["token"])
    return devices


def read(home=None):
    """The paired devices. No file is the normal condition of a new machine.

    A file that cannot be read or parsed gives an empty list and not an
    error. The window then offers to pair, which is the one thing a person
    can do about it, and a broken file never stops the panel from opening.
    """
    try:
        with open(path(home), encoding="utf-8") as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        return []
    try:
        validate(found)
    except NanoleafError:
        return []
    return [{field: one.get(field, "") for field in FIELDS} for one in found]


def text(devices):
    """That record as the text of the file."""
    return json.dumps([{field: one.get(field, "") for field in FIELDS}
                       for one in validate(devices)],
                      indent=2, sort_keys=True) + "\n"


def write(devices, home=None):
    """Writes the record, and makes its directory if it is not there.

    The file holds a token for each device, so it is readable by its owner
    and by nobody else. It needs no root, and a file in /etc would need one
    and would be readable by every program on the machine.
    """
    where = path(home)
    room = os.path.dirname(where)
    if room:
        os.makedirs(room, exist_ok=True)
    body = text(devices)
    handle = os.open(where, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(handle, body.encode("utf-8"))
    finally:
        os.close(handle)
    # A file that another version wrote with wider rights is narrowed here.
    os.chmod(where, 0o600)
    return where


def add(device, home=None):
    """Puts one device into the record, or replaces it where it is there.

    The token is what says "this device", because a name repeats on a
    network and an address moves with the lease.
    """
    devices = [one for one in read(home)
               if one["token"] != device.get("token")]
    devices.append({field: device.get(field, "") for field in FIELDS})
    write(devices, home)
    return devices


def remove(token, home=None):
    """Takes one device out of the record. It does not call the device."""
    devices = [one for one in read(home) if one["token"] != token]
    write(devices, home)
    return devices


def refresh(devices, seconds=3.0, finder=None):
    """The same devices with the address each one answers on now.

    A lease moves, and a record with the old address is a device that stopped
    answering for no reason a person can see. The name of the device is what
    joins the two, because that is what mDNS reports and it does not change
    with the lease.

    A device that mDNS does not report keeps the address in the record: a
    router that drops multicast must not empty the list.
    """
    finder = find if finder is None else finder
    live = dict((one["name"], one) for one in finder(seconds) if one["name"])
    out = []
    for one in devices:
        found = live.get(one.get("name", ""))
        moved = dict(one)
        if found and found.get("ip"):
            moved["ip"] = found["ip"]
            moved["model"] = found.get("model") or one.get("model", "")
        out.append(moved)
    return out
