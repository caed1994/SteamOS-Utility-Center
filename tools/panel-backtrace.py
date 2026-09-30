#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn the addresses of a panel crash into names.

    tools/panel-backtrace.py steamos_companion.elf < crash.txt
    tools/panel-backtrace.py steamos_companion.elf 0x4210c53b 0x4210c409

A panic on the board prints a line that starts "Backtrace:" and a list of
address pairs. Without names it says nothing at all.

The usual way to read one needs the Xtensa toolchain, which no machine here
has and which SteamOS cannot install. This needs neither. The symbol table
of an ELF file carries the address and the length of every function, and
that is enough to say which function an address is in. It does not give a
line number, and for a crash the function is what matters first.

The ELF must be the one that built the image on the board. A different
build puts the same functions at other addresses and this then prints names
that are wrong, which is worse than printing nothing. CI keeps the ELF of
every build as an artifact named companion-elf-<commit>. The commit is in
firmware/companion/prebuilt/built-from, as a fingerprint of the source.
"""

from __future__ import annotations

import re
import struct
import sys

# The addresses in a dump come as "pc:stack pc:stack". Only the first of
# each pair is code.
ADDRESS = re.compile(r"\b(0x4[0-9a-fA-F]{7})\b")

# What the symbol table calls a function.
STT_FUNC = 2


def functions(path):
    """Every function in the file, as (address, length, name)."""
    with open(path, "rb") as handle:
        blob = handle.read()
    if blob[:4] != b"\x7fELF":
        raise SystemExit("%s is not an ELF file" % path)
    wide = blob[4] == 2                      # 1 is 32 bit, 2 is 64
    if blob[5] != 1:
        raise SystemExit("%s is not little endian" % path)

    if wide:
        shoff, = struct.unpack_from("<Q", blob, 0x28)
        shentsize, shnum = struct.unpack_from("<HH", blob, 0x3A)
        head = "<IIQQQQIIQQ"                  # section header, 64 bit
        entry = "<IBBHQQ"                     # symbol, 64 bit
        entry_size = 24
    else:
        shoff, = struct.unpack_from("<I", blob, 0x20)
        shentsize, shnum = struct.unpack_from("<HH", blob, 0x2E)
        head = "<IIIIIIIIII"                  # section header, 32 bit
        entry = "<IIIBBH"                     # symbol, 32 bit
        entry_size = 16

    sections = []
    for i in range(shnum):
        at = shoff + i * shentsize
        sections.append(struct.unpack_from(head, blob, at))

    found = []
    for section in sections:
        kind = section[1]
        if kind not in (2, 11):              # SYMTAB, DYNSYM
            continue
        # Both layouts put the offset, the size and the link at the same
        # three places in the tuples unpacked above, so this needs no case.
        offset, size = section[4], section[5]
        names = sections[section[6]]
        name_at = names[4]
        for at in range(offset, offset + size, entry_size):
            if wide:
                name, info, _other, _shndx, value, length = \
                    struct.unpack_from(entry, blob, at)
            else:
                name, value, length, info, _other, _shndx = \
                    struct.unpack_from(entry, blob, at)
            if info & 0xF != STT_FUNC or value == 0:
                continue
            end = blob.index(b"\0", name_at + name)
            found.append((value, length or 1,
                          blob[name_at + name:end].decode("utf-8", "replace")))
    found.sort()
    return found


def name_of(table, address):
    """The function that holds this address, or None."""
    low, high = 0, len(table) - 1
    best = None
    while low <= high:
        middle = (low + high) // 2
        start, length, name = table[middle]
        if start <= address:
            best = table[middle]
            low = middle + 1
        else:
            high = middle - 1
    if best is None:
        return None
    start, length, name = best
    if address >= start + length:
        return None
    return name, address - start


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    table = functions(argv[1])
    if not table:
        raise SystemExit("%s carries no symbol table" % argv[1])
    text = " ".join(argv[2:]) if len(argv) > 2 else sys.stdin.read()
    addresses = ADDRESS.findall(text)
    if not addresses:
        raise SystemExit("no addresses of the code in what was given")
    seen = []
    for one in addresses:
        if one in seen:
            continue
        seen.append(one)
        where = name_of(table, int(one, 16))
        if where is None:
            print("%s  (no function holds this address)" % one)
        else:
            print("%s  %s + %d" % (one, where[0], where[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
