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
BAUD="460800"

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
    VENDOR="$(udevadm info --query=property --name="$PORT" 2>/dev/null \
              | sed -n 's/^ID_VENDOR_ID=//p' | head -1)"
    MODEL="$(udevadm info --query=property --name="$PORT" 2>/dev/null \
             | sed -n 's/^ID_MODEL=//p' | head -1)"
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

say "Writing the firmware to $PORT"
# The offsets are the ones the partition table in firmware/companion gives.
# They are spelled here because this script runs with no ESP-IDF to ask.
"$VENV/bin/python" -m esptool --chip "$CHIP" --port "$PORT" --baud "$BAUD" \
    --before default_reset --after hard_reset write_flash \
    --flash_mode dio --flash_freq 80m --flash_size 16MB \
    0x0 "$BOOTLOADER" \
    0x8000 "$PARTITIONS" \
    0x10000 "$APPLICATION"

say "Done. The panel restarts and asks for its network and this machine."
