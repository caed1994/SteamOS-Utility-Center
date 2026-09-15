# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every file this project points at, and whether it is still there.

The comments here carry the reasoning, and a comment that names a file is
how one part sends a reader to another. A file that moves or goes leaves
those names behind, and nothing reports it: the code runs, the tests pass,
and a reader follows a path to nothing.

This found three such names on the day it was written. A hook script under
scripts became the program at server/steamos_utility_center/sleepwatch.py,
and two units and one module still sent the reader to the file that was gone.

No dead name is written in this file. A test that forbids one must not hold
one, and the first version of it held two.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))

# The directories of this project, as a name in a comment spells them.
ROOMS = ("server", "scripts", "tests", "gui", "tools", "firmware", "decky",
         "docs", "cec-toolkit")

# A path that begins with one of those directories.
#
# It takes every path character it can and the suffix is checked after, which
# is what keeps three kinds of false name out. A greedy match reads
# "...toolkit.conf.example" whole, so it does not become a ".conf" that is
# not there. It reads "index.html" whole, so it does not become an ".h". And
# the guard in front refuses a path inside a longer word, because a hyphen
# ends a word and a home directory can hold a name that looks like this one.
NAMED = re.compile(r"(?<![A-Za-z0-9_./-])((?:%s)/[A-Za-z0-9_./-]+)"
                   % "|".join(ROOMS))

# The suffixes that this project writes. A name that ends in another one is
# not a name of a file here, and it is left alone.
ENDS = (".py", ".sh", ".service", ".md", ".conf", ".tsx", ".cpp", ".h", ".ini")


def names(text):
    """Every path of this project that this text points at.

    A name at the end of a sentence carries the full stop, so the punctuation
    comes off first. Without that, every reference that ends a sentence is
    read as a file with one character too many, and two thirds of them go
    unchecked.
    """
    for named in NAMED.findall(text):
        named = named.rstrip(".,;:)")
        if named.endswith(ENDS):
            yield named


# Where to read the names from. A binary file holds none.
SUFFIXES = (".py", ".sh", ".service", ".md", ".conf")

SKIP = {".git", "node_modules", "__pycache__", ".pytest_cache", "dist",
        ".venv", "build"}


def _files():
    """Every file of this project that a name can be written in."""
    for room, dirs, names in os.walk(REPO):
        dirs[:] = [one for one in dirs if one not in SKIP]
        for name in names:
            if name.endswith(SUFFIXES):
                yield os.path.join(room, name)


class ReferenceTest(unittest.TestCase):
    """A name in a comment that no longer names a file."""

    def test_every_path_this_project_names_is_there(self):
        """From the root of the repository, or from the root of the subtree
        that the file is in.

        cec-toolkit is another project inside this one, and its own README
        names its own docs the way that project spells them.
        """
        missing = []
        for path in _files():
            try:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            here = os.path.dirname(path)
            inside = os.path.join(REPO, "cec-toolkit")
            for named in sorted(set(names(text))):
                if os.path.exists(os.path.join(REPO, named)):
                    continue
                if path.startswith(inside) \
                        and os.path.exists(os.path.join(inside, named)):
                    continue
                if os.path.exists(os.path.join(here, named)):
                    continue
                missing.append("%s names %s"
                               % (os.path.relpath(path, REPO), named))
        self.assertEqual(missing, [])

    def test_it_reads_enough_names_to_be_worth_running(self):
        """A pattern that matched nothing passes the test above for ever.

        The count is a floor and not a measurement, so a file that goes does
        not fail this. It fails when the pattern itself stops working.
        """
        found = 0
        for path in _files():
            try:
                with open(path, encoding="utf-8") as handle:
                    found += len(set(names(handle.read())))
            except (OSError, UnicodeDecodeError):
                continue
        self.assertGreater(found, 100)


if __name__ == "__main__":
    unittest.main()
