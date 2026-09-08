# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalogue page against the effects it is a catalogue of.

docs/index.html is served at github.io and is the page a person is sent to
before they own the hardware. It holds a card for each effect, with the
numbers of that effect written into it.

Nothing tied the page to the code. A new effect in render.py reached the
panel, the config and the README by itself, because each of those reads
RAINBOW_CHOICES. The page did not, and a catalogue that is missing the newest
entry looks complete: there is no gap to see.
"""

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))

from steamos_utility_center import render                   # noqa: E402

PAGE = os.path.join(HERE, "..", "docs", "index.html")
CLIPS = os.path.join(HERE, "..", "docs", "effects.json")


def _page():
    with open(PAGE, encoding="utf-8") as handle:
        return handle.read()


def _cards(text):
    """Every card on the page, as (id, clip). Read from the source, because
    the page builds itself in the browser and there is no browser here.
    """
    found = []
    for card in re.finditer(r'\bid: "([a-z_]+)", name: "', text):
        rest = text[card.end():card.end() + 400]
        clip = re.search(r'\bclip: "([a-z_0-9]+)"', rest)
        found.append((card.group(1), clip.group(1) if clip else ""))
    return found


class CatalogueTest(unittest.TestCase):

    def setUp(self):
        self.text = _page()
        self.cards = _cards(self.text)

    def test_it_found_the_cards_at_all(self):
        """A change to the shape of the page must not turn this file into a
        test that passes because it reads nothing."""
        self.assertGreater(len(self.cards), 15, self.cards)

    def test_every_effect_of_the_slot_has_a_card(self):
        named = set(one for one, _clip in self.cards)
        for effect in render.RAINBOW_CHOICES:
            self.assertIn(effect, named,
                          "%s is an effect the rainbow slot offers and the "
                          "catalogue does not name it" % effect)

    def test_every_card_names_a_clip_that_exists(self):
        with open(CLIPS, encoding="utf-8") as handle:
            clips = json.load(handle)["clips"]
        for name, clip in self.cards:
            self.assertTrue(clip, "%s names no clip" % name)
            # patrol has one clip for each number of dots, and the page picks
            # between them. The others name their clip outright.
            if clip in clips or ("%s_1" % clip) in clips:
                continue
            self.fail("%s names the clip %r, which effects.json does not have"
                      % (name, clip))


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
