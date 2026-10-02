# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The order of the pages of the band, which somebody can change.

Asked for: a list in the settings of the panel with a button up and a
button down on each page. The top one is the start page. The order is
stored as one number with room for eight pages. A stored number that is
not valid gives the order of the firmware, and a page that a later
firmware adds comes last. No page is hidden, and a wake does not jump to
the start page.

firmware/companion/main/panel_pages.c reads and writes that number, and
the harness in tests/c/panel-pages-harness.c asks it here. The rules
below hold where main.c stores the number and where ui.c uses it.
firmware/companion/preview/check_pages.c checks the screen of the order
itself.
"""

from __future__ import annotations

import itertools
import os
import random
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
HARNESS = os.path.join(REPO, "tests", "c", "panel-pages-harness.c")

PAGES = 5
DEFAULT = list(range(PAGES))


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


def code(name):
    with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
        text = handle.read()
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def stored(*places):
    """The stored number of these pages, the first place lowest, with
    0xF in each place that is left."""
    value = 0xFFFFFFFF
    for place, page in enumerate(places):
        value &= ~(0xF << (4 * place))
        value |= (page & 0xF) << (4 * place)
    return value


@unittest.skipUnless(compiler(), "no C compiler here")
class OrderTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-pages")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_pages.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_pages.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def ask(self, *commands):
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def order(self, value):
        return [int(page) for page in self.ask("order %x" % value)[0].split()]

    def test_the_firmware_has_five_pages_and_room_for_eight(self):
        self.assertEqual(self.ask("size"), ["%d 8" % PAGES])

    def test_nobody_chose_an_order(self):
        self.assertEqual(self.order(0xFFFFFFFF), DEFAULT)

    def test_every_order_comes_back_as_it_was_stored(self):
        orders = list(itertools.permutations(DEFAULT))
        packed = self.ask(*["pack " + " ".join(map(str, one)) for one in orders])
        for one, value in zip(orders, packed):
            self.assertEqual(int(value, 16), stored(*one))
        answers = self.ask(*["order " + value for value in packed])
        for one, answer in zip(orders, answers):
            self.assertEqual([int(page) for page in answer.split()], list(one))

    def test_the_places_nobody_holds_are_0xf(self):
        self.assertEqual(self.ask("pack 3 0 1 2 4"), ["fff42103"])

    def test_a_page_that_comes_twice_counts_once(self):
        self.assertEqual(self.order(stored(3, 3, 1, 3)), [3, 1, 0, 2, 4])

    def test_a_page_this_firmware_does_not_have_is_left_out(self):
        self.assertEqual(self.order(stored(7, 2, 0xE, 5, 4)), [2, 4, 0, 1, 3])

    def test_a_page_a_later_update_adds_comes_last(self):
        # The order of a firmware with four pages, and the card is new.
        self.assertEqual(self.order(stored(3, 0, 2, 1)), [3, 0, 2, 1, 4])

    def test_a_number_nobody_wrote_still_gives_each_page_once(self):
        draw = random.Random(1994)
        values = [draw.getrandbits(32) for _ in range(3000)]
        values += [0, 0x44444444, 0x01234567, 0x76543210, 0x0F0F0F0F]
        answers = self.ask(*["order %x" % value for value in values])
        for value, answer in zip(values, answers):
            self.assertEqual(sorted(int(page) for page in answer.split()), DEFAULT,
                             "0x%08x" % value)

    def test_a_move_swaps_a_page_with_its_neighbour(self):
        self.assertEqual(self.ask("move ffffffff 0 1"), ["1 1 0 2 3 4"])
        self.assertEqual(self.ask("move ffffffff 4 -1"), ["1 0 1 2 4 3"])
        self.assertEqual(self.ask("move ffffffff 2 -1"), ["1 0 2 1 3 4"])

    def test_nothing_moves_past_an_end_or_further_than_one_place(self):
        for place, step in ((0, -1), (4, 1), (1, 2), (2, -2), (-1, 1), (5, -1), (2, 0)):
            self.assertEqual(self.ask("move ffffffff %d %d" % (place, step)),
                             ["0 0 1 2 3 4"], (place, step))

    def test_the_place_of_a_page(self):
        value = stored(3, 0, 4, 1, 2)
        self.assertEqual(self.ask(*["place %x %d" % (value, page) for page in DEFAULT]),
                         ["1", "3", "4", "0", "2"])


class StorageTest(unittest.TestCase):

    def test_a_panel_without_a_stored_order_has_the_order_of_the_firmware(self):
        main = code("main.c")
        self.assertIn(".page_order=PANEL_PAGES_UNSET", main)
        self.assertIn('nvs_get_u32(h,"page_order",&key)', main)

    def test_the_order_is_stored_as_one_wide_number(self):
        main = code("main.c")
        self.assertIn('key==PANEL_PAGE_ORDER?"page_order"', main)
        wide = re.search(r"bool wide=([^;]*);", main)
        self.assertIsNotNone(wide)
        self.assertIn("key==PANEL_PAGE_ORDER", wide.group(1))

    def test_the_band_stands_in_the_stored_order(self):
        ui = code("ui.c")
        self.assertIn("panel_pages_order(local.page_order,page_order)", ui)
        self.assertRegex(ui, r"panel_pages_place\(page_order,i\)\*480")

    def test_a_move_is_saved_at_once(self):
        ui = code("ui.c")
        move = re.search(r"static void arrange_move\(lv_event_t \*e\)\s*\{(.*?)\n\}", ui, re.S)
        self.assertIsNotNone(move)
        self.assertIn("save_setting(PANEL_PAGE_ORDER,(int)local.page_order,true)", move.group(1))
        self.assertIn("local.page_order=panel_pages_pack(page_order)", move.group(1))


if __name__ == "__main__":
    unittest.main()
