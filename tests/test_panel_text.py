# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every word the panel puts on its screen, in each language it offers.

The panel is on a wall and this machine is not, so the whole of this reads
the firmware rather than the board. The compiled part builds the real table
and asks it; the part below it reads the source and needs no compiler, so a
machine with no mbedtls and no cc still refuses German in ui.c.

The two rules that matter are not about wording. A text that is missing in
one language is a null pointer that LVGL follows, and the panel restarts in
front of the person using it. A format string whose %s count differs
between languages reads a value that nobody passed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
HARNESS = os.path.join(REPO, "tests", "c", "panel-text-harness.c")

# The fonts of the panel's text, and the letters of Montserrat that each one
# holds. A letter outside them is not drawn at all, so every text of the
# table is held to them. See panel_fonts.h.
FONT_SIZES = (12, 14, 16, 18, 20, 24, 26, 32)
FONT_FILES = [os.path.join(FIRMWARE, "panel_font_%d.c" % size)
              for size in FONT_SIZES]


def font_letters(path):
    """The letters of Montserrat in one font file, from its "Opts" line.

    lv_font_conv writes the command that made the file at its top. The
    range after the Montserrat face is the one of letters; the range after
    Font Awesome is the symbols.
    """
    with open(path, encoding="utf-8") as handle:
        head = handle.read(4096)
    found = re.search(r"--font Montserrat-Medium\.ttf -r (\S+)", head)
    assert found, "no Montserrat range in %s" % path
    letters = set()
    for part in found.group(1).split(","):
        low, _, high = part.partition("-")
        for code in range(int(low, 16), int(high or low, 16) + 1):
            letters.add(chr(code))
    return letters


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


@unittest.skipUnless(compiler(), "no C compiler here")
class PanelTextTest(unittest.TestCase):
    """The real tables, built and asked."""

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        program = os.path.join(cls.where, "panel-text")
        done = subprocess.run(
            [compiler(), "-Wall", "-Wextra", "-Werror", "-I", FIRMWARE,
             "-o", program, HARNESS,
             os.path.join(FIRMWARE, "panel_text.c")],
            capture_output=True, text=True)
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise unittest.SkipTest("panel_text.c did not build here:\n"
                                    + done.stderr.strip()[:500])
        said = subprocess.run([program], capture_output=True, text=True,
                              timeout=10)
        assert said.returncode == 0, said.stderr
        cls.rows = [line.split("\t", 2) for line in
                    said.stdout.splitlines() if line.count("\t") >= 2]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def table(self, language):
        return {int(row[1]): row[2] for row in self.rows
                if row[0] == str(language)}

    def test_the_languages_hold_the_same_ids(self):
        self.assertEqual(sorted(self.table(0)), sorted(self.table(1)))

    def test_no_text_is_missing_in_any_language(self):
        """A hole in a table is a null pointer that LVGL follows."""
        for language in (0, 1):
            empty = [key for key, value in self.table(language).items()
                     if not value.strip()]
            self.assertEqual(empty, [], "language %d" % language)

    def test_the_format_places_match_between_the_languages(self):
        """One %s more on one side reads a value that nobody passed."""
        english, german = self.table(0), self.table(1)
        for key in english:
            self.assertEqual(re.findall(r"%[a-zA-Z]", english[key]),
                             re.findall(r"%[a-zA-Z]", german[key]),
                             "text %d" % key)

    def test_every_text_stays_inside_the_fonts(self):
        """"Bestätigen" draws, and a letter none of the fonts holds would
        not. A line break is no letter."""
        letters = font_letters(FONT_FILES[0])
        for language in (0, 1):
            for value in self.table(language).values():
                outside = [one for one in value
                           if one != "\n" and one not in letters]
                self.assertEqual(outside, [], value)

    def test_the_german_has_its_own_letters(self):
        """The table once spelt "Bestaetigen", because the fonts had no
        umlaut. The panel shows the German as it is written now."""
        german = " ".join(self.table(1).values())
        for letter in "äöüÄß":
            self.assertIn(letter, german)
        for spelt in ("Bestaetigen", "Zurueck", "oeffnen", "Beruehrung",
                      "ausser", "Tastentoene", "Lautstaerke", "verfuegbar",
                      "Aenderungen", "LAUTSTAERKE", "ueber", "pruefen",
                      "ungueltig", "enthaelt", "Datentraeger", "aeuft",
                      "Maerz"):
            self.assertNotIn(spelt, german)

    def test_an_id_outside_the_table_is_not_a_null_pointer(self):
        outside = [row[2] for row in self.rows if row[0] == "range"]
        self.assertEqual(len(outside), 2)
        for value in outside:
            self.assertNotIn("(null)", value)

    def test_each_language_gives_its_own_name(self):
        names = {row[1]: row[2] for row in self.rows if row[0] == "name"}
        self.assertEqual(names, {"0": "English", "1": "Deutsch"})

    def test_the_two_languages_are_really_different(self):
        """Or the German column is the English one copied across."""
        english, german = self.table(0), self.table(1)
        same = [key for key in english if english[key] == german[key]]
        self.assertLess(len(same), len(english) // 3,
                        "most of the German is the English text")


class NoGermanInTheCodeTest(unittest.TestCase):
    """The words live in one table, and nowhere else.

    This needs no compiler, so it runs on every machine. The firmware came
    with its text written into the screen it draws, and that is the state
    this refuses to go back to.
    """

    WORDS = ("Bitte", "Aenderungen", "Einstellungen", "Lautstaerke",
             "Zurueck", "Abbrechen", "Bestaetigen", "Einrichten",
             "Verbinde", "Tastentoene", "Helligkeit", "Ausschalten",
             "Neustart", "Stumm", "gespeichert", "Lautsprecher",
             "Änderungen", "Lautstärke", "Zurück", "Bestätigen",
             "Tastentöne", "Berührung")

    def source(self, name):
        with open(os.path.join(FIRMWARE, name)) as handle:
            return handle.read()

    def test_the_screen_holds_no_words_of_its_own(self):
        text = self.source("ui.c")
        found = [word for word in self.WORDS if word in text]
        self.assertEqual(found, [], "these belong in panel_text.h")

    def test_the_service_side_holds_none_either(self):
        for name in ("main.c", "config.c"):
            text = self.source(name)
            found = [word for word in self.WORDS if word in text]
            self.assertEqual(found, [], "%s: these belong in panel_text.h"
                             % name)

    def test_english_leads(self):
        """A board with nothing stored answers in English."""
        text = self.source("panel_text.h")
        order = text.index("PANEL_ENGLISH"), text.index("PANEL_GERMAN")
        self.assertLess(*order)
        self.assertIn(".language=PANEL_ENGLISH", self.source("main.c"))

    def test_the_build_carries_both_setup_pages(self):
        cmake = self.source("CMakeLists.txt")
        self.assertIn("panel_text.c", cmake)
        self.assertIn("setup-de.html", cmake)


class FontTest(unittest.TestCase):
    """The text of the panel is drawn with its own fonts, and only those."""

    def source(self, name):
        with open(os.path.join(FIRMWARE, name), encoding="utf-8") as handle:
            return handle.read()

    def test_the_screen_names_no_built_in_font(self):
        """lv_font_montserrat_16 has no ä. One label that names it draws
        "Zurück" as "Zurck"."""
        self.assertNotIn("lv_font_montserrat", self.source("ui.c"))

    def test_a_label_that_names_no_font_gets_a_panel_font(self):
        self.assertRegex(self.source("ui.c"),
                         r"lv_obj_set_style_text_font\(s,&panel_font_16,0\)")

    def test_the_eight_fonts_hold_the_same_letters(self):
        first = font_letters(FONT_FILES[0])
        for path in FONT_FILES[1:]:
            self.assertEqual(font_letters(path), first, path)

    def test_they_hold_the_german_letters_and_no_cedilla(self):
        """The tail of a cedilla goes lower than any other letter, and a
        font that holds it is a line taller. See panel_font_16.c."""
        letters = font_letters(FONT_FILES[0])
        for letter in "ÄÖÜäöüßé°":
            self.assertIn(letter, letters)
        self.assertNotIn("ç", letters)

    def test_every_font_is_in_both_builds(self):
        main = self.source("CMakeLists.txt")
        with open(os.path.join(FIRMWARE, "..", "preview", "CMakeLists.txt"),
                  encoding="utf-8") as handle:
            preview = handle.read()
        for size in FONT_SIZES:
            self.assertIn("panel_font_%d.c" % size, main)
            self.assertIn("panel_font_%d.c" % size, preview)
            self.assertIn("LV_FONT_DECLARE(panel_font_%d)" % size,
                          self.source("panel_fonts.h"))


if __name__ == "__main__":
    unittest.main()
