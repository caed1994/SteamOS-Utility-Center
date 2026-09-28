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

# The fonts built into the firmware are a subset of Montserrat. A character
# outside it draws as an empty box, so the German is written as "Bestaetigen"
# and not "Bestätigen". Degree and the ASCII range are what the panel uses.
ALLOWED_OUTSIDE_ASCII = "°"


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

    def test_the_german_stays_inside_the_font(self):
        """"Bestaetigen" and not "Bestätigen". See ALLOWED_OUTSIDE_ASCII."""
        for value in self.table(1).values():
            outside = [one for one in value
                       if ord(one) > 127 and one not in ALLOWED_OUTSIDE_ASCII]
            self.assertEqual(outside, [], value)

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
             "Neustart", "Stumm", "gespeichert", "Lautsprecher")

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


if __name__ == "__main__":
    unittest.main()
