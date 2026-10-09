# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pairing of a panel: the key exchange, the code and the one request.

The vectors of RFC 7748 hold the arithmetic. The rest holds the rules: one
request at a time, a code on both ends, an answer of the person through a
file, and a secret that leaves the service one time.
"""

import json
import os
import shutil
import socket
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))

from steamos_utility_center import pairing  # noqa: E402

# RFC 7748, section 6.1.
ALICE = bytes.fromhex(
    "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
ALICE_PUBLIC = bytes.fromhex(
    "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a")
BOB = bytes.fromhex(
    "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
BOB_PUBLIC = bytes.fromhex(
    "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f")
SHARED = bytes.fromhex(
    "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742")
# Points of a small order: each scalar of X25519 gives zero with them.
SMALL_ORDER = [bytes(32), (1).to_bytes(32, "little"),
               bytes.fromhex("e0eb7a7c3b41b8ae1656e3faf19fc46ada098deb9c32b1fd"
                             "866205165f49b800"),
               bytes.fromhex("5f9c95bca3508c24b1d0b1559c83ef5b04445cc4581c8e86"
                             "d8224eddd09f1157")]


class X25519Test(unittest.TestCase):

    def test_the_vectors_of_the_rfc(self):
        self.assertEqual(pairing.public_key(ALICE), ALICE_PUBLIC)
        self.assertEqual(pairing.public_key(BOB), BOB_PUBLIC)
        self.assertEqual(pairing.shared_secret(ALICE, BOB_PUBLIC), SHARED)
        self.assertEqual(pairing.shared_secret(BOB, ALICE_PUBLIC), SHARED)

    def test_the_first_vector_of_section_5_2(self):
        scalar = bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a"
                               "18506a2244ba449ac4")
        point = bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b"
                              "10a903a6d0ab1c4c")
        self.assertEqual(pairing.x25519(scalar, point).hex(),
                         "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4"
                         "075577a28552")

    def test_the_top_bit_of_the_point_is_ignored(self):
        """The second vector of section 5.2. The last byte of its point is
        0x93, so a calculation that keeps the top bit gives another value."""
        scalar = bytes.fromhex("4b66e9d4d1b4673c5ad22691957d6af5c11b6421e0ea01"
                               "d42ca4169e7918ba0d")
        point = bytes.fromhex("e5210f12786811d3f4b7959d0538ae2c31dbe7106fc03c3e"
                              "fc4cd549c715a493")
        self.assertEqual(pairing.x25519(scalar, point).hex(),
                         "95cbde9476e8907d7aade45cb4b873f88b595a68799fa152e6f8"
                         "f7647aac7957")

    def test_a_key_of_small_order_is_refused(self):
        for point in SMALL_ORDER:
            with self.assertRaises(ValueError, msg=point.hex()):
                pairing.shared_secret(ALICE, point)

    def test_a_value_of_a_wrong_size_is_refused(self):
        with self.assertRaises(ValueError):
            pairing.x25519(ALICE[:31], BOB_PUBLIC)


class DeriveTest(unittest.TestCase):

    def test_the_two_ends_get_the_same_values(self):
        one = pairing.derive(pairing.shared_secret(ALICE, BOB_PUBLIC),
                             ALICE_PUBLIC, BOB_PUBLIC)
        two = pairing.derive(pairing.shared_secret(BOB, ALICE_PUBLIC),
                             ALICE_PUBLIC, BOB_PUBLIC)
        self.assertEqual(one, two)

    def test_the_values_the_firmware_must_also_give(self):
        """tests/test_panel_pair.py holds the C side to these two values."""
        secret, code = pairing.derive(SHARED, ALICE_PUBLIC, BOB_PUBLIC)
        self.assertRegex(secret, r"^[0-9a-f]{64}$")
        self.assertRegex(code, r"^\d{6}$")
        self.assertEqual((secret, code), KNOWN)

    def test_the_order_of_the_keys_counts(self):
        self.assertNotEqual(pairing.derive(SHARED, ALICE_PUBLIC, BOB_PUBLIC),
                            pairing.derive(SHARED, BOB_PUBLIC, ALICE_PUBLIC))

    def test_the_code_tells_nothing_of_the_secret(self):
        secret, code = pairing.derive(SHARED, ALICE_PUBLIC, BOB_PUBLIC)
        self.assertNotIn(code, secret)


# The two values for the shared secret and the keys of RFC 7748. Written out,
# so that a change of the calculation on one end fails here and in the test
# of the firmware.
KNOWN = ("8bd2419b37c0adb999136e1483f6d15d9f8fb394639741bc0defac985acbfc62",
         "264341")


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class PairingCase(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.clock = Clock()
        self.pairing = pairing.Pairing(folder=self.folder, wall=self.clock,
                                       random=lambda size: BOB, name="deck")

    def ask(self, private=ALICE, name="SteamOS-Panel-A1B2"):
        return self.pairing.ask({"name": name,
                                 "key": pairing.public_key(private).hex()},
                                "192.168.1.50")


class PairingTest(PairingCase):

    def test_a_request_gives_the_key_of_the_pc_and_waits(self):
        code, said = self.ask()
        self.assertEqual(code, 200)
        self.assertEqual(said["key"], BOB_PUBLIC.hex())
        self.assertEqual(said["name"], "deck")
        self.assertRegex(said["id"], r"^[0-9a-f]{16}$")
        found = pairing.waiting(self.folder, wall=self.clock)
        self.assertEqual(found["id"], said["id"])
        self.assertEqual(found["code"], KNOWN[1])
        self.assertEqual(found["name"], "SteamOS-Panel-A1B2")
        self.assertEqual(found["address"], "192.168.1.50")

    def test_the_file_of_the_request_holds_no_secret(self):
        self.ask()
        path = os.path.join(self.folder, pairing.REQUEST_NAME)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn(KNOWN[0], text)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_the_panel_gets_the_secret_one_time_after_an_accept(self):
        _, said = self.ask()
        self.assertEqual(self.pairing.check(said["id"]),
                         (200, {"state": "waiting"}, None))
        pairing.answer(said["id"], True, folder=self.folder)
        self.assertEqual(self.pairing.check(said["id"]),
                         (200, {"state": "accepted"}, KNOWN[0]))
        # An answer that the panel did not get: it asks again.
        self.assertEqual(self.pairing.check(said["id"]),
                         (200, {"state": "accepted"}, None))
        self.assertIsNone(pairing.waiting(self.folder, wall=self.clock))

    def test_a_refusal_gives_no_secret(self):
        _, said = self.ask()
        pairing.answer(said["id"], False, folder=self.folder)
        self.assertEqual(self.pairing.check(said["id"]),
                         (200, {"state": "refused"}, None))

    def test_an_answer_for_a_different_request_changes_nothing(self):
        _, said = self.ask()
        pairing.answer("0" * 16, True, folder=self.folder)
        self.assertEqual(self.pairing.check(said["id"])[1],
                         {"state": "waiting"})

    def test_one_request_at_a_time(self):
        _, said = self.ask()
        self.clock.now += 10
        code, refused = self.ask(private=bytes(range(32)))
        self.assertEqual(code, 409)
        # The panel that waits can ask again and gets the same request.
        self.assertEqual(self.ask(), (200, said))

    def test_a_request_expires(self):
        _, said = self.ask()
        self.clock.now += pairing.WAIT_SECONDS + 1
        self.assertIsNone(pairing.waiting(self.folder, wall=self.clock))
        pairing.answer(said["id"], True, folder=self.folder)
        self.assertEqual(self.pairing.check(said["id"]),
                         (404, {"state": "unknown"}, None))
        self.assertFalse(os.path.exists(
            os.path.join(self.folder, pairing.REQUEST_NAME)))

    def test_a_new_request_after_an_answer_needs_a_gap(self):
        _, said = self.ask()
        pairing.answer(said["id"], False, folder=self.folder)
        self.pairing.check(said["id"])
        self.assertEqual(self.ask()[0], 429)
        self.clock.now += pairing.GAP_SECONDS
        self.assertEqual(self.ask()[0], 200)

    def test_a_bad_request_is_refused(self):
        for body in (None, [], {"key": "xyz"}, {"key": "00" * 31},
                     {"key": "AB" * 32}, {"key": "00" * 32}):
            code, _ = self.pairing.ask(body, "192.168.1.50")
            self.assertEqual(code, 400, body)
        self.assertIsNone(pairing.waiting(self.folder, wall=self.clock))

    def test_a_name_is_made_safe(self):
        self.ask(name='<b>"x"</b>\n' + "y" * 40)
        name = pairing.waiting(self.folder, wall=self.clock)["name"]
        self.assertRegex(name, r"^[A-Za-z0-9 ._-]{1,24}$")

    def test_an_answer_needs_an_id(self):
        with self.assertRaises(ValueError):
            pairing.answer("../x", True, folder=self.folder)


class WaitingTest(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def write(self, values):
        with open(os.path.join(self.folder, pairing.REQUEST_NAME), "w") as out:
            json.dump(values, out)

    def test_a_damaged_file_waits_for_nothing(self):
        good = {"id": "0123456789abcdef", "code": "123456", "until": 2000.0,
                "name": "p", "address": "a"}
        self.write(good)
        self.assertIsNotNone(pairing.waiting(self.folder, wall=lambda: 1000))
        for key, value in (("id", "x"), ("code", "12345"), ("until", True),
                           ("until", "soon"), ("code", 123456)):
            self.write(dict(good, **{key: value}))
            self.assertIsNone(pairing.waiting(self.folder, wall=lambda: 1000),
                              key)


class ResponderTest(unittest.TestCase):

    def setUp(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server.bind(("127.0.0.1", 0))
        self.addCleanup(self.server.close)
        self.client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client.bind(("127.0.0.1", 0))
        self.client.settimeout(2)
        self.addCleanup(self.client.close)
        self.now = 0.0
        self.responder = pairing.Responder(8765, name="deck",
                                           sock=self.server,
                                           clock=lambda: self.now)

    def test_a_search_gets_the_port_and_the_name(self):
        self.assertTrue(self.responder.handle(pairing.DISCOVER,
                                              self.client.getsockname()))
        data, _ = self.client.recvfrom(256)
        self.assertEqual(json.loads(data), {"service": "steamos-utility-center",
                                            "port": 8765, "name": "deck"})

    def test_anything_else_gets_no_answer(self):
        for data in (b"", b"hello", pairing.DISCOVER + b"x"):
            self.assertFalse(self.responder.handle(
                data, self.client.getsockname()), data)

    def test_the_answers_each_second_are_few(self):
        sent = [self.responder.handle(pairing.DISCOVER,
                                      self.client.getsockname())
                for _ in range(pairing.ANSWERS_EACH_SECOND + 5)]
        self.assertEqual(sum(sent), pairing.ANSWERS_EACH_SECOND)
        self.now += 1.0
        self.assertTrue(self.responder.handle(pairing.DISCOVER,
                                              self.client.getsockname()))

    def test_the_thread_answers_a_real_datagram(self):
        responder = pairing.Responder(0, name="deck", sock=self.server).start()
        self.assertIsNotNone(responder)
        self.client.sendto(pairing.DISCOVER, self.server.getsockname())
        data, source = self.client.recvfrom(256)
        self.assertEqual(json.loads(data)["service"], "steamos-utility-center")
        self.assertEqual(source, self.server.getsockname())


if __name__ == "__main__":
    unittest.main()
