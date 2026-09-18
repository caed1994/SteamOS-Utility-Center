# dbus-next, carried

An unchanged copy of [dbus-next](https://pypi.org/project/dbus-next/) 0.2.3 by
Tony Crisci, MIT licensed. `ORIGIN` holds the wheel it came from and the
checksum of that wheel.

Three services of `cec-toolkit/` import it at their first line: the two that
put the machine to sleep with the television, and the one that repairs
Gamescope after a wake. Without it, all three die at once.

SteamOS ships no pip, so there is no one command that installs it. A copy
installed by hand lands under `.local/lib/python3.14/site-packages`, and the
name of that directory holds the version of Python. A SteamOS update that
raises Python thus leaves the copy behind, the three services die, and their
`Restart=on-failure` keeps them in "activating" for ever rather than letting
them fail. Every switch on the HDMI CEC page goes on saying "on".

The installer puts this tree in `/var/lib/steamos-utility-center/python`
instead. `/var` survives a SteamOS update, and that path holds no version of
Python. The module is pure Python, so one copy serves every Python 3.
