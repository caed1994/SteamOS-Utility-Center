#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Installs PlatformIO for the person who runs this, and puts pio on their PATH.
#
#   scripts/install-platformio.sh            install it, or say it is there
#   scripts/install-platformio.sh --force    install it again over what is there
#   scripts/install-platformio.sh --where    print where pio is, or exit 1
#
# As the user, and never as root. The toolchains land in ~/.platformio, and a
# copy of that owned by root stops every later run the person makes. install.sh
# is root and reaches this through runuser; the panel is already the user and
# runs it directly, which is why its button asks for no password.

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/user-unit.sh
source "$SOURCE_DIR/scripts/user-unit.sh"

[[ $EUID -ne 0 ]] || {
    warn "run this as the person who uses PlatformIO, not as root"
    exit 2
}

WANT_FORCE=0
WANT_WHERE=0
case "${1:-}" in
    --force) WANT_FORCE=1 ;;
    --where) WANT_WHERE=1 ;;
    "") ;;
    *) echo "usage: install-platformio.sh [--force|--where]" >&2; exit 2 ;;
esac

# Where pio is, if it is anywhere.
#
# The standalone installer puts it under ~/.platformio/penv/bin and pip puts
# it in ~/.local/bin. A shell that starts after either of those finds it on
# the PATH, and a person can also install it in a way of their own.
find_pio() {
    local candidate
    candidate="$(command -v pio 2>/dev/null || true)"
    if [[ -n "$candidate" && -x "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi
    for candidate in "$HOME/.platformio/penv/bin/pio" "$HOME/.local/bin/pio"; do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

if [[ $WANT_WHERE -eq 1 ]]; then
    find_pio
    exit $?
fi

if [[ $WANT_FORCE -eq 0 ]] && found="$(find_pio)"; then
    say "PlatformIO is already installed: $found"
    say "Run this with --force to install it again."
    exit 0
fi

# The standalone installer, and not pip. SteamOS keeps the rootfs read-only, so
# a system-wide pip install cannot write, and "pip install --user" writes to a
# directory that the next system update resets. This puts all of PlatformIO
# under ~/.platformio, which a system update keeps. It is also the method that
# the PlatformIO documentation gives.
say "Fetching $PLATFORMIO_INSTALLER_URL"
script="$(mktemp -t get-platformio-XXXXXX.py)"
trap 'rm -f "$script"' EXIT
curl -fsSL -o "$script" "$PLATFORMIO_INSTALLER_URL"
python3 "$script"

# In scripts/user-unit.sh, beside the strings it writes and the check that the
# uninstaller makes against them.
add_platformio_to_path "$HOME" || true

say "PlatformIO installed. Open a new shell, or run: source ~/.bashrc"
