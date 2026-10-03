# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The energy profiles of the CPU on the page of the wall panel.

The panel keeps the names and the order of the profiles in panel_cpu.c, and
the PC decides what each one is on its own machine, in power.py. These tests
hold the two lists equal. A profile that the PC learns is then a failing
test until the panel has it too, and a change that the panel builds is one
that the companion service takes.

The functions of panel_cpu.c run on the machine of the tests through a
small harness, as the functions of panel_led.c do.
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(REPO, "firmware", "companion", "main")
PREVIEW = os.path.join(REPO, "firmware", "companion", "preview")
HARNESS = os.path.join(REPO, "tests", "c", "panel-cpu-harness.c")
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import companion, power  # noqa: E402

# The profiles of the PC, in the order of the panel.
PROFILES = [name for name, _candidates in power.PROFILES] + [
    power.PROFILE_STEAMOS]


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def code(name):
    """A source file of the firmware, with no comments in it."""
    text = read(os.path.join(FIRMWARE, name))
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def profiles():
    """The entries of the list of panel_cpu.c: (key, text)."""
    found = re.search(r"profiles\[PANEL_CPU_PROFILES\] = \{(.*?)\};",
                      code("panel_cpu.c"), re.S)
    assert found
    return re.findall(r'\{"(\w+)", (TXT_\w+)\}', found.group(1))


def machine():
    """A sysfs with two policies of amd-pstate in its active mode."""
    root = tempfile.mkdtemp()
    for cpu in range(2):
        where = os.path.join(root,
                             "sys/devices/system/cpu/cpu%d/cpufreq" % cpu)
        os.makedirs(where)
        for name, text in (
                ("scaling_driver", "amd-pstate-epp"),
                ("scaling_available_governors", "performance powersave"),
                ("scaling_governor", "powersave"),
                ("energy_performance_available_preferences",
                 "default performance balance_performance balance_power "
                 "power"),
                ("energy_performance_preference", "balance_performance")):
            with open(os.path.join(where, name), "w") as handle:
                handle.write(text + "\n")
    return root


class ListTest(unittest.TestCase):
    """The list of the panel against the profiles of the PC."""

    def test_the_keys_are_the_profiles_of_the_pc_in_its_order(self):
        self.assertEqual([key for key, _ in profiles()], PROFILES)

    def test_the_enum_has_a_place_for_each(self):
        found = re.search(r"typedef enum \{(.*?)\} panel_cpu_profile_t;",
                          code("panel_cpu.h"), re.S)
        names = re.findall(r"PANEL_CPU_[A-Z]+", found.group(1))
        self.assertEqual(names[-1], "PANEL_CPU_PROFILES")
        self.assertEqual([name[len("PANEL_CPU_"):].lower()
                          for name in names[:-1]], PROFILES)

    def test_each_name_is_in_the_table_of_the_texts(self):
        table = read(os.path.join(FIRMWARE, "panel_text.h"))
        texts = [text for _, text in profiles()]
        self.assertEqual(len(set(texts)), len(texts))
        for text in texts:
            self.assertRegex(table, r"X\(%s," % text)

    def test_each_profile_has_the_name_of_its_key(self):
        """Two names that change places are two buttons that send the
        profile of the other one."""
        for key, text in profiles():
            self.assertEqual(text, "TXT_CPU_" + key.upper())

    def test_the_room_for_a_key_holds_the_longest_one(self):
        room = int(re.search(r"#define PANEL_CPU_KEY (\d+)",
                             code("panel_cpu.h")).group(1))
        self.assertGreater(room, max(len(key) for key in
                                     PROFILES + [power.PROFILE_CUSTOM]))


class StatusTest(unittest.TestCase):
    """What the panel reads, against what the companion service sends."""

    def test_the_two_sides_name_the_same_path(self):
        self.assertIn('#define PANEL_CPU_PATH "%s"' % companion.CPU_PATH,
                      code("main.c"))

    def test_the_panel_reads_each_key_the_service_sends(self):
        root = machine()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        said = companion.cpu(present=lambda path: True, root=root)
        main = code("main.c")
        self.assertIn('cJSON_GetObjectItemCaseSensitive(root,"cpu")', main)
        for key in said:
            self.assertIn('"%s"' % key, main, key)

    def test_the_words_of_the_kernel_fit_the_panel(self):
        header = code("ui.h")
        for name in ("cpu_governor", "cpu_epp", "cpu_driver"):
            room = int(re.search(r"\b%s\[(\d+)\]" % name, header).group(1))
            self.assertGreater(room, companion.CPU_WORD, name)

    def test_the_offers_fit_their_bits(self):
        found = re.search(r"uint(\d+)_t cpu_offers;", code("ui.h"))
        self.assertIsNotNone(found)
        self.assertLessEqual(len(PROFILES), int(found.group(1)))

    def test_both_builds_carry_the_file(self):
        self.assertIn('"panel_cpu.c"',
                      read(os.path.join(FIRMWARE, "CMakeLists.txt")))
        self.assertIn("../main/panel_cpu.c",
                      read(os.path.join(PREVIEW, "CMakeLists.txt")))


def compiler():
    return shutil.which("cc") or shutil.which("gcc")


@unittest.skipUnless(compiler(), "no C compiler here")
class HarnessTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-cpu")
        done = subprocess.run(
            [compiler(), "-std=gnu17", "-Wall", "-Wextra", "-Werror",
             "-I", FIRMWARE, "-o", cls.program, HARNESS,
             os.path.join(FIRMWARE, "panel_cpu.c")],
            capture_output=True, text=True)
        # A failure and not a skip: the file is plain C, so a build that
        # fails is a fault in it.
        if done.returncode != 0:
            shutil.rmtree(cls.where, ignore_errors=True)
            raise AssertionError("panel_cpu.c did not build here:\n"
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
        self.assertEqual(self.ask(*["key %d" % i
                                    for i in range(len(PROFILES))]),
                         PROFILES)
        self.assertEqual(self.ask(*["find %s" % key for key in PROFILES]),
                         [str(i) for i in range(len(PROFILES))])

    def test_custom_and_the_unknown_have_no_place(self):
        self.assertEqual(self.ask("find custom", "find turbo", "find (null)",
                                  "find power", "find balanced_power",
                                  "key -1", "key %d" % len(PROFILES)),
                         ["-1"] * 5 + ["(none)"] * 2)

    def test_each_profile_has_a_name_and_a_place_outside_has_none(self):
        names = self.ask(*["name %d" % i for i in range(len(PROFILES))])
        self.assertNotIn("(none)", names)
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(self.ask("name -1", "name %d" % len(PROFILES)),
                         ["(none)", "(none)"])

    def test_every_change_the_panel_builds_is_one_the_service_takes(self):
        root = machine()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        answers = self.ask(*["body 48 %d" % i for i in range(len(PROFILES))])
        for name, answer in zip(PROFILES, answers):
            body, length = answer.rsplit(" ", 1)
            self.assertEqual(int(length), len(body))
            self.assertEqual(json.loads(body), {"profile": name})
            self.assertLessEqual(len(body), companion.BODY_LIMIT)
            wrote = []
            answer_code, _ = companion.cpu_change(json.loads(body),
                                                  write=wrote.append,
                                                  root=root)
            self.assertEqual(answer_code, 200, body)
            self.assertEqual(wrote, [power.profile_settings(name, root)])

    def test_a_body_with_no_room_is_no_body(self):
        whole = self.ask("body 48 2")[0]
        size = len(whole.rsplit(" ", 1)[0])
        self.assertEqual(self.ask("body %d 2" % size, "body 0 2",
                                  "body 48 -1", "body 48 9"),
                         ["(empty) 0"] * 4)
        self.assertEqual(self.ask("body %d 2" % (size + 1)), [whole])

    def test_the_room_of_main_c_holds_the_longest_body(self):
        longest = max(self.ask(*["body 256 %d" % i
                                 for i in range(len(PROFILES))]),
                      key=len)
        room = int(re.search(r"char body\[(\d+)\];\s*int code=0;",
                             code("main.c")).group(1))
        self.assertLess(len(longest.rsplit(" ", 1)[0]), room)


if __name__ == "__main__":
    unittest.main()
