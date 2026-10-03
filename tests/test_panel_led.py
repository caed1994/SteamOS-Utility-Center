# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The effects of the page of the LED bar on the wall panel.

The panel keeps two lists of effects in panel_led.c, and the LED service
keeps the same two in its code. These tests hold them equal. An effect
that the service learns is then a failing test until the panel has it
too. The panel never sends an effect that the service does not know,
because the companion service refuses such a change.

The page also sets the colour and the brightness of the desktop scenes.
The colours of panel_led.c are held equal to the colours that the
companion service takes, and each change the panel builds goes through
the service in these tests.

The functions of panel_led.c run on the machine of the tests through a
small harness, as the functions of panel_pages.c do.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
PREVIEW = os.path.join(REPO, "firmware", "companion", "preview")
HARNESS = os.path.join(REPO, "tests", "c", "panel-led-harness.c")
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import companion, desktop, render  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def code(name):
    """A source file of the firmware, with no comments in it."""
    text = read(os.path.join(FIRMWARE, name))
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def effects(name):
    """The entries of one list of panel_led.c: (key, text, coloured,
    lit)."""
    found = re.search(r"static const effect_t %s\[\] = \{(.*?)\};" % name,
                      code("panel_led.c"), re.S)
    assert found, name
    return re.findall(r'\{"(\w+)", (TXT_\w+), (true|false), (true|false)\}',
                      found.group(1))


def colours():
    """The colours of panel_led.c: (colour, text)."""
    found = re.search(r"\} colours\[PANEL_LED_COLOURS\] = \{(.*?)\};",
                      code("panel_led.c"), re.S)
    assert found
    return re.findall(r'\{"(#[0-9a-f]{6})", (TXT_\w+)\}', found.group(1))


def number(name, text):
    found = re.search(r"#define %s (\d+)" % name, text)
    assert found, name
    return int(found.group(1))


class ListsTest(unittest.TestCase):
    """The two lists of the panel against the two of the service."""

    def test_the_desktop_list_is_the_list_of_the_service(self):
        self.assertEqual([key for key, _, _, _ in effects("desktop")],
                         list(desktop.SCENES))

    def test_the_game_mode_list_is_the_rainbow_slot_of_the_service(self):
        self.assertEqual([key for key, _, _, _ in effects("game")],
                         list(render.RAINBOW_CHOICES))

    def test_the_lists_are_what_the_service_takes_for_each_mode(self):
        """A change from the page goes to the setting of its mode."""
        self.assertEqual(companion.LED_CHOICES["desktop"][1], desktop.SCENES)
        self.assertEqual(companion.LED_CHOICES["game"][1],
                         render.RAINBOW_CHOICES)

    def test_the_effects_in_the_desktop_colour_are_marked(self):
        self.assertEqual(
            {key for key, _, coloured, _ in effects("desktop")
             if coloured == "true"},
            set(desktop.SCENES_WITH_COLOUR))
        self.assertEqual(
            [key for key, _, coloured, _ in effects("game")
             if coloured == "true"], [])

    def test_the_effects_in_the_desktop_brightness_are_marked(self):
        """Steam sets the brightness in Game Mode, so the page offers it
        for no effect of that list."""
        self.assertEqual(
            {key for key, _, _, lit in effects("desktop") if lit == "true"},
            set(desktop.SCENES_LIT))
        self.assertEqual(
            [key for key, _, _, lit in effects("game") if lit == "true"], [])

    def test_one_effect_has_one_name_in_both_lists(self):
        names = {}
        for key, text, _, _ in effects("desktop") + effects("game"):
            self.assertEqual(names.setdefault(key, text), text, key)
        self.assertEqual(len(set(names.values())), len(names))

    def test_each_name_is_in_the_table_of_the_texts(self):
        table = read(os.path.join(FIRMWARE, "panel_text.h"))
        for _, text, _, _ in effects("desktop") + effects("game"):
            self.assertRegex(table, r"X\(%s," % text)

    def test_the_colours_are_the_colours_the_service_takes(self):
        self.assertEqual(tuple(colour for colour, _ in colours()),
                         companion.LED_COLOURS)
        self.assertEqual(number("PANEL_LED_COLOURS", code("panel_led.h")),
                         len(companion.LED_COLOURS))

    def test_each_colour_has_a_name_of_its_own(self):
        table = read(os.path.join(FIRMWARE, "panel_text.h"))
        texts = [text for _, text in colours()] + ["TXT_COLOUR_OWN"]
        self.assertEqual(len(set(texts)), len(texts))
        for text in texts:
            self.assertRegex(table, r"X\(%s," % text)

    def test_the_room_for_a_colour_holds_one(self):
        self.assertGreater(number("PANEL_LED_COLOUR", code("panel_led.h")),
                           len("#rrggbb"))

    def test_the_keys_of_the_colour_and_the_brightness_are_the_services(self):
        header = code("panel_led.h")
        keys = re.findall(
            r'#define PANEL_LED_(?:COLOUR|BRIGHTNESS)_KEY "(\w+)"', header)
        self.assertEqual(sorted(keys), sorted(companion.LED_LOOK))

    def test_the_room_for_a_key_holds_the_longest_one(self):
        longest = max(len(key) for key in desktop.SCENES
                      + render.RAINBOW_CHOICES)
        self.assertGreater(number("PANEL_LED_KEY", code("panel_led.h")),
                           longest)


class RequestTest(unittest.TestCase):
    """What the panel sends, against what the companion service reads."""

    def test_the_two_sides_name_the_same_path(self):
        self.assertIn('#define PANEL_LED_PATH "%s"' % companion.LED_PATH,
                      code("main.c"))

    def test_the_status_is_read_and_the_change_built_in_one_place(self):
        """The names of the modes are in panel_led.c alone. The harness
        below holds them to the service."""
        main = code("main.c")
        self.assertIn("panel_led_mode_name((panel_led_mode_t)mode)", main)
        self.assertIn("panel_led_body(body,sizeof(body),change)", main)

    def test_a_service_without_the_page_is_told_from_a_pc_without_a_bar(self):
        """No key at all is a service older than the firmware, and null
        is a PC with no LED module. companion.status sends the second."""
        main = code("main.c")
        self.assertIn("state.led_known=led!=NULL;", main)
        self.assertIn("state.led_here=cJSON_IsObject(led);", main)
        with unittest.mock.patch.object(companion.modules, "installed",
                                        return_value=False):
            self.assertIsNone(companion.led())

    def test_the_status_of_the_colour_and_the_brightness_is_read(self):
        """With the names of panel_led.h, and only when both are there and
        right: a service older than the firmware sends neither."""
        main = code("main.c")
        self.assertIn(
            "cJSON_GetObjectItemCaseSensitive(led,PANEL_LED_COLOUR_KEY)", main)
        self.assertIn(
            "cJSON_GetObjectItemCaseSensitive(led,PANEL_LED_BRIGHTNESS_KEY)",
            main)
        self.assertIn("state.led_look=cJSON_IsString(colour)", main)

    def test_the_largest_change_fits_the_body_on_both_sides(self):
        longest = max(desktop.SCENES + render.RAINBOW_CHOICES, key=len)
        body = json.dumps(dict({mode: longest
                                for mode in companion.LED_CHOICES},
                               desktop_color="#ffffff",
                               desktop_brightness=255),
                          separators=(",", ":"))
        self.assertLessEqual(len(body), companion.BODY_LIMIT)
        found = re.search(r"static int led_request\(.*?char body\[(\d+)\];",
                          code("main.c"), re.S)
        self.assertIsNotNone(found)
        self.assertLess(len(body), int(found.group(1)))

    def test_a_change_waits_longer_for_its_answer_than_a_poll(self):
        """The service answers once the LED service runs again with the
        new file."""
        main = code("main.c")
        self.assertGreater(number("PANEL_CHANGE_WAIT_MS", main),
                           number("PANEL_ASK_MS", main))

    def test_both_builds_carry_the_file(self):
        self.assertIn('"panel_led.c"',
                      read(os.path.join(FIRMWARE, "CMakeLists.txt")))
        self.assertIn("../main/panel_led.c",
                      read(os.path.join(PREVIEW, "CMakeLists.txt")))


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


@unittest.skipUnless(compiler(), "no C compiler here")
class HarnessTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-led")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_led.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_led.c did not build here:\n"
                                 + done.stderr.strip()[:500])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def ask(self, *commands):
        done = subprocess.run([self.program], input="\n".join(commands) + "\n",
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def test_each_key_is_found_at_its_place(self):
        for mode, keys in enumerate((desktop.SCENES, render.RAINBOW_CHOICES)):
            self.assertEqual(self.ask("count %d" % mode), [str(len(keys))])
            self.assertEqual(
                self.ask(*["key %d %d" % (mode, i) for i in range(len(keys))]),
                list(keys))
            self.assertEqual(
                self.ask(*["find %d %s" % (mode, key) for key in keys]),
                [str(i) for i in range(len(keys))])

    def test_a_key_of_another_list_or_service_is_not_found(self):
        self.assertEqual(self.ask("find 1 off", "find 1 steam",
                                  "find 0 plasma", "find 2 fire"),
                         ["-1"] * 4)

    def test_a_place_outside_a_list_has_no_key(self):
        count = len(desktop.SCENES)
        self.assertEqual(self.ask("key 0 -1", "key 0 %d" % count, "key 2 0"),
                         ["(none)"] * 3)

    def test_a_step_goes_round_the_ends(self):
        last = len(desktop.SCENES) - 1
        self.assertEqual(
            self.ask("step 0 0 1", "step 0 %d 1" % last, "step 0 0 -1",
                     "step 0 3 -1"),
            ["1", "0", str(last), "2"])
        last = len(render.RAINBOW_CHOICES) - 1
        self.assertEqual(self.ask("step 1 %d 1" % last, "step 1 0 -1"),
                         ["0", str(last)])

    def test_an_effect_the_panel_does_not_know_steps_to_an_end(self):
        """The effect of a later service: a step forward goes to the first
        effect, and a step back to the last."""
        last = len(desktop.SCENES) - 1
        self.assertEqual(self.ask("step 0 -1 1", "step 0 -1 -1",
                                  "step 0 99 1"),
                         ["0", str(last), "0"])
        self.assertEqual(self.ask("step 2 0 1"), ["-1"])

    def test_the_modes_are_named_as_the_service_names_them(self):
        self.assertEqual(self.ask("mode 0", "mode 1"),
                         list(companion.LED_CHOICES))
        self.assertEqual(self.ask("mode 2", "mode -1"), ["(none)"] * 2)

    def test_every_change_the_panel_builds_is_one_the_service_takes(self):
        """Each pair of effects, and each effect alone, through the
        companion service with a writer that keeps what reached it."""
        pairs = [(one, other) for one in desktop.SCENES + ("-",)
                 for other in render.RAINBOW_CHOICES + ("-",)]
        answers = self.ask(*["body 96 %s %s" % pair for pair in pairs])
        for (one, other), answer in zip(pairs, answers):
            body, length = answer.rsplit(" ", 1)
            if one == other == "-":
                self.assertEqual((body, length), ("(empty)", "0"))
                continue
            self.assertEqual(int(length), len(body))
            wanted = {}
            if one != "-":
                wanted["desktop"] = one
            if other != "-":
                wanted["game"] = other
            self.assertEqual(json.loads(body), wanted)
            self.assertLessEqual(len(body), companion.BODY_LIMIT)
            wrote = []
            code_, _ = companion.led_change(json.loads(body),
                                            write=wrote.append)
            self.assertEqual(code_, 200, body)
            self.assertEqual(wrote, [{companion.LED_CHOICES[mode][0]: value
                                      for mode, value in wanted.items()}])

    def test_a_body_with_no_room_is_no_body(self):
        """Never half an object: the service would refuse it, and the
        page would show a refusal for a change that never went."""
        whole = self.ask("body 96 temperature temperature")[0]
        size = len(whole.rsplit(" ", 1)[0])
        self.assertEqual(self.ask("body %d temperature temperature" % size,
                                  "body 2 fire -", "body 0 fire -"),
                         ["(empty) 0"] * 3)
        self.assertEqual(self.ask("body %d temperature temperature"
                                  % (size + 1)), [whole])

    def test_each_colour_is_found_at_its_place(self):
        count = len(companion.LED_COLOURS)
        self.assertEqual(self.ask(*["colour %d" % i for i in range(count)]),
                         list(companion.LED_COLOURS))
        self.assertEqual(
            self.ask(*["colourfind %s" % colour
                       for colour in companion.LED_COLOURS]),
            [str(i) for i in range(count)])
        # The service sends "#rrggbb" in small letters, and a colour of the
        # file that is no colour of the list is no place.
        self.assertEqual(self.ask("colourfind #FF0000", "colourfind #25d366",
                                  "colourfind red", "colourfind (null)",
                                  "colour -1", "colour %d" % count),
                         ["-1"] * 4 + ["(none)"] * 2)

    def test_each_colour_has_a_name_and_a_colour_outside_has_its_own(self):
        count = len(companion.LED_COLOURS)
        names = self.ask(*["colourname %d" % i for i in range(count)])
        self.assertNotIn("own", names)
        self.assertEqual(len(set(names)), count)
        self.assertEqual(self.ask("colourname -1", "colourname %d" % count),
                         ["own", "own"])

    def test_a_colour_is_six_hex_digits_after_a_hash(self):
        self.assertEqual(
            self.ask("rgb #ff8000", "rgb #FF8000", "rgb #25d366",
                     "rgb #000000"),
            ["ff8000", "ff8000", "25d366", "000000"])
        self.assertEqual(
            self.ask("rgb ff8000", "rgb xff8000", "rgb #ff800",
                     "rgb #ff80000", "rgb #gg0000", "rgb #f/8000"),
            ["(none)"] * 6)

    def test_each_per_cent_comes_back_to_itself(self):
        """The slider says per cents and the service keeps 0 to 255. A per
        cent that came back as its neighbour would move the slider at the
        answer of the PC."""
        levels = [int(one) for one in self.ask(*["brightness %d" % percent
                                                 for percent in range(101)])]
        self.assertEqual(
            self.ask(*["percent %d" % level for level in levels]),
            [str(percent) for percent in range(101)])
        self.assertEqual((levels[0], levels[50], levels[100]), (0, 128, 255))
        low, high = companion.LED_BRIGHTNESS
        self.assertTrue(all(low <= level <= high for level in levels))
        self.assertEqual(self.ask("percent 128", "percent 255", "percent 1"),
                         ["50", "100", "0"])

    def test_a_value_outside_is_held_at_the_end(self):
        self.assertEqual(self.ask("percent -5", "percent 300",
                                  "brightness -1", "brightness 101"),
                         ["0", "100", "0", "255"])

    def test_the_lit_mark_follows_the_list(self):
        answers = self.ask(*["lit 0 %d" % i
                             for i in range(len(desktop.SCENES))])
        self.assertEqual(
            [key for key, said in zip(desktop.SCENES, answers) if said == "1"],
            [key for key in desktop.SCENES if key in desktop.SCENES_LIT])
        self.assertEqual(self.ask("lit 0 -1", "lit 1 0",
                                  "lit 0 %d" % len(desktop.SCENES)),
                         ["0"] * 3)

    def test_every_colour_and_brightness_the_panel_builds_is_taken(self):
        """Each colour with each kind of brightness, with an effect and
        without, through the companion service."""
        cases = [(effect, colour, level)
                 for effect in ("-", "breath")
                 for colour in companion.LED_COLOURS + ("-",)
                 for level in (-1, 0, 128, 255)
                 if not (effect == colour == "-" and level < 0)]
        answers = self.ask(*["body 160 %s - %s %d" % case for case in cases])
        names = dict(companion.LED_LOOK, desktop="DESKTOP_SCENE")
        for (effect, colour, level), answer in zip(cases, answers):
            body, length = answer.rsplit(" ", 1)
            self.assertEqual(int(length), len(body), answer)
            wanted = {}
            if effect != "-":
                wanted["desktop"] = effect
            if colour != "-":
                wanted["desktop_color"] = colour
            if level >= 0:
                wanted["desktop_brightness"] = level
            self.assertEqual(json.loads(body), wanted)
            wrote = []
            code_, _ = companion.led_change(json.loads(body),
                                            write=wrote.append)
            self.assertEqual(code_, 200, body)
            self.assertEqual(wrote, [{names[key]: value
                                      for key, value in wanted.items()}])

    def test_a_colour_or_brightness_the_service_cannot_read_is_no_body(self):
        """The panel builds neither, and a body with one would be half an
        object or a refusal."""
        self.assertEqual(
            self.ask("body 160 breath - #ff00 128", "body 160 breath - red -1",
                     "body 160 - - #gggggg -1", "body 160 breath - - 256",
                     "body 160 - - - -1"),
            ["(empty) 0"] * 5)

    def test_a_body_of_the_colour_with_no_room_is_no_body(self):
        whole = self.ask("body 160 temperature temperature #ffffff 255")[0]
        size = len(whole.rsplit(" ", 1)[0])
        for room in (size, size - 1, size - 10, 3, 2, 1, 0):
            self.assertEqual(
                self.ask("body %d temperature temperature #ffffff 255"
                         % room), ["(empty) 0"], room)
        self.assertEqual(self.ask("body %d temperature temperature #ffffff 255"
                                  % (size + 1)), [whole])

    def test_the_colour_mark_follows_the_list(self):
        answers = self.ask(*["coloured 0 %d" % i
                             for i in range(len(desktop.SCENES))])
        self.assertEqual(
            [key for key, said in zip(desktop.SCENES, answers)
             if said == "1"],
            [key for key in desktop.SCENES
             if key in desktop.SCENES_WITH_COLOUR])
        self.assertEqual(self.ask("coloured 0 -1", "coloured 1 0"),
                         ["0", "0"])


if __name__ == "__main__":
    unittest.main()
