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
    def serve(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                    companion.make_handler(TOKEN))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return HTTPConnection("127.0.0.1", httpd.server_port)

    def test_no_token_reaches_nothing(self):
        conn = self.serve()
        conn.request("GET", "/v1/status")
        self.assertEqual(conn.getresponse().status, 401)

    def test_an_unknown_path_answers_the_same_to_a_stranger(self):
        """The token is asked before the path, so the codes that come back
        tell a stranger nothing about which paths exist."""
        conn = self.serve()
        for path in ("/v1/status", "/v1/nothing", "/"):
            conn.request("GET", path)
            self.assertEqual(conn.getresponse().status, 401, path)

    def test_an_action_that_is_not_in_the_table_runs_nothing(self):
        conn = self.serve()
        with mock.patch.object(companion.subprocess, "run") as ran:
            conn.request("POST", "/v1/action", json.dumps({"action": "shell"}),
                         {"X-Panel-Token": TOKEN})
            self.assertEqual(conn.getresponse().status, 400)
            ran.assert_not_called()

    def test_a_known_action_runs_and_answers(self):
        conn = self.serve()
        with mock.patch.object(companion.subprocess, "run") as ran:
            conn.request("POST", "/v1/action", json.dumps({"action": "mute"}),
                         {"X-Panel-Token": TOKEN})
            self.assertEqual(conn.getresponse().status, 200)
            ran.assert_called_once()
            self.assertEqual(ran.call_args[0][0], companion.ACTIONS["mute"])

    def test_a_refused_command_comes_back_as_a_refusal(self):
        conn = self.serve()
        with mock.patch.object(companion.subprocess, "run") as ran:
            ran.side_effect = companion.subprocess.CalledProcessError(
                1, ["systemctl"])
            conn.request("POST", "/v1/action",
                         json.dumps({"action": "suspend"}),
                         {"X-Panel-Token": TOKEN})
            self.assertEqual(conn.getresponse().status, 502)

    def test_a_body_that_is_too_long_is_not_read(self):
        conn = self.serve()
        conn.request("POST", "/v1/action", "x" * (companion.BODY_LIMIT + 1),
                     {"X-Panel-Token": TOKEN})
        self.assertEqual(conn.getresponse().status, 400)

    def test_every_action_is_a_tuple_and_never_a_string(self):
        """A string goes to a shell. Each of these goes to execve."""
        for name, command in companion.ACTIONS.items():
            self.assertIsInstance(command, tuple, name)
            self.assertTrue(all(isinstance(one, str) for one in command), name)


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
