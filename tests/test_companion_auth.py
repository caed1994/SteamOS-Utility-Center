# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The firmware and the service have to sign the same bytes.

Two languages, and neither one calls the other. The panel signs in C with
mbedtls and this machine checks in Python with hashlib, and nothing in
either file makes the other one true. A newline that moves on one side is a
panel that says "no PC" and a journal that says "unauthorized", with no
line of code that looks wrong.

So this test builds the firmware's own file and compares the two, character
for character. It needs a C compiler and the mbedtls headers, and it says so
and stops where the machine has neither. The board's toolchain is not
needed: panel_auth.c is written to build against mbedtls 2 and mbedtls 3,
which is what the machine and ESP-IDF carry.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import companion                    # noqa: E402

FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
HARNESS = os.path.join(REPO, "tests", "c", "panel-auth-harness.c")


def buildable():
    """Whether this machine has what the build needs."""
    if not shutil.which("cc") and not shutil.which("gcc"):
        return False
    return any(os.path.exists(os.path.join(place, "mbedtls", "md.h"))
               for place in ("/usr/include", "/usr/local/include"))


@unittest.skipUnless(buildable(), "no C compiler or no mbedtls headers here")
class SameSignatureTest(unittest.TestCase):
    """What the panel sends, beside what this machine works out."""

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-auth")
        done = subprocess.run(
            [shutil.which("cc") or shutil.which("gcc"), "-Wall", "-Wextra",
             "-Werror", "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_auth.c"), "-lmbedcrypto"],
            capture_output=True, text=True)
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise unittest.SkipTest("panel_auth.c did not build here:\n"
                                    + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def firmware_says(self, token, method, path, nonce, body):
        done = subprocess.run(
            [self.program, token, method, path, nonce, body],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def both(self, token, method, path, nonce, body):
        return (self.firmware_says(token, method, path, nonce, body),
                companion.signature(token, method, path, nonce,
                                    body.encode()))

    def test_a_status_read_signs_the_same_on_both_sides(self):
        panel, host = self.both("x" * 32, "GET", "/v1/status", "a1b2", "")
        self.assertEqual(panel, host)

    def test_a_press_signs_the_same_on_both_sides(self):
        panel, host = self.both("x" * 32, "POST", "/v1/action", "c3d4",
                                '{"action":"mute"}')
        self.assertEqual(panel, host)

    def test_the_body_reaches_the_signature(self):
        """Or mute and poweroff sign the same and one becomes the other."""
        mute = self.firmware_says("x" * 32, "POST", "/v1/action", "c3d4",
                                  '{"action":"mute"}')
        off = self.firmware_says("x" * 32, "POST", "/v1/action", "c3d4",
                                 '{"action":"poweroff"}')
        self.assertNotEqual(mute, off)

    def test_the_path_reaches_the_signature(self):
        one = self.firmware_says("x" * 32, "GET", "/v1/status", "n", "")
        other = self.firmware_says("x" * 32, "GET", "/v1/other", "n", "")
        self.assertNotEqual(one, other)

    def test_the_nonce_reaches_the_signature(self):
        one = self.firmware_says("x" * 32, "GET", "/v1/status", "one", "")
        other = self.firmware_says("x" * 32, "GET", "/v1/status", "two", "")
        self.assertNotEqual(one, other)

    def test_a_different_token_signs_differently(self):
        one = self.firmware_says("x" * 32, "GET", "/v1/status", "n", "")
        other = self.firmware_says("y" * 32, "GET", "/v1/status", "n", "")
        self.assertNotEqual(one, other)

    def test_a_token_of_the_length_the_installer_writes(self):
        """43 characters, which is what secrets.token_urlsafe(32) gives."""
        token = "Hs7QpV2mXk9LbN4rT6yZ1cA3dE5gJ8uW0iO2pQ4sR6t"
        panel, host = self.both(token, "GET", "/v1/status", "f00d", "")
        self.assertEqual(panel, host)

    def test_the_signature_is_a_sha256_in_hexadecimal(self):
        said = self.firmware_says("x" * 32, "GET", "/v1/status", "n", "")
        self.assertEqual(len(said), 64)
        self.assertTrue(all(one in "0123456789abcdef" for one in said))

    def test_the_whole_exchange_signs_end_to_end(self):
        """The panel's signature, put through the service's own check."""
        token = "x" * 32
        nonces = companion.Nonces()
        nonce = nonces.issue()
        panel = self.firmware_says(token, "GET", "/v1/status", nonce, "")
        wanted = companion.signature(token, "GET", "/v1/status", nonce, b"")
        self.assertEqual(panel, wanted)
        self.assertTrue(nonces.spend(nonce))
        self.assertFalse(nonces.spend(nonce))


class FirmwareSendsNoSecretTest(unittest.TestCase):
    """What the panel puts on the wire, read out of its own source.

    No compiler and no board is needed for this, and that is the point: the
    test above is skipped on a machine with no mbedtls, and this one still
    refuses a firmware that goes back to sending the token.
    """

    def source(self, name):
        with open(os.path.join(FIRMWARE, name)) as handle:
            return handle.read()

    def test_the_token_is_no_longer_a_header(self):
        """It went out on every poll, which is 28,800 times a day."""
        self.assertNotIn("X-Panel-Token", self.source("main.c"))

    def test_every_request_is_signed(self):
        self.assertIn("panel_auth_sign", self.source("main.c"))

    def test_the_two_sides_name_the_same_headers(self):
        """A rename on one side is a panel that never gets an answer."""
        text = self.source("main.c")
        self.assertIn('"%s"' % companion.NONCE_HEADER, text)
        self.assertIn('"%s"' % companion.AUTH_HEADER, text)

    def test_the_build_carries_the_new_file_and_its_library(self):
        cmake = self.source("CMakeLists.txt")
        self.assertIn("panel_auth.c", cmake)
        self.assertIn("mbedtls", cmake)


if __name__ == "__main__":
    unittest.main()
