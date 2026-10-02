# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later
cmake_minimum_required(VERSION 3.16)

# These run on a normal machine, with cmake and a C compiler and no Espressif
# tools. They need the LVGL that the firmware pins, which the firmware build
# downloads into a directory that no repository holds. Get it directly:
#
#   cd firmware/companion
#   git clone --depth 1 --branch v9.5.0 https://github.com/lvgl/lvgl.git \
#             managed_components/lvgl__lvgl
#   cmake -S preview -B /tmp/preview -DCMAKE_BUILD_TYPE=Debug
#   cmake --build /tmp/preview --target check_power check_idle check_navigation
#   /tmp/preview/check_power && /tmp/preview/check_idle && \
#   /tmp/preview/check_navigation
#
# The version is the one in main/idf_component.yml. The job in
# .github/workflows/companion-firmware.yml runs the same three at each push.
project(panel_preview C CXX)
set(LV_BUILD_CONF_PATH "${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h" CACHE PATH "")
set(CONFIG_LV_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_BUILD_DEMOS OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_THORVG_INTERNAL OFF CACHE BOOL "" FORCE)
add_subdirectory(../managed_components/lvgl__lvgl lvgl)

# What ui.c needs beside itself. It draws its words out of panel_text.c and
# clears the sleeping cover through panel_ui_sleep.c, and a target that
# links ui.c without them does not link at all. Both arrived after this
# file was written and neither was added, which nothing noticed because
# nothing built these. The job in
# .github/workflows/companion-firmware.yml builds and runs them now.
set(PANEL_UI_SOURCES ../main/ui.c ../main/icons.c ../main/panel_text.c
                     ../main/panel_ui_sleep.c ../main/panel_count_font.c
                     ../main/panel_clock_font.c ../main/panel_timer.c
                     ../main/panel_history.c ../main/panel_pages.c
                     ../main/panel_font_12.c ../main/panel_font_14.c
                     ../main/panel_font_16.c ../main/panel_font_18.c
                     ../main/panel_font_20.c ../main/panel_font_24.c
                     ../main/panel_font_26.c ../main/panel_font_32.c)
# The firmware build makes each warning of -Wall an error. These are its own
# sources, so this build holds them to the same rule, and a fault that stops
# the board build shows here first. A backslash at the end of a line comment
# in panel_count_font.c went through this build and stopped that one.
set_source_files_properties(${PANEL_UI_SOURCES} PROPERTIES COMPILE_OPTIONS
    "-Wall;-Werror=all;-Wno-error=unused-function;-Wno-error=unused-variable;-Wno-error=unused-but-set-variable;-Wno-error=deprecated-declarations")
add_executable(panel_preview preview.c ${PANEL_UI_SOURCES})
target_include_directories(panel_preview PRIVATE ../main)
target_link_libraries(panel_preview PRIVATE lvgl m)
add_executable(check_navigation check_navigation.c ${PANEL_UI_SOURCES})
target_include_directories(check_navigation PRIVATE ../main)
target_link_libraries(check_navigation PRIVATE lvgl m)
target_compile_options(check_navigation PRIVATE -UNDEBUG)
add_executable(check_idle check_idle.c ${PANEL_UI_SOURCES})
target_include_directories(check_idle PRIVATE ../main)
target_link_libraries(check_idle PRIVATE lvgl m)
target_compile_options(check_idle PRIVATE -UNDEBUG)
add_executable(check_power check_power.c ../main/panel_key.c
                           ../main/panel_ui_sleep.c)
target_include_directories(check_power PRIVATE ../main)
target_link_libraries(check_power PRIVATE lvgl m)
target_compile_options(check_power PRIVATE -UNDEBUG)
# check_wol needs no LVGL at all. It is here because this is where the
# checks of the firmware live and where the job already builds them.
add_executable(check_wol check_wol.c ../main/panel_wol.c)
target_include_directories(check_wol PRIVATE ../main)
target_compile_options(check_wol PRIVATE -UNDEBUG)
add_executable(check_pages check_pages.c ${PANEL_UI_SOURCES})
target_include_directories(check_pages PRIVATE ../main)
target_link_libraries(check_pages PRIVATE lvgl m)
target_compile_options(check_pages PRIVATE -UNDEBUG)
add_executable(check_boot check_boot.c ../main/panel_boot.c)
target_include_directories(check_boot PRIVATE ../main)
target_link_libraries(check_boot PRIVATE lvgl m)
target_compile_options(check_boot PRIVATE -UNDEBUG)
