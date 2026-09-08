# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Runs the firmware's own test suite from this one.

tests/firmware/run.sh compiles firmware/led-client/src/main.cpp against
stubbed Arduino and NeoPixelBus headers and exercises its protocol handling
on this machine. No board is needed.

Nothing ran it. It was red for two checks that asserted the order of the
answer to HELLO, which the firmware changed when it started to send CAPS
first. A suite that nobody runs reports nothing.
"""

import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "firmware", "run.sh")


@unittest.skipUnless(shutil.which("g++"), "no C++ compiler on this machine")
class FirmwareTest(unittest.TestCase):

    def test_the_firmware_suite_passes(self):
        done = subprocess.run(["bash", RUNNER], capture_output=True,
                              text=True, cwd=os.path.join(HERE, ".."))
        self.assertEqual(done.returncode, 0,
                         "%s\n%s" % (done.stdout, done.stderr))
        self.assertIn("all firmware tests passed", done.stdout)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
