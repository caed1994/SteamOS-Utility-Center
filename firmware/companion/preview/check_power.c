// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "panel_key.h"
#include "panel_fonts.h"
#include "panel_ui_sleep.h"
/* For the room LVGL gives the letters of a label past its box. */
#include "src/core/lv_obj_draw_private.h"
LV_FONT_DECLARE(panel_clock_font);
static bool held;
static unsigned reads, clicks;
static uint8_t pixels[480*480*4];
static void read_touch(lv_indev_t *input,lv_indev_data_t *data)
{
    (void)input;reads++;data->point.x=40;data->point.y=40;
    data->state=held?LV_INDEV_STATE_PRESSED:LV_INDEV_STATE_RELEASED;
}
static void clicked(lv_event_t *event){(void)event;clicks++;}
static unsigned flushes;
static void flush(lv_display_t *d,const lv_area_t *area,uint8_t *data){(void)area;(void)data;flushes++;lv_display_flush_ready(d);}
/* What the display was asked to draw again: how many areas, and the
 * smallest box around all of them. */
static unsigned dirty;
static lv_area_t dirty_box;
/* A refresh asks the same event how to round the rows it draws, with an
 * area of its own that is no request to draw. Those are not counted. */
static bool refreshing;
static void refresh_edge(lv_event_t *event)
{
    refreshing=lv_event_get_code(event)==LV_EVENT_REFR_START;
}
static void invalidated(lv_event_t *event)
{
    const lv_area_t *a=lv_event_get_param(event);
    if(!a||refreshing)return;
    if(dirty++==0)dirty_box=*a;
    else{
        if(a->x1<dirty_box.x1)dirty_box.x1=a->x1;
        if(a->y1<dirty_box.y1)dirty_box.y1=a->y1;
        if(a->x2>dirty_box.x2)dirty_box.x2=a->x2;
        if(a->y2>dirty_box.y2)dirty_box.y2=a->y2;
    }
}
static bool inside(const lv_area_t *in,const lv_area_t *box)
{
    return in->x1>=box->x1&&in->y1>=box->y1&&in->x2<=box->x2&&in->y2<=box->y2;
}
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
/* The cover itself, shown or not: the child of the screen as large as it. */
static lv_obj_t *cover_of(lv_display_t *screen)
{
    lv_obj_t *active=lv_display_get_screen_active(screen);
    for(uint32_t i=0;i<lv_obj_get_child_count(active);i++){
        lv_obj_t *child=lv_obj_get_child(active,i);
        if(lv_obj_get_width(child)>=480 && lv_obj_get_height(child)>=480)return child;
    }
    return NULL;
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
    /* Partial, as the board draws only what changed: a full refresh would
     * hide what the clock below asks to draw again. */
    lv_display_set_buffers(screen,pixels,NULL,sizeof(pixels),LV_DISPLAY_RENDER_MODE_PARTIAL);
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
    /* A second wake changes nothing, and a sleep after it still takes the
     * invalidation away: LVGL counts each switch of it. */
    panel_ui_sleep(screen,input,false);panel_ui_sleep(screen,input,false);
    assert(lv_display_is_invalidation_enabled(screen));
    panel_ui_sleep(screen,input,true);assert(!lv_display_is_invalidation_enabled(screen));
    panel_ui_sleep(screen,input,true);assert(!lv_display_is_invalidation_enabled(screen));
    panel_ui_sleep(screen,input,false);assert(lv_display_is_invalidation_enabled(screen));
    /* A screen cleaned under the cover, which is what a change of language
     * does. Holding the old pointer past that is a use of a deleted object
     * at the next sleep. See panel_ui_sleep_reset. */
    panel_ui_sleep(screen,input,false);
    lv_obj_clean(lv_screen_active());
    panel_ui_sleep_reset();
    panel_ui_sleep(screen,input,true);assert(covered(screen));
    panel_ui_sleep(screen,input,false);assert(!covered(screen));

    /* The clock on the cover. Set while the panel is awake, it draws
     * nothing: the cover is hidden. */
    lv_display_add_event_cb(screen,invalidated,LV_EVENT_INVALIDATE_AREA,NULL);
    lv_display_add_event_cb(screen,refresh_edge,LV_EVENT_REFR_START,NULL);
    lv_display_add_event_cb(screen,refresh_edge,LV_EVENT_REFR_READY,NULL);
    dirty=0;flushes=0;
    panel_ui_sleep_clock(screen,"07:05","Thursday, 8 October");
    lv_refr_now(screen);
    assert(dirty==0&&flushes==0);
    /* The sleep shows it: the time over the date, both across the screen
     * and together in its middle, in the font of the clock page. */
    panel_ui_sleep(screen,input,true);
    lv_obj_t *black=cover_of(screen);assert(black&&lv_obj_get_child_count(black)==2);
    lv_obj_t *hours=lv_obj_get_child(black,0),*date=lv_obj_get_child(black,1);
    assert(strcmp(lv_label_get_text(hours),"07:05")==0);
    assert(strcmp(lv_label_get_text(date),"Thursday, 8 October")==0);
    assert(lv_obj_get_style_text_font(hours,0)==&panel_clock_font);
    assert(lv_obj_get_style_text_font(date,0)==&panel_font_24);
    assert(lv_obj_get_style_text_align(hours,0)==LV_TEXT_ALIGN_CENTER);
    lv_area_t time_at,date_at;
    lv_obj_get_coords(hours,&time_at);lv_obj_get_coords(date,&date_at);
    assert(time_at.x1==0&&time_at.x2==479&&date_at.x1==0&&date_at.x2==479);
    assert(time_at.y2<date_at.y1);
    int32_t above=time_at.y1,below=479-date_at.y2;
    assert(above-below<=1&&below-above<=1);
    /* Where each line draws: its box and the room LVGL gives its letters
     * past it. That is still the line and nothing beside it. */
    lv_area_t time_draw=time_at,date_draw=date_at;
    lv_area_increase(&time_draw,lv_obj_get_ext_draw_size(hours),lv_obj_get_ext_draw_size(hours));
    lv_area_increase(&date_draw,lv_obj_get_ext_draw_size(date),lv_obj_get_ext_draw_size(date));
    /* The same minute again, five times a second in a sleep: nothing is
     * asked of the display. */
    dirty=0;flushes=0;
    for(int i=0;i<300;i++)panel_ui_sleep_clock(screen,"07:05","Thursday, 8 October");
    assert(dirty==0&&flushes==0&&!lv_display_is_invalidation_enabled(screen));
    /* A new minute: one draw, of the line of the time and nothing else,
     * and the sleeping display takes no invalidation after it. */
    panel_ui_sleep_clock(screen,"07:06","Thursday, 8 October");
    assert(flushes==1&&dirty>0&&inside(&dirty_box,&time_draw));
    assert(!lv_display_is_invalidation_enabled(screen));
    assert(strcmp(lv_label_get_text(hours),"07:06")==0);
    /* Nothing else that changes in a sleep reaches the screen. */
    dirty=0;flushes=0;
    lv_obj_invalidate(lv_screen_active());lv_refr_now(screen);
    assert(dirty==0&&flushes==0);
    /* A new day: both lines, and nothing outside them. */
    lv_area_t both={0,time_draw.y1,479,date_draw.y2};
    panel_ui_sleep_clock(screen,"00:00","Friday, 9 October");
    assert(flushes>=1&&inside(&dirty_box,&both)&&dirty_box.y2>time_draw.y2);
    /* No clock: black again. */
    panel_ui_sleep_clock(screen,"","");
    assert(lv_label_get_text(hours)[0]==0&&lv_label_get_text(date)[0]==0);
    /* The wake takes the cover away, clock and all, and draws everything. */
    panel_ui_sleep_clock(screen,"08:00","Thursday, 8 October");
    panel_ui_sleep(screen,input,false);
    assert(!covered(screen)&&lv_display_is_invalidation_enabled(screen));
    /* After a clean of the screen, the next cover has its clock again. */
    lv_obj_clean(lv_screen_active());panel_ui_sleep_reset();
    panel_ui_sleep_clock(screen,"09:30","Thursday, 8 October");
    /* Made by the clock while the panel is awake, the cover waits hidden. */
    lv_obj_update_layout(lv_screen_active());
    assert(cover_of(screen)&&!covered(screen));
    panel_ui_sleep(screen,input,true);
    black=cover_of(screen);assert(black&&lv_obj_get_child_count(black)==2);
    assert(strcmp(lv_label_get_text(lv_obj_get_child(black,0)),"09:30")==0);
    panel_ui_sleep(screen,input,false);

    puts("OK: debounce, long hold, held-at-boot, I2C recovery, timer wrap; 100 standby cycles block dark/held touch, restore fresh clicks, and cover the screen while it sleeps, with a clock on it that draws one line a minute.");
    return 0;
}
