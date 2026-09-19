# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The half of every module page that is about the module itself.

Each module of this project arrives and leaves from its own page, and not
from one list of modules in a fifth place. A person who wants the LED bar
looks at the LED bar's page, reads what it brings, and presses the button
there.

So a module page is two pages in one frame and the machine decides which one
is packed: an offer to install, or the page itself with a line above it that
takes the module off again. This file builds both halves and switches
between them.

Both are built when the window opens, because somebody can install a module
while the window is open.

It is a mixin and not a widget. Panel takes it as a base, so every method
here is a method of Panel and `self` is the window. Three of the pages call
into it, which one name on one object is what makes possible.

What stays in the window: _reread_module_settings, which reads the four
settings files after a module arrived or left. That is the window's own
settings state and not this bar.
"""

from __future__ import annotations

from tkinter import ttk

import dialogs
import ledpanel

from panelbase import CARD_WRAP, GROUP_GAP, ROW_GAP, SIDE_MARGIN, SOURCE_DIR


class ModulePage:
    """The methods of that half. See the note at the top of this file."""

    def _read_modules(self):
        """Asks the machine which modules it has. See modules.py."""
        self._modules_here = frozenset(ledpanel.modules_here())

    def _module_here(self, name):
        return name in self._modules_here

    def _module_page(self, parent, name, build):
        """One section, with the offer to install its module in front of it."""
        outer = ttk.Frame(parent, style="Page.TFrame")
        present = ttk.Frame(outer, style="Page.TFrame")
        self._build_module_line(present, name)
        build(present).pack(fill="both", expand=True)
        self._module_halves[name] = (self._build_module_offer(outer, name),
                                     present)
        self._show_module(name)
        return outer

    def _build_module_offer(self, parent, name):
        """What the page holds before its module is installed.

        It says what the module does, what it puts on the machine, and what it
        needs, rather than only offering a button. A person decides here, and
        "install failed" three minutes later is a worse way to find out that
        the machine has no board on it.

        The words are in server/steamos_utility_center/modules.py, so this page
        and `./install.sh --modules` say the same thing.
        """
        holder = ttk.Frame(parent, style="Page.TFrame")
        card = self._card(holder)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(ROW_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)

        said = ledpanel.module_says(name)
        ttk.Label(inner, text="Not installed yet",
                  style="Section.TLabel").pack(anchor="w")
        for text in (said["does"], "Installs " + said["brings"],
                     "Needs " + said["needs"]):
            line = ttk.Label(inner, text=text, style="Muted.TLabel",
                             justify="left", wraplength=CARD_WRAP)
            line.pack(anchor="w", pady=(ROW_GAP, 0))
            self._wrapped.append(line)

        row = ttk.Frame(inner, style="OnCard.TFrame")
        row.pack(anchor="w", pady=(GROUP_GAP, 0))
        ttk.Button(row, text="Install %s" % said["title"],
                   style="Filled.TButton",
                   command=lambda: self._install_module(name)).pack(side="left")
        ttk.Button(row, text="Check again", style="Text.TButton",
                   command=self._reread_modules).pack(side="left",
                                                      padx=(ROW_GAP, 0))
        return holder

    def _build_module_line(self, parent, name):
        """The card at the head of a page whose module is installed.

        A name and a button, and no prose at all. The description belongs to
        a person who must decide, and that person reads the other half of
        this page. Somebody who opens this page every day must not read the
        same paragraph every day.
        """
        said = ledpanel.module_says(name)
        card = self._card(parent)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(ROW_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        inner.columnconfigure(0, weight=1)
        ttk.Label(inner, text="%s module" % said["title"],
                  style="Section.TLabel").grid(row=0, column=0, sticky="w")
        # At the far end of the line, where a rare and deliberate button
        # belongs. It is not a setting of this page, and a place among the
        # settings would read as one.
        #
        # "Remove module" and not "Remove %s". The System page has a Remove
        # button on each drive, so one word alone is two buttons a person
        # must tell apart. The name of the module was in the button before,
        # and "Drives, controller wake and Game Mode" is 366 pixels of it:
        # the heading and the button together measured 977 against a card of
        # about 950 at the font of somebody else's desktop, and the button
        # was drawn over the end of the heading. The heading already names
        # the module, one line above.
        ttk.Button(inner, text="Remove module", style="Text.TButton",
                   command=lambda: self._remove_module(name)).grid(
                       row=0, column=1, sticky="e")
        # And no line of prose under it. The offer above says what the module
        # does, which is where a person decides. Somebody who reads this card
        # has the module already.
        return card

    def _show_module(self, name):
        """Pack whichever half the machine justifies."""
        halves = self._module_halves.get(name)
        if halves is None:
            return
        here = self._module_here(name)
        for half, wanted in ((halves[1], here), (halves[0], not here)):
            if wanted:
                half.pack(fill="both", expand=True)
            else:
                half.pack_forget()

    def _reread_modules(self):
        """Reads the machine again and shows the right half of each page."""
        self._read_modules()
        for name in self._module_halves:
            self._show_module(name)
        # The Apply row belongs to the settings that are on screen, and a
        # module that went away took its settings with it.
        self._catch_up()
        self._refit_page()

    def _install_module(self, name):
        said = ledpanel.module_says(name)
        if not self._ask(said["title"],
                         "This installs the %s module and asks for your "
                         "password once.\n\nIt installs %s"
                         % (said["title"], said["brings"]),
                         confirm="Install"):
            return
        self.runner.start(ledpanel.module_command(SOURCE_DIR, name),
                          lambda _code: self._module_changed(name))

    def _ask_remove(self, name):
        """Asks about a removal, and returns (go ahead, take the settings).

        A seam beside _ask, which answers one question and cannot carry the
        second. Everything that opens a window is behind one of these, so a
        test can answer for a person.
        """
        # self.root and not self. Panel is a plain object that holds the Tk
        # root; it is not a widget, so tkinter finds no interpreter on it and
        # a press raised AttributeError into the terminal. Every other dialog
        # here is built on self.root. See DialogParentTest.
        asked = dialogs.RemoveDialog(self.root, ledpanel.module_says(name))
        return bool(asked.answer), bool(asked.purge.get())

    def _remove_module(self, name):
        """The settings are a question here and not a sentence.

        They stayed either way before, and the dialog said so. Files that
        stay after a removal are a surprise when the only choice is somebody
        else's.
        """
        go, purge = self._ask_remove(name)
        if not go:
            return
        self.runner.start(
            ledpanel.module_command(SOURCE_DIR, name, remove=True,
                                    purge=purge),
            lambda _code: self._module_changed(name))

    def _module_changed(self, name):
        """After a module arrived or left. The page and the status both move."""
        self._reread_module_settings(name)
        self._reread_modules()
        if name == "cec":
            self._reread_cec()
        self._after_install()
