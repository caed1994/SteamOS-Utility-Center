<!--
SPDX-FileCopyrightText: 2026 caed1994
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Notes for Claude Code

This file is the memory of the project for each new session. It gives the
rules of the owner, the map of the repository, and the facts that were
measured on the hardware. Trust it, and read a source file only when the task
needs that file.

## 1. Rules of the owner

- Branch: work on `experimental` and push to it. A session can start on a branch such as `claude/...`. Then change to `experimental` before the first change, and bring the commits of that branch to `experimental` first.
- Other branches: push to `main`, `addfeature` and `debug` only when the owner asks ("push auf alle branches"). They take a fast-forward from `experimental`.
- Language: reply in German. Write code, comments, commit messages and documents in English. Words for the panel screen go in `panel_text.h`, in English and German.
- Replies: short, with no filler. Say what changed, what was checked, and what the owner must do on the board.
- Bigger features: report the plan first and wait for the approval of the owner. Do small fixes and clear requests directly.
- Measure, do not assert. Say which part is verified and which part is not. A cause with no measurement is a guess, and the reply says so.
- Prove a new test with one or two mutations of the code that it guards, in a scratch copy of the tree.
- Commit and push before the end of each turn. End each commit message with the attribution lines that the session gives.

## 2. Token economy

- Use this file as the map. Do not explore the tree to find what this file says.
- Find a symbol with `grep -n` first. Then read only the lines that you need, with `sed -n` or with an offset and a limit.
- Do not open generated or large files: `panel_font_*.c`, `panel_clock_font.c`, `panel_count_font.c`, `icons.c`, `firmware/companion/prebuilt/`, `managed_components/`, `third-party-licenses/`, `decky/dist/`, `docs/previews/`.
- Do not read a file again after an edit. The edit tool fails when a change does not apply.
- Send long output through `tail`, `head` or `grep`. Never print a full build log or a full test log.
- Put independent tool calls in one message. Do not start subagents unless the owner asks for them.
- During the work, run the tests of the changed module only. Run the full suite one time, before the push.
- Do not repeat the diff in the reply. Do not write a long report.
- Keep a commit message short: a title, the reason, and one line that starts with "Checked:".

## 3. Map of the repository

| Path | What it is |
| --- | --- |
| `server/steamos_utility_center/` | The service of the PC (Python 3, no third-party packages) |
| `server/*.service`, `*.conf` | systemd units and configuration templates |
| `server/steamos-utility-centerctl` | the control command that speaks JSON (`ctl.py`) |
| `gui/` | the control panel, Tk (`steamos-utility-center-panel`) |
| `decky/` | the Game Mode plugin (TypeScript and `main.py`) |
| `firmware/companion/` | the wall panel firmware (ESP-IDF, LVGL) |
| `firmware/companion/preview/` | host builds of the screen with LVGL: checks and a preview |
| `firmware/led-client/` | the LED bar firmware, PlatformIO, ESP8266 or ESP32 |
| `scripts/` | appliers, installer parts, flash and log tools |
| `install.sh`, `uninstall.sh` | install by module (`modules.py`): `led`, `pegboard`, `power`, `cec`, `companion`, `system` |
| `tests/` | Python tests; `tests/c/` holds the C harnesses for firmware logic |
| `tools/ste-check.py` | the style check of all prose |
| `docs/` | `PROTOCOL.md` (serial frames), `STYLE.md` (STE rules), `WIRING.md` |
| `leds-valve-shim/`, `cec-toolkit/`, `dbus-next/` | work of other people: do not change, other licences |

## 4. The PC side

The PC is a Steam Machine with SteamOS. The root file system is read-only.
The installer keeps its copy in `/var/lib/steamos-utility-center` and the
clone of the source in `/var/lib/steamos-utility-center/source`.

| Part | Fact |
| --- | --- |
| LED service | `service.py`: kernel shim, renderer, USB serial to the LED client (frames in `docs/PROTOCOL.md`) |
| Modules | `led` (the bar from Steam: game, achievements, messages, load), `pegboard` (Nanoleaf Pegboard Desk Dock on USB), `power` (CPU governor and EPP, GPU through LACT), `cec` (television), `companion` (the wall panel), `system` (drives, controller wake, magic packet, Game Mode plugin) |
| Settings | `/etc/steamos-utility-center.conf`, `-power.conf`, `-pegboard.conf` |
| Appliers | `scripts/apply-*.sh`, installed at fixed paths and run as root through `sudo -n` |
| sudoers | `ctl.sudoers_text`: one program and one file on each line, no wildcard |
| Wall panel service | `companion.py`, a user service of the desktop user, never root, port 8765 |
| Wall panel API | `GET /v1/status` (every 3 s), `POST /v1/action`, `POST /v1/led`, `POST /v1/cpu`, `GET /v1/firmware` |
| Wall panel auth | HMAC with a nonce, headers `X-Panel-Nonce` and `X-Panel-Auth`, no clock needed |
| Wall panel secret | `~/.config/steamos-utility-center/companion-token`, 32 characters or more |
| Refusals | 409 a change runs, 501 no module, 403 no sudo rule, 502 refused, 401 new nonce |
| Actions | a name from the fixed table `ACTIONS`, sent to subprocess with no shell |

## 5. The wall panel firmware

The board is a Waveshare ESP32-S3-Touch-LCD-4B ("Smart 86 Box"). It asks the
PC for its status over Wi-Fi and has no cable to the PC in normal use.

| Item | Fact |
| --- | --- |
| Versions | ESP-IDF 5.5.5, LVGL 9.5.0, esp_lvgl_port 2.9.0, BSP 2.0.0, GT911 driver 1.2.1 (`dependencies.lock`) |
| Memory | 16 MB flash, 8 MB PSRAM; LVGL objects and some task stacks in PSRAM (`panel_psram.h`) |
| Display | ST7701, 480 x 480 RGB; direct mode with two frame buffers in PSRAM; bounce buffers of 40 rows |
| Pixel clock | 12 MHz in the boot animation, 16 MHz awake, 8 MHz in standby. 4 MHz showed each line twice |
| Backlight | GPIO4, LEDC 5 kHz, 10 bit, inverted. 5 % is the lowest steady level. It cannot go dark |
| CPU clock | 240 MHz awake, 80 MHz in standby (`panel_clock.c`). Below 80 the PSRAM slows. No light sleep |
| I2C bus | SDA GPIO47, SCL GPIO48: TCA9554 0x20, AXP2101 0x34, PCF85063 0x51, QMI8658 0x6B, GT911, audio codecs |
| Upper key (PWR) | EXIO4 through a BSS138, high while pressed. A short press toggles the standby |
| Lower key (BOOT) | GPIO0, low while pressed. A short press opens the start page |
| Keys | one task, every 15 ms; settle 20 ms; short press 40 to 1000 ms (`panel_key.c`, `panel_power.c`) |
| Touch | GT911, read by LVGL every 15 ms; its INT line (EXIO6) is not used |
| Standby | a black cover with a clock (`panel_ui_sleep.c`), one draw a minute. The key standby turns Wi-Fi off |
| Alarm clock | one alarm on the clock page (`panel_alarm.c`, NVS key `alarm`): weekdays or one time, snooze 5 min, rings 5 min. Both keys snooze, Off by touch only. The cover shows the next ring |
| Settings | NVS namespace `panel`: Wi-Fi, server, token, page order, theme, accent, language and more |
| Update | the PC offers `firmware/companion/prebuilt/` through `/v1/firmware`; two slots, boot on trial |

Code layout of the firmware:

- `main.c` holds the tasks, the poll of the PC and the standby rules (`display_sleeping`, `ui_tick` every 200 ms). It writes a health log line every 30 s.
- `ui.c` holds every screen: a band of seven pages and the screens over it. It holds no words and no colours of its own.
- Words come from `panel_text.h` (English and German) and colours from `panel_theme.c` (dark, light, eight accents).
- Logic with no ESP-IDF is in its own file and is tested on the host: `tests/c/<name>-harness.c` and `tests/test_<name>.py`.
- Each preview check in `firmware/companion/preview/` must be named in the CI workflow (`tests/test_preview_checks.py`).

Facts about LVGL that cost time:

- `lv_display_enable_invalidation` counts its calls. Balance each switch on with one switch off.
- `LV_DISPLAY_RENDER_MODE_FULL` sends no `LV_EVENT_INVALIDATE_AREA`. A refresh also sends that event as a probe from `get_max_row`.
- `lv_obj_get_width` returns 0 before the layout runs. Call `lv_obj_update_layout` first.
- A label draws a margin of a quarter of its line height past its box.

## 6. Hard limits

- AXP2101: write only to register 0x50 bit 4, 0x62, 0x69, and 0x30 bits 2 to 4. Read the other registers only.
- Never put a Wi-Fi password, a token or an API key into output, a log or a commit.
- Do not read the message queue of mangoapp in gamescope.
- A sudoers line has no wildcard. An applier stays at its fixed path.

## 7. Tests and checks

| What | Command |
| --- | --- |
| One module | `python3.12 -m pytest -q tests/test_<name>.py` |
| Full suite (about 3650 tests, 9 min) | `xvfb-run -a python3.12 -m pytest -q -p no:cacheprovider` |
| Prose check, must report 0 | `python3 tools/ste-check.py --quiet` |
| Screen checks | `cmake -S firmware/companion/preview -B <dir>`, then build and run `check_power check_idle check_navigation check_boot check_wol check_pages` |
| Draw a screen to a file | `<dir>/panel_preview out.ppm <mode> [de]` (modes in `preview.c`) |
| LED client parser | `./tests/firmware/run.sh` (needs g++) |

Notes for the checks:

- `python3` in the cloud container has no tkinter. Use `python3.12`, and `xvfb-run` for `tests/test_panel_live.py`.
- The C harnesses build with `-Wall -Wextra -Werror`. A build error is a failed test.
- The screen checks need LVGL v9.5.0 in `firmware/companion/managed_components/lvgl__lvgl` (clone it from GitHub).

## 8. Build, CI and the board

- CI (`.github/workflows/companion-firmware.yml`) runs on each push that changes `firmware/companion/`. It builds in `espressif/idf:v5.5.5` and runs the screen checks.
- CI then commits "Build the wall panel firmware for <sha>" with the image in `prebuilt/`. Always fetch and rebase on `origin/experimental` before a push.
- The owner flashes the image that CI made: the button "Flash the panel" in the control panel, or `scripts/flash-companion.sh /dev/ttyACM0`. The panel also takes it over Wi-Fi.
- Logs of the board come from the owner: `/var/lib/steamos-utility-center/source/scripts/panel-log.sh /dev/ttyACM0 20`. Ask for a log or a photo when a fact of the board is missing.
- A crash dump: `tools/panel-backtrace.py` with the ELF from the artifact of the CI run.
- A local firmware build is optional, because CI builds each push. In the cloud container it needs esp-idf v5.5.5 and the xtensa tool chain from GitHub.
- The component registry and the sites of Espressif and Waveshare were blocked in the cloud container. Copy the components from their GitHub repositories into `managed_components/`, with the hash from `dependencies.lock`.

## 9. Style

- Comments, docstrings and documents follow ASD-STE100 (`docs/STYLE.md`). This applies to `.py`, `.sh`, `.md` and `.service` files.
- A sentence has 25 words or less, an instruction 20. A paragraph has 6 sentences or less.
- Do not use the continuous or the perfect tense, or a dash for a remark. Write "must" for an obligation and "can" for a possibility.
- Tables, code blocks and headings are data and are not checked.
- Write the reason in one place. Do not write the history of a fault into a comment.
- Each `.py`, `.sh`, `.c` and `.h` file starts with an SPDX header (`tests/test_licensing.py`).
- C code follows the style of the file that it is in.

## 10. Open items

- Deep sleep of the panel, for a longer battery life. The owner put this off.
- A Nanoleaf page on the panel. The owner put this off.
- A switch for a high touch sensitivity under a glass protector. The plan: lower GT911 thresholds, the old values kept in NVS, and a "keep?" question of 10 s. The owner said "not yet".
