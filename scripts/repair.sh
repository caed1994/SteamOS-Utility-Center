#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Writes back what a SteamOS update took away, at each boot.
#
#   repair.sh
#
# server/steamos-utility-center-repair.service runs it. A person can run it
# by hand with sudo, and it does the same thing.
#
# The work is in server/steamos_utility_center/repair.py, because a test can
# read that and cannot read a script that unlocks a filesystem. This part is
# the three things a test cannot do: the unlock, the reload of systemd and
# udev, and the start of a service that was gone a moment ago.
#
# Nothing here writes a settings file. See repair.py for the whole list of
# what a repair leaves alone.

set -euo pipefail

# Every path below starts with this. On a machine it is empty, and the paths
# are the absolute paths that they read as.
#
# It is here so that a test can run this script against a directory that the
# test built, which is the only way to check the branches of it with no root
# and no systemd. scripts/user-unit.sh carries the same name for the same
# reason. Only the tests set it.
ROOT="${ROOT:-}"

INSTALL_DIR="$ROOT/var/lib/steamos-utility-center"
PROGRAM="$INSTALL_DIR/steamos-utility-center"
UNIT_DIR="$ROOT/etc/systemd/system"
WANTS="$UNIT_DIR/multi-user.target.wants"

say()  { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }

if [[ ! -x "$PROGRAM" ]]; then
    warn "no $PROGRAM, so there is nothing to repair from"
    exit 0
fi

# Read the machine first, and write nothing.
#
# This costs one Python start at a boot and it needs no root. The filesystem
# stays read-only on a machine that is in order, which is every boot but the
# first one after an update.
#
# The check exits 1 for a file that it cannot write, and that file is still
# worth the report. So the output decides here and the exit status does not.
missing="$("$PROGRAM" --repair-check 2>&1)" || true
if [[ -z "$missing" ]]; then
    say "Nothing to write back."
    exit 0
fi

say "These are gone:"
printf '%s\n' "$missing" | sed 's/^/  /'

# SteamOS keeps / read-only, and /etc and /usr/local/bin are both on it.
LOCK_AGAIN=0
relock_rootfs() {
    [[ "$LOCK_AGAIN" -eq 1 ]] || return 0
    steamos-readonly enable || true
}
trap relock_rootfs EXIT
if command -v steamos-readonly >/dev/null 2>&1; then
    if steamos-readonly status 2>/dev/null | grep -q enabled; then
        steamos-readonly disable
        LOCK_AGAIN=1
    fi
fi

said="$("$PROGRAM" --repair 2>&1)" || true
printf '%s\n' "$said"

systemctl daemon-reload || warn "could not reload systemd"
if printf '%s' "$said" | grep -q 'udev/rules.d'; then
    udevadm control --reload >/dev/null 2>&1 || warn "could not reload udev"
    udevadm trigger --subsystem-match=tty >/dev/null 2>&1 || true
fi

# Start a service that was written a moment ago.
#
# systemd worked out this boot before the file was there, so a link in a
# .wants directory does nothing until the next one. Without this the machine
# repairs itself and the feature comes back one restart later.
#
# Only the services that run all the time. A unit of a sleep or of a wake is
# a moment, and to start one at a boot is that moment happening for no reason.
#
# --no-block, and this is not a preference. Three of these units carry
# `After=multi-user.target`, and this one runs before that target. A start
# that waited for such a job would wait for the target, and the target waits
# for this unit. The queued job runs when the target is reached, which is
# when it runs on any other boot.
while read -r verb path; do
    [[ "$verb" == "wrote" ]] || continue
    # A * matches a / in a bash pattern, so the .wants links come through
    # this test as well. They are not units and they do not start.
    [[ "$path" == "$UNIT_DIR"/*.service && "$path" != *.wants/* ]] || continue
    unit="$(basename "$path")"
    [[ -e "$WANTS/$unit" ]] || continue
    say "Starting $unit"
    systemctl start --no-block "$unit" || warn "$unit did not start"
done <<< "$said"

exit 0
