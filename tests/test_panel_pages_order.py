# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The order of the pages of the band, which somebody can change.

Asked for: a list in the settings of the panel with a button up and a
button down on each page. The top one is the start page. The order is
stored as one number with room for eight pages. A stored number that is
not valid gives the order of the firmware, and a page that a later
firmware adds comes last. A wake does not jump to the start page.

Asked for later: an eye beside the arrows that hides a page, with a stroke
through the eye on a hidden page. A hidden page keeps its place in the
order. The band holds only the pages that are shown, and the first of
them is the start page. One page at the least stays shown. The hidden
pages are stored as a number of their own, a bit for each page.

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

PAGES = 6
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

    def test_the_firmware_has_six_pages_and_room_for_eight(self):
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
        self.assertEqual(self.ask("pack 3 0 1 2 4 5"), ["ff542103"])

    def test_a_page_that_comes_twice_counts_once(self):
        self.assertEqual(self.order(stored(3, 3, 1, 3)), [3, 1, 0, 2, 4, 5])

    def test_a_page_this_firmware_does_not_have_is_left_out(self):
        self.assertEqual(self.order(stored(7, 2, 0xE, 6, 4)), [2, 4, 0, 1, 3, 5])

    def test_a_page_a_later_update_adds_comes_last(self):
        # The order of a firmware with four pages, and the card and the LED
        # bar are new.
        self.assertEqual(self.order(stored(3, 0, 2, 1)), [3, 0, 2, 1, 4, 5])
        # The order of a firmware with five pages, and the LED bar is new.
        self.assertEqual(self.order(stored(4, 3, 0, 2, 1)), [4, 3, 0, 2, 1, 5])

    def test_a_number_nobody_wrote_still_gives_each_page_once(self):
        draw = random.Random(1994)
        values = [draw.getrandbits(32) for _ in range(3000)]
        values += [0, 0x44444444, 0x01234567, 0x76543210, 0x0F0F0F0F]
        answers = self.ask(*["order %x" % value for value in values])
        for value, answer in zip(values, answers):
            self.assertEqual(sorted(int(page) for page in answer.split()), DEFAULT,
                             "0x%08x" % value)

    def test_a_move_swaps_a_page_with_its_neighbour(self):
        self.assertEqual(self.ask("move ffffffff 0 1"), ["1 1 0 2 3 4 5"])
        self.assertEqual(self.ask("move ffffffff 5 -1"), ["1 0 1 2 3 5 4"])
        self.assertEqual(self.ask("move ffffffff 2 -1"), ["1 0 2 1 3 4 5"])

    def test_nothing_moves_past_an_end_or_further_than_one_place(self):
        for place, step in ((0, -1), (5, 1), (1, 2), (2, -2), (-1, 1), (6, -1), (2, 0)):
            self.assertEqual(self.ask("move ffffffff %d %d" % (place, step)),
                             ["0 0 1 2 3 4 5"], (place, step))

    # The hidden pages: a bit for each page, and one page at the least
    # shown.

    def test_the_hidden_pages_of_a_stored_number(self):
        self.assertEqual(self.ask("hidden 0", "hidden 5", "hidden f"), ["0", "5", "f"])
        # A bit of a page that this firmware does not have is left out.
        self.assertEqual(self.ask("hidden ffffffc2"), ["2"])
        # A number that hides every page hides none.
        self.assertEqual(self.ask("hidden 3f", "hidden ffffffff"), ["0", "0"])

    def test_a_page_is_hidden_and_shown_again(self):
        self.assertEqual(self.ask("toggle 0 1", "toggle 2 1", "toggle 3 4"),
                         ["1 2", "1 0", "1 13"])

    def test_the_last_page_that_is_shown_stays(self):
        self.assertEqual(self.ask("toggle 1f 5", "toggle 37 3"), ["0 1f", "0 37"])
        # Another page shown again, and then this one can go.
        self.assertEqual(self.ask("toggle 1f 0", "toggle 1e 5"), ["1 1e", "1 3e"])

    def test_a_page_that_this_firmware_does_not_have_does_not_toggle(self):
        self.assertEqual(self.ask("toggle 0 6", "toggle 0 -1", "toggle 0 31"), ["0 0"] * 3)

    def test_the_count_of_the_pages_that_are_shown(self):
        self.assertEqual(self.ask("shown 0", "shown 1", "shown 5", "shown 15", "shown f",
                                  "shown 1f"),
                         ["6", "5", "4", "3", "2", "1"])

    def test_the_band_holds_the_shown_pages_in_their_order(self):
        draw = random.Random(2610)
        for _ in range(300):
            order = DEFAULT[:]
            draw.shuffle(order)
            hidden = draw.randrange(0, (1 << PAGES) - 1)
            value = stored(*order)
            shown = [page for page in order if not hidden >> page & 1]
            places = self.ask(*["band %x %x %d" % (value, hidden, page) for page in DEFAULT])
            self.assertEqual([int(place) for place in places],
                             [shown.index(page) if page in shown else -1 for page in DEFAULT])
            # A place before the first is the first, and one past the last
            # is the last.
            wanted = range(-2, PAGES + 2)
            pages = self.ask(*["at %x %x %d" % (value, hidden, place) for place in wanted])
            self.assertEqual([int(page) for page in pages],
                             [shown[min(max(place, 0), len(shown) - 1)] for place in wanted])
        # A page that this firmware does not have has no place.
        value = stored(*DEFAULT)
        self.assertEqual(self.ask("band %x 0 6" % value, "band %x 0 -1" % value), ["-1", "-1"])

    def test_the_place_of_a_page(self):
        value = stored(3, 0, 4, 1, 2)
        self.assertEqual(self.ask(*["place %x %d" % (value, page) for page in DEFAULT]),
                         ["1", "3", "4", "0", "2", "5"])


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
        self.assertIn("page_hidden=panel_pages_hidden(local.page_hidden)", ui)
        arrange = re.search(r"static void band_arrange\(int showing\)\s*\{(.*?)\n\}", ui, re.S)
        self.assertIsNotNone(arrange)
        self.assertIn("int place=panel_pages_band_place(page_order,page_hidden,i);", arrange.group(1))
        self.assertIn("lv_obj_add_flag(band_pages[i],LV_OBJ_FLAG_HIDDEN)", arrange.group(1))
        self.assertIn("lv_obj_set_x(band_pages[i],place*480)", arrange.group(1))
        # The band starts on the first page that is shown.
        self.assertIn("band_arrange(panel_pages_band_page(page_order,page_hidden,0));", ui)

    def test_a_panel_without_hidden_pages_shows_every_page(self):
        main = code("main.c")
        self.assertIn(".page_hidden=0", main)
        self.assertIn('nvs_get_u32(h,"page_hidden",&key)', main)

    def test_the_hidden_pages_are_stored_as_one_wide_number(self):
        main = code("main.c")
        self.assertIn('key==PANEL_PAGE_HIDDEN?"page_hidden"', main)
        wide = re.search(r"bool wide=([^;]*);", main)
        self.assertIsNotNone(wide)
        self.assertIn("key==PANEL_PAGE_HIDDEN", wide.group(1))

    def test_an_eye_is_saved_at_once(self):
        ui = code("ui.c")
        eye = re.search(r"static void arrange_eye\(lv_event_t \*e\)\s*\{(.*?)\n\}", ui, re.S)
        self.assertIsNotNone(eye)
        self.assertIn("if(!panel_pages_toggle(&page_hidden,page_order[place]))return;", eye.group(1))
        self.assertIn("local.page_hidden=page_hidden;", eye.group(1))
        self.assertIn("save_setting(PANEL_PAGE_HIDDEN,(int)local.page_hidden,true)", eye.group(1))

    def test_a_move_is_saved_at_once(self):
        ui = code("ui.c")
        move = re.search(r"static void arrange_move\(lv_event_t \*e\)\s*\{(.*?)\n\}", ui, re.S)
        self.assertIsNotNone(move)
        self.assertIn("save_setting(PANEL_PAGE_ORDER,(int)local.page_order,true)", move.group(1))
        self.assertIn("local.page_order=panel_pages_pack(page_order)", move.group(1))


if __name__ == "__main__":
    unittest.main()
