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
import math
import os
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))

from steamos_utility_center import nanoleaf                    # noqa: E402
from steamos_utility_center.nanoleaf import (                  # noqa: E402
    API_PORT, NanoleafError, PTR, SERVICE, SRV, TXT, A,
    _name_bytes, _read_name, _records, _texts, call, document, find, forget,
    pair)

# Where a device takes a stream of frames.
#
# This module streams and nanoleaf.py does not. The rate and the shape are
# why: see the note at the top of that file. The probe keeps the code,
# because the two measurements that settled it were taken with it.
STREAM_PORT = 60222

# How long each frame takes to arrive at its colour, in units of 100ms.
#
# One unit is the gap of a stream at ten frames a second, so each frame
# arrives as the next one goes out and the movement has no steps in it.
TRANSITION = 1


def panels(said):
    """The panels of that document, in the order our effects would take.

    An effect of this project draws a line of LEDs and a device of Nanoleaf
    is a surface. So the panels are sorted by their angle around the middle
    of the shape, and an effect then travels around it. That is the same
    answer the Pegboard Desk Dock got, where the chain goes up one side and
    down the other.

    Measured on a Lines, that order jumps about and does not follow the
    figure. The layout there is two clusters and not a ring, and 81 panels
    stand in it. That measurement is why nanoleaf.py plays the effects of
    the device and streams nothing.

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


def before(ip, token):
    """What the device draws and whether it is on, to give back after.

    A name between asterisks is not an effect. *Solid*, *Dynamic* and
    *ExtControl* are the modes of the device, and a select of one of those
    does nothing: the first walk on a Lines left the device in *ExtControl*
    and lit, and the device was off before it, because this read *Solid* and
    tried to select it. So a mode is not carried, and the on state always is.
    """
    effect = None
    lit = None
    try:
        said = call(ip, "/api/v1/%s/effects/select" % token)
        if isinstance(said, str) and not said.startswith("*"):
            effect = said
    except NanoleafError:
        pass
    try:
        said = call(ip, "/api/v1/%s/state/on" % token)
        lit = said.get("value") if isinstance(said, dict) else None
    except NanoleafError:
        pass
    return effect, lit


def restore(ip, token, was):
    """Puts that effect and that on state back.

    The streaming mode ends with either of them. A device left in it goes
    back to its own effect after a minute of no frames, which is a minute of
    a person asking what happened.
    """
    effect, lit = was
    if effect:
        try:
            call(ip, "/api/v1/%s/effects" % token, method="PUT",
                 body={"select": effect})
        except NanoleafError:
            pass
    if lit is not None:
        try:
            call(ip, "/api/v1/%s/state" % token, method="PUT",
                 body={"on": {"value": bool(lit)}})
        except NanoleafError:
            pass


# -- what each command prints ------------------------------------------------

def _countdown(gap, left=[nanoleaf.PAIR_SECONDS]):
    """Sleeps that long and says how much of the window is left."""
    left[0] -= gap
    print("\r  %2d seconds left" % max(0, int(round(left[0]))),
          end="", flush=True)
    time.sleep(gap)


def _said_back(was):
    """Says what the device got back, so a person can check it."""
    effect, lit = was
    print("\nThe device is %s again, and its effect is %s."
          % ("on" if lit else "off", effect or "the one it had"))
    if effect is None:
        print("It was in a mode and not on an effect, and a mode is not "
              "a thing to select. Pick one in the app if it looks wrong.")


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
    ip, token = pair(ips, rest=_countdown)
    print()
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
    was = before(args.ip, args.token)
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
    _said_back(was)
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
    was = before(args.ip, args.token)
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
    _said_back(was)
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
    except NanoleafError as exc:
        print("%s" % exc, file=sys.stderr)
        print("A token that the device forgot needs the button and a new "
              "pair.", file=sys.stderr)
        return 1
    except OSError as exc:
        print("Could not reach the device: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
