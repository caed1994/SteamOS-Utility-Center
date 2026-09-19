# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Status page: what this machine has of this project, and what is wrong.

Every other page of this window sets something. This one reads, and it is
the page a person opens when something stopped working. So it says what it
found in the words of the machine, and it offers the one button that repairs
each finding rather than a paragraph about what to type.

The reading itself is not here. ledpanel.py works out the parts and their
verdicts with no widget in sight, which is what lets a machine with no
display test them. This file draws what that module returns.

It is a mixin and not a widget. Panel takes it as a base, so every method
here is a method of Panel and `self` is the window. refresh_status is called
from six places in the window and from two of its pages, and it stays one
name on one object for all of them.

What stays in the window: _forget_dead_labels, which the graphics card needs
as well, and _fit_window, _refit and _ask_for_the_open_page, which are the
layout of the window and not of this page.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

import ledpanel
from steamos_utility_center import cec
from steamos_utility_center import lact
from steamos_utility_center import modules
from steamos_utility_center import power
from steamos_utility_center import syssettings
from steamos_utility_center import __version__ as VERSION

from panelbase import (CARD_WRAP, FOLD_ROOM, GROUP_GAP, PART_INDENT,
                       ROW_GAP, SIDE_MARGIN, SOURCE_DIR)

# The size of the light at the head of each block.
#
# It is the height of a line of text. Smaller than that, the three colours of
# a block are not three lights but three bullet points.
STATUS_DOT = 7


class StatusPage:
    """The methods of that page. See the note at the top of this file."""

    def _build_status(self, parent):
        """The condition of each part of the toolbox, and its repair.

        A part with a fault gets a block of its own: a light, the sentence,
        the checks behind a fold, and the one button that repairs *that* part.
        Every other part is one row in one card at the foot. Six cards that
        each say "in order" are six cards to pass to reach the one that does
        not.

        The repair buttons stay here and do not move to their own pages. A
        person finds a fault here, and a walk to another section is the walk
        this page saves.
        """
        outer = ttk.Frame(parent, style="Page.TFrame")
        # Which blocks are unfolded, by part key. Kept out here because
        # refreshing rebuilds them and a fold that closed itself every time
        # the page was re-read would be a fold nobody could use.
        self._open_parts = set()
        # The fold buttons on the page now, by widget name. This code builds
        # them again with the blocks. See _register_buttons, which does not
        # disable them.
        self._fold_buttons = set()
        # The blocks that opened themselves for a fault. Each block does that
        # one time. Without this set, a block that the user closed opens again
        # at the next read. That read runs every few seconds during a command.
        self._shown_parts = set()
        # References into the blocks, so a fold opens with no rebuild of them.
        # See _fold_part. Each refresh_status fills this map again.
        self._part_details = {}
        self._fold_arrows = {}
        # The head of the page: the count, and Check again beside it. The
        # button stood below every block before, which is off the screen on
        # the machine that has something to repair.
        card = self._card(outer)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(ROW_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        inner.columnconfigure(0, weight=1)
        self.parts_line = ttk.Label(inner, style="Section.TLabel")
        self.parts_line.grid(row=0, column=0, sticky="w")
        ttk.Button(inner, text="Check again", style="Outlined.TButton",
                   command=self.refresh_status).grid(row=0, column=1,
                                                     sticky="e")

        self.parts_box = ttk.Frame(outer, style="Page.TFrame")
        self.parts_box.pack(fill="x", pady=(0, GROUP_GAP))
        return outer

    def _read_parts(self):
        """Ask every part how it is. One place, so the page and the headline
        cannot disagree about it.
        """
        checks = ledpanel.run_checks(config=self.config)
        self._checks = checks           # kept for the foot of the window
        return [
            ledpanel.led_part(checks, self._module_here("led")),
            ledpanel.power_part(self.power, power.available()),
            ledpanel.gpu_part(self._gpu, self._gpu_error,
                              available=lact.available(),
                              asked=self._gpu_asked),
            ledpanel.cec_part(self._cec, cec.installed(), SOURCE_DIR),
            ledpanel.layout_part(self.system.get(syssettings.LAYOUT, ""),
                                 dict((value, label) for label, value
                                      in syssettings.layouts())),
            # The installation itself, against what this project wrote. It
            # is last because it is the widest: a fault here usually
            # explains one of the cards above it. See checkup.py.
            ledpanel.install_part(here=modules.here()),
            ledpanel.panel_part(VERSION, getattr(self, "_update_state", None),
                                self.update_state.cget("text")
                                if hasattr(self, "update_state") else "",
                                ledpanel.install_is_behind(SOURCE_DIR),
                                head=ledpanel.head_commit(SOURCE_DIR)),
        ]

    def _light(self, parent, ok):
        """The three-state indicator of one part. Grey is "not installed"."""
        colour = (self.roles["on_surface_variant"] if ok is None
                  else self.roles["positive"] if ok
                  else self.roles["error"])
        dot = tk.Canvas(parent, width=STATUS_DOT * 2, height=STATUS_DOT * 2,
                        highlightthickness=0, borderwidth=0,
                        background=self.roles["surface_container_lowest"])
        dot.create_oval(1, 1, STATUS_DOT * 2 - 1, STATUS_DOT * 2 - 1,
                        width=0, fill=colour)
        return dot

    def _build_part(self, part):
        """One block for a part with a fault: a light, a sentence, a fold,
        and its own repair.
        """
        card = self._card(self.parts_box)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(ROW_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        inner.columnconfigure(1, weight=1)

        self._light(inner, part.ok).grid(row=0, column=0, sticky="w",
                                         padx=(0, ROW_GAP))
        ttk.Label(inner, text=part.name, style="Section.TLabel").grid(
            row=0, column=1, sticky="w")

        buttons = ttk.Frame(inner, style="OnCard.TFrame")
        buttons.grid(row=0, column=2, sticky="e")
        if part.detail:
            fold = ttk.Button(buttons, style="Text.TButton",
                              command=lambda k=part.key: self._fold_part(k))
            fold.configure(text="Details \u25b4" if part.key in self._open_parts
                           else "Details \u25be")
            fold.pack(side="left", padx=(0, ROW_GAP))
            self._fold_buttons.add(str(fold))
            self._fold_arrows[part.key] = fold
        if part.repair:
            ttk.Button(buttons, text=ledpanel.REPAIR_LABELS[part.repair],
                       style="Tonal.TButton",
                       command=lambda r=part.repair: self._repair(r)).pack(
                           side="left")

        said = ttk.Label(inner, text=part.verdict, justify="left",
                         style="Bad.TLabel",
                         wraplength=CARD_WRAP - PART_INDENT)
        said.grid(row=1, column=1, columnspan=2, sticky="w", pady=(2, 0))
        self._wrapped.append(said)
        self._wrap_insets[str(said)] = PART_INDENT

        if part.detail:
            # This code builds the detail for each block and hides a closed
            # one with grid_remove. Before, an open fold read the complete
            # machine again and built each block again. See _fold_part. That
            # is much work for a paragraph that this code already made. It
            # also moved the one widget that survives a rebuild, the Check
            # again button, over an area that Tk destroyed and did not draw
            # again. A user reported a button in pieces until the pointer
            # touched it.
            holder = self._build_part_detail(inner, part)
            self._part_details[part.key] = holder
            if part.key not in self._open_parts:
                holder.grid_remove()

    def _build_rest(self, parts, headed=False):
        """One card for the parts with no fault, one row for each.

        A row carries the same light and the same sentence as a block. Its
        checks and its repair are behind the fold, because a part that
        reports no fault needs neither to be read.
        """
        card = self._card(self.parts_box)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(ROW_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        # The empty column at the end takes the free width, so each Details
        # button stands beside its own sentence and not at the card edge.
        inner.columnconfigure(4, weight=1)

        at = 0
        if headed:
            ttk.Label(inner, text="The rest", style="Section.TLabel").grid(
                row=0, column=0, columnspan=5, sticky="w", pady=(0, ROW_GAP))
            at = 1
        for part in parts:
            self._light(inner, part.ok).grid(row=at, column=0, sticky="nw",
                                             padx=(0, ROW_GAP), pady=2)
            ttk.Label(inner, text=part.name).grid(
                row=at, column=1, sticky="nw", pady=2, padx=(0, GROUP_GAP))
            said = ttk.Label(inner, text=part.verdict, style="Muted.TLabel",
                             justify="left", wraplength=CARD_WRAP)
            said.grid(row=at, column=2, sticky="nw", pady=2)
            self._wrapped.append(said)
            # Its own position, because the name column takes the width of the
            # longest name and that width is the font's. See _inset_of. With
            # the room its Details button takes, which stands beside it.
            self._wrap_insets[str(said)] = (said, FOLD_ROOM)
            if not (part.detail or part.repair):
                at += 1
                continue
            fold = ttk.Button(inner, style="Text.TButton",
                              command=lambda k=part.key: self._fold_part(k))
            fold.configure(text="Details \u25b4" if part.key in self._open_parts
                           else "Details \u25be")
            fold.grid(row=at, column=3, sticky="nw", padx=(ROW_GAP, 0))
            self._fold_buttons.add(str(fold))
            self._fold_arrows[part.key] = fold
            holder = self._build_part_detail(inner, part, row=at + 1,
                                             column=2, span=3, repair=True)
            self._part_details[part.key] = holder
            if part.key not in self._open_parts:
                holder.grid_remove()
            at += 2

    def _build_part_detail(self, inner, part, row=2, column=1, span=2,
                           repair=False):
        """What is behind a block, which is a list of Checks or of lines.

        Returns the frame so the fold can show and hide it without this
        having to run again. A compact row places it one row lower and one
        column further in, under its own sentence, and asks for the repair
        here because it has no room of its own for that button.
        """
        holder = ttk.Frame(inner, style="OnCard.TFrame")
        holder.grid(row=row, column=column, columnspan=span, sticky="ew",
                    pady=(ROW_GAP, 0))
        holder.columnconfigure(2, weight=1)
        for line, item in enumerate(part.detail or ()):
            if isinstance(item, str):
                # A plain line, from a part that has no checks of its own.
                ttk.Label(holder, text=item, style="Muted.TLabel").grid(
                    row=line, column=0, columnspan=3, sticky="w", pady=2)
                continue
            ttk.Label(holder, text="\u2713" if item.ok else "\u2717", width=3,
                      style="Good.TLabel" if item.ok else "Bad.TLabel").grid(
                          row=line, column=0, sticky="nw", pady=2)
            # Each column at the top of its row. The third column wraps, so a
            # mark and a name that centre themselves against it stand beside
            # the wrong line of it.
            ttk.Label(holder, text=item.name,
                      style="TLabel" if item.ok else "Bad.TLabel").grid(
                          row=line, column=1, sticky="nw", pady=2,
                          padx=(0, GROUP_GAP))
            if not item.ok:
                ttk.Label(holder, text=item.detail, wraplength=460,
                          justify="left", style="Muted.TLabel").grid(
                              row=line, column=2, sticky="nw", pady=2)
        if repair and part.repair:
            # The repair of a part that has no block of its own. A part with
            # a block carries it beside the fold instead.
            ttk.Button(holder, text=ledpanel.REPAIR_LABELS[part.repair],
                       style="Tonal.TButton",
                       command=lambda r=part.repair: self._repair(r)).grid(
                           row=len(part.detail or ()), column=0, columnspan=3,
                           sticky="w", pady=(ROW_GAP, 0))
        return holder

    def _fold_part(self, key):
        """Show or hide one block's detail. Nothing else.

        Not refresh_status(), which reads the whole machine again and rebuilds
        every block to show a paragraph that already exists.

        That rebuild also left an artefact. The Check again button survives
        it, and the taller page moves it over an area Tk destroyed and did not
        paint again. X copies the pixels of a window that moves, so the button
        arrived carrying half its own label.
        """
        self._open_parts.symmetric_difference_update({key})
        holder = self._part_details.get(key)
        if holder is not None:
            if key in self._open_parts:
                holder.grid()
            else:
                holder.grid_remove()
        arrow = self._fold_arrows.get(key)
        if arrow is not None:
            arrow.configure(text="Details \u25b4" if key in self._open_parts
                            else "Details \u25be")
        self._refit_page()
        self._fit_window()

    def _repair(self, name):
        """Run the repair a block offers. Named rather than bound, so the
        model can say which repair a part has without knowing this window.
        """
        if name == "reinstall":
            self.reinstall()
        elif name == "install-cec":
            self._install_cec()

    def refresh_status(self):
        """Read every part again and draw the page from what they said."""
        for child in self.parts_box.winfo_children():
            child.destroy()
        self._forget_dead_labels()
        self._fold_buttons = set()
        self._part_details = {}
        self._fold_arrows = {}
        parts = self._read_parts()
        self.parts_line.configure(text=ledpanel.parts_count(parts))
        for part in parts:
            if part.ok is False:
                self._build_part(part)
        rest = [part for part in parts if part.ok is not False]
        if rest:
            self._build_rest(rest, headed=len(rest) < len(parts))
        # The blocks' buttons are new widgets every time, so the list of what
        # to grey while a command runs has to be taken again.
        self._register_buttons()
        # What they said, for the line under the title. That line follows the
        # open page, and a page opens far more often than the parts change.
        self._parts = parts
        self._say_headline()
        broken = [part for part in parts if part.ok is False]
        # A part that is broken unfolds itself, once. Left folded, the page
        # would say something is wrong and hide what.
        for part in broken:
            if part.detail and part.key not in self._shown_parts:
                self._shown_parts.add(part.key)
                self._open_parts.add(part.key)
                self.root.after_idle(self.refresh_status)
        self._rewrap_parts()

    def _say_headline(self):
        """One line below the title, for the page that is open now.

        It counts each part and reports the open page when that page has
        something to report. See ledpanel.summary_for. A part that is only
        absent gets neither a good nor a bad colour: "Not installed." in green
        is a contradiction, and in red it reports a fault on a machine that
        does not want the function.

        It reads the parts of the last status read and does not read them
        again. The checks call systemctl, lsmod and LACT, and a person who
        walks down the sidebar would wait for all of them at each step.

        A function of its own, because refresh_status held it and runs at the
        start and at Check again. The line then named the page that was open
        at the last read.
        """
        parts = getattr(self, "_parts", None)
        if not parts:
            return
        broken = [part for part in parts if part.ok is False]
        section = getattr(self, "section", "") or ""
        mine = next((part for part in parts
                     if part.key == ledpanel.SECTION_PARTS.get(section,
                                                               section)), None)
        self.headline.configure(
            text=ledpanel.summary_for(parts, section),
            style="Page.Muted.TLabel" if mine is not None and mine.ok is None
            else "Page.Bad.TLabel" if broken or (mine is not None
                                                 and mine.ok is False)
            else "Page.Good.TLabel")

    def _rewrap_parts(self):
        """Give the blocks' sentences the width the page has.

        This code builds them after the last resize, so they have no width
        from the page. _rewrap runs only after a change of the width, and the
        width did not change.
        """
        self._set_wrapping()

    def reinstall(self):
        if not os.path.exists(os.path.join(SOURCE_DIR, "install.sh")):
            self._say("Repair",
                      "install.sh is not next to this panel (%s).\nRepairing "
                      "needs the cloned repository." % SOURCE_DIR)
            return
        if not self._ask(
                "Repair", "Your configuration is kept and the ESP is not "
                          "touched. This asks for your password.",
                confirm="Re-run the installer"):
            return
        # Not _installed: this repairs with the files that are already here,
        # so the panel is not out of date and has no reason to offer a
        # restart.
        self.runner.start(ledpanel.reinstall_command(SOURCE_DIR),
                          lambda _code: self._after_install())
