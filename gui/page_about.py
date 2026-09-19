# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The About page: what this is, and the update that brings a new one.

The update fetches into the copy of this project that the menu entry opens,
and then runs the installer from it. The clone a person made is not needed
for either, and it can go: see scripts/update.sh.

The branch menu reads what that copy knows of its remote, with no network
access. A branch from after the last fetch arrives in the menu after the
next check.

It is a mixin and not a widget. Panel takes it as a base, so every method
here is a method of Panel and `self` is the window.

What stays in the window: _restart, which replaces this process with a
fresh copy of the panel. It names the file to run with __file__, and
__file__ in this module is this module. A restart from here would start a
page rather than a window, and nothing would come back.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ledpanel
from steamos_utility_center import cec

from panelbase import (GROUP_GAP, ROW_FIELD_WIDTH, ROW_GAP, SIDE_MARGIN,
                       SOURCE_DIR)


class AboutPage:
    """The methods of that page. See the note at the top of this file."""

    def _build_app(self, where, table, note):
        """App Settings: everything about this program itself.

        The look of the panel and its update controls, which are settings of
        the panel and not of the machine. A fault list is a different question
        and stays on the status page.
        """
        outer = self._build_settings(where, table, note)
        self.update_box = self._build_update(outer)
        return outer

    def _build_update(self, parent):
        """Fetch a branch and install it: the two halves of "get the new one".

        On a card, as each other group of settings on this page is. A plain
        frame here draws a band of the wrong colour at the width of its
        content, and the live tests check for that.
        """
        holder = ttk.Frame(parent, style="Page.TFrame")
        holder.pack(fill="x")

        if not ledpanel.is_git_clone(SOURCE_DIR):
            self._note(
                holder,
                "%s is not a git clone, so there is nothing to update from - "
                "this is what downloading a zip leaves you with. Clone it "
                "with git to get updates here." % SOURCE_DIR, page=True,
            ).pack(anchor="w", padx=SIDE_MARGIN, pady=(GROUP_GAP, 0))
            return holder

        card = self._card(holder)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(GROUP_GAP, 0))
        frame = ttk.Frame(card)
        frame.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        ttk.Label(frame, text="Update", style="Section.TLabel").pack(
            anchor="w", pady=(0, ROW_GAP))

        row = ttk.Frame(frame, style=self._ground(frame))
        row.pack(fill="x")
        ttk.Label(row, text="Branch").pack(side="left", padx=(0, ROW_GAP))
        self.branch = tk.StringVar()
        # Built with the branch that is checked out and nothing else, then
        # filled: _refresh_branches is the one place that knows how the list
        # is made, and it runs again after every fetch.
        self._field(row, "branch", self.branch, [],
                    ledpanel.current_branch(SOURCE_DIR),
                    width=ROW_FIELD_WIDTH).pack(side="left", padx=(0, GROUP_GAP))
        self._refresh_branches()
        ttk.Button(row, text="Check for updates", style="Outlined.TButton",
                   command=self.check_for_updates).pack(side="left",
                                                        padx=(0, ROW_GAP))
        self.update_button = ttk.Button(row, text="Update and install",
                                        style="Filled.TButton",
                                        command=self.update_now)
        self.update_button.pack(side="left")
        # The result of the last check, in a place with no fold. The log is
        # almost always folded now, and it was the one place with this
        # answer.
        self.update_state = ttk.Label(frame)
        self.update_state.pack(anchor="w", pady=(ROW_GAP, 0))
        self._say_update(ledpanel.UPDATE_UNKNOWN, "")
        # A different branch is a different question, and the old answer is
        # not one about it.
        self.branch.trace_add("write", lambda *_a: self._say_update(
            ledpanel.UPDATE_UNKNOWN, ""))
        return holder

    def _say_update(self, state, sentence):
        """Show what the last check found, and gate the install button on it."""
        self._update_state = state
        self.update_state.configure(
            text=sentence,
            style="Good.TLabel" if state == ledpanel.UPDATE_CURRENT
            else "Section.TLabel" if state == ledpanel.UPDATE_AVAILABLE
            else "Muted.TLabel")
        self._refresh_update()

    def _refresh_update(self):
        """Nothing to install is a button that says so by not being pressable.

        Only after a check has actually said there is nothing: never having
        asked is not the same answer, and a button dead before anyone has
        looked would be the window refusing to do something it can do.
        """
        if getattr(self, "update_button", None) is None:
            return                              # not a clone; there is no row
        self.update_button.state(
            ["disabled"] if self._update_state == ledpanel.UPDATE_CURRENT
            else ["!disabled"])

    def _refresh_branches(self):
        """Fill the list from what the clone knows, keeping the selection."""
        branches = ledpanel.known_branches(SOURCE_DIR)
        current = self.branch.get()
        # A branch that the clone does not list stays in the menu. The
        # detached head after a fetch is such a branch. Without this code,
        # the current entry goes away below the pointer.
        if current and current not in branches:
            branches = sorted(branches + [current])
        self._menus["branch"] = [(name, name) for name in branches]

    def check_for_updates(self):
        def checked(code):
            self._refresh_branches()
            self._say_update(*ledpanel.update_verdict(
                "".join(self.runner.transcript), code))

        self.runner.start(
            ledpanel.update_command(SOURCE_DIR, self.branch.get(), check=True),
            checked)

    def update_now(self):
        wanted = self.branch.get()
        if wanted != ledpanel.current_branch(SOURCE_DIR) and not self._ask(
                "Switch branch",
                "This will switch from %s to %s and install that instead."
                % (ledpanel.current_branch(SOURCE_DIR) or "?", wanted),
                confirm="Switch"):
            return

        before = ledpanel.head_commit(SOURCE_DIR)

        def updated(code):
            self._refresh_branches()
            if code != 0:
                return                      # the script said why
            self._say_update(*ledpanel.update_verdict(
                "".join(self.runner.transcript), code))
            if ledpanel.head_commit(SOURCE_DIR) == before:
                self._write("Nothing new, so nothing to install.\n\n")
                return
            # Only force a module rebuild when its source actually moved: the
            # installer skips a module that is loaded and working, which is
            # right after a repair and wrong after an update that changed it.
            self.runner.start(
                ledpanel.reinstall_command(
                    SOURCE_DIR,
                    rebuild_module=ledpanel.module_changed(SOURCE_DIR, before)),
                self._installed)

        self.runner.start(ledpanel.update_command(SOURCE_DIR, wanted), updated)

    def _after_install(self):
        """Reads the machine again, after anything that installed something.

        The toolkit as well. An installation can replace it now, and this page
        drew what it read when the window opened: the HDMI CEC block and the
        line at the foot of the window were both correct only after somebody
        pressed Check again.
        """
        self.refresh_status()
        if cec.installed():
            self._reread_cec()

    def _installed(self, code):
        self._after_install()
        if code != 0:
            self._write("The install did not finish, so the panel is still "
                        "running the old files.\n\n")
            return
        if self._ask(
                "Update",
                "Installed.\n\nThe panel itself is still running the files it "
                "started with.", confirm="Restart the panel", deny="Later"):
            self._restart()
        else:
            self._write("Restart the panel when it suits you; until then it "
                        "is the old one you are looking at.\n\n")
