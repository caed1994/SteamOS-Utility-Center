# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later
idf_component_register(SRCS "main.c" "panel_auth.c" "panel_ui_sleep.c" "panel_key.c" "panel_power.c" "panel_display.c" "ui.c" "icons.c" "config.c" INCLUDE_DIRS "."
    REQUIRES mbedtls esp_driver_ledc esp_wifi esp_event esp_netif esp_http_client esp_http_server nvs_flash json esp_lcd esp_timer esp_system esp_app_format espressif__esp_lcd_touch espressif__esp_lvgl_port espressif__esp_io_expander
    EMBED_TXTFILES "setup.html")
