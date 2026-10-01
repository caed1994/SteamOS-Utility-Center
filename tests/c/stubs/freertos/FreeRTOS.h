// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A critical section with nothing to hold off: the harness runs on one
// thread. See tests/c/stubs/esp_err.h.
#pragma once
typedef struct { int owner; } portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED { 0 }
#define portNUM_PROCESSORS 2
#define portENTER_CRITICAL(mux) ((void)(mux))
#define portEXIT_CRITICAL(mux) ((void)(mux))
