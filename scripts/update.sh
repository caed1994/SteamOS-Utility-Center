#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

# Bring the clone up to date with a branch.
#
#   update.sh [--check] [branch]
#
# This has no rights, and that is deliberate. The clone belongs to the person
# who made it. Only the installation of what it brings needs rights, and that
# is a separate step after this one.
#
# It is separate from the control panel, so that a person can read all of it. A
# GUI does not build it.
#
# It refuses rather than resolves. Local edits and local commits are somebody's
# work, and an updater that throws them away to succeed is worse than one that
# stops and says what it found.

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${REMOTE:-origin}"

# Where this project lives, for a copy that has to be told.
#
# A copy that git never made has no remote to read one from. This is the one
# place the address is written down, and tests/test_update.py holds it equal
# to the address the units carry.
PROJECT_URL="${PROJECT_URL:-https://github.com/caed1994/SteamOS-Utility-Center}"

# What the installer keeps, spelled here because this script sources nothing.
# It runs as a person with no rights, and scripts/user-unit.sh is the file
# that root reads.
INSTALLED_COPY="/var/lib/steamos-utility-center/source"
STAMP_PATH="/var/lib/steamos-utility-center/installed-from"

CHECK_ONLY=0
BRANCH=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) CHECK_ONLY=1; shift ;;
        -h|--help)
            sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) BRANCH="$1"; shift ;;
    esac
done

# The branch the installer took the files from.
#
# The stamp is "<commit> <branch>". A copy that is not a clone carries no HEAD
# to read a branch from, and an adoption needs one.
# It answers "" rather than failing. This runs under `set -e` inside a
# command substitution, where a non-zero status ends the script with no
# message at all.
stamp_branch() {
    [[ -r "$STAMP_PATH" ]] || return 0
    awk 'NR == 1 { print $2 }' "$STAMP_PATH"
}

# Make a plain copy of the files into a clone, where it stands.
#
# This is the zip download, and the install whose own clone step failed. The
# files are there and the history is not, so updating them means fetching a
# history and telling git that these files belong to it.
#
# Nothing on disk is overwritten. `reset --mixed` moves the branch and the
# index and leaves every file as it is, so what differs from the branch is
# then visible rather than gone. A zip of an older version differs in a lot,
# and a person is the one who decides to drop that.
adopt_or_explain() {
    local branch differs
    branch="${BRANCH:-$(stamp_branch)}"

    if [[ -z "$branch" ]]; then
        echo "$SOURCE_DIR is not a git clone, and nothing says which branch" >&2
        echo "it came from. Name one:" >&2
        echo "  $(basename "${BASH_SOURCE[0]}") <branch>" >&2
        exit 1
    fi
    if [[ ! -w "$SOURCE_DIR" ]]; then
        echo "$SOURCE_DIR is not a git clone, and $(id -un) cannot write" >&2
        echo "into it. One run of the installer gives it to you:" >&2
        echo "  sudo $SOURCE_DIR/install.sh" >&2
        exit 1
    fi
    if [[ "$CHECK_ONLY" -eq 1 ]]; then
        echo "$SOURCE_DIR is not a git clone yet."
        echo "An update makes it a clone of $PROJECT_URL"
        echo "on $branch, and it overwrites no file while it does."
        exit 0
    fi

    echo "Making $SOURCE_DIR a clone of $PROJECT_URL ..."
    git init --quiet
    git remote add "$REMOTE" "$PROJECT_URL"
    git fetch --quiet --depth 1 "$REMOTE"
    if ! git rev-parse --verify --quiet "$REMOTE/$branch^{commit}" >/dev/null
    then
        echo "$REMOTE has no branch $branch. It has:" >&2
        git for-each-ref --format='  %(refname:strip=3)' \
            "refs/remotes/$REMOTE" >&2
        exit 1
    fi
    git symbolic-ref HEAD "refs/heads/$branch"
    git reset --mixed --quiet "$REMOTE/$branch"
    git branch --quiet --set-upstream-to "$REMOTE/$branch" "$branch" \
        >/dev/null 2>&1 || true
    echo "This copy is now $branch of $PROJECT_URL."

    differs="$(git status --porcelain --untracked-files=no)"
    [[ -z "$differs" ]] && return 0

    echo
    echo "These files differ from $branch. No file was overwritten:"
    printf '%s\n' "$differs" | sed 's/^/  /'
    echo
    echo "That is what a zip of an older version looks like. Take the branch"
    echo "version of them with:"
    echo "  git -C $SOURCE_DIR checkout -- ."
    echo "Then run this again."
    exit 0
}

cd "$SOURCE_DIR"

# Three answers to "can this be updated", and they need three messages.
#
# git refuses a repository that belongs to somebody else. It says "detected
# dubious ownership" and stops, because a repository carries configuration
# and hooks that run commands. The installed copy is in /var, and an older
# installer left it with root while the panel runs as a person. This script
# read that refusal as "there is no clone here" and printed the message about
# a zip download, on a machine that had a clone and needed one line to mend.
#
# So the refusal is read, and not only the exit status.
GIT_SAID=""
is_a_clone() {
    GIT_SAID="$(git rev-parse --is-inside-work-tree 2>&1)"
    [[ "$GIT_SAID" == "true" ]]
}

if ! is_a_clone && [[ -e "$SOURCE_DIR/.git" ]]; then
    echo "$SOURCE_DIR holds a clone that git will not read:" >&2
    printf '%s\n' "$GIT_SAID" | sed 's/^/  /' >&2
    echo >&2
    if [[ "$SOURCE_DIR" -ef "$INSTALLED_COPY" ]]; then
        echo "This is the installed copy, and it belongs to root while you" >&2
        echo "are $(id -un). One run of the installer gives it back to you:" >&2
        echo "  sudo $SOURCE_DIR/install.sh" >&2
    fi
    exit 1
fi

if ! is_a_clone; then
    adopt_or_explain
fi

if [[ -z "$BRANCH" ]]; then
    BRANCH="$(git symbolic-ref --quiet --short HEAD || true)"
    if [[ -z "$BRANCH" ]]; then
        echo "No branch given, and this clone is not on one (detached HEAD)." >&2
        echo "Pick a branch to update to." >&2
        exit 1
    fi
fi

echo "Fetching $REMOTE ..."
git fetch --prune "$REMOTE"

TARGET="$REMOTE/$BRANCH"
if ! git rev-parse --verify --quiet "$TARGET^{commit}" >/dev/null; then
    echo "$REMOTE has no branch called $BRANCH. It has:" >&2
    git for-each-ref --format='  %(refname:strip=3)' "refs/remotes/$REMOTE" >&2
    exit 1
fi

BEFORE="$(git rev-parse HEAD)"
BEHIND="$(git rev-list --count "HEAD..$TARGET")"
AHEAD="$(git rev-list --count "$TARGET..HEAD")"

# Only tracked files matter: an untracked file of your own cannot conflict with
# a fast-forward, and git says so itself in the one case where it can.
DIRTY="$(git status --porcelain --untracked-files=no)"

if [[ $CHECK_ONLY -eq 1 ]]; then
    if [[ "$BEHIND" == "0" ]]; then
        echo "Already up to date with $TARGET."
    else
        echo "$BEHIND commit(s) waiting on $TARGET:"
        git log --oneline --no-decorate -20 "HEAD..$TARGET" | sed 's/^/  /'
        [[ "$BEHIND" -gt 20 ]] && echo "  ... and $((BEHIND - 20)) more"
    fi
    [[ -n "$DIRTY" ]] && echo && echo "Note: there are local changes; updating would stop and list them."
    [[ "$AHEAD" != "0" ]] && echo && echo "Note: $AHEAD local commit(s) are not on $TARGET; updating would stop."
    exit 0
fi

if [[ -n "$DIRTY" ]]; then
    echo "There are local changes to files this update would replace:" >&2
    echo "$DIRTY" | sed 's/^/  /' >&2
    echo >&2
    echo "Nothing was changed. Keep them with 'git -C $SOURCE_DIR stash', or" >&2
    echo "throw them away with 'git -C $SOURCE_DIR checkout -- <file>'." >&2
    exit 1
fi

CURRENT="$(git symbolic-ref --quiet --short HEAD || true)"
if [[ "$CURRENT" != "$BRANCH" ]]; then
    echo "Switching to $BRANCH ..."
    if git rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null; then
        git checkout "$BRANCH"
    else
        git checkout --track "$TARGET"
    fi
fi

# --ff-only: this is an update, not a merge. Local commits mean somebody is
# working here, and the honest answer is to say so rather than to invent a
# merge commit in their checkout.
if ! git merge --ff-only "$TARGET"; then
    echo >&2
    echo "$BRANCH has commits of its own that are not on $TARGET, so it cannot" >&2
    echo "simply be fast-forwarded. Nothing was changed." >&2
    echo "Look at them with: git -C $SOURCE_DIR log --oneline $TARGET..HEAD" >&2
    exit 1
fi

AFTER="$(git rev-parse HEAD)"
if [[ "$BEFORE" == "$AFTER" ]]; then
    echo "Already up to date with $TARGET."
    exit 0
fi

echo
echo "Updated $BRANCH to $(git rev-parse --short HEAD):"
git log --oneline --no-decorate -20 "$BEFORE..$AFTER" | sed 's/^/  /'
COUNT="$(git rev-list --count "$BEFORE..$AFTER")"
[[ "$COUNT" -gt 20 ]] && echo "  ... and $((COUNT - 20)) more"

# This message is necessary, because people forget this half.
#
# This script changes the clone and nothing else. The files that run are in
# /var/lib, and the installer puts them there.
#
# Two people read a log from the old copy while they looked at the new commits.
# This script caused that mistake: it stopped here with no message.
#
# The button in the panel runs the installer immediately after this, and it
# needs no message. A person at a terminal needs one.
#
# The status page of the panel also reports this. It uses the commit that the
# installer records. See install_is_behind.
echo
echo "That was the clone. The files that run are installed separately:"
echo "  sudo $SOURCE_DIR/install.sh"
echo "Until then this machine keeps running what it had."
exit 0
