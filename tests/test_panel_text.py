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
        cls.lines = said.stdout.splitlines()
        cls.rows = [line.split("\t", 2) for line in cls.lines
                    if line.count("\t") >= 2 and not line.startswith("date\t")]

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

    def dates(self):
        """(language, weekday, day, month, room) to what panel_text_date
        wrote."""
        found = {}
        for line in self.lines:
            parts = line.split("\t")
            if parts[0] == "date":
                key = tuple(int(part) for part in parts[1:6])
                found[key] = parts[6] if len(parts) > 6 else ""
        return found

    def test_the_date_reads_as_the_clock_says_it(self):
        """The clock page and the standby screen say it this way."""
        dates = self.dates()
        self.assertEqual(dates[(0, 4, 8, 10, 64)], "Thursday, 8 October")
        self.assertEqual(dates[(1, 4, 8, 10, 64)], "Donnerstag, 8. Oktober")
        self.assertEqual(dates[(1, 1, 3, 3, 64)], "Montag, 3. März")

    def test_the_ends_of_each_range_are_dates(self):
        """Sunday is 0 and January 1, as struct tm counts them."""
        dates = self.dates()
        self.assertEqual(dates[(0, 0, 1, 1, 64)], "Sunday, 1 January")
        self.assertEqual(dates[(0, 6, 31, 12, 64)], "Saturday, 31 December")
        self.assertEqual(dates[(1, 6, 31, 12, 64)], "Samstag, 31. Dezember")

    def test_a_value_out_of_range_is_no_date(self):
        """An empty line rather than the name next to the table."""
        dates = self.dates()
        for language in (0, 1):
            for weekday, day, month in ((-1, 8, 10), (7, 8, 10), (4, 0, 10),
                                        (4, 32, 10), (4, 8, 0), (4, 8, 13)):
                with self.subTest(language=language, weekday=weekday,
                                  day=day, month=month):
                    self.assertEqual(
                        dates[(language, weekday, day, month, 64)], "")

    def test_the_date_ends_inside_its_room(self):
        dates = self.dates()
        self.assertEqual(dates[(0, 4, 8, 10, 9)], "Thursday")
        self.assertEqual(dates[(0, 4, 8, 10, 1)], "")

    def test_the_two_languages_are_really_different(self):
        """Or the German column is the English one copied across."""
        english, german = self.table(0), self.table(1)
        same = [key for key in english if english[key] == german[key]]
        self.assertLess(len(same), len(english) // 3,
                        "most of the German is the English text")


def lvgl_bytes(first):
    """The bytes of a character by its first byte, as LVGL counts them.

    lv_text_encoded_size in LVGL 9.5. Nought for a byte that starts no
    character, which LVGL then steps over as one byte.
    """
    if first < 0x80:
        return 1
    if first & 0xE0 == 0xC0:
        return 2
    if first & 0xF0 == 0xE0:
        return 3
    if first & 0xF8 == 0xF0:
        return 4
    return 0


def lvgl_walk_stays_inside(text):
    """Whether LVGL stays inside the text when it steps from character to
    character (lv_text_utf8_get_byte_id). It steps by the first byte alone."""
    at = 0
    while at < len(text):
        at += lvgl_bytes(text[at]) or 1
    return at == len(text)


def whole_reference(text, size):
    """What panel_text_whole must give: (same, bytes)."""
    def whole_at(at):
        count = lvgl_bytes(text[at])
        if not count or at + count > len(text):
            return 0
        if any(byte & 0xC0 != 0x80 for byte in text[at + 1:at + count]):
            return 0
        return count

    at, clean = 0, True
    while at < len(text):
        step = whole_at(at)
        if not step:
            clean = False
            break
        at += step
    if clean:
        return True, text
    if size == 0:
        return False, b""
    out, at = bytearray(), 0
    while at < len(text):
        step = whole_at(at)
        if step:
            if len(out) + step >= size:
                break
            out += text[at:at + step]
            at += step
            continue
        rest = 1
        while at + rest < len(text) and text[at + rest] & 0xC0 == 0x80:
            rest += 1
        if at + rest == len(text) and rest < lvgl_bytes(text[at]):
            break
        if len(out) + 1 >= size:
            break
        out.append(ord("?"))
        at += 1
    return False, bytes(out)


@unittest.skipUnless(compiler(), "no C compiler here")
class WholeTextTest(unittest.TestCase):
    """A text for a label has whole characters only.

    The PC sends a name in UTF-8, and a field of the state cuts a long name
    at a byte. LVGL counts the bytes of a character by its first byte. So a
    cut character at the end of a label took LVGL past the end of the text:
    a read past the memory of the label, found with a random walk over the
    screen and AddressSanitizer.
    """

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-text")
        done = subprocess.run(
            [compiler(), "-Wall", "-Wextra", "-Werror", "-I", FIRMWARE,
             "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_text.c")],
            capture_output=True, text=True)
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise unittest.SkipTest("panel_text.c did not build here:\n"
                                    + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def ask(self, cases):
        """[(same, whole, bytes)] for each (text, size)."""
        lines = "".join("%d %s\n" % (size, text.hex())
                        for text, size in cases)
        said = subprocess.run([self.program, "whole"], input=lines,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(said.returncode, 0, said.stderr)
        out = []
        for line in said.stdout.splitlines():
            same, whole, got = line.split("\t")
            out.append((same == "same", whole == "1", bytes.fromhex(got)))
        self.assertEqual(len(out), len(cases))
        return out

    def test_a_whole_text_stays_as_it_is(self):
        for text in ("", "Steam", "Grüße aus Köln", "日本語 → €", "😀 4 bytes"):
            with self.subTest(text=text):
                raw = text.encode("utf-8")
                # With no room at all: a whole text needs none.
                self.assertEqual(self.ask([(raw, 0)]), [(True, True, raw)])

    def test_a_character_that_the_end_cuts_goes(self):
        """What snprintf leaves of a long name, for each length of a
        character."""
        for text, wanted in ((b"Gr\xc3", b"Gr"), (b"a\xe2\x82", b"a"),
                             (b"a\xe2", b"a"), (b"a\xf0\x9f\x98", b"a"),
                             (b"a\xf0\x9f", b"a"), (b"a\xf0", b"a"),
                             (b"\xc3", b""),
                             ("Köln ".encode() + b"\xe6\x97", "Köln ".encode())):
            with self.subTest(text=text):
                self.assertEqual(self.ask([(text, 64)]),
                                 [(False, False, wanted)])

    def test_a_byte_that_starts_no_character_shows_as_a_question_mark(self):
        for text, wanted in ((b"Pok\xe9mon", b"Pok?mon"), (b"a\x80b", b"a?b"),
                             (b"a\xffb", b"a?b"), (b"a\xc3b", b"a?b"),
                             (b"\xe2\x82X", b"??X"), (b"\xf8\x88", b"??")):
            with self.subTest(text=text):
                self.assertEqual(self.ask([(text, 64)]),
                                 [(False, False, wanted)])

    def test_the_copy_ends_inside_its_room_and_on_a_whole_character(self):
        text = b"\xff" + "ää€".encode()            # 1 + 2 + 2 + 3 bytes
        wanted = {1: b"", 2: b"?", 3: b"?", 4: "?ä".encode(),
                  5: "?ä".encode(), 6: "?ää".encode(), 8: "?ää".encode(),
                  9: "?ää€".encode(), 64: "?ää€".encode()}
        for size, out in wanted.items():
            with self.subTest(size=size):
                self.assertEqual(self.ask([(text, size)]),
                                 [(False, False, out)])
        self.assertEqual(self.ask([(text, 0)]), [(False, False, b"")])

    def test_each_text_of_random_bytes_is_safe_for_lvgl(self):
        """3000 texts of random bytes and of cut UTF-8, against the rules in
        Python: the same answer, inside the room, and LVGL stays inside."""
        import random
        chance = random.Random(4)
        letters = ["a", "Z", " ", "ä", "ß", "€", "日", "😀", "→"]
        cases = []
        for number in range(3000):
            if number % 3 == 0:
                raw = bytes(chance.randrange(1, 256)
                            for _ in range(chance.randrange(0, 40)))
            else:
                raw = "".join(chance.choice(letters) for _ in range(
                    chance.randrange(0, 30))).encode("utf-8")
                raw = raw[:chance.randrange(0, len(raw) + 1)]
                if number % 3 == 2 and raw:
                    at = chance.randrange(len(raw))
                    raw = raw[:at] + bytes([chance.randrange(128, 256)]) \
                        + raw[at:]
            cases.append((raw, chance.choice((1, 2, 3, 5, 8, 16, 48, 128))))
        cut = 0
        for (raw, size), (same, whole, got) in zip(cases, self.ask(cases)):
            wanted_same, wanted = whole_reference(raw, size)
            self.assertEqual((same, got), (wanted_same, wanted), (raw, size))
            self.assertEqual(whole, wanted_same, raw)
            self.assertTrue(lvgl_walk_stays_inside(got), (raw, got))
            self.assertLessEqual(len(got), max(len(raw), 0))
            if not same:
                self.assertLess(len(got), size)
                cut += 1
        # The cases are no walk in the park: many are not whole.
        self.assertGreater(cut, 1000)

    def test_the_screen_sends_each_text_through_it(self):
        """The two doors of ui.c for the text of a label. check_pages holds
        the labels themselves, on each page."""
        with open(os.path.join(FIRMWARE, "ui.c"), encoding="utf-8") as handle:
            source = handle.read()
        for door in ("static lv_obj_t *text_at(", "static void set_text("):
            body = source[source.index(door):]
            body = body[:body.index("\n}\n")]
            self.assertIn("panel_text_whole(text,whole,sizeof whole)", body, door)


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
             "Tastentöne", "Berührung", "Daten zu lang", "fehlgeschlagen")

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

    def test_a_text_of_the_table_alone_is_no_format(self):
        """A text with a per cent sign, as the format of snprintf with no
        argument after it, reads an argument that is not there."""
        alone = re.compile(
            r"snprintf\(\s*[^,;]+,\s*[^,;]+,\s*panel_text\(\w+\)\s*\)\s*;")
        for name in ("main.c", "config.c", "ui.c"):
            self.assertEqual(alone.findall(self.source(name)), [], name)

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
