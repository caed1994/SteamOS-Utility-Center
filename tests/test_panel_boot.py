# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""The startup animation of the wall panel, read out of the firmware.

What the animation does is checked where it can really run:
firmware/companion/preview/check_boot.c plays the file on a host LVGL and
watches it cover the screen, end, and go. That needs LVGL, so it runs in the
job and not here.

What these hold is everything that check cannot see. The asset belongs to
somebody else and has to stay declared. The decoder has to stay turned on,
or the animation is a black screen that never lifts. And the animation has
to stay after the screen is built and before the network work, because that
is the whole reason it costs no time.
"""

from __future__ import annotations

import collections
import os
import re
import tempfile
import subprocess
import shutil
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANION = os.path.join(REPO, "firmware", "companion")
FIRMWARE = os.path.join(COMPANION, "main")
ASSETS = os.path.join(FIRMWARE, "assets")
WORKFLOW = os.path.join(REPO, ".github", "workflows",
                        "companion-firmware.yml")

ANIMATION = os.path.join(ASSETS, "boot-steam.gif")
ORIGIN = os.path.join(ASSETS, "ORIGIN-BOOT-ANIMATION")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def without_comments(text):
    """The C with its comments taken out.

    These read calls and order. panel_boot.c explains itself at length, and
    a rule that answers from a word in a comment answers nothing.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


class AnimationFileTest(unittest.TestCase):
    """The file itself, and that it says whose it is."""

    def test_the_animation_is_there_and_is_a_gif(self):
        self.assertTrue(os.path.exists(ANIMATION), ANIMATION)
        with open(ANIMATION, "rb") as handle:
            self.assertIn(handle.read(6), (b"GIF87a", b"GIF89a"))

    def test_it_fits_in_the_partition_with_room_to_spare(self):
        """The app partition is 8 MB and the firmware fills about 1.5 MB.

        The number is a ceiling and not a measurement. It fails when
        somebody replaces the file with one that changes the answer to
        "does this still fit", not when they re-encode it a little larger.
        """
        size = os.path.getsize(ANIMATION)
        self.assertLess(size, 2 * 1024 * 1024,
                        "an animation this large needs the partition table "
                        "looked at again, not a bigger number here")

    def test_the_origin_of_it_is_written_down(self):
        """It is not ours, and a reader has to be able to find that out.

        This is the rule the icons follow: assets/LICENSE-LUCIDE sits beside
        the drawings. A file somebody else owns and nothing says so is the
        thing this forbids.
        """
        self.assertTrue(os.path.exists(ORIGIN), ORIGIN)
        text = read(ORIGIN)
        self.assertIn("boot-steam.gif", text)
        self.assertIn("Valve", text)
        for says in ("NOT under the GPL-3.0-or-later", "ffmpeg"):
            self.assertIn(says, text,
                          "the origin has to say what it is and how it "
                          "was made")

    def test_the_code_sends_a_reader_to_that_origin(self):
        """A note in the source, the way icons.c names LICENSE-LUCIDE."""
        for name in ("panel_boot.c",):
            self.assertIn("ORIGIN-BOOT-ANIMATION",
                          read(os.path.join(FIRMWARE, name)), name)

    def delays(self):
        """How long each frame of the animation holds, in hundredths.

        A GIF carries that in a Graphic Control Extension, which is a block
        of eight bytes: 0x21 0xF9 0x04, one byte of flags, the delay as two
        bytes, the transparent colour, and a nought that ends the block.
        The nought is what makes this reliable enough to count on. A run of
        those three bytes inside the compressed pixels is possible, and a
        nought in the eighth place after it is not likely.
        """
        with open(ANIMATION, "rb") as handle:
            data = handle.read()
        found, at = [], 0
        while True:
            at = data.find(b"\x21\xF9\x04", at)
            if at < 0:
                return found
            if at + 8 <= len(data) and data[at + 7] == 0:
                found.append(data[at + 4] | (data[at + 5] << 8))
            at += 1

    def test_every_frame_holds_for_the_same_time(self):
        """Reported from the board: the animation stutters.

        A GIF counts in hundredths of a second, so 30 frames a second is
        3.33 and cannot be written. ffmpeg wrote 4, 3, 3, 4, 3, 3 instead,
        and every third frame held a third longer than the two beside it.
        That is a third of the frames out of step, from beginning to end.

        25 frames a second is 4 hundredths and nothing else. This rule
        fails on the file that was here before it, which is the point of
        it: the next re-encode at a rate that does not divide into 100
        brings the stutter back in silence otherwise.
        """
        found = self.delays()
        self.assertTrue(found, "no frame delay found in the animation")
        self.assertEqual(sorted(set(found)), [4],
                         "the frames do not all hold for 40 ms: %r"
                         % dict(collections.Counter(found)))

    def test_the_firmware_measures_against_that_time(self):
        """panel_boot.c times the frames against a number of its own.

        A re-encode that changes the file and not that number measures the
        animation against a rate it does not run at, and the reading it
        prints is then wrong in a way nobody can see.
        """
        said = re.search(r"#define FRAME_MS (\d+)",
                         read(os.path.join(FIRMWARE, "panel_boot.c")))
        self.assertIsNotNone(said, "panel_boot.c names no frame time")
        self.assertEqual(int(said.group(1)), self.delays()[0] * 10)

    def canvas(self):
        """The size of the picture, out of the GIF header.

        Bytes six to nine of every GIF hold the width and the height, two
        bytes each, least significant first. A fixed place, so reading it
        needs no parser and cannot lose its way in the compressed pixels.
        """
        with open(ANIMATION, "rb") as handle:
            head = handle.read(10)
        return (head[6] | (head[7] << 8), head[8] | (head[9] << 8))

    def test_the_origin_names_the_size_the_file_really_is(self):
        """The recipe has to make the file beside it.

        It said fps=24 once while the file ran at 30, and a reader who
        trusts it makes a different file. The size is the same kind of
        claim and drifts the same way.
        """
        width, height = self.canvas()
        text = read(ORIGIN)
        self.assertIn("scale=%d:%d" % (width, height), text,
                      "the recipe scales to another size than the file is")
        self.assertIn("%dx%d" % (width, height), text,
                      "the prose names another size than the file is")

    def test_it_fits_on_the_panel(self):
        """panel_boot.c centres the picture and asks nothing. One wider
        than the screen is one with its edges cut off."""
        width, height = self.canvas()
        self.assertLessEqual(width, 480)
        self.assertLessEqual(height, 480)

    def test_the_origin_carries_the_rate_the_file_runs_at(self):
        """The recipe in there has to make the file that is here."""
        text = read(ORIGIN)
        self.assertIn("fps=25", text,
                      "the recipe in the origin makes another file than "
                      "the one beside it")


class DecoderTest(unittest.TestCase):
    """The GIF decoder, which LVGL builds and leaves off."""

    def test_the_build_turns_the_decoder_on(self):
        """Without this the animation never loads.

        panel_boot.c takes a refused image away again, so the panel starts
        without an animation instead of behind a black screen. The point of
        this rule is that it does not come to that.
        """
        self.assertIn("CONFIG_LV_USE_GIF=y",
                      read(os.path.join(COMPANION, "sdkconfig.defaults")))

    def test_the_preview_turns_it_on_too(self):
        """check_boot links panel_boot.c, which calls lv_gif_create."""
        self.assertIn("#define LV_USE_GIF 1",
                      read(os.path.join(COMPANION, "preview", "lv_conf.h")))

    def test_the_checks_run_at_the_depth_the_panel_does(self):
        """The preview was at 32 bits and the panel is at 16.

        That one difference hid the green: at 32 bits there is an alpha
        channel to hold transparency and at 16 there is not, so the checks
        saw a correct screen that the board never showed.
        """
        self.assertIn("#define LV_COLOR_DEPTH 16",
                      read(os.path.join(COMPANION, "preview", "lv_conf.h")))
        sdkconfig = read(os.path.join(COMPANION, "sdkconfig.defaults"))
        self.assertNotIn("CONFIG_LV_COLOR_DEPTH_32", sdkconfig,
                         "the firmware moved and the preview did not")

    def test_the_image_header_carries_the_magic(self):
        """Because the descriptor is one, not because lv_gif looks.

        lv_image_src_get_type reads the first byte of whatever it is handed
        and calls anything below 0x20 a descriptor, so a zero works as well
        as the 0x19 of a real one. The other paths of LVGL that take an
        lv_image_dsc_t do read it, and a half-filled struct is the kind of
        thing that works until it does not.
        """
        code = without_comments(read(os.path.join(FIRMWARE, "panel_boot.c")))
        self.assertRegex(code, r"\.header\.magic\s*=\s*LV_IMAGE_HEADER_MAGIC")

    def test_it_asks_for_the_format_the_display_takes(self):
        code = without_comments(read(os.path.join(FIRMWARE, "panel_boot.c")))
        self.assertIn("lv_gif_set_color_format", code)
        self.assertIn("LV_COLOR_FORMAT_RGB565", code)

    def test_it_plays_one_time(self):
        """Not what ends the animation, but what keeps the exit clean.

        The file carries a loop count of 0, and LVGL leaves a zero running.
        The cover goes on the first LV_EVENT_READY either way. What this
        saves is the frame decoded and shown between that event and the
        delete, which reads as a flash of the first frame on the way out.
        """
        code = without_comments(read(os.path.join(FIRMWARE, "panel_boot.c")))
        self.assertRegex(code, r"lv_gif_set_loop_count\s*\([^,]+,\s*1\s*\)")

    def test_a_refused_image_takes_the_cover_away(self):
        """Otherwise a panel that cannot decode shows black for ever."""
        code = without_comments(read(os.path.join(FIRMWARE, "panel_boot.c")))
        refused = re.search(r"if\s*\(\s*!\s*lv_gif_is_loaded\s*\([^)]*\)\s*\)"
                            r"\s*\{(.*?)\}", code, re.S)
        self.assertIsNotNone(refused, "nothing checks whether it loaded")
        self.assertIn("lv_obj_delete", refused.group(1))


class WhereItPlaysTest(unittest.TestCase):
    """Its place in app_main, which is the whole argument for having it."""

    def source(self):
        return without_comments(read(os.path.join(FIRMWARE, "main.c")))

    def test_it_comes_after_the_screen_is_built(self):
        """Over a finished page, not in front of building one."""
        code = self.source()
        built = code.index("panel_ui_create(action_send")
        shown = code.index("panel_boot_show(")
        self.assertLess(built, shown,
                        "the animation covers a page that is ready, so the "
                        "page is ready first")

    def test_it_comes_before_the_network_work(self):
        """This is what makes it cost nothing.

        Everything below it joins the WLAN and waits for the PC. Move it
        after that and it stops covering the wait and becomes a delay of
        three seconds that somebody added.
        """
        code = self.source()
        shown = code.index("panel_boot_show(")
        network = code.index("esp_netif_init()")
        self.assertLess(shown, network,
                        "put it after the network work and it is a pause, "
                        "not a cover")

    def test_it_runs_under_the_display_lock(self):
        """It builds LVGL objects, and the LVGL task draws them."""
        code = self.source()
        shown = code.index("panel_boot_show(")
        locked = code.rindex("bsp_display_lock(", 0, shown)
        unlocked = code.index("bsp_display_unlock()", locked)
        self.assertLess(shown, unlocked,
                        "the show is outside the lock it needs")

    def test_the_bytes_come_from_the_embedded_file(self):
        code = self.source()
        self.assertIn('asm("_binary_boot_steam_gif_start")', code)
        self.assertIn('asm("_binary_boot_steam_gif_end")', code)

    def test_the_build_embeds_that_file(self):
        build = read(os.path.join(FIRMWARE, "CMakeLists.txt"))
        self.assertIn("EMBED_FILES", build)
        self.assertIn("assets/boot-steam.gif", build)
        self.assertIn("panel_boot.c", build)


class CoverTest(unittest.TestCase):
    """What the cover does while it is up."""

    def source(self):
        return without_comments(read(os.path.join(FIRMWARE, "panel_boot.c")))

    def test_the_cover_swallows_a_touch(self):
        """A finger during these seconds must not reach a button nobody can
        see. A cover that is not clickable is not the hit target and the
        press goes through it.

        A new object is clickable already, so this holds a line that says
        what it means rather than one that fixes anything. The cover of a
        sleeping panel takes the flag away, and the two sit side by side.
        """
        self.assertRegex(self.source(),
                         r"lv_obj_add_flag\s*\(\s*cover\s*,\s*"
                         r"LV_OBJ_FLAG_CLICKABLE\s*\)")

    def test_the_pointer_goes_when_the_object_does(self):
        """A clean of the screen takes the cover. A pointer kept past that
        is a use of a deleted object, which is the bug panel_ui_sleep had.
        LVGL says when an object goes, so nothing has to remember."""
        code = self.source()
        self.assertIn("LV_EVENT_DELETE", code)
        forget = re.search(r"static void forget\s*\([^)]*\)\s*\{(.*?)\}",
                           code, re.S)
        self.assertIsNotNone(forget)
        self.assertIn("cover = NULL", forget.group(1).replace("cover=NULL",
                                                              "cover = NULL"))

    def test_the_delete_waits_until_the_event_is_over(self):
        """Both ways out run inside an event LVGL sent under this cover.

        lv_gif is the plain case: it sends LV_EVENT_READY and then reads
        gifobj->loop_count. A plain lv_obj_delete in that event frees the
        object that LVGL reads on the next line. check_boot watches the gap
        on the touch path, where it is the only thing that can see it.
        """
        code = self.source()
        self.assertIn("lv_obj_delete_async", code)
        # Only inside the handlers. A plain delete in panel_boot_show is
        # right: those paths run before any event exists, and they take a
        # cover away that nothing has drawn yet.
        for name in ("forget", "finish", "played_out", "skipped"):
            found = re.search(r"static void %s\s*\([^)]*\)\s*\{(.*?)\n\}"
                              % name, code, re.S)
            self.assertIsNotNone(found, "no %s()" % name)
            self.assertNotRegex(
                found.group(1), r"(?<!_async)\blv_obj_delete\s*\(",
                "%s() deletes inside the event it was sent" % name)

    def test_the_panel_is_free_before_the_object_goes(self):
        """Dropping the pointer is what makes the panel usable, and it
        happens first. The object lives to the end of the handler."""
        code = self.source()
        finish = re.search(r"static void finish\s*\(void\)\s*\{(.*?)\n\}",
                           code, re.S)
        self.assertIsNotNone(finish, "no finish()")
        body = finish.group(1)
        cleared = body.index("cover = NULL")
        deleted = body.index("lv_obj_delete_async")
        self.assertLess(cleared, deleted,
                        "the pointer has to go before the object does")

    def test_a_second_show_does_not_stack_a_second_cover(self):
        code = self.source()
        self.assertRegex(code, r"if\s*\(\s*cover\s*\)\s*return\s*;")

    def test_no_image_is_a_panel_that_simply_starts(self):
        """Deleting the asset has to leave a working panel."""
        code = self.source()
        self.assertRegex(code,
                         r"if\s*\(\s*!\s*image\s*\|\|\s*size\s*==\s*0\s*\)"
                         r"\s*return\s*;")


class TheJobRunsItTest(unittest.TestCase):
    """check_boot needs LVGL, so the job is the only place it runs."""

    def test_the_job_builds_and_runs_the_check(self):
        text = read(WORKFLOW)
        self.assertIn("check_boot", text)
        self.assertRegex(text, r"\./preview-build/check_boot")

    def test_the_preview_build_knows_the_check(self):
        build = read(os.path.join(COMPANION, "preview", "CMakeLists.txt"))
        self.assertIn("add_executable(check_boot check_boot.c "
                      "../main/panel_boot.c)", build)


class FlashGuardTest(unittest.TestCase):
    """What scripts/flash-companion.sh refuses to write to.

    The port was a guess in a text field. On the machine this was found on,
    /dev/ttyACM0 was the panel, /dev/ttyACM1 was a Steam Controller dongle,
    and unplugging the panel moved the dongle to ACM0. The button would then
    have reset a Valve device and handed it to esptool.

    esptool refuses a wrong chip on its own, but only after resetting the
    board to ask. The vendor is a file udev already filled in, so it is read
    first and nothing is disturbed.
    """

    SCRIPT = os.path.join(REPO, "scripts", "flash-companion.sh")

    def run_it(self, vendor, model="Some Device", product="4001"):
        """The script, as a person and not as root, with a made-up udevadm."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        # mkdtemp gives 0700, and the script is run as somebody else below,
        # who then cannot even reach the port it is asked about.
        os.chmod(root, 0o755)
        fake = os.path.join(root, "udevadm")
        with open(fake, "w") as handle:
            handle.write("#!/usr/bin/env bash\n"
                         "echo ID_VENDOR_ID=%s\n"
                         "echo ID_MODEL_ID=%s\n"
                         "echo ID_MODEL=%s\n"
                         % (vendor, product, model.replace(" ", "_")))
        os.chmod(fake, 0o755)
        port = os.path.join(root, "ttyFake")
        open(port, "w").close()
        place = dict(os.environ, PATH="%s:%s" % (root, os.environ["PATH"]),
                     HOME=root)
        # Not as root: the script refuses that before it looks at anything.
        return subprocess.run(
            ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups",
             "bash", self.SCRIPT, port, root],
            capture_output=True, text=True, env=place, timeout=60)

    def test_it_refuses_a_board_that_is_not_espressif(self):
        done = self.run_it("28de", "Steam Controller")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("not an Espressif board", done.stderr)

    def test_it_says_what_it_found_instead(self):
        """A refusal that names nothing leaves a person guessing which of
        their three ports it was."""
        done = self.run_it("0403", "FTDI USB Serial")
        self.assertIn("FTDI", done.stderr)
        self.assertIn("/dev/serial/by-id/", done.stderr)

    def test_an_espressif_board_gets_past_the_guard(self):
        """It stops later for want of an image, which is the next check and
        not this one."""
        done = self.run_it("303a", "USB JTAG serial debug unit")
        self.assertNotIn("not an Espressif board", done.stderr)
        self.assertIn("no firmware in", done.stderr)

    def test_the_native_usb_port_gets_no_baud_rate_change(self):
        """The panel reports "USB mode: USB-Serial/JTAG", which is a USB
        device of the chip itself and not a serial chip. The rate of a USB
        CDC device is a field the hardware ignores.

        esptool does not know that. It calls change_baud whenever the rate
        asked for stands above the one it connects with, on this port as on
        any other, so a number here bought no speed and put a handshake in
        the middle of a two megabyte write. The write stopped in the middle
        again and again.

        1001 is the product of that unit. esptool holds the same number as
        USB_JTAG_SERIAL_PID."""
        done = self.run_it("303a", "USB JTAG serial debug unit", "1001")
        self.assertIn("nothing behind it", done.stdout)
        self.assertIn("115200", done.stdout)

    def test_a_serial_chip_keeps_the_faster_rate(self):
        """There the rate is real and the write takes a quarter of the
        time."""
        done = self.run_it("303a", "CP2102 USB to UART Bridge", "ea60")
        # It reached the check and passed it, rather than stopping in front
        # of it. Without this the rule below holds for a script that never
        # ran that far.
        self.assertIn("no firmware in", done.stderr)
        self.assertNotIn("nothing behind it", done.stdout)

    def test_it_writes_again_rather_than_ask_the_person_to(self):
        """Two megabytes over this port stop in the middle now and then.
        Writing it again from the start is safe: every block is checked
        against its own hash, so a second run repairs what a first left
        behind."""
        with open(self.SCRIPT, encoding="utf-8") as handle:
            text = handle.read()
        self.assertRegex(text, r"(?m)^ATTEMPTS=([2-9])")
        self.assertRegex(text, r'for attempt in \$\(seq 1 "\$ATTEMPTS"\)')
        # The whole write is one function, so a retry repeats all of it and
        # not the last part of it.
        self.assertRegex(text, r"(?s)write_it\(\) \{.*0x20000 \"\$APPLICATION\"")
        self.assertIn("if write_it; then", text)

    def test_a_write_that_never_finishes_says_what_that_leaves(self):
        """A board that holds half an image does not start, and somebody
        who does not know that thinks it is broken."""
        with open(self.SCRIPT, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("holds half an image", text)

    def test_the_vendor_is_read_before_esptool_runs(self):
        """esptool resets the board to ask which chip it is. A reset of
        somebody else's device is small and it is not nothing."""
        with open(self.SCRIPT, encoding="utf-8") as handle:
            text = handle.read()
        self.assertLess(text.index("not an Espressif board"),
                        text.index("-m esptool"))


if __name__ == "__main__":
    unittest.main()
