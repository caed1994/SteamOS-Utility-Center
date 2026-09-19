# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The System page: the drives, controller wake and the Game Mode plugin.

These are settings of the machine and not of a device this project drives.
The LED bar has a strip, the Pegboard has a board and HDMI CEC has a
television; this page has the computer itself.

It is a mixin and not a widget. Panel takes it as a base, so every method
here is a method of Panel and reaches self.root, self.runner and the rest of
the window as it did when it was in one file. The cut is for reading, not for
a new boundary: a boundary would mean passing the window into each of these
and there is nothing to gain from that.

What stays in the panel: _run_privileged. It is shared with the settings
pages, which apply the LED and the CPU settings through the same path.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

import ledpanel
from steamos_utility_center import ctl
from steamos_utility_center import mounts
from steamos_utility_center import wake

from panelbase import (CARD_WRAP, CEC_INDENT, GROUP_GAP, ROW_GAP,
                       SENSOR_WIDTH, SOURCE_DIR)

# The columns of a drive on the System page. Every drive is a row in one grid,
# so the buttons of one drive stand under the buttons of the next. A frame for
# each drive would put each button where its own text ends. The last column
# holds the extra width, which keeps the buttons beside the drive they act on
# and not at the edge of the window.
#
# The comment above stood over the Nanoleaf columns in the panel, because a
# second grid was written between it and the names it describes. The move
# brings the two back together.
DRIVE_WHERE = 0
DRIVE_TYPE = 1
DRIVE_STATE = 2
DRIVE_OWN = 3
DRIVE_REMOVE = 4
DRIVE_SPACER = 5


class SystemPage:
    """The methods of the System page. See the note at the top of this file."""

    def _build_system(self, where, table, note):
        """The System page: the keyboard layout, the drives, and the plugin.

        All settings of the machine and not of the bar. The keyboard layout
        goes in the home directory of the user and needs no rights. A mount
        unit is in /etc and needs root, so this page has a privileged half.
        """
        outer = self._build_settings(where, table, note)
        # The keyboard layout above is the core. It writes into the home
        # directory of the user, it needs no rights at all, and it therefore
        # works on a machine with no module.
        #
        # The drives and the plugin are the module. They arrive together and
        # they leave together, so they share one offer below the keyboard.
        present = ttk.Frame(outer, style="Page.TFrame")
        self._build_module_line(present, "system")
        self._build_wake(present)
        self._build_drives(present)
        self._build_decky(present)
        self._module_halves["system"] = (
            self._build_module_offer(outer, "system"), present)
        self._show_module("system")
        return outer

    def _build_wake(self, parent):
        """Whether a controller can wake this machine from sleep.

        This was a switch on the HDMI CEC page, in somebody else's toolkit,
        because the toolkit needed it: the Steam button cannot reach a machine
        that sleeps. The work is one value in sysfs and sends no CEC, so it
        belongs with the other settings of the machine. A person with no
        television can want it, and removing HDMI CEC must not take it away.

        One switch that acts at its click, and not an Apply with the others.
        There is one of it, and a set of one is not a set of decisions a
        person makes together. See server/steamos_utility_center/wake.py.
        """
        box = self._section(parent, "Controller wake", card=True)
        row = ttk.Frame(box, style="OnCard.TFrame")
        row.pack(fill="x")
        row.columnconfigure(1, weight=1)
        self._wake_on = tk.BooleanVar(value=False)
        # The name is a label of its own and not the text of the switch, the
        # same as every switch on the CEC page. ttk leaves no space between
        # the picture of a switch and its own label.
        self.wake_switch = ttk.Checkbutton(row, variable=self._wake_on,
                                           command=self._wake_toggled)
        self.wake_switch.grid(row=0, column=0, sticky="w")
        named = ttk.Label(row, text="Let a controller wake the machine")
        named.grid(row=0, column=1, sticky="w", padx=(ROW_GAP, 0))
        explain = ttk.Label(
            row,
            text="Lets the Steam button of a controller wake this machine "
                 "from sleep. It writes one value on the USB radio and sends "
                 "nothing over HDMI.",
            style="Muted.TLabel", justify="left",
            wraplength=CARD_WRAP - CEC_INDENT)
        explain.grid(row=1, column=1, sticky="w", padx=(ROW_GAP, 0),
                     pady=(2, 0))
        self._wrapped.append(explain)
        self._wrap_insets[str(explain)] = named

        # The question, beside the switch it serves. "The switch is on and
        # nothing wakes the machine" needs the list of what the applier
        # matched, and nothing else on the machine reports it.
        buttons = ttk.Frame(box, style="OnCard.TFrame")
        buttons.pack(anchor="w", pady=(GROUP_GAP, 0))
        ttk.Button(buttons, text="Which radios can wake it",
                   style="Text.TButton",
                   command=self._ask_wake_radios).pack(side="left")
        # Where that answer lands. Built now and packed when there is
        # something to say, because this window has no log pane: the Runner's
        # output goes to stderr, where a terminal and the journal have it, and
        # a sentence meant to be read has to be on the page.
        self.wake_radios = ttk.Label(box, style="Muted.TLabel",
                                     justify="left", wraplength=CARD_WRAP)
        self._wrapped.append(self.wake_radios)
        self._show_wake()
        return box

    def _show_wake(self):
        """Puts the state of the switch on it, read from the machine."""
        on, _radios = ledpanel.wake_state()
        self._wake_on.set(bool(on))
        # Nothing to switch without the module. The offer above says so, and a
        # switch a person can move with no effect says the opposite.
        self.wake_switch.state(
            ["!disabled"] if on is not None else ["disabled"])

    def _wake_toggled(self):
        """Turns it on or off at the click, then reads the machine again.

        Read again and not trusted: the applier can find no radio, and then
        the switch is on and nothing changed. See _ask_wake_radios, which is
        the question that says which.
        """
        state = "on" if self._wake_on.get() else "off"

        def finished(_code):
            self._show_wake()
            self.refresh_status()

        if not self.runner.start(ledpanel.wake_switch_command(state),
                                 finished):
            # The Runner is busy, so nothing ran. Put the switch back, or it
            # says something the machine does not.
            self._show_wake()

    def _ask_wake_radios(self):
        """Asks which radios the applier found, and which of them can wake.

        A machine with the switch on and no wake gives a person no place to
        look. This asks for the list and puts the answer on the page as a
        sentence, because the JSON goes to stderr.
        """
        self.runner.start(
            ledpanel.wake_status_command(),
            lambda _code: self._say_wake_radios(
                "".join(self.runner.transcript)))

    def _say_wake_radios(self, said):
        text = wake.said(said)
        self.wake_radios.configure(text=text)
        self.wake_radios.pack(anchor="w", pady=(ROW_GAP, 0))
        self.runner.sink("\n%s\n" % text)

    def _build_decky(self, parent):
        """The Game Mode plugin, and one button that installs it.

        The panel is a window on the desktop, and Game Mode has no desktop.
        The plugin is the other half of this project, and it is on this page
        because a person who cannot find it does not know it exists.

        A card of state and one button, both from the same four words. See
        ledpanel.decky_state.
        """
        box = self._section(parent, "Game Mode Decky Plugin", card=True)
        self.decky_said = ttk.Label(box, style="Muted.TLabel", justify="left")
        self.decky_said.pack(anchor="w")
        self._wrapped.append(self.decky_said)
        self._wrap_insets[str(self.decky_said)] = 2 * GROUP_GAP
        # The one button of that row, because its name changes with the
        # state. _buttons returns the row, and the row holds the button.
        row = self._buttons(
            box, (("Add the Game Mode plugin", self.install_decky),),
            lead=ROW_GAP)
        self.decky_button = row.winfo_children()[0]
        self._show_decky()
        return box

    def _show_decky(self):
        """Puts the state of the plugin, and the name of the button, on it."""
        self._decky = ledpanel.decky_state(SOURCE_DIR)
        said, called = ledpanel.DECKY_WORDS[self._decky]
        self.decky_said.configure(text=said)
        self.decky_button.configure(text=called)

    def install_decky(self):
        """Copies the plugin in and restarts the loader, after asking."""
        if self._decky == ledpanel.DECKY_NONE and not self._ask(
                "Game Mode",
                "There is no Decky Loader on this machine, so this has "
                "nowhere to put the plugin.\n\nInstall Decky from "
                "https://decky.xyz first. Press Install to try it "
                "anyway.", confirm="Install"):
            return

        def finished(_code):
            self._show_decky()
            self._refit_page()
            self.refresh_status()

        self.runner.start(ledpanel.install_decky_command(SOURCE_DIR),
                          finished)

    def _build_drives(self, parent):
        """The second drives of this machine, and what mounts them.

        No /etc/fstab: a SteamOS update rebuilds /etc, so a line added there
        is lost. This writes one systemd mount unit for each drive, which is a
        file of this project and safe to carry across an update. See
        server/steamos_utility_center/mounts.py.
        """
        box = self._section(parent, "Drives", card=True)
        self.drives_box = ttk.Frame(box, style="OnCard.TFrame")
        self.drives_box.pack(fill="x", pady=(GROUP_GAP, 0))

        # The partition to add, read off the machine rather than typed. A
        # UUID is not a value to ask a person to copy.
        #
        # One row, with the button on it. In a _buttons row of its own, the
        # button took the first of four equal columns under two fields laid
        # out by width, and the card read as three lines with three starts.
        row = ttk.Frame(box, style="OnCard.TFrame")
        row.pack(fill="x", pady=(GROUP_GAP, 0))
        ttk.Label(row, text="Add").pack(side="left", padx=(0, ROW_GAP))
        self._drive_choice = tk.StringVar()
        self._drive_field = self._field(row, "drive-partition",
                                        self._drive_choice, [], "",
                                        width=SENSOR_WIDTH)
        self._drive_field.pack(side="left")
        self._drive_where = ttk.Entry(row, style="Material.TEntry", width=22)
        self._drive_where.pack(side="left", padx=(ROW_GAP, 0))
        self._drive_button = ttk.Button(row, text="Add this drive",
                                        style="Tonal.TButton",
                                        command=self.add_drive)
        self._drive_button.pack(side="left", padx=(GROUP_GAP, 0))
        self._drive_choice.trace_add("write", lambda *_a: self._drive_picked())

        # What the last apply said, empty until there is something to say. It
        # holds the reason a drive did not mount, which was in the output all
        # the time and needed a terminal to read. See ledpanel.drive_trouble.
        #
        # It carries its own space above it and none when it is empty, so an
        # empty one puts no band of nothing at the foot of the card. See
        # _tell_drives.
        self.drives_said = ttk.Label(box, style="Muted.TLabel", justify="left")
        self.drives_said.pack(anchor="w")
        self._wrapped.append(self.drives_said)
        self._wrap_insets[str(self.drives_said)] = 2 * GROUP_GAP
        self._show_drives()
        return box

    def _drive_picked(self):
        """Offers a mount point for the partition that a person selected.

        The label of the filesystem is the name that the person gave the
        drive, so /mnt/<label> is the answer they would type. An entry that
        somebody already filled in is left alone.
        """
        if self._drive_where.get().strip():
            return
        found = self._drive_by_uuid(self._value_for("drive-partition",
                                                    self._drive_choice.get()))
        if found:
            self._drive_where.insert(0, ledpanel.mount_point_for(found))

    def _drive_by_uuid(self, uuid):
        for found in getattr(self, "_partitions", ()):
            if found["uuid"] == uuid:
                return found
        return None

    def _show_drives(self):
        """Draws the drives of the record, and refills the partition menu."""
        for child in self.drives_box.winfo_children():
            child.destroy()

        self._partitions = mounts.partitions()
        taken = {entry["uuid"] for entry in self._drives}
        offered = [(mounts.partition_said(found), found["uuid"])
                   for found in self._partitions if found["uuid"] not in taken]
        self._menus["drive-partition"] = offered
        self._drive_field.configure(
            text=offered[0][0] if offered else "no drive to add")
        self._drive_choice.set(offered[0][0] if offered else "")

        # The column at the end takes the width that is left over. Without it
        # the grid gives that width to the buttons, and a button then stands
        # at the edge of the window far away from the drive it acts on.
        self.drives_box.columnconfigure(DRIVE_SPACER, weight=1)
        if not self._drives:
            ttk.Label(self.drives_box,
                      text="No drive is configured here.",
                      style="Muted.TLabel").grid(
                          row=0, column=DRIVE_WHERE, sticky="w",
                          columnspan=DRIVE_SPACER)
            return
        for row, entry in enumerate(sorted(self._drives,
                                           key=lambda one: one["where"])):
            self._build_one_drive(row, entry)

    def _build_one_drive(self, row, entry):
        """One drive: what it is, where it goes, and how to take it away."""
        box = self.drives_box
        gap = (0, ROW_GAP)
        ttk.Label(box, text=entry["where"]).grid(
            row=row, column=DRIVE_WHERE, sticky="w", padx=(0, GROUP_GAP),
            pady=gap)
        ttk.Label(box, text=entry["type"], style="Muted.TLabel").grid(
            row=row, column=DRIVE_TYPE, sticky="w", padx=(0, GROUP_GAP),
            pady=gap)
        mounted = os.path.ismount(entry["where"])
        ttk.Label(box, text="mounted" if mounted else "not mounted",
                  style="Good.TLabel" if mounted else "Muted.TLabel").grid(
                      row=row, column=DRIVE_STATE, sticky="w",
                      padx=(0, GROUP_GAP), pady=gap)
        # A drive that a person adds belongs to root, so Steam cannot write a
        # library to it. This is the chown, and it is offered only for a
        # filesystem that records an owner: exfat and vfat take theirs from the
        # mount options instead, and a chown on one of those fails. On a drive
        # of that kind the column stays empty, and Remove keeps its place.
        if not mounts.needs_owner_option(entry["type"]):
            ttk.Button(box, text="Take ownership", style="Text.TButton",
                       command=lambda one=entry: self.own_drive(one)).grid(
                           row=row, column=DRIVE_OWN, sticky="w",
                           padx=(0, ROW_GAP), pady=gap)
        ttk.Button(box, text="Remove", style="Text.TButton",
                   command=lambda one=entry: self.remove_drive(one)).grid(
                       row=row, column=DRIVE_REMOVE, sticky="w", pady=gap)

    def _tell_drives(self, said, bad=False):
        """Puts one sentence under the drives, or takes the last one away.

        The space above it belongs to the sentence and not to the card. An
        empty label with room above it is a band of nothing at the foot of the
        card, and this card has that shape for most of its life.
        """
        self.drives_said.configure(
            text=said, style="Bad.TLabel" if bad else "Muted.TLabel")
        self.drives_said.pack_configure(pady=(ROW_GAP if said else 0, 0))

    def add_drive(self):
        """Adds the partition that is selected, and writes the drives."""
        uuid = self._value_for("drive-partition", self._drive_choice.get())
        found = self._drive_by_uuid(uuid)
        where = self._drive_where.get().strip()
        if not found:
            self._say("Drives", "Pick a drive first.")
            return
        if not where:
            self._say("Drives", "Say where the drive should be mounted, for "
                                "example /mnt/games.")
            return
        entry = {"uuid": uuid, "where": where, "type": found["type"]}
        # exfat, ntfs3 and vfat record no owner, so the mount options carry
        # one. Without this the drive belongs to root and Steam cannot write
        # to it, and no chown can change that.
        if mounts.needs_owner_option(found["type"]):
            entry["options"] = "%s,%s" % (
                mounts.DEFAULT_OPTIONS,
                mounts.owner_options(os.getuid(), os.getgid()))
        try:
            mounts.validate(entry)
        except mounts.MountError as exc:
            self._say("Drives", str(exc))
            return
        # A mount unit holds no symlink, so the drive is recorded under the
        # resolved name. On SteamOS the root filesystem is read-only and
        # several directories in / are links into /var, so a person who writes
        # /mnt/games gets /var/mnt/games. Both names reach the same directory,
        # and the list would otherwise show one that nobody typed.
        landing = mounts.canonical(where)
        self._drive_note = ("" if landing == where.rstrip("/") else
                            "%s is a link, so the drive is recorded as %s. "
                            "A mount unit carries no link, and both names "
                            "reach the same directory."
                            % (where.rstrip("/"), landing))
        self._apply_drives(self._drives + [entry])

    def remove_drive(self, entry):
        """Takes one drive away, after asking. This unmounts it."""
        if not self._ask("Drives",
                         "This unmounts %s and stops mounting it at the "
                         "next boot.\n\nNothing on the drive is touched."
                         % entry["where"],
                         confirm="Remove"):
            return
        self._apply_drives([one for one in self._drives
                            if one["where"] != entry["where"]])

    def own_drive(self, entry):
        """Gives one mounted drive to the desktop user, with one prompt."""
        if not self._ask("Drives",
                         "This makes you the owner of every file under %s, "
                         "so that Steam can write a library there.\n\nOn a "
                         "drive with many files it takes a while."
                         % entry["where"],
                         confirm="Take ownership"):
            return
        self._apply_drives(self._drives, owner=entry["where"])

    def _apply_drives(self, entries, owner=""):
        """Writes the record, then hands it to the privileged applier."""
        try:
            record = mounts.text(entries)
        except mounts.MountError as exc:
            self._say("Drives", str(exc))
            return
        staged_path = ctl.stage(record, ctl.STAGED["drives"])

        def finished(code):
            os.unlink(staged_path)
            if code == 0:
                self._drives = entries
                self._drive_where.delete(0, "end")
                self._tell_drives(getattr(self, "_drive_note", ""))
            else:
                self._tell_drives(
                    ledpanel.drive_trouble(self.runner.transcript), bad=True)
            self._drive_note = ""
            self._show_drives()
            self._refit_page()
            self.refresh_status()

        # A run that gives a drive away carries a second argument, and no
        # line of the sudoers rule matches a command of two. That one asks
        # from the start, so there is no second run to make.
        first = ledpanel.apply_mounts_command(SOURCE_DIR, staged_path, owner)
        asking = ledpanel.apply_mounts_command(SOURCE_DIR, staged_path, owner,
                                               ask=True)
        self._run_privileged(first, None if first == asking else asking,
                             finished)
