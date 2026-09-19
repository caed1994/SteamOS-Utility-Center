#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Runs copy_toolbox of install.sh against two directories.
#
#   run-copy-toolbox.sh <source-dir> <copy-dir>
#
# Every test of the copy read the source of install.sh, so "the copy is a
# clone" was a grep. It passed while the copy was a clone of one branch: the
# menu on the update page then offered one branch on an installed machine,
# and four in the clone it came from.
#
# The steps that need root are replaced below. The git work is not.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

SOURCE_DIR="${1:?usage: run-copy-toolbox.sh <source-dir> <copy-dir>}"
SOURCE_COPY="${2:?}"

say()  { :; }
warn() { echo "warn: $*" >&2; }
give_away_toolbox() { :; }

# copy_toolbox and the helper it calls. A harness that took one of the two
# left the other undefined, and bash reported that on stderr and carried on:
# the test then measured a step that never ran.
for name in widen_toolbox_branches copy_toolbox; do
    eval "$(awk "/^$name\\(\\)/,/^}/" "$REPO/install.sh")"
    declare -F "$name" >/dev/null \
        || { echo "no function $name in install.sh" >&2; exit 2; }
done
copy_toolbox
