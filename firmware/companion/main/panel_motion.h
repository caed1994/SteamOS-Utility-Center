// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Lift to wake: the accelerometer of the board, a QMI8658 on the shared
// I2C bus. See panel_lift.h for what counts as a lift and panel_motion.c
// for who reads it.
#pragma once

#include <stdbool.h>

#include "esp_err.h"

// Finds the sensor and starts the task that reads it. ESP_OK when it
// answered with its own identity. An error is no fault of the panel: a
// board without the sensor runs as before, and a lift wakes nothing.
esp_err_t panel_motion_init(void);

// Whether to watch for a lift. The accelerometer runs only while this is
// on, and every watch starts with a fresh rest.
void panel_motion_watch(bool on);

// true once after a lift that the watch saw, and false after that.
bool panel_motion_take_lift(void);
