// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// What the panel shows while it starts.
//
// The animation is not a pause that this adds. Look at the order in
// app_main: the screen is built, and then the network half starts, joins
// the WLAN and waits for the first answer of the PC. That takes a second or
// three, and the panel used to spend it showing a finished page with no
// numbers in it. The animation covers exactly that, so it costs no time
// that the panel was not already spending.
//
// The image is in assets/boot-steam.gif and belongs to Valve. It is not
// under the licence of this project. assets/ORIGIN-BOOT-ANIMATION says what
// it is, where it came from and how to take it out.
#include "panel_boot.h"

/* The cover the animation sits on. It is black, it is the whole screen, and
 * it stays clickable, so that it swallows a touch: a finger on the panel
 * during these three seconds must not press a button that the person cannot
 * see. A new object is clickable already, so the line that says so below
 * changes nothing and is there to be read. The cover of a sleeping panel is
 * the opposite and takes that flag away, because there the touch device
 * itself is off. See panel_ui_sleep.c. */
static lv_obj_t *cover;

/* LVGL tells an object when it goes, and a clean of the screen takes this
 * one with it. So the pointer is dropped here and not by a caller who
 * remembers to. A pointer to a deleted object is the bug that panel_ui_sleep
 * had, and this cannot have it. */
static void forget(lv_event_t *event)
{
    (void)event;
    cover = NULL;
}

/* Take the animation away.
 *
 * The pointer is dropped first and the object goes later, on purpose. Both
 * of the callers below run inside an event that LVGL sent to an object
 * under this cover, and LVGL reads that object again after the event
 * returns. lv_gif is the plain case: it sends LV_EVENT_READY and then reads
 * gifobj->loop_count, so a delete inside that event is a read of memory
 * that was freed. lv_obj_delete_async puts the delete after the timer
 * handler, where nothing holds the object any more.
 *
 * Dropping the pointer first is what makes the panel usable at once
 * regardless: from here panel_boot_playing is false, although the object
 * lives until the end of this handler. */
static void finish(void)
{
    if (!cover) return;
    lv_obj_t *going = cover;
    cover = NULL;
    lv_obj_delete_async(going);
}

static void played_out(lv_event_t *event)
{
    (void)event;
    finish();
}

static void skipped(lv_event_t *event)
{
    (void)event;
    /* Somebody is already touching the panel, so they are not waiting for
     * a logo. */
    finish();
}

bool panel_boot_playing(void)
{
    return cover != NULL;
}

void panel_boot_show(const void *image, size_t size)
{
    /* No image is a panel that starts without an animation, and that is a
     * working panel. Somebody who deletes the asset gets this. */
    if (!image || size == 0) return;
    if (cover) return;

    lv_obj_t *screen = lv_screen_active();
    if (!screen) return;
    cover = lv_obj_create(screen);
    if (!cover) return;
    lv_obj_remove_style_all(cover);
    lv_obj_set_pos(cover, 0, 0);
    lv_obj_set_size(cover, lv_obj_get_width(screen), lv_obj_get_height(screen));
    lv_obj_set_style_bg_color(cover, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(cover, LV_OPA_COVER, 0);
    lv_obj_remove_flag(cover, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(cover, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(cover, forget, LV_EVENT_DELETE, NULL);
    lv_obj_add_event_cb(cover, skipped, LV_EVENT_CLICKED, NULL);

    /* lv_gif keeps this pointer rather than the bytes, so it outlives the
     * call.
     *
     * magic is not what makes this load. lv_image_src_get_type reads the
     * first byte of whatever it is given and calls anything below 0x20 a
     * descriptor, so a zero there works as well as the 0x19 of a real one.
     * It is set because this IS an image descriptor, and the other paths of
     * LVGL that read one do look. */
    static lv_image_dsc_t film;
    film.header.magic = LV_IMAGE_HEADER_MAGIC;
    film.header.cf = LV_COLOR_FORMAT_RAW;
    film.header.w = 0;
    film.header.h = 0;
    film.data = image;
    film.data_size = size;

    lv_obj_t *picture = lv_gif_create(cover);
    if (!picture) { lv_obj_delete(cover); return; }
    /* RGB565 is what the display takes. ARGB8888, which is the default,
     * would be twice the buffer for a transparency that black does not
     * need. */
    lv_gif_set_color_format(picture, LV_COLOR_FORMAT_RGB565);
    lv_gif_set_src(picture, &film);
    if (!lv_gif_is_loaded(picture)) {
        /* A refused image leaves a black screen that never goes away, which
         * is worse than no animation. */
        LV_LOG_WARN("panel_boot: the animation did not load");
        lv_obj_delete(cover);
        return;
    }
    /* The file carries a loop count of 0, which LVGL takes as "again and
     * again": it pauses the timer for a count below zero and counts one
     * down above zero, and leaves zero running. The cover goes on the first
     * LV_EVENT_READY either way, so this is not what ends the animation.
     * What it saves is the frame that would be decoded and shown between
     * that event and the delete, which reads as a flash of the first frame
     * on the way out. */
    lv_gif_set_loop_count(picture, 1);
    lv_obj_center(picture);
    lv_obj_add_event_cb(picture, played_out, LV_EVENT_READY, NULL);
    lv_obj_move_foreground(cover);
}
