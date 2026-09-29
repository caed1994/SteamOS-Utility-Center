# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The service that answers the Smart 86 Box panel.

The tests of the sensors build a /sys/class/hwmon in a directory. That is
the only way to check the choice between two graphics chips on a machine
that has one.

The structural test at the end is the one that matters over time. This
module came from a separate project with a hwmon reader of its own, and the
merge is what makes the LED bar and the panel report the same degrees. A
second reader here would pass every test above it.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import companion, temperature      # noqa: E402

TOKEN = "x" * 32


def machine(self, chips):
    """A /sys/class/hwmon with those chips in it.

    Each chip is a name and its files, and a file with a slash in it makes
    the directory under it. amdgpu keeps its memory size one level down.
    """
    root = tempfile.mkdtemp()
    self.addCleanup(__import__("shutil").rmtree, root, ignore_errors=True)
    for index, (name, files) in enumerate(chips):
        place = os.path.join(root, "hwmon%d" % index)
        os.makedirs(place, exist_ok=True)
        with open(os.path.join(place, "name"), "w") as handle:
            handle.write(name + "\n")
        for leaf, value in files.items():
            path = os.path.join(place, leaf)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(str(value) + "\n")
    return root


class ControllerTest(unittest.TestCase):
    def machine(self, entries):
        root = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, root, ignore_errors=True)
        for name, files in entries:
            place = os.path.join(root, name)
            os.makedirs(place)
            for leaf, value in files.items():
                with open(os.path.join(place, leaf), "w") as handle:
                    handle.write(str(value) + "\n")
        return root

    def test_a_controller_battery_is_reported_and_a_laptop_one_is_not(self):
        root = self.machine([
            ("ps-controller-battery-01", {"type": "Battery",
                                          "capacity": "78",
                                          "status": "Discharging"}),
            ("BAT0", {"type": "Battery", "capacity": "50"}),
        ])
        self.assertEqual(companion.controllers(root),
                         [{"name": "PlayStation Controller", "percent": 78,
                           "status": "Discharging"}])

    def test_a_capacity_that_is_not_a_number_drops_the_entry(self):
        """The firmware invents no battery, so neither does this."""
        root = self.machine([("ps-controller-battery-01",
                              {"type": "Battery", "capacity": "invalid"})])
        self.assertEqual(companion.controllers(root), [])

    def test_a_controller_that_is_not_present_is_left_out(self):
        root = self.machine([("steam-controller-battery",
                              {"type": "Battery", "capacity": "40",
                               "present": "0"})])
        self.assertEqual(companion.controllers(root), [])

    def test_a_missing_directory_is_no_controllers_and_no_error(self):
        self.assertEqual(companion.controllers("/does/not/exist"), [])


class TelemetryTest(unittest.TestCase):
    machine = machine

    def test_the_units_and_the_card_with_the_most_memory(self):
        """A Ryzen with a graphics part and a card gives two amdgpu chips."""
        root = self.machine([
            ("k10temp", {"temp1_input": 49500}),
            ("amdgpu", {"temp1_input": 35000, "power1_average": 5000000,
                        "device/mem_info_vram_total": 512}),
            ("amdgpu", {"temp1_input": 56000, "power1_average": 78000000,
                        "device/mem_info_vram_total": 16384}),
        ])
        self.assertEqual(companion.telemetry(root),
                         {"cpu_c": 50, "gpu_c": 56, "gpu_w": 78})

    def test_power1_input_answers_where_there_is_no_average(self):
        root = self.machine([
            ("amdgpu", {"temp1_input": 40000, "power1_input": 30000000,
                        "device/mem_info_vram_total": 16384}),
        ])
        self.assertEqual(companion.telemetry(root)["gpu_w"], 30)

    def test_a_machine_with_no_sensors_reports_a_dash_for_each(self):
        self.assertEqual(companion.telemetry("/does/not/exist"),
                         {"cpu_c": None, "gpu_c": None, "gpu_w": None})

    def test_a_reading_outside_the_possible_is_no_reading(self):
        root = self.machine([("k10temp", {"temp1_input": 4000000})])
        self.assertIsNone(companion.telemetry(root)["cpu_c"])

    def test_zenpower_answers_where_the_kernel_has_no_k10temp(self):
        """It replaces k10temp on a Ryzen, and this machine then has one CPU
        chip under another name. Without it the answer was acpitz."""
        root = self.machine([
            ("acpitz", {"temp1_input": 27000}),
            ("zenpower", {"temp1_input": 61000}),
        ])
        self.assertEqual(companion.telemetry(root)["cpu_c"], 61)

    def test_the_label_inside_a_chip_decides_which_sensor(self):
        """k10temp publishes Tctl and Tdie. temperature.py ranks them, and
        this test fails if the ranking stops being asked."""
        root = self.machine([("k10temp", {"temp1_input": 90000,
                                          "temp1_label": "Tccd1",
                                          "temp2_input": 55000,
                                          "temp2_label": "Tctl"})])
        self.assertEqual(companion.telemetry(root)["cpu_c"], 55)


class ServiceTest(unittest.TestCase):
    """The service, asked the way the panel asks."""

    def serve(self):
        self.nonces = companion.Nonces()
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), companion.make_handler(TOKEN, self.nonces))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.conn = HTTPConnection("127.0.0.1", httpd.server_port)
        self.addCleanup(self.conn.close)
        return self.conn

    def ask(self, method, path, body=b"", nonce=None, auth=None,
            headers=None):
        """One signed request. Each part is a parameter, so a test can put
        one of them wrong and leave the others right."""
        nonce = self.nonces.issue() if nonce is None else nonce
        sent = {companion.NONCE_HEADER: nonce,
                companion.AUTH_HEADER: auth if auth is not None
                else companion.signature(TOKEN, method, path, nonce, body)}
        sent.update(headers or {})
        self.conn.request(method, path, body, sent)
        answer = self.conn.getresponse()
        answer.read()
        return answer

    def action(self, name, **kw):
        return self.ask("POST", "/v1/action",
                        json.dumps({"action": name}).encode(), **kw)

    def test_a_signed_read_is_answered(self):
        self.serve()
        self.assertEqual(self.ask("GET", "/v1/status").status, 200)

    def test_nothing_at_all_reaches_nothing(self):
        conn = self.serve()
        conn.request("GET", "/v1/status")
        answer = conn.getresponse()
        answer.read()
        self.assertEqual(answer.status, 401)

    def test_the_bare_token_in_a_header_reaches_nothing(self):
        """The scheme this replaced. A panel with old firmware is refused,
        rather than quietly keeping the weaker of the two."""
        conn = self.serve()
        conn.request("GET", "/v1/status", headers={"X-Panel-Token": TOKEN})
        answer = conn.getresponse()
        answer.read()
        self.assertEqual(answer.status, 401)

    def test_the_same_request_a_second_time_is_refused(self):
        """The point of the whole scheme. Somebody who reads one request off
        the network holds a suspend for as long as the token lasts."""
        self.serve()
        nonce = self.nonces.issue()
        auth = companion.signature(TOKEN, "GET", "/v1/status", nonce, b"")
        self.assertEqual(self.ask("GET", "/v1/status", nonce=nonce,
                                  auth=auth).status, 200)
        self.assertEqual(self.ask("GET", "/v1/status", nonce=nonce,
                                  auth=auth).status, 401)

    def test_a_signature_for_one_path_does_not_fit_another(self):
        self.serve()
        nonce = self.nonces.issue()
        auth = companion.signature(TOKEN, "GET", "/v1/status", nonce, b"")
        self.assertEqual(self.ask("GET", "/v1/other", nonce=nonce,
                                  auth=auth).status, 401)

    def test_a_captured_press_cannot_be_re_addressed(self):
        """mute and poweroff go to the same path with the same method. The
        body is under the signature, which is what tells them apart."""
        self.serve()
        nonce = self.nonces.issue()
        mute = json.dumps({"action": "mute"}).encode()
        auth = companion.signature(TOKEN, "POST", "/v1/action", nonce, mute)
        with mock.patch.object(companion.subprocess, "run") as ran:
            self.assertEqual(
                self.ask("POST", "/v1/action",
                         json.dumps({"action": "poweroff"}).encode(),
                         nonce=nonce, auth=auth).status, 401)
            ran.assert_not_called()

    def test_a_wrong_signature_leaves_the_nonce_alone(self):
        """Or a stranger burns the nonce of the panel by guessing at it."""
        self.serve()
        nonce = self.nonces.issue()
        self.assertEqual(self.ask("GET", "/v1/status", nonce=nonce,
                                  auth="0" * 64).status, 401)
        self.assertEqual(self.ask("GET", "/v1/status", nonce=nonce).status,
                         200)

    def test_every_answer_carries_the_next_nonce(self):
        """Including the 401, which is how a panel that lost its nonce comes
        back with no help from anybody."""
        conn = self.serve()
        conn.request("GET", "/v1/status")
        answer = conn.getresponse()
        answer.read()
        offered = answer.getheader(companion.NONCE_HEADER)
        self.assertTrue(offered)
        auth = companion.signature(TOKEN, "GET", "/v1/status", offered, b"")
        self.assertEqual(self.ask("GET", "/v1/status", nonce=offered,
                                  auth=auth).status, 200)

    def test_an_unknown_path_answers_the_same_to_a_stranger(self):
        conn = self.serve()
        for path in ("/v1/status", "/v1/nothing", "/"):
            conn.request("GET", path)
            answer = conn.getresponse()
            answer.read()
            self.assertEqual(answer.status, 401, path)

    def test_an_action_that_is_not_in_the_table_runs_nothing(self):
        self.serve()
        with mock.patch.object(companion.subprocess, "run") as ran:
            self.assertEqual(self.action("shell").status, 400)
            ran.assert_not_called()

    def test_a_known_action_runs_and_answers(self):
        self.serve()
        with mock.patch.object(companion.subprocess, "run") as ran:
            self.assertEqual(self.action("mute").status, 200)
            ran.assert_called_once()
            self.assertEqual(ran.call_args[0][0], companion.ACTIONS["mute"])

    def test_a_refused_command_comes_back_as_a_refusal(self):
        self.serve()
        with mock.patch.object(companion.subprocess, "run") as ran:
            ran.side_effect = companion.subprocess.CalledProcessError(
                1, ["systemctl"])
            self.assertEqual(self.action("suspend").status, 502)

    def test_a_body_that_is_too_long_is_not_read(self):
        conn = self.serve()
        conn.request("POST", "/v1/action", b"x" * (companion.BODY_LIMIT + 1))
        answer = conn.getresponse()
        answer.read()
        self.assertEqual(answer.status, 400)

    def test_every_action_is_a_tuple_and_never_a_string(self):
        """A string goes to a shell. Each of these goes to execve."""
        for name, command in companion.ACTIONS.items():
            self.assertIsInstance(command, tuple, name)
            self.assertTrue(all(isinstance(one, str) for one in command), name)


def _net(self, cards, routes=()):
    """A /sys/class/net holding the cards given, and a /proc/net/route.

    Each card is (name, kind, mac, carrier). kind is "wired", "wireless" or
    "virtual", and it decides which files are there rather than being read
    anywhere: that is the whole point of the reader.
    """
    root = tempfile.mkdtemp()
    self.addCleanup(shutil.rmtree, root, ignore_errors=True)
    for name, kind, mac, carrier in cards:
        where = os.path.join(root, name)
        os.makedirs(where)
        with open(os.path.join(where, "address"), "w") as handle:
            handle.write(mac + "\n")
        with open(os.path.join(where, "carrier"), "w") as handle:
            handle.write("%d\n" % carrier)
        with open(os.path.join(where, "type"), "w") as handle:
            handle.write("772\n" if name == "lo" else "1\n")
        if kind != "virtual":
            os.makedirs(os.path.join(where, "device"))
        if kind == "wireless":
            os.makedirs(os.path.join(where, "wireless"))
    table = os.path.join(root, "route")
    with open(table, "w") as handle:
        handle.write("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\t"
                     "Metric\tMask\n")
        for name, metric in routes:
            handle.write("%s\t00000000\t0102000A\t0003\t0\t0\t%d\t"
                         "00000000\n" % (name, metric))
    return root, table


class WakeTargetTest(unittest.TestCase):
    """The card a magic packet has to name.

    Wake on LAN is a thing wired cards do. Everything here is about not
    naming the wrong one, because a packet sent to a radio that sleeps wakes
    nothing and leaves no trace of why.
    """

    def test_it_finds_the_one_wired_card(self):
        root, table = _net(self, [("eth0", "wired", "a4:bb:6d:1f:0e:27", 1)])
        self.assertEqual(companion.wake_target(root, table),
                         {"interface": "eth0", "mac": "a4:bb:6d:1f:0e:27"})

    def test_a_radio_is_not_a_wake_target(self):
        root, table = _net(self, [("wlan0", "wireless", "aa:bb:cc:dd:ee:ff", 1)])
        self.assertIsNone(companion.wake_target(root, table))

    def test_a_virtual_card_is_not_one_either(self):
        """A bridge, a veth or a tunnel has no hardware behind it."""
        root, table = _net(self, [("docker0", "virtual", "02:42:aa:bb:cc:dd", 1),
                                  ("lo", "virtual", "00:00:00:00:00:00", 1)])
        self.assertIsNone(companion.wake_target(root, table))

    def test_the_radio_carrying_the_route_does_not_win(self):
        """The case this exists for.

        A machine with a cable and a radio routes over whichever it prefers,
        and that is often the radio. Reading the default route on its own
        gives the wrong card, and the packet goes nowhere.
        """
        root, table = _net(self,
                           [("eth0", "wired", "a4:bb:6d:1f:0e:27", 1),
                            ("wlan0", "wireless", "aa:bb:cc:dd:ee:ff", 1)],
                           routes=[("wlan0", 600)])
        found = companion.wake_target(root, table)
        self.assertEqual(found["interface"], "eth0")

    def test_of_two_wired_cards_the_routing_one_wins(self):
        root, table = _net(self,
                           [("eth0", "wired", "a4:bb:6d:1f:0e:27", 1),
                            ("eth1", "wired", "b8:27:eb:00:11:22", 1)],
                           routes=[("eth1", 100)])
        self.assertEqual(companion.wake_target(root, table)["interface"], "eth1")

    def test_a_cable_beats_an_empty_socket_when_neither_routes(self):
        root, table = _net(self,
                           [("eth0", "wired", "a4:bb:6d:1f:0e:27", 0),
                            ("eth1", "wired", "b8:27:eb:00:11:22", 1)])
        self.assertEqual(companion.wake_target(root, table)["interface"], "eth1")

    def test_the_lowest_metric_is_the_default_route(self):
        root, table = _net(self,
                           [("eth0", "wired", "a4:bb:6d:1f:0e:27", 1),
                            ("eth1", "wired", "b8:27:eb:00:11:22", 1)],
                           routes=[("eth0", 900), ("eth1", 50)])
        self.assertEqual(companion.wake_target(root, table)["interface"], "eth1")

    def test_an_address_of_nothing_is_no_answer(self):
        """What a card reports before it is ready. A packet naming it wakes
        nothing, and an empty field on the panel is the honest answer."""
        root, table = _net(self, [("eth0", "wired", "00:00:00:00:00:00", 1)])
        self.assertIsNone(companion.wake_target(root, table))

    def test_a_scrambled_address_is_no_answer(self):
        root, table = _net(self, [("eth0", "wired", "not an address", 1)])
        self.assertIsNone(companion.wake_target(root, table))

    def test_a_machine_with_no_cards_answers_nothing(self):
        root, table = _net(self, [])
        self.assertIsNone(companion.wake_target(root, table))

    def test_a_missing_directory_is_not_an_error(self):
        """This fills a field on a screen. It does not stop the service."""
        self.assertIsNone(companion.wake_target("/no/such/place",
                                                "/no/such/route"))

    def test_the_status_carries_it(self):
        """The panel learns the address from an ordinary status answer, so
        it has one when the PC is off and cannot be asked."""
        self.assertIn("wake", companion.status())


class NonceTest(unittest.TestCase):
    def test_one_spend_for_each(self):
        room = companion.Nonces()
        value = room.issue()
        self.assertTrue(room.spend(value))
        self.assertFalse(room.spend(value))

    def test_one_that_nobody_gave_out_is_refused(self):
        self.assertFalse(companion.Nonces().spend("made up"))

    def test_the_room_is_bounded_and_the_oldest_leaves(self):
        """A stranger asks for as many as they like, and memory is not a
        thing to hand to a stranger."""
        room = companion.Nonces(room=4)
        first = room.issue()
        for _ in range(4):
            room.issue()
        self.assertFalse(room.spend(first))
        self.assertLessEqual(len(room._open), 4)

    def test_two_are_never_the_same(self):
        room = companion.Nonces(room=500)
        values = {room.issue() for _ in range(400)}
        self.assertEqual(len(values), 400)


class TokenTest(unittest.TestCase):
    def test_a_missing_file_gives_a_sentence_and_not_a_traceback(self):
        with self.assertRaises(SystemExit) as caught:
            companion.read_token("/does/not/exist")
        self.assertIn("companion module", str(caught.exception))

    def test_a_short_token_is_refused(self):
        with tempfile.NamedTemporaryFile("w", suffix=".token",
                                         delete=False) as handle:
            handle.write("short\n")
        self.addCleanup(os.unlink, handle.name)
        with self.assertRaises(SystemExit):
            companion.read_token(handle.name)

    def test_the_token_lives_in_the_home_directory(self):
        """Not in /etc. It belongs to one person and one panel, it needs no
        root to read, and a SteamOS update leaves a home directory alone."""
        self.assertTrue(companion.token_path("/home/deck").startswith(
            "/home/deck/.config/"))


class FirmwareImageTest(unittest.TestCase):
    """The image in the repository, against the firmware beside it.

    Build output in a repository is a thing to be careful with, and this is
    the care: CI writes the fingerprint of the source it built from, and the
    page refuses an image whose fingerprint does not match. Without the
    check, an update that changed the firmware and a flash from the old
    image give a board that talks to a service it does not match, and a wall
    that says "no PC" with nothing to explain it.
    """

    def tree(self):
        """A machine with a firmware source in it, and nothing else."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        where = os.path.join(root, companion.FIRMWARE_DIR)
        os.makedirs(os.path.join(where, "main"))
        for name in ("CMakeLists.txt", "partitions.csv",
                     "sdkconfig.defaults", "dependencies.lock"):
            with open(os.path.join(where, name), "w") as handle:
                handle.write(name + "\n")
        with open(os.path.join(where, "main", "main.c"), "w") as handle:
            handle.write("int main(void){return 0;}\n")
        return root

    def image(self, root, where, stamp=None):
        place = os.path.join(root, where)
        for part in companion.IMAGE_PARTS:
            path = os.path.join(place, part)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"\x00")
        if stamp is not None:
            with open(os.path.join(place, companion.STAMP_NAME), "w") as h:
                h.write(stamp + "\n")
        return place

    def test_the_same_source_gives_the_same_fingerprint(self):
        root = self.tree()
        self.assertEqual(companion.firmware_fingerprint(root),
                         companion.firmware_fingerprint(root))

    def test_a_changed_source_file_changes_it(self):
        root = self.tree()
        before = companion.firmware_fingerprint(root)
        path = os.path.join(root, companion.FIRMWARE_DIR, "main", "main.c")
        with open(path, "a") as handle:
            handle.write("// one more line\n")
        self.assertNotEqual(companion.firmware_fingerprint(root), before)

    def test_a_file_that_moves_changes_it(self):
        """The path is in the hash beside the bytes. Without it, a rename
        gives the same answer as no change at all."""
        root = self.tree()
        before = companion.firmware_fingerprint(root)
        main = os.path.join(root, companion.FIRMWARE_DIR, "main")
        os.rename(os.path.join(main, "main.c"),
                  os.path.join(main, "start.c"))
        self.assertNotEqual(companion.firmware_fingerprint(root), before)

    def test_a_note_beside_the_firmware_does_not_change_it(self):
        """A licence or a README is not a reason to build again."""
        root = self.tree()
        before = companion.firmware_fingerprint(root)
        with open(os.path.join(root, companion.FIRMWARE_DIR, "NOTES.md"),
                  "w") as handle:
            handle.write("# notes\n")
        self.assertEqual(companion.firmware_fingerprint(root), before)

    def test_an_image_is_all_three_parts_or_none(self):
        root = self.tree()
        place = self.image(root, companion.PREBUILT_DIR)
        self.assertTrue(companion.image_is_complete(place))
        os.unlink(os.path.join(place, "steamos_companion.bin"))
        self.assertFalse(companion.image_is_complete(place),
                         "a build that stopped is not an image")

    def test_a_missing_stamp_reads_as_no_stamp(self):
        root = self.tree()
        place = self.image(root, companion.PREBUILT_DIR)
        self.assertEqual(companion.image_stamp(place), "")
        self.assertEqual(companion.image_stamp("/does/not/exist"), "")

    def test_the_stamp_the_job_writes_is_the_one_the_page_reads(self):
        """The whole chain, with the fingerprint in the middle."""
        root = self.tree()
        place = self.image(root, companion.PREBUILT_DIR,
                           stamp=companion.firmware_fingerprint(root))
        self.assertEqual(companion.image_stamp(place),
                         companion.firmware_fingerprint(root))


class WorkflowTest(unittest.TestCase):
    """The job that builds the image, read rather than run.

    Nothing here can run GitHub Actions, so this holds the two facts that a
    reader of the file cannot check for themselves: it builds at the version
    the lock names, and it writes the stamp with the same function the page
    reads.
    """

    def source(self):
        with open(os.path.join(
                REPO, ".github", "workflows",
                "companion-firmware.yml")) as handle:
            return handle.read()

    def locked_version(self):
        with open(os.path.join(REPO, companion.FIRMWARE_DIR,
                               "dependencies.lock")) as handle:
            lines = handle.read().splitlines()
        for index, line in enumerate(lines):
            if line.strip() == "idf:":
                for after in lines[index:index + 5]:
                    if after.strip().startswith("version:"):
                        return after.split(":", 1)[1].strip()
        raise AssertionError("dependencies.lock names no idf version")

    def test_it_builds_at_the_version_the_lock_names(self):
        """A container of another version is a build nobody measured."""
        self.assertIn("espressif/idf:v%s" % self.locked_version(),
                      self.source())

    def test_it_writes_the_stamp_with_the_function_the_page_reads(self):
        text = self.source()
        self.assertIn("firmware_fingerprint", text)
        self.assertIn(companion.STAMP_NAME, text)

    def test_it_does_not_start_itself_again(self):
        """It commits under firmware/companion, which is what starts it."""
        self.assertIn("'!firmware/companion/prebuilt/**'", self.source())


class OneSensorReaderTest(unittest.TestCase):
    """This module reads no hwmon file of its own.

    It came from a separate project that walked /sys/class/hwmon itself.
    Two readers become two answers on the day one of them learns about a new
    chip, and the LED bar and the panel then disagree about the temperature
    of the same machine. So the reads go through temperature.py, and this
    test refuses a second reader.
    """

    def tree(self):
        path = os.path.join(REPO, "server", "steamos_utility_center",
                            "companion.py")
        with open(path) as handle:
            return ast.parse(handle.read())

    def written(self, tree):
        """Every string in the code, and none of the ones in the prose.

        The first version of this read the docstrings too, and the paragraph
        that explains why the reads belong to temperature.py failed the test
        that asks for it. A rule about code that a comment can break is not
        a rule about code.
        """
        prose = set()
        holders = (ast.Module, ast.ClassDef, ast.FunctionDef,
                   ast.AsyncFunctionDef)
        for node in ast.walk(tree):
            if not isinstance(node, holders) or not node.body:
                continue
            first = node.body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                prose.add(id(first.value))
        return [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str) and id(node) not in prose]

    def test_it_names_no_hwmon_path_of_its_own(self):
        said = [one for one in self.written(self.tree()) if "hwmon" in one]
        self.assertEqual(said, [], "the hwmon path belongs to temperature.py")

    def test_that_rule_reads_the_code_and_not_the_prose(self):
        """Or the test above passes by deleting a paragraph."""
        tree = ast.parse('"""A hwmon docstring."""\nX = "/sys/class/hwmon"\n')
        self.assertEqual(self.written(tree), ["/sys/class/hwmon"])

    def test_it_does_not_divide_a_reading_by_a_thousand(self):
        """That conversion is read_celsius. A copy of it here is the second
        reader arriving one number at a time."""
        found = [node.value for node in ast.walk(self.tree())
                 if isinstance(node, ast.Constant)
                 and node.value in (1000, 1000.0)]
        self.assertEqual(found, [])

    def test_the_sensors_come_from_the_module_that_ranks_them(self):
        names = {node.attr for node in ast.walk(self.tree())
                 if isinstance(node, ast.Attribute)
                 and isinstance(node.value, ast.Name)
                 and node.value.id == "temperature"}
        for wanted in ("find_sensors", "pick_sensor", "read_celsius"):
            self.assertIn(wanted, names)


if __name__ == "__main__":
    unittest.main()
