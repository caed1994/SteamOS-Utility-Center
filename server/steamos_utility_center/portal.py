# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The picture of the desktop, from the screen cast portal.

In Game Mode, gamescope gives its picture to each program of the user. On the
Wayland desktop of KDE, KWin gives its picture only through the screen cast
portal. A program asks the portal, and a person allows the share in a dialog.
The portal then gives a PipeWire node and a file descriptor that reads it.

The share stays only while the connection to the session bus stays. So a
ScreenCast object keeps its bus for as long as the capture runs.

The portal can keep the approval. It then gives a restore token, and this
module keeps that token in a file that only the user can read. The next
session gives the token back, and the portal can start with no dialog.
Version 4 of the portal is the first version that can do this.

probe() does all of this one time, measures a capture, and says what it
found. A person runs it on the desktop:

    steamos-utility-center --screen-probe
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import threading
import time

from . import screen
from .cec import PYTHON_DIR

BUS_NAME = "org.freedesktop.portal.Desktop"
OBJECT = "/org/freedesktop/portal/desktop"
SCREEN_CAST = "org.freedesktop.portal.ScreenCast"
REQUEST = "org.freedesktop.portal.Request"
SESSION = "org.freedesktop.portal.Session"
PROPERTIES = "org.freedesktop.DBus.Properties"
DBUS = "org.freedesktop.DBus"
DBUS_OBJECT = "/org/freedesktop/DBus"

# AvailableSourceTypes and AvailableCursorModes are bit masks.
MONITOR = 1
WINDOW = 2
VIRTUAL = 4
CURSOR_HIDDEN = 1
CURSOR_EMBEDDED = 2
CURSOR_METADATA = 4
SOURCE_NAMES = ((MONITOR, "monitor"), (WINDOW, "window"), (VIRTUAL, "virtual"))
CURSOR_NAMES = ((CURSOR_HIDDEN, "hidden"), (CURSOR_EMBEDDED, "embedded"),
                (CURSOR_METADATA, "metadata"))

# persist_mode 2: the portal keeps the approval until the person takes it
# back. Version 4 is the first with persist_mode and restore_token.
PERSIST = 2
PERSIST_VERSION = 4

# The answers to a request. Each other number is a different end.
ALLOWED = 0
CANCELLED = 1

# Why a request gave no picture. Watcher reports REFUSED and FAILED as
# they are, and each other one as screen.NO_PORTAL.
NO_DBUS = "no-dbus"         # the copy of dbus_next is not there
NO_BUS = "no-bus"           # no session bus
NO_PORTAL = screen.NO_PORTAL    # no portal, or a portal with no screen cast
NO_MONITOR = "no-monitor"   # the portal cannot share a screen
REFUSED = screen.REFUSED    # the person cancelled the dialog
FAILED = screen.FAILED

# The time for a request with no dialog. A dialog waits for a person, and
# the caller of open() says how long that can take.
ANSWER_SECONDS = 30.0

# The errors of the bus that say that the screen cast portal is not there.
NOT_THERE = ("org.freedesktop.DBus.Error.ServiceUnknown",
             "org.freedesktop.DBus.Error.NameHasNoOwner",
             "org.freedesktop.DBus.Error.UnknownInterface",
             "org.freedesktop.DBus.Error.UnknownObject",
             "org.freedesktop.DBus.Error.UnknownMethod",
             "org.freedesktop.DBus.Error.UnknownProperty")

# The restore token. It is in the directory of the token of the panel
# (companion.TOKEN_DIR). This module cannot import companion, because
# companion imports screen. A test keeps the two the same.
TOKEN_DIR = os.path.join(".config", "steamos-utility-center")
TOKEN_FILE = "mirror-screen-token"
TOKEN_MODE = 0o600

# The copy of dbus_next in a clone of the source. The installer puts the
# same copy in PYTHON_DIR.
SOURCE_COPY = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir,
    "dbus-next"))


def load_dbus(places=(PYTHON_DIR, SOURCE_COPY)):
    """Returns the module dbus_next, or None when no copy is there.

    SteamOS ships no dbus_next, and this project carries its own copy. The
    services of the CEC toolkit find it in the same way.
    """
    for place in places:
        if (os.path.isdir(os.path.join(place, "dbus_next"))
                and place not in sys.path):
            sys.path.append(place)
    try:
        import dbus_next
        import dbus_next.aio  # noqa: F401
    except ImportError:
        return None
    return dbus_next


def request_path(sender, token):
    """The object path of a request, from the unique name of the caller.

    The portal makes it from that name with no colon and with each dot as an
    underscore. A client must watch this path before the call, because the
    answer can come before the reply to the call.
    """
    return "%s/request/%s/%s" % (OBJECT, sender.lstrip(":").replace(".", "_"),
                                 token)


def token_path(home=None):
    """Where the restore token of the screen is."""
    return os.path.join(home or os.path.expanduser("~"), TOKEN_DIR,
                        TOKEN_FILE)


def read_token(path):
    """Returns the kept restore token, or None."""
    try:
        with open(path, encoding="ascii") as handle:
            token = handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return token or None


def write_token(path, token):
    """Keeps a restore token for the next session.

    A different program of the same user can start a share with this token
    and with no dialog. So only the user can read the file, and no log
    shows the token.
    """
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    temporary = path + ".new"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, TOKEN_MODE)
    try:
        # O_CREAT does not change the mode of a file that is there.
        os.fchmod(fd, TOKEN_MODE)
        os.write(fd, token.encode("ascii") + b"\n")
    finally:
        os.close(fd)
    os.replace(temporary, path)


def forget_token(path):
    """Removes a restore token that the portal did not take."""
    try:
        os.unlink(path)
    except OSError:
        pass


def bits(mask, names):
    """The names of the bits in a mask, as "monitor, window"."""
    found = [name for bit, name in names if mask & bit]
    return ", ".join(found) if found else "none"


class PortalError(Exception):
    """A request to the portal that gave no picture."""

    def __init__(self, state, detail=""):
        super().__init__(detail or state)
        self.state = state
        self.detail = detail


class Stream:
    """The screen that the portal shares.

    node is the id of its PipeWire node, and fd reads that node. The fd
    belongs to the caller, which must close it.
    """

    def __init__(self, node, width, height, fd, token):
        self.node = node
        self.width = width
        self.height = height
        self.fd = fd
        self.token = token


def _error(reply):
    # The last part of the name: the status has one short line for it.
    detail = (reply.error_name or "error").rsplit(".", 1)[-1]
    if reply.body and isinstance(reply.body[0], str):
        detail += ": " + reply.body[0]
    return PortalError(NO_PORTAL if reply.error_name in NOT_THERE else FAILED,
                       detail)


class ScreenCast:
    """One session of the screen cast portal, on one connection to the bus.

    Each request of the portal answers with a signal, so each method waits
    for that signal. The bus must be a connected dbus_next.aio.MessageBus
    that can take file descriptors.
    """

    def __init__(self, bus, dbus):
        self.bus = bus
        self.dbus = dbus
        self.session = None
        self.closed = False
        self._waiting = {}
        self._count = 0
        bus.add_message_handler(self._on_message)

    def _on_message(self, message):
        if message.message_type != self.dbus.MessageType.SIGNAL:
            return None
        if message.interface == REQUEST and message.member == "Response":
            answer = self._waiting.pop(message.path, None)
            if answer is not None and not answer.done():
                answer.set_result(message.body)
        elif (message.interface == SESSION and message.member == "Closed"
              and message.path == self.session):
            # The person stopped the share, or the desktop ended.
            self.closed = True
        return None

    async def _call(self, interface, member, signature, body, path=OBJECT,
                    destination=BUS_NAME):
        reply = await self.bus.call(self.dbus.Message(
            destination=destination, path=path, interface=interface,
            member=member, signature=signature, body=body))
        if reply.message_type == self.dbus.MessageType.ERROR:
            raise _error(reply)
        return reply

    async def _match(self, path, interface, member):
        rule = ("type='signal',interface='%s',member='%s',path='%s'"
                % (interface, member, path))
        await self._call(DBUS, "AddMatch", "s", [rule], path=DBUS_OBJECT,
                         destination=DBUS)

    async def property(self, name):
        reply = await self._call(PROPERTIES, "Get", "ss", [SCREEN_CAST, name])
        return reply.body[0].value

    async def facts(self):
        """Returns the version, the source types and the cursor modes."""
        version = await self.property("version")
        sources = await self.property("AvailableSourceTypes")
        try:
            cursors = await self.property("AvailableCursorModes")
        except PortalError:
            # Version 1 has no cursor modes.
            cursors = 0
        return version, sources, cursors

    def _token(self):
        self._count += 1
        return "steamos_utility_center_%d_%d" % (os.getpid(), self._count)

    async def _request(self, member, signature, body, options, timeout):
        token = self._token()
        path = request_path(self.bus.unique_name, token)
        answer = asyncio.get_running_loop().create_future()
        self._waiting[path] = answer
        try:
            await self._match(path, REQUEST, "Response")
            options = dict(options, handle_token=self.dbus.Variant("s", token))
            reply = await self._call(SCREEN_CAST, member, signature,
                                     body + [options])
        except BaseException:
            self._waiting.pop(path, None)
            raise
        handle = reply.body[0] if reply.body else path
        if handle != path:
            # A portal older than version 0.9 makes a path of its own.
            self._waiting[handle] = self._waiting.pop(path, answer)
            path = handle
        try:
            response, results = await asyncio.wait_for(answer, timeout)
        except asyncio.TimeoutError:
            await self._forget(path)
            raise PortalError(FAILED, "no answer to %s in %d s"
                              % (member, timeout)) from None
        except asyncio.CancelledError:
            await self._forget(path)
            raise
        if response == CANCELLED:
            raise PortalError(REFUSED, member)
        if response != ALLOWED:
            raise PortalError(FAILED, "%s answered %d" % (member, response))
        return results

    async def _forget(self, path):
        """Takes the dialog of a request with no answer off the screen."""
        self._waiting.pop(path, None)
        with contextlib.suppress(PortalError, OSError):
            await self._call(REQUEST, "Close", "", [], path=path)

    async def open(self, token=None, version=PERSIST_VERSION,
                   cursors=CURSOR_HIDDEN, dialog_seconds=None):
        """Starts the share of one screen, and returns its Stream.

        A version of 4 or more keeps the approval, and a token from an
        earlier share can then start with no dialog. dialog_seconds is the
        longest time for the dialog, and None waits with no end.
        """
        variant = self.dbus.Variant
        results = await self._request(
            "CreateSession", "a{sv}", [],
            {"session_handle_token": variant("s", self._token())},
            ANSWER_SECONDS)
        self.session = str(results["session_handle"].value)
        await self._match(self.session, SESSION, "Closed")
        chosen = {"types": variant("u", MONITOR),
                  "multiple": variant("b", False)}
        if cursors & CURSOR_HIDDEN:
            chosen["cursor_mode"] = variant("u", CURSOR_HIDDEN)
        if version >= PERSIST_VERSION:
            chosen["persist_mode"] = variant("u", PERSIST)
            if token:
                chosen["restore_token"] = variant("s", token)
        await self._request("SelectSources", "oa{sv}", [self.session], chosen,
                            ANSWER_SECONDS)
        results = await self._request("Start", "osa{sv}", [self.session, ""],
                                      {}, dialog_seconds)
        streams = results.get("streams")
        if streams is None or not streams.value:
            raise PortalError(FAILED, "the portal shares no stream")
        node, props = streams.value[0]
        size = props.get("size")
        width, height = size.value if size is not None else (0, 0)
        kept = results.get("restore_token")
        return Stream(int(node), int(width), int(height), await self.remote(),
                      kept.value if kept is not None else None)

    async def remote(self):
        """Returns a new file descriptor that reads the shared screen.

        Each reader needs its own: two processes cannot share one
        connection to PipeWire.
        """
        reply = await self._call(SCREEN_CAST, "OpenPipeWireRemote", "oa{sv}",
                                 [self.session, {}])
        fds = list(reply.unix_fds or [])
        index = reply.body[0] if reply.body else None
        if not isinstance(index, int) or not 0 <= index < len(fds):
            for extra in fds:
                os.close(extra)
            raise PortalError(FAILED, "no file descriptor from the portal")
        fd = fds.pop(index)
        for extra in fds:
            os.close(extra)
        return fd

    async def close(self):
        """Ends the share. The portal also ends it when the bus goes."""
        session, self.session = self.session, None
        if session is None or self.closed:
            return
        try:
            await self._call(SESSION, "Close", "", [], path=session)
        except PortalError:
            pass


class Share:
    """The share of the desktop screen, held in a thread of its own.

    The share ends with its connection to the bus, so the thread holds the
    bus for as long as the share runs. Watcher reads state, stream and
    error from its own thread. The first share shows a dialog, and a person
    can take minutes to answer it. stop() takes that dialog off the screen.
    """

    def __init__(self, path=None, load=load_dbus, connect=None, start=True):
        self.path = token_path() if path is None else path
        self.load = load
        self.connect = connect
        self.state = screen.SHARE_ASKING
        self.stream = None
        self.error = None
        # The portal closed the session: the person stopped the share, or
        # the desktop ended.
        self.closed = False
        self.finished = threading.Event()
        self._stopping = threading.Event()
        self._loop = None
        self._wake = None
        self._thread = threading.Thread(target=self._run, name="screen share",
                                        daemon=True)
        if start:
            self._thread.start()

    def _run(self):
        try:
            asyncio.run(self._main())
        except Exception as exc:    # a fault of the thread must reach Watcher
            if self.error is None:
                self.error = PortalError(FAILED, str(exc) or type(exc).__name__)
        finally:
            self.state = screen.SHARE_ENDED
            self.finished.set()

    async def _main(self):
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        if self._stopping.is_set():
            return
        dbus = self.load()
        if dbus is None:
            self.error = PortalError(NO_DBUS, "dbus_next is not there")
            return
        try:
            bus = await (self.connect or _connect)(dbus)
        except Exception as exc:    # dbus_next raises many kinds of errors
            self.error = PortalError(NO_BUS, str(exc))
            return
        cast = ScreenCast(bus, dbus)
        try:
            opening = asyncio.ensure_future(self._open(cast))
            stopping = asyncio.ensure_future(self._wake.wait())
            await asyncio.wait((opening, stopping),
                               return_when=asyncio.FIRST_COMPLETED)
            if not opening.done():
                opening.cancel()
                with contextlib.suppress(asyncio.CancelledError, PortalError):
                    await opening
                return
            stopping.cancel()
            self.stream = opening.result()
            self.state = screen.SHARE_READY
            while not (self._wake.is_set() or cast.closed):
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), 1.0)
            self.closed = cast.closed
        except PortalError as exc:
            self.error = exc
        finally:
            await cast.close()
            bus.disconnect()

    async def _open(self, cast):
        version, sources, cursors = await cast.facts()
        if not sources & MONITOR:
            raise PortalError(NO_MONITOR, "the portal cannot share a screen")
        token = read_token(self.path)
        stream = await cast.open(token, version, cursors)
        if stream.token:
            write_token(self.path, stream.token)
        elif token:
            # A token is good for one start only.
            forget_token(self.path)
        return stream

    def stop(self, timeout=5.0):
        """Ends the share, waits for the thread, and closes the fd."""
        self._stopping.set()
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(wake.set)
        if self._thread.is_alive():
            self._thread.join(timeout)
        stream, self.stream = self.stream, None
        if stream is not None:
            with contextlib.suppress(OSError):
                os.close(stream.fd)


def desktop_runs(proc="/proc"):
    """Returns the process id of KWin on Wayland, or None.

    Watcher asks the portal only while that desktop runs. In Game Mode the
    portal can be there with no screen to share.
    """
    return find_process(("kwin_wayland",), proc)


# -- the probe ---------------------------------------------------------------

# How long the probe measures, first with no capture and then with it.
PROBE_SECONDS = 10.0
# How long the probe waits for a person at the dialog.
DIALOG_SECONDS = 120.0
# The programs of the compositor, whose load the probe measures.
COMPOSITORS = ("kwin_wayland", "kwin_x11", "gamescope-wl", "gamescope")


def find_process(names, proc="/proc"):
    """Returns the pid of the first process with one of the names, or None."""
    try:
        entries = sorted(os.listdir(proc))
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc, entry, "comm"),
                      encoding="utf-8") as handle:
                name = handle.read().strip()
        except OSError:
            continue
        if name in names:
            return int(entry)
    return None


def _load(pid, before, seconds, cpu, proc):
    """The part of one core that pid used since `before`, in per cent."""
    if pid is None or before is None or seconds <= 0:
        return None
    now = cpu(pid, proc)
    if now is None:
        return None
    return 100.0 * (now - before) / seconds


def _count(pipeline, seconds, clock):
    """Reads pictures for `seconds`. Returns their number."""
    frames = 0
    end = clock() + seconds
    while True:
        left = end - clock()
        if left <= 0 or pipeline.ended or not pipeline.alive():
            return frames
        if pipeline.frame(min(left, 0.25)) is not None:
            frames += 1


async def _connect(dbus):
    bus = dbus.aio.MessageBus(bus_type=dbus.BusType.SESSION,
                              negotiate_unix_fd=True)
    return await bus.connect()


async def _probe(seconds, out, dbus, connect, launch, run, proc, path, clock,
                 cpu, environ):
    out("Session type: %s" % (environ.get("XDG_SESSION_TYPE") or "not set"))
    try:
        said = run([screen.GST_LAUNCH, "--version"], capture_output=True,
                   text=True, timeout=10).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        said = []
    out("GStreamer: %s" % (said[0].strip() if said else "not found"))
    if dbus is None:
        out("dbus_next is not there. Run install.sh again.")
        return 1
    try:
        bus = await connect(dbus)
    except Exception as exc:    # dbus_next raises many kinds of errors here
        out("No session bus: %s" % exc)
        return 1
    cast = ScreenCast(bus, dbus)
    try:
        return await _share(cast, seconds, out, launch, proc, path, clock, cpu)
    finally:
        await cast.close()
        bus.disconnect()


async def _share(cast, seconds, out, launch, proc, path, clock, cpu):
    try:
        version, sources, cursors = await cast.facts()
    except PortalError as exc:
        out("No screen cast portal: %s" % exc.detail)
        return 1
    out("Screen cast portal: version %d, sources: %s, pointer: %s"
        % (version, bits(sources, SOURCE_NAMES), bits(cursors, CURSOR_NAMES)))
    if not sources & MONITOR:
        out("This portal cannot share a screen.")
        return 1
    token = read_token(path)
    out("A kept approval: %s" % ("yes" if token else "no"))
    out("The portal can show a dialog now. Allow the share of the screen.")
    asked = clock()
    try:
        stream = await cast.open(token, version, cursors, DIALOG_SECONDS)
    except PortalError as exc:
        if exc.state == REFUSED:
            out("The share was refused in the dialog.")
        else:
            out("The portal gave no screen: %s" % exc.detail)
        return 1
    out("Answer after %.1f s. With no dialog, it comes in less than 1 s."
        % (clock() - asked))
    if stream.token:
        write_token(path, stream.token)
        out("The portal gave a restore token. It is kept for the next start.")
    else:
        out("The portal gave no restore token. Each start asks again.")
    out("Screen: node %d, %d x %d" % (stream.node, stream.width, stream.height))
    try:
        return await _measure(cast, stream, seconds, out, launch, proc, clock,
                              cpu)
    finally:
        os.close(stream.fd)


async def _measure(cast, stream, seconds, out, launch, proc, clock, cpu):
    compositor = find_process(COMPOSITORS, proc)
    out("Measuring %d s with no capture, %d s with it, and %d s with a limit "
        "of %d pictures each second. Show something that moves, for example "
        "a video." % (seconds, seconds, seconds, screen.RATE))
    before = cpu(compositor, proc) if compositor else None
    await asyncio.sleep(seconds)
    loads = [_load(compositor, before, seconds, cpu, proc)]
    failed = False
    for cap in (False, True):
        try:
            # Each reader needs its own connection to PipeWire.
            fd = stream.fd if not cap else await cast.remote()
        except PortalError as exc:
            out("No second reader from the portal: %s" % exc.detail)
            failed = True
            break
        try:
            frames, took, load, busy, problem = await _capture(
                stream.node, fd, cap, seconds, launch, proc, clock, cpu,
                compositor)
        finally:
            if cap:
                os.close(fd)
        loads.append(busy)
        out("Mirror pipeline%s: %.1f pictures each second, %s of one core"
            % (" with the limit" if cap else "",
               frames / took if took > 0 else 0.0, _per_cent(load)))
        if problem or not frames:
            out("gst-launch-1.0 stopped: %s" % (problem or "no picture"))
            failed = True
    if compositor is None:
        out("Compositor: not found")
    else:
        out("Compositor: %s of one core with no capture, %s with it, %s with "
            "the limit" % tuple(_per_cent(value) for value in
                                (loads + [None, None])[:3]))
    return 1 if failed else 0


async def _capture(node, fd, cap, seconds, launch, proc, clock, cpu,
                   compositor):
    """Reads the screen for `seconds`. Returns the counts and the loads."""
    loop = asyncio.get_running_loop()
    pipeline = screen.Pipeline(screen.command(str(node), fd=fd, cap=cap),
                               launch=launch, keep=(fd,))
    try:
        pipeline.start()
    except (OSError, ValueError) as exc:
        return 0, 0.0, None, None, str(exc)
    try:
        # The first pictures come after the start of the pipeline.
        await loop.run_in_executor(None, _count, pipeline, min(1.0, seconds),
                                   clock)
        started = clock()
        before = cpu(compositor, proc) if compositor else None
        own = cpu(pipeline.pid, proc)
        frames = await loop.run_in_executor(None, _count, pipeline, seconds,
                                            clock)
        took = clock() - started
        busy = _load(compositor, before, took, cpu, proc)
        load = _load(pipeline.pid, own, took, cpu, proc)
        problem = "" if pipeline.alive() else pipeline.error()
    finally:
        pipeline.stop()
    return frames, took, load, busy, problem


def _per_cent(value):
    return "unknown" if value is None else "%.1f %%" % value


def _cpu(pid, proc):
    if pid is None:
        return None
    return screen.cpu_seconds(pid, proc)


def probe(seconds=PROBE_SECONDS, out=print, load=load_dbus, connect=_connect,
          launch=subprocess.Popen, run=subprocess.run, proc="/proc",
          path=None, clock=time.monotonic, cpu=_cpu, environ=None):
    """Tries a share of the screen and a capture, and says what it found.

    Returns the exit code: 0 for a capture that gave pictures.
    """
    return asyncio.run(_probe(
        seconds, out, load(), connect, launch, run, proc,
        token_path() if path is None else path, clock, cpu,
        os.environ if environ is None else environ))

