# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later
idf_component_register(SRCS "main.c" "panel_auth.c" "panel_text.c" "panel_ui_sleep.c" "panel_boot.c" "panel_wol.c" "panel_key.c" "panel_power.c" "panel_battery.c" "panel_clock.c" "panel_display.c" "ui.c" "icons.c" "panel_count_font.c" "panel_clock_font.c" "panel_font_12.c" "panel_font_14.c" "panel_font_16.c" "panel_font_18.c" "panel_font_20.c" "panel_font_24.c" "panel_font_26.c" "panel_font_32.c" "panel_timer.c" "panel_alarm.c" "panel_time.c" "panel_update.c" "panel_ota.c" "panel_history.c" "panel_lift.c" "panel_motion.c" "panel_pages.c" "panel_rtc.c" "panel_frames.c" "panel_led.c" "panel_cpu.c" "panel_taps.c" "panel_theme.c" "panel_lvgl_mem.c" "config.c" INCLUDE_DIRS "."
    REQUIRES mbedtls app_update esp_pm esp_driver_ledc esp_driver_i2c esp_driver_gpio esp_wifi esp_event esp_netif esp_http_client esp_http_server nvs_flash json esp_lcd esp_timer esp_system esp_app_format espressif__esp_lcd_touch espressif__esp_lvgl_port espressif__esp_io_expander
    EMBED_TXTFILES "setup.html" "setup-de.html"
    # The startup animation, as bytes. It belongs to Valve and not to
    # this project; see assets/ORIGIN-BOOT-ANIMATION.
    EMBED_FILES "assets/boot-steam.gif")
# The memory of LVGL is in panel_lvgl_mem.c, and LVGL is linked after this
# component. -u keeps that file in the link, the way esp_lvgl_port keeps
# its own functions for LVGL.
set_property(TARGET ${COMPONENT_LIB} APPEND PROPERTY INTERFACE_LINK_LIBRARIES "-u lv_mem_init")
