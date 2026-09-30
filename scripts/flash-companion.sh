#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Writes the wall panel's firmware to a Waveshare ESP32-S3-Touch-LCD-4B.
#
#   ./scripts/flash-companion.sh /dev/ttyACM0 [image directory]
#
# No ESP-IDF and no toolchain. This needs three files that a build leaves
# behind, and esptool, which it puts in a virtual environment in the home
# directory of the caller. The rootfs of SteamOS is read-only, so pip has
# nowhere else to write, and "pip install --user" lands where the next system
# update takes it.
#
# The image that comes with this version is in firmware/companion/prebuilt,
# built by CI from the firmware beside it, and that is the default. The panel
# page passes the directory rather than leaving it to this script: the page
# knows whether a build of your own is there, and one decider is one answer.
#
# Not run as root. The port needs the caller in the right group, and a
# virtual environment owned by root stops every later run that person makes.
# See scripts/install-platformio.sh, which refuses root for the same reason.
#
set -euo pipefail

# The version this was tested against. A newer esptool changes its command
# line between releases, and a flash that stops halfway is a board that needs
# the BOOT button to come back.
ESPTOOL_VERSION="4.12.0"
CHIP="esp32s3"

# How fast, over a wire where that means something.
#
# A board on a USB-to-serial chip really runs at this rate and the write
# takes about a quarter of the time it would at 115200.
BAUD="460800"

# And the rate over the native USB port of the chip, which is a number with
# nothing behind it.
#
# The panel reports "USB mode: USB-Serial/JTAG", so it is a USB device of
# its own and not a serial chip. The rate of a USB CDC device is a field the
# hardware ignores; the speed is USB's. esptool does not know that: it calls
# change_baud whenever the rate asked for is above the one it connects with,
# on this port as on any other. So the number bought no speed and added a
# handshake in the middle of a flash, and the flash stopped in the middle
# again and again with "Lost connection" and "The chip stopped responding".
#
# 115200 is the rate esptool connects at, so this asks for no change at all.
USB_BAUD="115200"

# The USB-Serial/JTAG unit of an Espressif chip. esptool knows it by the
# same number: USB_JTAG_SERIAL_PID in esptool/loader.py.
NATIVE_USB="1001"

# How many times to write the whole flash before giving up.
#
# Writing it again from the start is safe: every byte is written and
# verified against its own hash, so a second run repairs whatever a first
# run left behind. What it is not is free, so this stops at three.
ATTEMPTS=3

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

PORT="${1:-}"
BUILD="${2:-$REPO/firmware/companion/prebuilt}"

die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

[[ -n "$PORT" ]] || die "usage: flash-companion.sh <port> [image directory]"
[[ $EUID -ne 0 ]] || die "run this as yourself, not with sudo. See the note above."
[[ -e "$PORT" ]] || die "$PORT is not there. Use a data cable, not a charging one."

# Whose board is on that port.
#
# This writes a whole flash, and the port it writes to used to be a guess in
# a text field on a page. An ESP32-S3 has the vendor of Espressif, and a
# Steam Controller dongle, an FTDI board and a printer do not. Reading the
# vendor disturbs nothing: it is a file that udev already filled in.
#
# esptool refuses a wrong chip as well, with --chip above, but it resets the
# board before it looks. A reset of somebody else's device is a small thing
# and it is not nothing, so the question is asked before that.
#
# A machine with no udevadm gets no check and a line saying so, rather than
# a refusal to flash a board that is probably right.
ESPRESSIF="303a"
if command -v udevadm >/dev/null 2>&1; then
    PROPERTIES="$(udevadm info --query=property --name="$PORT" 2>/dev/null)"
    VENDOR="$(printf '%s\n' "$PROPERTIES" | sed -n 's/^ID_VENDOR_ID=//p' | head -1)"
    MODEL="$(printf '%s\n' "$PROPERTIES" | sed -n 's/^ID_MODEL=//p' | head -1)"
    PRODUCT="$(printf '%s\n' "$PROPERTIES" | sed -n 's/^ID_MODEL_ID=//p' | head -1)"
    # The same answer esptool prints as "USB mode: USB-Serial/JTAG", read
    # before the board is touched rather than after.
    if [[ "${PRODUCT,,}" == "$NATIVE_USB" ]]; then
        BAUD="$USB_BAUD"
        say "This board talks over the USB port of the chip itself, where a
    baud rate is a number with nothing behind it. Asking for $USB_BAUD,
    which asks esptool to change nothing."
    fi
    if [[ -n "$VENDOR" && "${VENDOR,,}" != "$ESPRESSIF" ]]; then
        die "$PORT is not an Espressif board. It reports ${MODEL:-vendor $VENDOR}.
The panel is an ESP32-S3 and shows up as an Espressif device. Look at
  ls -l /dev/serial/by-id/
and use the one whose name holds Espressif."
    fi
else
    say "No udevadm here, so nothing checked which board is on $PORT."
fi

# The three parts of an image, at the offsets the partition table gives.
BOOTLOADER="$BUILD/bootloader/bootloader.bin"
PARTITIONS="$BUILD/partition_table/partition-table.bin"
APPLICATION="$BUILD/steamos_companion.bin"
for part in "$BOOTLOADER" "$PARTITIONS" "$APPLICATION"; do
    [[ -f "$part" ]] || die "no firmware in $BUILD ($(basename "$part") is missing).
Update the panel, which brings the image, or build one yourself:
  cd firmware/companion && idf.py set-target esp32s3 && idf.py build"
done

VENV="$HOME/.local/share/steamos-utility-center/esptool"
if [[ ! -x "$VENV/bin/python" ]]; then
    say "Making a Python environment for esptool in $VENV"
    python3 -m venv "$VENV" || die "could not create $VENV"
fi
if ! "$VENV/bin/python" -c "import importlib.metadata as m
assert m.version('esptool') == '$ESPTOOL_VERSION'" 2>/dev/null; then
    say "Installing esptool $ESPTOOL_VERSION"
    "$VENV/bin/python" -m pip install --quiet "esptool==$ESPTOOL_VERSION" \
        || die "could not install esptool. Is this machine on the network?"
fi

# The offsets are the ones the partition table in firmware/companion gives.
# They are spelled here because this script runs with no ESP-IDF to ask.
write_it() {
    "$VENV/bin/python" -m esptool --chip "$CHIP" --port "$PORT" --baud "$BAUD" \
        --before default_reset --after hard_reset write_flash \
        --flash_mode dio --flash_freq 80m --flash_size 16MB \
        0x0 "$BOOTLOADER" \
        0x8000 "$PARTITIONS" \
        0x10000 "$APPLICATION"
}

# Again, rather than the person again.
#
# A write of two megabytes over this port stops in the middle now and then,
# and every stop reads as "Lost connection" or "The chip stopped
# responding". Whatever the reason of the day, the answer is the same, and
# this gives it rather than the person at the keyboard.
#
# Nothing here is lost by a second run. esptool writes every block and
# checks it against its own hash, and a partition written twice holds what
# the second run put there. A run that stopped halfway leaves a board that
# cannot start, and the only way out of that is exactly this: write it
# again.
for attempt in $(seq 1 "$ATTEMPTS"); do
    if [[ "$attempt" -eq 1 ]]; then
        say "Writing the firmware to $PORT"
    else
        say "That stopped before the end. Trying again, $attempt of $ATTEMPTS."
        # The board restarts itself after a broken write and takes a moment
        # to show up on the port again.
        sleep 2
        [[ -e "$PORT" ]] || die "$PORT went away. Unplug the board and plug it
in again, then run this once more."
    fi
    if write_it; then
        say "Done. The panel restarts and asks for its network and this machine."
        exit 0
    fi
done

die "The firmware did not go over in $ATTEMPTS tries.
The board holds half an image now and does not start. That is not broken:
run this again, and if it keeps stopping, use another USB cable or another
port. A hub between the two is worth taking out."
