#!/bin/sh
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Turn the Nanoleaf devices on the network off before the machine sleeps.
#
# NetworkManager runs this, and not systemd. A unit with Before=sleep.target
# runs too late for a device on the network. NetworkManager answers the
# PrepareForSleep signal of logind and takes the interface down, and that
# happens before any unit of the sleep transition starts. The journal of this
# machine gave the order:
#
#   NM:       device (enp11s0): state change: disconnected -> unmanaged
#             (reason 'unmanaged-sleeping')
#   systemd:  Starting Turn the Nanoleaf devices off before sleep...
#   nanoleaf: 192.168.178.93 did not answer: [Errno 101] Network is unreachable
#
# Errno 101 is not a timeout. It says that there is no route any more, and no
# order of units repairs that: NetworkManager acts on a signal and not as a
# unit, so nothing in the sleep transition is early enough.
#
# pre-down is the moment before the disconnection. The manual of the
# dispatcher names it so, and NetworkManager waits here for this script. The
# call thus goes out while the route is still there.
#
# NetworkManager runs this as root. The record of the devices is in the home
# directory of the person who paired them, so the call drops to that account.
#
# Log: journalctl -t steamos-utility-center-nanoleaf

TAG="steamos-utility-center-nanoleaf"

# The dispatcher gives every script the interface and the action.
[ "$2" = "pre-down" ] || exit 0

# A sleep, and not every disconnection.
#
# pre-down also arrives when somebody takes the cable out or turns a
# connection off. The lights follow the machine and not the cable, so this
# asks logind which of the two it is. The property is true from the moment
# logind announces the sleep until the machine is awake again.
#
# The answer is the type and the value, so "b false" on a machine that a
# person is at, and "b true" from the announcement of the sleep until the
# wake. Both were read on the machine this is for.
#
# Any other answer gets the off. busctl is part of systemd and is always
# there, so something else is wrong at that point, and of the two halves dark
# lamps are the safer one.
state="$(busctl get-property org.freedesktop.login1 /org/freedesktop/login1 \
         org.freedesktop.login1.Manager PreparingForSleep 2>/dev/null)"
if [ "$state" = "b false" ]; then
    logger -t "$TAG" "$1 went down while the machine is awake, so the lights stay"
    exit 0
fi

# One try for each device, with a timeout of some seconds. NetworkManager
# waits here, and a lamp that misses this message stays lit until the wake.
runuser -u @WATCHER_USER@ -- \
    @INSTALL_DIR@/steamos-utility-center-nanoleaf off 2>&1 | logger -t "$TAG"

exit 0
