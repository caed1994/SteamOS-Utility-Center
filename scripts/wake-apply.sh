#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Lets a controller wake this machine from sleep.
#
#   wake-apply.sh apply|on|off|status
#
# A controller wakes a sleeping machine over the USB bus and not over HDMI.
# The work is one line in sysfs:
#
#     /sys/bus/usb/devices/<device>/power/wakeup <- enabled
#
# The kernel writes "disabled" there at each boot for most devices, so the
# unit of this program writes it again. That is the whole feature.
#
# It came from the SteamOS CEC Toolkit, where it lived because the toolkit
# needed it: the Steam button cannot reach a machine that sleeps. The work
# has no CEC in it, so it is a module of this project now and a person with
# no television can have it. See server/steamos_utility_center/wake.py.
#
# The four words:
#
#   apply    write the sysfs values. The unit runs this at each boot.
#   on       enable the unit, then apply.
#   off      disable the unit, then put the values back.
#   status   what the unit is, and which radios this matched. JSON.
#
# "on" and "off" are what the panel runs, and ctl.py permits those two words
# only. There is no wildcard in that rule. See ctl.sudoers_text.

set -euo pipefail

UNIT="steamos-utility-center-wake.service"
# Where this program is, so "on" can name it to the unit. Both come from the
# installer, which puts them in the same directory.
INSTALL_DIR="${WAKE_INSTALL_DIR:-/var/lib/steamos-utility-center}"
STATE_FILE="${WAKE_STATE_FILE:-$INSTALL_DIR/wake-state}"
# Where the USB bus is, so a test can point this at a made-up one.
WAKE_SYSFS="${WAKE_SYSFS:-/sys/bus/usb/devices}"
# ROOT is empty on a machine and a directory in the tests, the same way
# scripts/resume-wake.sh uses it.
UNIT_FILE="${ROOT:-}/etc/systemd/system/$UNIT"

# Which devices count as a controller receiver.
#
# The class check below is right for a plain USB Bluetooth dongle and blind to
# every wifi-and-Bluetooth combo chip, which is what a current board has.
# Measured on an AM5 board:
#
#   0e8d:0616 MediaTek Inc. Wireless_Device
#   class=ef sub=02 proto=01
#
# ef/02/01 is Interface Association: "I am several things, my classes are in
# my interfaces". So bDeviceClass can never be e0 on one of these, and a check
# on it alone matched nothing and said nothing about why. The answer is one
# level down, where the descriptor points. See has_bluetooth_interface.
WAKE_MATCH="${WAKE_MATCH:-bluetooth|steam controller|xbox|playstation|dualsense|dualshock|8bitdo|nintendo|shield|santroller}"
WAKE_EXCLUDE="${WAKE_EXCLUDE:-hub|host controller|keyboard|mouse|touchpad|aura|audio}"
WAKE_USB_IDS="${WAKE_USB_IDS:-8087:0032}"

WORD="${1:-}"
case "$WORD" in
  apply|on|off|status) ;;
  *)
    echo "usage: wake-apply.sh apply|on|off|status" >&2
    exit 2
    ;;
esac

has_bluetooth_interface() {
  local device_dir="$1" interface class sub proto
  for interface in "$device_dir"/*:*; do
    [[ -r "$interface/bInterfaceClass" ]] || continue
    class="$(cat "$interface/bInterfaceClass" 2>/dev/null || true)"
    sub="$(cat "$interface/bInterfaceSubClass" 2>/dev/null || true)"
    proto="$(cat "$interface/bInterfaceProtocol" 2>/dev/null || true)"
    [[ "$class$sub$proto" == "e00101" ]] && return 0
  done
  return 1
}

json_escape() {
  local value="${1//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/ }"
  printf '"%s"' "$value"
}

matched=0
changed=0
items=()

say_devices() {
  local separator="" item
  printf '{"matched":%d,"changed":%d,"devices":[' "$matched" "$changed"
  for item in ${items[@]+"${items[@]}"}; do
    printf '%s%s' "$separator" "$item"
    separator=","
  done
  printf ']}'
}

add_item() {
  items+=("$(printf '{"path":%s,"label":%s,"before":%s,"after":%s}' \
    "$(json_escape "$1")" "$(json_escape "$2")" \
    "$(json_escape "$3")" "$(json_escape "$4")")")
}

# Puts every value this program changed back the way it found it.
#
# The record and not "write disabled everywhere": a radio that could already
# wake the machine before this module arrived must keep that when the module
# leaves. See walk, which writes the record.
restore() {
  local device_dir previous wakeup before after
  if [[ -r "$STATE_FILE" ]]; then
    while IFS=$'\t' read -r device_dir previous; do
      wakeup="$device_dir/power/wakeup"
      [[ -e "$wakeup" && -n "$previous" ]] || continue
      before="$(cat "$wakeup" 2>/dev/null || true)"
      after="$before"
      matched=$((matched + 1))
      if [[ "$before" != "$previous" ]]; then
        printf '%s\n' "$previous" > "$wakeup"
        after="$(cat "$wakeup" 2>/dev/null || true)"
        changed=$((changed + 1))
      fi
      add_item "$device_dir" "restored" "$before" "$after"
    done < "$STATE_FILE"
  fi
  rm -f "$STATE_FILE"
}

# Looks at each USB device, and writes "enabled" on the ones that match.
#
# `writing` is 1 for apply and 0 for status, so one walk answers both "set it"
# and "what would you set". A question that walks different code from the
# answer is a question about something else.
walk() {
  local writing="$1" wakeup device_dir product vendor_id product_id
  local device_class device_subclass device_protocol usb_id manufacturer
  local label label_lower bluetooth before after

  if [[ "$writing" == 1 ]]; then
    install -d -m 0755 "$(dirname "$STATE_FILE")"
    : > "$STATE_FILE"
  fi

  for wakeup in "$WAKE_SYSFS"/*/power/wakeup; do
    [[ -e "$wakeup" ]] || continue
    device_dir="${wakeup%/power/wakeup}"
    product="$(cat "$device_dir/product" 2>/dev/null || true)"
    vendor_id="$(cat "$device_dir/idVendor" 2>/dev/null || true)"
    product_id="$(cat "$device_dir/idProduct" 2>/dev/null || true)"
    device_class="$(cat "$device_dir/bDeviceClass" 2>/dev/null || true)"
    device_subclass="$(cat "$device_dir/bDeviceSubClass" 2>/dev/null || true)"
    device_protocol="$(cat "$device_dir/bDeviceProtocol" 2>/dev/null || true)"
    usb_id="$vendor_id:$product_id"
    manufacturer="$(cat "$device_dir/manufacturer" 2>/dev/null || true)"
    label="$manufacturer $product"
    label_lower="$(printf '%s' "$label" | tr '[:upper:]' '[:lower:]')"

    bluetooth=0
    if [[ "$device_class" == e0 && "$device_subclass" == 01 \
          && "$device_protocol" == 01 ]]; then
      bluetooth=1
    elif has_bluetooth_interface "$device_dir"; then
      bluetooth=1
    fi

    if [[ "$bluetooth" -ne 1 && ! " $WAKE_USB_IDS " =~ " $usb_id " \
          && ! "$label_lower" =~ $WAKE_MATCH ]]; then
      continue
    fi
    [[ ! "$label_lower" =~ $WAKE_EXCLUDE ]] || continue

    matched=$((matched + 1))
    before="$(cat "$wakeup" 2>/dev/null || true)"
    after="$before"
    if [[ "$writing" == 1 ]]; then
      printf '%s\t%s\n' "$device_dir" "$before" >> "$STATE_FILE"
      if [[ "$before" != "enabled" ]]; then
        printf 'enabled\n' > "$wakeup"
        after="$(cat "$wakeup" 2>/dev/null || true)"
        changed=$((changed + 1))
      fi
    fi
    add_item "$device_dir" "${label#"${label%%[![:space:]]*}"} ($usb_id)" \
      "$before" "$after"
  done
}

case "$WORD" in
  apply)
    walk 1
    say_devices
    printf '\n'
    ;;
  on)
    if [[ ! -f "$UNIT_FILE" ]]; then
      echo "$UNIT is not there - install the System module first." >&2
      exit 1
    fi
    systemctl enable "$UNIT"
    walk 1
    say_devices
    printf '\n'
    ;;
  off)
    systemctl disable "$UNIT" >/dev/null 2>&1 || true
    restore
    say_devices
    printf '\n'
    ;;
  status)
    enabled="$(systemctl is-enabled "$UNIT" 2>/dev/null || true)"
    walk 0
    printf '{"unit":"%s","enabled":"%s","is_enabled":%s,"found":%s}\n' \
      "$UNIT" "$enabled" \
      "$([[ "$enabled" == enabled ]] && echo true || echo false)" \
      "$(say_devices)"
    ;;
esac
