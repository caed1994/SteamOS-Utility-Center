// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The startup animation, played on a real LVGL rather than described.
//
// It reads the same file the firmware embeds. A check that holds its own
// picture proves that a picture plays, not that ours does.
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "lvgl.h"
#include "panel_boot.h"

#define SCREEN 480
static double origin;
static double now_ms(void)
{
    struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);
    return t.tv_sec*1000.0+t.tv_nsec/1e6;
}
static uint32_t tick_get(void){return (uint32_t)(now_ms()-origin);}
/* Nothing leaves this program, but a flush that never reports itself done
 * leaves lv_timer_handler waiting for one for ever. */
static void flushed(lv_display_t *display,const lv_area_t *area,uint8_t *pixels)
{
    (void)area;(void)pixels;lv_display_flush_ready(display);
}
static uint8_t *slurp(const char *path,size_t *size)
{
    FILE *file=fopen(path,"rb");
    if(!file){fprintf(stderr,"check_boot: cannot read %s\n",path);exit(1);}
    fseek(file,0,SEEK_END);*size=(size_t)ftell(file);fseek(file,0,SEEK_SET);
    uint8_t *bytes=malloc(*size);
    assert(bytes && fread(bytes,1,*size,file)==*size);
    fclose(file);return bytes;
}
/* Whether something the size of the screen is over it. The same question
 * check_power asks about a sleeping panel. */
static bool covered(void)
{
    lv_obj_t *active=lv_screen_active();
    for(uint32_t i=0;i<lv_obj_get_child_count(active);i++){
        lv_obj_t *child=lv_obj_get_child(active,i);
        if(lv_obj_has_flag(child,LV_OBJ_FLAG_HIDDEN))continue;
        if(lv_obj_get_width(child)>=SCREEN && lv_obj_get_height(child)>=SCREEN)
            return true;
    }
    return false;
}
/* Run the timers for a while, or until the animation goes. */
static double run_until_done(double limit_ms)
{
    double started=now_ms();
    while(now_ms()-started<limit_ms){
        lv_timer_handler();
        if(!panel_boot_playing())break;
        usleep(1000);
    }
    return now_ms()-started;
}
int main(int argc,char **argv)
{
    const char *path=argc>1?argv[1]:"firmware/companion/main/assets/boot-steam.gif";
    size_t size;uint8_t *image=slurp(path,&size);

    lv_init();
    origin=now_ms();
    lv_tick_set_cb(tick_get);
    static uint8_t pixels[SCREEN*SCREEN*4];
    lv_display_t *screen=lv_display_create(SCREEN,SCREEN);
    lv_display_set_buffers(screen,pixels,NULL,sizeof pixels,
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(screen,flushed);
    lv_obj_update_layout(lv_screen_active());

    /* Nothing to play is a panel that starts without an animation. */
    panel_boot_show(NULL,size);assert(!panel_boot_playing());
    panel_boot_show(image,0);assert(!panel_boot_playing());
    assert(!covered());

    /* It covers the screen the moment it is asked to. */
    panel_boot_show(image,size);
    assert(panel_boot_playing());
    lv_obj_update_layout(lv_screen_active());
    assert(covered());

    /* A second ask while one plays does not stack a second cover. */
    uint32_t children=lv_obj_get_child_count(lv_screen_active());
    panel_boot_show(image,size);
    assert(lv_obj_get_child_count(lv_screen_active())==children);

    /* It plays and then it goes, on its own, and it does not come back. */
    double spent=run_until_done(20000);
    assert(!panel_boot_playing());
    assert(!covered());
    /* The clip is about three seconds. A cover that goes at once played
     * nothing, and one that never goes is a black panel. */
    assert(spent>1500 && spent<12000);
    lv_timer_handler();assert(!panel_boot_playing());

    /* A touch takes it away, because somebody touching the panel is not
     * waiting for a logo. */
    panel_boot_show(image,size);assert(panel_boot_playing());
    lv_obj_update_layout(lv_screen_active());
    lv_obj_t *cover=lv_obj_get_child(lv_screen_active(),
                                     (int32_t)lv_obj_get_child_count(lv_screen_active())-1);
    assert(lv_obj_has_flag(cover,LV_OBJ_FLAG_CLICKABLE));
    lv_obj_send_event(cover,LV_EVENT_CLICKED,NULL);
    /* The panel is free from this moment, and the object goes a little
     * later. That is the whole point of the delete being asynchronous:
     * this line runs inside the event that LVGL sent to the cover, and
     * LVGL reads the object again after the event returns. So the cover is
     * still on the screen right here, and gone after one turn of the
     * handler. Nothing but the touch path can see this gap, because every
     * other way out of the animation already runs inside a handler. */
    assert(!panel_boot_playing());
    assert(covered());
    lv_timer_handler();
    assert(!covered());

    /* A cleaned screen takes the cover with it, and the pointer to it goes
     * at the same time. Without that, the next show returns at once on a
     * pointer to something deleted, and the panel never plays again. */
    panel_boot_show(image,size);assert(panel_boot_playing());
    lv_obj_clean(lv_screen_active());
    assert(!panel_boot_playing());
    panel_boot_show(image,size);assert(panel_boot_playing());
    lv_obj_update_layout(lv_screen_active());
    assert(covered());

    printf("OK: startup animation of %zu bytes covers the screen, plays for "
           "%.1f s, goes on its own, goes on a touch, and survives a "
           "cleaned screen.\n",size,spent/1000.0);
    return 0;
}
