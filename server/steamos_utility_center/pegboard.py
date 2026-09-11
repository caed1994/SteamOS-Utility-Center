# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Nanoleaf Pegboard Desk Dock, and what it takes to light it.

The board has no network. It hangs on USB-C, it reports itself as a HID
device, and the program of Nanoleaf that drives it is for Windows and macOS.
So this project drives it instead.

-- what the board said, measured on one -----------------------------------

It is 37fa:8201. Its report descriptor asks for reports of 64 bytes and
carries no report ID:

    75 08   Report Size   8 bit
    95 40   Report Count  64
    91 06   Output

Nanoleaf documents the payload as TLV: one byte of type, two bytes of length
big-endian, then the payload. A frame of colour is type 0x02 with three bytes
for each LED. 64 LEDs is 192 bytes, so the message is 195 and does not fit in
one report. It goes in four, one write for each.

The board answers each frame:

    82 00 01 00
    |  |     +- the payload: 0
    |  +------- the length: 1
    +---------- the type of the request, with bit 7 set

So a frame that arrived says so. This module counts those answers, and the
service reports a board that stopped answering.

The three bytes of an LED are GRB and not RGB:

    ff 00 00 -> green      00 ff 00 -> red      00 00 ff -> blue

which is the order of a WS2812. The renderer of this project makes RGB, so
the swap is here, at the edge.

-- the shape ---------------------------------------------------------------

The 64 LEDs are two strips of 32, one on each side of the board, and they are
one chain: LED 0 is the bottom of the left side, LED 31 the top of it, LED 32
the top of the right side, and LED 63 the bottom of it.

So the middle of the chain is the top of the board, and the two ends are the
two bottom corners. One effect is drawn on half of it and put on both
sides. See MIRRORED and fold().
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import select
import signal
import sys
import time

from . import render
from . import shim
from . import temperature

LOG = logging.getLogger("steamos-utility-center-pegboard")

# How long to wait before looking for a board that is not there, and the
# longest that wait becomes. The unit starts with the machine and USB takes
# its time, so a board that is missing at the start is normal.
RETRY_DELAY = 2.0
RETRY_CEILING = 30.0

# How long to give the board to say that a frame arrived.
#
# A fixed wait and not a share of the frame, which is what it was. At sixty
# frames a second a share of 0.8 was 13.3 ms of a 16.6 ms budget, so one slow
# answer took the whole frame and the next one went out with no gap at all.
# The answer takes about a millisecond, so five is generous and can never eat
# a frame.
SETTLE_SECONDS = 0.005

# The least time between the last report of one frame and the first of the
# next.
#
# A frame that runs over its budget must still leave this. Two frames sent
# back to back are eight reports in a burst, and a burst is what makes the
# board lose its place in the stream. See run().
MIN_GAP_SECONDS = 0.002

# The most frames a second this board takes.
#
# Measured on one, by raising the rate until the LEDs flashed again: 40 is
# the last clean value and 45 is not. The rate that works is the one this
# permits.
#
# It is not a limit of the link. The endpoints poll every millisecond and a
# frame is four reports, so the wire carries 250. It is what the board does
# with a frame after it arrives, and it answers before it draws the frame:
# the answer comes for every frame at 60 as well, and the LEDs are still
# wrong.
MAX_FPS = 40

# How many frames with no answer before this says so in the log. One second at
# sixty frames a second.
QUIET_FRAMES = 60

# -- the device --------------------------------------------------------------

VENDOR = 0x37FA
PRODUCT = 0x8201

# From the report descriptor. Not a guess, and not a number to tune.
REPORT_BYTES = 64

# What one board holds: two strips of 32, one on each side. It was a setting
# and it is a constant, because it is not a choice a person has. A board with
# a different count is a different board, and the rest of this file would need
# its layout and not only its number.
LEDS = 64

TYPE_COLOUR = 0x02
ANSWER_BIT = 0x80

# Which byte of an LED is which colour, as the board reads them. See the note
# above: this is GRB.
WIRE_ORDER = (1, 0, 2)

WHERE = "/sys/class/hidraw/*/device/uevent"


class PegboardError(Exception):
    """The board is not there, or it refused something."""


def find_device(where=WHERE):
    """The hidraw node of the board. None when it is not plugged in.

    By vendor and product and not by number: hidraw5 today is hidraw2 after
    the next boot, and a machine with a controller on it has several.
    """
    want = "%04X:%04X" % (VENDOR, PRODUCT)
    for uevent in sorted(glob.glob(where)):
        try:
            with open(uevent, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.startswith("HID_ID="):
                continue
            # HID_ID=0003:000037FA:00008201, as bus:vendor:product.
            parts = line.split("=", 1)[1].split(":")
            if len(parts) != 3:
                continue
            found = "%s:%s" % (parts[1][-4:].upper(), parts[2][-4:].upper())
            if found == want:
                # .../hidraw5/device/uevent -> hidraw5. Two directories up and
                # not an index into the path: the index is correct for one
                # spelling of /sys and wrong for each other one.
                node = os.path.basename(
                    os.path.dirname(os.path.dirname(uevent)))
                return "/dev/" + node
    return None


def message(kind, payload):
    """One TLV message: the type, the length big-endian, then the payload."""
    if len(payload) > 0xFFFF:
        raise PegboardError("a payload of %d bytes is too long"
                            % len(payload))
    return bytes([kind]) + len(payload).to_bytes(2, "big") + bytes(payload)


def reports(text):
    """That message, cut into the reports the descriptor allows.

    The last one is padded with zeros. A short write is a report of the wrong
    size, and the board drops it.
    """
    out = []
    for start in range(0, len(text), REPORT_BYTES):
        piece = text[start:start + REPORT_BYTES]
        out.append(piece + bytes(REPORT_BYTES - len(piece)))
    return out


def on_the_wire(payload):
    """The RGB bytes of the renderer, in the order the board reads them."""
    first, second, third = WIRE_ORDER
    out = bytearray()
    for at in range(0, len(payload) - 2, 3):
        pixel = payload[at:at + 3]
        out.append(pixel[first])
        out.append(pixel[second])
        out.append(pixel[third])
    return bytes(out)


def answer_of(piece):
    """Reads one answer. Returns (type asked about, payload). None for junk."""
    if len(piece) < 3:
        return None
    kind = piece[0]
    if not kind & ANSWER_BIT:
        return None
    length = int.from_bytes(piece[1:3], "big")
    return kind & ~ANSWER_BIT, piece[3:3 + length]


# -- the shape ---------------------------------------------------------------

# The rainbow, drawn on half the board and put on both sides.
#
# This is the one effect with a fold. It was a setting, `mirror` against
# `chain`, and every effect looked better on the chain: the chain is the LEDs
# in the order the hardware gives them, so an effect that moves along a strip
# runs up the left side and down the right, once around the board. Only the
# rainbow gained from the fold, where the colour rises on both sides at once.
#
# So the fold is a property of an effect now and not a thing to set. See
# MIRRORED and fold().
SHOWS_RAINBOW_WAVE = "rainbow-wave"

# The effects that are drawn on half the board and mirrored onto the other
# side. Everything else takes the chain, LED 0 to LED 63.
MIRRORED = frozenset({SHOWS_RAINBOW_WAVE})

# Which effect of the renderer draws each of these. Only the wave needs an
# entry: it is the rainbow with the fold, and not an effect of its own.
DRAWN_BY = {SHOWS_RAINBOW_WAVE: render.SHOWS_RAINBOW}

# What the board can draw: every effect of the renderer except the load gauge,
# and the wave.
#
# That gauge draws two bars of a fixed colour that grow and shrink with the
# counters. On a strip behind a case it reads as a meter. On a board it reads
# as two coloured stubs, and the numbers it shows are on the Status page in
# words. The rest is derived from the renderer, so a new effect still arrives
# by itself.
EFFECTS = tuple(sorted(
    {name for name in render.RAINBOW_CHOICES if name != render.SHOWS_LOAD}
    | {SHOWS_RAINBOW_WAVE}))


def drawn_by(effect):
    """Which effect of the renderer draws this one."""
    return DRAWN_BY.get(effect, effect)


def logical_leds(effect):
    """How many LEDs the renderer draws for that effect.

    Half of them for a folded one, because the second half is the first one
    backwards.
    """
    return LEDS // 2 if effect in MIRRORED else LEDS


def fold(payload, effect):
    """Puts a drawn frame on the chain of the board.

    `payload` is what the renderer made: three bytes for each LED, in RGB.
    """
    if effect not in MIRRORED:
        return payload
    return payload + _backwards(payload)


def _backwards(payload):
    """The pixels of that payload in the other order, bytes of each kept."""
    out = bytearray()
    for at in range(len(payload) - 3, -1, -3):
        out.extend(payload[at:at + 3])
    return bytes(out)


def frame(payload, effect):
    """One frame for the wire, from what the renderer drew."""
    return message(TYPE_COLOUR, on_the_wire(fold(payload, effect)))


# -- the configuration -------------------------------------------------------

CONFIG_PATH = "/etc/steamos-utility-center-pegboard.conf"

# The board runs on its own. It does not read what Steam shows, it has no
# notifications, and no scene of the desktop reaches it. A person sets one
# effect here and the board draws it.
#
# The names are the names of the same settings for the LED bar, where the two
# mean the same thing. A person who knows one page knows the other.
DEFAULTS = {
    "ENABLED": True,
    "EFFECT": render.SHOWS_RAINBOW,
    "BRIGHTNESS": 128,
    "SPEED": 1.0,
    "GAMMA": 1.0,
    # The hue window of the effects that have one. It is the value that the
    # colour picker of Steam gives the bar, and here a person sets it.
    "COLOR_SHIFT": 0,
    "TEMPERATURE_MIN": 40.0,
    "TEMPERATURE_MAX": 80.0,
    "TEMPERATURE_SENSOR": "auto",
    "FPS": MAX_FPS,
    "IDLE_FPS": 4,
    "LOG_LEVEL": "info",
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _coerce(key, value, template):
    """One value from the file, in the type its default has."""
    if isinstance(template, bool):
        lowered = str(value).strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise PegboardError("%s: expected a boolean, got %r" % (key, value))
    try:
        if isinstance(template, int):
            return int(str(value).strip(), 0)
        if isinstance(template, float):
            return float(str(value).strip())
    except ValueError:
        raise PegboardError("%s: expected a number, got %r" % (key, value))
    return str(value).strip()


def read(path=CONFIG_PATH):
    """The settings file, with a default for each line it leaves out.

    A file that is not there is a board that nobody configured, and the
    defaults say that. The shape is KEY=value and nothing more.
    """
    values = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return values
    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sign, value = line.partition("=")
        name = name.strip().upper()
        if not sign:
            raise PegboardError("%s:%d: expected KEY=value" % (path, number))
        if name not in DEFAULTS:
            raise PegboardError("%s:%d: unknown option %r"
                                % (path, number, name))
        values[name] = _coerce(name, value.strip().strip("\"'"),
                               DEFAULTS[name])
    validate(values)
    return values


def validate(values):
    """Refuses a setting that would draw nothing, or draw it wrong."""
    if values["EFFECT"] not in EFFECTS:
        raise PegboardError("EFFECT must be one of %s" % ", ".join(EFFECTS))
    if not 0 <= values["BRIGHTNESS"] <= 255:
        raise PegboardError("BRIGHTNESS must be between 0 and 255")
    if not 0 <= values["COLOR_SHIFT"] <= 255:
        raise PegboardError("COLOR_SHIFT must be between 0 and 255")
    if not 0.05 <= values["SPEED"] <= 20.0:
        raise PegboardError("SPEED must be between 0.05 and 20")
    if not 0.1 <= values["GAMMA"] <= 5.0:
        raise PegboardError("GAMMA must be between 0.1 and 5")
    if not 1 <= values["FPS"] <= MAX_FPS:
        raise PegboardError("FPS must be between 1 and %d. Above that a "
                            "board flashed single LEDs, and %d was the last "
                            "clean rate measured on one." % (MAX_FPS, MAX_FPS))
    if not 1 <= values["IDLE_FPS"] <= values["FPS"]:
        raise PegboardError("IDLE_FPS must be between 1 and FPS")
    return values


def text(values):
    """Those settings as the text of the file, in a fixed order.

    A fixed order, so two writes of the same settings give the same file and a
    difference in it is a difference of the settings.
    """
    lines = [
        "# The Nanoleaf Pegboard Desk Dock, for the SteamOS Utility Center.",
        "#",
        "# Written by the Pegboard page of the control panel, and read by",
        "# steamos-utility-center-pegboard.service.",
        "#",
        "# The board runs on its own. Nothing that Steam shows on the LED bar",
        "# reaches it, and the settings of the bar are not these settings.",
        "",
    ]
    for key in sorted(DEFAULTS):
        value = values.get(key, DEFAULTS[key])
        if isinstance(value, bool):
            value = "1" if value else "0"
        lines.append("%s=%s" % (key, value))
    return "\n".join(lines) + "\n"


# -- the link ----------------------------------------------------------------


class Board:
    """The board, held open. To open it for each frame is too slow."""

    def __init__(self, node=None, where=WHERE):
        self.node = node or find_device(where)
        if self.node is None:
            raise PegboardError("no %04x:%04x on this machine"
                                % (VENDOR, PRODUCT))
        try:
            self.handle = os.open(self.node, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            raise PegboardError("cannot open %s: %s" % (self.node, exc))
        self.frames = 0
        self.answers = 0

    def close(self):
        if self.handle >= 0:
            os.close(self.handle)
            self.handle = -1

    def show(self, text, settle=0.0):
        """Writes one TLV message, in reports, and waits to be told it landed.

        Linux hidraw wants the report number in the first byte of a write.
        This board has no numbered reports, so that byte is 0 and each write
        is one byte longer than the report itself.

        `settle` is the wait for the answer, and it is what paces this. One
        frame is four reports, and at sixty frames a second that is 240 of
        them. Sent with no pause, the board loses its place in the stream:
        the answer to a frame then does not come, and the frame after it is
        read from the wrong offset. Some LEDs take a byte meant for another
        one, which looks like one LED flashing at nothing.

        The board answers in about a millisecond, so the wait costs a frame
        almost nothing and stops this from sending into a board that is still
        reading the last one. It returns the answers it collected.
        """
        for piece in reports(text):
            wanted = b"\x00" + piece
            wrote = os.write(self.handle, wanted)
            if wrote != len(wanted):
                raise PegboardError("wrote %d of %d bytes to %s"
                                    % (wrote, len(wanted), self.node))
        self.frames += 1
        return self.wait(settle) if settle else []

    def wait(self, seconds):
        """The answers the board sends, for that long or until one arrives.

        It stops at the first one. One frame is answered one time, so a
        further wait is a wait for nothing.
        """
        heard = []
        until = time.monotonic() + seconds
        while not heard:
            left = until - time.monotonic()
            if left <= 0:
                break
            ready, _, _ = select.select([self.handle], [], [], left)
            if not ready:
                break
            try:
                piece = os.read(self.handle, REPORT_BYTES)
            except (BlockingIOError, InterruptedError):
                break
            self.answers += 1
            said = answer_of(piece)
            if said is not None:
                heard.append(said)
        return heard

    def drain(self):
        """Reads the answers that are there. It waits for none of them."""
        heard = []
        while True:
            ready, _, _ = select.select([self.handle], [], [], 0)
            if not ready:
                return heard
            try:
                piece = os.read(self.handle, REPORT_BYTES)
            except (BlockingIOError, InterruptedError):
                return heard
            self.answers += 1
            said = answer_of(piece)
            if said is not None:
                heard.append(said)

    def blank(self):
        """Every LED dark. The service sends this before it stops."""
        self.show(message(TYPE_COLOUR, bytes(3 * LEDS)))

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


# -- the service -------------------------------------------------------------
#
# The board draws one effect and nothing else. It reads no snapshot from
# Steam, it gets no notification, and no scene of the desktop reaches it.
#
# The renderer still wants a snapshot, because that is the shape of every
# effect function. So this builds one from the settings of the board. Steam
# would set the colour of the game, the brightness of the slider and the
# pixels of a static effect. Here those are the values a person put in the
# file.


def build_renderer(values):
    """The renderer for the board, at the count its effect asks for."""
    shows = drawn_by(values["EFFECT"])
    return render.Renderer(
        # The count comes from the effect of the board and not from the one
        # the renderer draws. They differ for the wave: it is drawn by the
        # rainbow, on half the LEDs, and fold() puts the other half on.
        led_count=logical_leds(values["EFFECT"]),
        gamma=values["GAMMA"],
        speed_scale=values["SPEED"],
        temperature=(temperature.TemperatureSource(
            path=values["TEMPERATURE_SENSOR"])
            if shows == render.SHOWS_TEMPERATURE else None),
        temperature_range=(values["TEMPERATURE_MIN"],
                           values["TEMPERATURE_MAX"]),
        rainbow_shows=shows)


def build_snapshot(values):
    """The state the effects read, made from the settings of this board.

    UNTOUCHED_SEQ is not used here. That number means "Steam wrote nothing
    yet", and this board never waits for Steam.
    """
    return shim.Snapshot(
        seq=1, monotonic_ns=0, enabled=bool(values["ENABLED"]),
        effect=shim.EFFECT_RAINBOW,
        brightness_scale=values["BRIGHTNESS"],
        # render.DELAY_DEFAULT and not 0. Zero is a value that Steam writes
        # and it means "as fast as possible": the cycle of every effect then
        # comes out at MIN_CYCLE_SECONDS, whatever SPEED says. The ooze ran
        # its 14 seconds in 0.8, and the speed slider moved nothing. See
        # render._cycle, whose first paragraph says so.
        delay=render.DELAY_DEFAULT,
        breath_offset=0, breath_level=0, patrol_num=0,
        color_shift=values["COLOR_SHIFT"],
        # What a static effect shows. White, because a person who picks one
        # sets the colour with COLOR_SHIFT and not with this.
        pixels=[(255, 255, 255)] * shim.LOGICAL_LEDS)


def run(values, board=None, stop=None, now=None):
    """Draws the board until something stops it.

    `board`, `stop` and `now` are parameters so that a test can run this loop
    with no board and no clock.
    """
    now = time.monotonic if now is None else now
    renderer = build_renderer(values)
    snapshot = build_snapshot(values)
    # Two names: the renderer knows the effect it draws, and the fold knows
    # the effect the board was asked for. They differ for the wave.
    effect = values["EFFECT"]
    shows = drawn_by(effect)
    started = now()
    animated = renderer.is_animated(snapshot, shows)
    # A still effect needs no sixty frames a second. It still needs some: the
    # board holds the last frame, and a service that sends nothing cannot be
    # told from a service that stopped.
    interval = 1.0 / (values["FPS"] if animated else values["IDLE_FPS"])
    owned = board is None
    if owned:
        board = Board()
    quiet = 0
    try:
        while stop is None or not stop():
            due = now() + interval
            payload = renderer.render(snapshot, now() - started, shows)
            if board.show(frame(payload, effect),
                          settle=SETTLE_SECONDS):
                quiet = 0
            else:
                quiet += 1
                # Once, and not for each frame: a board that stopped
                # answering would otherwise write a line for every frame.
                if quiet == QUIET_FRAMES:
                    LOG.warning("the board has not answered for %d frames; "
                                "it is drawing without an answer", quiet)
            # The gap even when the frame ran over. Without it a late frame
            # is followed at once by the next, and the board reads eight
            # reports where it expected four.
            time.sleep(max(due - now(), MIN_GAP_SECONDS))
    finally:
        try:
            board.blank()
        except OSError:
            pass
        if owned:
            board.close()
    return board.frames


def main(argv=None):
    """The service. One board, one effect, and a blank frame when it stops."""
    parser = argparse.ArgumentParser(
        description="Light the Nanoleaf Pegboard Desk Dock.")
    parser.add_argument("--config", default=CONFIG_PATH,
                        help="the settings file (default %s)" % CONFIG_PATH)
    parser.add_argument("--report", action="store_true",
                        help="say what is on this machine, and stop")
    parser.add_argument("--check-config", action="store_true",
                        help="read the settings file, say whether it is good, "
                             "and stop. The applier runs this before it "
                             "replaces a file that operates.")
    args = parser.parse_args(argv)

    try:
        values = read(args.config)
    except PegboardError as exc:
        print("the settings are wrong: %s" % exc, file=sys.stderr)
        return 2

    if args.check_config:
        print("%s is good" % args.config)
        return 0

    logging.basicConfig(
        level=getattr(logging, str(values["LOG_LEVEL"]).upper(), logging.INFO),
        format="%(levelname)s: %(message)s")

    node = find_device()
    if args.report:
        print("board: %s" % (node or "not plugged in"))
        print("LEDs: %d, %d drawn%s"
              % (LEDS, logical_leds(values["EFFECT"]),
                 " and mirrored" if values["EFFECT"] in MIRRORED else ""))
        print("effect: %s at %d brightness, speed %.2f"
              % (values["EFFECT"], values["BRIGHTNESS"], values["SPEED"]))
        return 0 if node else 1

    if not values["ENABLED"]:
        LOG.info("the board is switched off in %s", args.config)
        return 0

    stopping = []
    def asked_to_stop(_signum, _frame):
        stopping.append(True)
    signal.signal(signal.SIGTERM, asked_to_stop)
    signal.signal(signal.SIGINT, asked_to_stop)

    # A board that is not there yet is not a failure. The unit starts with the
    # machine, and USB takes its time.
    delay = RETRY_DELAY
    while not stopping:
        try:
            with Board() as board:
                LOG.info("drawing %s on %s, %d LEDs",
                         values["EFFECT"], board.node, LEDS)
                delay = RETRY_DELAY
                run(values, board=board, stop=lambda: bool(stopping))
        except PegboardError as exc:
            LOG.warning("%s; looking again in %.0f s", exc, delay)
        except OSError as exc:
            LOG.warning("the board stopped answering: %s; looking again in "
                        "%.0f s", exc, delay)
        if stopping:
            break
        time.sleep(delay)
        delay = min(delay * 2, RETRY_CEILING)
    LOG.info("stopped")
    return 0
