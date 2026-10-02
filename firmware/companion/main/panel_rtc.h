// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The clock chip of the board: a PCF85063 at 0x51 on the shared I2C bus.
//
// It counts on its own crystal while the ESP restarts, so the panel has
// the time right after a restart, with no network. panel_time.c reads it
// once at the start, and gives it the time of the server after each
// answer of SNTP.
//
// The chip holds UTC, and the zone is the business of the ESP. So the
// change to summer time and back does not touch the chip.
//
// The chip says when its time is not to be trusted. The flag OS in the
// register of the seconds stands at 1 from a power-on until a write of the
// time clears it, and after a stop of the crystal. A chip whose clock is
// stopped or counts in hours of twelve holds no time this reads either:
// this firmware never sets them, and a write of the time clears them.
//
// The registers and the values are those of the datasheet of NXP, rev. 7
// of 2018, which the maker of the board ships with SensorLib in
// waveshareteam/ESP32-S3-Touch-LCD-4B. This writes the register Control_1
// and the seven registers of the time, 04h to 0Ah, and nothing else.
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <time.h>

#include "esp_err.h"

// The years the chip holds: two digits, from 2000.
#define PANEL_RTC_FIRST_YEAR 2000
#define PANEL_RTC_LAST_YEAR 2099

// Looks for the chip on the bus. ESP_ERR_NOT_FOUND when nothing answers
// at its address.
esp_err_t panel_rtc_init(void);

// The time of the chip in seconds since 1970, UTC. false without a chip,
// after an error on the bus, and when the chip holds no time to trust.
bool panel_rtc_read(time_t *utc);

// The chip takes this time. ESP_ERR_INVALID_STATE without a chip, and
// ESP_ERR_INVALID_ARG for a time outside the years it holds.
esp_err_t panel_rtc_write(time_t utc);

// The work of the two above without the bus, for the tests: the register
// Control_1 and the registers 04h to 0Ah, and the time in them.
bool panel_rtc_decode(uint8_t control, const uint8_t time[7], time_t *utc);
bool panel_rtc_encode(time_t utc, uint8_t time[7]);
