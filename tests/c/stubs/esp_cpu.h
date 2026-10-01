// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The core and its cycle counter. See tests/c/stubs/esp_err.h.
#pragma once
#include <stdint.h>
int esp_cpu_get_core_id(void);
uint32_t esp_cpu_get_cycle_count(void);
