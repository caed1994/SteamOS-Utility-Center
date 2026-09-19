# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Nanoleaf devices on the network, as a card on the Nanoleaf page.

Beside the Pegboard board and not on a page of their own. The rail says
Nanoleaf, and the board and these are the same maker: a second page for one
card is a second place to look.

They are part of the core and not a module. An effect on one of them is an
HTTP call to an address on the LAN, and pairing one needs no rights at all,
so there is nothing here for an installer to install. See
server/steamos_utility_center/nanoleaf.py.

Every call to a device goes through _in_background. One of them costs a
timeout of some seconds, and a window that waits for it on the thread that
draws is a window that a person calls frozen.

It is a mixin and not a widget. Panel takes it as a base, so every method
here is a method of Panel and `self` is the window.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

import ledpanel
from dialogs import Dialog, PairDialog

from panelbase import GROUP_GAP, ROW_GAP, SENSOR_WIDTH

# The columns of one Nanoleaf device. A grid, one row for each, so the
# buttons of one device stand under the buttons of the next. The column
# before the buttons takes the width that is left over, which keeps them
# beside the device they act on and not at the edge of the window.
NET_NAME = 0
NET_WHERE = 1
NET_STATE = 2
NET_EFFECT = 3
NET_SWITCH = 4
NET_SPACER = 5
NET_REMOVE = 6


class NetworkPage:
    """The methods of that card. See the note at the top of this file."""

    def _build_network(self, parent):
        """The Nanoleaf devices on the network, and the effect each one plays.

        The effects are the ones on the device, put there with the app of
        Nanoleaf. This project draws none of them: measured on a Lines, the
        device recommends no more than ten frames a second and reports 81
        panels as a surface, and an effect of this project draws a line. See
        server/steamos_utility_center/nanoleaf.py.
        """
        box = self._section(parent, "On the network", card=True)
        self.network_box = ttk.Frame(box, style="OnCard.TFrame")
        self.network_box.pack(fill="x", pady=(GROUP_GAP, 0))

        # One row with the two ways in. The button is the ordinary way and
        # needs nothing typed. The address is for a network whose router
        # drops multicast, where nothing answers the search at all.
        row = ttk.Frame(box, style="OnCard.TFrame")
        row.pack(fill="x", pady=(GROUP_GAP, 0))
        ttk.Button(row, text="Add a device", style="Tonal.TButton",
                   command=self.pair_nanoleaf).pack(side="left")
        ttk.Label(row, text="or the address").pack(side="left",
                                                   padx=(GROUP_GAP, ROW_GAP))
        self._network_where = ttk.Entry(row, style="Material.TEntry",
                                        width=16)
        self._network_where.pack(side="left")
        ttk.Button(row, text="Add", style="Text.TButton",
                   command=self.pair_nanoleaf_at).pack(side="left",
                                                       padx=(ROW_GAP, 0))
        ttk.Button(row, text="Search again", style="Text.TButton",
                   command=self.refresh_nanoleaf).pack(side="right")

        # What the last call said, empty until there is something to say.
        # It carries its own space, so an empty one puts no band of nothing
        # at the foot of the card. See _tell_network.
        self.network_said = ttk.Label(box, style="Muted.TLabel",
                                      justify="left")
        self.network_said.pack(anchor="w")
        self._wrapped.append(self.network_said)
        self._wrap_insets[str(self.network_said)] = 2 * GROUP_GAP
        self._network = []
        self._reread_network()
        return box

    def _reread_network(self):
        """Reads each device, away from the thread that draws the window.

        One call for each device and a timeout of some seconds, so a device
        that is off must not stop the window.
        """
        self._tell_network("Reading the devices...")
        self._in_background(
            ledpanel.nanoleaf_devices,
            lambda found, bad: self._network_read(found, bad))

    def _network_read(self, found, bad):
        if bad is not None:
            self._tell_network(str(bad), bad=True)
            return
        self._network = found
        self._tell_network("")
        self._show_network()
        self._refit_page()

    def _show_network(self):
        """Draws one row for each device of the record."""
        for child in self.network_box.winfo_children():
            child.destroy()
        self.network_box.columnconfigure(NET_SPACER, weight=1)
        if not self._network:
            ttk.Label(self.network_box,
                      text="No Nanoleaf device on the network is paired "
                           "here.", style="Muted.TLabel").grid(
                               row=0, column=NET_NAME, sticky="w",
                               columnspan=NET_SPACER)
            return
        for row, said in enumerate(self._network):
            self._build_one_device(row, said)

    def _build_one_device(self, row, said):
        """One device: what it is, what it plays, and how to take it away."""
        box = self.network_box
        gap = (0, ROW_GAP)
        ttk.Label(box, text=said.get("name") or said["ip"]).grid(
            row=row, column=NET_NAME, sticky="w", padx=(0, GROUP_GAP),
            pady=gap)
        where = said["ip"]
        ttk.Label(box, text=where, style="Muted.TLabel").grid(
            row=row, column=NET_WHERE, sticky="w", padx=(0, GROUP_GAP),
            pady=gap)
        if not said["ok"]:
            # The reason in the row of the device it belongs to. A device
            # that is away keeps its place: the record says it is paired.
            ttk.Label(box, text="does not answer",
                      style="Bad.TLabel").grid(
                          row=row, column=NET_STATE, sticky="w",
                          padx=(0, GROUP_GAP), pady=gap)
            ttk.Button(box, text="Remove", style="Text.TButton",
                       command=lambda one=said: self.remove_nanoleaf(one)
                       ).grid(row=row, column=NET_REMOVE, sticky="w",
                              pady=gap)
            return
        # The state in a name of its own. A subscript inside the style
        # argument reads as a style name to the test that collects them.
        lit = bool(said["on"])
        ttk.Label(box, text="on" if lit else "off",
                  style="Good.TLabel" if lit else "Muted.TLabel").grid(
                      row=row, column=NET_STATE, sticky="w",
                      padx=(0, GROUP_GAP), pady=gap)
        # The effects of this device and not a list of this project. The key
        # of the menu is the token, because two devices of one model carry
        # the same name and the token is what tells them apart.
        key = "nanoleaf-%s" % said["token"]
        choices = [(name, name) for name in said["effects"]]
        chosen = tk.StringVar()
        field = self._field(box, key, chosen, choices, said["effect"],
                            width=SENSOR_WIDTH)
        # _field puts the label of `current` in the variable, and a device in
        # one of its modes has no effect to name. The word goes in after that
        # set and before the trace below, so nothing is played by the draw.
        if not said["effect"]:
            chosen.set("pick an effect")
        field.grid(row=row, column=NET_EFFECT, sticky="w",
                   padx=(0, ROW_GAP), pady=gap)
        chosen.trace_add("write",
                         lambda *_a, one=said, box=chosen:
                         self.play_nanoleaf(one, box.get()))
        ttk.Button(box, text="Turn off" if lit else "Turn on",
                   style="Text.TButton",
                   command=lambda one=said: self.switch_nanoleaf(one)).grid(
                       row=row, column=NET_SWITCH, sticky="w",
                       padx=(0, ROW_GAP), pady=gap)
        ttk.Button(box, text="Remove", style="Text.TButton",
                   command=lambda one=said: self.remove_nanoleaf(one)).grid(
                       row=row, column=NET_REMOVE, sticky="w", pady=gap)

    def _tell_network(self, said, bad=False):
        """Puts one sentence under the devices, or takes the last one away."""
        self.network_said.configure(
            text=said, style="Bad.TLabel" if bad else "Muted.TLabel")
        self.network_said.pack_configure(pady=(ROW_GAP if said else 0, 0))

    def pair_nanoleaf(self):
        """Waits for the button on a device, then puts it in the record."""
        self._tell_network("Looking for devices...")
        self._in_background(ledpanel.nanoleaf_found, self._pair_with)

    def pair_nanoleaf_at(self):
        """The same, for one address that a person typed.

        A network whose router drops multicast answers no search at all, and
        this is the way in on such a network.
        """
        where = self._network_where.get().strip()
        if not where:
            self._say("Nanoleaf", "Type the address of the device first.")
            return
        self._pair_with([{"ip": where, "name": "", "model": ""}], None)

    def _pair_with(self, found, bad):
        if bad is not None:
            self._tell_network(str(bad), bad=True)
            return
        known = {one["ip"] for one in self._network}
        ips = [one["ip"] for one in found if one["ip"] not in known]
        if not ips:
            self._tell_network(
                "Every device that answered is paired here already."
                if found else
                "No device answered the search. On a network that drops "
                "multicast, type the address instead.", bad=not found)
            return
        self._tell_network("")
        dialog = PairDialog(self.root, ips)
        if dialog.found is None:
            self._tell_network("No device gave a token. The button holds "
                               "the window open for 30 seconds.")
            return
        named = next((one for one in found
                      if one["ip"] == dialog.found["ip"]), {})
        ledpanel.nanoleaf_add({"ip": dialog.found["ip"],
                               "token": dialog.found["token"],
                               "name": named.get("name", ""),
                               "model": named.get("model", "")})
        self._reread_network()

    def remove_nanoleaf(self, device):
        """Takes the device out of the record and its token off the device."""
        if not Dialog(self.root, "Remove this device?",
                      "%s stays where it is and keeps whatever it plays. "
                      "This window forgets it, and the device forgets the "
                      "token of this machine."
                      % (device.get("name") or device["ip"]),
                      confirm="Remove").answer:
            return
        self._in_background(
            lambda one=device: ledpanel.nanoleaf_drop(one),
            lambda left, bad: self._network_dropped(left, bad))

    def _network_dropped(self, left, bad):
        if bad is not None:
            self._tell_network(str(bad), bad=True)
        elif left:
            # Out of the list either way. A device that is away must still
            # leave it, and the token on it is then still there.
            self._tell_network("The device is off the list. Its token is "
                               "still on it, because it did not answer: %s"
                               % left)
        self._reread_network()

    def play_nanoleaf(self, device, effect):
        """Plays one of the effects that the device holds."""
        if not effect or effect == device.get("effect"):
            return
        self._in_background(
            lambda one=device, name=effect: ledpanel.nanoleaf_select(one,
                                                                     name),
            lambda _done, bad: self._network_acted(bad))

    def switch_nanoleaf(self, device):
        """Turns the device on, or off."""
        self._in_background(
            lambda one=device: ledpanel.nanoleaf_switch(one, not one["on"]),
            lambda _done, bad: self._network_acted(bad))

    def refresh_nanoleaf(self):
        """Reads the addresses off mDNS again, then the devices.

        A lease moves, and a record with the old address is a device that
        stopped answering for no reason a person can see.
        """
        self._tell_network("Searching...")
        self._in_background(ledpanel.nanoleaf_refresh,
                            lambda _found, bad: self._network_acted(bad))

    def _network_acted(self, bad):
        if bad is not None:
            self._tell_network(str(bad), bad=True)
            return
        self._reread_network()

    def _in_background(self, work, done):
        """Runs `work()` off the drawing thread and gives `done` the answer.

        `done(answer, trouble)` runs on the thread that draws, because Tk
        belongs to that one thread. Every call to a device on the network
        goes through this: one of them costs a timeout of some seconds, and
        a window that waits for it is a window that a person calls frozen.
        """
        room = {}

        def run():
            try:
                room["answer"] = work()
            except Exception as exc:            # the reason goes on the card
                room["trouble"] = exc

        def look():
            # A window that closed while the call was in flight. Tk raises
            # on a widget that is gone, and the answer has nowhere to go.
            if not self.root.winfo_exists():
                return
            if "answer" not in room and "trouble" not in room:
                self.root.after(80, look)
                return
            done(room.get("answer"), room.get("trouble"))

        threading.Thread(target=run, daemon=True).start()
        self.root.after(80, look)
