# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The graphics card, through the daemon of LACT.

The one page of this window that sets nothing of its own. LACT is another
project's daemon and it owns the card; this page reads what it offers,
shows it, and sends a change back over the socket that daemon already
listens on. Nothing here installs LACT, and a machine without it sees a
sentence and no controls.

Why it has an Apply of its own, beside the CPU settings above it on the same
page: a change to the card applies at once and must be confirmed within
seconds, or the daemon puts the old one back. That countdown is what keeps a
bad voltage survivable. The CPU settings are this project's own file and need
no countdown, and one button for both would give one half the wrong
behaviour.

FanCurve is here rather than beside the other widget classes of the window.
It draws one thing, the page draws it, and nothing else in the window has a
curve to edit.

It is a mixin and not a widget. Panel takes it as a base, so every method
here is a method of Panel and `self` is the window.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import dialogs
import ledpanel
from steamos_utility_center import lact

from panelbase import (CARD_WRAP, GROUP_GAP, ROW_FIELD_WIDTH, ROW_GAP,
                       SIDE_MARGIN)


class FanCurve:
    """Shows the fan curve as a graph that the user can drag.

    Temperature across, fan speed up. A point drags in both directions and
    cannot pass its neighbours, so the curve is a function of the temperature:
    LACT stores it as a map with the degrees as the key.

    A canvas, because ttk has no graph. The alternative is a column of
    numbers, which answers "what is the speed at 60 degrees" and never "what
    is the shape of this curve".
    """

    LOW, HIGH = 20, 100                 # the degrees the graph spans
    # Room for the labels round the plot. Measured rather than guessed: 26 cut
    # the leading digit off "100%", which reads as a graph that starts at 0.
    PAD = 40
    GRAB = 9                            # how near a point you have to press
    HEIGHT = 200

    def __init__(self, parent, roles, curve, on_change=None):
        self.roles = roles
        self.on_change = on_change or (lambda: None)
        self.curve = dict(curve)
        self.held = None
        self.canvas = tk.Canvas(parent, height=self.HEIGHT,
                                highlightthickness=0, borderwidth=0,
                                background=roles["surface_container_lowest"])
        self.canvas.bind("<Configure>", lambda _event: self.draw())
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)

    # -- where a point sits on screen, and the way back ---------------------

    def _plot(self):
        width = max(self.canvas.winfo_width(), 2 * self.PAD + 40)
        return (self.PAD, self.PAD // 2,
                width - self.PAD // 2, self.HEIGHT - self.PAD)

    def _at(self, degrees, fraction):
        left, top, right, bottom = self._plot()
        across = (degrees - self.LOW) / float(self.HIGH - self.LOW)
        return (left + across * (right - left),
                bottom - fraction * (bottom - top))

    def _from(self, x, y):
        left, top, right, bottom = self._plot()
        degrees = self.LOW + (x - left) / float(right - left) * (
            self.HIGH - self.LOW)
        fraction = (bottom - y) / float(bottom - top)
        return (int(round(max(self.LOW, min(self.HIGH, degrees)))),
                max(0.0, min(1.0, fraction)))

    # -- drawing ------------------------------------------------------------

    def draw(self):
        canvas = self.canvas
        canvas.delete("all")
        left, top, right, bottom = self._plot()
        grid = self.roles["outline_variant"]
        # Gridlines and their labels, so the shape can be read rather than
        # only felt: a curve with no scale is a picture of a curve.
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = bottom - fraction * (bottom - top)
            canvas.create_line(left, y, right, y, fill=grid, width=1)
            canvas.create_text(left - 6, y, text="%d%%" % (fraction * 100),
                               anchor="e", fill=self.roles["on_surface_variant"],
                               font=("TkDefaultFont", 7))
        for degrees in range(self.LOW, self.HIGH + 1, 20):
            x, _ = self._at(degrees, 0)
            canvas.create_line(x, top, x, bottom, fill=grid, width=1)
            canvas.create_text(x, bottom + 10, text="%d°" % degrees,
                               fill=self.roles["on_surface_variant"],
                               font=("TkDefaultFont", 7))

        points = sorted(self.curve.items())
        if not points:
            return
        line = []
        for degrees, fraction in points:
            line.extend(self._at(degrees, fraction))
        if len(line) >= 4:
            canvas.create_line(*line, fill=self.roles["primary"], width=2,
                               smooth=False)
        for index, (degrees, fraction) in enumerate(points):
            x, y = self._at(degrees, fraction)
            held = self.held == index
            canvas.create_oval(x - 5, y - 5, x + 5, y + 5, width=0,
                               fill=self.roles["on_primary"] if held
                               else self.roles["primary"])
            if held:
                canvas.create_text(
                    x, y - 14, text="%d° %d%%" % (degrees, fraction * 100),
                    fill=self.roles["on_surface"],
                    font=("TkDefaultFont", 8))

    # -- taking hold of it --------------------------------------------------

    def _nearest(self, x, y):
        for index, (degrees, fraction) in enumerate(sorted(self.curve.items())):
            at_x, at_y = self._at(degrees, fraction)
            if abs(at_x - x) <= self.GRAB and abs(at_y - y) <= self.GRAB:
                return index
        return None

    def _press(self, event):
        self.held = self._nearest(event.x, event.y)
        self.draw()

    def _drag(self, event):
        if self.held is None:
            return
        points = sorted(self.curve.items())
        degrees, fraction = self._from(event.x, event.y)
        # The point stays between its neighbours and never passes them. LACT
        # uses the temperature as the key of the curve. A point that passes
        # its neighbour does not change position with it. The two points then
        # have the same key, and one of the two goes away.
        low = points[self.held - 1][0] + 1 if self.held > 0 else self.LOW
        high = (points[self.held + 1][0] - 1
                if self.held + 1 < len(points) else self.HIGH)
        degrees = max(low, min(high, degrees))
        self.curve = dict(points[:self.held] + [(degrees, fraction)]
                          + points[self.held + 1:])
        self.draw()

    def _release(self, _event):
        if self.held is not None:
            self.held = None
            self.draw()
            self.on_change()

    # -- adding and taking away ---------------------------------------------

    def add(self):
        """A point in the widest gap, which is where one is wanted."""
        points = sorted(self.curve)
        if len(points) < 2:
            self.curve[(self.LOW + self.HIGH) // 2] = 0.5
        else:
            widest = max(zip(points, points[1:]),
                         key=lambda pair: pair[1] - pair[0])
            if widest[1] - widest[0] < 2:
                return                  # no room between any two of them
            middle = (widest[0] + widest[1]) // 2
            self.curve[middle] = (self.curve[widest[0]]
                                  + self.curve[widest[1]]) / 2
        self.draw()
        self.on_change()

    def remove(self):
        """Removes the last point, but keeps a curve of two points.

        Two points are the minimum for a curve, and LACT needs a curve and not
        a point. So this function stops at two points. It does not let the
        graph become a shape that the daemon cannot accept.
        """
        if len(self.curve) <= 2:
            return
        self.curve.pop(max(self.curve))
        self.draw()
        self.on_change()


class GpuPage:
    """The methods of that page. See the note at the top of this file."""

    def _build_power(self, where, table, note):
        """The CPU settings, and the graphics card underneath them.

        Two halves that do not share an Apply. The CPU half is this project's
        configuration file and goes through the window's Apply. The GPU half
        is somebody else's daemon: it applies at once and must be confirmed
        within seconds.

        One button would give the CPU settings a countdown they do not need,
        or take from the GPU ones the countdown that keeps a bad voltage
        survivable.
        """
        outer = self._build_settings(where, table, note)
        self._gpu = None                # the last read, or None for no daemon
        self._gpu_asked = False
        self._gpu_error = ""
        self._gpu_vars = {}
        self._gpu_curve = None
        self.gpu_box = ttk.Frame(outer, style="Page.TFrame")
        self.gpu_box.pack(fill="x")
        return outer

    def _first_look_gpu(self):
        """Reads the card one time after the window opens, and reports it.

        The block of the page is drawn by _reread_gpu whether or not the page
        is on the screen, which costs nothing: the page is built already, and
        a person who opens it then finds it filled in.
        """
        self._gpu_first = None
        self._reread_gpu()
        self.refresh_status()

    def _catch_up_gpu(self):
        """Read the card the first time somebody opens this section."""
        if not self._gpu_asked:
            self._reread_gpu()

    def _reread_gpu(self):
        """Ask LACT about the card again and draw the block from the answer."""
        self._gpu_error = ""
        try:
            self._gpu = ledpanel.gpu_state()
        except lact.LactError as exc:
            # An installed daemon with a fault is not the same as no daemon, and
            # the block reports which one it is. "no daemon" hides the page.
            # "would not answer" is a fault to read.
            self._gpu = None
            self._gpu_error = str(exc)
        self._gpu_asked = True
        self._draw_gpu()

    def _draw_gpu(self):
        """Rebuild the block. Cheap enough to do rather than to update."""
        for child in self.gpu_box.winfo_children():
            child.destroy()
        self._forget_dead_labels()
        self._gpu_vars = {}
        self._gpu_curve = None
        if self._gpu is None and not self._gpu_error:
            return                      # no LACT: no block at all
        card = self._card(self.gpu_box)
        card.pack(fill="x", padx=SIDE_MARGIN, pady=(GROUP_GAP, 0))
        inner = ttk.Frame(card, style="OnCard.TFrame")
        inner.pack(fill="x", padx=GROUP_GAP, pady=GROUP_GAP)
        ttk.Label(inner, text="Graphics card", style="Section.TLabel").pack(
            anchor="w", pady=(0, ROW_GAP))

        said = ttk.Label(inner, justify="left", wraplength=CARD_WRAP,
                         text=self._gpu_error or ledpanel.gpu_summary(self._gpu),
                         style="Bad.TLabel" if self._gpu_error else "TLabel")
        said.pack(anchor="w")
        self._wrapped.append(said)
        self._wrap_insets[str(said)] = 2 * GROUP_GAP
        if self._gpu_error or not (self._gpu or {}).get("gpu"):
            self._buttons(inner, [("Check again", self._reread_gpu)])
            return

        self._build_gpu_profiles(inner)
        self._build_gpu_knobs(inner)
        self._build_gpu_fan(inner)
        self._buttons(inner, [("Apply to the card", self._apply_gpu),
                              ("Check again", self._reread_gpu)],
                      lead=GROUP_GAP)
        self._refit_page()
        self._note(inner,
                   "Applied through LACT, which puts the old settings back "
                   "by itself unless the change is confirmed - so a setting "
                   "this card will not take undoes itself.").pack(
                       anchor="w", pady=(ROW_GAP, 0))

    def _build_gpu_profiles(self, inner):
        """LACT's own saved profiles, if it has any.

        This block lists them and does not edit them. To make one, a user
        selects settings, gives them a name, and gives the condition that
        turns them on. The window of LACT does that work, and a copy here is a
        second and worse copy.
        """
        names = (self._gpu or {}).get("profiles") or []
        if not names:
            return
        row = ttk.Frame(inner, style="OnCard.TFrame")
        row.pack(fill="x", pady=(GROUP_GAP, 0))
        ttk.Label(row, text="Profile").pack(side="left", padx=(0, GROUP_GAP))
        variable = tk.StringVar()
        self._gpu_vars["profile"] = variable
        current = self._gpu.get("profile") or ""
        # The default profile has no name in LACT, so this code gives it one.
        # A menu with an empty entry looks like a menu with a fault.
        choices = [("Default", "")] + [(name, name) for name in names]
        self._field(row, "gpu-profile", variable, choices, current,
                    width=ROW_FIELD_WIDTH).pack(side="left")
        variable.trace_add("write", lambda *_a: self._gpu_profile_chosen())

    def _build_gpu_knobs(self, inner):
        """One slider per knob this card actually reported."""
        knobs = ledpanel.gpu_knobs(self._gpu)
        if not knobs:
            return
        grid = ttk.Frame(inner, style="OnCard.TFrame")
        grid.pack(fill="x", pady=(GROUP_GAP, 0))
        grid.columnconfigure(1, weight=1)
        for row, knob in enumerate(knobs):
            ttk.Label(grid, text=knob["label"]).grid(
                row=row, column=0, sticky="w", padx=(0, GROUP_GAP),
                pady=(0 if row == 0 else ROW_GAP, 0))
            variable = tk.DoubleVar(value=knob["start"])
            self._gpu_vars[knob["key"]] = variable
            ttk.Scale(grid, from_=knob["min"], to=knob["max"],
                      variable=variable).grid(
                          row=row, column=1, sticky="ew",
                          pady=(0 if row == 0 else ROW_GAP, 0))
            reading = ttk.Label(grid, style="Muted.TLabel", width=10)
            reading.grid(row=row, column=2, sticky="e", padx=(GROUP_GAP, 0),
                         pady=(0 if row == 0 else ROW_GAP, 0))

            def show(*_args, box=reading, unit=knob["unit"], var=variable):
                box.configure(text="%d %s" % (round(var.get()), unit))

            variable.trace_add("write", show)
            show()

    def _build_gpu_fan(self, inner):
        """The fan: off, a fixed speed, or a curve.

        "Off" means that the firmware of the card drives the fan. A machine
        with no change has that state. So this block opens in that state, and
        that state disables the other controls of the block.
        """
        fan = lact.fan((self._gpu or {}).get("config") or {})
        holder = ttk.Frame(inner, style="OnCard.TFrame")
        holder.pack(fill="x", pady=(GROUP_GAP, 0))

        row = ttk.Frame(holder, style="OnCard.TFrame")
        row.pack(fill="x")
        enabled = tk.BooleanVar(value=fan["enabled"])
        self._gpu_vars["fan_enabled"] = enabled
        ttk.Checkbutton(row, variable=enabled,
                        command=self._gpu_fan_changed).pack(side="left")
        ttk.Label(row, text="Control the fan").pack(side="left",
                                                    padx=(ROW_GAP, GROUP_GAP))
        mode = tk.StringVar(value=fan["mode"])
        self._gpu_vars["fan_mode"] = mode
        self._field(row, "gpu-fan-mode", mode,
                    [("Curve", lact.FAN_CURVE), ("Fixed speed",
                                                 lact.FAN_STATIC)],
                    fan["mode"], width=ROW_FIELD_WIDTH).pack(side="left")
        mode.trace_add("write", lambda *_a: self._gpu_fan_changed())

        self.gpu_fan_body = ttk.Frame(holder, style="OnCard.TFrame")
        self.gpu_fan_body.pack(fill="x", pady=(ROW_GAP, 0))

        speed = tk.DoubleVar(value=fan["static_speed"] * 100)
        self._gpu_vars["fan_speed"] = speed
        self.gpu_fan_static = ttk.Frame(self.gpu_fan_body,
                                        style="OnCard.TFrame")
        ttk.Label(self.gpu_fan_static, text="Speed").pack(side="left",
                                                          padx=(0, GROUP_GAP))
        ttk.Scale(self.gpu_fan_static, from_=0, to=100,
                  variable=speed).pack(side="left", fill="x", expand=True)
        reading = ttk.Label(self.gpu_fan_static, style="Muted.TLabel", width=6)
        reading.pack(side="left", padx=(GROUP_GAP, 0))
        speed.trace_add("write",
                        lambda *_a: reading.configure(
                            text="%d%%" % round(speed.get())))
        reading.configure(text="%d%%" % round(speed.get()))

        self.gpu_fan_curve = ttk.Frame(self.gpu_fan_body,
                                       style="OnCard.TFrame")
        self._gpu_curve = FanCurve(self.gpu_fan_curve, self.roles,
                                   fan["curve"])
        self._gpu_curve.canvas.pack(fill="x")
        self._buttons(self.gpu_fan_curve,
                      [("Add a point", self._gpu_curve.add),
                       ("Remove one", self._gpu_curve.remove)])
        self._build_gpu_firmware(holder)
        self._gpu_fan_changed()

    def _build_gpu_firmware(self, holder):
        """The card's own fan settings, on the cards that have them.

        Outside the "control the fan" switch above, because they are in the
        firmware and not in the control loop of LACT. They apply while the
        card drives its own fan, which is the state most people keep.

        It draws the settings the card reports. A card before RDNA3 reports
        none, and this block is then absent and not empty.
        """
        offered = lact.firmware((self._gpu or {}).get("stats") or {})
        if not offered:
            return
        ttk.Label(holder, text="The card's own fan settings",
                  style="Section.TLabel").pack(anchor="w",
                                               pady=(GROUP_GAP, ROW_GAP))
        said = self._note(
            holder,
            "These are the firmware's, not LACT's, so they apply whether or "
            "not the switch above is on. Only the ones this card reports are "
            "shown.")
        said.pack(anchor="w", pady=(0, ROW_GAP))

        grid = ttk.Frame(holder, style="OnCard.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        for row, one in enumerate(offered):
            if one["switch"]:
                variable = tk.BooleanVar(value=bool(one["value"]))
                box = ttk.Frame(grid, style="OnCard.TFrame")
                box.grid(row=row, column=0, columnspan=3, sticky="w",
                         pady=(0 if row == 0 else ROW_GAP, 0))
                ttk.Checkbutton(box, variable=variable).pack(side="left")
                ttk.Label(box, text=one["label"]).pack(side="left",
                                                       padx=(ROW_GAP, 0))
                self._gpu_vars["fw:" + one["key"]] = variable
                continue
            ttk.Label(grid, text="%s (%s)" % (one["label"], one["unit"])).grid(
                row=row, column=0, sticky="w", padx=(0, GROUP_GAP),
                pady=(0 if row == 0 else ROW_GAP, 0))
            variable = tk.DoubleVar(value=one["value"])
            self._gpu_vars["fw:" + one["key"]] = variable
            ttk.Scale(grid, from_=one["min"], to=one["max"],
                      variable=variable).grid(
                          row=row, column=1, sticky="ew",
                          pady=(0 if row == 0 else ROW_GAP, 0))
            reading = ttk.Label(grid, style="Muted.TLabel", width=8)
            reading.grid(row=row, column=2, sticky="e", padx=(GROUP_GAP, 0),
                         pady=(0 if row == 0 else ROW_GAP, 0))

            def show(*_args, box=reading, var=variable):
                box.configure(text="%d" % round(var.get()))

            variable.trace_add("write", show)
            show()

    def _gpu_fan_changed(self):
        """Show the half of the fan settings the chosen mode uses."""
        on = bool(self._gpu_vars["fan_enabled"].get())
        # This uses _value_for. A drop-down of this window holds the label
        # on the screen and not the value behind it. A comparison of the
        # variable with the word of LACT therefore matches nothing, and this
        # function draws the wrong half.
        curve = self._gpu_mode() == lact.FAN_CURVE
        for frame, wanted in ((self.gpu_fan_static, on and not curve),
                              (self.gpu_fan_curve, on and curve)):
            if wanted:
                frame.pack(fill="x")
            else:
                frame.pack_forget()
        self._refit_page()
        self._fit_window()

    def _gpu_mode(self):
        """Which fan mode is chosen, as LACT spells it."""
        return self._value_for("gpu-fan-mode",
                               self._gpu_vars["fan_mode"].get())

    def _gpu_profile_chosen(self):
        """Changes the profile now. This is not a setting for Apply.

        A profile of LACT carries its own settings, so a new profile replaces
        each setting below it. This function reads the block again at the end,
        and it does not leave the values of the last profile on the screen.
        """
        wanted = self._value_for("gpu-profile", self._gpu_vars["profile"].get())
        if wanted == (self._gpu or {}).get("profile", ""):
            return                              # the trace fires on redraw too
        try:
            lact.set_profile(wanted)
        except lact.LactError as exc:
            self._say("Graphics card", "Could not switch profile:\n%s" % exc)
        self._reread_gpu()

    def _collect_gpu(self):
        """The whole config, with what is on screen written into it.

        The whole of it, because that is LACT's interface: set_gpu_config
        replaces the document rather than patching it, so anything not carried
        across is a setting silently turned off on somebody's card.
        """
        config = (self._gpu or {}).get("config") or {}
        for knob in ledpanel.gpu_knobs(self._gpu):
            variable = self._gpu_vars.get(knob["key"])
            if variable is not None:
                config = lact.with_knob(config, knob["key"],
                                        round(variable.get()),
                                        knob.get("scale", 1))
        # The settings of the firmware. They are a third position in the
        # document, and this code collects them for each fan mode.
        config = lact.with_firmware(config, {
            key[len("fw:"):]: variable.get() for key, variable
            in self._gpu_vars.items() if key.startswith("fw:")})
        curve = self._gpu_curve.curve if self._gpu_curve else None
        return lact.with_fan(
            config,
            enabled=bool(self._gpu_vars["fan_enabled"].get()),
            mode=self._gpu_mode(),
            static_speed=self._gpu_vars["fan_speed"].get() / 100.0,
            curve=curve)

    def _apply_gpu(self):
        """Send it, then ask whether to keep it before the daemon takes it back."""
        gpu = (self._gpu or {}).get("gpu")
        if not gpu:
            return
        try:
            seconds = lact.set_gpu_config(gpu, self._collect_gpu())
        except lact.LactError as exc:
            self._say("Graphics card", "The card would not take it:\n%s" % exc)
            self._reread_gpu()
            return
        keep = dialogs.CountdownDialog(self.root, seconds).answer
        try:
            lact.confirm(keep=keep)
        except lact.LactError as exc:
            # The confirmation can fail after the window closes, because the
            # daemon then reverses the settings itself. The dialog offers that
            # same result. So one message is sufficient, and this is not a
            # fault.
            self._write("LACT did not take the confirmation: %s\n" % exc)
        self._reread_gpu()
