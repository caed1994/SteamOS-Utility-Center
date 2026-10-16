# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Steam Companion page: the service, the secret, and the board.

The panel is a Waveshare ESP32-S3 with a touch screen, somewhere on a wall.
It reaches this machine over the network and nothing else, so this page has
three questions and no settings at all: is the service answering, what does
the panel have to be told, and how does the firmware get onto the board.

The secret is shown and never changed here. The installer writes it one
time, because the panel on the wall holds a copy that somebody typed into a
form on their phone. A new secret from a button is a panel that stops with
nothing on its screen to say why.

It is a mixin and not a widget. Panel takes it as a base, so every method
here is a method of Panel and `self` is the window.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import dialogs
import ledpanel
from steamos_utility_center import pairing

from panelbase import (CARD_WRAP, GROUP_GAP, ROW_FIELD_WIDTH, ROW_GAP,
                       SIDE_MARGIN, SOURCE_DIR)

# What the panel asks on, and what a person types into the form on their
# phone. companion.PORT is the one that decides; this is the same number for
# the sentence on the screen.
PORT = 8765

# The port of the board while it is plugged in for a flash. It is a guess and
# a starting point, and the field takes anything.
DEFAULT_BOARD_PORT = "/dev/ttyACM0"


class CompanionPage:
    """The methods of that page. See the note at the top of this file."""

    def _build_companion(self, where):
        """The three cards, and nothing that writes a setting.

        The three labels are cleared first. A change of theme builds this
        window again, and the labels of the old window stay on self: getattr
        finds one, and configure then fails with "invalid command name" on a
        widget that Tk destroyed. Measured, on the rebuild that
        AppearanceTest makes.
        """
        self.companion_state = None
        self.companion_where = None
        self.companion_build = None
        outer = ttk.Frame(where, style="Page.TFrame")
        self._build_companion_service(outer)
        self._build_companion_secret(outer)
        self._build_companion_board(outer)
        return outer

    def _companion_card(self, parent, title):
        """A card with a heading, which all three of these are."""
        card = self._card(parent)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(ROW_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        ttk.Label(inner, text=title, style="Section.TLabel").pack(anchor="w")
        return inner

    def _companion_line(self, parent, text, muted=True):
        line = ttk.Label(parent, text=text,
                         style="Muted.TLabel" if muted else "Section.TLabel",
                         justify="left", wraplength=CARD_WRAP)
        line.pack(anchor="w", pady=(ROW_GAP, 0))
        self._wrapped.append(line)
        return line

    # -- is it answering ---------------------------------------------------

    def _build_companion_service(self, parent):
        inner = self._companion_card(parent, "The service")
        self.companion_state = self._companion_line(inner, "")
        self._companion_line(
            inner,
            "It runs in your session and never as root. So the panel reaches "
            "what you reach at this keyboard, and nothing else.")
        row = ttk.Frame(inner, style="OnCard.TFrame")
        row.pack(anchor="w", pady=(GROUP_GAP, 0))
        ttk.Button(row, text="Start it again", style="Text.TButton",
                   command=self._restart_companion).pack(side="left")
        ttk.Button(row, text="Check again", style="Text.TButton",
                   command=self._reread_companion).pack(side="left",
                                                        padx=(ROW_GAP, 0))
        self._reread_companion()

    def _say_on_companion(self, name, text):
        """Writes one of this page's labels, if that label is still there.

        Two reasons for the check, and both happen. The cards are built in
        order, so the first of them reads the service before the other two
        exist. And a flash or a restart answers through the runner, which
        can come back after a change of theme has built this window again.
        """
        label = getattr(self, name, None)
        if label is None or not label.winfo_exists():
            return
        label.configure(text=text)

    def _reread_companion(self):
        """Asks the session about the service, and the disk about the rest."""
        if ledpanel.companion_running():
            said = "Answering on port %d." % PORT
        else:
            said = ("Not answering. journalctl --user -u %s says why."
                    % ledpanel.COMPANION_SERVICE)
        self._say_on_companion("companion_state", said)
        self._say_on_companion("companion_where", self._companion_where())
        self._say_on_companion("companion_build",
                               self._companion_build_state())

    def _restart_companion(self):
        self.runner.start(ledpanel.restart_companion_command(),
                          lambda _code: self._reread_companion())

    # -- a new panel that asks to pair --------------------------------------

    # How often the window looks for a panel that asks to pair.
    PAIR_LOOK_MS = 1500

    def _watch_pairing(self):
        """Asks the person about a panel that asks to pair, one time each.

        The service of the panel writes the request into a file in the
        runtime directory, and the answer goes back the same way. See
        pairing.py.
        """
        found = pairing.waiting()
        if found and found["id"] != getattr(self, "_pairing_seen", None):
            self._pairing_seen = found["id"]
            dialog = dialogs.CompanionPairDialog(self.root, found,
                                                 pairing.waiting)
            if not dialog.gone:
                try:
                    pairing.answer(found["id"], dialog.answer)
                except (OSError, ValueError) as exc:
                    self._say("Pair a Steam Companion",
                              "The answer did not reach the service of the "
                              "panel: %s" % exc)
        self._pairing_job = self.root.after(self.PAIR_LOOK_MS,
                                            self._watch_pairing)

    # -- what the panel has to be told -------------------------------------

    def _companion_where(self):
        found = ledpanel.companion_addresses()
        if not found:
            return ("This machine reports no address. Put it on the network "
                    "first.")
        return "\n".join("http://%s:%d" % (one, PORT) for one in found)

    def _build_companion_secret(self, parent):
        inner = self._companion_card(parent, "What the panel needs")
        self._companion_line(
            inner,
            "Hold the panel's Set up button, join the network it opens, and "
            "open http://192.168.4.1 on a phone. Give it your Wi-Fi. The "
            "panel then finds this PC and asks to pair, and this window asks "
            "you to compare a code. The address and the secret below are for "
            "a setup by hand.")
        self.companion_where = self._companion_line(inner,
                                                    self._companion_where(),
                                                    muted=False)

        row = ttk.Frame(inner, style="OnCard.TFrame")
        row.pack(fill="x", pady=(GROUP_GAP, 0))
        # Hidden until somebody asks. This page is the one a person opens to
        # read a number off, and a secret in plain sight is a secret in every
        # photograph of the screen.
        self.companion_secret = ttk.Label(row, text=self._companion_hidden(),
                                          style="Section.TLabel")
        self.companion_secret.pack(side="left")
        self.companion_shown = False
        self.companion_reveal = ttk.Button(row, text="Show",
                                           style="Text.TButton",
                                           command=self._show_companion_token)
        self.companion_reveal.pack(side="left", padx=(ROW_GAP, 0))

    def _companion_hidden(self):
        token = ledpanel.companion_token()
        if not token:
            return "No secret yet. Install this module to write one."
        return "The secret is " + "•" * 12

    def _show_companion_token(self):
        """Shows the secret, or hides it again.

        A label and not an entry: nothing here edits it, and an entry that
        refuses every keystroke is a control that lies about what it is.
        """
        token = ledpanel.companion_token()
        if not token:
            self._reread_companion()
            return
        self.companion_shown = not self.companion_shown
        self.companion_secret.configure(
            text=token if self.companion_shown else self._companion_hidden())
        self.companion_reveal.configure(
            text="Hide" if self.companion_shown else "Show")

    # -- the board ---------------------------------------------------------

    # What the page says for each state of the image. The button is a button
    # and the sentence beside it is the whole explanation, so a person who
    # cannot press it knows why without reading anything else.
    IMAGE_SAYS = {
        ledpanel.IMAGE_SHIPPED:
            "The image that came with this version is here. Press the button "
            "and the board is written.",
        ledpanel.IMAGE_BUILT_HERE:
            "A build you made yourself is in firmware/companion/build, and "
            "the button writes that one rather than the one that came with "
            "this version.",
        ledpanel.IMAGE_STALE:
            "The image here was built from a different version of the "
            "firmware, so the button is off. Update this panel under App "
            "Settings; the image comes with the update.",
        ledpanel.IMAGE_NONE:
            "No image here. Update this panel under App Settings, which "
            "brings one. Or build it yourself with ESP-IDF v5.5 in "
            "firmware/companion.",
    }

    def _companion_build_state(self):
        _where, state = ledpanel.companion_image(SOURCE_DIR)
        return self.IMAGE_SAYS[state]

    def _load_companion_ports(self):
        """Puts what is plugged in on the list, keeping the choice if it is
        still there.

        The label of each entry names the board and the value is the port,
        so a person reads "Espressif USB JTAG" and not a path that means
        nothing until something goes wrong.

        A machine with nothing plugged in keeps the old guess as the only
        entry, so the field is never empty and the line under it says what
        is missing.
        """
        if not hasattr(self, "companion_port"):
            return
        ports = ledpanel.serial_ports()
        choices = [(one["said"], one["device"]) for one in ports]
        if not choices:
            choices = [("Nothing is plugged in", DEFAULT_BOARD_PORT)]
        self._menus["companion-port"] = choices
        chosen = self._companion_port_value()
        if chosen not in [value for _label, value in choices]:
            chosen = choices[0][1]
        self.companion_port.set(self._label_for("companion-port", chosen))
        self._say_companion_port()

    def _companion_port_value(self):
        """The port itself, from the label on the field."""
        return self._value_for("companion-port", self.companion_port.get())

    def _say_companion_port(self):
        """Names what the flash would write to, under the row."""
        if not hasattr(self, "companion_port_said"):
            return
        chosen = self._companion_port_value()
        known = any(chosen == value
                    for _label, value in self._menus.get("companion-port", ()))
        if known and ledpanel.serial_ports():
            self.companion_port_said.configure(
                text="The panel is written at %s." % chosen)
        else:
            self.companion_port_said.configure(
                text="Nothing is plugged in at %s. Use a data cable, at the "
                     "programming socket." % chosen)

    def _build_companion_board(self, parent):
        inner = self._companion_card(parent, "The board")
        self.companion_build = self._companion_line(
            inner, self._companion_build_state())
        self._companion_line(
            inner,
            "Plug the board into this machine with a data cable, at its "
            "programming socket. A charging cable carries no data and the "
            "port never appears.")
        row = ttk.Frame(inner, style="OnCard.TFrame")
        row.pack(anchor="w", pady=(GROUP_GAP, 0))
        ttk.Label(row, text="Port", style="Muted.TLabel").pack(side="left")
        # A list of what is plugged in, and not a typed path.
        #
        # It was a text field holding a guess. A machine with one board has
        # one port and the guess was right; a machine with two has two, and
        # on the one this was found on the guess pointed at a Steam
        # Controller dongle whenever the panel was unplugged.
        #
        # _field and not a combobox, for the reason _field gives: Tk posts
        # its own list under a grab it does not release, and it stays above
        # the next window. tests/test_panel_live.py walks the window for
        # them, and it found this one.
        self.companion_port = tk.StringVar()
        self._field(row, "companion-port", self.companion_port, [],
                    DEFAULT_BOARD_PORT,
                    width=ROW_FIELD_WIDTH).pack(side="left",
                                                padx=(ROW_GAP, 0))
        ttk.Button(row, text="Flash the panel", style="Filled.TButton",
                   command=self._flash_companion).pack(side="left",
                                                       padx=(ROW_GAP, 0))
        ttk.Button(row, text="Read its log", style="Text.TButton",
                   command=self._read_companion_log).pack(side="left",
                                                          padx=(ROW_GAP, 0))
        self._companion_line(
            inner,
            "\"Read its log\" listens on the same cable for %d seconds and "
            "puts what the panel says below. Press the button on the panel "
            "while it runs. It needs no build tools."
            % ledpanel.COMPANION_LOG_SECONDS)
        # What is on the port that is chosen. Built here and filled by
        # _load_companion_ports, which runs now and at every refresh.
        self.companion_port_said = self._companion_line(inner, "")
        self._load_companion_ports()

    def _read_companion_log(self):
        """Reads the panel's own words, for somebody who has to report them.

        The alternative is idf.py monitor, which needs the build environment
        that this project keeps off the machine. A person who installs
        ESP-IDF to read one line undoes the reason the image is in this
        repository at all.
        """
        port = self._companion_port_value() or DEFAULT_BOARD_PORT
        self.runner.start(ledpanel.panel_log_command(SOURCE_DIR, port))

    def _flash_companion(self):
        """Writes the firmware, after one question.

        The question is not a formality. A flash that stops halfway leaves a
        board that does not start, and the way back is the BOOT button and a
        second try.

        An image that no build of this firmware produced is refused here and
        not written with a warning. The panel would come back talking to a
        service it does not match, and what a person sees then is "no PC" on
        a wall with nothing to say why.
        """
        port = self._companion_port_value() or DEFAULT_BOARD_PORT
        where, state = ledpanel.companion_image(SOURCE_DIR)
        if state in (ledpanel.IMAGE_NONE, ledpanel.IMAGE_STALE):
            self._say("Flash the panel", self.IMAGE_SAYS[state])
            return
        asked = dialogs.Dialog(
            self.root, "Flash the panel",
            "This writes the image in %s to the board on %s.\n\nIt replaces "
            "what is on the board. A flash that stops halfway needs the BOOT "
            "button and a second try." % (where, port),
            confirm="Flash")
        if not asked.answer:
            return
        self.runner.start(
            ledpanel.flash_companion_command(SOURCE_DIR, port, where),
            lambda _code: self._reread_companion())
