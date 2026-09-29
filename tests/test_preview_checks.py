# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Everything under firmware/companion/preview is built by the job.

That directory holds the checks of the panel's screen half and the program
that draws the screen into a file. They need the LVGL that the firmware
build downloads, so for a long time nothing built any of them, and things
rotted there three separate times:

  ui.c grew a call into panel_text.c when the panel learned English, and
  panel_text.c was not in the CMakeLists. Two targets stopped linking.

  check_navigation clicked on the German words of a panel that answers in
  English. Every click missed. It had never run.

  preview.c wrote a word into panel_state_t.charging after that field became
  a flag, which is not something a C compiler lets pass. It had never built.

Each one was found by adding the next target to the job, one at a time. This
rule ends that: a target that exists under preview/ is a target the job
builds. Somebody who adds a fifth one and forgets the workflow fails here,
and not in six months.
"""

from __future__ import annotations

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREVIEW = os.path.join(REPO, "firmware", "companion", "preview")
WORKFLOW = os.path.join(REPO, ".github", "workflows",
                        "companion-firmware.yml")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def targets():
    """Every executable the preview build knows how to make."""
    build = read(os.path.join(PREVIEW, "CMakeLists.txt"))
    return sorted(set(re.findall(r"add_executable\(\s*(\w+)", build)))


def built_by_the_job():
    """The names on the --target line of the step that builds them."""
    text = read(WORKFLOW)
    line = re.search(r"cmake --build preview-build --target(.*?)-j",
                     text, re.S)
    if not line:
        return []
    # The line is wrapped with a backslash, which is not a target name.
    return sorted(set(line.group(1).replace("\\", " ").split()))


class PreviewTargetTest(unittest.TestCase):
    def test_the_list_is_worth_reading(self):
        """A pattern that finds nothing passes every rule below for ever."""
        self.assertGreater(len(targets()), 3,
                           "the CMakeLists reads wrong, not the workflow")

    def test_the_job_builds_every_one_of_them(self):
        missing = sorted(set(targets()) - set(built_by_the_job()))
        self.assertEqual(missing, [],
                         "these are under preview/ and the job never builds "
                         "them, which is how the last three broke")

    def test_the_job_names_nothing_that_is_not_there(self):
        """A target that went, left behind on the line, fails the build."""
        extra = sorted(set(built_by_the_job()) - set(targets()))
        self.assertEqual(extra, [])

    def test_each_one_is_run_and_not_only_built(self):
        """Building proves it compiles. Running proves it works.

        panel_preview draws a file and answers nothing, and it is run for
        the same reason: a program that only builds can still crash on the
        first line.
        """
        text = read(WORKFLOW)
        for name in targets():
            self.assertRegex(text, r"\./preview-build/%s\b" % name,
                             "%s is built and never run" % name)


if __name__ == "__main__":
    unittest.main()
