#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Writes the wall panel's firmware to a Waveshare ESP32-S3-Touch-LCD-4B.
#
#   ./scripts/flash-companion.sh /dev/ttyACM0 [build directory]
#
# No ESP-IDF and no toolchain. This needs three files that a build leaves
# behind, and esptool, which it puts in a virtual environment in the home
# directory of the caller. The rootfs of SteamOS is read-only, so pip has
# nowhere else to write, and "pip install --user" lands where the next system
# update takes it.
#
# Not run as root. The port needs the caller in the right group, and a
# virtual environment owned by root stops every later run that person makes.
# See scripts/install-platformio.sh, which refuses root for the same reason.
#
# The image itself is not in this repository. It is 1.5 MB of build output
# that goes out of date at the first change to firmware/companion, and a
# stale binary beside the source it no longer matches is worse than none.
# Build it one time with ESP-IDF v5.5:
#
#     cd firmware/companion && idf.py set-target esp32s3 && idf.py build

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
BUILD="${2:-$REPO/firmware/companion/build}"

die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

[[ -n "$PORT" ]] || die "usage: flash-companion.sh <port> [build directory]"
[[ $EUID -ne 0 ]] || die "run this as yourself, not with sudo. See the note above."
[[ -e "$PORT" ]] || die "$PORT is not there. Use a data cable, not a charging one."

# The three parts of an image, at the offsets the partition table gives.
BOOTLOADER="$BUILD/bootloader/bootloader.bin"
PARTITIONS="$BUILD/partition_table/partition-table.bin"
APPLICATION="$BUILD/steamos_companion.bin"
for part in "$BOOTLOADER" "$PARTITIONS" "$APPLICATION"; do
    [[ -f "$part" ]] || die "no firmware in $BUILD ($(basename "$part") is missing).
Build it first:  cd firmware/companion && idf.py set-target esp32s3 && idf.py build"
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
