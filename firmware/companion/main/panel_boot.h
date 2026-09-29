// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stddef.h>
#include <stdbool.h>
#include "lvgl.h"

// The animation the panel plays while it starts.
//
// The bytes are a parameter and not a name inside this file. The firmware
// passes the image that the build embedded, and the check under preview/
// passes the same image read from the disk of whatever machine runs it.
// A module that names its own asset can only be tested where that asset is.
void panel_boot_show(const void *image, size_t size);

// Whether the animation is on the screen now. The panel does not ask; the
// check under preview/ does.
bool panel_boot_playing(void);
