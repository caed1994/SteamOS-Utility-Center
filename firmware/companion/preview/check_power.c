// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include "panel_key.h"
#include "panel_ui_sleep.h"
static bool held;
static unsigned reads, clicks;
static uint8_t pixels[480*480*4];
static void read_touch(lv_indev_t *input,lv_indev_data_t *data)
{
    (void)input;reads++;data->point.x=40;data->point.y=40;
    data->state=held?LV_INDEV_STATE_PRESSED:LV_INDEV_STATE_RELEASED;
}
static void clicked(lv_event_t *event){(void)event;clicks++;}
static void flush(lv_display_t *d,const lv_area_t *area,uint8_t *data){(void)area;(void)data;lv_display_flush_ready(d);}
static void input_sample(lv_indev_t *input,bool press){held=press;lv_tick_inc(30);lv_indev_read(input);}
/* Whether something the size of the screen is over it and not hidden.
 * The backlight of this board cannot go dark, so a sleeping panel wears a
 * black cover instead and the screen looks switched off. */
static bool covered(lv_display_t *screen)
{
    lv_obj_t *active=lv_display_get_screen_active(screen);
    for(uint32_t i=0;i<lv_obj_get_child_count(active);i++){
        lv_obj_t *child=lv_obj_get_child(active,i);
        if(lv_obj_has_flag(child,LV_OBJ_FLAG_HIDDEN))continue;
        if(lv_obj_get_width(child)>=480 && lv_obj_get_height(child)>=480)
            return true;
    }
    return false;
}
static void arm(panel_key_t *key,uint32_t at)
{
    assert(!panel_key_sample(key,false,at));assert(!panel_key_sample(key,false,at+40));
}
static void tap(panel_key_t *key,uint32_t at)
{
    assert(!panel_key_sample(key,true,at));
    assert(!panel_key_sample(key,true,at+40));
    assert(!panel_key_sample(key,false,at+160));
    assert(panel_key_sample(key,false,at+200));
    assert(!panel_key_sample(key,false,at+220));
}
int main(void)
{
    panel_key_t key={0};arm(&key,0);tap(&key,100);tap(&key,400);
    /* Contact bounce cannot become a press. */
    assert(!panel_key_sample(&key,true,700));assert(!panel_key_sample(&key,false,720));
    assert(!panel_key_sample(&key,false,760));
    /* A long hold must never toggle, including on release. */
    assert(!panel_key_sample(&key,true,800));assert(!panel_key_sample(&key,true,840));
    for(uint32_t i=900;i<4000;i+=100)assert(!panel_key_sample(&key,true,i));
    assert(!panel_key_sample(&key,false,4000));assert(!panel_key_sample(&key,false,4040));
    panel_key_reset(&key);
    assert(!panel_key_sample(&key,true,0));assert(!panel_key_sample(&key,true,100));
    assert(!panel_key_sample(&key,false,200));assert(!panel_key_sample(&key,false,240));
    tap(&key,300);
    /* Lost I2C reads reset the gesture instead of producing a phantom release. */
    panel_key_reset(&key);arm(&key,1000);assert(!panel_key_sample(&key,true,1100));
    assert(!panel_key_sample(&key,true,1140));panel_key_reset(&key);arm(&key,1200);tap(&key,1300);
    panel_key_reset(&key);arm(&key,UINT32_MAX-200);tap(&key,UINT32_MAX-100);

    lv_init();lv_display_t *screen=lv_display_create(480,480);
    lv_display_set_color_format(screen,LV_COLOR_FORMAT_XRGB8888);
    lv_display_set_buffers(screen,pixels,NULL,sizeof(pixels),LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(screen,flush);
    lv_obj_t *button=lv_button_create(lv_screen_active());lv_obj_set_pos(button,0,0);lv_obj_set_size(button,100,100);
    lv_obj_add_event_cb(button,clicked,LV_EVENT_CLICKED,NULL);lv_refr_now(screen);
    lv_indev_t *input=lv_indev_create();lv_indev_set_type(input,LV_INDEV_TYPE_POINTER);
    lv_indev_set_display(input,screen);lv_indev_set_read_cb(input,read_touch);
    input_sample(input,false);input_sample(input,true);input_sample(input,false);assert(clicks==1);
    for(unsigned cycle=0;cycle<100;cycle++){
        panel_ui_sleep(screen,input,true);assert(!lv_display_is_invalidation_enabled(screen));
        /* Painted before the drawing stopped, or the last frame stays on a
         * screen that cannot go dark. */
        assert(covered(screen));
        unsigned before=reads,prior_clicks=clicks;
        input_sample(input,true);input_sample(input,false);assert(reads==before && clicks==prior_clicks);
        held=true;panel_ui_sleep(screen,input,false);assert(lv_display_is_invalidation_enabled(screen));
        assert(!covered(screen));
        input_sample(input,true);input_sample(input,false);assert(clicks==prior_clicks);
        input_sample(input,true);input_sample(input,false);assert(clicks==prior_clicks+1);
    }
    /* Enter standby during an existing touch, then resume with the finger held. */
    input_sample(input,true);unsigned prior_clicks=clicks;
    panel_ui_sleep(screen,input,true);panel_ui_sleep(screen,input,false);
    input_sample(input,true);input_sample(input,false);assert(clicks==prior_clicks);
    /* A screen cleaned under the cover, which is what a change of language
     * does. Holding the old pointer past that is a use of a deleted object
     * at the next sleep. See panel_ui_sleep_reset. */
    panel_ui_sleep(screen,input,false);
    lv_obj_clean(lv_screen_active());
    panel_ui_sleep_reset();
    panel_ui_sleep(screen,input,true);assert(covered(screen));
    panel_ui_sleep(screen,input,false);assert(!covered(screen));

    puts("OK: debounce, long hold, held-at-boot, I2C recovery, timer wrap; 100 standby cycles block dark/held touch, restore fresh clicks, and cover the screen while it sleeps.");
    return 0;
}
