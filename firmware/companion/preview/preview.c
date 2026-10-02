// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <stdio.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
static uint8_t pixels[480*480*4];
static void flush(lv_display_t *display,const lv_area_t *area,uint8_t *data){(void)area;(void)data;lv_display_flush_ready(display);}
/* The band is the one object that scrolls sideways and holds the pages. */
static lv_obj_t *band_in(lv_obj_t *root)
{
    if(lv_obj_get_scroll_dir(root)==LV_DIR_HOR&&lv_obj_get_child_count(root)==PANEL_PAGES)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){
        lv_obj_t *f=band_in(lv_obj_get_child(root,i));if(f)return f;
    }
    return NULL;
}
/* The label with that text, for a tap on what holds it. */
static lv_obj_t *find_label(lv_obj_t *root,const char *text)
{
    if(lv_obj_check_type(root,&lv_label_class)&&strcmp(lv_label_get_text(root),text)==0)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){
        lv_obj_t *found=find_label(lv_obj_get_child(root,i),text);
        if(found)return found;
    }
    return NULL;
}
int main(int argc,char **argv)
{
    lv_init();
    lv_display_t *d=lv_display_create(480,480);
    lv_display_set_color_format(d,LV_COLOR_FORMAT_XRGB8888);
    lv_display_set_buffers(d,pixels,NULL,sizeof(pixels),LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(d,flush);
    /* A third word "de" draws the screen in German. */
    panel_settings_t settings={.brightness=70,.sound_volume=30,.touch_tones=false,
                               .language=argc>3&&strcmp(argv[3],"de")==0?PANEL_GERMAN:PANEL_ENGLISH};
    panel_ui_create(NULL,NULL,NULL,&settings);
    panel_state_t s={.wifi=true,.online=true,.volume=42,.cpu_temp=49,.gpu_temp=56,.gpu_watts=78};
    strcpy(s.host,"FractalMachine");
    /* Two controllers in the head, and four on their page: one charges and
     * one has no battery that anybody reports. "pads" opens that page, and
     * "pad" is the head with one controller. */
    static const panel_pad_t pads[]={{"Steam Controller 1",93,false},
                                      {"PlayStation Controller",100,true},
                                      {"Steam Controller 2",8,false},
                                      {"8BitDo Ultimate 2C Wireless Controller",-1,false}};
    memcpy(s.pads,pads,sizeof pads);s.pad_count=4;
    if(argc>2&&strcmp(argv[2],"pad")==0)s.pad_count=1;
    /* The page of the PC, as the board answers. "pc" opens it and "pc-end"
     * scrolls it to its end. */
    static const panel_pc_t pc={.os="SteamOS 3.9.2",.build="20260925.100",.channel="Beta",
        .kernel="7.2.7-valve1-1",.cpu="AMD Ryzen 7 7800X3D",
        .gpu="AMD Radeon RX 9070 XT",.ip="192.168.178.42",.mac="a8:a1:59:3c:21:7e",
        .uptime_s=2*86400+4*3600+13*60,.cpu_load=12,.fan_rpm=1180,.gpu_fan_rpm=0,
        .memory_used=9876543210ULL,.memory_total=33554432000ULL,.link=PANEL_LINK_WIRED,
        .link_mbit=2500,.answer_ms=38};
    s.pc=pc;
    /* The sensors of the board's machine to choose from. "cpu-menu" and
     * "gpu-menu" open the choice, by a tap on the tile. */
    static const panel_sensor_t cpu_sensors[]={{"k10temp/Tctl","Tctl",49},{"k10temp/Tccd1","CCD 1",47}};
    static const panel_sensor_t gpu_sensors[]={{"amdgpu/edge","Edge",56},
        {"amdgpu/junction","Junction (Hotspot)",68},{"amdgpu/mem","VRAM",60}};
    memcpy(s.cpu_sensors,cpu_sensors,sizeof cpu_sensors);s.cpu_sensor_count=2;
    memcpy(s.gpu_sensors,gpu_sensors,sizeof gpu_sensors);s.gpu_sensor_count=3;
    /* The panel itself, and an update the PC offers. "self" opens its
     * page, "self-low" is a battery too low for the update, "self-failed"
     * an update that failed, and "updating" the screen while one writes. */
    static const panel_self_t self={.version="61-1eec536",.ssid="FRITZ!Box 7590",
        .ip="192.168.178.57",.mac="24:58:7c:12:ab:cd",.server="192.168.178.42:8765",
        .rssi=-58,.uptime_s=3*3600+12*60,.heap_free=142*1024,.psram_free=6400*1024};
    s.self=self;
    snprintf(s.update.offered,sizeof s.update.offered,"64-2b7f0c1");
    if(argc>2&&strcmp(argv[2],"self-failed")==0){
        s.update.phase=PANEL_UPDATE_FAILED;s.update.failure=TXT_UPDATE_BROKEN;
    }
    if(argc>2&&strcmp(argv[2],"updating")==0){s.update.phase=PANEL_UPDATE_RUNNING;s.update.percent=45;}
    /* The battery of the panel itself, for the corner of the main screen.
     * A real board shows this only once its power chip answers. */
    s.esp_supply=PANEL_SUPPLY_BATTERY;s.esp_battery=87;
    if(argc>2&&strcmp(argv[2],"self-low")==0){s.esp_battery=12;s.esp_charging=false;}
    if(argc>2&&strcmp(argv[2],"offline")==0){s.online=false;s.wifi=false;}
    /* Offline, with an address to wake the PC at. The control card shows
     * its other face here. See panel_wol.c. */
    if(argc>2&&strcmp(argv[2],"wake")==0){
        s.online=false;s.can_wake=true;
    }
    if(argc>2&&strcmp(argv[2],"setup")==0){s.setup=true;strcpy(s.setup_ssid,"SteamOS-Panel-3A12");strcpy(s.setup_password,"ABCD2345EFGH");}
    /* The third page, with a game on it and its achievements under the
     * name. */
    if(argc>2&&strcmp(argv[2],"playing")==0){
        strcpy(s.playing,"DragonSword : Awakening");
        s.achievements_done=49;s.achievements_total=60;
    }
    /* The fourth page, on a Wednesday at 18:42, with a timer of 25
     * minutes set. "timer" has it running for 90 seconds, "alarm" has it
     * ringing, and "noclock" is a panel the network has not set yet. */
    bool clock=argc>2&&(strcmp(argv[2],"clock")==0||strcmp(argv[2],"timer")==0||
                        strcmp(argv[2],"alarm")==0||strcmp(argv[2],"noclock")==0);
    if(clock&&strcmp(argv[2],"noclock")!=0){
        s.clock_set=true;s.hour=18;s.minute=42;s.weekday=3;s.day=1;s.month=10;
    }
    panel_ui_update(&s);
    if(argc>2&&strcmp(argv[2],"playing")==0){
        lv_obj_t *band=band_in(lv_screen_active());
        if(band){
            lv_obj_update_layout(band);
            lv_obj_scroll_to_view(lv_obj_get_child(band,2),LV_ANIM_OFF);
        }
    }
    if(clock){
        lv_obj_t *band=band_in(lv_screen_active());
        if(band){
            lv_obj_update_layout(band);
            lv_obj_scroll_to_view(lv_obj_get_child(band,3),LV_ANIM_OFF);
        }
        /* The + of the timer, pressed by its events: 5, then 4 times 5. */
        lv_obj_t *card=lv_obj_get_child(lv_obj_get_child(band,3),1);
        lv_obj_t *plus=lv_obj_get_child(card,1);
        lv_obj_send_event(plus,LV_EVENT_LONG_PRESSED,NULL);
        for(int i=0;i<16;i++){lv_tick_inc(100);lv_obj_send_event(plus,LV_EVENT_LONG_PRESSED_REPEAT,NULL);}
        if(strcmp(argv[2],"timer")==0||strcmp(argv[2],"alarm")==0){
            lv_obj_send_event(lv_obj_get_child(card,3),LV_EVENT_CLICKED,NULL);
            lv_tick_inc(90*1000);
            panel_ui_timer_tick();
        }
        if(strcmp(argv[2],"alarm")==0){
            lv_tick_inc(25*60*1000);
            panel_ui_timer_tick();
        }
    }
    if(argc>2&&strcmp(argv[2],"pads")==0)panel_ui_pads_open();
    if(argc>2&&strncmp(argv[2],"self",4)==0)panel_ui_self_open();
    if(argc>2&&strstr(argv[2],"-menu")){
        const char *reading=strncmp(argv[2],"gpu",3)==0?"56 °C":"49 °C";
        lv_obj_t *value=find_label(lv_screen_active(),reading);
        if(value)lv_obj_send_event(lv_obj_get_parent(value),LV_EVENT_CLICKED,NULL);
    }
    if(argc>2&&strncmp(argv[2],"pc",2)==0)panel_ui_pc_open();
    if(argc>2&&strcmp(argv[2],"pc-end")==0){
        lv_obj_t *page=lv_obj_get_child(lv_screen_active(),-1);
        lv_obj_update_layout(page);
        lv_obj_scroll_to_y(page,LV_COORD_MAX,LV_ANIM_OFF);
    }
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
