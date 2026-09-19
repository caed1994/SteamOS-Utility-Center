#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Runs one remove_<module> of install.sh against a machine in a directory.
#
#   run-remove.sh <function> <purge> <root>
#
# Every test of the removals read the source of install.sh and none of them
# ran one. So "--purge removes the settings" was a grep for the word PURGE,
# and the purge that left a file under the project's old name passed it.
#
# The steps that reach outside the directory are replaced below. What stays
# is the part under test: which files the function removes.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

FUNC="${1:?usage: run-remove.sh <function> <purge> <root>}"
PURGE="${2:?}"
ROOT="${3:?}"
export ROOT

# shellcheck source=/dev/null
source "$REPO/scripts/user-unit.sh"

# On stdout, because a test reads it. The installer prints "and the
# settings in <path>" after a purge, and that line has to follow what
# the purge did rather than what it was asked to do.
say()  { echo "$*"; }
warn() { echo "warn: $*" >&2; }
systemctl() { :; }
udevadm()   { :; }
remove_legacy_sleep_hooks() { :; }
remove_user_units()   { :; }
remove_mount_units()  { :; }
remove_decky_plugin() { :; }

SOURCE_DIR="$REPO"
eval "$(awk "/^$FUNC\\(\\)/,/^}/" "$REPO/install.sh")"
"$FUNC"
