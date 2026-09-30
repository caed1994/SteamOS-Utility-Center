// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <stdio.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
static uint8_t pixels[480*480*4];
static void flush(lv_display_t *display,const lv_area_t *area,uint8_t *data){(void)area;(void)data;lv_display_flush_ready(display);}
int main(int argc,char **argv)
{
    lv_init();
    lv_display_t *d=lv_display_create(480,480);
    lv_display_set_color_format(d,LV_COLOR_FORMAT_XRGB8888);
    lv_display_set_buffers(d,pixels,NULL,sizeof(pixels),LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(d,flush);
    panel_settings_t settings={.brightness=70,.sound_volume=30,.touch_tones=false};
    panel_ui_create(NULL,NULL,NULL,&settings);
    panel_state_t s={.wifi=true,.online=true,.battery=85,.volume=42,.cpu_temp=49,.gpu_temp=56,.gpu_watts=78};
    /* charging is a flag and not a word any more, and this still wrote a
     * word into it. Nothing built this file, so nothing said so. The job in
     * .github/workflows/companion-firmware.yml builds and runs it now. */
    s.charging=false;
    strcpy(s.host,"FractalMachine");strcpy(s.controller,"PlayStation Controller");
    strcpy(s.message,"Up to date");
    /* The battery of the panel itself, for the corner of the main screen.
     * A real board shows this only once its power chip answers. */
    s.esp_supply=PANEL_SUPPLY_BATTERY;s.esp_battery=87;
    if(argc>2&&strcmp(argv[2],"offline")==0){s.online=false;s.wifi=false;strcpy(s.message,"Joining the network");}
    /* Offline, with an address to wake the PC at. The control card shows
     * its other face here. See panel_wol.c. */
    if(argc>2&&strcmp(argv[2],"wake")==0){
        s.online=false;s.can_wake=true;strcpy(s.message,"No answer from the PC");
    }
    if(argc>2&&strcmp(argv[2],"setup")==0){s.setup=true;strcpy(s.setup_ssid,"SteamOS-Panel-3A12");strcpy(s.setup_password,"ABCD2345EFGH");}
    panel_ui_update(&s);
    if(argc>2&&strcmp(argv[2],"confirm")==0)panel_ui_confirm(PANEL_POWEROFF);
    if(argc>2&&strncmp(argv[2],"settings",8)==0)panel_ui_settings_open();
    /* The settings scroll, and the end of them is a page of its own to
     * look at. The page is the last child of the screen. */
    if(argc>2&&strcmp(argv[2],"settings-end")==0){
        lv_obj_t *page=lv_obj_get_child(lv_screen_active(),-1);
        lv_obj_update_layout(page);
        lv_obj_scroll_to_y(page,LV_COORD_MAX,LV_ANIM_OFF);
    }
    lv_refr_now(d);
    FILE *f=fopen(argc>1?argv[1]:"preview.ppm","wb");if(!f)return 1;
    fprintf(f,"P6\n480 480\n255\n");
    for(int i=0;i<480*480;i++){uint8_t rgb[]={pixels[i*4+2],pixels[i*4+1],pixels[i*4]};fwrite(rgb,1,3,f);}
    fclose(f);return 0;
}
