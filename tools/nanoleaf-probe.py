#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asks a Nanoleaf device on the network what it is and what it takes.

This writes nothing to the machine and installs nothing. It is the step
before the module, the way the first look at the Pegboard Desk Dock was the
step before that one: the answers decide the design. On the board the probe
gave 40 frames a second and not 60, GRB and not RGB, and four reports for
one frame. Each of those three is now a line of the module.

The Open API of Nanoleaf is local and needs no cloud. The devices with one
are the Light Panels, Canvas, Shapes, Elements, Lines and Skylight. The
Essentials range has none, and the Pegboard Desk Dock has none either: that
board is USB only, which this project already knows.

    tools/nanoleaf-probe.py find
    tools/nanoleaf-probe.py pair
    tools/nanoleaf-probe.py read  --ip 192.168.1.41 --token XXXX
    tools/nanoleaf-probe.py walk  --ip 192.168.1.41 --token XXXX
    tools/nanoleaf-probe.py stream --ip 192.168.1.41 --token XXXX
    tools/nanoleaf-probe.py forget --ip 192.168.1.41 --token XXXX

What each answer decides:

    find    whether mDNS reaches the devices, and which models are there.
    pair    whether the firmware still gives a token out.
    read    the count of panels, their ids and where each one is. Our
            effects draw a line and a device is a surface, so the order of
            the panels along that line is a choice this makes from the x
            and y of each one.
    walk    which physical path that order is. The board needed this: the
            walk said "up the left side, then down the right", and that one
            sentence is the whole layout of the board in the module.
    stream  the rate. Nanoleaf recommends no more than 10 a second, and a
            measurement on the machine beats a recommendation.
    forget  whether a token can be taken back. The window needs that for
            the button that removes a device, and a person who read a token
            out loud needs it at once.
"""

import argparse
import json
import math
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
STREAM_PORT = 60222

# The records this reads out of an answer.
PTR, TXT, A, SRV = 12, 16, 1, 33

# How long each frame takes to arrive at its colour, in units of 100ms.
#
# One unit is the gap of a stream at ten frames a second, so each frame
# arrives as the next one goes out and the movement has no steps in it.
TRANSITION = 1

HTTP_TIMEOUT = 4.0


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
    """Every record of an answer, as (name, type, body)."""
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


def find(seconds=4.0):
    """The devices that answer the service query of Nanoleaf.

    The question carries the bit that asks for a unicast answer, and this
    listens on the port it sent from. A query to port 5353 needs that port,
    and on a desktop the mDNS daemon already holds it.

    A device that answers nothing is not a device that cannot be reached:
    a router that drops multicast gives the same silence. That is what
    --ip is for.
    """
    question = (struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
                + _name_bytes(SERVICE)
                + struct.pack("!HH", PTR, 0x8001))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    sock.settimeout(0.4)
    found = {}
    hosts = {}
    ends = time.monotonic() + seconds
    asked = 0.0
    while time.monotonic() < ends:
        if time.monotonic() >= asked:
            try:
                sock.sendto(question, (MDNS_GROUP, MDNS_PORT))
            except OSError as exc:
                print("could not ask: %s" % exc, file=sys.stderr)
                break
            asked = time.monotonic() + 1.0
        try:
            data, _where = sock.recvfrom(9000)
        except socket.timeout:
            continue
        for name, rtype, body, whole, at in _records(data):
            if rtype == A and len(body) == 4:
                hosts[name] = socket.inet_ntoa(body)
            elif rtype == SRV:
                target, _end = _read_name(whole, at + 6)
                port = struct.unpack_from("!H", body, 4)[0]
                found.setdefault(name, {})["host"] = target
                found[name]["port"] = port
            elif rtype == TXT and SERVICE in name:
                found.setdefault(name, {}).update(_texts(body))
    sock.close()
    out = []
    for name, what in sorted(found.items()):
        what["name"] = name.split("." + SERVICE)[0]
        what["ip"] = hosts.get(what.get("host", ""), "")
        out.append(what)
    return out


# -- the REST half -----------------------------------------------------------

def call(ip, path, method="GET", body=None, port=API_PORT):
    """One call to the Open API. It returns the answer, parsed if it is JSON.

    The API is HTTP and has no HTTPS, which is safe on a LAN and must never
    face the internet.
    """
    url = "http://%s:%d%s" % (ip, port, path)
    data = None if body is None else json.dumps(body).encode("utf-8")
    ask = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(ask, timeout=HTTP_TIMEOUT) as answer:
        raw = answer.read()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return {"raw": raw.decode("utf-8", "replace")}


def pair(ips, seconds=30.0):
    """Asks each device for a token until one of them gives one.

    A device gives a token out for 30 seconds after a person holds its power
    button. So this asks and asks rather than asking one time: a person holds
    the button on the device they want, and that device answers.

    This is the part of the design that decides the window. A list to pick
    from needs the name of the device and the person needs to know which name
    is which. A countdown needs neither.
    """
    ends = time.monotonic() + seconds
    while time.monotonic() < ends:
        left = int(round(ends - time.monotonic()))
        print("\r  %2d seconds left" % left, end="", flush=True)
        for ip in ips:
            try:
                said = call(ip, "/api/v1/new", method="POST")
            except (urllib.error.URLError, OSError):
                continue
            token = said.get("auth_token")
            if token:
                print()
                return ip, token
        time.sleep(1.0)
    print()
    return None, None


def document(ip, token):
    """Everything the device says about itself, in one call."""
    return call(ip, "/api/v1/%s/" % token)


def panels(said):
    """The panels of that document, in the order our effects would take.

    An effect of this project draws a line of LEDs and a device of Nanoleaf
    is a surface. So the panels are sorted by their angle around the middle
    of the shape, and an effect then travels around it. That is the same
    answer the Pegboard Desk Dock got, where the chain goes up one side and
    down the other.

    The path starts at the left of the shape and turns the way a clock does
    not. Where it starts is not a decision: a ring has no first panel, and
    COLOR_SHIFT moves an effect along the path anyway.

    Every entry is kept, the controller of the device included. Some models
    report it in this list and it carries no light, and a probe that dropped
    an id on a guess would hide the one thing the walk is here to find. The
    walk names each id as it lights it, so an id with no light reports
    itself.
    """
    layout = said.get("panelLayout", {}).get("layout", {})
    rows = [one for one in layout.get("positionData", [])
            if "panelId" in one and "x" in one and "y" in one]
    if not rows:
        return []
    middle_x = sum(one["x"] for one in rows) / float(len(rows))
    middle_y = sum(one["y"] for one in rows) / float(len(rows))

    def angle(one):
        return math.atan2(one["y"] - middle_y, one["x"] - middle_x)

    return sorted(rows, key=angle)


def frame(order, colours, transition=TRANSITION):
    """One v2 frame for the stream.

    nPanels is two bytes, then for each panel: the id in two bytes, red,
    green, blue and white in one each, and the transition in two. Version 1
    has one byte for the three wide fields and carries a frame count as
    well, and only the oldest Light Panels speak it.
    """
    out = bytearray(struct.pack("!H", len(order)))
    for one, (red, green, blue) in zip(order, colours):
        out += struct.pack("!HBBBBH", one["panelId"], red, green, blue, 0,
                           transition)
    return bytes(out)


def external(ip, token):
    """Puts the device into the streaming mode, and says where to send.

    Canvas and the models after it answer with nothing and take the stream at
    their own address. The Light Panels answer with an address and a port of
    their own, so this reads the answer rather than assuming.
    """
    said = call(ip, "/api/v1/%s/effects" % token, method="PUT",
                body={"write": {"command": "display",
                                "animType": "extControl",
                                "extControlVersion": "v2"}})
    where = said.get("streamControlIpAddr") or ip
    port = said.get("streamControlPort") or STREAM_PORT
    return where, int(port)


def forget(ip, token):
    """Takes that token back. The device keeps its other tokens.

    One DELETE on the token itself. This is what the window needs for the
    button that removes a device: a removal that left the token on the
    device would leave a key to it on every machine that ever paired.
    """
    return call(ip, "/api/v1/%s" % token, method="DELETE")


def selected(ip, token):
    """Which effect the device draws now, so this can give it back."""
    try:
        said = call(ip, "/api/v1/%s/effects/select" % token)
    except (urllib.error.URLError, OSError):
        return None
    return said if isinstance(said, str) else None


def restore(ip, token, effect):
    """Selects that effect again. The streaming mode ends with it."""
    if not effect:
        return
    try:
        call(ip, "/api/v1/%s/effects" % token, method="PUT",
             body={"select": effect})
    except (urllib.error.URLError, OSError):
        pass


# -- what each command prints ------------------------------------------------

def do_find(args):
    print("Asking for %s, %.0f seconds" % (SERVICE, args.seconds))
    devices = find(args.seconds)
    if not devices:
        print("\nNothing answered.")
        print("A router that drops multicast gives the same silence as an "
              "empty network.")
        print("Try: tools/nanoleaf-probe.py pair --ip <address of the device>")
        return 1
    print()
    for one in devices:
        print("  %-22s %-15s model %-10s firmware %s"
              % (one.get("name", "?"), one.get("ip", "?"),
                 one.get("md", "?"), one.get("srcvers", "?")))
    print("\n%d device(s). The id of each one is in its TXT record."
          % len(devices))
    return 0


def do_pair(args):
    ips = [args.ip] if args.ip else [one["ip"] for one in find(args.seconds)
                                     if one.get("ip")]
    if not ips:
        print("No device to ask. Give --ip <address>.")
        return 1
    print("Hold the power button on the device for 5 to 7 seconds, until "
          "its LEDs flash.")
    print("Asking: %s" % ", ".join(ips))
    ip, token = pair(ips)
    if not token:
        print("No device gave a token.")
        print("The button holds the window open for 30 seconds, so hold it "
              "first and then run this.")
        return 1
    print("Paired with %s" % ip)
    print("  token: %s" % token)
    print("\nKeep it. It is the whole of the authorisation, it works on the "
          "LAN only, and a second one needs the button again.")
    return 0


def do_read(args):
    said = document(args.ip, args.token)
    order = panels(said)
    print("name        %s" % said.get("name", "?"))
    print("model       %s" % said.get("model", "?"))
    print("firmware    %s" % said.get("firmwareVersion", "?"))
    print("serial      %s" % said.get("serialNo", "?"))
    state = said.get("state", {})
    print("on          %s" % state.get("on", {}).get("value"))
    print("brightness  %s" % state.get("brightness", {}).get("value"))
    print("effect      %s" % said.get("effects", {}).get("select"))
    print("panels      %d" % len(order))
    layout = said.get("panelLayout", {}).get("layout", {})
    print("shape       %s, side length %s"
          % (layout.get("numPanels"), layout.get("sideLength")))
    print("\nThe order our effects would take, around the middle of the "
          "shape:")
    print("  %4s %6s %6s %6s  %s" % ("step", "id", "x", "y", "orientation"))
    for step, one in enumerate(order):
        print("  %4d %6d %6d %6d  %s"
              % (step, one["panelId"], one["x"], one["y"], one.get("o")))
    print("\nEffects on the device: %s"
          % ", ".join(said.get("effects", {}).get("effectsList", [])))
    return 0


def do_walk(args):
    """One panel at a time, so a person can write down the path.

    This is the measurement that gave the board its layout. The answer is a
    sentence and not a number: "it started at the bottom left, went up the
    left side, then from the top right down to the bottom right."
    """
    said = document(args.ip, args.token)
    order = panels(said)
    if not order:
        print("The device reports no panels.")
        return 1
    was = selected(args.ip, args.token)
    where, port = external(args.ip, args.token)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print("Lighting one panel at a time, %.1f seconds each. Watch the device."
          % args.hold)
    print("Say which panel of the shape lights up at each step.\n")
    try:
        for step, one in enumerate(order):
            colours = [(0, 0, 0)] * len(order)
            colours[step] = (255, 255, 255)
            print("  step %2d of %2d   id %-6d x %-6d y %-6d"
                  % (step + 1, len(order), one["panelId"], one["x"], one["y"]))
            ends = time.monotonic() + args.hold
            while time.monotonic() < ends:
                sock.sendto(frame(order, colours), (where, port))
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.sendto(frame(order, [(0, 0, 0)] * len(order)), (where, port))
        sock.close()
        restore(args.ip, args.token, was)
    print("\nThe device has its effect back: %s" % (was or "none"))
    return 0


def do_stream(args):
    """A ladder of rates, so a person can say where it stops being clean.

    Nanoleaf recommends no more than ten a second. The board recommended
    nothing and took 40, and 45 flashed single LEDs: the measurement is the
    answer and the recommendation is the guess.

    UDP says nothing back, so the sender cannot see a dropped frame. The eye
    can. This announces each rate and holds it, and a person reports the last
    clean one.
    """
    said = document(args.ip, args.token)
    order = panels(said)
    if not order:
        print("The device reports no panels.")
        return 1
    was = selected(args.ip, args.token)
    where, port = external(args.ip, args.token)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rates = [int(one) for one in args.rates.split(",")]
    print("%d panels, streaming to %s:%d" % (len(order), where, port))
    print("One bright panel travels around the shape. Watch for steps in "
          "the movement.\n")
    try:
        for rate in rates:
            print("  %2d frames a second, %.0f seconds" % (rate, args.hold))
            gap = 1.0 / rate
            sent = 0
            started = time.monotonic()
            ends = started + args.hold
            while time.monotonic() < ends:
                at = int((time.monotonic() - started) * rate) % len(order)
                colours = [(6, 0, 12)] * len(order)
                colours[at] = (255, 140, 0)
                sock.sendto(frame(order, colours), (where, port))
                sent += 1
                time.sleep(gap)
            took = time.monotonic() - started
            print("     sent %d frames in %.1f s, which is %.1f a second"
                  % (sent, took, sent / took))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.sendto(frame(order, [(0, 0, 0)] * len(order)), (where, port))
        sock.close()
        restore(args.ip, args.token, was)
    print("\nThe device has its effect back: %s" % (was or "none"))
    print("Report the highest rate with no steps in the movement.")
    return 0


def do_forget(args):
    forget(args.ip, args.token)
    print("The device no longer knows that token.")
    print("Pair again to get another one. The button opens the window.")
    return 0


def main(argv=None):
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--ip", help="the address of the device")
    parent.add_argument("--token", help="the token that pairing gave")

    parser = argparse.ArgumentParser(
        prog="nanoleaf-probe",
        description="Asks a Nanoleaf device on the network what it takes.")
    commands = parser.add_subparsers(dest="command", required=True)

    one = commands.add_parser("find", parents=[parent],
                              help="the devices that answer mDNS")
    one.add_argument("--seconds", type=float, default=4.0)
    one.set_defaults(run=do_find)

    one = commands.add_parser("pair", parents=[parent],
                              help="ask for a token, button held")
    one.add_argument("--seconds", type=float, default=4.0)
    one.set_defaults(run=do_pair)

    one = commands.add_parser("read", parents=[parent],
                              help="the device, its panels and their order")
    one.set_defaults(run=do_read)

    one = commands.add_parser("walk", parents=[parent],
                              help="one panel at a time, to learn the path")
    one.add_argument("--hold", type=float, default=1.5)
    one.set_defaults(run=do_walk)

    one = commands.add_parser("stream", parents=[parent],
                              help="a ladder of frame rates")
    one.add_argument("--hold", type=float, default=6.0)
    one.add_argument("--rates", default="5,10,15,20,30")
    one.set_defaults(run=do_stream)

    one = commands.add_parser("forget", parents=[parent],
                              help="take a token back")
    one.set_defaults(run=do_forget)

    args = parser.parse_args(argv)
    if (args.run in (do_read, do_walk, do_stream, do_forget)
            and not (args.ip and args.token)):
        parser.error("%s needs --ip and --token" % args.command)
    try:
        return args.run(args)
    except urllib.error.HTTPError as exc:
        print("The device refused: %s %s" % (exc.code, exc.reason),
              file=sys.stderr)
        if exc.code == 401:
            print("401 is a token that the device does not know. Pair again.",
                  file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print("Could not reach the device: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
