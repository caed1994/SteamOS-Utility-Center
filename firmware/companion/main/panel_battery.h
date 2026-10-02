// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>
#include "esp_err.h"
#include "ui.h"

/* Find the power chip of the board, an AXP2101 on the shared I2C bus.
 *
 * ESP_OK when it answered with its own type, and an error otherwise. An
 * error is not a fault of the panel: a board without the chip, or with
 * the chip on another bus, runs as before and shows no battery. */
esp_err_t panel_battery_init(void);

/* What powers the panel now.
 *
 * false when the chip was not found or did not answer this time; supply
 * is then PANEL_SUPPLY_UNKNOWN. percent means something only for
 * PANEL_SUPPLY_BATTERY. */
bool panel_battery_read(panel_supply_t *supply, int *percent, bool *charging);

/* Whether a cable feeds the panel, as the power chip says: its input is
 * good. false when the chip was not found or did not answer. A panel full
 * on its cable charges no more, so this and not the charging tells the
 * cable from the battery. Reads, and writes nothing. */
bool panel_battery_cable(void);

/* The chip in detail, for the page of the panel: the voltages, the
 * temperature of its die, the phase of the charge, what holds the charge
 * down, and the settings of the charger. Every field the chip did not
 * give is -1, and the die PANEL_NO_DEGREES. false when the chip was not
 * found or did not answer. Reads, and writes nothing. */
bool panel_battery_detail(panel_power_detail_t *out);
