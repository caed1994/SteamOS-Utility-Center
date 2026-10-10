# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mirror: the LED bar takes the colours of the screen in Game Mode.

Two processes do this work, because the LED service cannot see the screen.
That service runs as root in a sandbox, and the sandbox hides /run/user. The
screen of Game Mode is a PipeWire stream of gamescope, and PipeWire is a
service of the user.

So a user service reads the screen: Watcher. It starts gst-launch-1.0, which
gives it small pictures of 68 by 36 pixels. Watcher makes 17 colours from
each picture and writes them into a pipe. In the LED service, Mirror reads
that pipe, and the renderer draws the colours.

The pipe also tells Watcher when to read the screen. The LED service opens
the pipe only while the bar shows the mirror. With no reader, the open of
Watcher fails. Watcher then starts no capture, and gamescope copies no
pictures.

Watcher writes what it does into a small file in the runtime directory of the
user. The panel service and the control panel read that file. A person thus
sees why the mirror does not work, with no terminal.
"""

from __future__ import annotations

import errno
import json
import logging
import math
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import time

from . import shim

LOG = logging.getLogger(__name__)

# One zone of the screen for each LED of the bar, from the left to the right.
ZONES = shim.LOGICAL_LEDS

# The picture that gst-launch-1.0 gives: four columns for each zone, and
# sufficient rows to find the black bars of a film.
WIDTH = 4 * ZONES
HEIGHT = 36
FRAME = WIDTH * HEIGHT * 3

# The pipeline scales in two steps. The first step keeps one pixel of each
# cell, at four times the last size. The second step makes the mean of each
# cell. One step that makes the mean of the full screen costs 0.7 ms to 2.1 ms
# for each picture. The two steps cost less than 0.3 ms, and the mean of an
# 8 pixel checkerboard is equally flat. Measured with GStreamer 1.24 at 1080p,
# 1440p and 2160p, with no PipeWire.
COARSE = 4

# The pictures each second. The bar eases between them at its frame rate.
# gamescope sends up to one picture for each frame of the game. The memory of
# each picture is mapped again, so each row that the first step reads costs
# a page fault. Measured at 1080p with a stream like that of gamescope: 6 %
# of one core at 60 pictures each second, and 2.5 % at 15.
RATE = 15

# The pipe from Watcher to the LED service. It is in the runtime directory of
# the LED service, beside the pipe for the notifications.
FIFO = "/run/steamos-utility-center/mirror"
# Each user can write, and only root can read. A reader starts the capture of
# the screen, so the reader must be the LED service.
FIFO_MODE = 0o622

# One message: a byte for the kind, then three bytes for each zone. It is
# smaller than PIPE_BUF, so each write arrives whole.
KIND_COLOURS = 1
MESSAGE = 1 + 3 * ZONES

# The file of the status, in the runtime directory of the user.
STATUS_NAME = "steamos-utility-center-mirror.json"

# The words of the status. The panel and the control panel translate them.
OFF = "off"                     # no pipe: the LED service offers no mirror
IDLE = "idle"                   # the bar shows a different effect now
NO_GSTREAMER = "no-gstreamer"   # gst-launch-1.0 is not on this machine
NO_PLUGIN = "no-plugin"         # an element of the pipeline is not there
NO_SCREEN = "no-screen"         # no stream of gamescope: no Game Mode
ASKING = "asking"               # the portal asks for the desktop screen
REFUSED = "refused"             # the person refused or stopped the share
NO_PORTAL = "no-portal"         # the desktop has no screen cast portal
BUSY = "busy"                   # a different program reads the screen
STARTING = "starting"           # the capture runs and has no picture yet
WAITING = "waiting"             # it is connected, and the screen is still
RUNNING = "running"
FAILED = "failed"
GONE = "gone"                   # no recent status: Watcher does not run
STATES = (OFF, IDLE, NO_GSTREAMER, NO_PLUGIN, NO_SCREEN, ASKING, REFUSED,
          NO_PORTAL, BUSY, STARTING, WAITING, RUNNING, FAILED, GONE)

# The states of a share of the desktop screen (portal.Share): it asks, it
# gives the screen, or it is over.
SHARE_ASKING = ASKING
SHARE_READY = "ready"
SHARE_ENDED = "ended"

# The longest detail in the status. The panel has one line for it.
DETAIL_CHARS = 40


# -- from a picture to the colours of the bar ------------------------------

# A channel at or below this value is black, for the bars of a film. Video
# black is 16, and a compressed film adds noise to it.
BLACK = 24
# A bar can be this part of each edge at most. A dark scene with one light in
# the middle is not a film with bars.
MOST_BAR = 0.3
# How long a new bar must stay before the zones use it. A dark scene makes a
# bar that is not there, so a larger bar must stay longer. Light in a bar is
# always a part of the picture, so a smaller bar comes quickly.
GROW_SECONDS = 2.0
SHRINK_SECONDS = 0.2

# The level below which a zone is dark. Black on a screen is often not zero,
# and a bar that glows for a black screen is not a mirror.
DARK = 18


def _light(value):
    value /= 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


# The light of each value of a pixel, from 0 to 1. A screen gives light by
# the sRGB curve, and an LED of the bar gives light in proportion to its
# value. So the bar gets the light of the screen, and not the value of the
# pixel. The values of the pixels made the middle tones too bright, and each
# colour went pale.
LIGHT = tuple(_light(value) for value in range(256))
DARK_LIGHT = LIGHT[DARK]

# The profiles of the mirror. MIRROR_PROFILE in the settings selects one.
CINEMATIC = "cinematic"     # the mean light of each zone, with calm changes
POP = "pop"                 # the colours of each zone, strong and quick
SOLID = "solid"             # one colour for the whole bar, with calm changes
PROFILES = (CINEMATIC, POP, SOLID)
DEFAULT_PROFILE = POP
# The names that a person reads. They are English in each language.
PROFILE_NAMES = {CINEMATIC: "Cinematic", POP: "Color Pop", SOLID: "Solid"}
# How much each profile multiplies the distance from grey, in light.
MORE_COLOUR = {CINEMATIC: 1.25, POP: 1.8, SOLID: 1.8}
# The least light of a zone that has light, as a part of full light. A dim
# colour thus still shows. Cinematic follows the light of the screen.
LEAST_LIGHT = {CINEMATIC: 0.0, POP: 0.35, SOLID: 0.35}
# The time constants of the bar for each profile, in seconds: for light that
# comes, and for light that goes. Light comes more quickly, as from a lamp.
EASING = {CINEMATIC: (0.40, 1.00), POP: (0.10, 0.35), SOLID: (0.50, 1.00)}
# The weight of a grey pixel. A zone with no colour thus keeps its mean.
GREY_WEIGHT = 1e-4

# Measured with 12 pictures of games, as the saturation of the light from 0
# to 1: 0.49 on the screen, 0.33 on the bar with the values of the pixels and
# a mean of each zone. With the light: 0.45 for cinematic, 0.71 for pop and
# 0.63 for solid.


def bars(frame, width=WIDTH, height=HEIGHT, black=BLACK):
    """Returns the black bars as (rows, columns), or None for a black picture.

    The rows are at the top and at the bottom, and the columns are at the
    left and at the right. Each value is the smaller of its two sides, because
    the two bars of a film are equal. A bar that is too large counts as no
    bar.
    """
    stride = width * 3
    lit = [max(frame[row * stride:(row + 1) * stride]) > black
           for row in range(height)]
    if True not in lit:
        return None
    rows = min(lit.index(True), lit[::-1].index(True))
    lit = [max(max(frame[column * 3::stride]),
               max(frame[column * 3 + 1::stride]),
               max(frame[column * 3 + 2::stride])) > black
           for column in range(width)]
    columns = min(lit.index(True), lit[::-1].index(True))
    if rows > height * MOST_BAR:
        rows = 0
    if columns > width * MOST_BAR:
        columns = 0
    return rows, columns


class Crop:
    """The bars that the zones leave out, with a hold time for each change."""

    def __init__(self):
        self.bars = (0, 0)
        self._next = None
        self._since = 0.0

    def update(self, found, now):
        """Returns the bars to use after a picture with the bars `found`.

        A black picture says nothing about the bars, so it changes nothing.
        """
        if found is None or found == self.bars:
            self._next = None
            return self.bars
        if found != self._next:
            self._next = found
            self._since = now
        grows = found[0] > self.bars[0] or found[1] > self.bars[1]
        if now - self._since >= (GROW_SECONDS if grows else SHRINK_SECONDS):
            self.bars = found
            self._next = None
        return self.bars


_SPANS = {}


def _spans(count):
    """Returns the columns of each zone, as (column, weight) pairs.

    The zones are equal, so a zone can start or stop in a column. That column
    then counts in two zones, each with its part.
    """
    spans = _SPANS.get(count)
    if spans is None:
        spans = []
        for zone in range(ZONES):
            start = zone * count / float(ZONES)
            end = (zone + 1) * count / float(ZONES)
            parts = []
            for column in range(int(start), min(int(math.ceil(end)), count)):
                weight = min(end, column + 1.0) - max(start, float(column))
                if weight > 1e-9:
                    parts.append((column, weight))
            spans.append(parts)
        _SPANS[count] = spans
    return spans


def _columns(frame, crop, width, height):
    """Returns the sums of the light of each column inside the bars.

    Each column gives (plain sum, sum weighted by colour, sum of weights). A
    pixel weighs its saturation squared times its light. A grey pixel thus
    weighs almost nothing, and the colours of a zone decide its colour.
    """
    rows, columns = crop
    light = LIGHT
    found = []
    for column in range(columns, width - columns):
        plain_red = plain_green = plain_blue = 0.0
        red_sum = green_sum = blue_sum = weights = 0.0
        for row in range(rows, height - rows):
            at = (row * width + column) * 3
            red = light[frame[at]]
            green = light[frame[at + 1]]
            blue = light[frame[at + 2]]
            top = red if red > green else green
            top = top if top > blue else blue
            low = red if red < green else green
            low = low if low < blue else blue
            weight = GREY_WEIGHT
            if top > 0.0:
                weight += (top - low) * (top - low) / top
            plain_red += red
            plain_green += green
            plain_blue += blue
            red_sum += red * weight
            green_sum += green * weight
            blue_sum += blue * weight
            weights += weight
        found.append(((plain_red, plain_green, plain_blue),
                      (red_sum, green_sum, blue_sum), weights))
    return found


def zones(frame, crop=(0, 0), width=WIDTH, height=HEIGHT):
    """Returns (mean light, colour, weight) of each zone, from the left.

    The zones divide the picture inside the bars into equal columns. The mean
    light is that of the screen in the zone. The colour is the mean light
    weighted by colour, and the weight is the sum of the weights.
    """
    rows = crop[0]
    used = height - 2 * rows
    columns = _columns(frame, crop, width, height)
    found = []
    for parts in _spans(len(columns)):
        plain = [0.0, 0.0, 0.0]
        weighted = [0.0, 0.0, 0.0]
        weight = 0.0
        count = 0.0
        for column, part in parts:
            sums, colour_sums, weights = columns[column]
            for channel in range(3):
                plain[channel] += sums[channel] * part
                weighted[channel] += colour_sums[channel] * part
            weight += weights * part
            count += part * used
        found.append((tuple(value / count for value in plain),
                      tuple(value / weight for value in weighted), weight))
    return found


def together(found):
    """Returns one zone with the light of all the zones of `found`."""
    weight = sum(one[2] for one in found)
    mean = tuple(sum(one[0][channel] for one in found) / len(found)
                 for channel in range(3))
    colour = tuple(sum(one[1][channel] * one[2] for one in found) / weight
                   for channel in range(3))
    return mean, colour, weight


def _more_colour(light, factor):
    grey = sum(light) / 3.0
    light = [max(0.0, grey + (channel - grey) * factor) for channel in light]
    top = max(light)
    if top > 1.0:
        # A clamp of one channel changes the hue. A scale of all three does
        # not.
        light = [channel / top for channel in light]
    return light


def shade(zone, profile=DEFAULT_PROFILE):
    """Returns the values of the LEDs for one zone, from 0 to 255."""
    mean, colour = zone[0], zone[1]
    level = max(mean)
    if level <= DARK_LIGHT:
        return (0.0, 0.0, 0.0)
    if profile == CINEMATIC:
        light = _more_colour(mean, MORE_COLOUR[CINEMATIC])
    else:
        # The colour decides the hue, and the zone decides the light.
        light = _more_colour(colour, MORE_COLOUR[profile])
        top = max(light)
        if top <= 0.0:
            return (0.0, 0.0, 0.0)
        want = max(level, LEAST_LIGHT[profile])
        light = [channel / top * want for channel in light]
    return tuple(channel * 255.0 for channel in light)


class Picture:
    """Makes the colours of the bar from each picture of the screen."""

    def __init__(self, profile=DEFAULT_PROFILE):
        self.profile = profile if profile in PROFILES else DEFAULT_PROFILE
        self.crop = Crop()

    def colours(self, frame, now):
        crop = self.crop.update(bars(frame), now)
        found = zones(frame, crop)
        if self.profile == SOLID:
            return [shade(together(found), SOLID)] * ZONES
        return [shade(zone, self.profile) for zone in found]


def encode(colours):
    """Returns one message for the pipe."""
    message = bytearray([KIND_COLOURS])
    for colour in colours:
        for channel in colour:
            message.append(max(0, min(int(channel + 0.5), 255)))
    return bytes(message)


def decode(message):
    """Returns the colours of one message, or None for a message of a
    different kind or size."""
    if len(message) != MESSAGE or message[0] != KIND_COLOURS:
        return None
    return [(float(message[1 + zone * 3]), float(message[2 + zone * 3]),
             float(message[3 + zone * 3]))
            for zone in range(ZONES)]


# -- a screen for the previews -----------------------------------------------
#
# The previews in the control panel and on the catalogue page have no screen.
# These pictures take its place: a sunset, the sea, a forest and a fire, each
# as colours from the left to the right of the screen.
DEMO = (
    ((255, 120, 20), (240, 60, 60), (90, 30, 120)),
    ((10, 60, 160), (20, 150, 200), (200, 220, 235)),
    ((20, 90, 20), (90, 160, 40), (30, 70, 25)),
    ((40, 10, 0), (255, 190, 50), (40, 10, 0)),
)
# The part of each picture in which it stays. The change to the next one
# takes the rest.
DEMO_STAY = 0.6


def _gradient(stops):
    colours = []
    for zone in range(ZONES):
        place = zone * (len(stops) - 1) / float(ZONES - 1)
        first = min(int(place), len(stops) - 2)
        blend = place - first
        colours.append(tuple(float(low + (high - low) * blend) for low, high
                             in zip(stops[first], stops[first + 1])))
    return colours


def demo(fraction):
    """Returns the colours of the screen of the previews, at `fraction` of
    its loop. The loop ends where it starts."""
    place = (fraction % 1.0) * len(DEMO)
    index = int(place) % len(DEMO)
    blend = max(0.0, (place - int(place) - DEMO_STAY) / (1.0 - DEMO_STAY))
    now = _gradient(DEMO[index])
    then = _gradient(DEMO[(index + 1) % len(DEMO)])
    return [tuple(low + (high - low) * blend for low, high in zip(one, two))
            for one, two in zip(now, then)]


# -- the LED service: the colours for the renderer -------------------------

# How long the bar keeps the last colours with no new message. After that the
# renderer gives the slot back to the rainbow of Steam, as with no sensor.
HOLD = 3.0
# How long the pipe stays open after the last frame that showed the mirror. A
# short change of the effect thus does not stop the capture.
RELEASE = 10.0


class Mirror:
    """The colours of the screen, for the renderer in the LED service."""

    def __init__(self, path=None, clock=time.monotonic,
                 profile=DEFAULT_PROFILE):
        self.path = FIFO if path is None else path
        self.clock = clock
        self.rise, self.fall = EASING.get(profile, EASING[DEFAULT_PROFILE])
        self.fd = None
        self.target = None
        self.shown = None
        # The time of the last message, of the last frame, and of the last
        # frame that asked for the mirror.
        self.arrived = None
        self.drawn = None
        self.wanted = None
        self._rest = b""
        self._warned = False

    def create(self):
        """Makes the pipe. The LED service calls this one time at its start."""
        try:
            os.mkfifo(self.path, FIFO_MODE)
        except FileExistsError:
            pass
        if not stat.S_ISFIFO(os.lstat(self.path).st_mode):
            raise OSError(errno.EEXIST, "not a pipe", self.path)
        # umask changes the mode of mkfifo, so set the mode again.
        os.chmod(self.path, FIFO_MODE)

    def colours(self, now=None):
        """Returns the colours of this frame, or None with no recent picture.

        Each call says that the bar shows the mirror now. The first call opens
        the pipe, and that starts the capture.
        """
        now = self.clock() if now is None else now
        self.wanted = now
        if self.fd is None:
            self._open()
        if self.fd is not None:
            self._read(now)
        if self.target is None or now - self.arrived > HOLD:
            self.shown = None
            self.drawn = now
            return None
        if self.shown is None:
            self.shown = list(self.target)
        else:
            step = max(0.0, min(now - self.drawn, 0.25))
            rise = 1.0 - math.exp(-step / self.rise)
            fall = 1.0 - math.exp(-step / self.fall)
            for zone, (target, shown) in enumerate(zip(self.target,
                                                       self.shown)):
                # One speed for the three channels of a zone, so that the
                # hue does not change on the way.
                blend = rise if max(target) > max(shown) else fall
                self.shown[zone] = tuple(old + (new - old) * blend
                                         for old, new in zip(shown, target))
        self.drawn = now
        return list(self.shown)

    def poll(self, now=None):
        """Closes the pipe when no frame asked for the mirror for a time.

        The loop of the service calls this at each turn. That stops the
        capture of the screen.
        """
        now = self.clock() if now is None else now
        if self.fd is not None and (self.wanted is None
                                    or now - self.wanted > RELEASE):
            self.close()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.target = None
        self.shown = None
        self._rest = b""

    def _open(self):
        try:
            self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            if not self._warned:
                LOG.warning("mirror: cannot open %s: %s", self.path, exc)
                self._warned = True
            return
        LOG.info("mirror: the bar shows the screen, so the pipe is open")

    def _read(self, now):
        size = MESSAGE * 64
        while True:
            try:
                data = os.read(self.fd, size)
            except BlockingIOError:
                return
            except OSError as exc:
                LOG.warning("mirror: reading %s failed: %s", self.path, exc)
                self.close()
                return
            # Empty: no writer has the pipe open now.
            if not data:
                return
            # Each write is one whole message. A read can still stop in a
            # message, so the rest waits for the next read.
            more = len(data)
            data = self._rest + data
            whole = len(data) - len(data) % MESSAGE
            self._rest = data[whole:]
            if whole:
                colours = decode(data[whole - MESSAGE:whole])
                if colours is not None:
                    self.target = colours
                    self.arrived = now
            if more < size:
                return


# -- the user service: from the screen into the pipe ------------------------

GST_LAUNCH = "gst-launch-1.0"
GST_INSPECT = "gst-inspect-1.0"
PW_DUMP = "pw-dump"
# The elements of the pipeline. pipewiresrc is in a package of its own on
# many systems, and the others are in the base plugins.
ELEMENTS = ("pipewiresrc", "videorate", "queue", "videoscale",
            "videoconvert", "fdsink")
# The stream of the screen in Game Mode, and the name of the reader.
SCREEN_NODE = "gamescope"
CLIENT = "steamos-utility-center-mirror"

# How often Watcher looks at the pipe while nothing reads it, and while the
# pipe is not there. The LED service makes the pipe at its start, after each
# change of its settings. A person who chooses the mirror then sees the new
# status after this time. A look costs one open() that fails.
LOOK_SECONDS = 2.0
# How often it asks PipeWire about other readers while it reads the screen.
CHECK_SECONDS = 5.0
# The wait after a failure: the first value, then two times the last value,
# up to the maximum.
RETRY_SECONDS = 5.0
RETRY_MOST = 60.0
# How long a new capture can take to connect to the stream of gamescope.
LINK_SECONDS = 10.0
# How often Watcher looks at a share while the portal asks a person.
ASK_SECONDS = 0.5
# How long Watcher waits for the end of a share after the end of its capture.
# KWin can end the stream a moment before the portal closes the session.
SHARE_SECONDS = 1.0
# How long a capture waits for a new reader of the pipe. The LED service
# starts again at each change of its settings, and its pipe goes and comes
# back. A new capture is a new reader of the stream of gamescope, so the
# capture goes on through that gap.
KEEP_SECONDS = 10.0
# gamescope sends a picture only when the game or Steam changes the screen.
# It sends none at the start of a capture either. A still screen thus gives
# no picture, and that is not a failure. The bar keeps a picture for HOLD
# seconds, so Watcher sends the last colours again after this time.
REPEAT_SECONDS = 1.0
# How often Watcher writes the status file, and the age at which a reader
# calls it GONE.
STATUS_SECONDS = 2.0
STATUS_STALE = 15.0

# The error lines that Pipeline keeps, and writes into the log at the end.
ERROR_LINES = 20
# How often Watcher looks at the settings file for a new profile.
PROFILE_SECONDS = 2.0

TICKS = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def command(target, by_id=False, rate=True, fd=None, cap=False):
    """Returns the argument list of the pipeline.

    GStreamer before 1.22 has no target-object. A pipeline for that version
    names the node by its id with path=. The screen cast portal gives the id
    of its node and a file descriptor that reads only that node, so a
    pipeline with fd also names the node by its id.

    With cap, the pipeline asks the stream for RATE pictures each second at
    the most. Only the probe uses it (portal.probe): on one PC, a capture of
    KWin with it gave no picture and no error.

    videorate drops the pictures that come too soon. Its output must have a
    fixed rate: the stream of gamescope has the rate 0/1 and no duration on
    its pictures, and on such a stream videorate with max-rate stops the
    program with a failed assertion. With rate=False, the pipeline has no
    videorate, and Watcher drops the pictures itself.
    """
    source = ["pipewiresrc"] + (["fd=%d" % fd] if fd is not None else [])
    source += [("path=%s" if by_id or fd is not None else "target-object=%s")
               % target, "client-name=" + CLIENT, "do-timestamp=true"]
    if cap:
        source += ["!", "video/x-raw,max-framerate=%d/1" % RATE]
    if rate:
        source += ["!", "videorate", "drop-only=true",
                   "!", "video/x-raw,framerate=%d/1" % RATE]
    return ([GST_LAUNCH, "-q"] + source
            + ["!", "queue", "leaky=downstream", "max-size-buffers=1",
               "!", "videoscale", "method=nearest-neighbour",
               "!", "video/x-raw,width=%d,height=%d"
               % (COARSE * WIDTH, COARSE * HEIGHT),
               "!", "videoscale", "method=bilinear2",
               "!", "video/x-raw,width=%d,height=%d" % (WIDTH, HEIGHT),
               "!", "videoconvert",
               "!", "video/x-raw,format=RGB",
               "!", "fdsink", "fd=1", "sync=false"])


def has_element(name, run=subprocess.run):
    """Returns whether GStreamer has the element `name`."""
    try:
        done = run([GST_INSPECT, "--exists", name], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def pw_dump(run=subprocess.run):
    """Returns the objects of PipeWire, or None when pw-dump fails."""
    try:
        done = run([PW_DUMP], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        objects = json.loads(done.stdout)
    except ValueError:
        return None
    if not isinstance(objects, list):
        return None
    return [one for one in objects if isinstance(one, dict)]


def _info(one):
    info = one.get("info")
    return info if isinstance(info, dict) else {}


def _props(one):
    props = _info(one).get("props")
    return props if isinstance(props, dict) else {}


def screen_node(objects):
    """Returns the id of the stream of the screen, or None."""
    for one in objects:
        props = _props(one)
        if (one.get("type") == "PipeWire:Interface:Node"
                and props.get("node.name") == SCREEN_NODE
                and props.get("media.class") == "Video/Source"):
            return one.get("id")
    return None


def _same(first, second):
    return first is not None and str(first) == str(second)


def _links(objects, node):
    """Gives (link info, process id, name) for each reader of `node`.

    The reader of a link is a node, and its client says which process it
    is. PipeWire sets pipewire.sec.pid itself, so a client cannot give a
    false one.
    """
    nodes = {}
    clients = {}
    for one in objects:
        if one.get("type") == "PipeWire:Interface:Node":
            nodes[one.get("id")] = _props(one)
        elif one.get("type") == "PipeWire:Interface:Client":
            clients[one.get("id")] = _props(one)
    for one in objects:
        info = _info(one)
        if (one.get("type") != "PipeWire:Interface:Link"
                or not _same(info.get("output-node-id"), node)):
            continue
        reader = nodes.get(info.get("input-node-id"), {})
        client = {}
        for key, value in clients.items():
            if _same(key, reader.get("client.id")):
                client = value
        pid = client.get("pipewire.sec.pid",
                         client.get("application.process.id"))
        yield info, pid, (reader.get("application.name")
                          or client.get("application.name")
                          or reader.get("node.name") or "unknown")


def readers(objects, node, own_pid=None):
    """Returns the names of the programs that read the stream `node`.

    The readers of `own_pid` are not in the list.
    """
    return [_name(name) for _info, pid, name in _links(objects, node)
            if own_pid is None or not _same(pid, own_pid)]


def own_link(objects, node, own_pid):
    """Returns (state, error) of the link from `node` to `own_pid`.

    The state is "active" while the link can carry pictures, also while
    gamescope sends none. None means no link.
    """
    for info, pid, _name in _links(objects, node):
        if _same(pid, own_pid):
            return (_short(str(info.get("state") or "unknown")),
                    _short(str(info.get("error") or "")))
    return None


def _name(text):
    """Returns a name that is safe and short for the status."""
    return re.sub(r"[^A-Za-z0-9 ._-]", "", str(text))[:24] or "unknown"


def screen_size(objects, node):
    """Returns the size of the stream as "WxH", or "" with no format."""
    for one in objects:
        info = _info(one)
        if (one.get("type") != "PipeWire:Interface:Port"
                or info.get("direction") != "output"
                or not _same(_props(one).get("node.id"), node)):
            continue
        params = info.get("params")
        formats = params.get("Format") if isinstance(params, dict) else None
        for found in formats if isinstance(formats, list) else ():
            size = found.get("size") if isinstance(found, dict) else None
            try:
                return "%dx%d" % (int(size["width"]), int(size["height"]))
            except (KeyError, TypeError, ValueError):
                continue
    return ""


def cpu_seconds(pid, proc="/proc"):
    """Returns the processor time of `pid` in seconds, or 0.0."""
    try:
        with open(os.path.join(proc, str(pid), "stat")) as handle:
            fields = handle.read().rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / float(TICKS)
    except (OSError, IndexError, ValueError):
        return 0.0


def _own_cpu():
    times = os.times()
    return times[0] + times[1]


def _short(line):
    """Returns the useful end of an error line of gst-launch-1.0."""
    line = line.strip()
    for prefix in ("ERROR:", "WARNING:"):
        if line.startswith(prefix):
            line = line[len(prefix):].strip()
    # "from element /GstPipeline:pipeline0/...: text" keeps the text.
    if line.startswith("from element"):
        line = line.split(": ", 1)[-1]
    for words in ("erroneous pipeline: ", "stream error: "):
        line = line.replace(words, "")
    # A path keeps its last part: the name of the file.
    line = re.sub(r"(?<!\S)\.{0,2}/(?:[^\s/]+/)*", "", line)
    return re.sub(r"[^\x20-\x7e]", "", line)[:DETAIL_CHARS]


# gst-launch-1.0 gives an error of an element in four lines:
#   ERROR: from element /GstPipeline:pipeline0/GstVideoRate:videorate0: text
#   Additional debug info:
#   ../gst/videorate/gstvideorate.c(1699): function (): /GstPipeline:...:
#   a text for a developer
_FROM = re.compile(r"(?:ERROR|WARNING): from element (\S+): (.*)")
_PLACE = re.compile(r"\S+\(\d+\): \S+ \(\): ")
_REASON = re.compile(r"reason (\S+)")
# A failed check in the code stops the program with one line:
#   ERROR:../gst/videorate/gstvideorate.c:757:function: assertion failed: (...)
_CHECK = re.compile(r"(?:ERROR|CRITICAL):(\S+?\.c):\d+:\w+: (.*)")
# The texts that say only that an element stopped. The text for a developer
# says more.
_GENERAL = ("Internal data stream error.",
            "GStreamer encountered a general stream error.")


def _element(name):
    """Returns the element from a path of GStreamer or a file of its code."""
    name = re.split(r"[/:]", name)[-1]
    if name.endswith(".c"):
        name = name[:-2]
        if name.startswith("gst"):
            name = name[3:]
    return re.sub(r"\d+$", "", name) or "?"


def describe(lines):
    """Returns the most useful short line from the last error lines."""
    lines = [line.strip() for line in lines if line.strip()]
    for line in reversed(lines):
        found = _CHECK.fullmatch(line)
        if found:
            return _short("%s: %s" % (_element(found.group(1)),
                                      found.group(2)))
    for index in range(len(lines) - 1, -1, -1):
        found = _FROM.fullmatch(lines[index])
        if not found:
            continue
        text = found.group(2)
        more = []
        for line in lines[index + 1:]:
            if line.startswith(("ERROR", "WARNING")):
                break
            if line != "Additional debug info:" and not _PLACE.match(line):
                more.append(line)
        reasons = [_REASON.search(line) for line in more]
        reasons = [reason.group(1) for reason in reasons if reason]
        if reasons:
            text = reasons[0]
        elif more and text in _GENERAL:
            text = " ".join(more)
        return _short("%s: %s" % (_element(found.group(1)), text))
    for line in reversed(lines):
        if line.startswith(("ERROR", "WARNING")):
            return _short(line)
    return _short(lines[-1]) if lines else ""


class Pipeline:
    """The gst-launch-1.0 child, and the pictures that it gives."""

    def __init__(self, argv, launch=subprocess.Popen, keep=()):
        self.argv = argv
        self.launch = launch
        # The file descriptors that the child gets, as the fd of the portal.
        self.keep = tuple(keep)
        self.process = None
        self.ended = False
        self._buffer = bytearray()
        self._errors = []
        self._part = ""

    @property
    def pid(self):
        return None if self.process is None else self.process.pid

    def start(self):
        extra = {"pass_fds": self.keep} if self.keep else {}
        self.process = self.launch(
            self.argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
            env=dict(os.environ, LC_ALL="C"), **extra)
        for stream in (self.process.stdout, self.process.stderr):
            os.set_blocking(stream.fileno(), False)

    def frame(self, timeout):
        """Returns the newest whole picture, or None after `timeout` seconds.

        Older pictures in the pipe are discarded. The newest one is the
        screen now.
        """
        streams = [self.process.stdout, self.process.stderr]
        try:
            readable = select.select(streams, [], [], timeout)[0]
        except (OSError, ValueError):
            readable = []
        if self.process.stderr in readable:
            self._read_errors()
        if self.process.stdout in readable:
            try:
                chunk = os.read(self.process.stdout.fileno(), FRAME * 8)
            except BlockingIOError:
                chunk = None
            except OSError:
                chunk = b""
            if chunk == b"":
                self.ended = True
            elif chunk:
                self._buffer += chunk
        whole = len(self._buffer) // FRAME
        if not whole:
            if self.ended:
                # Do not turn at full speed on a closed pipe.
                time.sleep(min(timeout, 0.1))
            return None
        picture = bytes(self._buffer[(whole - 1) * FRAME:whole * FRAME])
        del self._buffer[:whole * FRAME]
        return picture

    def _read_errors(self):
        """Reads what stderr has. Returns the number of bytes."""
        try:
            chunk = os.read(self.process.stderr.fileno(), 4096)
        except OSError:
            return 0
        # A line can come in two reads. The part after the last line end
        # waits for the next read.
        text = self._part + chunk.decode("utf-8", "replace")
        lines = text.split("\n")
        self._part = "" if not chunk else lines.pop()[-1024:]
        for line in lines:
            line = re.sub(r"[^\x20-\x7e]", "", line).strip()
            if line:
                self._errors = (self._errors + [line])[-ERROR_LINES:]
        return len(chunk)

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def said(self):
        """Returns the last lines that gst-launch-1.0 wrote as errors."""
        for _read in range(64):
            if not self._read_errors():
                break
        return self._errors + ([self._part.strip()] if self._part.strip()
                               else [])

    def error(self):
        """Returns the most useful of the last error lines, or ""."""
        return describe(self.said())

    def stop(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except OSError:
                    pass
                self.process.wait()
        for stream in (self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except (OSError, AttributeError):
                pass


def status_path():
    """The file of the status, in the runtime directory of the user."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return os.path.join(runtime, STATUS_NAME)


def read_status(path=None, wall=time.time):
    """Returns the status that Watcher wrote, as a small dict.

    An old, absent or damaged file gives GONE: Watcher writes the file each
    STATUS_SECONDS while it runs.
    """
    path = status_path() if path is None else path
    try:
        with open(path, "rb") as handle:
            values = json.loads(handle.read(4096).decode("utf-8"))
    except (OSError, ValueError):
        return {"state": GONE}
    if not isinstance(values, dict) or values.get("state") not in STATES:
        return {"state": GONE}
    at = values.get("at")
    if (not isinstance(at, (int, float)) or isinstance(at, bool)
            or abs(wall() - at) > STATUS_STALE):
        return {"state": GONE}
    found = {"state": values["state"]}
    detail = values.get("detail")
    if isinstance(detail, str) and detail:
        found["detail"] = detail[:DETAIL_CHARS]
    for key in ("fps", "cpu"):
        value = values.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found[key] = round(float(value), 1)
    source = values.get("source")
    if isinstance(source, str) and re.match(r"^\d{1,5}x\d{1,5}$", source):
        found["source"] = source
    return found


class ProfileFile:
    """The profile of the mirror in the settings file, or a different value.

    The file changes while Watcher runs: a person selects a profile on the
    panel or in the plugin. So it reads the file again after each change of
    its time, its size or its inode, and at most each PROFILE_SECONDS.
    `read` gives the value in the file at a path. A value that is not one of
    `choices` gives `default`.
    """

    def __init__(self, path, read, clock=time.monotonic, choices=PROFILES,
                 default=DEFAULT_PROFILE):
        self.path = path
        self.read = read
        self.clock = clock
        self.choices = choices
        self.default = default
        self.value = default
        self._stamp = None
        self._looked = -math.inf

    def __call__(self):
        now = self.clock()
        if now - self._looked < PROFILE_SECONDS:
            return self.value
        self._looked = now
        try:
            info = os.stat(self.path)
            stamp = (info.st_mtime_ns, info.st_size, info.st_ino)
        except OSError:
            stamp = None
        if stamp == self._stamp:
            return self.value
        self._stamp = stamp
        found = self.default
        if stamp is not None:
            try:
                found = self.read(self.path)
            except (OSError, ValueError, KeyError) as exc:
                LOG.warning("mirror: cannot read the settings in %s: %s",
                            self.path, exc)
        self.value = found if found in self.choices else self.default
        return self.value


class Watcher:
    """Reads the screen while the LED service shows the mirror.

    In Game Mode it reads the stream of gamescope. On the desktop it reads
    the screen that the portal shares, but only for the mirror scene of the
    desktop. share starts a share (portal.Share), and wanted says if the
    scene of the desktop is the mirror. desktop gives the process id of the
    compositor of the desktop, or None while no desktop runs.
    """

    def __init__(self, fifo=None, status=None, dump=pw_dump,
                 launch=subprocess.Popen, which=shutil.which,
                 element=has_element, clock=time.monotonic, wall=time.time,
                 cpu=cpu_seconds, profile=lambda: DEFAULT_PROFILE,
                 share=None, desktop=lambda: None, wanted=lambda: False):
        self.fifo = FIFO if fifo is None else fifo
        self.profile = profile
        self.start_share = share
        self.desktop = desktop
        self.wanted = wanted
        self.share = None
        self.node = None
        # A refusal of the share holds for the desktop of the compositor
        # refused_by. It is None with no refusal, "" for the dialog, and
        # "stopped" for a share that the person stopped.
        self.refused = None
        self.refused_by = None
        self.asked_at = 0.0
        self.status = status_path() if status is None else status
        self.dump = dump
        self.launch = launch
        self.which = which
        self.element = element
        self.clock = clock
        self.wall = wall
        self.cpu = cpu
        self.state = None
        self.detail = ""
        self.out = None
        self.pipeline = None
        self.picture = Picture()
        self.by_id = False
        self.rate = True
        self.pending = None
        self.used_at = -math.inf
        self.lost_at = -math.inf
        self.tools = False
        self.retry_at = 0.0
        self.retry = RETRY_SECONDS
        self.started = 0.0
        self.next_check = 0.0
        self.sent = None
        self.sent_at = 0.0
        self.source = ""
        self.fps = 0.0
        self.load = 0.0
        self.frames = 0
        self.counted_at = 0.0
        self.counted_cpu = 0.0
        self.reported_at = None
        self._changed = True

    # -- the loop ----------------------------------------------------------

    def run(self, running=lambda: True, sleep=time.sleep):
        try:
            while running():
                wait = self.step()
                if wait > 0:
                    sleep(wait)
        finally:
            self.close()

    def step(self):
        """Does one turn of the work. Returns the time to wait after it."""
        now = self.clock()
        if self.out is not None and self._reader_gone():
            # The bar shows a different effect, or the LED service starts
            # again. A capture waits KEEP_SECONDS for a new reader.
            self._disconnect()
            self.lost_at = now
            if self.pipeline is None and self.share is None:
                self._set(IDLE)
        # A share keeps its dialog through the gap too.
        keeping = self.pipeline is not None or self.share is not None
        if self.out is None and not self._connect(quiet=keeping):
            if not keeping:
                wait = LOOK_SECONDS
            elif now - self.lost_at > KEEP_SECONDS:
                self._stop()
                self._connect()
                wait = LOOK_SECONDS
            elif self.pipeline is None:
                wait = ASK_SECONDS
            else:
                # The pictures go nowhere until the new pipe is there.
                self._watch()
                wait = 0.0
        elif self.pipeline is None:
            wait = self._begin(now)
        else:
            self._watch()
            wait = 0.0
        self._report(self.clock())
        return wait

    def close(self):
        """Stops the capture and removes the status file."""
        self._stop()
        self._disconnect()
        try:
            os.unlink(self.status)
        except OSError:
            pass

    # -- the pipe ----------------------------------------------------------

    def _connect(self, quiet=False):
        """Opens the pipe. `quiet` keeps the state of a capture that runs."""
        try:
            fd = os.open(self.fifo, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as exc:
            if quiet:
                return False
            if exc.errno == errno.ENOENT:
                self._set(OFF)
            elif exc.errno == errno.ENXIO:
                self._set(IDLE)
            else:
                self._set(FAILED, os.strerror(exc.errno))
            return False
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            os.close(fd)
            self._set(FAILED, "%s is not a pipe" % self.fifo)
            return False
        self.out = fd
        return True

    def _disconnect(self):
        if self.out is not None:
            os.close(self.out)
            self.out = None

    def _reader_gone(self):
        poller = select.poll()
        poller.register(self.out, select.POLLOUT)
        return any(events & (select.POLLERR | select.POLLHUP)
                   for _fd, events in poller.poll(0))

    def _send(self, message, now):
        if self.out is None:
            # No reader yet. The first look after the new pipe sends it.
            self.sent = message
            self.sent_at = -math.inf
            return
        try:
            os.write(self.out, message)
        except BlockingIOError:
            # The LED service is late, and the next picture replaces this.
            pass
        except OSError:
            # The reader is gone. The next step finds that and stops.
            return
        self.sent = message
        self.sent_at = now

    # -- the capture -------------------------------------------------------

    def _missing(self):
        """Returns (state, detail) for a part that is not there, or None."""
        if self.tools:
            return None
        if self.which(GST_LAUNCH) is None:
            return NO_GSTREAMER, GST_LAUNCH
        for name in ELEMENTS:
            if not self.element(name):
                return NO_PLUGIN, name
        # Programs do not go away while the machine runs, so ask one time.
        self.tools = True
        return None

    def _begin(self, now):
        if self.share is not None:
            return self._begin_desktop(now)
        if now < self.retry_at:
            return min(self.retry_at - now, LOOK_SECONDS)
        missing = self._missing()
        if missing is not None:
            self._set(*missing)
            self.retry_at = now + RETRY_MOST
            return LOOK_SECONDS
        objects = self.dump()
        if objects is None:
            self._fail(now, "no answer from pw-dump")
            return LOOK_SECONDS
        node = screen_node(objects)
        if node is None:
            return self._begin_desktop(now)
        others = readers(objects, node)
        if others:
            self._set(BUSY, others[0])
            self.retry_at = now + CHECK_SECONDS
            return LOOK_SECONDS
        return self._launch(now, command(node if self.by_id else SCREEN_NODE,
                                         self.by_id, self.rate))

    def _begin_desktop(self, now):
        """Starts a share of the desktop screen, and then its capture."""
        share = self.share
        if share is not None and now - self.asked_at >= CHECK_SECONDS:
            # A dialog of a desktop that ended gets no answer.
            self.asked_at = now
            if self.desktop() is None:
                self._stop()
                share = None
        if share is None:
            running = self.desktop()
            if self.refused is not None and self.refused_by != running:
                # A new desktop asks again.
                self.refused = None
            if self.start_share is None or running is None or not self.wanted():
                # Each question costs a run of pw-dump, and Game Mode does
                # not start in a moment.
                self._set(NO_SCREEN)
                self.retry_at = now + CHECK_SECONDS
                return LOOK_SECONDS
            if self.refused is not None:
                self._set(REFUSED, self.refused)
                self.retry_at = now + CHECK_SECONDS
                return LOOK_SECONDS
            share = self.share = self.start_share()
            self.asked_at = now
        if share.state == SHARE_ASKING:
            self._set(ASKING)
            return ASK_SECONDS
        if share.state != SHARE_READY or share.stream is None:
            error = share.error
            self._stop()
            if error is not None and error.state == REFUSED:
                self._refuse("")
            elif error is None or error.state == FAILED:
                self._fail(now, error.detail if error else "the share ended")
            else:
                self._set(NO_PORTAL, error.detail or error.state)
                self.retry_at = now + RETRY_MOST
            return LOOK_SECONDS
        stream = share.stream
        self.node = stream.node
        return self._launch(now, command(str(stream.node), rate=self.rate,
                                         fd=stream.fd),
                            keep=(stream.fd,))

    def _launch(self, now, argv, keep=()):
        pipeline = Pipeline(argv, launch=self.launch, keep=keep)
        try:
            pipeline.start()
        except (OSError, ValueError) as exc:
            self._fail(now, str(exc))
            return LOOK_SECONDS
        self.pipeline = pipeline
        self.picture = Picture()
        self.pending = None
        self.used_at = -math.inf
        self.started = now
        self.next_check = now + CHECK_SECONDS
        self.sent = None
        self.source = ""
        self.frames = 0
        self.counted_at = now
        self.counted_cpu = self._cpu_now()
        self._set(STARTING)
        return 0.0

    def _watch(self):
        pipeline = self.pipeline
        # At most RATE pictures each second go to the bar. A picture that
        # comes too soon waits, so the last picture of a change is not lost.
        due = self.used_at + 1.0 / RATE
        wait = 0.25
        if self.pending is not None:
            wait = min(wait, max(0.0, due - self.clock()))
        picture = pipeline.frame(wait)
        now = self.clock()
        if picture is not None:
            self.pending = picture
        if self.pending is not None and now >= due:
            self._use(now)
        elif self.sent is not None and now - self.sent_at >= REPEAT_SECONDS:
            self._send(self.sent, now)
        if not pipeline.alive() or pipeline.ended:
            for line in pipeline.said():
                LOG.warning("mirror: %s said: %s", GST_LAUNCH, line)
            detail = pipeline.error()
            if self.share is not None:
                self.share.finished.wait(SHARE_SECONDS)
                if self.share.state == SHARE_ENDED:
                    self._share_ended(now)
                    return
            if not self.by_id and "target-object" in detail:
                # An older GStreamer. Try again at once, with the id.
                self.by_id = True
                self._stop()
                self._set(STARTING)
                return
            if self.rate and detail.startswith("videorate"):
                # This videorate cannot drop the pictures. Try again at
                # once with no videorate.
                self.rate = False
                self._stop()
                self._set(STARTING)
                return
            self._fail(now, detail or "gst-launch-1.0 stopped")
            return
        if now >= self.next_check:
            self.next_check = now + CHECK_SECONDS
            self._check(now)

    def _use(self, now):
        """Sends the colours of the waiting picture to the bar."""
        profile = self.profile()
        if profile != self.picture.profile:
            LOG.info("mirror: the profile is %s", profile)
            self.picture = Picture(profile)
        self._send(encode(self.picture.colours(self.pending, now)), now)
        self.pending = None
        self.used_at = now
        self.frames += 1
        if self.state != RUNNING:
            self._set(RUNNING)
            self.retry = RETRY_SECONDS

    def _check(self, now):
        """Stops the capture when a different program reads the screen.

        It also looks at the link of a capture with no picture. An active
        link with no picture is a still screen. A link that does not become
        active is a failure.
        """
        if self.share is not None:
            self._check_desktop(now)
            return
        objects = self.dump()
        if objects is None:
            return
        node = screen_node(objects)
        if node is None:
            self._stop()
            self._set(NO_SCREEN)
            self.retry_at = now + LOOK_SECONDS
            return
        others = readers(objects, node, own_pid=self.pipeline.pid)
        if others:
            # The other program came after this one. Make room for it: the
            # screen of a recording is more important than the bar.
            self._stop()
            self._set(BUSY, others[0])
            self.retry_at = now + CHECK_SECONDS
            return
        self.source = screen_size(objects, node)
        if self.state not in (STARTING, WAITING):
            return
        link = own_link(objects, node, self.pipeline.pid)
        if link is not None and link[0] == "active":
            self._set(WAITING)
        elif now - self.started >= LINK_SECONDS:
            if link is None:
                self._fail(now, "no link to gamescope")
            else:
                self._fail(now, "link " + ": ".join(part for part in link
                                                    if part))

    def _check_desktop(self, now):
        """Looks at the share and at the size of its screen.

        KWin sends a picture when the screen changes, so a still desktop
        sends none. A capture with no picture is thus WAITING, not FAILED.
        """
        if self.share.state == SHARE_ENDED:
            self._share_ended(now)
            return
        objects = self.dump()
        found = screen_size(objects, self.node) if objects is not None else ""
        stream = self.share.stream
        self.source = found or ("%dx%d" % (stream.width, stream.height)
                                if stream is not None else "")
        if self.state == STARTING and now - self.started >= LINK_SECONDS:
            self._set(WAITING)

    def _share_ended(self, now):
        """The portal closed the share, or the desktop ended."""
        closed = self.share.closed
        self._stop()
        if closed and self.desktop() is not None:
            # The person stopped the share.
            self._refuse("stopped")
        else:
            self._set(NO_SCREEN)
        self.retry_at = now + LOOK_SECONDS

    def _refuse(self, detail):
        """No new share until the desktop or this service starts again."""
        self.refused = detail
        self.refused_by = self.desktop()
        self._set(REFUSED, detail)

    def _fail(self, now, detail):
        self._stop()
        self._set(FAILED, detail)
        self.retry_at = now + self.retry
        self.retry = min(self.retry * 2.0, RETRY_MOST)

    def _stop(self):
        if self.pipeline is not None:
            self.pipeline.stop()
            self.pipeline = None
        if self.share is not None:
            # A new capture of the desktop needs a new reader of the portal,
            # so the share ends with its capture.
            self.share.stop()
            self.share = None
            self.node = None
        self.sent = None
        self.fps = 0.0
        self.load = 0.0

    def _cpu_now(self):
        used = _own_cpu()
        if self.pipeline is not None and self.pipeline.pid is not None:
            used += self.cpu(self.pipeline.pid)
        return used

    # -- the status --------------------------------------------------------

    def _set(self, state, detail=""):
        detail = _short(detail) if detail else ""
        if state == self.state and detail == self.detail:
            return
        if detail:
            LOG.info("mirror: %s (%s)", state, detail)
        else:
            LOG.info("mirror: %s", state)
        self.state = state
        self.detail = detail
        self._changed = True

    def _report(self, now):
        if (not self._changed and self.reported_at is not None
                and now - self.reported_at < STATUS_SECONDS):
            return
        if self.pipeline is not None and self.state == RUNNING:
            span = now - self.counted_at
            if span >= 1.0:
                used = self._cpu_now()
                self.fps = self.frames / span
                self.load = max(0.0, (used - self.counted_cpu) / span * 100.0)
                self.frames = 0
                self.counted_at = now
                self.counted_cpu = used
        values = {"state": self.state, "at": round(self.wall(), 1)}
        if self.detail:
            values["detail"] = self.detail
        if self.state == RUNNING:
            values["fps"] = round(self.fps, 1)
            values["cpu"] = round(self.load, 1)
            if self.source:
                values["source"] = self.source
        temporary = self.status + ".new"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(values, handle)
            os.replace(temporary, self.status)
        except OSError as exc:
            LOG.debug("mirror: cannot write %s: %s", self.status, exc)
        self.reported_at = now
        self._changed = False
