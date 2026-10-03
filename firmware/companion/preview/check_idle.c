// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
static unsigned invalidations;
/* An area of the screen, and the redraws that touched it. */
static lv_area_t watched;
static unsigned watched_hits;
static void invalidated(lv_event_t *event)
{
    invalidations++;
    const lv_area_t *a=lv_event_get_param(event);
    if(a&&a->x1<=watched.x2&&watched.x1<=a->x2&&a->y1<=watched.y2&&watched.y1<=a->y2)watched_hits++;
}
/* The band is the one object on the screen that scrolls sideways. */
static lv_obj_t *find_band(lv_obj_t *root)
{
    if(lv_obj_get_scroll_dir(root)==LV_DIR_HOR&&lv_obj_get_child_count(root)==PANEL_PAGES)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){lv_obj_t *f=find_band(lv_obj_get_child(root,i));if(f)return f;}
    return NULL;
}
static void flush(lv_display_t *display,const lv_area_t *area,uint8_t *data){(void)area;(void)data;lv_display_flush_ready(display);}
static uint8_t pixels[480*480*4];
int main(void)
{
    lv_init();
    lv_display_t *display=lv_display_create(480,480);
    lv_display_set_color_format(display,LV_COLOR_FORMAT_XRGB8888);
    lv_display_set_buffers(display,pixels,NULL,sizeof(pixels),LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display,flush);
    panel_settings_t settings={.brightness=70,.sound_volume=30};
    panel_ui_create(NULL,NULL,NULL,&settings);
    panel_state_t state={.online=true,.wifi=true,.volume=42,.cpu_temp=49,.gpu_temp=56,.gpu_watts=78};
    strcpy(state.message,"Status aktuell");
    panel_ui_update(&state);lv_refr_now(display);
    lv_display_add_event_cb(display,invalidated,LV_EVENT_INVALIDATE_AREA,NULL);
    for(int i=0;i<10000;i++){panel_ui_update(&state);lv_obj_update_layout(lv_screen_active());}
    assert(invalidations==0);
    state.volume=43;panel_ui_update(&state);lv_obj_update_layout(lv_screen_active());
    assert(invalidations>0);lv_refr_now(display);invalidations=0;
    for(int i=0;i<10000;i++)panel_ui_update(&state);
    assert(invalidations==0);
    /* The page of the CPU on the screen. A status that changes nothing on
     * it redraws nothing on it: its buttons take a colour, and its lines a
     * text, only when that changes. A change of the profile redraws it. */
    lv_obj_t *page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_CPU);
    state.cpu_known=state.cpu_here=true;
    strcpy(state.cpu_profile,"balanced");
    state.cpu_offers=(uint8_t)((1u<<PANEL_CPU_PROFILES)-1);
    strcpy(state.cpu_governor,"powersave");strcpy(state.cpu_epp,"balance_performance");
    strcpy(state.cpu_driver,"amd-pstate-epp");
    panel_ui_update(&state);
    lv_obj_scroll_to_view(page,LV_ANIM_OFF);
    lv_obj_update_layout(lv_screen_active());lv_refr_now(display);
    lv_obj_get_coords(page,&watched);
    watched_hits=0;
    for(int i=0;i<10;i++){state.cpu_temp=50+i;panel_ui_update(&state);lv_obj_update_layout(lv_screen_active());}
    assert(watched_hits==0);
    strcpy(state.cpu_profile,"performance");panel_ui_update(&state);lv_obj_update_layout(lv_screen_active());
    assert(watched_hits>0);
    lv_refr_now(display);
    /* New settings page must receive a previously cached audio failure state. */
    state.sound_error=true;panel_ui_update(&state);lv_refr_now(display);
    panel_ui_settings_open();lv_refr_now(display);invalidations=0;
    panel_ui_update(&state);lv_obj_update_layout(lv_screen_active());assert(invalidations>0);
    puts("OK: 20000 unchanged updates cause no invalidation; changes still redraw; the page of the CPU redraws only for its own changes; settings state refreshes.");
    return 0;
}
