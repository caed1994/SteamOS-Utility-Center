# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The modal windows of the control panel.

One base and five that build on it. Each one asks a question, waits, and
gives the caller an answer as a value: the caller reads `.answer` and does
not pass a callback. That is what makes a press behind a question testable
without a display for the question itself.

Nothing of Tk is drawn by the platform any more. Tk draws its own message
box and its own colour chooser, and beside a Material window they look very
old; the chooser is the worst of the two, because this project is about
colour and that window asks for a colour.

In their own module, and not in the window, because a page of the window
needs them too. The window imports each page, so a page cannot import the
window back. See gui/panelbase.py for the same reason applied to the
measurements.

None of these knows what Panel is. Each takes a widget as its parent, which
is the Tk root of the window, and reads nothing of the window besides.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

import ledpanel

from panelbase import COLOUR, GROUP_GAP, ROW_GAP

# The maximum width of a message in a dialog before it wraps. It is wide
# enough for a path, and narrow enough to put a sentence on more than one
# line.
DIALOG_WRAP = 460


class Dialog:
    """Shows a message in the style of this window.

    Tk draws its own message boxes, and beside a Material window they look
    very old. A Toplevel needs approximately the same code and takes the
    theme, because ttk styles apply to the whole interpreter.

    Modal, as a question must be: transient to its parent, with a grab, and
    the caller waits and reads the answer as a return value.
    """

    def __init__(self, parent, title, message, confirm=None, deny="Cancel"):
        self.answer = confirm is None
        self.window = window = tk.Toplevel(parent)
        window.withdraw()                       # placed before it is shown
        window.title(title)
        window.transient(parent)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self._deny)
        # A ttk frame fills the window, but a thin part is visible during the
        # layout step. The default grey of Tk is not a colour of this window.
        window.configure(background=ttk.Style().lookup("TFrame", "background"))

        body = ttk.Frame(window, padding=GROUP_GAP)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, style="Heading.TLabel").pack(
            anchor="w", pady=(0, ROW_GAP))
        if message:
            ttk.Label(body, text=message, justify="left",
                      wraplength=DIALOG_WRAP).pack(anchor="w")
        self.build(body)

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(GROUP_GAP, 0))
        ttk.Button(buttons, text=confirm or "OK", style="Filled.TButton",
                   command=self._confirm).pack(side="right")
        if confirm is not None:
            ttk.Button(buttons, text=deny, style="Text.TButton",
                       command=self._deny).pack(side="right",
                                                padx=(0, ROW_GAP))

        window.bind("<Return>", lambda _event: self._confirm())
        window.bind("<Escape>", lambda _event: self._deny())
        self._centre(parent)
        window.deiconify()
        window.grab_set()
        window.focus_set()
        parent.wait_window(window)

    def build(self, body):
        """What goes between the message and the buttons, if anything."""

    def _centre(self, parent):
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        left = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        top = parent.winfo_rooty() + (parent.winfo_height() - height) // 3
        self.window.geometry("+%d+%d" % (max(0, left), max(0, top)))

    def _confirm(self):
        self.answer = True
        self.window.destroy()

    def _deny(self):
        self.answer = False
        self.window.destroy()


class CountdownDialog(Dialog):
    """Asks the user to keep these settings, or to let LACT reverse them.

    LACT reverses a change after some seconds without a confirmation. That is
    a function: a clock the card cannot hold makes the screen black, and a
    machine that reverses it stays usable. So this dialog asks, and it answers
    "no" itself when nobody answers.
    """

    def __init__(self, parent, seconds):
        self.left = max(1, int(seconds))
        self.job = None
        Dialog.__init__(
            self, parent, "Keep these settings?",
            "The graphics card has been set. If the screen has gone wrong or "
            "nothing is responding, wait - LACT puts the old settings back on "
            "its own.",
            confirm="Keep", deny="Put them back")

    def build(self, body):
        self.left_said = ttk.Label(body, style="Section.TLabel")
        self.left_said.pack(anchor="w", pady=(ROW_GAP, 0))
        self._tick()

    def _tick(self):
        self.left_said.configure(
            text="Putting them back in %d second%s"
                 % (self.left, "" if self.left == 1 else "s"))
        if self.left <= 0:
            # Not confirmed, so the daemon has already done it. Closing with
            # "no" keeps the window's idea of the card and the card itself
            # saying the same thing.
            self._deny()
            return
        self.left -= 1
        self.job = self.window.after(1000, self._tick)

    def _confirm(self):
        self._stop()
        Dialog._confirm(self)

    def _deny(self):
        self._stop()
        Dialog._deny(self)

    def _stop(self):
        if self.job is not None:
            self.window.after_cancel(self.job)
            self.job = None


class PairDialog(Dialog):
    """Waits for a person to hold the button on the device they want.

    A device gives a token out for 30 seconds after its power button is held,
    and this asks every device on the network once a second for that long. So
    a person holds the button on the one they want and it appears.

    That is why there is no list to pick from here. A list needs the name of
    each device and a person to know which name is which, and the button they
    are already holding says it better.

    The asking is on a thread, because it is a call over the network for each
    device and this window must keep drawing its countdown. The thread never
    touches Tk: it puts its answer in self.found, and the tick reads it.
    """

    def __init__(self, parent, ips):
        self.ips = list(ips)
        self.left = int(ledpanel.nanoleaf_module.PAIR_SECONDS)
        self.found = None
        self.job = None
        self.stop = threading.Event()
        Dialog.__init__(
            self, parent, "Add a Nanoleaf device",
            "Hold the power button on the device for five seconds, until its "
            "LEDs flash. It appears here on its own.",
            confirm=None)

    def build(self, body):
        self.left_said = ttk.Label(body, style="Section.TLabel")
        self.left_said.pack(anchor="w", pady=(ROW_GAP, 0))
        threading.Thread(target=self._ask, daemon=True).start()
        self._tick()

    def _ask(self):
        """The thread. It stops at the first token, or when the window goes."""
        def rest(gap):
            self.stop.wait(gap)

        try:
            ip, token = ledpanel.nanoleaf_pair(
                self.ips, seconds=self.left, rest=rest)
        except Exception:                       # pragma: no cover
            ip, token = None, None
        if token and not self.stop.is_set():
            self.found = {"ip": ip, "token": token}

    def _tick(self):
        if self.found is not None:
            self._deny()
            return
        self.left_said.configure(
            text="Looking for %d more second%s"
                 % (self.left, "" if self.left == 1 else "s"))
        if self.left <= 0:
            self._deny()
            return
        self.left -= 1
        self.job = self.window.after(1000, self._tick)

    def _confirm(self):
        # One button, and it says Cancel. Dialog wires the only button of a
        # dialog with no confirm to this one, so both ways out come here.
        self._deny()

    def _deny(self):
        self.stop.set()
        if self.job is not None:
            self.window.after_cancel(self.job)
            self.job = None
        Dialog._deny(self)


class ColourDialog(Dialog):
    """Asks for a colour to flash, from a grid or from typed text.

    The chooser of Tk has the worst look of each window that this panel can
    show. It is also the most important one, because this project is about
    colour. The grid offers the colours of the notifications, and those
    colours are correct on this strip. The user types each other colour,
    because the trigger accepts each colour.
    """

    ACROSS = 5

    def __init__(self, parent, dress, title="Flash a colour"):
        self.chosen = None
        # This takes a function that styles a button, and not an image. An
        # outlined button mixes its own fill below the pointer. A colour
        # sample that holds the plain shade then shows a box on the hover
        # shade. A grey field has the same fault and the same correction.
        self.dress = dress
        super().__init__(parent, title, None, confirm="Flash")

    def build(self, body):
        grid = ttk.Frame(body)
        grid.pack(anchor="w")
        for index, (label, value) in enumerate(ledpanel.palette()):
            button = ttk.Button(grid, text=label, compound="left",
                                style="Outlined.TButton",
                                command=lambda hue=value: self._take(hue))
            button.grid(row=index // self.ACROSS, column=index % self.ACROSS,
                        sticky="ew", padx=(0, ROW_GAP), pady=(0, ROW_GAP))
            self.dress(button, value)

        typed = ttk.Frame(body)
        typed.pack(fill="x", pady=(ROW_GAP, 0))
        ttk.Label(typed, text="Or a colour of your own").pack(anchor="w")
        self.entry = ttk.Entry(typed, width=12, style="Material.TEntry")
        self.entry.insert(0, ledpanel.SHAPE_TEST_COLOUR)
        self.entry.pack(anchor="w", pady=(ROW_GAP, 0))

    def _take(self, value):
        """A swatch is the whole answer: pick it and the dialog is done."""
        self.chosen = value
        self._confirm()

    def _confirm(self):
        if self.chosen is None:
            typed = self.entry.get().strip()
            if not COLOUR.match(typed):
                self.entry.focus_set()
                return                      # not a colour; say nothing, wait
            self.chosen = typed
        super()._confirm()


class RemoveDialog(Dialog):
    """Take a module off, and whether its settings go with it.

    The settings stay by default. Somebody who takes a module off to try
    something gets their LED count, their serial port and their effect back
    at the next install, and a press by accident then costs nothing.

    The box is here because the other half is just as reasonable, and because
    files that stay after a removal are a surprise when nobody said so. The
    line under it names what stays whatever the box says.
    """

    def __init__(self, parent, said):
        self.purge = tk.BooleanVar(value=False)
        super().__init__(
            parent, said["title"],
            "This takes the %s module off the machine and asks for your "
            "password once." % said["title"],
            confirm="Remove")

    def build(self, body):
        ttk.Checkbutton(body, variable=self.purge,
                        text="Remove its settings as well").pack(
                            anchor="w", pady=(GROUP_GAP, 0))
        # What no answer here reaches. The kernel module is another project's
        # code that other programs load, and the board is out of reach of any
        # button. uninstall.sh holds the first one.
        note = ttk.Label(
            body, style="Muted.TLabel", justify="left",
            wraplength=DIALOG_WRAP,
            text="The kernel module and the firmware on the board stay "
                 "either way.")
        note.pack(anchor="w", pady=(ROW_GAP, 0))


class ProfileDialog(Dialog):
    """Save or load one of your own profiles, without a file browser.

    Tk's file chooser is Tk's own and not the desktop's, which is exactly what
    it looks like next to this window. A browser is the wrong shape for the
    job as well: profiles live in one directory beside the clone, they are
    named rather than filed, and what anybody wants here is the list of the
    ones they have.
    """

    def __init__(self, parent, directory, roles, saving):
        self.directory = directory
        self.roles = roles
        self.saving = saving
        self.names = ledpanel.profiles(directory)
        self.chosen = None
        super().__init__(
            parent, "Save profile" if saving else "Load profile",
            "Saved beside the clone, in %s." % directory if saving
            else "Loaded into this window; nothing is written until you press "
                 "Apply.",
            confirm="Save" if saving else "Load")

    def build(self, body):
        self.listing = tk.Listbox(
            body, height=min(8, max(3, len(self.names))), activestyle="none",
            borderwidth=0, highlightthickness=0, exportselection=False,
            # This is a tk widget and not a themed widget. It has no style with
            # a colour, so the caller must give it one. Each ttk label in this
            # window already holds the colour below it. See dress().
            background=self.roles["surface_container_low"],
            foreground=self.roles["on_surface"],
            selectbackground=self.roles["secondary_container"],
            selectforeground=self.roles["on_secondary_container"])
        for name in self.names:
            self.listing.insert("end", name)
        self.listing.pack(fill="x", pady=(GROUP_GAP, 0))
        self.listing.bind("<<ListboxSelect>>", self._picked)
        self.listing.bind("<Double-Button-1>", lambda _event: self._confirm())
        if not self.names:
            self.listing.insert("end", " nothing saved yet")
            self.listing.configure(foreground=self.roles["on_surface_variant"],
                                   state="disabled")

        if not self.saving:
            return
        typed = ttk.Frame(body)
        typed.pack(fill="x", pady=(GROUP_GAP, 0))
        ttk.Label(typed, text="Call it").pack(anchor="w")
        self.entry = ttk.Entry(typed, style="Material.TEntry")
        self.entry.pack(fill="x", pady=(ROW_GAP, 0))
        self.entry.focus_set()
        ttk.Label(typed, text="A profile of the same name is replaced.",
                  style="Muted.TLabel").pack(anchor="w", pady=(ROW_GAP, 0))

    def _picked(self, _event=None):
        """Clicking one fills the name in, so overwriting is a click away."""
        picked = self.listing.curselection()
        if picked and self.saving:
            self.entry.delete(0, "end")
            self.entry.insert(0, self.names[picked[0]])

    def _confirm(self):
        if self.saving:
            self.chosen = ledpanel.profile_path(self.directory,
                                                self.entry.get())
            if self.chosen is None:
                self.entry.focus_set()
                return                          # unnamed; say nothing, wait
        else:
            picked = self.listing.curselection()
            if not picked or not self.names:
                return                          # nothing chosen yet
            self.chosen = ledpanel.profile_path(self.directory,
                                                self.names[picked[0]])
        super()._confirm()
