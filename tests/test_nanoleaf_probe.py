# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The probe that asks a Nanoleaf device on the network what it takes.

No device answers on a build machine, so the tests here are on the two parts
that a machine can check: the message that discovery sends and reads, and the
bytes of one frame. Those are the two parts that are wrong the first time.

The frame is checked against the example in the documentation of Nanoleaf,
byte for byte. The rate, the panel count and the physical path of the panels
are measurements on hardware, and the probe exists to take them.
"""

import importlib.util
import math
import os
import struct
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, "..", "tools", "nanoleaf-probe.py")


def _probe():
    """The probe as a module. Its name has a dash, so import cannot."""
    spec = importlib.util.spec_from_file_location("nanoleaf_probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _probe()


def _record(name_bytes, rtype, body):
    return (name_bytes + struct.pack("!HHIH", rtype, 1, 120, len(body))
            + body)


def _answer(instance="Shapes-A1B2", host="nl-a1b2.local", ip="192.168.1.41",
            port=probe.API_PORT, texts=(("md", "NL42"), ("srcvers", "7.1.1"),
                                        ("id", "aa:bb:cc:dd:ee:ff"))):
    """One mDNS answer of the shape a Nanoleaf device sends."""
    full = probe._name_bytes("%s.%s" % (instance, probe.SERVICE))
    text = b"".join(bytes([len("%s=%s" % pair)]) + ("%s=%s" % pair).encode()
                    for pair in texts)
    service = probe._name_bytes(probe.SERVICE)
    body = struct.pack("!HHH", 0, 0, port) + probe._name_bytes(host)
    return (struct.pack("!HHHHHH", 0, 0x8400, 0, 4, 0, 0)
            + _record(service, probe.PTR, full)
            + _record(full, probe.TXT, text)
            + _record(full, probe.SRV, body)
            + _record(probe._name_bytes(host), probe.A,
                      bytes(int(one) for one in ip.split("."))))


class FrameTest(unittest.TestCase):
    """The bytes of one streaming frame, version 2.

    nPanels is two bytes, then for each panel the id in two, red, green,
    blue and white in one each, and the transition in two. Version 1 has one
    byte for the three wide fields and a frame count as well, and only the
    oldest Light Panels speak it.
    """

    def test_it_matches_the_example_in_the_documentation(self):
        # 0x0176 is 374, the colour is magenta, and 0x000c is a transition of
        # twelve units of 100ms.
        got = probe.frame([{"panelId": 0x0176}], [(255, 0, 255)],
                          transition=12)
        self.assertEqual(got, bytes.fromhex("0001017 6ff00ff00000c"
                                            .replace(" ", "")))

    def test_it_is_two_bytes_and_then_eight_for_each_panel(self):
        order = [{"panelId": index} for index in range(12)]
        got = probe.frame(order, [(1, 2, 3)] * 12)
        self.assertEqual(len(got), 2 + 8 * 12)
        self.assertEqual(struct.unpack_from("!H", got, 0)[0], 12)

    def test_the_white_channel_is_always_zero(self):
        """These devices are RGB. The field is in the protocol and not on
        the device, and a value there lights nothing."""
        got = probe.frame([{"panelId": 7}], [(10, 20, 30)])
        self.assertEqual(got[2:], struct.pack("!HBBBBH", 7, 10, 20, 30, 0,
                                              probe.TRANSITION))

    def test_the_transition_joins_one_frame_to_the_next(self):
        # One unit is 100ms, which is the gap of a stream at ten a second.
        self.assertEqual(probe.TRANSITION, 1)


class DiscoveryTest(unittest.TestCase):
    """The message that the service query sends and reads."""

    def test_the_question_names_the_service_of_nanoleaf(self):
        self.assertEqual(probe.SERVICE, "_nanoleafapi._tcp.local")
        self.assertIn(b"_nanoleafapi", probe._name_bytes(probe.SERVICE))

    def test_a_name_is_its_labels_with_a_length_in_front_of_each(self):
        self.assertEqual(probe._name_bytes("a.bc.local"),
                         b"\x01a\x02bc\x05local\x00")

    def test_a_name_that_points_at_an_earlier_one_is_read(self):
        """A label can be a pointer, and the end to report is this name's.

        A reader that returned the end of the name it points at would read
        the next record from the middle of an earlier one.
        """
        data = b"\x00" * 12 + b"\x05local\x00" + b"\x02nl\xc0\x0c" + b"\xff"
        name, end = probe._read_name(data, 19)
        self.assertEqual(name, "nl.local")
        self.assertEqual(end, len(data) - 1)
        self.assertEqual(data[end], 0xFF)

    def test_the_pairs_of_a_text_record_are_read(self):
        text = b"\x07md=NL42\x0dsrcvers=7.1.1"
        self.assertEqual(probe._texts(text),
                         {"md": "NL42", "srcvers": "7.1.1"})

    def test_every_record_of_an_answer_is_found(self):
        kinds = [rtype for _name, rtype, _body, _whole, _at
                 in probe._records(_answer())]
        self.assertEqual(sorted(kinds),
                         sorted([probe.PTR, probe.TXT, probe.SRV, probe.A]))

    def test_a_question_in_the_message_is_stepped_over(self):
        """A responder can echo the question, and the records come after it."""
        with_question = (struct.pack("!HHHHHH", 0, 0x8400, 1, 1, 0, 0)
                         + probe._name_bytes(probe.SERVICE)
                         + struct.pack("!HH", probe.PTR, 1)
                         + _record(probe._name_bytes("nl.local"), probe.A,
                                   b"\x01\x02\x03\x04"))
        found = probe._records(with_question)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], probe.A)

    def test_the_address_the_service_record_points_at_is_read(self):
        """The name, the port and the address arrive in three records.

        A device that gave its address in a record of its own and its name in
        another is the ordinary case, so the reader joins them.
        """
        host = None
        port = None
        for name, rtype, body, whole, at in probe._records(_answer()):
            if rtype == probe.SRV:
                host, _end = probe._read_name(whole, at + 6)
                port = struct.unpack_from("!H", body, 4)[0]
        self.assertEqual(host, "nl-a1b2.local")
        self.assertEqual(port, probe.API_PORT)

    def test_the_api_is_on_the_port_nanoleaf_documents(self):
        self.assertEqual(probe.API_PORT, 16021)
        self.assertEqual(probe.STREAM_PORT, 60222)


class OrderTest(unittest.TestCase):
    """Which order the panels of a surface take for a line of effects."""

    @staticmethod
    def _ring(count, radius=100):
        """Panels on a circle, given out of order."""
        rows = []
        for index in range(count):
            turn = 2.0 * math.pi * index / count
            rows.append({"panelId": 100 + index,
                         "x": int(round(radius * math.cos(turn))),
                         "y": int(round(radius * math.sin(turn))),
                         "o": 0})
        return {"panelLayout": {"layout": {"positionData":
                                           rows[3:] + rows[:3]}}}

    def test_the_panels_come_out_as_a_path_around_the_shape(self):
        """Each one next to the one before it, all the way round.

        Where the path starts is not a property to hold: a ring has no
        first panel, and COLOR_SHIFT moves an effect along it anyway. That
        each step is one place along the ring is the property.
        """
        order = probe.panels(self._ring(8))
        self.assertEqual(len(order), 8)
        ids = [one["panelId"] - 100 for one in order]
        steps = set((after - before) % 8
                    for before, after in zip(ids, ids[1:]))
        self.assertEqual(steps, {1}, ids)

    def test_a_device_that_reports_nothing_is_not_an_error(self):
        self.assertEqual(probe.panels({}), [])
        self.assertEqual(probe.panels(
            {"panelLayout": {"layout": {"positionData": []}}}), [])

    def test_an_entry_with_no_position_is_left_out(self):
        """A frame needs an id and the order needs an x and a y."""
        said = {"panelLayout": {"layout": {"positionData": [
            {"panelId": 1, "x": 0, "y": 0}, {"panelId": 2}]}}}
        self.assertEqual([one["panelId"] for one in probe.panels(said)], [1])

    def test_the_controller_is_not_dropped_on_a_guess(self):
        """Some models report it in this list and it carries no light.

        A probe that dropped an id would hide the one thing the walk is here
        to find. The walk names each id as it lights it, so an id with no
        light reports itself.
        """
        said = {"panelLayout": {"layout": {"positionData": [
            {"panelId": 0, "x": 10, "y": 0},
            {"panelId": 5, "x": -10, "y": 0}]}}}
        self.assertEqual(len(probe.panels(said)), 2)


class ShapeTest(unittest.TestCase):
    """Properties of the file that are easy to break from a distance."""

    def test_it_is_a_program_that_a_person_can_run(self):
        self.assertTrue(os.access(PROBE, os.X_OK))

    def test_it_writes_nothing_to_the_machine(self):
        """The step before the module, so it installs nothing.

        The comments are cut out first: they say what it does not do, and a
        test that read them would refuse the explanation.
        """
        with open(PROBE) as handle:
            code = "\\n".join(line for line in handle.read().splitlines()
                              if not line.lstrip().startswith("#"))
        for named in ("/etc/", "systemctl", "sudo", "install -m"):
            self.assertNotIn(named, code, named)

    def test_it_gives_the_device_its_effect_back(self):
        """Streaming replaces what the device draws, so the probe restores it.

        Without this a person is left with a dark device and no way to see
        why, because the streaming mode ends by itself after a minute.
        """
        with open(PROBE) as handle:
            text = handle.read()
        for command in ("do_walk", "do_stream"):
            body = text.split("def %s(" % command)[1].split("\\ndef ")[0]
            self.assertIn("restore(", body, command)
            self.assertIn("finally:", body, command)


if __name__ == "__main__":
    unittest.main()
