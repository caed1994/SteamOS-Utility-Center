# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pairing: a new panel gets its secret, and nobody types a token.

The panel and this service do a key exchange, X25519 of RFC 7748. Each side
sends its public key, and each side then calculates the same secret. The
secret itself never goes over the network.

A key exchange alone does not say who is at the other end. So both ends show
a code of six digits, which comes from the same calculation. A person
compares the two codes and accepts the panel on the PC. A device between the
two has a different secret with each end, and thus a different code on each
screen.

The panel also finds the PC by itself. It sends a short broadcast into the
network, and Responder answers it with the port of this service.

The service of the panel and the two programs with the buttons are different
processes of the same user. They speak through two files in the runtime
directory of the user, which only that user can read: the request, and the
answer of the person.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import socket
import threading
import time

LOG = logging.getLogger(__name__)

KEY_BYTES = 32
# How long a request waits for a person.
WAIT_SECONDS = 300.0
# The least time between two new requests. One request waits at a time, so
# this only stops a stranger who asks again and again for a new code.
GAP_SECONDS = 2.0
CODE_DIGITS = 6
# The labels of the two values that come from the shared secret. Two labels,
# so that the code says nothing about the secret.
SECRET_LABEL = b"steamos-utility-center pairing secret"
CODE_LABEL = b"steamos-utility-center pairing code"

REQUEST_NAME = "steamos-utility-center-pairing.json"
ANSWER_NAME = "steamos-utility-center-pairing-answer.json"

# The broadcast of a panel that looks for the PC, and the most answers each
# second.
DISCOVER = b"steamos-utility-center discover 1"
SERVICE = "steamos-utility-center"
ANSWERS_EACH_SECOND = 10

WAITING = "waiting"
ACCEPTED = "accepted"
REFUSED = "refused"
EXPIRED = "expired"

NAME_CHARS = 24


# -- X25519 -----------------------------------------------------------------
#
# The Montgomery ladder of RFC 7748, section 5. Python has no X25519 in its
# standard library, and this project uses no package from outside it. Each
# key of a pairing is new and is used one time, so a difference in the time
# of a calculation tells an observer nothing that they can use again.

_P = 2 ** 255 - 19
_A24 = 121665
BASE = (9).to_bytes(KEY_BYTES, "little")


def x25519(scalar, point):
    """Returns scalar times point, both 32 bytes, as RFC 7748 says."""
    if len(scalar) != KEY_BYTES or len(point) != KEY_BYTES:
        raise ValueError("an X25519 value has 32 bytes")
    clamped = bytearray(scalar)
    clamped[0] &= 248
    clamped[31] &= 127
    clamped[31] |= 64
    k = int.from_bytes(clamped, "little")
    u = int.from_bytes(point, "little") & ((1 << 255) - 1)
    x1, x2, z2, x3, z3, swap = u, 1, 0, u, 1, 0
    for bit_number in reversed(range(255)):
        bit = (k >> bit_number) & 1
        swap ^= bit
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a = (x2 + z2) % _P
        aa = a * a % _P
        b = (x2 - z2) % _P
        bb = b * b % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = d * a % _P
        cb = c * b % _P
        x3 = (da + cb) ** 2 % _P
        z3 = x1 * (da - cb) ** 2 % _P
        x2 = aa * bb % _P
        z2 = e * (aa + _A24 * e) % _P
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(KEY_BYTES, "little")


def public_key(private):
    return x25519(private, BASE)


def shared_secret(private, other):
    """Returns the shared secret, or raises ValueError for a weak key.

    A key of a small order gives zero whatever the other key is. RFC 7748
    says to refuse that result.
    """
    shared = x25519(private, other)
    if not any(shared):
        raise ValueError("a weak public key")
    return shared


def derive(shared, panel_key, pc_key):
    """Returns (secret, code): the token as 64 hex digits, and six digits.

    Both keys are in the calculation, in a fixed order, so the two ends get
    the same values only for the same two keys.
    """
    keys = panel_key + pc_key
    secret = hmac.new(shared, SECRET_LABEL + keys, hashlib.sha256).hexdigest()
    number = int.from_bytes(
        hmac.new(shared, CODE_LABEL + keys, hashlib.sha256).digest()[:4],
        "big")
    return secret, "%0*d" % (CODE_DIGITS, number % 10 ** CODE_DIGITS)


def safe_name(text):
    """Returns a name that is safe and short for a screen and a file."""
    return re.sub(r"[^A-Za-z0-9 ._-]", "", str(text))[:NAME_CHARS]


# -- the files between the processes ----------------------------------------


def runtime_dir():
    return os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()


def _write(path, values):
    """Writes a small JSON file that only this user can read."""
    temporary = path + ".new"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                         0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(values, handle)
    os.replace(temporary, path)


def _read(path, limit=4096):
    try:
        with open(path, "rb") as handle:
            values = json.loads(handle.read(limit).decode("utf-8"))
    except (OSError, ValueError):
        return None
    return values if isinstance(values, dict) else None


def _remove(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def waiting(folder=None, wall=time.time):
    """Returns the request that waits for a person, or None.

    The keys are id, name, address, code and until. The secret is not in the
    file.
    """
    found = _read(os.path.join(folder or runtime_dir(), REQUEST_NAME))
    if not found:
        return None
    until = found.get("until")
    if (not isinstance(until, (int, float)) or isinstance(until, bool)
            or until < wall()):
        return None
    if not (isinstance(found.get("id"), str)
            and re.match(r"^[0-9a-f]{16}$", found["id"])
            and isinstance(found.get("code"), str)
            and re.match(r"^\d{%d}$" % CODE_DIGITS, found["code"])):
        return None
    return {"id": found["id"], "code": found["code"],
            "name": safe_name(found.get("name", "")),
            "address": safe_name(found.get("address", "")),
            "until": float(until)}


def answer(request_id, accept, folder=None):
    """Gives the answer of the person to the service of the panel."""
    if not re.match(r"^[0-9a-f]{16}$", str(request_id)):
        raise ValueError("not a request id")
    _write(os.path.join(folder or runtime_dir(), ANSWER_NAME),
           {"id": request_id, "accept": bool(accept)})


# -- the service: the one request that waits --------------------------------


class Pairing:
    """The one request that waits for a person, and what the person said."""

    def __init__(self, folder=None, wall=time.time, random=secrets.token_bytes,
                 name=None):
        self.folder = folder or runtime_dir()
        self.wall = wall
        self.random = random
        self.name = safe_name(name or socket.gethostname()) or "PC"
        self._lock = threading.Lock()
        self._request = None
        self._last = None

    @property
    def request_path(self):
        return os.path.join(self.folder, REQUEST_NAME)

    @property
    def answer_path(self):
        return os.path.join(self.folder, ANSWER_NAME)

    def ask(self, body, address):
        """A panel asks to pair. Returns (HTTP code, answer)."""
        if not isinstance(body, dict):
            return 400, {"error": "invalid request"}
        key = body.get("key")
        if not (isinstance(key, str) and re.match(r"^[0-9a-f]{64}$", key)):
            return 400, {"error": "invalid key"}
        panel_key = bytes.fromhex(key)
        name = safe_name(body.get("name", "")) or "panel"
        now = self.wall()
        with self._lock:
            self._expire(now)
            request = self._request
            if request is not None and request["state"] == WAITING:
                if request["panel_key"] == panel_key:
                    # The same panel asks again, because an answer was lost.
                    return 200, self._reply(request)
                return 409, {"error": "another panel waits"}
            if self._last is not None and now - self._last < GAP_SECONDS:
                return 429, {"error": "too soon"}
            private = self.random(KEY_BYTES)
            pc_key = public_key(private)
            try:
                shared = shared_secret(private, panel_key)
            except ValueError:
                return 400, {"error": "invalid key"}
            secret, code = derive(shared, panel_key, pc_key)
            self._last = now
            self._request = {
                "id": secrets.token_hex(8), "name": name,
                "address": safe_name(address), "panel_key": panel_key,
                "pc_key": pc_key, "secret": secret, "code": code,
                "until": now + WAIT_SECONDS, "state": WAITING}
            _remove(self.answer_path)
            self._publish()
            LOG.info("pairing: %s at %s asks to pair, code %s", name,
                     address, code)
            return 200, self._reply(self._request)

    def check(self, request_id):
        """The panel asks for the answer. Returns (code, answer, secret).

        The secret comes back one time, with the first answer that says
        accepted. The caller then keeps it as the new token.
        """
        now = self.wall()
        with self._lock:
            self._expire(now)
            request = self._request
            if request is None or request["id"] != request_id:
                return 404, {"state": "unknown"}, None
            if request["state"] == WAITING:
                said = _read(self.answer_path)
                if said and said.get("id") == request_id:
                    request["state"] = (ACCEPTED if said.get("accept") is True
                                        else REFUSED)
                    _remove(self.answer_path)
                    _remove(self.request_path)
                    LOG.info("pairing: %s %s", request["name"],
                             request["state"])
                    if request["state"] == ACCEPTED:
                        return 200, {"state": ACCEPTED}, request["secret"]
            return 200, {"state": request["state"]}, None

    def _reply(self, request):
        return {"id": request["id"], "key": request["pc_key"].hex(),
                "name": self.name}

    def _publish(self):
        request = self._request
        try:
            _write(self.request_path, {
                "id": request["id"], "name": request["name"],
                "address": request["address"], "code": request["code"],
                "until": request["until"]})
        except OSError as exc:
            LOG.warning("pairing: cannot write %s: %s", self.request_path, exc)

    def _expire(self, now):
        request = self._request
        if request is not None and now > request["until"]:
            if request["state"] == WAITING:
                LOG.info("pairing: the request of %s expired", request["name"])
            self._request = None
            _remove(self.request_path)
            _remove(self.answer_path)


# -- the broadcast of a panel that looks for the PC -------------------------


class Responder:
    """Answers the broadcast of a panel with the port of the service.

    The answer goes to the sender alone. The panel takes the address of the
    PC from the answer: it is the address that the answer came from.
    """

    def __init__(self, port, name=None, sock=None, clock=time.monotonic):
        self.port = port
        self.name = safe_name(name or socket.gethostname()) or "PC"
        self.clock = clock
        self.sock = sock
        self._second = None
        self._count = 0

    def open(self):
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("", self.port))
        return self

    def reply(self):
        return json.dumps({"service": SERVICE, "port": self.port,
                           "name": self.name},
                          separators=(",", ":")).encode()

    def handle(self, data, address):
        """Answers one datagram. Returns True when it sent an answer."""
        if data.strip() != DISCOVER:
            return False
        second = int(self.clock())
        if second != self._second:
            self._second, self._count = second, 0
        if self._count >= ANSWERS_EACH_SECOND:
            return False
        self._count += 1
        try:
            self.sock.sendto(self.reply(), address)
        except OSError:
            return False
        return True

    def serve(self):
        while True:
            try:
                data, address = self.sock.recvfrom(256)
            except OSError:
                return
            self.handle(data, address)

    def start(self):
        """Opens the socket and answers in a thread. Returns self or None."""
        try:
            self.open()
        except OSError as exc:
            LOG.warning("pairing: no answers to a search for the PC: %s", exc)
            return None
        threading.Thread(target=self.serve, name="discovery",
                         daemon=True).start()
        return self
