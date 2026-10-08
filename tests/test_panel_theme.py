# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The colours of the wall panel: a dark theme, a light one, eight accents.

Asked for: a light theme beside the dark one, and the accent colour of the
sliders and the switches to choose, out of eight colours that make sense.

firmware/companion/main/panel_theme.c holds every colour of the screen, and
the harness in tests/c/panel-theme-harness.c asks it here. The rules below
are about what a person sees: every colour that words stand on reads as
words, a face in the accent stands off its card, the eight accents are told
apart from each other and from the words that name a value, and the dark
theme in its blue is the panel as it was before there was a choice.
firmware/companion/preview/check_pages.c holds each label of each page to
the same contrast on the screen itself, in each theme and each accent.

Contrast is the ratio of WCAG 2: 4.5 for words, 3 for large words and for
a face that has to be seen. Colour difference is CIE76 in L*a*b*, where 2
is about the least an eye tells apart and 20 is plainly another colour.
"""

from __future__ import annotations

import colorsys
import itertools
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
PREVIEW = os.path.join(REPO, "firmware", "companion", "preview")
HARNESS = os.path.join(REPO, "tests", "c", "panel-theme-harness.c")

THEMES = 2
ACCENTS = 8

# The colours of the screen before there was a choice, as ui.c wrote them.
# The rim of a knob in the colour of the knob is no rim: ui.c draws none.
AS_IT_WAS = {
    "bg": 0x0C1721, "card": 0x111F2B, "edge": 0x293D51, "text": 0xEDF4FC,
    "muted": 0xAEC4DE, "button": 0x1B2B3C, "accent": 0x49A8F7,
    "accent_text": 0x49A8F7, "on_accent": 0x0C1721, "knob": 0xEDF4FC,
    "knob_edge": 0xEDF4FC, "slider_knob": 0xEDF4FC, "red": 0xF06B79, "danger": 0x2C202B,
    "danger_edge": 0xA54757, "online": 0x70C256, "offline": 0x60758A,
    "curve_cpu": 0x49A8F7, "curve_gpu": 0xF5A25D, "curve_watts": 0x70C256,
}


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def code(name):
    """A source file of the firmware, with no comments in it."""
    text = read(os.path.join(FIRMWARE, name))
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def channel(value):
    value /= 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    return (0.2126 * channel(rgb >> 16 & 255) + 0.7152 * channel(rgb >> 8 & 255)
            + 0.0722 * channel(rgb & 255))


def contrast(a, b):
    high, low = sorted((luminance(a) + 0.05, luminance(b) + 0.05), reverse=True)
    return high / low


def lab(rgb):
    red, green, blue = (channel(rgb >> shift & 255) for shift in (16, 8, 0))
    x = (0.4124 * red + 0.3576 * green + 0.1805 * blue) / 0.95047
    y = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    z = (0.0193 * red + 0.1192 * green + 0.9505 * blue) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def difference(a, b):
    return sum((p - q) ** 2 for p, q in zip(lab(a), lab(b))) ** 0.5


def hue(rgb):
    return 360 * colorsys.rgb_to_hls((rgb >> 16 & 255) / 255, (rgb >> 8 & 255) / 255,
                                     (rgb & 255) / 255)[0]


@unittest.skipUnless(compiler(), "no C compiler here")
class PaletteTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-theme")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_theme.c"),
             os.path.join(FIRMWARE, "panel_led.c"),
             os.path.join(FIRMWARE, "panel_text.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the files are plain C, so a build that
        # fails is a fault in them.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_theme.c did not build here:\n"
                                 + done.stderr.strip()[:500])
        commands = ["palette %d %d" % pair
                    for pair in itertools.product(range(THEMES), range(ACCENTS))]
        cls.palettes = {}
        for command, answer in zip(commands, cls.ask_program(*commands)):
            theme, accent = map(int, command.split()[1:])
            cls.palettes[theme, accent] = cls.colours(answer)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    @classmethod
    def ask_program(cls, *commands):
        done = subprocess.run([cls.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        return done.stdout.splitlines()

    @staticmethod
    def colours(answer):
        return {name: int(value, 16) for name, value in
                (pair.split("=") for pair in answer.split())}

    def ask(self, *commands):
        return self.ask_program(*commands)

    def each(self):
        for (theme, accent), palette in sorted(self.palettes.items()):
            yield "theme %d, accent %d" % (theme, accent), palette

    def test_two_themes_and_eight_accents(self):
        self.assertEqual(self.ask("size"), ["%d %d" % (THEMES, ACCENTS)])

    def test_the_dark_theme_in_blue_is_the_panel_as_it_was(self):
        self.assertEqual(self.palettes[0, 0], AS_IT_WAS)

    def test_a_number_outside_the_lists_is_the_dark_theme_or_blue(self):
        """A stored number of a later firmware, or of nobody."""
        for theme, accent in ((-1, 0), (2, 0), (99, 0), (0, -1), (0, 8), (0, 255), (7, 99)):
            self.assertEqual(self.colours(self.ask("palette %d %d" % (theme, accent))[0]),
                             self.palettes[0, 0], (theme, accent))
        # A theme that is there keeps its colours, in blue.
        self.assertEqual(self.colours(self.ask("palette 1 8")[0]), self.palettes[1, 0])

    def test_words_read_on_what_they_stand_on(self):
        for where, p in self.each():
            for ground in ("bg", "card", "button"):
                self.assertGreaterEqual(contrast(p["text"], p[ground]), 7, (where, ground))
                self.assertGreaterEqual(contrast(p["muted"], p[ground]), 4.5, (where, ground))
            # A value in the accent stands on a card, and the choice in a
            # list or a window of the history on a button.
            for ground in ("card", "button"):
                self.assertGreaterEqual(contrast(p["accent_text"], p[ground]), 4.5,
                                        (where, ground))
            # The title of the setup, in large words on the page.
            self.assertGreaterEqual(contrast(p["accent_text"], p["bg"]), 3, where)
            # "Confirm", the profile of the CPU that runs, the tick of the
            # accent that is chosen.
            self.assertGreaterEqual(contrast(p["on_accent"], p["accent"]), 4.5, where)
            # Switch off, a full drive, no network, an update that failed.
            for ground in ("bg", "card", "danger"):
                self.assertGreaterEqual(contrast(p["red"], p[ground]), 4.5, (where, ground))

    def test_a_face_in_the_accent_stands_off_its_card(self):
        """A bar, the track of a switch that is on, the round button of an
        accent, and the knob of a slider."""
        for where, p in self.each():
            self.assertGreaterEqual(contrast(p["accent"], p["card"]), 3, where)
            self.assertGreaterEqual(contrast(p["slider_knob"], p["card"]), 3, where)

    def test_a_knob_is_seen_on_its_track(self):
        for where, p in self.each():
            # On: the knob on the accent. White on yellow is the least of
            # them, and still a knob.
            self.assertGreaterEqual(contrast(p["knob"], p["accent"]), 1.4, where)
            # Off, and greyed: the knob against its track, or its rim
            # against the knob where the two are pale.
            self.assertGreaterEqual(max(contrast(p["knob"], p["edge"]),
                                        contrast(p["knob_edge"], p["knob"])), 2, where)

    def test_the_light_theme_stands_apart_as_the_dark_one_does(self):
        """The border of a card off the card, and a button off its card."""
        dark, light = self.palettes[0, 0], self.palettes[1, 0]
        for part in ("edge", "button"):
            self.assertAlmostEqual(contrast(light[part], light["card"]),
                                   contrast(dark[part], dark["card"]), delta=0.1)
        self.assertGreater(luminance(light["bg"]), luminance(dark["text"]) / 2)

    def test_the_eight_are_told_apart(self):
        for theme in range(THEMES):
            for part in ("accent", "accent_text"):
                tones = [self.palettes[theme, accent][part] for accent in range(ACCENTS)]
                for a, b in itertools.combinations(range(ACCENTS), 2):
                    self.assertGreaterEqual(difference(tones[a], tones[b]), 20,
                                            (theme, part, a, b))

    def test_a_value_does_not_look_like_its_name(self):
        """A reading in the accent beside the muted words that name it."""
        for where, p in self.each():
            self.assertGreaterEqual(difference(p["accent_text"], p["muted"]), 20, where)
            self.assertGreaterEqual(difference(p["accent_text"], p["text"]), 20, where)

    def test_the_row_goes_once_round_the_colour_circle(self):
        """From the blue the panel always had, a step down the circle each."""
        for theme in range(THEMES):
            hues = [hue(self.palettes[theme, accent]["accent"]) for accent in range(ACCENTS)]
            steps = [(hues[i] - hues[(i + 1) % ACCENTS]) % 360 for i in range(ACCENTS)]
            self.assertTrue(all(0 < step < 120 for step in steps), (theme, steps))
            self.assertAlmostEqual(sum(steps), 360, delta=0.01)

    def test_the_curves_read_and_keep_their_colours(self):
        """A curve in the accent could be the curve of the card beside it."""
        for theme in range(THEMES):
            first = self.palettes[theme, 0]
            curves = [first[name] for name in ("curve_cpu", "curve_gpu", "curve_watts")]
            for curve in curves:
                self.assertGreaterEqual(contrast(curve, first["card"]), 3, theme)
            for a, b in itertools.combinations(curves, 2):
                self.assertGreaterEqual(difference(a, b), 40, theme)
            for accent in range(ACCENTS):
                p = self.palettes[theme, accent]
                self.assertEqual([p[name] for name in ("curve_cpu", "curve_gpu", "curve_watts")],
                                 curves)

    def test_only_the_accent_follows_the_accent(self):
        mine = {"accent", "accent_text", "on_accent", "slider_knob"}
        for theme in range(THEMES):
            first = self.palettes[theme, 0]
            for accent in range(ACCENTS):
                for name, value in self.palettes[theme, accent].items():
                    if name not in mine:
                        self.assertEqual(value, first[name], (theme, accent, name))

    def test_the_accents_are_the_colours_of_the_led_bar_without_its_white(self):
        accents = [int(n) for n in self.ask(*["accent %d" % a for a in range(ACCENTS)])]
        leds = [int(n) for n in self.ask(*["led %d" % i for i in range(9)])]
        names = self.ask(*["text %d" % n for n in accents])
        self.assertEqual(names, ["Blue", "Cyan", "Green", "Yellow", "Orange", "Red",
                                 "Magenta", "Purple"])
        white = leds[self.ask(*["text %d" % n for n in leds]).index("White")]
        self.assertEqual(sorted(accents), sorted(set(leds) - {white}))
        themes = [int(n) for n in self.ask("theme 0", "theme 1")]
        self.assertEqual(self.ask(*["text %d" % n for n in themes]), ["Dark", "Light"])

    def test_the_sleeping_clock_wears_the_dark_theme(self):
        """The cover is black in either theme: see panel_ui_sleep.c."""
        sleep = code("panel_ui_sleep.c")
        for name, part in (("CLOCK_TIME_COLOUR", "text"), ("CLOCK_DATE_COLOUR", "muted")):
            found = re.search(r"#define %s 0x([0-9A-Fa-f]{6})" % name, sleep)
            self.assertIsNotNone(found, name)
            self.assertEqual(int(found.group(1), 16), self.palettes[0, 0][part], name)


class StorageTest(unittest.TestCase):
    """The choice is stored as two small numbers, and read with care."""

    def test_a_panel_with_nothing_stored_is_dark_and_blue(self):
        main = code("main.c")
        self.assertIn(".theme=PANEL_THEME_DARK", main)
        self.assertIn(".accent=PANEL_ACCENT_BLUE", main)

    def test_a_stored_number_outside_the_lists_is_not_read(self):
        main = code("main.c")
        self.assertIn('nvs_get_u8(h,"theme",&value)==ESP_OK && value<PANEL_THEMES', main)
        self.assertIn('nvs_get_u8(h,"accent",&value)==ESP_OK && value<PANEL_ACCENTS', main)

    def test_both_are_stored_as_small_numbers(self):
        main = code("main.c")
        self.assertIn('key==PANEL_THEME?"theme"', main)
        self.assertIn('key==PANEL_ACCENT?"accent"', main)
        wide = re.search(r"bool wide=([^;]*);", main)
        self.assertIsNotNone(wide)
        self.assertNotIn("PANEL_THEME", wide.group(1))
        self.assertNotIn("PANEL_ACCENT", wide.group(1))

    def test_a_choice_is_saved_at_once(self):
        ui = code("ui.c")
        for handler, key, field in (("theme_clicked", "PANEL_THEME", "theme"),
                                    ("accent_clicked", "PANEL_ACCENT", "accent")):
            body = re.search(r"static void %s\(lv_event_t \*e\)\s*\{(.*?)\n\}" % handler, ui, re.S)
            self.assertIsNotNone(body, handler)
            self.assertIn("local.%s=%s;" % (field, field), body.group(1))
            self.assertIn("save_setting(%s,(int)%s,true)" % (key, field), body.group(1))
            self.assertIn("appearance_again();", body.group(1))


class ScreenTest(unittest.TestCase):
    """Every colour of the screen comes out of panel_theme.c."""

    def test_the_screen_has_no_colour_of_its_own(self):
        """A colour written into ui.c is a colour of one theme on both."""
        ui = code("ui.c")
        self.assertEqual(re.findall(r"0x[0-9A-Fa-f]{6}\b", ui), [])
        for call in ("lv_color_white", "lv_color_black", "lv_palette_"):
            self.assertNotIn(call, ui)

    def test_the_colours_are_taken_before_anything_is_built(self):
        ui = code("ui.c")
        create = ui.index("void panel_ui_create(")
        taken = ui.index("palette=panel_palette(local.theme,local.accent);", create)
        self.assertLess(taken, ui.index("lv_obj_clean(s);", create))

    def test_both_builds_carry_the_colours(self):
        self.assertIn('"panel_theme.c"', read(os.path.join(FIRMWARE, "CMakeLists.txt")))
        self.assertIn("../main/panel_theme.c", read(os.path.join(PREVIEW, "CMakeLists.txt")))


if __name__ == "__main__":
    unittest.main()
