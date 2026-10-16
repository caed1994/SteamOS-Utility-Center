# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The update of the panel over the network, from the side of this machine.

Three things are held here. The flash layout: two slots for the firmware,
the place of nvs that keeps the settings, and the offsets the flash script
writes to. The offer: the image of the toolbox, its number, its SHA-256 and
the signature with the token. And the path that hands the image out, which
answers a signed request and nothing else.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "server"))

from steamos_utility_center import companion  # noqa: E402

FIRMWARE = os.path.join(REPO, "firmware", "companion")
TOKEN = "x" * 32


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return handle.read()


def partitions():
    """The rows of partitions.csv, as (name, type, subtype, offset, size)."""
    rows = []
    for line in read("firmware", "companion", "partitions.csv").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name, kind, sub, offset, size = [part.strip() for part in
                                         line.split(",")[:5]]
        rows.append((name, kind, sub, int(offset, 0), int(size, 0)))
    return {row[0]: row for row in rows}


def image(version, size=4096):
    """An ESP-IDF image with that version in its app description."""
    head = bytearray(size)
    head[0] = companion.IMAGE_MAGIC
    at = companion.APP_DESC_OFFSET
    head[at:at + 4] = companion.APP_DESC_MAGIC.to_bytes(4, "little")
    raw = version.encode()
    head[at + companion.VERSION_AT:at + companion.VERSION_AT + len(raw)] = raw
    return bytes(head)


class LayoutTest(unittest.TestCase):
    """The partition table, the flash script and the build, read."""

    def test_two_slots_of_one_size_and_room_to_grow(self):
        """The board's image is 2.2 MB. A slot holds three times that, as
        the owner of the panel asked for room above."""
        table = partitions()
        first, second = table["ota_0"], table["ota_1"]
        self.assertEqual((first[1], first[2]), ("app", "ota_0"))
        self.assertEqual((second[1], second[2]), ("app", "ota_1"))
        self.assertEqual(first[4], second[4])
        self.assertGreaterEqual(first[4], 3 * 2200 * 1024)
        self.assertEqual(first[4], companion.SLOT_BYTES)
        self.assertEqual(table["otadata"][1:3], ("data", "ota"))
        self.assertEqual(table["otadata"][4], 0x2000)

    def test_nvs_stays_where_it_was(self):
        """The network, the PC, the token and the settings live in it. A
        board written with this table keeps them."""
        self.assertEqual(partitions()["nvs"][3:], (0x9000, 0x6000))

    def test_the_slots_are_aligned_and_nothing_overlaps(self):
        rows = sorted(partitions().values(), key=lambda row: row[3])
        for row in rows:
            if row[1] == "app":
                self.assertEqual(row[3] % 0x10000, 0, row[0])
        for one, two in zip(rows, rows[1:]):
            self.assertLessEqual(one[3] + one[4], two[3], (one, two))
        last = rows[-1]
        self.assertLessEqual(last[3] + last[4], 16 * 1024 * 1024)
        self.assertGreaterEqual(rows[0][3], 0x9000, "the table is at 0x8000")

    def test_the_flash_script_writes_where_the_table_says(self):
        text = read("scripts", "flash-companion.sh")
        table = partitions()
        self.assertIn('0x%x "$OTADATA"' % table["otadata"][3], text)
        self.assertIn('0x%x "$APPLICATION"' % table["ota_0"][3], text)
        self.assertIn('0x8000 "$PARTITIONS"', text)
        self.assertIn('0x0 "$BOOTLOADER"', text)

    def test_the_bootloader_falls_back(self):
        self.assertRegex(read("firmware", "companion", "sdkconfig.defaults"),
                         r"(?m)^CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y$")

    def test_the_build_carries_its_number_from_the_job(self):
        cmake = read("firmware", "companion", "CMakeLists.txt")
        self.assertIn('set(PROJECT_VER "$ENV{PANEL_BUILD}-$ENV{PANEL_COMMIT}")',
                      cmake)
        self.assertIn('set(PROJECT_VER "0-local")', cmake)
        self.assertLess(cmake.index("PROJECT_VER"), cmake.index("project("))
        job = read(".github", "workflows", "companion-firmware.yml")
        self.assertIn('export PANEL_BUILD="$GITHUB_RUN_NUMBER"', job)
        self.assertIn('export PANEL_COMMIT="${GITHUB_SHA:0:7}"', job)
        self.assertLess(job.index("export PANEL_BUILD"),
                        job.index("idf.py build"))

    def test_the_job_ships_the_empty_otadata(self):
        """Without it a flash over USB leaves the choice of the last update
        in otadata, and the board boots the other slot."""
        job = read(".github", "workflows", "companion-firmware.yml")
        self.assertIn('cp "$build/ota_data_initial.bin"', job)
        self.assertRegex(job, r"(?s)sha256sum .*ota_data_initial\.bin")
        self.assertIn("ota_data_initial.bin", companion.IMAGE_PARTS)


class VersionTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, data):
        path = os.path.join(self.root, "image.bin")
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_the_version_out_of_the_app_description(self):
        self.assertEqual(companion.image_version(self.write(image("61-1eec536"))),
                         "61-1eec536")

    def test_the_image_in_the_tree_is_read_too(self):
        """A real image of this firmware, and not one this test made."""
        path = os.path.join(FIRMWARE, "prebuilt", "steamos_companion.bin")
        if not os.path.exists(path):
            self.skipTest("no image in this tree")
        self.assertIsNotNone(companion.image_version(path))

    def test_what_is_no_image_has_no_version(self):
        self.assertIsNone(companion.image_version(self.write(b"\0" * 4096)))
        broken = bytearray(image("61-a"))
        broken[companion.APP_DESC_OFFSET] ^= 0xFF
        self.assertIsNone(companion.image_version(self.write(bytes(broken))))
        self.assertIsNone(companion.image_version(self.write(b"\xe9")))
        self.assertIsNone(companion.image_version("/does/not/exist"))

    def test_the_number_of_a_build(self):
        for version, number in (("61-1eec536", 61), ("0-local", 0),
                                ("0.5.1", 0), ("", 0), (None, 0),
                                ("1204-abc", 1204)):
            self.assertEqual(companion.build_number(version), number, version)


class OfferTest(unittest.TestCase):
    """The image of a toolbox, as the service offers it."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        where = os.path.join(self.root, companion.FIRMWARE_DIR)
        os.makedirs(os.path.join(where, "main"))
        with open(os.path.join(where, "main", "main.c"), "w") as handle:
            handle.write("int main(void){return 0;}\n")
        self.prebuilt = os.path.join(self.root, companion.PREBUILT_DIR)
        for part in companion.IMAGE_PARTS:
            path = os.path.join(self.prebuilt, part)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"\0")
        self.data = image("61-1eec536", 8192)
        with open(os.path.join(self.prebuilt, "steamos_companion.bin"),
                  "wb") as handle:
            handle.write(self.data)
        self.stamp(companion.firmware_fingerprint(self.root))
        self.offer = companion.FirmwareOffer((self.root,))

    def stamp(self, text):
        with open(os.path.join(self.prebuilt, companion.STAMP_NAME),
                  "w") as handle:
            handle.write(text + "\n")

    def test_the_offer_of_an_image_that_matches_its_source(self):
        found = self.offer.current()
        self.assertEqual(found["build"], 61)
        self.assertEqual(found["version"], "61-1eec536")
        self.assertEqual(found["size"], len(self.data))
        self.assertEqual(found["sha256"], hashlib.sha256(self.data).hexdigest())

    def test_a_stale_image_is_not_offered(self):
        """The same rule as the Flash button: an image built from another
        source is firmware for another service."""
        self.stamp("0" * 64)
        self.assertIsNone(companion.FirmwareOffer((self.root,)).current())

    def test_an_image_with_a_part_missing_is_not_offered(self):
        os.unlink(os.path.join(self.prebuilt, "ota_data_initial.bin"))
        self.assertIsNone(companion.FirmwareOffer((self.root,)).current())

    def test_an_image_larger_than_a_slot_is_not_offered(self):
        with open(os.path.join(self.prebuilt, "steamos_companion.bin"),
                  "ab") as handle:
            handle.truncate(companion.SLOT_BYTES + 1)
        self.stamp(companion.firmware_fingerprint(self.root))
        self.assertIsNone(companion.FirmwareOffer((self.root,)).current())

    def test_the_offer_is_signed_with_the_token(self):
        signed = self.offer.signed(TOKEN)
        self.assertNotIn("path", signed)
        self.assertEqual(signed["sign"], companion.offer_signature(
            TOKEN, 61, len(self.data), signed["sha256"]))
        self.assertNotEqual(signed["sign"], companion.offer_signature(
            "y" * 32, 61, len(self.data), signed["sha256"]))
        self.assertIsNone(self.offer.signed(""))

    def test_the_signature_covers_the_number_the_size_and_the_hash(self):
        base = companion.offer_signature(TOKEN, 61, 100, "ab" * 32)
        for other in (companion.offer_signature(TOKEN, 62, 100, "ab" * 32),
                      companion.offer_signature(TOKEN, 61, 101, "ab" * 32),
                      companion.offer_signature(TOKEN, 61, 100, "cd" * 32)):
            self.assertNotEqual(other, base)

    def test_a_new_image_is_read_again(self):
        first = self.offer.current()
        self.data = image("62-2222222", 8192)
        path = os.path.join(self.prebuilt, "steamos_companion.bin")
        with open(path, "wb") as handle:
            handle.write(self.data)
        self.assertEqual(first["build"], 61)
        # The same size, so only the time of the change tells the two apart.
        os.utime(path, ns=(10 ** 18, 10 ** 18))
        self.assertEqual(self.offer.current()["build"], 62)

    def test_the_first_root_with_an_image_wins(self):
        """The copy the installer keeps comes before the tree of a clone."""
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        self.assertEqual(companion.FirmwareOffer((empty, self.root)).current()
                         ["build"], 61)

    def test_the_status_carries_the_signed_offer(self):
        answer = companion.status("127.0.0.1", TOKEN, self.offer)
        self.assertEqual(answer["firmware"]["build"], 61)
        self.assertIn("sign", answer["firmware"])
        self.assertIsNone(companion.status("127.0.0.1", None,
                                           self.offer)["firmware"])


class ServeTest(OfferTest):
    """The path that hands the image out."""

    def serve(self):
        self.nonces = companion.Nonces()
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            companion.make_handler(TOKEN, self.nonces, self.offer))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        conn = HTTPConnection("127.0.0.1", httpd.server_port)
        self.addCleanup(conn.close)
        return conn

    def get(self, conn, path, signed=True):
        nonce = self.nonces.issue()
        headers = {}
        if signed:
            headers = {companion.NONCE_HEADER: nonce,
                       companion.AUTH_HEADER: companion.signature(
                           TOKEN, "GET", path, nonce, b"")}
        conn.request("GET", path, headers=headers)
        answer = conn.getresponse()
        return answer, answer.read()

    def test_a_signed_request_gets_the_image_and_a_nonce(self):
        conn = self.serve()
        answer, body = self.get(conn, companion.FIRMWARE_PATH)
        self.assertEqual(answer.status, 200)
        self.assertEqual(body, self.data)
        self.assertEqual(int(answer.getheader("Content-Length")),
                         len(self.data))
        self.assertTrue(answer.getheader(companion.NONCE_HEADER))

    def test_an_unsigned_request_gets_nothing(self):
        conn = self.serve()
        answer, body = self.get(conn, companion.FIRMWARE_PATH, signed=False)
        self.assertEqual(answer.status, 401)
        self.assertNotIn(self.data[:64], body)

    def test_no_image_is_a_404(self):
        self.stamp("0" * 64)
        self.offer = companion.FirmwareOffer((self.root,))
        conn = self.serve()
        answer, _ = self.get(conn, companion.FIRMWARE_PATH)
        self.assertEqual(answer.status, 404)

    def test_the_status_through_the_service_carries_the_offer(self):
        conn = self.serve()
        answer, body = self.get(conn, "/v1/status")
        self.assertEqual(answer.status, 200)
        self.assertEqual(json.loads(body)["firmware"]["build"], 61)


def code(name):
    """A source file of the firmware, without its comments."""
    text = read("firmware", "companion", "main", name)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def body(text, head):
    """The body of the C function that starts with that head."""
    start = text.index(head)
    at = text.index("{", start)
    depth = 0
    for index in range(at, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[at:index + 1]
    raise AssertionError("no end to " + head)


class FirmwareRuleTest(unittest.TestCase):
    """The order of the update in the firmware, read off its source.

    The order is the safety: the slot is erased before the download, the
    hash is compared before the boot slot changes, and the new firmware
    stays only once the PC answered it. The board cannot show a mistake in
    that order until an update goes wrong.
    """

    def test_the_two_sides_name_one_path(self):
        self.assertIn('#define PANEL_UPDATE_PATH "%s"' % companion.FIRMWARE_PATH,
                      read("firmware", "companion", "main", "panel_update.h"))

    def test_the_two_sides_know_one_slot(self):
        found = re.search(r"#define PANEL_UPDATE_SLOT_BYTES (0x[0-9a-f]+)u",
                          read("firmware", "companion", "main",
                               "panel_update.h"))
        self.assertIsNotNone(found)
        self.assertEqual(int(found.group(1), 16), companion.SLOT_BYTES)
        self.assertEqual(int(found.group(1), 16), partitions()["ota_1"][4])

    def test_the_battery_guard_is_twenty_per_cent(self):
        self.assertRegex(read("firmware", "companion", "main",
                              "panel_update.h"),
                         r"#define PANEL_UPDATE_LEAST_BATTERY 20\b")

    def test_the_power_is_asked_before_anything_is_erased(self):
        update = body(code("main.c"), "static void firmware_update(void)")
        power = update.index("panel_update_power_ok(")
        begin = update.index("panel_ota_begin(")
        self.assertLess(power, begin)
        self.assertRegex(update[power - 10:begin],
                         r"if\(!panel_update_power_ok\([^)]*\)\)\{\s*"
                         r"update_phase\(PANEL_UPDATE_FAILED[^;]*;\s*return;")

    def test_the_slot_is_erased_before_the_download(self):
        """esp_ota_begin erases for seconds. Between two blocks of the
        download that is a socket nobody reads, and the PC gives up."""
        update = body(code("main.c"), "static void firmware_update(void)")
        self.assertRegex(update, r"panel_ota_begin\(offer\.size\)==ESP_OK"
                                 r"&&download\(&offer,&why\)")
        self.assertLess(update.index("download("),
                        update.index("panel_ota_finish("))

    def test_the_download_is_the_size_of_the_offer(self):
        download = body(code("main.c"), "static bool download(")
        self.assertIn("length!=(int64_t)offer->size", download)
        self.assertIn("return got==offer->size;", download)
        self.assertIn("panel_ota_write(block,(size_t)read)", download)

    def test_the_download_is_signed_like_every_request(self):
        download = body(code("main.c"), "static bool download(")
        self.assertRegex(download, r'panel_auth_sign\(config\.token,"GET",'
                                   r"PANEL_UPDATE_PATH,panel_nonce,")
        self.assertIn("status==401&&round==0", download)

    def test_the_boot_slot_changes_only_after_the_hash(self):
        ota = code("panel_ota.c")
        finish = body(ota, "esp_err_t panel_ota_finish(")
        self.assertEqual(ota.count("esp_ota_set_boot_partition("), 1)
        same = finish.index("same = panel_auth_equal(said, sha256);")
        refused = finish.index("if (!same)")
        end = finish.index("esp_ota_end(handle)")
        boot = finish.index("esp_ota_set_boot_partition(")
        self.assertLess(same, refused)
        self.assertLess(refused, end)
        self.assertLess(end, boot)
        self.assertRegex(finish[refused:end], r"(?s)esp_ota_abort\(handle\);"
                                              r".*return whole \?")
        self.assertNotIn("esp_ota_set_boot_partition(",
                         code("main.c") + code("ui.c"))

    def test_the_hash_covers_every_byte_written(self):
        write = body(code("panel_ota.c"), "esp_err_t panel_ota_write(")
        self.assertLess(write.index("esp_ota_write(handle, data, length)"),
                        write.index("mbedtls_md_update(&digest, data, length)"))
        self.assertIn("length > expected - written", write)

    def test_a_new_firmware_stays_once_the_pc_answered(self):
        loop = code("main.c")
        self.assertRegex(loop, r"if \(code==200 && !trial_over\) \{ "
                               r"trial_over=true; panel_ota_confirm\(\); \}")
        self.assertEqual(loop.count("panel_ota_confirm("), 1)
        confirm = body(code("panel_ota.c"), "bool panel_ota_confirm(void)")
        self.assertIn("if (state != ESP_OTA_IMG_PENDING_VERIFY) return false;",
                      confirm)
        self.assertLess(confirm.index("ESP_OTA_IMG_PENDING_VERIFY"),
                        confirm.index("esp_ota_mark_app_valid_cancel_rollback"))

    def test_the_display_stays_on_while_it_updates(self):
        """A dark panel in the middle of an update reads as one that is
        off, and somebody switches it off for real."""
        main = code("main.c")
        self.assertRegex(main, r"display_sleep_after>0 && "
                               r"!panel_ui_timer_ringing\(\) &&\s*"
                               r"!panel_ui_alarm_clock_ringing\(\) && "
                               r"!atomic_load\(&updating\) &&")
        self.assertRegex(main, r"\}else if\(atomic_load\(&updating\)\)\{"
                               r"[^}]*\}else display_sleeping\(")
        update = body(main, "static void firmware_update(void)")
        self.assertEqual(update.count("atomic_store(&updating,true);"), 1)
        self.assertTrue(update.rstrip("} \n").endswith(
            "atomic_store(&updating,false);"),
            "every way out of a failed update clears the flag")

    def test_the_flag_is_declared_before_the_screen_reads_it(self):
        """main.c is built for the board alone. A use above the
        declaration fails that build and no other."""
        main = code("main.c")
        self.assertLess(main.index("static atomic_bool updating;"),
                        main.index("atomic_load(&updating)"))

    def test_the_panel_does_the_update_itself(self):
        """The service performs the names in the table. An update is the
        panel's own work, like the setup and the wake."""
        main = code("main.c")
        self.assertRegex(main, r"if \(action==PANEL_UPDATE\) \{\s*"
                               r"firmware_update\(\);")
        table = re.search(r"const char \*names\[\]=\{(.*?)\};", main, re.S)
        self.assertNotIn("update", table.group(1))

    def test_the_offer_is_read_at_every_poll(self):
        """An offer that the PC takes back, because its image went away,
        goes from the page with the next answer."""
        request = body(code("main.c"), "static int request(")
        self.assertIn('offer_read(cJSON_GetObjectItemCaseSensitive(root,'
                      '"firmware"));', request)
        offer = body(code("main.c"), "static void offer_read(")
        self.assertIn("if(!wanted)memset(&offer,0,sizeof offer);", offer)

    def test_a_failure_goes_with_its_offer(self):
        """The red line under the card names what went wrong with one
        image. A newer image, or none, does not inherit it."""
        offer = body(code("main.c"), "static void offer_read(")
        self.assertRegex(offer, r"if\(strcmp\(state\.update\.offered,now\)!=0"
                                r"&&state\.update\.phase==PANEL_UPDATE_FAILED\)"
                                r"\s*state\.update\.phase=PANEL_UPDATE_NONE;")
        self.assertLess(offer.index("state.update.phase=PANEL_UPDATE_NONE"),
                        offer.index("snprintf(state.update.offered"))


def buildable():
    """Whether this machine has a C compiler and the mbedtls headers."""
    if not shutil.which("cc") and not shutil.which("gcc"):
        return False
    return any(os.path.exists(os.path.join(place, "mbedtls", "md.h"))
               for place in ("/usr/include", "/usr/local/include"))


@unittest.skipUnless(buildable(), "no C compiler or no mbedtls headers here")
class PanelSideTest(unittest.TestCase):
    """panel_update.c, built here and asked, against this side.

    A build that fails here fails the test, rather than skipping it: the
    file is ours and a compiler that refuses it refuses the board too.
    """

    @classmethod
    def setUpClass(cls):
        cls.where = tempfile.mkdtemp()
        cls.program = os.path.join(cls.where, "panel-update")
        main = os.path.join(FIRMWARE, "main")
        cls.built = subprocess.run(
            [shutil.which("cc") or shutil.which("gcc"), "-Wall", "-Wextra",
             "-Werror", "-I", main, "-o", cls.program,
             os.path.join(REPO, "tests", "c", "panel-update-harness.c"),
             os.path.join(main, "panel_update.c"),
             os.path.join(main, "panel_auth.c"), "-lmbedcrypto"],
            capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.where, ignore_errors=True)

    def ask(self, *words):
        self.assertEqual(self.built.returncode, 0, self.built.stderr)
        done = subprocess.run([self.program] + [str(one) for one in words],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_the_two_sides_sign_alike(self):
        sha = hashlib.sha256(b"an image").hexdigest()
        self.assertEqual(self.ask("sign", TOKEN, 61, 2213456, sha),
                         companion.offer_signature(TOKEN, 61, 2213456, sha))

    def test_the_two_sides_read_a_number_alike(self):
        for version in ("61-1eec536", "0-local", "0.5.1", "1204-abc", "x"):
            self.assertEqual(int(self.ask("build", version)),
                             companion.build_number(version), version)

    def offer(self, build=62, size=2213456, sha=None, token=TOKEN):
        sha = sha or hashlib.sha256(b"an image").hexdigest()
        return [build, size, sha,
                companion.offer_signature(token, build, size, sha)]

    def wanted(self, running, offer, token=TOKEN):
        return self.ask("wanted", token, running, *offer) == "1"

    def test_a_signed_newer_build_is_wanted(self):
        self.assertTrue(self.wanted(61, self.offer()))

    def test_the_same_or_an_older_build_is_not(self):
        self.assertFalse(self.wanted(62, self.offer()))
        self.assertFalse(self.wanted(63, self.offer()))

    def test_an_offer_signed_with_another_token_is_not(self):
        """Somebody on the network who does not know the token cannot
        offer an image of their own."""
        self.assertFalse(self.wanted(61, self.offer(token="y" * 32)))

    def test_a_changed_part_breaks_the_signature(self):
        build, size, sha, sign = self.offer()
        self.assertFalse(self.wanted(61, [build + 1, size, sha, sign]))
        self.assertFalse(self.wanted(61, [build, size + 1, sha, sign]))
        other = hashlib.sha256(b"another").hexdigest()
        self.assertFalse(self.wanted(61, [build, size, other, sign]))

    def test_an_image_larger_than_a_slot_or_empty_is_not(self):
        self.assertFalse(self.wanted(61, self.offer(
            size=companion.SLOT_BYTES + 1)))
        self.assertFalse(self.wanted(61, self.offer(size=0)))
        self.assertTrue(self.wanted(61, self.offer(
            size=companion.SLOT_BYTES)))

    def test_a_hash_that_is_no_hash_is_not(self):
        self.assertFalse(self.wanted(61, self.offer(sha="ab" * 31)))
        self.assertFalse(self.wanted(61, self.offer(sha="AB" * 32)))

    def test_the_battery_guard(self):
        """Cable, charging, or 20 per cent on the cell, as was asked."""
        for on_battery, percent, charging, ok in (
                (0, 5, 0, True), (1, 5, 1, True), (1, 20, 0, True),
                (1, 19, 0, False), (1, 0, 0, False)):
            self.assertEqual(self.ask("power", on_battery, percent,
                                      charging) == "1", ok,
                             (on_battery, percent, charging))


if __name__ == "__main__":
    unittest.main()
