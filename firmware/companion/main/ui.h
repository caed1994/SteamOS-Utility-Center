// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <stdbool.h>

typedef enum {
    PANEL_VOLUME_DOWN, PANEL_MUTE, PANEL_VOLUME_UP,
    PANEL_SUSPEND, PANEL_REBOOT, PANEL_POWEROFF, PANEL_SETUP
} panel_action_t;

typedef struct {
    bool wifi, online, muted, setup, sound_error;
    int battery, volume, cpu_temp, gpu_temp, gpu_watts;
    char host[48], controller[64], charging[32], message[80];
    char setup_ssid[32], setup_password[32];
} panel_state_t;

typedef void (*panel_action_cb_t)(panel_action_t action);
typedef enum { PANEL_BRIGHTNESS, PANEL_SOUND_VOLUME, PANEL_TOUCH_TONES } panel_setting_t;
typedef struct { int brightness, sound_volume; bool touch_tones; } panel_settings_t;
typedef void (*panel_setting_cb_t)(panel_setting_t key, int value, bool save);
typedef void (*panel_sound_cb_t)(int volume);
void panel_ui_create(panel_action_cb_t callback, panel_setting_cb_t setting_cb, panel_sound_cb_t sound_cb, const panel_settings_t *settings);
void panel_ui_settings_open(void);
void panel_ui_update(const panel_state_t *state);
void panel_ui_confirm(panel_action_t action);
