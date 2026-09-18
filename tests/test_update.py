# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Updating the clone, against real git repositories.

This is the one script that reaches into somebody's working copy, so it is
tested against actual repositories rather than a mock of one: what matters is
that it refuses in the cases where finishing the job would cost somebody their
work, and that a refusal really does leave everything as it was.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = os.path.join(HERE, "..", "scripts", "update.sh")

sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "gui"))

import ledpanel  # noqa: E402


def git(directory, *args):
    return subprocess.run(("git",) + args, cwd=directory, check=True,
                          capture_output=True, text=True).stdout.strip()


class UpdateScriptTest(unittest.TestCase):
    """A bare "origin", a clone of it, and the script in between."""

    def setUp(self):
        if not shutil.which("git"):                     # pragma: no cover
            self.skipTest("git is not installed")
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

        self.origin = os.path.join(self.root, "origin")
        self.work = os.path.join(self.root, "work")     # where commits are made
        os.makedirs(self.origin)
        git(self.origin, "init", "--bare", "--initial-branch=main", ".")

        os.makedirs(self.work)
        self._init(self.work)
        git(self.work, "remote", "add", "origin", self.origin)
        self._commit(self.work, "README.md", "first\n", "first commit")
        git(self.work, "push", "-u", "origin", "main")

        self.clone = os.path.join(self.root, "clone")
        git(self.root, "clone", self.origin, self.clone)
        self._init(self.clone)
        # The script finds the clone from its own path, so this test must run
        # a copy inside the clone. The installer puts it there.
        os.makedirs(os.path.join(self.clone, "scripts"), exist_ok=True)
        shutil.copy(UPDATE, os.path.join(self.clone, "scripts", "update.sh"))

    def _init(self, directory):
        git(directory, "init", "--initial-branch=main", ".")
        git(directory, "config", "user.email", "test@example.com")
        git(directory, "config", "user.name", "Test")

    def _commit(self, directory, name, text, message):
        path = os.path.join(directory, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
        git(directory, "add", name)
        git(directory, "commit", "-m", message)

    def _upstream_commit(self, message="second commit", branch="main",
                         name="README.md", text="second\n"):
        git(self.work, "checkout", branch)
        self._commit(self.work, name, text, message)
        git(self.work, "push", "origin", branch)

    def _run(self, *args, cwd=None):
        return subprocess.run(
            ["bash", os.path.join(self.clone, "scripts", "update.sh")]
            + list(args),
            cwd=cwd or self.root, capture_output=True, text=True)

    def _head(self, directory=None):
        return git(directory or self.clone, "rev-parse", "HEAD")

    # -- the ordinary path -------------------------------------------------

    def test_it_brings_the_clone_up_to_date(self):
        before = self._head()
        self._upstream_commit()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self._head(), before)
        self.assertIn("second commit", result.stdout)

    def test_it_says_so_when_there_is_nothing_to_do(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Already up to date", result.stdout)

    def test_it_reports_what_it_brought(self):
        self._upstream_commit("a change worth naming")
        self.assertIn("a change worth naming", self._run().stdout)

    def test_it_runs_from_anywhere(self):
        # The panel starts it with its own working directory, whatever that is.
        self._upstream_commit()
        result = self._run(cwd=os.path.expanduser("~"))
        self.assertEqual(result.returncode, 0, result.stderr)

    # -- switching branches ------------------------------------------------

    def test_it_switches_to_another_branch(self):
        git(self.work, "checkout", "-b", "experiment")
        self._commit(self.work, "new.txt", "x\n", "on the branch")
        git(self.work, "push", "-u", "origin", "experiment")

        result = self._run("experiment")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.clone, "symbolic-ref", "--short", "HEAD"),
                         "experiment")
        self.assertTrue(os.path.exists(os.path.join(self.clone, "new.txt")))

    def test_it_can_come_back_again(self):
        git(self.work, "checkout", "-b", "experiment")
        self._commit(self.work, "new.txt", "x\n", "on the branch")
        git(self.work, "push", "-u", "origin", "experiment")
        self._run("experiment")

        result = self._run("main")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.clone, "symbolic-ref", "--short", "HEAD"),
                         "main")

    def test_an_unknown_branch_is_refused_with_the_list(self):
        result = self._run("nonesuch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no branch called nonesuch", result.stderr)
        self.assertIn("main", result.stderr, "it should say what there is")

    # -- the refusals ------------------------------------------------------

    def test_local_changes_stop_it_and_survive(self):
        with open(os.path.join(self.clone, "README.md"), "w") as handle:
            handle.write("mine\n")
        self._upstream_commit()
        before = self._head()

        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local changes", result.stderr)
        self.assertEqual(self._head(), before, "it must not have moved")
        with open(os.path.join(self.clone, "README.md")) as handle:
            self.assertEqual(handle.read(), "mine\n",
                             "the edit must still be there")

    def test_an_untracked_file_is_not_in_the_way(self):
        # Notes of your own next to the code cannot conflict with a
        # fast-forward, and refusing over them would be unhelpful.
        with open(os.path.join(self.clone, "notes.txt"), "w") as handle:
            handle.write("mine\n")
        self._upstream_commit()

        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.clone, "notes.txt")))

    def test_local_commits_stop_it_and_survive(self):
        self._commit(self.clone, "local.txt", "mine\n", "my own work")
        mine = self._head()
        self._upstream_commit()

        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commits of its own", result.stderr)
        self.assertEqual(self._head(), mine, "the local commit must survive")

    def test_it_says_where_it_is_not_a_clone(self):
        plain = os.path.join(self.root, "plain", "scripts")
        os.makedirs(plain)
        shutil.copy(UPDATE, os.path.join(plain, "update.sh"))
        result = subprocess.run(["bash", os.path.join(plain, "update.sh")],
                                cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a git clone", result.stderr)
        self.assertIn("git clone", result.stderr, "it should say what to do")

    # -- checking without changing anything --------------------------------

    def test_check_reports_what_would_arrive(self):
        self._upstream_commit("something new")
        before = self._head()

        result = self._run("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("something new", result.stdout)
        self.assertEqual(self._head(), before, "--check must not touch it")

    def test_check_is_happy_when_there_is_nothing(self):
        result = self._run("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Already up to date", result.stdout)

    def test_check_warns_about_what_would_stop_the_update(self):
        with open(os.path.join(self.clone, "README.md"), "w") as handle:
            handle.write("mine\n")
        self._upstream_commit()
        result = self._run("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("local changes", result.stdout)

    def test_check_looks_at_the_branch_it_was_given(self):
        git(self.work, "checkout", "-b", "experiment")
        self._commit(self.work, "new.txt", "x\n", "only on experiment")
        git(self.work, "push", "-u", "origin", "experiment")

        result = self._run("--check", "experiment")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("only on experiment", result.stdout)
        self.assertEqual(git(self.clone, "symbolic-ref", "--short", "HEAD"),
                         "main", "checking is not switching")


class PanelUpdateHelpersTest(UpdateScriptTest):
    """What the panel needs to know about the clone before and after.

    These tests use the same repositories as the tests above, because they read
    a real repository. A mock of git proves only that the mock agrees with
    itself.
    """

    def test_it_recognises_a_clone(self):
        self.assertTrue(ledpanel.is_git_clone(self.clone))
        self.assertFalse(ledpanel.is_git_clone(self.root))

    def test_it_reads_the_current_branch(self):
        self.assertEqual(ledpanel.current_branch(self.clone), "main")

    def test_a_detached_head_is_on_no_branch(self):
        git(self.clone, "checkout", "--detach", "HEAD")
        self.assertEqual(ledpanel.current_branch(self.clone), "")

    def test_the_menu_lists_the_branches_the_clone_knows(self):
        git(self.work, "checkout", "-b", "experiment")
        self._commit(self.work, "new.txt", "x\n", "on the branch")
        git(self.work, "push", "-u", "origin", "experiment")
        git(self.clone, "fetch", "origin")
        self.assertEqual(ledpanel.known_branches(self.clone),
                         ["experiment", "main"])

    def test_the_menu_leaves_out_the_head_pointer(self):
        # origin/HEAD is a symbolic ref, not somewhere to update to.
        git(self.clone, "remote", "set-head", "origin", "main")
        self.assertNotIn("HEAD", ledpanel.known_branches(self.clone))

    def test_the_module_counts_as_changed_when_it_changed(self):
        before = ledpanel.head_commit(self.clone)
        self._upstream_commit("touch the module",
                             name="leds-valve-shim/module.c", text="int x;\n")
        self._run()
        self.assertTrue(ledpanel.module_changed(self.clone, before))

    def test_an_update_elsewhere_does_not_force_a_rebuild(self):
        # Rebuilding costs half a minute and needs kernel headers, so it has
        # to be worth it.
        before = ledpanel.head_commit(self.clone)
        self._upstream_commit("only the README")
        self._run()
        self.assertFalse(ledpanel.module_changed(self.clone, before))

    def test_not_knowing_where_it_started_means_rebuild(self):
        # A stale module costs the bar; a needless rebuild costs a minute.
        self.assertTrue(ledpanel.module_changed(self.clone, ""))


class AdoptTest(UpdateScriptTest):
    """A copy of the files with no history, which has to become a clone.

    This is the zip download, and the install whose own clone step failed.
    The person asked for one thing: the clone they started with is something
    they can throw away, and updating has to work without it.
    """

    def setUp(self):
        super().setUp()
        # The same files, with no .git at all.
        self.plain = os.path.join(self.root, "downloaded")
        shutil.copytree(self.clone, self.plain,
                        ignore=shutil.ignore_patterns(".git"))
        self.assertFalse(os.path.exists(os.path.join(self.plain, ".git")))

    def _adopt(self, *args):
        return subprocess.run(
            ["bash", os.path.join(self.plain, "scripts", "update.sh")]
            + list(args),
            cwd=self.root, capture_output=True, text=True,
            env=dict(os.environ, PROJECT_URL=self.origin))

    def test_a_check_writes_nothing_and_says_what_would_happen(self):
        result = self._adopt("--check", "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not a git clone yet", result.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.plain, ".git")))

    def test_it_becomes_a_clone_on_the_branch(self):
        result = self._adopt("main")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.plain, ".git")))
        self.assertEqual(git(self.plain, "rev-parse", "--abbrev-ref", "HEAD"),
                         "main")
        self.assertEqual(git(self.plain, "remote", "get-url", "origin"),
                         self.origin)

    def test_it_overwrites_no_file(self):
        """A zip of an older version differs from the branch in a lot.

        A reset that took the branch version would be somebody's files gone
        with no question asked. So the files stay and the difference is
        reported.
        """
        mine = os.path.join(self.plain, "README.md")
        with open(mine, "w") as handle:
            handle.write("what this copy holds\n")
        result = self._adopt("main")
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(mine) as handle:
            self.assertEqual(handle.read(), "what this copy holds\n")
        self.assertIn("README.md", result.stdout)
        self.assertIn("No file was overwritten", result.stdout)

    def test_a_copy_that_matches_carries_on_into_the_update(self):
        """Nothing differs, so the same run goes on to the ordinary path.

        One press of the button, and the person never learns that their copy
        had no history.
        """
        result = self._adopt("main")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Already up to date", result.stdout)
        self.assertEqual(git(self.plain, "rev-parse", "HEAD"),
                         self._head(self.work))

    def test_it_asks_for_a_branch_when_nothing_names_one(self):
        result = self._adopt()
        self.assertEqual(result.returncode, 1)
        self.assertIn("which branch", result.stderr)

    def test_it_reads_the_branch_of_the_installed_stamp(self):
        """The installer writes "<commit> <branch>" for exactly this.

        A copy with no history carries no HEAD, so without the stamp there is
        nothing that says which branch these files came from.
        """
        with open(os.path.join(self.plain, "scripts", "update.sh")) as handle:
            text = handle.read()
        self.assertIn("installed-from", text)
        self.assertIn("NR == 1 { print $2 }", text)


class RefusedCloneTest(UpdateScriptTest):
    """A clone that is there and that git will not read.

    The installed copy belonged to root while the panel runs as a person.
    git answers "detected dubious ownership" and stops, and this script read
    that as "there is no clone here". It then printed the message about a zip
    download on a machine that had a clone and needed one line to mend. A
    person who reads that message looks in the wrong place.
    """

    def setUp(self):
        super().setUp()
        self.broken = os.path.join(self.root, "broken")
        shutil.copytree(self.clone, self.broken,
                        ignore=shutil.ignore_patterns(".git"))
        # A .git that is there and that git refuses, which is the shape of
        # the fault whatever the reason for it is.
        os.makedirs(os.path.join(self.broken, ".git"))

    def _go(self, *args):
        return subprocess.run(
            ["bash", os.path.join(self.broken, "scripts", "update.sh")]
            + list(args), cwd=self.root, capture_output=True, text=True)

    def test_it_does_not_call_it_a_zip_download(self):
        result = self._go("--check")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("zip", result.stderr.lower())

    def test_it_repeats_what_git_said(self):
        result = self._go("--check")
        self.assertIn("will not read", result.stderr)
        self.assertIn("git", result.stderr)

    def test_it_makes_nothing_a_clone(self):
        """Adoption is for a directory with no history at all.

        A .git that git refuses holds somebody's history, and git init over
        the top of it is that history gone.
        """
        self._go()
        self.assertEqual(os.listdir(os.path.join(self.broken, ".git")), [])

    def test_the_installed_copy_is_told_to_run_the_installer(self):
        with open(os.path.join(self.broken, "scripts", "update.sh")) as handle:
            text = handle.read()
        where = text.index("INSTALLED_COPY")
        self.assertIn("/var/lib/steamos-utility-center/source",
                      text[where:where + 200])
        self.assertIn("sudo $SOURCE_DIR/install.sh", text)


class ToolboxCloneTest(unittest.TestCase):
    """copy_toolbox against a clone that git treats as somebody else's.

    The installer runs as root on a clone that belongs to a person, and git
    refuses a repository it believes belongs to another account. `git -c
    safe.directory=...` does not reach the second git that a clone starts to
    read the source, so the clone step failed on every ordinary install. The
    installer then fell back to a plain copy of the files, the one warning it
    printed said nothing about why, and the update page reported "this is not
    a git clone" on a machine that never had a chance to get one.

    GIT_TEST_ASSUME_DIFFERENT_OWNER is how git's own tests ask for that
    refusal with one account, so this runs anywhere.
    """

    RUN = (
        "set -e\n"
        'export ROOT="%(root)s"\n'
        'SOURCE_DIR="%(source)s"\n'
        'source "%(repo)s/scripts/user-unit.sh"\n'
        "eval \"$(sed -n '/^copy_toolbox() {/,/^}/p' \"%(repo)s/install.sh\")\"\n"
        "eval \"$(sed -n '/^give_away_toolbox() {/,/^}/p' "
        "\"%(repo)s/install.sh\")\"\n"
        "watcher_user_dirs() { return 1; }\n"
        "copy_toolbox\n")

    def setUp(self):
        if not shutil.which("git"):                     # pragma: no cover
            self.skipTest("git is not installed")
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.source = os.path.join(self.root, "clone")
        os.makedirs(os.path.join(self.source, "scripts"))
        git(self.source, "init", "--initial-branch=main", ".")
        git(self.source, "config", "user.email", "test@example.com")
        git(self.source, "config", "user.name", "Test")
        git(self.source, "remote", "add", "origin",
            "https://example.invalid/project")
        with open(os.path.join(self.source, "README.md"), "w") as handle:
            handle.write("the toolbox\n")
        git(self.source, "add", "README.md")
        git(self.source, "commit", "-m", "first")

    def _copy(self, foreign):
        where = os.path.join(self.root, "machine")
        env = dict(os.environ)
        if foreign:
            env["GIT_TEST_ASSUME_DIFFERENT_OWNER"] = "1"
        answer = subprocess.run(
            ["bash", "-c", self.RUN % {"root": where, "source": self.source,
                                       "repo": os.path.join(HERE, "..")}],
            capture_output=True, text=True, env=env)
        return answer, os.path.join(
            where, "var/lib/steamos-utility-center/source")

    def test_it_clones_a_repository_that_git_calls_somebody_elses(self):
        answer, copy = self._copy(foreign=True)
        self.assertEqual(answer.returncode, 0, answer.stderr)
        self.assertTrue(os.path.isdir(os.path.join(copy, ".git")),
                        "the copy has no history:\n" + answer.stderr)
        self.assertEqual(git(copy, "rev-parse", "--abbrev-ref", "HEAD"), "main")

    def test_the_copy_keeps_the_remote_of_the_source(self):
        """Asked of an ordinary clone.

        GIT_TEST_ASSUME_DIFFERENT_OWNER makes every repository foreign, the
        fresh copy as well, so the remote cannot be set under it. On a
        machine root makes the copy and root is the one that sets it.
        """
        answer, copy = self._copy(foreign=False)
        self.assertEqual(git(copy, "remote", "get-url", "origin"),
                         "https://example.invalid/project")

    def test_a_remote_it_cannot_set_does_not_stop_the_install(self):
        """install.sh runs with `set -e`.

        An unguarded git call here takes the whole installation with it, and
        the copy is already made by the time it runs.
        """
        answer, copy = self._copy(foreign=True)
        self.assertEqual(answer.returncode, 0, answer.stderr)
        self.assertIn("could not point", answer.stderr)

    def test_it_clones_an_ordinary_one_as_well(self):
        answer, copy = self._copy(foreign=False)
        self.assertTrue(os.path.isdir(os.path.join(copy, ".git")),
                        answer.stderr)

    def test_a_clone_that_fails_says_what_git_said(self):
        """The silent warning is what hid this for a week.

        The copy still happens, so the installation works either way. What
        was missing was the reason, which is the thing a person needs.
        """
        with open(os.path.join(HERE, "..", "install.sh")) as handle:
            body = handle.read()
        where = body.index("could not clone the toolbox")
        self.assertIn("printf", body[where:where + 300])
        self.assertIn('"$said"', body[where:where + 300])


class UpdateCommandTest(unittest.TestCase):
    """The commands the panel builds, without running them."""

    def test_updating_needs_no_privileges(self):
        # The clone belongs to the user; only installing what it brings does.
        command = ledpanel.update_command("/repo")
        self.assertNotIn("pkexec", command)
        self.assertIn("/repo/scripts/update.sh", command)

    def test_a_branch_is_passed_on(self):
        self.assertIn("debug", ledpanel.update_command("/repo", "debug"))

    def test_checking_is_the_same_command_with_a_flag(self):
        command = ledpanel.update_command("/repo", "main", check=True)
        self.assertIn("--check", command)
        self.assertIn("main", command)

    def test_no_branch_means_the_one_it_is_on(self):
        self.assertEqual(ledpanel.update_command("/repo"),
                         ["/repo/scripts/update.sh"])

    def test_branch_names_are_read_off_for_each_ref(self):
        self.assertEqual(
            ledpanel.parse_branches("main\nHEAD\ndebug\n\nmain\n"),
            ["debug", "main"])

    def test_nothing_known_is_an_empty_menu_not_a_crash(self):
        self.assertEqual(ledpanel.parse_branches(""), [])


if __name__ == "__main__":
    unittest.main()
