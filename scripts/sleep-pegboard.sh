#!/bin/sh
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Take the Nanoleaf board dark while the machine sleeps, and light it again
# on the way out.
#
# Two units call this: steamos-utility-center-pegboard-sleep.service with
# "pre" before a suspend, and steamos-utility-center-pegboard-resume.service
# with "post" after a wake. systemd waits for the first one.
#
# This was a program in /usr/lib/systemd/system-sleep before, which systemd
# runs at the same two moments with the same two words. A SteamOS update
# rebuilds /usr and took the file away each time, so the board stayed lit at
# the first suspend after an update. The units are in /etc, which the
# keep-list carries. See server/steamos_utility_center/mounts.py.
#
# That wait is what this needs. The board holds the last frame
# it was sent, and a suspend only freezes the service: no frame follows, so
# the board stays lit at the last picture it drew. A shutdown always worked,
# because systemd stops the unit there and the service sends a dark frame as
# it goes.
#
# So this stops the unit, and the same dark frame goes out. It does not write
# to the board itself. The service holds /dev/hidraw* open, one frame is four
# reports, and a second writer puts its bytes between them: the board loses
# its place in the stream and draws the wrong colours. See
# server/steamos_utility_center/pegboard.py, which says what a burst does.
#
# A stop and a start of a service that begins in milliseconds, rather than a
# pipe and a word and an answer. The LED bar needs those, because its strip
# carries on by itself while the machine sleeps and the ESP has to be told
# what to draw. This board draws nothing without the host, so "off" is the
# whole of the message.

UNIT="steamos-utility-center-pegboard.service"

# A machine with no such unit is a machine with no Pegboard module. That is
# not a failure, and is-enabled answers without starting anything.
systemctl list-unit-files "$UNIT" >/dev/null 2>&1 || exit 0

case "$1" in
  pre)
    # systemd waits here, so the dark frame is on the wire before the freeze.
    systemctl stop "$UNIT" >/dev/null 2>&1 || true
    ;;
  post)
    # Only where it was switched on. A unit that a person disabled must stay
    # off, and a resume is not the moment to decide otherwise.
    if systemctl is-enabled "$UNIT" >/dev/null 2>&1; then
        systemctl start "$UNIT" >/dev/null 2>&1 || true
    fi
    ;;
esac

exit 0
