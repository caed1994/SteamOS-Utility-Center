# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""panel_pair.c, built here and asked, against pairing.py.

The panel and the PC must calculate the same secret and the same code from
the same keys, byte for byte, or a pairing ends in a code that differs on
the two screens. The harness builds against the mbedtls of this machine,
which is mbedtls 2; the board has mbedtls 3, and panel_pair.c uses calls
that the two have in common.
"""

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(REPO, "server"))
sys.path.insert(0, HERE)

from steamos_utility_center import companion, pairing  # noqa: E402

FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
HARNESS = os.path.join(HERE, "c", "panel-pair-harness.c")


def code(name):
    with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
        return handle.read()


def define(name, text):
    found = re.search(r'#define %s ("[^"]*"|\d+)' % name, text)
    assert found, name
    value = found.group(1)
    return value.strip('"') if value.startswith('"') else int(value)


class SameNamesTest(unittest.TestCase):
    """The numbers and words that both ends must have alike."""

    def test_the_search_and_the_path_are_the_ones_of_the_pc(self):
        header = code("panel_pair.h")
        self.assertEqual(define("PANEL_PAIR_DISCOVER", header).encode(),
                         pairing.DISCOVER)
        self.assertEqual(define("PANEL_PAIR_SERVICE", header), pairing.SERVICE)
        self.assertEqual(define("PANEL_PAIR_PORT", header), companion.PORT)
        self.assertEqual(define("PANEL_PAIR_PATH", header), companion.PAIR_PATH)

    def test_the_rooms_hold_what_the_pc_sends(self):
        header = code("panel_pair.h")
        self.assertEqual(define("PANEL_PAIR_NAME", header),
                         pairing.NAME_CHARS + 1)
        self.assertEqual(define("PANEL_PAIR_CODE", header),
                         pairing.CODE_DIGITS + 1)

    def test_the_labels_are_the_labels_of_the_pc(self):
        source = code("panel_pair.c")
        self.assertEqual(define("SECRET_LABEL", source).encode(),
                         pairing.SECRET_LABEL)
        self.assertEqual(define("CODE_LABEL", source).encode(),
                         pairing.CODE_LABEL)

    def test_the_firmware_builds_it(self):
        cmake = code("CMakeLists.txt")
        self.assertIn('"panel_pair.c"', cmake)

    def test_the_token_fits_where_the_panel_keeps_it(self):
        self.assertGreater(define("PANEL_PAIR_SECRET", code("panel_pair.h")),
                           companion.TOKEN_MINIMUM)
        self.assertIn("char token[128];", code("config.h"))


class FirmwareRulesTest(unittest.TestCase):
    """The rules of the pairing in the parts that only the board runs.

    main.c and config.c need ESP-IDF, so this reads them. The board itself
    is the test of the rest.
    """

    def test_a_panel_with_a_network_and_no_secret_pairs(self):
        main = code("main.c")
        self.assertIn("if (!config.ssid[0]) portal_start();\n"
                      "    else if (!config.token[0]) pair_start();", main)

    def test_the_pairing_takes_the_place_of_the_poll(self):
        main = code("main.c")
        turn = main.index("pair_turn(&answered);")
        poll = main.index('request("/v1/status",NULL,PANEL_ASK_MS)')
        self.assertLess(turn, poll)
        self.assertIn("if (pair.phase!=PANEL_PAIRING_NONE) {", main)

    def test_the_address_and_the_secret_go_into_one_commit(self):
        main = code("main.c")
        self.assertIn("panel_config_save_pairing(pair.server,pair.secret)",
                      main)
        saved = code("config.c")
        body = saved[saved.index("esp_err_t panel_config_save_pairing"):]
        body = body[:body.index("\n}\n")]
        self.assertEqual(body.count("nvs_commit"), 1)

    def test_the_private_key_does_not_outlive_its_use(self):
        main = code("main.c")
        self.assertIn("memset(&pair.keys.private_key,0,"
                      "sizeof(pair.keys.private_key));", main)
        self.assertIn("memset(&pair.keys,0,sizeof(pair.keys));", main)

    def test_a_secret_by_hand_still_has_the_length_of_one(self):
        saved = code("config.c")
        self.assertIn("(tlen && tlen<32)", saved)
        self.assertIn("(token==0 || token>=32)", saved)

    def test_the_setup_pages_need_no_address_and_no_token(self):
        for page in ("setup.html", "setup-de.html"):
            text = code(page)
            for field in ("server", "token"):
                tag = re.search(r'<input id="%s"[^>]*>' % field, text).group(0)
                self.assertNotIn("required", tag, (page, field))
            self.assertIn('minlength="32"', text)


def buildable():
    if not shutil.which("cc") and not shutil.which("gcc"):
        return False
    return any(os.path.exists(os.path.join(place, "mbedtls", "ecdh.h"))
               for place in ("/usr/include", "/usr/local/include"))


@unittest.skipUnless(buildable(), "no C compiler or no mbedtls headers here")
class HarnessTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-pair")
        done = subprocess.run(
            [shutil.which("cc") or shutil.which("gcc"), "-std=gnu17", "-Wall",
             "-Wextra", "-Werror", "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_pair.c"), "-lmbedcrypto"],
            capture_output=True, text=True)
        # A failure and not a skip: the headers are here, so a build that
        # fails is a fault in the file.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_pair.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def ask(self, *commands):
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def test_the_vectors_of_the_rfc(self):
        alice = "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
        bob_public = ("de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e14"
                      "6f882b4f")
        nine = "09" + "00" * 31
        self.assertEqual(self.ask("x25519 %s %s" % (alice, nine),
                                  "shared %s %s" % (alice, bob_public)),
                         ["8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eb"
                          "a4a98eaa9b4e6a",
                          "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376"
                          "f09b3c1e161742"])

    def test_both_ends_calculate_the_same_values(self):
        cases = []
        for _ in range(12):
            panel_private = secrets.token_bytes(32)
            pc_private = secrets.token_bytes(32)
            panel_key = pairing.public_key(panel_private)
            pc_key = pairing.public_key(pc_private)
            shared = pairing.shared_secret(pc_private, panel_key)
            cases.append((panel_private, panel_key, pc_key, shared))
        answers = self.ask(*["shared %s %s" % (one.hex(), pc.hex())
                             for one, _key, pc, _shared in cases]
                           + ["derive %s %s %s" % (shared.hex(), key.hex(),
                                                   pc.hex())
                              for _one, key, pc, shared in cases])
        for index, (_one, key, pc, shared) in enumerate(cases):
            self.assertEqual(answers[index], shared.hex())
            secret, said = pairing.derive(shared, key, pc)
            self.assertEqual(answers[len(cases) + index], "%s %s"
                             % (secret, said))

    def test_a_new_key_pair_is_a_key_pair(self):
        private, public = self.ask("keys 7")[0].split()
        self.assertEqual(private, bytes(range(7, 39)).hex())
        self.assertEqual(public,
                         pairing.public_key(bytes.fromhex(private)).hex())

    def test_a_weak_key_is_refused(self):
        """mbedtls refuses some of these itself. panel_pair_shared refuses
        a result of zero as well, so the rule does not depend on it."""
        from test_pairing import SMALL_ORDER
        alice = "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
        self.assertEqual(self.ask(*["shared %s %s" % (alice, point.hex())
                                    for point in SMALL_ORDER]),
                         ["(weak)"] * len(SMALL_ORDER))

    def test_the_top_bit_of_the_point_is_ignored(self):
        self.assertEqual(
            self.ask("x25519 4b66e9d4d1b4673c5ad22691957d6af5c11b6421e0ea01d4"
                     "2ca4169e7918ba0d e5210f12786811d3f4b7959d0538ae2c31dbe7"
                     "106fc03c3efc4cd549c715a493"),
            ["95cbde9476e8907d7aade45cb4b873f88b595a68799fa152e6f8f7647aac7957"])

    def test_the_body_is_one_the_pc_takes(self):
        key = pairing.public_key(bytes(range(32)))
        body, length = self.ask("body 200 SteamOS-Panel-A1B2 %s"
                                % key.hex())[0].rsplit(" ", 1)
        self.assertEqual(int(length), len(body))
        self.assertLessEqual(len(body), companion.BODY_LIMIT)
        self.assertEqual(json.loads(body), {"name": "SteamOS-Panel-A1B2",
                                            "key": key.hex()})
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        said = pairing.Pairing(folder=folder, name="deck").ask(
            json.loads(body), "192.168.1.50")
        self.assertEqual(said[0], 200)

    def test_a_body_with_no_room_is_no_body(self):
        key = "ab" * 32
        self.assertEqual(self.ask("body 50 panel %s" % key), ["(empty) 0"])

    def test_only_small_hexadecimal_digits_are_a_key(self):
        self.assertEqual(self.ask("unhex " + "AB" * 32, "unhex " + "ab" * 31,
                                  "unhex " + "xy" * 32, "unhex " + "0f" * 32),
                         ["(no)", "(no)", "(no)", "0f" * 32])

    def test_a_name_keeps_only_the_characters_of_a_name(self):
        self.assertEqual(self.ask('name <b>"Deck"</b>;rm -rf ~',
                                  "name " + "x" * 40),
                         ["[bDeckbrm -rf ]", "[" + "x" * 24 + "]"])

    def test_an_id_is_sixteen_small_hexadecimal_digits(self):
        self.assertEqual(self.ask("id 0123456789abcdef", "id 0123456789ABCDEF",
                                  "id 0123", "id ../../etc/passwd00"),
                         ["1", "0", "0", "0"])


if __name__ == "__main__":
    unittest.main()
