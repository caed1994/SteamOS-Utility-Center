# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Waking the PC from the panel, read out of the firmware.

The packet itself is checked where it can really be built:
firmware/companion/preview/check_wol.c reads all 102 bytes of it and gives
the address parser ten texts it has to refuse. That needs a compiler, so it
runs in the job.

What these hold is the shape around it. A wake that does not work leaves
nothing behind: no error, no log on the far side, only a machine that stays
off. So the things that would break it quietly are written down here.
"""

from __future__ import annotations

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(REPO, "firmware", "companion")
FIRMWARE = os.path.join(COMPANION, "main")
PREVIEW = os.path.join(COMPANION, "preview")


def read(name, where=FIRMWARE):
    with open(os.path.join(where, name), encoding="utf-8") as handle:
        return handle.read()


def without_comments(text):
    """The C with its comments taken out, because these read calls."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


class PacketModuleTest(unittest.TestCase):
    """panel_wol.c is arithmetic and nothing else.

    The same split as panel_key.c, which holds the state machine of the key
    while panel_power.c holds the hardware. It is what lets check_wol run
    the real code on any machine instead of a copy of it.
    """

    def source(self):
        return without_comments(read("panel_wol.c"))

    def test_it_opens_no_socket_and_calls_no_driver(self):
        code = self.source()
        found = sorted(set(re.findall(r"\b(socket|sendto|setsockopt|esp_\w+|"
                                      r"lwip_\w+)\s*\(", code)))
        self.assertEqual(found, [],
                         "these belong with the network half, not here")

    def test_it_includes_nothing_of_the_board(self):
        for line in read("panel_wol.h").splitlines() + read("panel_wol.c").splitlines():
            if line.startswith("#include"):
                self.assertNotIn("esp_", line)
                self.assertNotIn("freertos", line)

    def test_the_packet_is_the_size_the_standard_says(self):
        """Six of 0xFF and the address sixteen times over."""
        header = read("panel_wol.h")
        self.assertIn("#define PANEL_WOL_MAC_BYTES 6", header)
        self.assertRegex(header,
                         r"#define PANEL_WOL_PACKET_BYTES \(6 \+ 16 \* "
                         r"PANEL_WOL_MAC_BYTES\)")

    def test_it_is_in_the_firmware_build(self):
        self.assertIn("panel_wol.c", read("CMakeLists.txt"))


class LearntNotTypedTest(unittest.TestCase):
    """Where the address comes from.

    Not the setup form. The panel needs it when the PC is off, which is the
    one moment it cannot ask, so it reads it while the PC is up.
    """

    def test_the_setup_form_does_not_ask_for_an_address(self):
        for page in ("setup.html", "setup-de.html"):
            text = read(page)
            self.assertNotIn("wol", text.lower(),
                             "%s asks for something it should learn" % page)

    def test_the_panel_keeps_one(self):
        self.assertIn("char wol_mac[18];", read("config.h"))

    def test_a_panel_with_no_address_still_counts_as_set_up(self):
        """Folded into the others, a missing key reads as a panel that was
        never configured, and the whole thing asks to be set up again."""
        code = without_comments(read("config.c"))
        stored = re.search(r'nvs_get_str\(handle, "wol_mac".*?\n', code)
        self.assertIsNotNone(stored, "the address is not read at all")
        self.assertNotRegex(stored.group(0), r"ok\s*\|=",
                            "a missing address must not fail the load")

    def test_it_is_written_only_when_it_changes(self):
        """This runs at every poll. Flash rewritten every three seconds is
        flash that wears out."""
        code = without_comments(read("main.c"))
        learn = re.search(r"static void learn_wake_address\(.*?\n\}", code, re.S)
        self.assertIsNotNone(learn)
        body = learn.group(0)
        compared = body.index("strcmp(config.wol_mac")
        saved = body.index("panel_config_save_wol")
        self.assertLess(compared, saved,
                        "it saves before it compares, so it saves every time")

    def test_an_address_it_cannot_read_is_not_stored(self):
        code = without_comments(read("main.c"))
        learn = re.search(r"static void learn_wake_address\(.*?\n\}", code, re.S)
        self.assertIn("panel_wol_parse", learn.group(0))


class TheActionTest(unittest.TestCase):
    """PANEL_WAKE, and the table it must not walk into."""

    def test_it_comes_after_the_ones_the_service_performs(self):
        """main.c holds a table of names indexed by the action, and the
        guard around it is a range. An action put in the middle makes every
        button below it send the name of another one."""
        header = read("ui.h")
        order = re.search(r"typedef enum \{(.*?)\} panel_action_t;",
                          header, re.S).group(1)
        names = re.findall(r"PANEL_[A-Z_]+", order)
        self.assertEqual(names[-1], "PANEL_WAKE")
        self.assertEqual(names[-2], "PANEL_SETUP")

    def test_the_names_table_still_stops_before_it(self):
        code = without_comments(read("main.c"))
        self.assertRegex(code, r"action\s*<\s*PANEL_SETUP",
                         "the guard that keeps the table in range")

    def test_the_panel_sends_it_and_not_the_service(self):
        """The whole point: there is no service to ask when the PC is off."""
        code = without_comments(read("main.c"))
        self.assertRegex(code, r"if\s*\(\s*action\s*==\s*PANEL_WAKE\s*\)")

    def test_waking_asks_nobody_first(self):
        """Standby, restart and switch off interrupt the work of a person.
        Waking a machine that is off interrupts nothing."""
        code = without_comments(read("ui.c"))
        self.assertRegex(code,
                         r"action\s*>=\s*PANEL_SUSPEND\s*&&\s*"
                         r"action\s*<=\s*PANEL_SETUP")

    def test_the_button_is_not_in_the_table_of_controls(self):
        """controls[] has six places and is indexed by the action."""
        code = without_comments(read("ui.c"))
        self.assertIn("static lv_obj_t *controls[6]", code)
        self.assertNotRegex(code, r"controls\[PANEL_WAKE\]")


class TheButtonTest(unittest.TestCase):
    """When it is there, and when it is not."""

    def source(self):
        return without_comments(read("ui.c"))

    def test_it_shows_only_when_the_pc_is_off_and_an_address_is_known(self):
        """A button that cannot work is worse than no button."""
        self.assertRegex(self.source(),
                         r"offer_wake\s*=\s*!\s*s->online\s*&&\s*s->can_wake")

    def test_the_three_that_mean_nothing_then_go_away(self):
        """Standby, restart and switch off, on a machine already off."""
        code = self.source()
        self.assertRegex(code,
                         r"for\s*\(\s*int i\s*=\s*PANEL_SUSPEND\s*;\s*"
                         r"i\s*<=\s*PANEL_POWEROFF\s*;")

    def test_a_panel_that_knows_no_address_keeps_them(self):
        """can_wake false leaves the card as it was."""
        code = self.source()
        self.assertIn("LV_OBJ_FLAG_HIDDEN", code)
        self.assertIn("wake_button", code)

    def test_the_word_is_in_both_languages(self):
        table = read("panel_text.h")
        for name in ("TXT_WAKE", "TXT_WAKE_WHAT", "TXT_WAKE_SENT",
                     "TXT_WAKE_FAILED"):
            self.assertIn(name, table)


class TheSendTest(unittest.TestCase):
    """The two addresses, and what is not claimed about the packet."""

    def source(self):
        return without_comments(read("main.c"))

    def test_it_goes_to_two_addresses(self):
        """The all-ones broadcast is what everybody writes and some access
        points drop. The broadcast of this subnet goes through where that
        one does not."""
        code = self.source()
        send = re.search(r"static bool wake_the_pc\(void\).*?\n\}", code, re.S)
        self.assertIsNotNone(send)
        body = send.group(0)
        self.assertIn("0xFFFFFFFF", body)
        self.assertIn("esp_netif_get_ip_info", body)
        self.assertRegex(body, r"info\.ip\.addr\s*\|\s*~\s*info\.netmask\.addr")

    def test_it_asks_for_broadcast_on_the_socket(self):
        """Without SO_BROADCAST the send is refused and nothing says why."""
        self.assertIn("SO_BROADCAST", self.source())

    def test_the_port_is_named_once(self):
        self.assertIn("#define PANEL_WOL_PORT 9", read("panel_wol.h"))
        self.assertIn("PANEL_WOL_PORT", self.source())

    def test_the_source_says_the_packet_is_not_signed(self):
        """Every other action the panel sends carries a signature. This one
        cannot, and a reader who finds that later reads it as a hole. It is
        Wake on LAN, and it is written down where it happens.
        """
        text = read("main.c")
        send = re.search(r"/\*.{0,1200}?magic packet.{0,1200}?\*/\s*"
                         r"static bool wake_the_pc", text, re.S)
        self.assertIsNotNone(send, "wake_the_pc has no note above it")
        self.assertIn("signs it", send.group(0))


class TheJobRunsItTest(unittest.TestCase):
    def test_the_preview_build_knows_the_check(self):
        build = read("CMakeLists.txt", PREVIEW)
        self.assertIn("add_executable(check_wol check_wol.c "
                      "../main/panel_wol.c)", build)


if __name__ == "__main__":
    unittest.main()
