# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Running a command from the window, without freezing it.

Only the thread that owns tkinter can touch a widget, so the work happens on
another thread and its output arrives through a queue that the window reads
on a timer.

It is not a widget. It takes one, because it needs somewhere to hang that
timer, and it writes through the two functions the caller gives it.

In its own module and not beside the window's widgets: a reader looking for
"how does this window run a command" looks for a file with that name.
"""

from __future__ import annotations

import queue
import subprocess
import threading

import ledpanel


class Runner:
    """Runs a command without freezing the window.

Only the thread that owns tkinter can call it. So the worker puts its
    lines into a queue, and the window reads that queue on a timer.
    """

    def __init__(self, widget, sink, on_state=None):
        # sink(text, tag=None). The tag is optional, so a simple writer works.
        # on_state(busy, code) gives the text of the window during a command,
        # and the result at the end. It is optional, so a Runner also works
        # without it.
        self.widget = widget
        self.sink = sink
        self.on_state = on_state or (lambda _busy, _code: None)
        self.queue = queue.Queue()
        self.busy = False
        self.transcript = []
        self._job = None
        # The timer outlives the window otherwise: closing it leaves one drain
        # already booked, which then fires at a callback that no longer exists
        # and Tk reports as an invalid command name.
        widget.bind("<Destroy>", self._stop, add="+")
        self._drain()

    def _stop(self, event=None):
        if event is not None and event.widget is not self.widget:
            return                          # a child of ours, not the window
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job = None

    def start(self, command, done=None):
        if self.busy:
            self.sink("Still busy with the last command.\n")
            return False
        self.busy = True
        self.transcript = []
        self.on_state(True, None)
        self.sink("$ %s\n" % " ".join(command), "command")
        threading.Thread(target=self._work, args=(command, done),
                         daemon=True).start()
        return True

    def _work(self, command, done):
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
        except OSError as exc:
            self.queue.put(("line", "cannot run: %s\n" % exc))   # noqa
            self.queue.put(("done", (1, done)))
            return
        for line in process.stdout:
            self.transcript.append(line)
            self.queue.put(("line", line))
        code = process.wait()
        self.queue.put(("done", (code, done)))

    def _drain(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "line":
                    self.sink(payload)
                else:
                    code, done = payload
                    self.busy = False
                    self.sink("[exit %d]\n" % code, "command")
                    self.on_state(False, code)
                    # pkexec's own complaint explains nothing to anyone who
                    # has not met it before; say what it means instead.
                    if ledpanel.looks_like_no_auth_agent(
                            "".join(self.transcript), code):
                        self.sink("\n%s\n" % ledpanel.NO_AGENT_ADVICE)
                    self.sink("\n")
                    if done is not None:
                        done(code)
        except queue.Empty:
            pass
        self._job = self.widget.after(120, self._drain)
