// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
#include "icons.h"

#define BG 0x0C1721
#define CARD 0x111F2B
#define EDGE 0x293D51
#define TEXT 0xEDF4FC
#define MUTED 0xAEC4DE
#define BLUE 0x49A8F7
#define RED 0xF06B79

static lv_obj_t *connection,*dot,*battery,*audio_status,*audio_toggle,*audio_knob,*volume,*small_volume,*brightness_label,*message;
static lv_obj_t *controls[6],*overlay,*setup_screen,*setup_text,*cpu_value,*gpu_value,*power_value;
static panel_action_cb_t send_action;
static panel_setting_cb_t save_setting;
static panel_sound_cb_t play_sound;
static panel_settings_t local;
static lv_obj_t *settings_screen, *sound_value, *sound_status;
static void feedback(void){if(local.touch_tones && play_sound)play_sound(local.sound_volume);}
static panel_action_t pending;
static panel_state_t last_state;
static bool last_state_valid;

static lv_obj_t *text_at(lv_obj_t *parent,const char *text,int x,int y,int width,const lv_font_t *font,uint32_t color)
{
    lv_obj_t *label=lv_label_create(parent);
    lv_obj_set_pos(label,x,y);lv_obj_set_width(label,width);
    lv_label_set_long_mode(label,LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_font(label,font,0);lv_obj_set_style_text_color(label,lv_color_hex(color),0);
    lv_label_set_text(label,text);return label;
}
static void center_text(lv_obj_t *label){lv_obj_set_style_text_align(label,LV_TEXT_ALIGN_CENTER,0);}
static lv_obj_t *panel(lv_obj_t *parent,int x,int y,int w,int h,uint32_t color,bool border)
{
    lv_obj_t *o=lv_obj_create(parent);lv_obj_remove_style_all(o);
    lv_obj_set_pos(o,x,y);lv_obj_set_size(o,w,h);
    lv_obj_set_style_bg_color(o,lv_color_hex(color),0);lv_obj_set_style_bg_opa(o,LV_OPA_COVER,0);
    lv_obj_remove_flag(o,LV_OBJ_FLAG_SCROLLABLE);
    if(border){lv_obj_set_style_border_width(o,1,0);lv_obj_set_style_border_color(o,lv_color_hex(EDGE),0);lv_obj_set_style_radius(o,6,0);}
    return o;
}
static void line(lv_obj_t *parent,int x,int y,int w,int h){lv_obj_t *o=panel(parent,x,y,w,h,EDGE,false);lv_obj_remove_flag(o,LV_OBJ_FLAG_CLICKABLE);}
static lv_obj_t *icon(lv_obj_t *parent,const lv_image_dsc_t *source,int x,int y,uint32_t color)
{
    lv_obj_t *o=lv_image_create(parent);lv_image_set_src(o,source);lv_obj_set_pos(o,x,y);
    lv_obj_set_style_image_recolor(o,lv_color_hex(color),0);lv_obj_set_style_image_recolor_opa(o,LV_OPA_COVER,0);return o;
}
static lv_obj_t *button(lv_obj_t *parent,const char *caption,int x,int y,int w,int h,lv_event_cb_t cb,intptr_t data)
{
    lv_obj_t *b=lv_button_create(parent);lv_obj_set_pos(b,x,y);lv_obj_set_size(b,w,h);
    lv_obj_set_style_bg_color(b,lv_color_hex(0x1B2B3C),0);
    lv_obj_set_style_text_color(b,lv_color_hex(TEXT),0);lv_obj_set_style_text_font(b,&lv_font_montserrat_16,0);
    lv_obj_set_style_radius(b,5,0);lv_obj_set_style_border_width(b,1,0);lv_obj_set_style_border_color(b,lv_color_hex(EDGE),0);
    lv_obj_set_style_shadow_width(b,0,0);lv_obj_set_style_pad_all(b,0,0);
    lv_obj_set_style_opa(b,LV_OPA_40,LV_STATE_DISABLED);
    if(caption[0]){lv_obj_t *l=lv_label_create(b);lv_label_set_text(l,caption);lv_obj_center(l);}
    lv_obj_add_event_cb(b,cb,LV_EVENT_CLICKED,(void *)data);return b;
}
static void confirmation(lv_event_t *e)
{
    bool yes=(intptr_t)lv_event_get_user_data(e)!=0;
    feedback();
    lv_obj_delete(overlay);overlay=NULL;if(yes&&send_action)send_action(pending);
}
void panel_ui_confirm(panel_action_t action)
{
    if (overlay) return;
    pending=action;
    overlay=panel(lv_screen_active(),0,0,480,480,BG,false);lv_obj_set_style_bg_opa(overlay,LV_OPA_90,0);
    const char *caption=action==PANEL_SUSPEND?"PC in Standby versetzen?":action==PANEL_REBOOT?"PC neu starten?":action==PANEL_POWEROFF?"PC ausschalten?":"Einrichtung oeffnen?";
    lv_obj_t *box=panel(overlay,20,132,440,216,CARD,true);
    text_at(box,caption,20,26,400,&lv_font_montserrat_20,TEXT);
    text_at(box,action==PANEL_SETUP?"WLAN und PC-Verbindung konfigurieren":"Bitte am Display bestaetigen.",20,66,400,&lv_font_montserrat_16,MUTED);
    button(box,"Abbrechen",20,126,192,62,confirmation,0);
    lv_obj_t *yes=button(box,"Bestaetigen",228,126,192,62,confirmation,1);lv_obj_set_style_bg_color(yes,lv_color_hex(BLUE),0);
    lv_obj_set_style_text_color(yes,lv_color_hex(BG),0);
}
static void clicked(lv_event_t *e)
{
    feedback();
    panel_action_t action=(panel_action_t)(intptr_t)lv_event_get_user_data(e);
    if(action>=PANEL_SUSPEND)panel_ui_confirm(action);else if(send_action)send_action(action);
}
static void setting_slider(lv_event_t *e)
{
    panel_setting_t key=(panel_setting_t)(intptr_t)lv_event_get_user_data(e);
    int value=lv_slider_get_value(lv_event_get_target(e));
    if(key==PANEL_BRIGHTNESS){local.brightness=value;lv_label_set_text_fmt(brightness_label,"%d %%",value);}
    else {local.sound_volume=value;lv_label_set_text_fmt(sound_value,"%d %%",value);}
    bool save=lv_event_get_code(e)==LV_EVENT_RELEASED;
    if(save_setting)save_setting(key,value,save);
    if(save && key==PANEL_SOUND_VOLUME)feedback();
}
static void slider_at(lv_obj_t *parent,int y,int minimum,int value,panel_setting_t key)
{
    lv_obj_t *slider=lv_slider_create(parent);lv_obj_set_pos(slider,28,y);lv_obj_set_size(slider,380,8);
    lv_slider_set_range(slider,minimum,100);lv_slider_set_value(slider,value,LV_ANIM_OFF);
    lv_obj_set_style_bg_color(slider,lv_color_hex(EDGE),LV_PART_MAIN);
    lv_obj_set_style_bg_color(slider,lv_color_hex(BLUE),LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(slider,lv_color_hex(TEXT),LV_PART_KNOB);
    lv_obj_set_style_pad_all(slider,7,LV_PART_KNOB);lv_obj_set_ext_click_area(slider,18);
    lv_obj_add_event_cb(slider,setting_slider,LV_EVENT_VALUE_CHANGED,(void *)(intptr_t)key);
    lv_obj_add_event_cb(slider,setting_slider,LV_EVENT_RELEASED,(void *)(intptr_t)key);
}
static void tones_changed(lv_event_t *e)
{
    local.touch_tones=lv_obj_has_state(lv_event_get_target(e),LV_STATE_CHECKED);
    if(save_setting)save_setting(PANEL_TOUCH_TONES,local.touch_tones,true);
    feedback();
}
static void test_sound(lv_event_t *e){(void)e;if(play_sound)play_sound(local.sound_volume);}
static void settings_close(lv_event_t *e)
{
    (void)e;feedback();lv_obj_delete(settings_screen);settings_screen=NULL;
    brightness_label=NULL;sound_value=NULL;sound_status=NULL;
}
void panel_ui_settings_open(void)
{
    if(settings_screen)return;
    last_state_valid=false;
    settings_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
    button(settings_screen,"< Zurueck",12,8,112,44,settings_close,0);
    text_at(settings_screen,"ESP-Einstellungen",144,20,320,&lv_font_montserrat_20,TEXT);
    line(settings_screen,0,62,480,1);
    lv_obj_t *display=panel(settings_screen,20,78,440,114,CARD,true);
    icon(display,&icon_sun,16,18,MUTED);
    text_at(display,"Displayhelligkeit",62,16,268,&lv_font_montserrat_18,TEXT);
    brightness_label=text_at(display,"",338,16,88,&lv_font_montserrat_18,BLUE);
    lv_label_set_text_fmt(brightness_label,"%d %%",local.brightness);
    text_at(display,"Nur das Display dieses ESP",62,43,350,&lv_font_montserrat_12,MUTED);
    slider_at(display,88,5,local.brightness,PANEL_BRIGHTNESS);
    lv_obj_t *sound=panel(settings_screen,20,206,440,216,CARD,true);
    icon(sound,&icon_volume_2,12,12,MUTED);
    text_at(sound,"Tastentoene",70,16,240,&lv_font_montserrat_18,TEXT);
    text_at(sound,"Ton bei Bedienung des Panels",70,44,340,&lv_font_montserrat_12,MUTED);
    lv_obj_t *sw=lv_switch_create(sound);lv_obj_set_pos(sw,358,17);lv_obj_set_size(sw,58,30);
    lv_obj_set_style_bg_color(sw,lv_color_hex(BLUE),LV_PART_INDICATOR|LV_STATE_CHECKED);
    lv_obj_set_ext_click_area(sw,8);
    if(local.touch_tones)lv_obj_add_state(sw,LV_STATE_CHECKED);
    lv_obj_add_event_cb(sw,tones_changed,LV_EVENT_VALUE_CHANGED,NULL);
    line(sound,18,76,402,1);
    text_at(sound,"ESP-Lautstaerke",20,92,296,&lv_font_montserrat_16,TEXT);
    sound_value=text_at(sound,"",338,92,88,&lv_font_montserrat_18,BLUE);
    lv_label_set_text_fmt(sound_value,"%d %%",local.sound_volume);
    slider_at(sound,138,0,local.sound_volume,PANEL_SOUND_VOLUME);
    button(sound,"Testton",276,164,144,44,test_sound,0);
    sound_status=text_at(sound,"Lokaler Lautsprecher",20,176,248,&lv_font_montserrat_12,MUTED);
    text_at(settings_screen,"Aenderungen werden automatisch gespeichert.",22,447,440,&lv_font_montserrat_12,MUTED);
}
static void settings_clicked(lv_event_t *e){(void)e;feedback();panel_ui_settings_open();}
static lv_obj_t *power_button(lv_obj_t *parent,const char *caption,const lv_image_dsc_t *source,int y,panel_action_t action)
{
    lv_obj_t *b=button(parent,"",14,y,196,56,clicked,action);
    uint32_t color=action==PANEL_POWEROFF?RED:MUTED;
    icon(b,source,14,14,color);
    text_at(b,caption,54,18,136,&lv_font_montserrat_16,color);
    if(action==PANEL_POWEROFF){lv_obj_set_style_bg_color(b,lv_color_hex(0x2C202B),0);lv_obj_set_style_border_color(b,lv_color_hex(0xA54757),0);}
    return b;
}
void panel_ui_create(panel_action_cb_t callback,panel_setting_cb_t setting_cb,panel_sound_cb_t sound_cb,const panel_settings_t *settings)
{
    last_state_valid=false;
    send_action=callback;save_setting=setting_cb;play_sound=sound_cb;local=*settings;
    lv_obj_t *s=lv_screen_active();lv_obj_remove_style_all(s);lv_obj_remove_flag(s,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(s,lv_color_hex(BG),0);lv_obj_set_style_bg_opa(s,LV_OPA_COVER,0);
    lv_obj_set_style_text_color(s,lv_color_hex(TEXT),0);
    icon(s,&icon_monitor,14,19,MUTED);line(s,50,16,1,28);
    connection=text_at(s,"PC OFFLINE",62,22,140,&lv_font_montserrat_14,TEXT);
    dot=panel(s,202,26,9,9,0x60758A,false);lv_obj_set_style_radius(dot,LV_RADIUS_CIRCLE,0);
    line(s,234,16,1,28);icon(s,&icon_gamepad_2,248,19,MUTED);
    text_at(s,"CONTROLLER",282,15,142,&lv_font_montserrat_12,MUTED);
    battery=text_at(s,"-- %",282,31,142,&lv_font_montserrat_16,TEXT);
    line(s,0,57,480,1);
    lv_obj_t *left=panel(s,10,70,222,304,CARD,true);
    lv_obj_t *right=panel(s,244,70,226,304,CARD,true);
    icon(left,&icon_volume_2,12,30,MUTED);text_at(left,"PC-TON",70,23,78,&lv_font_montserrat_12,MUTED);
    audio_status=text_at(left,"--",70,44,82,&lv_font_montserrat_18,TEXT);
    audio_toggle=button(left,"",154,28,54,48,clicked,PANEL_MUTE);controls[PANEL_MUTE]=audio_toggle;
    lv_obj_set_style_bg_opa(audio_toggle,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(audio_toggle,0,0);
    lv_obj_t *track=panel(audio_toggle,0,10,52,28,BLUE,false);lv_obj_remove_flag(track,LV_OBJ_FLAG_CLICKABLE);lv_obj_set_style_radius(track,LV_RADIUS_CIRCLE,0);
    audio_knob=panel(track,27,3,22,22,TEXT,false);lv_obj_remove_flag(audio_knob,LV_OBJ_FLAG_CLICKABLE);lv_obj_set_style_radius(audio_knob,LV_RADIUS_CIRCLE,0);
    lv_obj_set_user_data(audio_toggle,track);
    line(left,16,112,190,1);
    center_text(text_at(left,"PC-LAUTSTAERKE",12,135,196,&lv_font_montserrat_14,MUTED));
    volume=text_at(left,"-- %",12,166,196,&lv_font_montserrat_32,TEXT);center_text(volume);
    controls[PANEL_VOLUME_DOWN]=button(left,LV_SYMBOL_MINUS,12,232,48,48,clicked,PANEL_VOLUME_DOWN);
    lv_obj_t *v=panel(left,66,232,88,48,0x18314A,true);small_volume=text_at(v,"-- %",0,15,86,&lv_font_montserrat_16,TEXT);center_text(small_volume);
    controls[PANEL_VOLUME_UP]=button(left,LV_SYMBOL_PLUS,160,232,48,48,clicked,PANEL_VOLUME_UP);
    icon(right,&icon_monitor,22,23,MUTED);
    text_at(right,"PC-STEUERUNG",60,27,160,&lv_font_montserrat_14,MUTED);
    line(right,14,68,196,1);
    controls[PANEL_SUSPEND]=power_button(right,"Standby",&icon_moon,86,PANEL_SUSPEND);
    controls[PANEL_REBOOT]=power_button(right,"Neustart",&icon_rotate_cw,160,PANEL_REBOOT);
    controls[PANEL_POWEROFF]=power_button(right,"Ausschalten",&icon_power,234,PANEL_POWEROFF);
    lv_obj_t *foot=panel(s,10,386,460,48,CARD,true);
    icon(foot,&icon_cpu,12,12,MUTED);text_at(foot,"CPU",45,6,99,&lv_font_montserrat_12,MUTED);cpu_value=text_at(foot,"-- C",45,22,99,&lv_font_montserrat_18,BLUE);
    line(foot,151,9,1,30);icon(foot,&icon_circuit_board,165,12,MUTED);text_at(foot,"GPU",198,6,99,&lv_font_montserrat_12,MUTED);gpu_value=text_at(foot,"-- C",198,22,99,&lv_font_montserrat_18,BLUE);
    line(foot,304,9,1,30);icon(foot,&icon_zap,318,12,MUTED);text_at(foot,"GPU-WATT",350,6,98,&lv_font_montserrat_12,MUTED);power_value=text_at(foot,"-- W",350,22,98,&lv_font_montserrat_18,BLUE);
    message=text_at(s,"Verbinde ...",12,451,188,&lv_font_montserrat_12,MUTED);
    lv_obj_set_height(message,18);
    lv_obj_t *settings_button=button(s,"Einstellungen",206,436,146,44,settings_clicked,0);
    lv_obj_set_style_bg_opa(settings_button,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(settings_button,0,0);
    lv_obj_set_style_text_font(settings_button,&lv_font_montserrat_14,0);
    lv_obj_t *setup=button(s,"Einrichten",358,436,112,44,clicked,PANEL_SETUP);lv_obj_set_style_bg_opa(setup,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(setup,0,0);lv_obj_set_style_text_font(setup,&lv_font_montserrat_14,0);
}
void panel_ui_update(const panel_state_t *s)
{
    /* Repeated label_set_text_fmt calls allocate and invalidate even unchanged
     * values. Status is polled at 3 s; idle 200 ms UI ticks need no redraw.
     * A padding-only difference can merely cause an extra update, never hide one. */
    if(last_state_valid && memcmp(&last_state,s,sizeof(*s))==0)return;
    memcpy(&last_state,s,sizeof(*s));last_state_valid=true;
    if(sound_status)lv_label_set_text(sound_status,s->sound_error?"Audio nicht verfuegbar":"Lokaler Lautsprecher");
    if(s->setup){
        if(settings_screen){lv_obj_delete(settings_screen);settings_screen=NULL;brightness_label=NULL;sound_value=NULL;sound_status=NULL;}
        if(!setup_screen){
            if(overlay){lv_obj_delete(overlay);overlay=NULL;}
            setup_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
            text_at(setup_screen,"Panel einrichten",24,28,432,&lv_font_montserrat_24,BLUE);
            setup_text=text_at(setup_screen,"",24,96,432,&lv_font_montserrat_18,TEXT);lv_label_set_long_mode(setup_text,LV_LABEL_LONG_WRAP);
            text_at(setup_screen,"Zum Abbrechen das Panel neu starten.",24,428,432,&lv_font_montserrat_16,MUTED);
        }
        lv_label_set_text_fmt(setup_text,"1. Mit diesem WLAN verbinden:\n%s\n\nPasswort: %s\n\n2. Im Browser oeffnen:\nhttp://192.168.4.1\n\n3. Heim-WLAN und PC eintragen.",s->setup_ssid,s->setup_password);return;
    }
    lv_label_set_text(connection,!s->wifi?"WLAN OFFLINE":s->online?"PC VERBUNDEN":"PC OFFLINE");
    lv_obj_set_style_bg_color(dot,lv_color_hex(s->online?0x70C256:0x60758A),0);
    if(s->online&&s->battery>=0)lv_label_set_text_fmt(battery,"%d %% %s",s->battery,strcmp(s->charging,"Wird geladen")==0?LV_SYMBOL_CHARGE:"");else lv_label_set_text(battery,"-- %");
    bool audio=s->online&&s->volume>=0;
    lv_label_set_text(audio_status,!audio?"--":s->muted?"STUMM":"AKTIV");
    lv_obj_t *track=lv_obj_get_user_data(audio_toggle);lv_obj_set_style_bg_color(track,lv_color_hex(audio&&!s->muted?BLUE:EDGE),0);lv_obj_set_x(audio_knob,audio&&!s->muted?27:3);
    if(audio){lv_label_set_text_fmt(volume,"%d %%",s->volume);lv_label_set_text_fmt(small_volume,"%d %%",s->volume);}else{lv_label_set_text(volume,"-- %");lv_label_set_text(small_volume,"-- %");}
    for(int i=0;i<6;i++){bool enabled=s->online&&(i>=3||audio);if(enabled)lv_obj_remove_state(controls[i],LV_STATE_DISABLED);else lv_obj_add_state(controls[i],LV_STATE_DISABLED);}
    if(s->online&&s->cpu_temp>=0)lv_label_set_text_fmt(cpu_value,"%d °C",s->cpu_temp);else lv_label_set_text(cpu_value,"-- °C");
    if(s->online&&s->gpu_temp>=0)lv_label_set_text_fmt(gpu_value,"%d °C",s->gpu_temp);else lv_label_set_text(gpu_value,"-- °C");
    if(s->online&&s->gpu_watts>=0)lv_label_set_text_fmt(power_value,"%d W",s->gpu_watts);else lv_label_set_text(power_value,"-- W");
    lv_label_set_text(message,s->message);
}
