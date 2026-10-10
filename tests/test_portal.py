# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The screen cast portal: the share of the desktop screen for the mirror.

This machine has no desktop and no portal. A fake bus takes the place of the
session bus and answers as xdg-desktop-portal does: a reply with the path of
the request, and then a Response signal on that path. The messages are real
messages of the carried dbus_next, so their signatures are checked.

A second test starts a real dbus-daemon with a fake portal service on it,
for the marshalling and the file descriptor. It needs dbus-daemon.
"""

import asyncio
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "server")
sys.path.insert(0, SERVER)

from steamos_utility_center import companion, portal, screen  # noqa: E402
from steamos_utility_center import service                     # noqa: E402

DBUS = portal.load_dbus()
SESSION = "/org/freedesktop/portal/desktop/session/1_7/s"


class FakePortal:
    """Answers the calls of ScreenCast as xdg-desktop-portal does."""

    def __init__(self, version=5, sources=portal.MONITOR | portal.WINDOW,
                 cursors=portal.CURSOR_HIDDEN | portal.CURSOR_EMBEDDED,
                 answers=None, token="new-token", streams=None, fd=True,
                 missing=()):
        self.version = version
        self.sources = sources
        self.cursors = cursors
        # The answer to each request, by its member: 0, 1, 2 or None for
        # no answer at all.
        self.answers = dict(answers or {})
        self.token = token
        self.streams = ([[42, {"size": DBUS.Variant("(ii)", [1920, 1080])}]]
                        if streams is None else streams)
        self.fd = fd
        self.missing = missing
        self.options = {}
        self.closed = []

    def answer(self, bus, message):
        """Returns the reply, and makes a later signal where one is due."""
        Message = DBUS.Message
        if message.interface == portal.DBUS:
            return Message.new_method_return(message)
        if message.interface == portal.PROPERTIES:
            name = message.body[1]
            if name in self.missing:
                return Message.new_error(
                    message, "org.freedesktop.DBus.Error.UnknownProperty",
                    "no property " + name)
            value = {"version": self.version,
                     "AvailableSourceTypes": self.sources,
                     "AvailableCursorModes": self.cursors}[name]
            return Message.new_method_return(message, "v",
                                             [DBUS.Variant("u", value)])
        if message.interface in (portal.SESSION, portal.REQUEST):
            self.closed.append((message.interface, message.path))
            return Message.new_method_return(message)
        member = message.member
        if member == "OpenPipeWireRemote":
            if not self.fd:
                return Message.new_method_return(message, "h", [0])
            read, write = os.pipe()
            os.close(write)
            return Message.new_method_return(message, "h", [0],
                                             unix_fds=[read])
        options = message.body[-1]
        self.options[member] = {key: value.value
                                for key, value in options.items()}
        path = portal.request_path(bus.unique_name,
                                   options["handle_token"].value)
        results = {}
        if member == "CreateSession":
            results = {"session_handle": DBUS.Variant("s", SESSION)}
        elif member == "Start":
            results = {"streams": DBUS.Variant("a(ua{sv})", self.streams)}
            if self.token:
                results["restore_token"] = DBUS.Variant("s", self.token)
        response = self.answers.get(member, 0)
        if response is not None:
            asyncio.get_running_loop().call_soon(
                bus.emit, path, portal.REQUEST, "Response", "ua{sv}",
                [response, results])
        return Message.new_method_return(message, "o", [path])


class FakeBus:
    """The session bus, as far as ScreenCast uses it."""

    unique_name = ":1.7"

    def __init__(self, fake):
        self.fake = fake
        self.handlers = []
        self.calls = []
        self.disconnected = False

    def add_message_handler(self, handler):
        self.handlers.append(handler)

    async def call(self, message):
        self.calls.append(message)
        # A reply names the serial of its call, as on a real bus.
        message.serial = len(self.calls)
        return self.fake.answer(self, message)

    def emit(self, path, interface, member, signature, body):
        signal = DBUS.Message.new_signal(path, interface, member, signature,
                                         body)
        for handler in list(self.handlers):
            handler(signal)

    def disconnect(self):
        self.disconnected = True

    def members(self):
        return [(message.interface, message.member, message.path)
                for message in self.calls]


def run(coroutine):
    return asyncio.run(coroutine)


class Opened:
    """A share through the fake portal, with its bus and its stream."""

    def __init__(self, fake=None, **options):
        self.fake = fake or FakePortal()
        self.bus = FakeBus(self.fake)
        self.cast = portal.ScreenCast(self.bus, DBUS)
        self.error = None
        self.stream = None
        try:
            self.stream = run(self.cast.open(**options))
        except portal.PortalError as exc:
            self.error = exc

    def close(self):
        if self.stream is not None:
            os.close(self.stream.fd)


@unittest.skipIf(DBUS is None, "the carried dbus_next is not there")
class ShareTest(unittest.TestCase):
    """open() asks for one screen, and gives its node and its reader."""

    def opened(self, fake=None, **options):
        share = Opened(fake, **options)
        self.addCleanup(share.close)
        return share

    def test_the_path_of_a_request_comes_from_the_unique_name(self):
        self.assertEqual(portal.request_path(":1.42", "abc"),
                         "/org/freedesktop/portal/desktop/request/1_42/abc")

    def test_one_screen_with_no_pointer_and_a_kept_approval(self):
        share = self.opened()
        self.assertIsNone(share.error)
        chosen = share.fake.options["SelectSources"]
        self.assertEqual(chosen["types"], portal.MONITOR)
        self.assertIs(chosen["multiple"], False)
        self.assertEqual(chosen["cursor_mode"], portal.CURSOR_HIDDEN)
        self.assertEqual(chosen["persist_mode"], portal.PERSIST)
        self.assertNotIn("restore_token", chosen)
        stream = share.stream
        self.assertEqual((stream.node, stream.width, stream.height),
                         (42, 1920, 1080))
        self.assertEqual(stream.token, "new-token")
        self.assertTrue(stat.S_ISFIFO(os.fstat(stream.fd).st_mode))
        self.assertEqual(share.cast.session, SESSION)

    def test_a_kept_token_goes_back_to_the_portal(self):
        share = self.opened(token="old-token")
        self.assertEqual(share.fake.options["SelectSources"]["restore_token"],
                         "old-token")

    def test_a_portal_before_version_4_keeps_nothing(self):
        share = self.opened(token="old-token", version=3)
        chosen = share.fake.options["SelectSources"]
        self.assertNotIn("persist_mode", chosen)
        self.assertNotIn("restore_token", chosen)

    def test_a_portal_with_no_hidden_pointer_gets_no_cursor_mode(self):
        share = self.opened(cursors=portal.CURSOR_EMBEDDED)
        self.assertNotIn("cursor_mode", share.fake.options["SelectSources"])

    def test_each_request_watches_its_path_before_the_call(self):
        share = self.opened()
        calls = share.bus.members()
        for member in ("CreateSession", "SelectSources", "Start"):
            place = [i for i, call in enumerate(calls) if call[1] == member][0]
            path = portal.request_path(
                FakeBus.unique_name,
                share.fake.options[member]["handle_token"])
            watch = calls[place - 1]
            self.assertEqual(watch[:2], (portal.DBUS, "AddMatch"))
            rule = share.bus.calls[place - 1].body[0]
            self.assertIn("path='%s'" % path, rule)
            self.assertIn("member='Response'", rule)

    def test_the_tokens_of_the_requests_are_not_the_same(self):
        share = self.opened()
        tokens = [share.fake.options[member]["handle_token"]
                  for member in ("CreateSession", "SelectSources", "Start")]
        tokens.append(share.fake.options["CreateSession"]
                      ["session_handle_token"])
        self.assertEqual(len(set(tokens)), 4)

    def test_a_cancelled_dialog_is_a_refusal(self):
        share = self.opened(FakePortal(answers={"Start": 1}))
        self.assertEqual(share.error.state, portal.REFUSED)
        self.assertIsNone(share.stream)

    def test_a_different_end_of_a_request_is_a_failure(self):
        share = self.opened(FakePortal(answers={"SelectSources": 2}))
        self.assertEqual(share.error.state, portal.FAILED)
        self.assertNotIn("Start", share.fake.options)

    def test_a_dialog_with_no_answer_ends_and_goes_from_the_screen(self):
        share = self.opened(FakePortal(answers={"Start": None}),
                            dialog_seconds=0.05)
        self.assertEqual(share.error.state, portal.FAILED)
        request = portal.request_path(
            FakeBus.unique_name, share.fake.options["Start"]["handle_token"])
        self.assertIn((portal.REQUEST, request), share.fake.closed)

    def test_no_stream_in_the_answer_is_a_failure(self):
        share = self.opened(FakePortal(streams=[]))
        self.assertEqual(share.error.state, portal.FAILED)

    def test_no_file_descriptor_is_a_failure(self):
        share = self.opened(FakePortal(fd=False))
        self.assertEqual(share.error.state, portal.FAILED)
        self.assertIn("file descriptor", share.error.detail)

    def test_no_restore_token_is_no_token(self):
        share = self.opened(FakePortal(token=None))
        self.assertIsNone(share.error)
        self.assertIsNone(share.stream.token)

    def test_close_ends_the_session_one_time(self):
        share = self.opened()
        run(share.cast.close())
        run(share.cast.close())
        self.assertEqual(share.fake.closed, [(portal.SESSION, SESSION)])

    def test_a_session_that_the_portal_closed_is_not_closed_again(self):
        share = self.opened()
        share.bus.emit(SESSION, portal.SESSION, "Closed", "a{sv}", [{}])
        self.assertTrue(share.cast.closed)
        run(share.cast.close())
        self.assertEqual(share.fake.closed, [])

    def test_a_closed_signal_of_a_different_session_changes_nothing(self):
        share = self.opened()
        share.bus.emit(SESSION + "x", portal.SESSION, "Closed", "a{sv}", [{}])
        self.assertFalse(share.cast.closed)


@unittest.skipIf(DBUS is None, "the carried dbus_next is not there")
class FactsTest(unittest.TestCase):

    def facts(self, fake):
        return run(portal.ScreenCast(FakeBus(fake), DBUS).facts())

    def test_the_version_the_sources_and_the_pointer(self):
        self.assertEqual(self.facts(FakePortal()),
                         (5, portal.MONITOR | portal.WINDOW,
                          portal.CURSOR_HIDDEN | portal.CURSOR_EMBEDDED))

    def test_version_1_has_no_cursor_modes(self):
        self.assertEqual(self.facts(FakePortal(
            version=1, missing=("AvailableCursorModes",)))[2], 0)

    def test_no_screen_cast_is_no_portal(self):
        with self.assertRaises(portal.PortalError) as caught:
            self.facts(FakePortal(missing=("version",)))
        self.assertEqual(caught.exception.state, portal.NO_PORTAL)

    def test_the_names_of_the_bits(self):
        self.assertEqual(portal.bits(portal.MONITOR | portal.VIRTUAL,
                                     portal.SOURCE_NAMES), "monitor, virtual")
        self.assertEqual(portal.bits(0, portal.CURSOR_NAMES), "none")


class TokenTest(unittest.TestCase):
    """The restore token: kept for the next session, read by the user only."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.path = portal.token_path(self.home)

    def test_it_is_beside_the_token_of_the_panel(self):
        self.assertEqual(portal.TOKEN_DIR, companion.TOKEN_DIR)
        self.assertEqual(os.path.dirname(self.path),
                         os.path.dirname(companion.token_path(self.home)))

    def test_only_the_user_can_read_it(self):
        portal.write_token(self.path, "abc")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.path))
                                      .st_mode), 0o700)
        self.assertEqual(portal.read_token(self.path), "abc")

    def test_an_old_file_that_others_can_read_gets_the_mode_too(self):
        # The file of the token, and a part of a write that stopped.
        os.makedirs(os.path.dirname(self.path))
        for old in (self.path, self.path + ".new"):
            with open(old, "w") as handle:
                handle.write("old\n")
            os.chmod(old, 0o644)
        portal.write_token(self.path, "new")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(portal.read_token(self.path), "new")
        self.assertFalse(os.path.exists(self.path + ".new"))

    def test_no_file_or_an_empty_file_is_no_token(self):
        self.assertIsNone(portal.read_token(self.path))
        portal.write_token(self.path, "")
        self.assertIsNone(portal.read_token(self.path))
        portal.forget_token(self.path)
        self.assertFalse(os.path.exists(self.path))
        portal.forget_token(self.path)


class PipelineTest(unittest.TestCase):
    """The pipeline reads the node of the portal through its fd."""

    def test_the_fd_and_the_id_of_the_node(self):
        argv = screen.command("77", fd=5)
        self.assertEqual(argv[2:5], ["pipewiresrc", "fd=5", "path=77"])
        self.assertNotIn("target-object=77", argv)
        self.assertEqual(screen.command("gamescope")[3],
                         "target-object=gamescope")

    def test_the_child_gets_the_fd_and_only_with_one(self):
        seen = []

        def launch(argv, **options):
            seen.append(options)
            raise OSError("no start")

        for keep in ((), (9,)):
            pipeline = screen.Pipeline(["x"], launch=launch, keep=keep)
            with self.assertRaises(OSError):
                pipeline.start()
        self.assertNotIn("pass_fds", seen[0])
        self.assertEqual(seen[1]["pass_fds"], (9,))


class LoadTest(unittest.TestCase):

    def test_the_copy_in_the_source_is_found(self):
        self.assertTrue(os.path.isdir(os.path.join(portal.SOURCE_COPY,
                                                   "dbus_next")))

    def test_no_copy_is_none(self):
        code = ("import sys; sys.path.insert(0, %r); "
                "from steamos_utility_center import portal; "
                "print(portal.load_dbus(places=()))" % SERVER)
        said = subprocess.run([sys.executable, "-I", "-c", code],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(said.stdout.strip(), "None", said.stderr)


class ServiceTest(unittest.TestCase):

    def test_the_option_starts_the_probe(self):
        with unittest.mock.patch.object(portal, "probe",
                                        return_value=3) as probe:
            self.assertEqual(service.main(["--screen-probe"]), 3)
        probe.assert_called_once_with()


# A child that takes the place of gst-launch-1.0: it checks that it got the
# fd of the portal, and then writes pictures.
CHILD = textwrap.dedent("""
    import os, sys, time
    os.fstat(int(sys.argv[1]))
    frame = bytes(%d)
    while True:
        os.write(1, frame)
        time.sleep(0.02)
""" % screen.FRAME)


@unittest.skipIf(DBUS is None, "the carried dbus_next is not there")
class ProbeTest(unittest.TestCase):
    """What the probe says, with a fake portal and a fake pipeline."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.path = portal.token_path(self.home)
        self.said = []
        self.argv = []

    def launch(self, argv, **options):
        self.argv.append(argv)
        fd = argv[3].split("=")[1]
        return subprocess.Popen([sys.executable, "-c", CHILD, fd], **options)

    def probe(self, fake=None, dbus=DBUS, connect=None):
        self.fake = fake or FakePortal()
        self.bus = FakeBus(self.fake)

        async def connected(_dbus):
            return self.bus

        def gst(argv, **options):
            return subprocess.CompletedProcess(argv, 0, "gst-launch-1.0 "
                                               "version 1.24.9\n", "")

        return portal.probe(
            seconds=0.3, out=self.said.append, load=lambda: dbus,
            connect=connect or connected, launch=self.launch, run=gst,
            proc=self.home, path=self.path,
            environ={"XDG_SESSION_TYPE": "wayland"})

    def text(self):
        return "\n".join(self.said)

    def test_a_capture_that_gives_pictures(self):
        self.assertEqual(self.probe(), 0)
        text = self.text()
        self.assertIn("Session type: wayland", text)
        self.assertIn("GStreamer: gst-launch-1.0 version 1.24.9", text)
        self.assertIn("version 5, sources: monitor, window", text)
        self.assertIn("A kept approval: no", text)
        self.assertIn("Screen: node 42, 1920 x 1080", text)
        self.assertIn("It is kept for the next start", text)
        self.assertIn("Compositor: not found", text)
        self.assertRegex(text, r"Mirror pipeline: [1-9][0-9.]* pictures")
        self.assertEqual(portal.read_token(self.path), "new-token")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertNotIn("new-token", text)
        self.assertEqual(self.argv[0][2:5], ["pipewiresrc", self.argv[0][3],
                                             "path=42"])
        self.assertIn((portal.SESSION, SESSION), self.fake.closed)
        self.assertTrue(self.bus.disconnected)

    def test_a_second_start_gives_the_kept_token(self):
        portal.write_token(self.path, "old-token")
        self.assertEqual(self.probe(), 0)
        self.assertIn("A kept approval: yes", self.text())
        self.assertEqual(self.fake.options["SelectSources"]["restore_token"],
                         "old-token")
        self.assertNotIn("old-token", self.text())

    def test_a_refusal(self):
        self.assertEqual(self.probe(FakePortal(answers={"Start": 1})), 1)
        self.assertIn("refused", self.text())
        self.assertEqual(self.argv, [])

    def test_no_portal(self):
        self.assertEqual(self.probe(FakePortal(missing=("version",))), 1)
        self.assertIn("No screen cast portal", self.text())

    def test_a_portal_with_no_screens(self):
        self.assertEqual(self.probe(FakePortal(sources=portal.WINDOW)), 1)
        self.assertIn("cannot share a screen", self.text())

    def test_no_session_bus(self):
        async def broken(_dbus):
            raise OSError("no socket")
        self.assertEqual(self.probe(connect=broken), 1)
        self.assertIn("No session bus: no socket", self.text())

    def test_no_dbus_next(self):
        self.assertEqual(self.probe(dbus=None), 1)
        self.assertIn("dbus_next is not there", self.text())

    def test_the_load_of_the_compositor(self):
        os.makedirs(os.path.join(self.home, "123"))
        with open(os.path.join(self.home, "123", "comm"), "w") as handle:
            handle.write("kwin_wayland\n")
        self.assertEqual(portal.find_process(portal.COMPOSITORS, self.home),
                         123)
        self.assertIsNone(portal.find_process(("other",), self.home))


def _dbus_daemon():
    return shutil.which("dbus-daemon")


# A fake portal service on a real bus. It shares the end of a socket pair,
# so the test sees the fd come through the bus.
SERVICE = textwrap.dedent("""
    import asyncio, os, socket, sys
    sys.path.insert(0, sys.argv[1])
    from steamos_utility_center import portal
    dbus = portal.load_dbus()
    from dbus_next.service import ServiceInterface, method, dbus_property
    from dbus_next.constants import PropertyAccess
    from dbus_next import Message, Variant

    class Cast(ServiceInterface):
        def __init__(self, bus):
            super().__init__(portal.SCREEN_CAST)
            self.bus = bus
            self.ends = []

        def answer(self, sender, options, results):
            path = portal.request_path(sender, options["handle_token"].value)
            message = Message.new_signal(path, portal.REQUEST, "Response",
                                         "ua{sv}", [0, results])
            message.destination = sender
            asyncio.get_running_loop().call_later(
                0.05, self.bus.send, message)
            return path

        @dbus_property(access=PropertyAccess.READ)
        def version(self) -> "u":
            return 5

        @dbus_property(access=PropertyAccess.READ)
        def AvailableSourceTypes(self) -> "u":
            return 1

        @dbus_property(access=PropertyAccess.READ)
        def AvailableCursorModes(self) -> "u":
            return 1

        @method()
        def CreateSession(self, options: "a{sv}") -> "o":
            return self.answer(self.sender, options, {
                "session_handle": Variant("s", "/s/1")})

        @method()
        def SelectSources(self, session: "o", options: "a{sv}") -> "o":
            return self.answer(self.sender, options, {})

        @method()
        def Start(self, session: "o", parent: "s", options: "a{sv}") -> "o":
            return self.answer(self.sender, options, {
                "streams": Variant("a(ua{sv})",
                                   [[7, {"size": Variant("(ii)", [640, 480])}]]),
                "restore_token": Variant("s", "t1")})

        @method()
        def OpenPipeWireRemote(self, session: "o", options: "a{sv}") -> "h":
            mine, theirs = socket.socketpair()
            self.ends.append(mine)
            mine.sendall(b"hello")
            return theirs.detach()

    async def main():
        bus = await dbus.aio.MessageBus(negotiate_unix_fd=True).connect()
        cast = Cast(bus)

        def remember(message):
            cast.sender = message.sender
            return False

        bus.add_message_handler(remember)
        bus.export(portal.OBJECT, cast)
        await bus.request_name(portal.BUS_NAME)
        print("ready", flush=True)
        await asyncio.Future()

    asyncio.run(main())
""")


@unittest.skipIf(DBUS is None or _dbus_daemon() is None,
                 "needs dbus-daemon and the carried dbus_next")
class RealBusTest(unittest.TestCase):
    """The same share through a real dbus-daemon and a fake portal."""

    def setUp(self):
        self.place = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.place)
        address = "unix:path=" + os.path.join(self.place, "bus")
        self.daemon = subprocess.Popen(
            [_dbus_daemon(), "--session", "--nofork", "--address=" + address],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop, self.daemon)
        for _wait in range(100):
            if os.path.exists(os.path.join(self.place, "bus")):
                break
            time.sleep(0.05)
        environ = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address)
        self.service = subprocess.Popen(
            [sys.executable, "-c", SERVICE, SERVER], env=environ,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop, self.service)
        self.assertEqual(self.service.stdout.readline().strip(), "ready",
                         self.service.stderr.read() if self.service.poll()
                         is not None else "")
        self.address = address

    @staticmethod
    def stop(process):
        process.kill()
        process.wait()
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()

    def test_the_share_and_its_file_descriptor(self):
        async def share():
            bus = await DBUS.aio.MessageBus(bus_address=self.address,
                                            negotiate_unix_fd=True).connect()
            try:
                cast = portal.ScreenCast(bus, DBUS)
                facts = await cast.facts()
                stream = await cast.open(version=facts[0], cursors=facts[2],
                                         dialog_seconds=10)
                return facts, stream
            finally:
                bus.disconnect()

        facts, stream = run(share())
        self.addCleanup(os.close, stream.fd)
        self.assertEqual(facts, (5, 1, 1))
        self.assertEqual((stream.node, stream.width, stream.height, stream.token),
                         (7, 640, 480, "t1"))
        reader = socket.socket(fileno=os.dup(stream.fd))
        self.addCleanup(reader.close)
        reader.settimeout(5)
        self.assertEqual(reader.recv(5), b"hello")


if __name__ == "__main__":
    unittest.main()
