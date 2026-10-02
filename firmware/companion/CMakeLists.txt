# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
set(COMPONENTS main)
# The number of the build and its commit, as "61-1eec536", which the CI
# job gives. The number counts up with every build, and an update over the
# network is offered only for a higher one: see main/panel_update.c. A
# build made by hand is build 0, below every build of the job. A dash and
# not a space, because this goes into a compile definition.
if(DEFINED ENV{PANEL_BUILD} AND NOT "$ENV{PANEL_BUILD}" STREQUAL "")
    set(PROJECT_VER "$ENV{PANEL_BUILD}-$ENV{PANEL_COMMIT}")
else()
    set(PROJECT_VER "0-local")
endif()
project(steamos_companion)
