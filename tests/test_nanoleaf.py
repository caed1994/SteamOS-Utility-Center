# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Nanoleaf devices on the network, and the record of the paired ones.

No device answers on a build machine, so the calls are checked against a
stand-in for nanoleaf.call and the record against a temporary home. The
parts that need hardware are the two that tools/nanoleaf-probe.py takes:
the rate of a stream and the physical path of the panels. Both said this
module plays the effects of the device rather than drawing its own.

The record holds a token for each device. That it is written for its owner
and nobody else is a test here, because a mode of 0644 is the sort of thing
that nobody notices.
"""

import ast
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))

from steamos_utility_center import nanoleaf                    # noqa: E402


DEVICE = {"name": "Lines A5F4", "model": "NL59", "ip": "192.168.178.93",
          "token": "6TxT461CoLus5wJcAHpiuAkc8b2t5x3"}

OTHER = {"name": "Shapes 1B2C", "model": "NL42", "ip": "192.168.178.41",
         "token": "another-token-entirely"}


class Talker:
    """Stands in for nanoleaf.call and writes down what it was asked."""

    def __init__(self, answers=None, raises=None):
        self.answers = answers or {}
        self.raises = raises
        self.asked = []

    def __call__(self, ip, path, method="GET", body=None, timeout=None):
        self.asked.append({"ip": ip, "path": path, "method": method,
                           "body": body})
        if self.raises is not None:
            raise self.raises
        return self.answers.get(path, {})


class Room(unittest.TestCase):
    """A home directory of its own for each test."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def _talk(self, **kwargs):
        talker = Talker(**kwargs)
        before = nanoleaf.call
        nanoleaf.call = talker
        self.addCleanup(setattr, nanoleaf, "call", before)
        return talker


class RecordTest(Room):
    """The file that says which devices are paired."""

    def test_it_lives_in_the_home_of_the_person_who_paired_them(self):
        """And never in /etc.

        A token needs no root, so a file in /etc would need one to write and
        would be readable by every program on the machine.
        """
        where = nanoleaf.path(self.home)
        self.assertTrue(where.startswith(self.home), where)
        self.assertIn(".config", where)
        self.assertNotIn("/etc", where)

    def test_no_file_is_the_normal_condition_of_a_new_machine(self):
        self.assertEqual(nanoleaf.read(self.home), [])

    def test_what_was_written_is_what_is_read(self):
        nanoleaf.write([DEVICE], self.home)
        self.assertEqual(nanoleaf.read(self.home), [DEVICE])

    def test_only_its_owner_can_read_the_token(self):
        where = nanoleaf.write([DEVICE], self.home)
        mode = stat.S_IMODE(os.stat(where).st_mode)
        self.assertEqual(mode, 0o600, oct(mode))

    def test_a_file_of_an_older_version_is_narrowed(self):
        where = nanoleaf.path(self.home)
        os.makedirs(os.path.dirname(where), exist_ok=True)
        with open(where, "w") as handle:
            handle.write("[]\n")
        os.chmod(where, 0o644)
        nanoleaf.write([DEVICE], self.home)
        self.assertEqual(stat.S_IMODE(os.stat(where).st_mode), 0o600)

    def test_a_file_that_cannot_be_read_gives_an_empty_list(self):
        """The window then offers to pair, which is the one thing to do.

        A broken file must never stop the panel from opening.
        """
        where = nanoleaf.path(self.home)
        os.makedirs(os.path.dirname(where), exist_ok=True)
        with open(where, "w") as handle:
            handle.write("this is not json")
        self.assertEqual(nanoleaf.read(self.home), [])

    def test_a_record_with_a_device_that_has_no_token_is_refused(self):
        for broken in ([{"ip": "10.0.0.1"}], [{"token": "x"}],
                       [{"ip": "", "token": "x"}], "not a list",
                       ["not an object"]):
            with self.assertRaises(nanoleaf.NanoleafError):
                nanoleaf.validate(broken)

    def test_two_devices_cannot_share_a_token(self):
        with self.assertRaises(nanoleaf.NanoleafError):
            nanoleaf.validate([DEVICE, dict(OTHER,
                                            token=DEVICE["token"])])

    def test_the_file_holds_the_four_fields_and_nothing_else(self):
        nanoleaf.write([dict(DEVICE, secret="do not keep this")], self.home)
        with open(nanoleaf.path(self.home)) as handle:
            found = json.load(handle)
        self.assertEqual(sorted(found[0]), sorted(nanoleaf.FIELDS))

    def test_adding_one_puts_it_in(self):
        nanoleaf.add(DEVICE, self.home)
        nanoleaf.add(OTHER, self.home)
        self.assertEqual([one["token"] for one in nanoleaf.read(self.home)],
                         [DEVICE["token"], OTHER["token"]])

    def test_adding_the_same_device_again_replaces_it(self):
        """The token says "this device".

        A name repeats on a network and an address moves with the lease, so
        neither of those two can say it.
        """
        nanoleaf.add(DEVICE, self.home)
        nanoleaf.add(dict(DEVICE, ip="192.168.178.99"), self.home)
        found = nanoleaf.read(self.home)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["ip"], "192.168.178.99")

    def test_removing_one_takes_it_out_and_leaves_the_rest(self):
        nanoleaf.add(DEVICE, self.home)
        nanoleaf.add(OTHER, self.home)
        nanoleaf.remove(DEVICE["token"], self.home)
        self.assertEqual([one["token"] for one in nanoleaf.read(self.home)],
                         [OTHER["token"]])

    def test_removing_one_calls_nothing(self):
        """The device is told by forget() and the record by this.

        A removal of a device that is away must work, and the two steps are
        therefore apart.
        """
        talker = self._talk()
        nanoleaf.add(DEVICE, self.home)
        nanoleaf.remove(DEVICE["token"], self.home)
        self.assertEqual(talker.asked, [])


class LookTest(Room):
    """The state of one device, and what it can do."""

    WHOLE = {
        "name": "Lines A5F4",
        "model": "NL59",
        "state": {"on": {"value": True}, "brightness": {"value": 60}},
        "effects": {"select": "Northern Lights",
                    "effectsList": ["Cotton Candy", "Northern Lights"]},
    }

    def _answers(self, said):
        return {"/api/v1/%s/" % DEVICE["token"]: said}

    def test_it_reports_the_effect_and_the_list_to_pick_from(self):
        self._talk(answers=self._answers(self.WHOLE))
        said = nanoleaf.look(DEVICE)
        self.assertTrue(said["ok"])
        self.assertEqual(said["effect"], "Northern Lights")
        self.assertEqual(said["effects"],
                         ("Cotton Candy", "Northern Lights"))
        self.assertEqual(said["on"], True)
        self.assertEqual(said["brightness"], 60)

    def test_a_mode_is_reported_as_no_effect(self):
        """*Solid*, *Dynamic* and *ExtControl* are modes of the device.

        The window draws a list of effects, and a mode in it is an entry
        that a person cannot select and that does nothing.
        """
        for mode in ("*Solid*", "*Dynamic*", "*ExtControl*"):
            self._talk(answers=self._answers(
                dict(self.WHOLE, effects={"select": mode,
                                          "effectsList": ["Prism"]})))
            self.assertEqual(nanoleaf.look(DEVICE)["effect"], "")

    def test_a_device_that_is_away_is_a_row_with_a_reason_on_it(self):
        """And never an error out of the window.

        One row for each device of the record, whether it answers or not.
        """
        self._talk(raises=nanoleaf.NanoleafError("did not answer"))
        said = nanoleaf.look(DEVICE)
        self.assertFalse(said["ok"])
        self.assertIn("did not answer", said["error"])
        self.assertEqual(said["name"], DEVICE["name"])
        self.assertEqual(said["ip"], DEVICE["ip"])

    def test_it_keeps_the_name_of_the_record_when_the_device_gives_none(self):
        self._talk(answers=self._answers({}))
        self.assertEqual(nanoleaf.look(DEVICE)["name"], DEVICE["name"])


class CommandTest(Room):
    """The four things a person does to a device."""

    def test_selecting_an_effect_names_it(self):
        talker = self._talk()
        nanoleaf.select(DEVICE, "Northern Lights")
        self.assertEqual(talker.asked[0]["method"], "PUT")
        self.assertEqual(talker.asked[0]["body"],
                         {"select": "Northern Lights"})
        self.assertIn(DEVICE["token"], talker.asked[0]["path"])

    def test_a_mode_cannot_be_selected(self):
        talker = self._talk()
        with self.assertRaises(nanoleaf.NanoleafError):
            nanoleaf.select(DEVICE, "*Solid*")
        self.assertEqual(talker.asked, [])

    def test_the_switch_sends_a_boolean(self):
        talker = self._talk()
        nanoleaf.switch(DEVICE, True)
        nanoleaf.switch(DEVICE, 0)
        self.assertEqual([one["body"] for one in talker.asked],
                         [{"on": {"value": True}}, {"on": {"value": False}}])

    def test_the_brightness_is_between_zero_and_a_hundred(self):
        """The device counts it that way, and a slider can be anything."""
        talker = self._talk()
        for asked, wanted in ((-5, 0), (0, 0), (60, 60), (100, 100),
                              (255, 100)):
            nanoleaf.dim(DEVICE, asked)
            self.assertEqual(talker.asked[-1]["body"],
                             {"brightness": {"value": wanted}})

    def test_forgetting_a_token_deletes_it(self):
        talker = self._talk()
        nanoleaf.forget(DEVICE["ip"], DEVICE["token"])
        self.assertEqual(talker.asked[0]["method"], "DELETE")
        self.assertTrue(talker.asked[0]["path"].endswith(DEVICE["token"]))


class PairTest(Room):
    """The handshake, which is a button on the device and a window of time."""

    def test_it_asks_until_one_device_answers(self):
        """A person holds the button on the device they want.

        So the window needs no list to pick from and no address typed.
        """
        answers = {"/api/v1/new": {}}
        talker = self._talk(answers=answers)
        clock = [0.0]

        def rest(gap):
            clock[0] += gap
            if clock[0] >= 3.0:
                answers["/api/v1/new"] = {"auth_token": "fresh"}

        ip, token = nanoleaf.pair(["10.0.0.1", "10.0.0.2"], seconds=10.0,
                                  now=lambda: clock[0], rest=rest)
        self.assertEqual(token, "fresh")
        self.assertEqual(ip, "10.0.0.1")
        self.assertGreater(len(talker.asked), 2)

    def test_a_window_that_closes_with_no_token_is_not_an_error(self):
        clock = [0.0]

        def rest(gap):
            clock[0] += gap

        self._talk(answers={"/api/v1/new": {}})
        ip, token = nanoleaf.pair(["10.0.0.1"], seconds=4.0,
                                  now=lambda: clock[0], rest=rest)
        self.assertIsNone(token)
        self.assertIsNone(ip)

    def test_a_device_that_refuses_is_a_device_without_the_button(self):
        self._talk(raises=nanoleaf.NanoleafError("403"))
        self.assertIsNone(nanoleaf.pair_once("10.0.0.1"))

    def test_the_window_is_the_thirty_seconds_nanoleaf_documents(self):
        self.assertEqual(nanoleaf.PAIR_SECONDS, 30.0)


class RefreshTest(Room):
    """A lease that moved, which is the ordinary way a device goes away."""

    def test_the_address_of_the_record_is_brought_up_to_date(self):
        found = nanoleaf.refresh(
            [DEVICE],
            finder=lambda _seconds: [{"name": DEVICE["name"], "model": "NL59",
                                      "ip": "192.168.178.150"}])
        self.assertEqual(found[0]["ip"], "192.168.178.150")
        self.assertEqual(found[0]["token"], DEVICE["token"])

    def test_a_silent_network_keeps_the_addresses_of_the_record(self):
        """A router that drops multicast must not empty the list."""
        found = nanoleaf.refresh([DEVICE, OTHER], finder=lambda _s: [])
        self.assertEqual([one["ip"] for one in found],
                         [DEVICE["ip"], OTHER["ip"]])

    def test_a_device_that_is_not_in_the_record_is_not_added(self):
        found = nanoleaf.refresh(
            [DEVICE], finder=lambda _s: [{"name": "Shapes 9Z9Z",
                                          "ip": "10.0.0.9"}])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["ip"], DEVICE["ip"])


class DiscoveryTest(unittest.TestCase):
    """The message that the service query sends and reads."""

    def test_it_asks_for_the_service_of_nanoleaf(self):
        self.assertEqual(nanoleaf.SERVICE, "_nanoleafapi._tcp.local")

    def test_the_api_is_on_the_port_nanoleaf_documents(self):
        self.assertEqual(nanoleaf.API_PORT, 16021)

    def test_a_name_is_its_labels_with_a_length_in_front_of_each(self):
        self.assertEqual(nanoleaf._name_bytes("a.bc.local"),
                         b"\x01a\x02bc\x05local\x00")

    def test_a_name_that_points_at_an_earlier_one_is_read(self):
        data = b"\x00" * 12 + b"\x05local\x00" + b"\x02nl\xc0\x0c" + b"\xff"
        name, end = nanoleaf._read_name(data, 19)
        self.assertEqual(name, "nl.local")
        self.assertEqual(data[end], 0xFF)

    def test_the_pairs_of_a_text_record_are_read(self):
        self.assertEqual(nanoleaf._texts(b"\x07md=NL59\x0esrcvers=12.4.1"),
                         {"md": "NL59", "srcvers": "12.4.1"})

    def test_a_device_with_no_address_is_not_reported(self):
        """A TXT record with no A record beside it names nothing to call."""
        self.assertEqual(nanoleaf.find(seconds=0.0), [])


class ControlTest(Room):
    """The area of the control command, which is what Game Mode talks to."""

    def setUp(self):
        super().setUp()
        from steamos_utility_center import ctl
        self.ctl = ctl

    def test_the_area_is_there_and_carries_no_list_of_keys(self):
        """A device is a thing to act on and not a set of settings."""
        self.assertIn("nanoleaf", self.ctl.AREAS)
        self.assertIsNone(self.ctl.AREA["nanoleaf"]["keys"])

    def test_reading_it_gives_one_row_for_each_paired_device(self):
        self._talk(answers={"/api/v1/%s/" % DEVICE["token"]: {
            "effects": {"select": "Prism", "effectsList": ["Prism"]}}})
        nanoleaf.add(DEVICE, self.home)
        said = self.ctl.nanoleaf_read(home=self.home)
        self.assertEqual(len(said["devices"]), 1)
        self.assertEqual(said["devices"][0]["effect"], "Prism")

    def test_the_effects_come_with_the_device_and_not_from_offers(self):
        """One call for each device and not two for the same answer."""
        self.assertIsInstance(self.ctl.nanoleaf_offers()["effects"], str)

    def test_one_device_needs_no_token_in_the_menu(self):
        """Which is the ordinary machine, and one key fewer in Game Mode."""
        talker = self._talk()
        nanoleaf.add(DEVICE, self.home)
        said = self.ctl.nanoleaf_write({"effect": "Prism"}, home=self.home)
        self.assertIn("Prism", said)
        self.assertEqual(talker.asked[0]["body"], {"select": "Prism"})

    def test_two_devices_need_the_token(self):
        self._talk()
        nanoleaf.add(DEVICE, self.home)
        nanoleaf.add(OTHER, self.home)
        with self.assertRaises(self.ctl.CtlError):
            self.ctl.nanoleaf_write({"effect": "Prism"}, home=self.home)
        said = self.ctl.nanoleaf_write(
            {"token": OTHER["token"], "effect": "Prism"}, home=self.home)
        self.assertIn(OTHER["name"], said)

    def test_the_switch_and_the_brightness_go_through_it_too(self):
        talker = self._talk()
        nanoleaf.add(DEVICE, self.home)
        self.ctl.nanoleaf_write({"on": True, "brightness": 40},
                                home=self.home)
        self.assertEqual([one["body"] for one in talker.asked],
                         [{"on": {"value": True}},
                          {"brightness": {"value": 40}}])

    def test_a_machine_with_no_device_says_where_to_pair_one(self):
        with self.assertRaises(self.ctl.CtlError) as caught:
            self.ctl.nanoleaf_write({"effect": "Prism"}, home=self.home)
        self.assertIn("panel", str(caught.exception))

    def test_a_device_that_refused_is_reported_and_not_raised_raw(self):
        """Game Mode shows the message, so it must read as a sentence."""
        self._talk(raises=nanoleaf.NanoleafError("192.168.1.9 did not "
                                                 "answer"))
        nanoleaf.add(DEVICE, self.home)
        with self.assertRaises(self.ctl.CtlError) as caught:
            self.ctl.nanoleaf_write({"effect": "Prism"}, home=self.home)
        self.assertIn("did not answer", str(caught.exception))

    def test_it_asks_for_no_action_at_all_and_is_told_so(self):
        self._talk()
        nanoleaf.add(DEVICE, self.home)
        with self.assertRaises(self.ctl.CtlError):
            self.ctl.nanoleaf_write({}, home=self.home)


class NoRightsTest(unittest.TestCase):
    """This module needs nothing of the machine, and that is the design.

    An effect on one of these devices is one HTTP call to an address on the
    LAN. So there is no unit, no applier and no line in the sudoers file,
    and this is part of the core rather than a module.
    """

    SOURCE = os.path.join(HERE, "..", "server", "steamos_utility_center",
                          "nanoleaf.py")

    def _tree(self):
        with open(self.SOURCE) as handle:
            return ast.parse(handle.read())

    def test_it_runs_no_program(self):
        """There is nothing here to run as root, so nothing runs at all.

        A search for the word would find "sudoers" in the note that says
        there is no line in it, so this reads the code and not the text.
        """
        names = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Import):
                names.update(one.name for one in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        for banned in ("subprocess", "os.system", "pty", "shlex"):
            self.assertNotIn(banned, names, banned)

    def test_it_writes_to_no_path_of_the_system(self):
        """The record is in a home directory and nowhere else.

        A token needs no root, so a file in /etc would need one to write
        and would be readable by every program on the machine.
        """
        for node in ast.walk(self._tree()):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str):
                continue
            for room in ("/etc", "/var", "/usr", "/run"):
                self.assertFalse(node.value.startswith(room),
                                 "%r starts at %s" % (node.value, room))

    def test_it_is_not_in_the_registry_of_modules(self):
        from steamos_utility_center import modules
        self.assertNotIn("nanoleaf", modules.ORDER)


if __name__ == "__main__":
    unittest.main()
