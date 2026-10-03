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
#include <stdio.h>

/* The cover the animation sits on. It is black, it is the whole screen, and
 * it stays clickable, so that it swallows a touch: a finger on the panel
 * during these three seconds must not press a button that the person cannot
 * see. A new object is clickable already, so the line that says so below
 * changes nothing and is there to be read. The cover of a sleeping panel is
 * the opposite and takes that flag away, because there the touch device
 * itself is off. See panel_ui_sleep.c. */
static lv_obj_t *cover;

/* The rate the file holds, in milliseconds per frame.
 *
 * 25 frames a second is 4 hundredths of a second, and a GIF counts in
 * hundredths. 30 was not representable, so ffmpeg wrote 4, 3, 3, 4, 3, 3
 * and every third frame held a third longer than its neighbours.
 * assets/ORIGIN-BOOT-ANIMATION carries the rate and the reason. A
 * re-encode at another rate changes this number too. */
#define FRAME_MS 40

/* What the animation really ran at, measured while it ran.
 *
 * Reported from the board: the middle looks slower than the ends, and it
 * does. The heaviest frame of this file carries 14326 bytes of LZW and
 * covers the whole square, where the frames at each end carry about 1600
 * and cover a small rectangle in the middle of it. So the decoder has
 * about nine times the work where the shape changes.
 *
 * That alone does not make a step anybody sees. The step comes from the
 * flush, which waits for a frame boundary of the panel. A period is 22.1
 * ms at the clock of the animation (PANEL_FRAME_CLOCKS in
 * panel_display.c), so a frame takes 44 ms or 66 or 88 and nothing
 * between. Work that runs past a
 * boundary costs a whole period, and the heavy frames land a rung lower
 * than the rest.
 * LV_EVENT_DRAW_POST_END arrives once for each frame that reaches the
 * screen, because nothing else under this cover asks for a refresh. So the
 * gap between two of them is the gap a person sees. */
static uint32_t drawn, began, previous, slowest, slowest_at, slipped;

/* Every gap, in buckets of five milliseconds.
 *
 * The average and the worst frame say how bad it is. Neither says what
 * shape it is, and the shape is the answer to why.
 *
 * A flush waits for a frame boundary of the panel, so a frame takes one
 * period, or two, or three. The gaps therefore fall into heaps, one heap
 * for each count of periods, and the distance between the heaps is the
 * period. Nothing on the board has ever said what that period is. 12 MHz
 * and the timings of this panel work out at about 45 Hz, and that is a
 * calculation, not a measurement. These heaps are the measurement.
 *
 * They also separate two causes that look alike in an average. Work that
 * is always a little too big puts every frame in one heap. Something that
 * interrupts now and then leaves most of them in the low heap and throws a
 * few a long way out. */
#define GAP_BUCKET_MS 5
#define GAP_BUCKETS 32
static uint16_t gaps[GAP_BUCKETS + 1];

/* A frame that runs a quarter past its own delay. Two panel periods rather
 * than one is not a slip at this rate; three is. */
#define SLIPPED_MS (FRAME_MS + FRAME_MS / 4)

static void frame_drawn(lv_event_t *event)
{
    (void)event;
    uint32_t now = lv_tick_get();
    if (drawn == 0) {
        began = now;
    } else {
        uint32_t gap = now - previous;
        if (gap > slowest) { slowest = gap; slowest_at = drawn; }
        if (gap > SLIPPED_MS) slipped++;
        unsigned bucket = gap / GAP_BUCKET_MS;
        if (bucket > GAP_BUCKETS) bucket = GAP_BUCKETS;
        gaps[bucket]++;
    }
    previous = now;
    drawn++;
}

static void report(void)
{
    if (drawn < 2) return;
    uint32_t ran = previous - began;
    LV_LOG_USER("boot animation: %u frames in %u ms, %u ms a frame against "
                "%u asked, slowest %u ms at frame %u, %u past %u ms",
                (unsigned)drawn, (unsigned)ran,
                (unsigned)(ran / (drawn - 1)), (unsigned)FRAME_MS,
                (unsigned)slowest, (unsigned)slowest_at,
                (unsigned)slipped, (unsigned)SLIPPED_MS);

    /* The heaps, as milliseconds against the count of frames in them. The
     * last bucket carries a plus, because it holds everything above where
     * the buckets end. */
    char line[220];
    line[0] = '\0';
    size_t at = 0;
    for (unsigned bucket = 0; bucket <= GAP_BUCKETS; bucket++) {
        if (gaps[bucket] == 0) continue;
        int put = snprintf(line + at, sizeof(line) - at, "%s%u%s:%u",
                           at ? "  " : "", bucket * GAP_BUCKET_MS,
                           bucket == GAP_BUCKETS ? "+" : "",
                           (unsigned)gaps[bucket]);
        if (put < 0 || (size_t)put >= sizeof(line) - at) break;
        at += (size_t)put;
    }
    LV_LOG_USER("boot animation gaps, ms:frames   %s", line);
}

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
    report();
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
    drawn = began = previous = slowest = slowest_at = slipped = 0;
    for (unsigned i = 0; i <= GAP_BUCKETS; i++) gaps[i] = 0;

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
    lv_obj_add_event_cb(picture, frame_drawn, LV_EVENT_DRAW_POST_END, NULL);
    lv_obj_move_foreground(cover);
}
