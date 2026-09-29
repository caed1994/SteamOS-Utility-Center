#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Lets a magic packet on the network wake this machine.
#
#   wol-apply.sh on|off|status
#
# The wall panel sends that packet. It is the one thing the panel does
# without the service on this machine, because the service is not running
# when the machine is off. See firmware/companion/main/panel_wol.c.
#
# The card has to be told to listen for it, and that is one property of one
# NetworkManager connection:
#
#     802-3-ethernet.wake-on-lan <- magic
#
# NetworkManager keeps that in the connection file, so unlike controller
# wake this needs no unit that writes it again at each boot. It reaches the
# card when the connection is brought up, which is why "on" brings it down
# and up again rather than leaving the change for the next start.
#
# The three words:
#
#   on       set the property, then bring the connection up again.
#   off      set it back to default, the same way.
#   status   what the connection says and what the card says. JSON.
#
# "on" and "off" are what the page runs through sudo, and ctl.py permits
# those two words only. The connection is not an argument: a rule that took
# one would need a wildcard, and this program finds the connection itself.
# See ctl.sudoers_text.
#
# Only a wired card. Wake on LAN over radio is unreliable to absent on the
# cards people have, and a switch that promises it is a switch that lies.

set -euo pipefail

# Where the network lives, so a test can point this at a made-up one.
NET_SYSFS="${WOL_NET_SYSFS:-/sys/class/net}"
NMCLI="${WOL_NMCLI:-nmcli}"

WORD="${1:-}"
case "$WORD" in
  on|off|status) ;;
  *)
    echo "usage: wol-apply.sh on|off|status" >&2
    exit 2
    ;;
esac

json_escape() {
  local value="${1//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/ }"
  printf '"%s"' "$value"
}

# Whether that card is one a magic packet can reach.
#
# The same three questions the service asks in companion.wake_target: real
# hardware behind it, no radio, and the type of an ethernet card.
is_wired() {
  local name="$1" path="$NET_SYSFS/$1"
  [[ -e "$path/device" ]] || return 1
  [[ -d "$path/wireless" ]] && return 1
  [[ -e "$path/phy80211" ]] && return 1
  [[ "$(cat "$path/type" 2>/dev/null || true)" == "1" ]] || return 1
  return 0
}

# The wired card, and the connection that is on it.
#
# nmcli names the device in its terse listing, so the two are found in one
# pass. A machine with several takes the first that carries a connection.
find_connection() {
  local line name device candidate=""
  while IFS=: read -r name device; do
    [[ -n "$name" && -n "$device" ]] || continue
    is_wired "$device" || continue
    CONNECTION="$name"
    DEVICE="$device"
    return 0
  done < <("$NMCLI" -t -f NAME,DEVICE connection show --active 2>/dev/null || true)
  return 1
}

# What the connection file says about waking.
stored_value() {
  "$NMCLI" -t -f 802-3-ethernet.wake-on-lan connection show "$1" 2>/dev/null \
    | sed 's/^[^:]*://' | head -1
}

# What the card itself says. This is readable by everybody, and it is a
# different question from the one above: the connection holds the wish, and
# this holds whether the hardware was told.
card_wakeup() {
  cat "$NET_SYSFS/$1/device/power/wakeup" 2>/dev/null || true
}

if ! find_connection; then
  if [[ "$WORD" == "status" ]]; then
    printf '{"found":false}\n'
    exit 0
  fi
  echo "wol-apply.sh: no wired connection to set this on" >&2
  exit 1
fi

case "$WORD" in
  status)
    printf '{"found":true,"connection":%s,"device":%s,"stored":%s,"card":%s}\n' \
      "$(json_escape "$CONNECTION")" "$(json_escape "$DEVICE")" \
      "$(json_escape "$(stored_value "$CONNECTION")")" \
      "$(json_escape "$(card_wakeup "$DEVICE")")"
    ;;
  on|off)
    WANT="default"
    [[ "$WORD" == "on" ]] && WANT="magic"
    "$NMCLI" connection modify "$CONNECTION" 802-3-ethernet.wake-on-lan "$WANT"
    # Down and then up, because the property reaches the card when the
    # connection is brought up. Without this the switch does nothing until
    # the next start, and somebody who shuts the machine down right away
    # finds a card that was never told.
    "$NMCLI" connection down "$CONNECTION" >/dev/null
    "$NMCLI" connection up "$CONNECTION" >/dev/null
    printf '{"connection":%s,"stored":%s}\n' \
      "$(json_escape "$CONNECTION")" \
      "$(json_escape "$(stored_value "$CONNECTION")")"
    ;;
esac
