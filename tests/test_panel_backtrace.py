# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reading a crash dump off the panel.

A panic prints "Backtrace:" and a list of addresses. Reading them the usual
way needs the Xtensa toolchain, which this machine does not have and SteamOS
cannot install. tools/panel-backtrace.py reads the symbol table of the ELF
instead, which needs nothing.

The firmware is a 32 bit ELF and nothing here is, so the file these rules
read is built by hand. That is the point: the one layout that matters is the
one no binary on this machine can exercise.
"""

from __future__ import annotations

import importlib.util
import os
import struct
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "panel_backtrace", os.path.join(REPO, "tools", "panel-backtrace.py"))
backtrace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backtrace)

STT_FUNC = 2

# What the board printed the day the picture of the game took it down. Kept
# whole, because a rule written against a tidied line is a rule against
# something the panel never prints.
DUMP = """Guru Meditation Error: Core  / panic'ed (Cache error).
MMU entry fault error

Core  0 register dump:
PC      : 0x4210c53e  PS      : 0x00060434  A0      : 0x8210c40c
Backtrace: 0x4210c53b:0x3fcdffc0 0x4210c409:0x3fcdffe0 0x4200494d:0x3fce0000
"""


def elf32(functions):
    """A 32 bit little endian ELF carrying these (address, size, name)."""
    strings = b"\0"
    symbols = b""
    for address, size, name in functions:
        at = len(strings)
        strings += name.encode() + b"\0"
        symbols += struct.pack("<IIIBBH", at, address, size,
                               STT_FUNC, 0, 1)
    section_names = b"\0.symtab\0.strtab\0"

    header = 52
    entry = 40
    count = 3                                   # null, symtab, strtab
    shoff = header
    body = shoff + entry * count
    sym_at = body
    str_at = sym_at + len(symbols)
    shstr_at = str_at + len(strings)

    out = bytearray()
    out += b"\x7fELF" + bytes([1, 1, 1]) + b"\0" * 9
    out += struct.pack("<HHIIIIIHHHHHH",
                       2, 94, 1, 0, 0, shoff, 0,
                       header, 0, 0, entry, count, 2)
    out += struct.pack("<IIIIIIIIII", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    out += struct.pack("<IIIIIIIIII", 1, 2, 0, 0, sym_at, len(symbols),
                       2, 0, 4, 16)             # .symtab, link to .strtab
    out += struct.pack("<IIIIIIIIII", 9, 3, 0, 0, str_at, len(strings),
                       0, 0, 1, 0)              # .strtab
    out += symbols + strings + section_names
    del shstr_at
    return bytes(out)


class ElfTest(unittest.TestCase):
    def build(self, functions):
        handle = tempfile.NamedTemporaryFile(suffix=".elf", delete=False)
        handle.write(elf32(functions))
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_the_functions_come_out_of_a_32_bit_file(self):
        path = self.build([(0x42004900, 0x80, "network_task"),
                           (0x4210c400, 0x200, "jpeg_size")])
        found = backtrace.functions(path)
        self.assertEqual([name for _a, _s, name in found],
                         ["network_task", "jpeg_size"])

    def test_an_address_inside_one_carries_its_name_and_the_offset(self):
        path = self.build([(0x42004900, 0x80, "network_task"),
                           (0x4210c400, 0x200, "jpeg_size")])
        table = backtrace.functions(path)
        self.assertEqual(backtrace.name_of(table, 0x4210c53b),
                         ("jpeg_size", 0x13b))
        self.assertEqual(backtrace.name_of(table, 0x42004900),
                         ("network_task", 0))

    def test_an_address_in_the_gap_between_two_carries_none(self):
        """Silence beats a wrong name. The function before an address
        often ends long in front of it, and saying so is the honest
        answer."""
        path = self.build([(0x42004900, 0x80, "network_task"),
                           (0x4210c400, 0x200, "jpeg_size")])
        table = backtrace.functions(path)
        self.assertIsNone(backtrace.name_of(table, 0x42004a00))
        self.assertIsNone(backtrace.name_of(table, 0x4210d000))

    def test_something_that_is_not_an_elf_is_refused(self):
        handle = tempfile.NamedTemporaryFile(suffix=".elf", delete=False)
        handle.write(b"not an elf at all")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        with self.assertRaises(SystemExit):
            backtrace.functions(handle.name)


class DumpTest(unittest.TestCase):
    def test_the_addresses_of_the_code_are_picked_out_of_a_real_dump(self):
        """The stack pointers stand beside them and are not code. So do the
        register values, which are mostly not addresses of code at all."""
        found = backtrace.ADDRESS.findall(DUMP)
        self.assertIn("0x4210c53e", found)      # the program counter
        self.assertIn("0x4210c53b", found)      # the first frame
        self.assertIn("0x4200494d", found)
        for stack in ("0x3fcdffc0", "0x3fce0000"):
            self.assertNotIn(stack, found)
        for register in ("0x00060434", "0x8210c40c"):
            self.assertNotIn(register, found)


if __name__ == "__main__":
    unittest.main()
