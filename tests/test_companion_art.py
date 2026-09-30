# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The picture of the game that runs, and the one path that serves it.

Steam downloads the artwork of every game a person owns and keeps it on
the disk. The panel therefore needs no network of its own and no key to
anything: the picture is already here, and this hands it over.

The path carries no number. steamapps builds it from the number it read
out of the process table and a name of its own, so there is nothing in a
request that can ask for another game or another file.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

from steamos_utility_center import companion, steamapps    # noqa: E402

TOKEN = "t" * companion.TOKEN_MINIMUM


def jpeg(width=460, height=215, kind=0xC0, room=0):
    """A JPEG as far as its frame header, and padding after it.

    The service reads the front of the file to learn whether the panel
    can decode it, so the front has to be real. What follows a frame
    header is entropy data that nothing here reads.

    kind names the frame header: 0xC0 is baseline, which the panel
    decodes, and 0xC2 is progressive, which it does not.
    """
    frame = bytes([0xFF, kind, 0x00, 0x11, 0x08,
                   height >> 8, height & 0xFF, width >> 8, width & 0xFF,
                   0x03]) + bytes([1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1])
    out = (b"\xff\xd8"
           + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
           + frame + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00")
    out += b"\x7f" * max(0, room - len(out) - 2)
    return out + b"\xff\xd9"


# The one the tests hand over unless they want another.
PICTURE = jpeg(room=760)


def library(home, appid, name="header.jpg", body=PICTURE):
    where = os.path.join(home, ".local", "share", "Steam",
                         "appcache", "librarycache", str(appid))
    os.makedirs(where, exist_ok=True)
    path = os.path.join(where, name)
    with open(path, "wb") as handle:
        handle.write(body)
    return path


class LookupTest(unittest.TestCase):
    def test_the_header_is_the_one_it_takes(self):
        """460 across, and the card on the panel is 460 across."""
        with tempfile.TemporaryDirectory() as home:
            library(home, 1840, "library_hero.jpg")
            wanted = library(home, 1840, "header.jpg")
            self.assertEqual(steamapps.artwork(1840, home), wanted)

    def test_the_hero_answers_where_there_is_no_header(self):
        with tempfile.TemporaryDirectory() as home:
            wanted = library(home, 1840, "library_hero.jpg")
            self.assertEqual(steamapps.artwork(1840, home), wanted)

    def test_a_portrait_alone_is_no_picture(self):
        """Stretched across a wide card it looks worse than a name."""
        with tempfile.TemporaryDirectory() as home:
            library(home, 1840, "library_600x900.jpg")
            library(home, 1840, "logo.png")
            self.assertEqual(steamapps.artwork(1840, home), "")

    def test_a_game_with_nothing_downloaded_is_no_picture(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(steamapps.artwork(999999, home), "")

    def test_nothing_playing_is_no_picture(self):
        self.assertEqual(steamapps.artwork(None), "")

    def test_one_too_large_to_carry_is_left_alone(self):
        """A hero can be megabytes. The panel decodes this on a chip with
        one screen's worth of memory to spare."""
        with tempfile.TemporaryDirectory() as home:
            library(home, 1840, "header.jpg",
                    jpeg(room=steamapps.ART_LIMIT + 10))
            self.assertEqual(steamapps.artwork(1840, home), "")

    def test_a_picture_the_panel_cannot_decode_is_no_picture(self):
        """The panel decodes with TJPGD, which reads baseline JPEG and
        nothing else. A progressive one costs 40 KB over the air and
        leaves the card empty, so it never leaves this machine."""
        with tempfile.TemporaryDirectory() as home:
            library(home, 1840, "header.jpg", jpeg(kind=0xC2))
            self.assertEqual(steamapps.artwork(1840, home), "")

    def test_a_baseline_one_next_to_it_is_taken(self):
        """The header is progressive and the hero is not, so the hero
        goes. A game keeps its picture where one of the two can be
        read."""
        with tempfile.TemporaryDirectory() as home:
            library(home, 1840, "header.jpg", jpeg(kind=0xC2))
            wanted = library(home, 1840, "library_hero.jpg", jpeg())
            self.assertEqual(steamapps.artwork(1840, home), wanted)

    def test_something_that_is_not_a_picture_at_all_is_no_picture(self):
        with tempfile.TemporaryDirectory() as home:
            library(home, 1840, "header.jpg", b"not a picture")
            self.assertEqual(steamapps.artwork(1840, home), "")

    def test_the_path_is_built_and_never_taken_from_a_caller(self):
        """The number goes through int(), so a string that walks upward
        out of the directory is not a number and raises rather than
        reaching a file."""
        with tempfile.TemporaryDirectory() as home:
            with self.assertRaises(ValueError):
                steamapps.artwork("../../../../etc/passwd", home)


class ServedTest(unittest.TestCase):
    """The path, over a real socket, signed the way the panel signs."""

    def setUp(self):
        self.nonces = companion.Nonces()
        handler = companion.make_handler(TOKEN, self.nonces)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path, signed=True):
        nonce = self.nonces.issue()
        headers = {}
        if signed:
            headers = {
                companion.NONCE_HEADER: nonce,
                companion.AUTH_HEADER: companion.signature(
                    TOKEN, "GET", path, nonce, b""),
            }
        link = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        link.request("GET", path, headers=headers)
        answer = link.getresponse()
        body = answer.read()
        code = answer.status
        kind = answer.getheader("Content-Type")
        link.close()
        return code, kind, body

    def test_it_hands_over_the_bytes_that_are_on_the_disk(self):
        with tempfile.TemporaryDirectory() as home:
            library(home, 620)
            keep = steamapps.now_playing_art
            steamapps.now_playing_art = lambda *a, **k: library(home, 620)
            try:
                code, kind, body = self.get("/v1/art")
            finally:
                steamapps.now_playing_art = keep
        self.assertEqual(code, 200)
        self.assertEqual(kind, "image/jpeg")
        self.assertEqual(body, PICTURE)

    def test_no_game_and_no_picture_read_the_same(self):
        """The panel draws both as a card with a name and no picture."""
        keep = steamapps.now_playing_art
        steamapps.now_playing_art = lambda *a, **k: ""
        try:
            code, _kind, body = self.get("/v1/art")
        finally:
            steamapps.now_playing_art = keep
        self.assertEqual(code, 404)
        self.assertIn("error", json.loads(body))

    def test_a_stranger_gets_no_picture_either(self):
        """The check comes before the path, the way it does for status."""
        code, _kind, _body = self.get("/v1/art", signed=False)
        self.assertEqual(code, 401)

    def test_a_signature_for_one_path_does_not_fit_the_other(self):
        """The path is under the signature, so a captured status read is
        not an artwork read and the other way round."""
        nonce = self.nonces.issue()
        headers = {
            companion.NONCE_HEADER: nonce,
            companion.AUTH_HEADER: companion.signature(
                TOKEN, "GET", "/v1/status", nonce, b""),
        }
        link = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        link.request("GET", "/v1/art", headers=headers)
        answer = link.getresponse()
        answer.read()
        self.assertEqual(answer.status, 401)
        link.close()

    def test_the_answer_carries_the_next_nonce(self):
        """Every answer does, so the ordinary poll stays at one round
        trip. An artwork read that forgot would cost the panel a 401 on
        whatever it asked next."""
        keep = steamapps.now_playing_art
        steamapps.now_playing_art = lambda *a, **k: ""
        try:
            nonce = self.nonces.issue()
            link = http.client.HTTPConnection("127.0.0.1", self.port,
                                              timeout=5)
            link.request("GET", "/v1/art", headers={
                companion.NONCE_HEADER: nonce,
                companion.AUTH_HEADER: companion.signature(
                    TOKEN, "GET", "/v1/art", nonce, b""),
            })
            answer = link.getresponse()
            answer.read()
            self.assertTrue(answer.getheader(companion.NONCE_HEADER))
            link.close()
        finally:
            steamapps.now_playing_art = keep

    def test_a_path_nobody_serves_is_still_a_404(self):
        code, _kind, _body = self.get("/v1/whatever")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
