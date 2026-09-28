// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_ui_sleep.h"
void panel_ui_sleep(lv_display_t *screen,lv_indev_t *input,bool sleep)
{
    lv_timer_t *refresh=lv_display_get_refr_timer(screen);
    lv_timer_t *touch=lv_indev_get_read_timer(input);
    if(sleep){
        lv_indev_reset(input,NULL);
        lv_indev_enable(input,false);
        if(touch)lv_timer_pause(touch);
        lv_display_enable_invalidation(screen,false);
        if(refresh)lv_timer_pause(refresh);
    }else{
        lv_display_enable_invalidation(screen,true);
        if(refresh)lv_timer_resume(refresh);
        lv_obj_invalidate(lv_display_get_screen_active(screen));
        lv_refr_now(screen);
        lv_indev_reset(input,NULL);
        lv_indev_wait_release(input);
        lv_indev_enable(input,true);
        if(touch)lv_timer_resume(touch);
    }
}
