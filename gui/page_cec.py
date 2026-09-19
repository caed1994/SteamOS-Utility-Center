# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The HDMI CEC page of the control panel.

The window was one class of five thousand lines, and this is the first page
to move out of it. Nothing here is rewritten: the methods are the methods
that were in Panel, with the comments they carried.

A mixin and not an object of its own. Panel inherits it, so every method is
still a method of the window and `self` is still the window. The tests call
these by name on the panel, and they keep working without a line of change.
That is the whole reason for this shape: a cut that costs the tests nothing
is a cut that can be checked by running them.

What it needs from the window, it takes through `self`: the cards, the
fields, the runner and the rest. What it needs from the module around it is
in gui/panelbase.py, because a page cannot import the window that imports it.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import ledpanel

# The same spelling the window uses. The path to it is set by the window
# before it imports this file, from the toolbox that gui/panelbase.py names.
from steamos_utility_center import cec

from panelbase import (CARD_WRAP, CEC_INDENT, GROUP_GAP, ROW_GAP,
                       SIDE_MARGIN, SOURCE_DIR)


class CecPage:
    """The HDMI CEC page. Panel inherits it; it is never made on its own."""

    def _build_cec(self, parent):
        """Talking to the television, if the toolkit for it is installed.

        Two pages in one frame, and the machine decides which one a person
        sees: an offer to install, or the switches. Both are built now and one
        is packed, because somebody can install the toolkit while the window
        is open. See _show_cec.

        Nothing here waits for Apply. The toolkit's installer leaves a sudoers
        rule for its own helpers, so each switch is an ordinary command that
        runs at the click. The settings pages wait because a write to /etc
        needs a password and a restart of the service.
        """
        outer = ttk.Frame(parent, style="Page.TFrame")
        self._cec = None                    # the last status read, or None
        self._cec_asked = False             # True after the first read
        self._cec_vars = {}
        self._cec_rows = {}
        self._cec_entries = {}
        # The settings with a menu and not with a typed value. These are
        # separate from the text boxes, because a drop-down of this window
        # holds the label and the file needs the value. See _value_for.
        self._cec_menus = {}
        # True while this code sets the switches from a status read. Without
        # it, a write to a variable starts the same handler as a click, and a
        # refresh after one change changes each switch again.
        self._cec_settling = False
        # Which of the folding cards on this page are open. Empty, so both
        # start closed. See _folding_card.
        self._cec_open = set()
        self._cec_folds = {}

        self.cec_missing = self._build_cec_offer(outer)
        self.cec_present = self._build_cec_switches(outer)
        self._show_cec()
        return outer

    def _build_cec_offer(self, parent):
        """What is there before any of it is installed.

        It says what the feature is and what the machine is missing for it,
        rather than only offering the button. Every requirement here is
        somebody else's package, and "install failed" three minutes later is a
        worse way to find out that v4l-utils is not on the machine.
        """
        holder = ttk.Frame(parent, style="Page.TFrame")
        card = self._card(holder)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(ROW_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)

        ttk.Label(inner, text="Not installed yet", style="Section.TLabel").pack(anchor="w")
        # The same three sentences as the other three modules, from the same
        # place. See _build_module_offer and modules.py. The fourth line is
        # this page's own: nothing here switches itself on.
        module = ledpanel.module_says("cec")
        for text in (module["does"], "Installs " + module["brings"],
                     "Needs " + module["needs"],
                     "Nothing is switched on by installing it. Each feature "
                     "gets a switch here afterwards."):
            said = ttk.Label(inner, text=text, style="Muted.TLabel", justify="left",
                             wraplength=CARD_WRAP)
            said.pack(anchor="w", pady=(ROW_GAP, 0))
            self._wrapped.append(said)

        # What the machine has not got, asked of the machine. A list written
        # down here would be a list that is wrong on the next SteamOS.
        self.cec_needs = ttk.Label(inner, style="Bad.TLabel", justify="left",
                                   wraplength=CARD_WRAP)
        self._wrapped.append(self.cec_needs)

        row = ttk.Frame(inner, style="OnCard.TFrame")
        row.pack(anchor="w", pady=(GROUP_GAP, 0))
        ttk.Button(row, text="Install HDMI CEC", style="Filled.TButton",
                   command=self._install_cec).pack(side="left")
        ttk.Button(row, text="Check again", style="Text.TButton",
                   command=self._reread_cec).pack(side="left",
                                                  padx=(ROW_GAP, 0))
        return holder

    def _build_cec_switches(self, parent):
        """The page once it is installed: what works, what is on, and a try."""
        holder = ttk.Frame(parent, style="Page.TFrame")

        # The adapter first. Each switch below needs it. When nothing works,
        # this line gives the reason.
        card = self._card(holder)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(ROW_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        ttk.Label(inner, text="The adapter", style="Section.TLabel").pack(anchor="w")
        self.cec_adapter = ttk.Label(inner, justify="left",
                                     wraplength=CARD_WRAP)
        self.cec_adapter.pack(anchor="w", pady=(ROW_GAP, 0))
        self._wrapped.append(self.cec_adapter)
        row = ttk.Frame(inner, style="OnCard.TFrame")
        row.pack(anchor="w", pady=(GROUP_GAP, 0))
        ttk.Button(row, text="Check again", style="Tonal.TButton",
                   command=self._reread_cec).pack(side="left")
        ttk.Button(row, text="Remove HDMI CEC", style="Text.TButton",
                   command=self._remove_cec).pack(side="left",
                                                  padx=(ROW_GAP, 0))
        self._build_cec_features(holder)
        self._build_cec_actions(holder)
        self._build_cec_config(holder)
        return holder

    def _build_cec_features(self, parent):
        """One switch per feature, each with the sentence that explains it.

        Explained rather than only named, and at more length than the settings
        pages bother with, because these are switches whose effect is on the
        television and on whether the machine goes to sleep. "TV standby
        suspend" is a label somebody can only find out the meaning of by
        turning it on and losing their session.
        """
        card = self._card(parent)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(GROUP_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        ttk.Label(inner, text="Features", style="Section.TLabel").pack(anchor="w", pady=(0, ROW_GAP))

        # What this card is beside the switches of SteamOS itself.
        #
        # Without it a person turns one of these off, the machine goes on
        # sleeping when the television does, and the fault looks like ours.
        # It is the switch of SteamOS that acts. See cec.STEAM_OWN.
        overlap = ttk.Label(
            inner, style="Muted.TLabel", justify="left",
            wraplength=CARD_WRAP,
            text="SteamOS has switches of its own under %s. This "
                 "installation is what makes them work: its daemon is "
                 "refused the adapter after a boot, and the toolkit repairs "
                 "that. The features marked below are in SteamOS as well. "
                 "Ours are the second answer, for a television that the "
                 "switch of SteamOS turns on and does not move."
                 % cec.STEAM_SETTINGS)
        overlap.pack(anchor="w", pady=(0, GROUP_GAP))
        self._wrapped.append(overlap)

        for index, (name, _kind, label, said) in enumerate(cec.FEATURES):
            block = ttk.Frame(inner, style="OnCard.TFrame")
            block.pack(fill="x", pady=(0 if index == 0 else GROUP_GAP, 0))
            block.columnconfigure(1, weight=1)
            variable = tk.BooleanVar(value=False)
            # The name is a label of its own and not the text of the switch.
            # ttk leaves no space between the picture of a switch and its own
            # label. A measurement showed that the two touched. The switch
            # also must not set that space. Each other switch in this window
            # has its name in the column beside it, and this matches them.
            switch = ttk.Checkbutton(
                block, variable=variable,
                command=lambda n=name: self._cec_toggled(n))
            switch.grid(row=0, column=0, sticky="w")
            named = ttk.Label(block, text=label)
            named.grid(row=0, column=1, sticky="w", padx=(ROW_GAP, 0))
            # Under the name and not beside it: at this length beside it would
            # set the column of switches against a ragged wall of text, and
            # the page would stop reading as a list of switches.
            explain = ttk.Label(block, text=said, style="Muted.TLabel",
                                justify="left",
                                wraplength=CARD_WRAP - CEC_INDENT)
            explain.grid(row=1, column=1, sticky="w", padx=(ROW_GAP, 0),
                         pady=(2, 0))
            self._wrapped.append(explain)
            # Under the name, so the name is what says how far in it starts -
            # which is the switch's own width, and that is the font's.
            self._wrap_insets[str(explain)] = named
            # And the mark, for a feature that SteamOS has as well. Under the
            # explanation rather than beside the name: the name is what the
            # eye runs down, and a suffix on it would break that column.
            if name in cec.STEAM_OWN:
                also = ttk.Label(block, style="Muted.TLabel", justify="left",
                                 wraplength=CARD_WRAP - CEC_INDENT,
                                 text="SteamOS does this too.")
                also.grid(row=2, column=1, sticky="w", padx=(ROW_GAP, 0),
                          pady=(2, 0))
                self._wrapped.append(also)
                self._wrap_insets[str(also)] = named
            self._cec_vars[name] = variable
            self._cec_rows[name] = (switch, named, explain)

        # This collects the switches and sends them together. One switch does
        # not act at its click. Each of these switches starts or stops a unit,
        # and one half of them control the suspend behaviour of the machine. A
        # row of switches in one pass is therefore a set of decisions that the
        # user made together. The user also corrects an accidental click with
        # a second click, and does not wait for a service to stop and start.
        # The settings below already work in this way.
        self.cec_apply = ttk.Button(inner, text="Apply", style="Tonal.TButton",
                                    command=self._apply_cec_features)
        self.cec_apply.pack(anchor="w", pady=(GROUP_GAP, 0))
        # The cost of these switches after the adapter goes away. This line
        # comes only for that condition. It is here and not on the status page
        # alone, because the switches are here. See adapter_gone_cost.
        #
        # In the error colour rather than the muted one every other
        # explanation on this page wears: those describe what a switch does
        # and are there to be read once, this one is a bill being run up
        # right now. _note is still what builds it, so it wraps with the rest.
        self.cec_cost = self._note(inner, "")
        self.cec_cost.configure(style="Bad.TLabel")
        self._cec_changed()

    def _say_cec_cost(self):
        """Show the price of an adapter that is out with the features on.

        Packed and unpacked rather than emptied: a label with no text still
        takes a line, and a card that grows a blank row when nothing is wrong
        is a card that looks broken.
        """
        said = ledpanel.adapter_gone_cost(self._cec)
        self.cec_cost.configure(text=said)
        if said:
            self.cec_cost.pack(anchor="w", pady=(GROUP_GAP, 0))
        else:
            self.cec_cost.pack_forget()

    def _folding_card(self, parent, key, title, pady=None):
        """A card whose content one press shows or hides. Returns the holder.

        The caller fills what comes back and knows nothing else about the
        fold. The title stays whatever the fold says, so a closed card is
        still a card with a name and not a gap.

        Both cards that use this hold a job that is done one time: a
        television that answers, and three settings whose value is right
        after the first try. They were two thirds of the page afterwards.

        The fold is the one the Status page uses, in the words that page
        uses. A second shape for one question is a second thing to learn.
        """
        card = self._card(parent)
        card.pack(fill="x", padx=SIDE_MARGIN,
                  pady=pady if pady is not None else (GROUP_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        head = ttk.Frame(inner, style="OnCard.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text=title, style="Section.TLabel").pack(side="left")
        arrow = ttk.Button(head, style="Text.TButton",
                           command=lambda k=key: self._fold_cec_card(k))
        arrow.pack(side="right")
        holder = ttk.Frame(inner, style="OnCard.TFrame")
        self._cec_folds[key] = (holder, arrow)
        self._show_cec_fold(key)
        return holder

    def _show_cec_fold(self, key):
        """Put one card in the state the set says, and name that state."""
        holder, arrow = self._cec_folds[key]
        if key in self._cec_open:
            holder.pack(fill="x", pady=(ROW_GAP, 0))
            arrow.configure(text="Hide \u25b4")
        else:
            holder.pack_forget()
            arrow.configure(text="Show \u25be")

    def _fold_cec_card(self, key):
        """Show or hide one card. Nothing else is read and nothing rebuilt."""
        self._cec_open.symmetric_difference_update({key})
        self._show_cec_fold(key)
        self._refit_page()
        self._fit_window()

    def _build_cec_actions(self, parent):
        """Four things that happen once and leave nothing behind.

        Which is what makes them the way to find out whether any of this
        reaches the television, before switching on a feature and rebooting
        into it to see.
        """
        inner = self._folding_card(parent, "actions", "Try it")
        self._buttons(inner, [
            (label, lambda k=key: self._cec_action(k))
            for key, label, _tail in cec.ACTIONS])

    def _build_cec_config(self, parent):
        """The three settings whose wrong value stops all of it working.

        These are three of approximately forty settings. The other settings
        are timings and report bytes for one television or one controller.
        They belong in the file, where each of them has its own paragraph of
        explanation. On a page here they are forty rows with no context.
        """
        inner = self._folding_card(parent, "config", "Configuration",
                                   pady=(GROUP_GAP, GROUP_GAP))

        grid = ttk.Frame(inner, style="OnCard.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        for row, (key, label, said, choices) in enumerate(cec.SHOWN):
            ttk.Label(grid, text=label).grid(
                row=row * 2, column=0, sticky="w",
                padx=(0, GROUP_GAP), pady=(0 if row == 0 else ROW_GAP, 0))
            if choices:
                # A field of this file and not a combobox, for the reasons in
                # _field. It also accepts a value from the file that the list
                # does not offer. A set of radio buttons cannot do that.
                variable = tk.StringVar()
                widget = self._field(grid, key, variable, choices,
                                     choices[0][1])
                self._cec_menus[key] = variable
            else:
                widget = ttk.Entry(grid, style="Material.TEntry")
                self._cec_entries[key] = widget
            widget.grid(row=row * 2, column=1,
                        sticky="w" if choices else "ew",
                        pady=(0 if row == 0 else ROW_GAP, 0))
            explain = ttk.Label(grid, text=said, style="Muted.TLabel", justify="left",
                                wraplength=CARD_WRAP - CEC_INDENT)
            explain.grid(row=row * 2 + 1, column=1, sticky="w", pady=(2, 0))
            self._wrapped.append(explain)
            # Under the box, and the column of setting names in front of it is
            # a good deal wider than the switch CEC_INDENT was measured from.
            self._wrap_insets[str(explain)] = widget

        ttk.Button(inner, text="Save these", style="Tonal.TButton",
                   command=self._save_cec_config).pack(anchor="w",
                                                       pady=(GROUP_GAP, 0))
        said = self._note(
            inner,
            "Discovery asks the bus and the sound server what is actually "
            "there and fills these in, which is easier than reading them off "
            "the television.")
        said.pack(anchor="w", pady=(GROUP_GAP, ROW_GAP))
        self._buttons(inner, [
            (label, lambda k=key: self._cec_action(k))
            for key, label, _said in cec.DISCOVERIES])

    # -- what the CEC page does -------------------------------------------

    def _show_cec(self):
        """Pack whichever half the last status read justifies."""
        there = self._cec is not None
        for half, wanted in ((self.cec_present, there),
                             (self.cec_missing, not there)):
            if wanted:
                half.pack(fill="both", expand=True)
            else:
                half.pack_forget()
        if there:
            self._say_cec_adapter()
            self._settle_cec_switches()
            self._say_cec_cost()
        else:
            self._say_cec_needs()
        # The foot of the window reports the same adapter from every page, so
        # it is redrawn by whatever redrew this one.
        # The height of its page also changed. See _refit_page.
        self._refit_page()

    def _say_cec_needs(self):
        """Name what the machine has not got, or say nothing when it has."""
        absent = cec.missing()
        if not absent:
            self.cec_needs.pack_forget()
            return
        self.cec_needs.configure(text="Missing on this machine: " + "; ".join(
            "%s (%s)" % (name, why) for name, why in absent))
        self.cec_needs.pack(anchor="w", pady=(ROW_GAP, 0))

    def _say_cec_adapter(self):
        """One line about the adapter, in the colour the news deserves.

        Three states rather than two, because "there but not writable" is a
        different problem with a different fix: the toolkit ships a helper and
        a udev rule for exactly that, and it is what a suspend or a SteamOS
        update leaves behind.
        """
        found = cec.device(self._cec)
        where = found.get("device") or "no adapter configured"
        if cec.usable(self._cec):
            said, style = "Ready on %s." % where, "Good.TLabel"
        elif found.get("exists"):
            said = ("%s is there but this user cannot write to it, so nothing "
                    "can be sent. Reinstalling puts the permissions helper "
                    "and its udev rule back." % where)
            style = "Bad.TLabel"
        else:
            said = ("%s is not there. HDMI CEC needs an adapter the kernel "
                    "exposes as a /dev/cec device - the machine's own HDMI or "
                    "DisplayPort output usually is not one." % where)
            style = "Bad.TLabel"
        self.cec_adapter.configure(
            text=said, style=style)

    def _settle_cec_switches(self):
        """Sets each switch and box to the value that the machine reports.

        This function sets them from the status and does not leave them at the
        position of the click. The machine can refuse a change. An absent
        helper does that, and a unit that does not start does that. A switch
        that stays at the position of the click then reports the opinion of
        this window and not the state of the machine.
        """
        self._cec_settling = True
        try:
            for name, variable in self._cec_vars.items():
                variable.set(cec.feature_on(self._cec, name))
        finally:
            self._cec_settling = False
        values = cec.config(self._cec)
        for key, entry in self._cec_entries.items():
            entry.delete(0, "end")
            entry.insert(0, values.get(key, ""))
        # A setting that is not in the file has the default value of the
        # toolkit, and that value is the first entry of the list. The field
        # then opens on the behaviour of the machine and not on nothing.
        fallbacks = dict((key, choices[0][1])
                         for key, _l, _s, choices in cec.SHOWN if choices)
        for key, variable in self._cec_menus.items():
            variable.set(self._label_for(
                key, values.get(key) or fallbacks.get(key, "")))
        # The switches now stand where the machine has them, so there is
        # nothing left to apply.
        self._cec_changed()

    def _reread_cec(self, then=None):
        """Ask the toolkit about itself again, and redraw from the answer."""
        try:
            self._cec = ledpanel.cec_status()
        except cec.CecError as exc:
            self._cec = None
            self._write("The CEC toolkit could not be read: %s\n\n" % exc)
        self._cec_asked = True
        self._show_cec()
        # The status page and the line below the title read this same answer
        # through _read_parts, so a change here makes both of them old.
        #
        # Here and not in each caller. The first read runs after the window
        # opens, and until then a toolkit with no read counts as "installed,
        # but it will not say how it is". One place cannot forget the call.
        self.refresh_status()
        if then is not None:
            then()

    def _catch_up_cec(self):
        """Read the status the first time the section is opened, not before.

        This code builds the page of each section with the window. A read at
        the build step therefore starts a subprocess at each start of the
        window and at each change of the theme. Most users never open this
        page.
        """
        if not self._cec_asked:
            self._reread_cec()

    def _cec_toggled(self, _name):
        """A switch was clicked. Nothing reaches the machine until Apply."""
        if self._cec_settling:
            return                          # we are the ones who set it
        self._cec_changed()

    def _cec_pending(self):
        """The switches that are not where the machine has them.

        Asked of the status rather than remembered from the clicks, so a
        switch turned on and off again is no change at all rather than two.
        """
        if self._cec is None:
            # There is no status yet. This occurs at the build step, and on a
            # machine with a toolkit that does not answer. There is no value
            # for a comparison, so there is nothing to apply.
            return []
        return [(name, bool(variable.get()))
                for name, variable in self._cec_vars.items()
                if bool(variable.get()) != cec.feature_on(self._cec, name)]

    def _cec_changed(self):
        """Let Apply be pressed only when there is something to apply."""
        button = getattr(self, "cec_apply", None)
        if button is None:
            return                          # the page is still being built
        button.state(["!disabled"] if self._cec_pending() else ["disabled"])

    def _apply_cec_features(self):
        self._run_cec_toggles(self._cec_pending())

    def _run_cec_toggles(self, left):
        """One switch at a time, because the runner holds one command.

        This function runs them in a chain and does not start them together.
        Each of them is a systemctl call through a helper. With two at the
        same time, the Runner refuses the second one. See Runner.start. One
        half of the page is then applied, with no report of which half.
        """
        if not left:
            self._reread_cec()
            return
        name, wanted = left[0]
        self._write("%s %s...\n" % ("Turning on" if wanted else "Turning off",
                                    cec.BY_NAME[name][1]))
        # The wake after a resume is a unit of root and goes through a
        # program that the sudoers rule permits. Where there is no rule, the
        # same switch runs through pkexec and asks. Each other switch here is
        # a unit of the user, or a helper that the toolkit's own rule permits,
        # and for those two commands are the same one.
        first = cec.toggle_command(name, wanted, source_dir=SOURCE_DIR)
        asking = cec.toggle_command(name, wanted, source_dir=SOURCE_DIR,
                                    ask=True)
        started = self._run_privileged(
            first, None if first == asking else asking,
            lambda _code, rest=left[1:]: self._run_cec_toggles(rest))
        if not started:
            # The Runner refused it, because another command runs. This
            # function applied nothing, so the switches take the values of
            # the machine again. They must not keep the values of this window.
            self._settle_cec_switches()

    def _cec_action(self, key):
        # The settings go with it, because one of these actions asks the
        # television a question. That action needs the device from the
        # settings. See cec.AUDIO_PROBE.
        if not self.runner.start(
                cec.action_command(key, settings=cec.config(self._cec)),
                lambda _code: self._reread_cec()):
            return

    def _save_cec_config(self):
        """Write the three boxes back, through the toolkit's own writer.

        That writer writes a *user* configuration file, and that file has
        priority over /etc. So this needs no password. A value from here also
        survives a new install of the toolkit.
        """
        values = {key: entry.get().strip()
                  for key, entry in self._cec_entries.items()}
        values.update((key, self._value_for(key, variable.get()))
                      for key, variable in self._cec_menus.items())
        self.runner.start(cec.set_config_command(values),
                          lambda _code: self._reread_cec())

    def _install_cec(self):
        """The CEC module, through the same installer as the other three.

        One route for every module, and not this page's own. Two ways to
        install one thing are two answers on the day one of them changes. The
        installer calls scripts/install-cec.sh, which is what this page called
        before. See install.sh, install_cec.
        """
        if not self._ask("HDMI CEC",
                         "This installs the SteamOS CEC Toolkit from "
                         "cec-toolkit/ and asks for your password once."
                         "\n\nNothing is switched on by installing it.",
                         confirm="Install"):
            return
        self.runner.start(ledpanel.module_command(SOURCE_DIR, "cec"),
                          lambda _code: self._module_changed("cec"))

    def _remove_cec(self):
        if not self._ask("HDMI CEC",
                         "This removes the CEC toolkit and everything it "
                         "installed, and asks for your password once.\n\nThe "
                         "television is left however it is now.",
                         confirm="Remove"):
            return
        self.runner.start(ledpanel.module_command(SOURCE_DIR, "cec",
                                                  remove=True),
                          lambda _code: self._module_changed("cec"))