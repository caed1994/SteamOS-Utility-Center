#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Reads what the wall panel says over its USB cable, for a while.
#
#   ./scripts/panel-log.sh /dev/ttyACM0 [seconds]
#
# No ESP-IDF and no toolchain, which is the point. `idf.py monitor` is the
# usual way to read this, and it needs the whole build environment that this
# project deliberately keeps off the machine. stty sets the speed and cat
# reads the bytes, and both are already here.
#
# It reads for a fixed time and stops. The panel talks for as long as it is
# powered, so something has to end the reading, and a window with an end is
# the one thing a button on a page can wait for.
#
# 115200 is CONFIG_ESP_CONSOLE_UART_BAUDRATE in firmware/companion. The
# secondary console goes out of the native USB port as well, so the cable
# that flashes the board also carries its log.

set -uo pipefail

BAUD=115200
DEFAULT_WINDOW=20

PORT="${1:-}"
WINDOW="${2:-$DEFAULT_WINDOW}"

die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

[[ -n "$PORT" ]] || die "usage: panel-log.sh <port> [seconds]"
[[ -e "$PORT" ]] || die "$PORT is not there. Use a data cable, not a charging one."
[[ "$WINDOW" =~ ^[0-9]+$ ]] || die "the number of seconds has to be a number"

if [[ ! -r "$PORT" ]]; then
    die "$PORT is there and this account cannot read it.
On SteamOS the group is usually uucp:  sudo usermod -aG uucp \"$USER\"
Log out and in again after that."
fi

# -hupcl, so closing the port does not drop the line and restart the board.
stty -F "$PORT" "$BAUD" raw -echo -hupcl 2>/dev/null \
    || die "could not set $PORT to $BAUD baud"

say "Reading $PORT for $WINDOW seconds. Press the button on the panel now."
echo
timeout "$WINDOW" cat "$PORT"
result=$?
echo
# 124 is what timeout returns when it ends the reading, which is the normal
# way out of here and not a fault.
if [[ $result -ne 0 && $result -ne 124 ]]; then
    die "reading $PORT stopped with $result"
fi
say "Done. Nothing above means the panel said nothing in those $WINDOW seconds."
