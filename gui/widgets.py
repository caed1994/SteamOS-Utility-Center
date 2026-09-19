# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The widgets of this window that Tk does not give it.

One so far. SidebarEntry is the other candidate and stays in the window for
now: it draws itself through _photo, which the theme code of the window uses
ten times over, and that helper belongs with the theme and not here.
gui/dialogs.py holds the modal windows, and gui/roundrect.py the pixels that
both are drawn from.
"""

from __future__ import annotations

import tkinter as tk


class Popup:
    """Draws the list of a drop-down. This class draws it, and Tk does not.

    A tk.Menu cannot take the look of the other controls: it marks the current
    entry with an indicator and not with a filled row, and its border is not
    settable.

    It also stays too long. Tk posts it under a grab of its own and gives the
    menu no control of the close step, so it stayed above the window that took
    the focus next.

    So this is a plain Toplevel of this file. It draws the rows and closes
    when the focus leaves it. The note below the constructor gives the reason
    for the missing grab.
    """

    PAD_X = 14
    PAD_Y = 8

    def __init__(self, button, key, roles, choices, variable, swatch, on_close):
        self.roles = roles
        self.variable = variable
        self.on_close = on_close
        self.rows = []

        self.owner = button
        self.key = key
        self.window = window = tk.Toplevel(button)
        window.withdraw()
        window.overrideredirect(True)
        # One pixel of edge, which is the Toplevel below. A window cannot get a
        # border of its own without a frame around each element.
        window.configure(background=roles["outline_variant"])
        inner = tk.Frame(window, background=roles["surface_container"],
                         borderwidth=0, highlightthickness=0)
        inner.pack(padx=1, pady=1, fill="both", expand=True)

        # A colour sample has no alpha channel. This code draws it against a
        # known background, and the sample holds that background in its
        # corners and in the space beside it. A row has three backgrounds:
        # plain, hover and selected. So a row needs three samples. With one
        # sample for the plain shade, the filled row shows a block of the
        # incorrect colour. The rows had that fault.
        self.swatch = swatch
        for label, value in choices:
            row = tk.Label(inner, text=label, compound="left", anchor="w",
                           font=roles["_font"], padx=self.PAD_X,
                           pady=self.PAD_Y, borderwidth=0,
                           highlightthickness=0)
            row.pack(fill="x")
            row.bind("<Enter>", lambda _e, name=label: self._hover(name))
            row.bind("<Leave>", lambda _e: self._hover(None))
            row.bind("<Button-1>", lambda _e, name=label: self._take(name))
            self.rows.append((row, label, value))
        self._paint(None)

        window.bind("<Escape>", lambda _e: self.close())
        # Two ways out that do not need a click. The list takes the focus when
        # it opens, so losing it means it went somewhere else; focus_get()
        # coming back as None means it went out of this application
        # altogether, which is the case where the list was left floating over
        # somebody else's window.
        window.bind("<FocusOut>", lambda _e: self._left())
        self._watching = button.winfo_toplevel()
        self._watching.bind("<FocusOut>", lambda _e: self._left(), add="+")
        self._watching.bind("<Unmap>", lambda _e: self.close(), add="+")
        window.bind("<Up>", lambda _e: self._step(-1))
        window.bind("<Down>", lambda _e: self._step(1))
        window.bind("<Return>", lambda _e: self.close())
        # Under a local grab every click in this application arrives here; one
        # that did not land on a row is a click away, which closes.
        window.bind("<Button-1>", lambda _e: self.close())
        self._place(button)
        window.deiconify()

    # There is no grab, and that is the design and not an error. A
    # measurement under a window manager, with another application above the
    # panel, showed this: with a grab of each type the list stayed on the
    # screen, and without a grab it closed.
    #
    # A grab takes the focus event that reports the change to another
    # application. An override-redirect window gets that event only, and a
    # list with no decoration must be such a window. So this class uses no
    # grab. The panel receives the clicks that the grab received before. See
    # Panel._panel_click.

    def _left(self):
        """Closes the list, if the focus left this application.

        Never asked immediately. A focus event arrives at the start of the
        change, and a question then can land after the old window released the
        focus and before the new one took it. One pass of the idle loop is
        enough.
        """
        self.window.after_idle(self._elsewhere)

    def _elsewhere(self, _event=None):
        try:
            if self.window.focus_get() is None:
                self.close()
        except (tk.TclError, KeyError):                      # pragma: no cover
            self.close()                        # focus is somewhere we cannot see

    def _place(self, button):
        """Puts the list below the field, with its top edge on the field.

        A list that opens *over* the field, with the selected row on it, has a
        different position for each entry and covers the control a person just
        pressed. Below the field, the field stays visible and the position is
        always the same.

        It opens upwards when there is not sufficient space below.
        """
        window = self.window
        window.update_idletasks()
        height = window.winfo_reqheight()
        width = max(button.winfo_width(), window.winfo_reqwidth())

        left = button.winfo_rootx()
        below = button.winfo_rooty() + button.winfo_height()
        if below + height <= window.winfo_screenheight():
            top = below
        else:
            # Above, on the top edge of the field. A list that is longer than
            # the screen does not fit there either. The clamp then puts it as
            # far down as possible.
            top = max(0, min(button.winfo_rooty() - height,
                             window.winfo_screenheight() - height))
        left = max(0, min(left, window.winfo_screenwidth() - width))
        window.geometry("%dx%d+%d+%d" % (width, height, left, top))

    def _paint(self, hovered):
        """Colours each row. The selected row is filled, and the row below the
        pointer is bright.

        This function paints the colour sample again, against the shade of the
        row. See the note at the code that builds the rows.
        """
        for row, label, value in self.rows:
            if label == self.variable.get():
                fill, ink = "secondary_container", "on_secondary_container"
            elif label == hovered:
                fill, ink = "surface_container_high", "on_surface"
            else:
                fill, ink = "surface_container", "on_surface"
            row.configure(background=self.roles[fill],
                          foreground=self.roles[ink],
                          image=self.swatch(value, fill) or "")

    def _hover(self, label):
        self._paint(label)

    def _step(self, by):
        labels = [label for _row, label, _value in self.rows]
        if not labels:
            return
        try:
            at = labels.index(self.variable.get())
        except ValueError:
            at = 0
        self.variable.set(labels[max(0, min(at + by, len(labels) - 1))])
        self._paint(None)

    def _take(self, label):
        self.variable.set(label)
        self.close()

    def close(self):
        for sequence in ("<FocusOut>", "<Unmap>"):
            try:
                self._watching.unbind(sequence)
            except tk.TclError:                             # pragma: no cover
                pass
        try:
            self.window.destroy()
        except tk.TclError:                                 # pragma: no cover
            pass                                            # already gone
        self.on_close()
