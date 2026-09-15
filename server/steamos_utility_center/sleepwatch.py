# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn the Nanoleaf devices on the network off at the moment a sleep begins.

The moment is narrow. logind announces the sleep with the PrepareForSleep
signal, and NetworkManager answers the same signal by taking the interface
down. One measurement on the machine this is for:

    .8172  NM: sleep requested
    .8450  enp11s0: activated -> deactivating, dhcp4: canceled, no lease

Twenty-eight milliseconds from the announcement to no address at all. After
that a call to a lamp on the LAN reports Errno 101, which says there is no
route.

Two earlier shapes lost that race, and neither was slow by accident:

    a unit at Before=sleep.target     runs after the whole delay phase
    a hook at NetworkManager pre-down starts its dispatcher service, a
                                      runuser with a PAM session and a
                                      Python, and all of that is hundreds
                                      of milliseconds

The hook held the right place in the state machine of NetworkManager for one
SteamOS version. An update changed the order, and it lost the place.

So this is a program that is already running. It holds a delay inhibitor at
logind, it reads the same signal NetworkManager reads, and it makes the call
with no process to start first. A LAN call from a warm process takes two to
five milliseconds against those twenty-eight.

It stays a race. logind gives the signal to every holder of a delay lock at
once, and the locks have no order between them. The margin is the whole
argument, so the time of each call is in the journal and nobody has to trust
this text.

The delay lock is what makes the suspend wait for the call. Without it the
machine sleeps while the message is in flight.

D-Bus here is the socket and nothing else. python-dbus and gi are packages
that a SteamOS update can take away, and an update is exactly the event this
file exists because of.
"""

from __future__ import annotations

import os
import socket
import struct
import subprocess
import sys
import time

from . import nanoleaf

# Where the system bus listens. The address is a setting of D-Bus, and this
# is the path that every machine with systemd uses.
BUS_ADDRESS = "DBUS_SYSTEM_BUS_ADDRESS"
BUS_PATH = "/run/dbus/system_bus_socket"

# The signal, and the only traffic this program asks for.
LOGIND = "org.freedesktop.login1"
MANAGER = "org.freedesktop.login1.Manager"
SIGNAL = "PrepareForSleep"
RULE = ("type='signal',interface='%s',member='%s'" % (MANAGER, SIGNAL))

# The lock that makes the suspend wait, and the words that name it in
# `systemd-inhibit --list`.
INHIBIT = "/usr/bin/systemd-inhibit"
WHO = "SteamOS Utility Center"
WHY = "Turn the Nanoleaf devices on the network off"

# How long to wait before deciding that the lock was refused.
#
# systemd-inhibit that cannot take the lock writes the reason and stops. A
# child that is alive after this much time holds it.
HOLD_CHECK = 0.5

# How long to wait for the answer of a device on the way into a suspend.
#
# The answer cannot arrive. The message goes out while the interface is up,
# and the interface goes away some milliseconds later, so the reply has
# nothing to come back over. The first version used the ordinary limit of the
# module and held every suspend for its whole 2.5 seconds:
#
#   after 2531 ms, Lines A5F4: 192.168.178.93 did not answer: timed out
#
# The lamp went off at that suspend. urllib writes the request and then waits,
# so the message was on the wire within milliseconds and the wait bought
# nothing. A device that does answer answers in some tens of milliseconds, so
# this is room for that and no more.
SLEEP_TIMEOUT = 0.5

# What a message of D-Bus carries before its body.
HEAD = 16
SIGNAL_TYPE = 4


class BusError(OSError):
    """The bus said no, or said something this file cannot read."""


# -- the little of D-Bus that this needs -------------------------------------
#
# Marshalling by hand, for two method calls and one signal. Each value is
# aligned to its own width from the start of the message, and the header is
# padded to eight before the body. See the specification of D-Bus.

def _pad(data, boundary):
    """The data with zeros up to the next boundary."""
    return data + b"\0" * ((-len(data)) % boundary)


def _string(text):
    """A STRING or an OBJECT_PATH: the length, the bytes and a zero."""
    raw = text.encode()
    return struct.pack("<I", len(raw)) + raw + b"\0"


def _signature(text):
    """A SIGNATURE, whose length is one byte and not four."""
    raw = text.encode()
    return bytes([len(raw)]) + raw + b"\0"


def fields(entries):
    """The header fields, as an array of a byte and a variant.

    Each entry is a struct, and a struct begins at a multiple of eight. The
    array itself begins at sixteen bytes into the message, so a padding of
    eight here is the padding of the message.
    """
    out = b""
    for code, kind, value in entries:
        out = _pad(out, 8) + bytes([code]) + _signature(kind)
        if kind == "g":
            out += _signature(value)
        else:
            out = _pad(out, 4) + _string(value)
    return out


def message(kind, entries, body=b"", serial=1):
    """One message of D-Bus, little endian, protocol version one."""
    packed = fields(entries)
    head = struct.pack("<BBBB", ord("l"), kind, 0, 1)
    head += struct.pack("<II", len(body), serial)
    head += struct.pack("<I", len(packed)) + packed
    return _pad(head, 8) + body


def call(member, entries=(), body=b"", serial=1):
    """A method call to the bus itself, which is where both of ours go."""
    named = [(1, "o", "/org/freedesktop/DBus"),
             (6, "s", "org.freedesktop.DBus"),
             (2, "s", "org.freedesktop.DBus"),
             (3, "s", member)]
    named.extend(entries)
    return message(1, named, body, serial)


def _take(sock, count):
    """Exactly this many bytes, or an error."""
    out = b""
    while len(out) < count:
        part = sock.recv(count - len(out))
        if not part:
            raise BusError("the system bus closed the connection")
        out += part
    return out


def next_message(sock):
    """The next whole message, as its head, its fields and its body."""
    head = _take(sock, HEAD)
    order = "<" if head[:1] == b"l" else ">"
    body_length, = struct.unpack_from(order + "I", head, 4)
    field_length, = struct.unpack_from(order + "I", head, 12)
    named = _take(sock, field_length)
    gap = (-(HEAD + field_length)) % 8
    if gap:
        _take(sock, gap)
    return head, named, _take(sock, body_length), order


def asleep(head, named, body, order):
    """Whether this message is PrepareForSleep, and what it says.

    Returns None for every other message. The member is read from the bytes
    of the header rather than from a full walk of the fields: this connection
    asks for one signal, and the rest of its traffic is the two answers to
    the calls below.
    """
    if head[1] != SIGNAL_TYPE:
        return None
    if SIGNAL.encode() not in named:
        return None
    if len(body) < 4:
        return None
    value, = struct.unpack_from(order + "I", body, 0)
    return bool(value)


def connect(path=None, uid=None):
    """The system bus, with the handshake and the match rule done.

    EXTERNAL is the mechanism that gives the user id of this process to the
    bus over the socket. The id goes as the hexadecimal of its digits, which
    is what the specification asks for.
    """
    if path is None:
        said = os.environ.get(BUS_ADDRESS, "")
        path = said.split("unix:path=")[-1].split(",")[0] if said else BUS_PATH
    uid = os.getuid() if uid is None else uid
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
        sock.sendall(b"\0AUTH EXTERNAL "
                     + str(uid).encode().hex().encode() + b"\r\n")
        answer = b""
        while b"\r\n" not in answer:
            part = sock.recv(1024)
            if not part:
                raise BusError("the system bus gave no answer to AUTH")
            answer += part
        if not answer.startswith(b"OK"):
            raise BusError("the system bus refused this user: %r" % answer)
        sock.sendall(b"BEGIN\r\n")
        sock.sendall(call("Hello"))
        sock.sendall(call("AddMatch", [(8, "g", "s")], _string(RULE), 2))
    except OSError:
        sock.close()
        raise
    return sock


# -- the lock ----------------------------------------------------------------

def hold(run=None, rest=None):
    """A delay lock at logind, held while the returned process runs.

    systemd-inhibit and not a call of our own: the lock arrives as a file
    descriptor over the bus, and receiving one is more of this protocol than
    the rest of this file together. systemd-inhibit is part of systemd, so it
    is on every machine that has logind.

    `cat` holds the lock and ends at the close of its input, which is how
    release below gives the sleep its way.
    """
    run = subprocess.Popen if run is None else run
    rest = time.sleep if rest is None else rest
    child = run([INHIBIT, "--what=sleep", "--mode=delay",
                 "--who=" + WHO, "--why=" + WHY, "cat"],
                stdin=subprocess.PIPE)
    rest(HOLD_CHECK)
    if child.poll() is not None:
        raise BusError("logind refused the delay lock for this account")
    return child


def release(child):
    """Let the sleep go on. The lock ends with the process that holds it."""
    if child is None:
        return
    try:
        if child.stdin is not None:
            child.stdin.close()
    except OSError:
        pass
    try:
        child.wait(timeout=5)
    except Exception:
        child.kill()


# -- the program -------------------------------------------------------------

def say(line):
    """One line for the journal, which is the record of the margin."""
    print(line, flush=True)


def darken(home=None, now=None):
    """Turn them off, and report what it cost.

    The time is the whole point of this program, so it is measured and not
    asserted. It runs from the signal to the last answer or to the limit.

    A device that gives no answer here is the ordinary case and not a fault.
    The message goes out and the interface goes away, so the reply has
    nothing to come back over. The lamp acts on the message either way.
    """
    now = time.monotonic if now is None else now
    started = now()
    said = nanoleaf.follow(False, home, timeout=SLEEP_TIMEOUT)
    took = (now() - started) * 1000.0
    if said["done"]:
        say("off in %.0f ms: %s" % (took, ", ".join(said["done"])))
    for line in said["trouble"]:
        say("sent in %.0f ms, no answer before the network went: %s"
            % (took, line))
    if not said["done"] and not said["trouble"]:
        say("no Nanoleaf device on the network is paired here")
    return said


def watch(sock, home=None, hold_one=None, now=None):
    """Read the bus and act on each announcement of a sleep.

    The wake is the resume unit and not this loop. That unit works, and a
    second program for the same moment is a second thing to be wrong. This
    takes the lock again there, for the sleep after it.
    """
    hold_one = hold if hold_one is None else hold_one
    lock = hold_one()
    say("holding a delay lock, watching for a sleep")
    try:
        while True:
            state = asleep(*next_message(sock))
            if state is None:
                continue
            if state:
                darken(home, now)
                release(lock)
                lock = None
            elif lock is None:
                lock = hold_one()
    finally:
        release(lock)


def main(argv=None):
    """The unit runs this and nothing else runs it."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv:
        print("usage: steamos-utility-center-nanoleaf-watch", file=sys.stderr)
        return 2
    try:
        sock = connect()
    except OSError as exc:
        print("no system bus: %s" % exc, file=sys.stderr)
        return 1
    try:
        watch(sock)
    except BusError as exc:
        print("%s" % exc, file=sys.stderr)
        return 1
    finally:
        sock.close()
    return 0
