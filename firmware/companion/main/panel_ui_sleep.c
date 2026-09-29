// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_ui_sleep.h"

/* The black cover that a sleeping panel wears.
 *
 * The backlight of this board cannot go dark. Four ways were tried and
 * measured, and the lowest it goes is the five percent that the converter
 * still regulates. See panel_display.c.
 *
 * So what is left is to leave nothing on the screen for that light to show.
 * Stopping the drawing keeps the last frame, and a dimmed page of buttons
 * is a panel that looks switched on. A black object over the whole screen,
 * painted before the drawing stops, is a panel that looks switched off.
 *
 * It is made once and kept. Making one at each sleep is an allocation on a
 * path that has to work when memory is short, and this is the path that
 * makes memory short less often. */
static lv_obj_t *cover;

void panel_ui_sleep_reset(void)
{
    /* The screen was cleaned under us, so the cover went with its children.
     * Holding the pointer past that is a use of a deleted object at the
     * next sleep. See panel_ui_create, which cleans the screen when the
     * language changes. */
    cover = NULL;
}

static lv_obj_t *cover_for(lv_display_t *screen)
{
    if (cover) return cover;
    cover = lv_obj_create(lv_display_get_screen_active(screen));
    if (!cover) return NULL;
    lv_obj_remove_style_all(cover);
    lv_obj_set_pos(cover, 0, 0);
    lv_obj_set_size(cover, lv_display_get_horizontal_resolution(screen),
                    lv_display_get_vertical_resolution(screen));
    lv_obj_set_style_bg_color(cover, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(cover, LV_OPA_COVER, 0);
    lv_obj_remove_flag(cover, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(cover, LV_OBJ_FLAG_CLICKABLE);
    return cover;
}

void panel_ui_sleep(lv_display_t *screen,lv_indev_t *input,bool sleep)
{
    lv_timer_t *refresh=lv_display_get_refr_timer(screen);
    lv_timer_t *touch=lv_indev_get_read_timer(input);
    if(sleep){
        lv_indev_reset(input,NULL);
        lv_indev_enable(input,false);
        if(touch)lv_timer_pause(touch);
        /* The cover goes on while the drawing still runs. After the pause
         * below, nothing reaches the screen. */
        lv_obj_t *black=cover_for(screen);
        if(black){
            lv_obj_remove_flag(black,LV_OBJ_FLAG_HIDDEN);
            lv_obj_move_foreground(black);
            lv_refr_now(screen);
        }
        lv_display_enable_invalidation(screen,false);
        if(refresh)lv_timer_pause(refresh);
    }else{
        lv_display_enable_invalidation(screen,true);
        if(refresh)lv_timer_resume(refresh);
        if(cover)lv_obj_add_flag(cover,LV_OBJ_FLAG_HIDDEN);
        lv_obj_invalidate(lv_display_get_screen_active(screen));
        lv_refr_now(screen);
        lv_indev_reset(input,NULL);
        lv_indev_wait_release(input);
        lv_indev_enable(input,true);
        if(touch)lv_timer_resume(touch);
    }
}
