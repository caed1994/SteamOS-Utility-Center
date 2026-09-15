# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The program that hears a sleep begin, and the bytes it reads to hear it.

Two shapes lost the race to NetworkManager before this one, and the reason
was never the code inside them. A unit at Before=sleep.target runs after the
whole delay phase. A hook at the pre-down of NetworkManager starts a
dispatcher service, a runuser with a PAM session and a Python, which is
hundreds of milliseconds against the twenty-eight that the interface has
left. So this one is a program that already runs.

That leaves the protocol as the part that is easy to get wrong and silent
when it is. D-Bus aligns each value to its own width from the start of the
message, and a padding that is off by one byte desynchronises every message
after the first. Nothing reports it: the reader simply never sees a sleep
again.

The byte vectors below came out of jeepney, which is another implementation
of D-Bus and not this one. They are frozen here so that the suite needs no
such package on the machine that runs it.
"""

import os
import socket
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))

from steamos_utility_center import sleepwatch  # noqa: E402


class VectorTest(unittest.TestCase):
    """Messages that another implementation of D-Bus produced."""

    # PrepareForSleep(true) and PrepareForSleep(false) from logind, and one
    # message that is none of this program's business.
    ASLEEP = bytes.fromhex(
        "6c04010104000000070000007700000001016f00170000002f6f7267"
        "2f667265656465736b746f702f6c6f67696e3100020173001e000000"
        "6f72672e667265656465736b746f702e6c6f67696e312e4d616e6167"
        "65720000030173000f00000050726570617265466f72536c65657000"
        "07017300040000003a312e3200000000080167000162000001000000"
    )
    AWAKE = bytes.fromhex(
        "6c04010104000000070000007700000001016f00170000002f6f7267"
        "2f667265656465736b746f702f6c6f67696e3100020173001e000000"
        "6f72672e667265656465736b746f702e6c6f67696e312e4d616e6167"
        "65720000030173000f00000050726570617265466f72536c65657000"
        "07017300040000003a312e3200000000080167000162000000000000"
    )
    # A method call that names the signal in its header. Only the type of the
    # message tells it apart, and nothing else here does.
    CALLED = bytes.fromhex(
        "6c010001040000000b0000007700000001016f00170000002f6f7267"
        "2f667265656465736b746f702f6c6f67696e3100020173001e000000"
        "6f72672e667265656465736b746f702e6c6f67696e312e4d616e6167"
        "65720000030173000f00000050726570617265466f72536c65657000"
        "06017300040000003a312e3900000000080167000162000001000000"
    )
    OTHER = bytes.fromhex(
        "6c01000100000000090000006d00000001016f00150000002f6f7267"
        "2f667265656465736b746f702f444275730000000201730014000000"
        "6f72672e667265656465736b746f702e444275730000000003017300"
        "0500000048656c6c6f00000006017300140000006f72672e66726565"
        "6465736b746f702e4442757300000000"
    )

    def _read(self, *messages):
        """What the reader makes of these bytes, in order.

        The socket has a limit, because a reader that lost its place waits
        for bytes that nobody sends. Without the limit a padding that is
        wrong hangs this test rather than failing it, and a test that hangs
        says less than one that fails.
        """
        here, there = socket.socketpair()
        there.settimeout(5)
        try:
            here.sendall(b"".join(messages))
            return [sleepwatch.asleep(*sleepwatch.next_message(there))
                    for _ in messages]
        finally:
            here.close()
            there.close()

    def test_the_announcement_of_a_sleep_is_read(self):
        self.assertEqual(self._read(self.ASLEEP), [True])

    def test_the_word_that_the_machine_is_awake_again_is_read(self):
        self.assertEqual(self._read(self.AWAKE), [False])

    def test_another_message_is_not_a_sleep(self):
        """A method call carries no state, and the loop steps over it."""
        self.assertEqual(self._read(self.OTHER), [None])

    def test_only_a_signal_counts_as_an_announcement(self):
        """A message that names PrepareForSleep and is not a signal.

        The bus sends this connection its two answers and the broadcasts it
        asked for, so this is a guard and not a daily event. The test for
        OTHER above passes with the guard gone, because that message never
        names the signal at all.
        """
        self.assertEqual(self._read(self.CALLED), [None])

    def test_messages_that_arrive_together_are_read_apart(self):
        """The padding after the header is the part that is easy to lose.

        One byte too few or too many leaves the reader in the middle of the
        next message, and it never reads a sleep again. A single message
        cannot show that, because there is nothing after it.
        """
        self.assertEqual(
            self._read(self.ASLEEP, self.AWAKE, self.OTHER, self.ASLEEP),
            [True, False, None, True])


class MarshalTest(unittest.TestCase):
    """The two calls this program makes, read back by a separate walk.

    The walk below follows the specification rather than the code above, so
    an alignment that is wrong in one of them shows here.
    """

    @staticmethod
    def _walk(raw):
        """The header fields of a message, as {code: value}."""
        order = "<" if raw[:1] == b"l" else ">"
        end, = struct.unpack_from(order + "I", raw, 12)
        at = 16
        stop = 16 + end
        out = {}
        while at < stop:
            at += (-at) % 8
            code = raw[at]
            size = raw[at + 1]
            kind = raw[at + 2:at + 2 + size].decode()
            at += 2 + size + 1
            if kind == "g":
                length = raw[at]
                out[code] = raw[at + 1:at + 1 + length].decode()
                at += 1 + length + 1
            else:
                at += (-at) % 4
                length, = struct.unpack_from(order + "I", raw, at)
                out[code] = raw[at + 4:at + 4 + length].decode()
                at += 4 + length + 1
        return out

    @staticmethod
    def _body(raw):
        """The body of a message that carries one string."""
        order = "<" if raw[:1] == b"l" else ">"
        size, = struct.unpack_from(order + "I", raw, 4)
        end, = struct.unpack_from(order + "I", raw, 12)
        at = 16 + end
        at += (-at) % 8
        length, = struct.unpack_from(order + "I", raw, at)
        return raw[at + 4:at + 4 + length].decode()

    def test_the_first_call_says_hello_to_the_bus(self):
        """Every connection begins with it, and the bus answers nothing
        else until it arrives."""
        said = self._walk(sleepwatch.call("Hello"))
        self.assertEqual(said[1], "/org/freedesktop/DBus")
        self.assertEqual(said[2], "org.freedesktop.DBus")
        self.assertEqual(said[3], "Hello")
        self.assertEqual(said[6], "org.freedesktop.DBus")

    def test_the_second_call_asks_for_the_one_signal(self):
        """Without a match rule the bus sends no broadcast at all, and this
        program waits for a sleep that never reaches it."""
        raw = sleepwatch.call("AddMatch", [(8, "g", "s")],
                              sleepwatch._string(sleepwatch.RULE), 2)
        said = self._walk(raw)
        self.assertEqual(said[3], "AddMatch")
        self.assertEqual(said[8], "s")
        self.assertEqual(self._body(raw), sleepwatch.RULE)

    def test_the_rule_names_the_signal_of_logind(self):
        self.assertIn("org.freedesktop.login1.Manager", sleepwatch.RULE)
        self.assertIn("PrepareForSleep", sleepwatch.RULE)
        self.assertIn("type='signal'", sleepwatch.RULE)

    def test_the_body_begins_on_a_boundary_of_eight(self):
        """The header is padded to eight and the body is not padded at all.

        So a message ends where its body ends, and the next one begins
        there. The first version of this test asked for the whole message to
        be a multiple of eight, which is false and which the reader above
        already disproves: it takes four messages out of one buffer.
        """
        for raw in (sleepwatch.call("Hello"),
                    sleepwatch.call("AddMatch", [(8, "g", "s")],
                                    sleepwatch._string(sleepwatch.RULE), 2)):
            order = "<" if raw[:1] == b"l" else ">"
            size, = struct.unpack_from(order + "I", raw, 4)
            end, = struct.unpack_from(order + "I", raw, 12)
            body_at = 16 + end
            body_at += (-body_at) % 8
            self.assertEqual(body_at % 8, 0)
            self.assertEqual(len(raw), body_at + size)


class HoldTest(unittest.TestCase):
    """The delay lock, which is what makes the suspend wait for the call."""

    class Child(object):
        def __init__(self, alive=True):
            self.alive = alive
            self.stdin = None
            self.killed = False

        def poll(self):
            return None if self.alive else 1

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True

    def _run(self, alive=True):
        said = {}

        def run(command, **rest):
            said["command"] = command
            return self.Child(alive)

        return run, said

    def test_it_asks_logind_to_delay_and_not_to_block(self):
        """A block lock stops the sleep. A delay lock holds it for a moment
        and then lets it go, which is the whole of what this needs."""
        run, said = self._run()
        sleepwatch.hold(run=run, rest=lambda seconds: None)
        self.assertIn("--what=sleep", said["command"])
        self.assertIn("--mode=delay", said["command"])
        self.assertEqual(said["command"][0], sleepwatch.INHIBIT)

    def test_a_refused_lock_is_an_error_and_not_a_quiet_start(self):
        """Without the lock the machine sleeps while the message is in
        flight, and the lamps stay lit with nothing in the journal."""
        run, _said = self._run(alive=False)
        with self.assertRaises(sleepwatch.BusError):
            sleepwatch.hold(run=run, rest=lambda seconds: None)

    def test_the_lock_ends_with_the_process_that_holds_it(self):
        child = self.Child()

        class Pipe(object):
            closed = False

            def close(self):
                Pipe.closed = True

        child.stdin = Pipe()
        sleepwatch.release(child)
        self.assertTrue(Pipe.closed)


class WatchTest(unittest.TestCase):
    """The loop: what it does at each of the two words it hears."""

    def setUp(self):
        self.done = []
        self.locks = []

    def _lock(self):
        self.locks.append("held")
        return None

    def _loop(self, *messages):
        """Run the loop over these messages and report what happened."""
        here, there = socket.socketpair()
        self.addCleanup(here.close)
        self.addCleanup(there.close)
        here.sendall(b"".join(messages))
        here.close()
        said = []

        def darken(home=None, now=None):
            said.append("off")
            return {"done": ["a lamp"], "trouble": []}

        kept = sleepwatch.darken
        sleepwatch.darken = darken
        try:
            sleepwatch.watch(there, hold_one=self._lock)
        except sleepwatch.BusError:
            pass
        finally:
            sleepwatch.darken = kept
        return said

    def test_it_turns_them_off_when_the_sleep_is_announced(self):
        self.assertEqual(self._loop(VectorTest.ASLEEP), ["off"])

    def test_it_does_nothing_of_its_own_at_the_wake(self):
        """The resume unit lights them again. That unit works, and a second
        program for one moment is a second thing to be wrong."""
        self.assertEqual(self._loop(VectorTest.AWAKE), [])

    def test_it_takes_the_lock_again_after_a_sleep(self):
        """The lock ends with the call, so the sleep after this one needs a
        new one. Without it the second suspend is not waited for."""
        self._loop(VectorTest.ASLEEP, VectorTest.AWAKE)
        self.assertEqual(len(self.locks), 2)

    def test_a_message_that_is_not_a_sleep_changes_nothing(self):
        self.assertEqual(self._loop(VectorTest.OTHER), [])
        self.assertEqual(len(self.locks), 1)


class ReportTest(unittest.TestCase):
    """What the journal holds, which is how the margin is checked."""

    def test_the_time_of_the_call_is_reported(self):
        """Twenty-eight milliseconds is the whole argument for this program,
        so the cost of each call is measured and not asserted."""
        clock = [0.0, 0.012]

        def now():
            return clock.pop(0)

        kept = sleepwatch.nanoleaf.follow
        sleepwatch.nanoleaf.follow = lambda state, home, timeout=None: {
            "done": ["Lines A5F4"], "trouble": []}
        try:
            import io
            import contextlib
            said = io.StringIO()
            with contextlib.redirect_stdout(said):
                sleepwatch.darken(now=now)
        finally:
            sleepwatch.nanoleaf.follow = kept
        self.assertIn("12 ms", said.getvalue())
        self.assertIn("Lines A5F4", said.getvalue())

    def test_the_way_into_a_suspend_does_not_wait_for_an_answer(self):
        """The answer cannot arrive: the interface goes away first.

        The first version used the ordinary limit of the module and held
        every suspend for its whole 2.5 seconds, for a reply that had nothing
        to come back over. The lamp went off at that suspend all the same.
        """
        said = {}

        def follow(state, home=None, timeout=None):
            said["timeout"] = timeout
            return {"done": [], "trouble": []}

        kept = sleepwatch.nanoleaf.follow
        sleepwatch.nanoleaf.follow = follow
        try:
            sleepwatch.darken()
        finally:
            sleepwatch.nanoleaf.follow = kept
        self.assertEqual(said["timeout"], sleepwatch.SLEEP_TIMEOUT)
        self.assertLess(sleepwatch.SLEEP_TIMEOUT, sleepwatch.nanoleaf.TIMEOUT)

    def test_a_device_that_gives_no_answer_is_not_called_a_fault(self):
        """It is the ordinary case here, and a line that reads as a failure
        sends the next reader of this journal after the wrong thing."""
        import contextlib
        import io as pipes

        kept = sleepwatch.nanoleaf.follow
        sleepwatch.nanoleaf.follow = lambda state, home=None, timeout=None: {
            "done": [], "trouble": ["Lines A5F4: 1.2.3.4 did not answer"]}
        try:
            said = pipes.StringIO()
            with contextlib.redirect_stdout(said):
                sleepwatch.darken()
        finally:
            sleepwatch.nanoleaf.follow = kept
        self.assertIn("sent in", said.getvalue())
        self.assertIn("no answer before the network went", said.getvalue())


if __name__ == "__main__":
    unittest.main()
