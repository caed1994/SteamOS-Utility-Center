// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
static unsigned invalidations;
static void invalidated(lv_event_t *event){(void)event;invalidations++;}
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
    panel_state_t state={.online=true,.wifi=true,.battery=85,.volume=42,.cpu_temp=49,.gpu_temp=56,.gpu_watts=78};
    strcpy(state.message,"Status aktuell");
    panel_ui_update(&state);lv_refr_now(display);
    lv_display_add_event_cb(display,invalidated,LV_EVENT_INVALIDATE_AREA,NULL);
    for(int i=0;i<10000;i++){panel_ui_update(&state);lv_obj_update_layout(lv_screen_active());}
    assert(invalidations==0);
    state.volume=43;panel_ui_update(&state);lv_obj_update_layout(lv_screen_active());
    assert(invalidations>0);lv_refr_now(display);invalidations=0;
    for(int i=0;i<10000;i++)panel_ui_update(&state);
    assert(invalidations==0);
    /* New settings page must receive a previously cached audio failure state. */
    state.sound_error=true;panel_ui_update(&state);lv_refr_now(display);
    panel_ui_settings_open();lv_refr_now(display);invalidations=0;
    panel_ui_update(&state);lv_obj_update_layout(lv_screen_active());assert(invalidations>0);
    puts("OK: 20000 unchanged updates cause no invalidation; changes still redraw; settings state refreshes.");
    return 0;
}
