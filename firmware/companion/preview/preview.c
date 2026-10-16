// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <stdio.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
#include "panel_ui_sleep.h"
#include "panel_frames.h"
#include "panel_taps.h"
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
/* The frames of a scroll at 16 MHz for the page of the panel, as its count
 * takes them: 184 frames that took two, three, two and four frames of the
 * panel in turn. */
static void count_frames(void)
{
    static const int64_t frames[][3]={{2000,29000,33150},{3000,31000,49725},
                                       {2000,30000,33150},{9000,45000,66300}};
    panel_frames_reset(&panel_frames);
    panel_frames_period(&panel_frames,16575);
    int64_t shown=1000000;
    panel_frames_begin(&panel_frames,shown-20000);
    panel_frames_drawn(&panel_frames,shown-10000);
    panel_frames_shown(&panel_frames,shown);
    for(unsigned i=0;i<184;i++){
        const int64_t *frame=frames[i%4];
        panel_frames_begin(&panel_frames,shown+frame[0]);
        panel_frames_drawn(&panel_frames,shown+frame[0]+frame[1]);
        shown+=frame[2];
        panel_frames_shown(&panel_frames,shown);
    }
}

/* The touches of a while for the page of the panel, as the count takes
 * them: taps, a swipe in five, two lost taps and one late read, and the
 * thresholds of a controller. The numbers of the controller are an
 * example, not those of the board. */
static void count_taps(void)
{
    panel_taps_reset(&panel_taps);
    uint32_t now=1000;
    panel_taps_press_t done;
    for(int i=0;i<40;i++){
        bool swipe=i%5==4,lost=i==7||i==23;
        panel_taps_read(&panel_taps,now,true,true,200,200,40-(i%9),&done);
        panel_taps_pressed(&panel_taps,true);
        now+=15;panel_taps_read(&panel_taps,now,true,true,swipe?260:203,201,38,&done);
        now+=15+(i==11?70:0);panel_taps_read(&panel_taps,now,true,true,swipe?340:204,201,36,&done);
        now+=15;panel_taps_read(&panel_taps,now,true,false,0,0,-1,&done);
        panel_taps_released(&panel_taps,swipe);
        if(!swipe&&!lost)panel_taps_clicked(&panel_taps);
        for(int idle=0;idle<4;idle++){now+=15;panel_taps_read(&panel_taps,now,true,false,0,0,-1,&done);}
    }
    panel_taps_chip=(panel_taps_chip_t){.known=true,.version='A',.touch_level=80,.leave_level=50,.report_ms=10};
}

/* The clock of LVGL here, which a mode moves on by hand. */
static uint32_t preview_ms;
static uint32_t preview_tick(void){return preview_ms;}

int main(int argc,char **argv)
{
    lv_init();
    lv_tick_set_cb(preview_tick);
    lv_display_t *d=lv_display_create(480,480);
    lv_display_set_color_format(d,LV_COLOR_FORMAT_XRGB8888);
    lv_display_set_buffers(d,pixels,NULL,sizeof(pixels),LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(d,flush);
    /* The words after the mode: "de" draws the screen in German, "light"
     * in the light theme, and the name of a colour in that accent, as
     * "panel.ppm settings de light orange". See panel_theme.h. */
    panel_settings_t settings={.brightness=70,.sound_volume=30,.touch_tones=false,.lift_wake=true,
                               .language=PANEL_ENGLISH};
    static const char *const accents[PANEL_ACCENTS]={"blue","cyan","green","yellow",
                                                     "orange","red","magenta","purple"};
    for(int i=3;i<argc;i++){
        if(strcmp(argv[i],"de")==0)settings.language=PANEL_GERMAN;
        else if(strcmp(argv[i],"light")==0)settings.theme=PANEL_THEME_LIGHT;
        else for(int a=0;a<PANEL_ACCENTS;a++)if(strcmp(argv[i],accents[a])==0)settings.accent=(panel_accent_t)a;
    }
    /* "pages-hidden" is that screen with the session hidden. */
    if(argc>2&&strcmp(argv[2],"pages-hidden")==0)settings.page_hidden=1u<<PANEL_PAGE_SESSION;
    /* "alarm-clock" is the clock page with an alarm at 6:30 from Monday to
     * Friday. "alarm-clock-set" has the layer that sets it open, and
     * "alarm-clock-ring" has it ringing. "standby-alarm" is the cover with
     * its next ring. */
    bool alarm_clock=argc>2&&(strncmp(argv[2],"alarm-clock",11)==0||
                              strcmp(argv[2],"standby-alarm")==0);
    if(alarm_clock)settings.alarm=panel_alarm_pack((panel_alarm_set_t){.on=true,.hour=6,.minute=30,
                                                                       .days=0x1F});
    /* The history of the page of the card, which main.c keeps in PSRAM. */
    static panel_history_t history;
    panel_history_reset(&history);
    panel_ui_history_use(&history);
    panel_ui_create(NULL,NULL,NULL,&settings);
    panel_state_t s={.wifi=true,.online=true,.volume=42,.cpu_temp=49,.gpu_temp=56,.gpu_watts=78,
                     .gpu_load=87,.gpu_mhz=2450,.gpu_mhz_max=2970,.vram_used=10522460160ULL,
                     .vram_total=17163091968ULL};
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
        .rssi=-58,.uptime_s=3*3600+12*60,.heap_free=142*1024,.psram_free=6400*1024,
        .heap_least=98*1024};
    s.self=self;
    snprintf(s.update.offered,sizeof s.update.offered,"64-2b7f0c1");
    /* "self-frames" shows the frames of a scroll with no update in the
     * way. The page counts them itself: see count_frames. */
    if(argc>2&&strcmp(argv[2],"self-frames")==0)s.update.offered[0]=0;
    if(argc>2&&strcmp(argv[2],"self-failed")==0){
        s.update.phase=PANEL_UPDATE_FAILED;s.update.failure=TXT_UPDATE_BROKEN;
    }
    if(argc>2&&strcmp(argv[2],"updating")==0){s.update.phase=PANEL_UPDATE_RUNNING;s.update.percent=45;}
    /* The battery of the panel itself, for the corner of the main screen.
     * A real board shows this only once its power chip answers. */
    s.esp_supply=PANEL_SUPPLY_BATTERY;s.esp_battery=87;
    /* The power chip in detail, as the page of the panel shows it:
     * charging at constant current and held by the input. "self-end"
     * scrolls the page to it. */
    s.esp_detail=(panel_power_detail_t){.vbat_mv=3984,.vbus_mv=5011,.vsys_mv=3714,
        .die_c=38,.phase=2,.held_current=true,.charge_ma=1000,.charge_mv=4200,.input_ma=1500};
    if(argc>2&&strcmp(argv[2],"self-low")==0){s.esp_battery=12;s.esp_charging=false;}
    if(argc>2&&strcmp(argv[2],"offline")==0){s.online=false;s.wifi=false;}
    /* Offline, with an address to wake the PC at. The control card shows
     * its other face here. See panel_wol.c. */
    if(argc>2&&strcmp(argv[2],"wake")==0){
        s.online=false;s.can_wake=true;
    }
    if(argc>2&&strcmp(argv[2],"setup")==0){s.setup=true;strcpy(s.setup_ssid,"SteamOS-Panel-3A12");strcpy(s.setup_password,"ABCD2345EFGH");}
    /* The pairing with the PC: "pair-search" looks for it, "pair-wait"
     * shows the code, "pair-not-found" found none, and "pair-expired"
     * waited for nobody. */
    if(argc>2&&strncmp(argv[2],"pair-",5)==0){
        s.pairing=strcmp(argv[2],"pair-search")==0?PANEL_PAIRING_SEARCH
                 :strcmp(argv[2],"pair-not-found")==0?PANEL_PAIRING_NOT_FOUND
                 :strcmp(argv[2],"pair-expired")==0?PANEL_PAIRING_EXPIRED:PANEL_PAIRING_WAIT;
        if(s.pairing==PANEL_PAIRING_WAIT){
            strcpy(s.pair_code,"482913");strcpy(s.pair_pc,"steamdeck");
            strcpy(s.pair_address,"192.168.178.20:8765");s.pair_can_cancel=true;
        }
    }
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
                        strcmp(argv[2],"alarm")==0||strcmp(argv[2],"noclock")==0||
                        strncmp(argv[2],"alarm-clock",11)==0);
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
        if(alarm_clock){
            /* The time of the page, or a Thursday at 6:30 for the ring. */
            panel_alarm_clock_t now={.known=true,.day=1,.weekday=3,.hour=18,.minute=42};
            if(strcmp(argv[2],"alarm-clock-ring")==0)
                now=(panel_alarm_clock_t){.known=true,.day=2,.weekday=4,.hour=6,.minute=30};
            panel_ui_alarm_clock_tick(&now);
            /* The button in the corner of the clock card, pressed by its
             * event. */
            lv_obj_t *clock_card=lv_obj_get_child(lv_obj_get_child(band,3),0);
            if(strcmp(argv[2],"alarm-clock-set")==0)
                lv_obj_send_event(lv_obj_get_child(clock_card,2),LV_EVENT_CLICKED,NULL);
        }
    }
    /* The fifth page. "card" is 35 minutes of the board's machine: ten
     * idle, then a game, with a minute in it in which the PC did not
     * answer. "card-60" shows the hour, "card-empty" is a panel that just
     * started, and "card-boost" has Cooling Boost on. Zero RPM is on in each. */
    if(argc>2&&strncmp(argv[2],"card",4)==0){
        s.boost_here=true;
        s.boost_on=strcmp(argv[2],"card-boost")==0;
        s.zero_rpm_here=s.zero_rpm_on=true;
        if(strcmp(argv[2],"card-empty")!=0){
            uint32_t seed=7;
            panel_state_t t=s;
            for(uint32_t now=0;now<=35u*60u*1000u;now+=1000){
                if(now%3000==0&&!(now>=19u*60u*1000u&&now<20u*60u*1000u)){
                    seed=seed*1103515245u+12345u;
                    int noise=(int)((seed>>16)%7)-3;
                    bool game=now>=10u*60u*1000u;
                    int warm=game?(int)((now-10u*60u*1000u)/60000u):0;
                    if(warm>8)warm=8;
                    t.cpu_temp=game?66+warm+noise/2:44+noise/3;
                    t.gpu_temp=game?54+warm+noise/2:39;
                    t.gpu_watts=game?262+noise*9+(int)((seed>>8)%30):24+noise;
                    t.answers++;
                }
                if(panel_history_due(&history,now))panel_ui_history_tick(&t,now);
            }
            s.cpu_temp=t.cpu_temp;s.gpu_temp=t.gpu_temp;s.gpu_watts=t.gpu_watts;
            s.answers=t.answers;
        }
        panel_ui_update(&s);
        lv_obj_t *band=band_in(lv_screen_active());
        if(band){
            lv_obj_update_layout(band);
            lv_obj_scroll_to_view(lv_obj_get_child(band,4),LV_ANIM_OFF);
        }
        if(strcmp(argv[2],"card-60")==0){
            char caption[16];
            snprintf(caption,sizeof caption,"60 %s",panel_text(TXT_MINUTES));
            lv_obj_t *sixty=find_label(lv_screen_active(),caption);
            if(sixty)lv_obj_send_event(lv_obj_get_parent(sixty),LV_EVENT_CLICKED,NULL);
        }
    }
    /* The sixth page. "led" is the board's machine on the desktop,
     * "led-colour" an effect in the desktop colour, "led-old" the same from
     * a service that sends no colour, "led-look" the layer of the colour and
     * the brightness, "led-look-fire" that layer for a scene with colours of
     * its own, "led-none" a PC with no LED module, "led-applying" a tap that
     * waits to go, "led-refused" a change the PC refused for want of the
     * sudo rule, "led-mirror" the mirror in Game Mode with the line of its
     * status and the button of its profile, "led-profiles" the menu of
     * that button, and "led-mirror-desktop" the mirror of the desktop that
     * waits for the share of the screen. */
    if(argc>2&&strncmp(argv[2],"led",3)==0){
        bool fire=strcmp(argv[2],"led-look-fire")==0;
        bool coloured=strcmp(argv[2],"led-colour")==0||strcmp(argv[2],"led-old")==0
                      ||strcmp(argv[2],"led-look")==0;
        s.led_known=true;
        s.led_here=strcmp(argv[2],"led-none")!=0;
        s.led_look=strcmp(argv[2],"led-old")!=0;
        snprintf(s.led_colour,sizeof s.led_colour,"#ff8000");
        s.led_brightness=128;
        snprintf(s.led_effect[PANEL_LED_DESKTOP],PANEL_LED_KEY,"%s",
                 coloured?"breath":fire?"fire":"aurora");
        snprintf(s.led_effect[PANEL_LED_GAME],PANEL_LED_KEY,"fire");
        bool profiles=strcmp(argv[2],"led-profiles")==0;
        if(profiles||strcmp(argv[2],"led-mirror")==0){
            snprintf(s.led_effect[PANEL_LED_GAME],PANEL_LED_KEY,"mirror");
            s.led_mirror=(panel_led_mirror_t){.state="running",.fps=15,.cpu=12,.source="2560x1440"};
            for(int m=0;m<PANEL_LED_MODES;m++)snprintf(s.led_profile[m],sizeof s.led_profile[m],"pop");
        }
        if(strcmp(argv[2],"led-mirror-desktop")==0){
            snprintf(s.led_effect[PANEL_LED_DESKTOP],PANEL_LED_KEY,"mirror");
            s.led_mirror=(panel_led_mirror_t){.state="asking"};
            for(int m=0;m<PANEL_LED_MODES;m++)snprintf(s.led_profile[m],sizeof s.led_profile[m],"pop");
            s.game_mode=false;
        }
        panel_ui_update(&s);
        lv_obj_t *band=band_in(lv_screen_active());
        if(band){
            lv_obj_update_layout(band);
            lv_obj_scroll_to_view(lv_obj_get_child(band,PANEL_PAGE_LED),LV_ANIM_OFF);
        }
        if(strncmp(argv[2],"led-look",8)==0){
            char said[48];
            if(fire)snprintf(said,sizeof said,"%s %d %%",panel_text(TXT_LED_BRIGHTNESS),50);
            else snprintf(said,sizeof said,"%s • %d %%",panel_text(TXT_COLOUR_ORANGE),50);
            lv_obj_t *words=find_label(lv_screen_active(),said);
            if(words)lv_obj_send_event(lv_obj_get_parent(words),LV_EVENT_CLICKED,NULL);
        }
        if(profiles){
            lv_obj_t *words=find_label(lv_screen_active(),panel_text(TXT_PROFILE_POP));
            if(words)lv_obj_send_event(lv_obj_get_parent(words),LV_EVENT_CLICKED,NULL);
        }
        bool applying=strcmp(argv[2],"led-applying")==0,refused=strcmp(argv[2],"led-refused")==0;
        if(applying||refused){
            lv_obj_t *next=find_label(lv_screen_active(),LV_SYMBOL_RIGHT);
            if(next)lv_obj_send_event(lv_obj_get_parent(next),LV_EVENT_CLICKED,NULL);
        }
        if(refused){
            /* The wait after the tap, and then the answer of the PC. */
            preview_ms+=2000;
            lv_timer_handler();
            s.led_replies=1;s.led_code=403;
            panel_ui_update(&s);
        }
    }
    /* The seventh page. "energy" is the board's machine on the balanced
     * profile, "energy-custom" a setting of the control panel that no
     * profile is, "energy-passive" a driver with no preference, and
     * "energy-none" a PC with no power module. */
    if(argc>2&&strncmp(argv[2],"energy",6)==0){
        bool passive=strcmp(argv[2],"energy-passive")==0,custom=strcmp(argv[2],"energy-custom")==0;
        s.cpu_known=true;
        s.cpu_here=strcmp(argv[2],"energy-none")!=0;
        snprintf(s.cpu_profile,sizeof s.cpu_profile,"%s",custom?"custom":"balanced");
        s.cpu_offers=passive?(uint8_t)((1u<<PANEL_CPU_BALANCED)|(1u<<PANEL_CPU_PERFORMANCE)|(1u<<PANEL_CPU_STEAMOS))
                            :(uint8_t)((1u<<PANEL_CPU_PROFILES)-1);
        snprintf(s.cpu_governor,sizeof s.cpu_governor,"%s",passive?"schedutil":"powersave");
        snprintf(s.cpu_epp,sizeof s.cpu_epp,"%s",passive?"":custom?"balance_power":"balance_performance");
        snprintf(s.cpu_driver,sizeof s.cpu_driver,"%s",passive?"amd-pstate":"amd-pstate-epp");
        panel_ui_update(&s);
        lv_obj_t *band=band_in(lv_screen_active());
        if(band){
            lv_obj_update_layout(band);
            lv_obj_scroll_to_view(lv_obj_get_child(band,PANEL_PAGE_CPU),LV_ANIM_OFF);
        }
    }
    if(argc>2&&strcmp(argv[2],"pads")==0)panel_ui_pads_open();
    if(argc>2&&strncmp(argv[2],"self",4)==0){count_frames();count_taps();panel_ui_self_open();}
    /* "self-touch" is the card of the touches on that page. */
    if(argc>2&&strcmp(argv[2],"self-touch")==0){
        lv_obj_t *title=find_label(lv_screen_active(),panel_text(TXT_SELF_TOUCH));
        if(title){
            lv_obj_update_layout(lv_screen_active());
            lv_obj_scroll_to_view_recursive(lv_obj_get_parent(title),LV_ANIM_OFF);
        }
    }
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
    if(argc>2&&strcmp(argv[2],"self-end")==0){
        lv_obj_t *page=lv_obj_get_child(lv_screen_active(),-1);
        lv_obj_update_layout(page);
        lv_obj_scroll_to_y(page,LV_COORD_MAX,LV_ANIM_OFF);
    }
    if(argc>2&&strcmp(argv[2],"confirm")==0)panel_ui_confirm(PANEL_POWEROFF);
    if(argc>2&&strncmp(argv[2],"settings",8)==0)panel_ui_settings_open();
    /* "pages" is the screen that puts the pages in order, behind the
     * settings. */
    if(argc>2&&strncmp(argv[2],"pages",5)==0){panel_ui_settings_open();panel_ui_arrange_open();}
    /* The settings scroll, and the end of them is a page of its own to
     * look at. The page is the last child of the screen. */
    if(argc>2&&strcmp(argv[2],"settings-end")==0){
        lv_obj_t *page=lv_obj_get_child(lv_screen_active(),-1);
        lv_obj_update_layout(page);
        lv_obj_scroll_to_y(page,LV_COORD_MAX,LV_ANIM_OFF);
    }
    /* "settings-appearance" is the card of the theme and the accent, in
     * the middle of the screen. */
    if(argc>2&&strcmp(argv[2],"settings-appearance")==0){
        lv_obj_t *title=find_label(lv_screen_active(),panel_text(TXT_APPEARANCE));
        if(title){
            lv_obj_t *page=lv_obj_get_child(lv_screen_active(),-1);
            lv_obj_update_layout(page);
            lv_obj_scroll_to_y(page,lv_obj_get_y(lv_obj_get_parent(title))-150,LV_ANIM_OFF);
        }
    }
    /* "standby" is the black cover of a sleeping panel with its clock, as
     * main.c writes it: the time, and the day and the date under it.
     * "standby-alarm" has the next ring of the alarm clock under them. */
    if(argc>2&&(strcmp(argv[2],"standby")==0||strcmp(argv[2],"standby-alarm")==0)){
        lv_indev_t *input=lv_indev_create();
        lv_indev_set_type(input,LV_INDEV_TYPE_POINTER);
        lv_indev_set_display(input,d);
        char date[64],alarm[24]="";
        panel_text_date(date,sizeof date,4,8,10);
        if(alarm_clock){
            panel_alarm_clock_t now={.known=true,.day=1,.weekday=4,.hour=21,.minute=47};
            panel_ui_alarm_clock_tick(&now);
            panel_ui_alarm_clock_next(alarm,sizeof alarm);
        }
        panel_ui_sleep_clock(d,"21:47",date,alarm);
        panel_ui_sleep(d,input,true);
    }
    lv_refr_now(d);
    FILE *f=fopen(argc>1?argv[1]:"preview.ppm","wb");if(!f)return 1;
    fprintf(f,"P6\n480 480\n255\n");
    for(int i=0;i<480*480;i++){uint8_t rgb[]={pixels[i*4+2],pixels[i*4+1],pixels[i*4]};fwrite(rgb,1,3,f);}
    fclose(f);return 0;
}
