#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Walks over the screens of the wall panel at random, with AddressSanitizer.
#
#   tools/panel-walk.sh [first seed] [seeds] [operations]
#
# The walk is firmware/companion/preview/check_walk.c. This script builds it
# and LVGL with AddressSanitizer and UndefinedBehaviorSanitizer, and then it
# walks each seed. It needs cmake, a C compiler and LVGL. The head of
# firmware/companion/preview/CMakeLists.txt tells you how to get LVGL.
#
# A seed that fails keeps its log, and the log names the fault and its
# place. Walk that seed again with "v" to see each operation:
#
#   <build>/check_walk <seed> <operations> v
#
# The build directory is PANEL_WALK_BUILD, or panel-walk-build in the
# temporary directory.
set -euo pipefail

first="${1:-1}"
seeds="${2:-20}"
operations="${3:-3000}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
build="${PANEL_WALK_BUILD:-${TMPDIR:-/tmp}/panel-walk-build}"
flags="-fsanitize=address,undefined -fno-omit-frame-pointer -g"

mkdir -p "$build"
cmake -S "$repo/firmware/companion/preview" -B "$build" \
      -DCMAKE_BUILD_TYPE=Debug -DCMAKE_C_FLAGS="$flags" \
      -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address,undefined" \
      > "$build/configure.log" 2>&1 \
    || { tail -20 "$build/configure.log"; exit 1; }
cmake --build "$build" --target check_walk -j"$(nproc)" \
      > "$build/build.log" 2>&1 \
    || { tail -20 "$build/build.log"; exit 1; }

# A fault is a walk that stops, a fault of memory, or undefined behaviour
# in the files of the firmware. The undefined shifts in LVGL itself are no
# fault of this project.
own="firmware/companion/(main|preview)/[^ :]+:[0-9]+:[0-9]+: runtime error"
failed=0
last=$((first + seeds - 1))
for seed in $(seq "$first" "$last"); do
    log="$build/walk-$seed.log"
    if timeout 900 "$build/check_walk" "$seed" "$operations" \
            > /dev/null 2> "$log" \
       && ! grep -Eq "ERROR: AddressSanitizer|$own" "$log"; then
        rm -f "$log"
    else
        echo "seed $seed failed: $log"
        failed=1
    fi
done
if [ "$failed" -eq 0 ]; then
    echo "seeds $first to $last, $operations operations each: no fault"
fi
exit "$failed"
