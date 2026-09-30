// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
#include "icons.h"
#include "panel_text.h"
#include "panel_ui_sleep.h"

#define BG 0x0C1721
#define CARD 0x111F2B
#define EDGE 0x293D51
#define TEXT 0xEDF4FC
#define MUTED 0xAEC4DE
#define BLUE 0x49A8F7
#define RED 0xF06B79

static lv_obj_t *connection,*dot,*battery,*audio_status,*audio_toggle,*audio_knob,*volume,*brightness_label,*message;
static lv_obj_t *controls[6],*overlay,*setup_screen,*setup_text,*cpu_value,*gpu_value,*power_value;
/* Not in controls[]: that table is indexed by the action, it holds the
 * six the service performs, and PANEL_WAKE is done by the panel. */
static lv_obj_t *wake_button,*wake_what;
/* The second and third pages. Not in controls[] either: that table is
 * indexed by the action and holds the six on the first page. */
static lv_obj_t *mode_now,*mode_button,*mode_caption,*playing_name;
static lv_obj_t *drive_rows[PANEL_DRIVES],*drive_names[PANEL_DRIVES];
static lv_obj_t *drive_bars[PANEL_DRIVES],*drive_free[PANEL_DRIVES];
static lv_obj_t *no_drives,*band,*dots[3];
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
    const char *caption=action==PANEL_SUSPEND?panel_text(TXT_CONFIRM_SUSPEND):action==PANEL_REBOOT?panel_text(TXT_CONFIRM_REBOOT):action==PANEL_POWEROFF?panel_text(TXT_CONFIRM_OFF):(action==PANEL_DESKTOP_MODE||action==PANEL_GAME_MODE)?panel_text(TXT_CONFIRM_MODE):panel_text(TXT_CONFIRM_SETUP);
    lv_obj_t *box=panel(overlay,20,132,440,216,CARD,true);
    text_at(box,caption,20,26,400,&lv_font_montserrat_20,TEXT);
    /* A second line only where there is something to say. Switching the
     * session says it in the question, and a sentence under it that
     * repeats the obvious is a sentence somebody reads once and then
     * reads past. */
    const char *what=action==PANEL_SETUP?panel_text(TXT_SETUP_WHAT)
        :(action==PANEL_DESKTOP_MODE||action==PANEL_GAME_MODE)?""
        :panel_text(TXT_CONFIRM_HERE);
    if(what[0])text_at(box,what,20,66,400,&lv_font_montserrat_16,MUTED);
    button(box,panel_text(TXT_CANCEL),20,126,192,62,confirmation,0);
    lv_obj_t *yes=button(box,panel_text(TXT_CONFIRM),228,126,192,62,confirmation,1);lv_obj_set_style_bg_color(yes,lv_color_hex(BLUE),0);
    lv_obj_set_style_text_color(yes,lv_color_hex(BG),0);
}
static void clicked(lv_event_t *e)
{
    feedback();
    panel_action_t action=(panel_action_t)(intptr_t)lv_event_get_user_data(e);
    /* The four that interrupt what somebody is doing ask first. Waking a
     * machine that is off interrupts nothing, so it is one press. */
    if(action>=PANEL_SUSPEND&&action<=PANEL_SETUP)panel_ui_confirm(action);
    else if(send_action)send_action(action);
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
static void language_clicked(lv_event_t *e)
{
    (void)e;feedback();
    panel_language_t next=panel_text_language()==PANEL_ENGLISH?PANEL_GERMAN:PANEL_ENGLISH;
    panel_text_set(next);local.language=next;
    if(save_setting)save_setting(PANEL_LANGUAGE,(int)next,true);
    // Both screens are built one time, with the words of the language that
    // was current then. Every one of them is now wrong, so both are built
    // again. The person stays where they were, on the settings page.
    lv_obj_delete(settings_screen);settings_screen=NULL;
    brightness_label=NULL;sound_value=NULL;sound_status=NULL;
    panel_ui_create(send_action,save_setting,play_sound,&local);
    panel_ui_settings_open();
}
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
    button(settings_screen,panel_text(TXT_BACK),12,8,112,44,settings_close,0);
    text_at(settings_screen,panel_text(TXT_SETTINGS_TITLE),136,20,200,&lv_font_montserrat_20,TEXT);
    // The name of the other language, written in that language. Somebody
    // who cannot read the one on the screen still finds their own.
    button(settings_screen,panel_language_name(panel_text_language()==PANEL_ENGLISH?PANEL_GERMAN:PANEL_ENGLISH),
           344,8,124,44,language_clicked,0);
    line(settings_screen,0,62,480,1);
    lv_obj_t *display=panel(settings_screen,20,78,440,114,CARD,true);
    icon(display,&icon_sun,16,18,MUTED);
    text_at(display,panel_text(TXT_BRIGHTNESS),62,16,268,&lv_font_montserrat_18,TEXT);
    brightness_label=text_at(display,"",338,16,88,&lv_font_montserrat_18,BLUE);
    lv_label_set_text_fmt(brightness_label,"%d %%",local.brightness);
    text_at(display,panel_text(TXT_BRIGHTNESS_WHAT),62,43,350,&lv_font_montserrat_12,MUTED);
    slider_at(display,88,5,local.brightness,PANEL_BRIGHTNESS);
    lv_obj_t *sound=panel(settings_screen,20,206,440,216,CARD,true);
    icon(sound,&icon_volume_2,12,12,MUTED);
    text_at(sound,panel_text(TXT_TONES),70,16,240,&lv_font_montserrat_18,TEXT);
    text_at(sound,panel_text(TXT_TONES_WHAT),70,44,340,&lv_font_montserrat_12,MUTED);
    lv_obj_t *sw=lv_switch_create(sound);lv_obj_set_pos(sw,358,17);lv_obj_set_size(sw,58,30);
    lv_obj_set_style_bg_color(sw,lv_color_hex(BLUE),LV_PART_INDICATOR|LV_STATE_CHECKED);
    lv_obj_set_ext_click_area(sw,8);
    if(local.touch_tones)lv_obj_add_state(sw,LV_STATE_CHECKED);
    lv_obj_add_event_cb(sw,tones_changed,LV_EVENT_VALUE_CHANGED,NULL);
    line(sound,18,76,402,1);
    text_at(sound,panel_text(TXT_ESP_VOLUME),20,92,296,&lv_font_montserrat_16,TEXT);
    sound_value=text_at(sound,"",338,92,88,&lv_font_montserrat_18,BLUE);
    lv_label_set_text_fmt(sound_value,"%d %%",local.sound_volume);
    slider_at(sound,138,0,local.sound_volume,PANEL_SOUND_VOLUME);
    button(sound,panel_text(TXT_TEST_TONE),276,164,144,44,test_sound,0);
    sound_status=text_at(sound,panel_text(TXT_SPEAKER),20,176,248,&lv_font_montserrat_12,MUTED);
    text_at(settings_screen,panel_text(TXT_AUTOSAVE),22,447,440,&lv_font_montserrat_12,MUTED);
}
static void settings_clicked(lv_event_t *e){(void)e;feedback();panel_ui_settings_open();}
/* Which of the three marks under the band is lit.
 *
 * Read from where the band stopped and not counted from the swipes: a
 * swipe that does not carry far enough leaves the band where it was, and a
 * count would then be one ahead of the screen for good. */
static void band_scrolled(lv_event_t *e)
{
    (void)e;
    if(!band)return;
    int32_t at=lv_obj_get_scroll_x(band);
    int page=(at+240)/480;
    if(page<0)page=0;
    if(page>2)page=2;
    for(int i=0;i<3;i++)
        if(dots[i])lv_obj_set_style_bg_color(dots[i],lv_color_hex(i==page?BLUE:EDGE),0);
}
/* One drive, as a name, a bar and what is left of it. */
static void drive_row(lv_obj_t *parent,int index,int y)
{
    drive_rows[index]=panel(parent,0,y,436,44,CARD,false);
    lv_obj_set_style_bg_opa(drive_rows[index],LV_OPA_TRANSP,0);
    lv_obj_remove_flag(drive_rows[index],LV_OBJ_FLAG_CLICKABLE);
    drive_names[index]=text_at(drive_rows[index],"",0,0,150,&lv_font_montserrat_16,TEXT);
    drive_free[index]=text_at(drive_rows[index],"",156,0,280,&lv_font_montserrat_14,MUTED);
    lv_obj_set_style_text_align(drive_free[index],LV_TEXT_ALIGN_RIGHT,0);
    lv_obj_t *track=panel(drive_rows[index],0,26,436,10,EDGE,false);
    lv_obj_set_style_radius(track,LV_RADIUS_CIRCLE,0);
    lv_obj_remove_flag(track,LV_OBJ_FLAG_CLICKABLE);
    drive_bars[index]=panel(track,0,0,0,10,BLUE,false);
    lv_obj_set_style_radius(drive_bars[index],LV_RADIUS_CIRCLE,0);
    lv_obj_remove_flag(drive_bars[index],LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(drive_rows[index],LV_OBJ_FLAG_HIDDEN);
}
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
    panel_text_set(local.language);
    lv_obj_t *s=lv_screen_active();
    // Everything on the screen goes, because this runs a second time when
    // the language changes. Without it the new words are drawn over the old
    // ones. The pointers below are the ones that outlive a clean.
    lv_obj_clean(s);overlay=NULL;setup_screen=NULL;setup_text=NULL;
    /* The settings page is a child of this screen too, so the clean
     * above took it. Kept, its pointer is the reason that
     * panel_ui_settings_open returns at once and the page never opens
     * again. check_navigation builds the screens with that page open. */
    settings_screen=NULL;brightness_label=NULL;sound_value=NULL;sound_status=NULL;
    /* The band and everything on the second and third pages are children
     * of this screen too. A pointer kept past the clean above is a pointer
     * to freed memory, and band_scrolled runs from a touch. */
    band=NULL;mode_now=NULL;mode_button=NULL;mode_caption=NULL;
    playing_name=NULL;no_drives=NULL;
    for(int i=0;i<3;i++)dots[i]=NULL;
    for(int i=0;i<PANEL_DRIVES;i++){
        drive_rows[i]=NULL;drive_names[i]=NULL;
        drive_bars[i]=NULL;drive_free[i]=NULL;
    }
    /* The black cover of a sleeping panel is a child of this screen,
     * so the clean above took it. See panel_ui_sleep_reset. */
    panel_ui_sleep_reset();
    lv_obj_remove_style_all(s);lv_obj_remove_flag(s,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(s,lv_color_hex(BG),0);lv_obj_set_style_bg_opa(s,LV_OPA_COVER,0);
    lv_obj_set_style_text_color(s,lv_color_hex(TEXT),0);
    icon(s,&icon_monitor,14,19,MUTED);line(s,50,16,1,28);
    connection=text_at(s,panel_text(TXT_PC_OFFLINE),62,22,140,&lv_font_montserrat_14,TEXT);
    dot=panel(s,202,26,9,9,0x60758A,false);lv_obj_set_style_radius(dot,LV_RADIUS_CIRCLE,0);
    line(s,234,16,1,28);icon(s,&icon_gamepad_2,248,19,MUTED);
    text_at(s,panel_text(TXT_CONTROLLER),282,15,142,&lv_font_montserrat_12,MUTED);
    battery=text_at(s,"-- %",282,31,142,&lv_font_montserrat_16,TEXT);
    line(s,0,57,480,1);
    /* The middle band, which scrolls sideways. Three pages of one screen
     * each, and the head above it and the sensors below it stay where they
     * are: those are the numbers somebody looks at without touching
     * anything, and a page that can carry them away is a page that hides
     * them.
     *
     * LV_SCROLL_SNAP_CENTER with SCROLL_ONE is what makes it pages rather
     * than a strip. A swipe moves exactly one and lands on it, so there is
     * no place to stop between two.
     *
     * The band itself is not clickable, which matters: lv_obj_create makes
     * a clickable object, and a band that takes a press swallows the one
     * meant for a button on it. */
    band=lv_obj_create(s);lv_obj_remove_style_all(band);
    lv_obj_set_pos(band,0,70);lv_obj_set_size(band,480,302);
    lv_obj_set_scroll_dir(band,LV_DIR_HOR);
    lv_obj_set_scroll_snap_x(band,LV_SCROLL_SNAP_CENTER);
    lv_obj_add_flag(band,LV_OBJ_FLAG_SCROLL_ONE);
    lv_obj_remove_flag(band,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_pad_all(band,0,0);
    lv_obj_set_scrollbar_mode(band,LV_SCROLLBAR_MODE_OFF);
    lv_obj_t *page[3];
    for(int i=0;i<3;i++){
        page[i]=panel(band,i*480,0,480,300,BG,false);
        lv_obj_set_style_bg_opa(page[i],LV_OPA_TRANSP,0);
        lv_obj_remove_flag(page[i],LV_OBJ_FLAG_CLICKABLE);
    }
    /* Which page is on the screen. Three of them and no words: the band
     * is the only thing that moves, so a row of marks under it is read
     * without anybody being told what it means. */
    for(int i=0;i<3;i++){
        dots[i]=panel(s,222+i*18,376,8,8,EDGE,false);
        lv_obj_set_style_radius(dots[i],LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(dots[i],LV_OBJ_FLAG_CLICKABLE);
    }
    lv_obj_add_event_cb(band,band_scrolled,LV_EVENT_SCROLL_END,NULL);
    lv_obj_set_style_bg_color(dots[0],lv_color_hex(BLUE),0);
    lv_obj_t *left=panel(page[0],10,0,222,300,CARD,true);
    lv_obj_t *right=panel(page[0],244,0,226,300,CARD,true);
    icon(left,&icon_volume_2,12,26,MUTED);text_at(left,panel_text(TXT_PC_AUDIO),70,19,78,&lv_font_montserrat_12,MUTED);
    audio_status=text_at(left,"--",70,40,82,&lv_font_montserrat_18,TEXT);
    audio_toggle=button(left,"",154,24,54,48,clicked,PANEL_MUTE);controls[PANEL_MUTE]=audio_toggle;
    lv_obj_set_style_bg_opa(audio_toggle,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(audio_toggle,0,0);
    lv_obj_t *track=panel(audio_toggle,0,10,52,28,BLUE,false);lv_obj_remove_flag(track,LV_OBJ_FLAG_CLICKABLE);lv_obj_set_style_radius(track,LV_RADIUS_CIRCLE,0);
    audio_knob=panel(track,27,3,22,22,TEXT,false);lv_obj_remove_flag(audio_knob,LV_OBJ_FLAG_CLICKABLE);lv_obj_set_style_radius(audio_knob,LV_RADIUS_CIRCLE,0);
    lv_obj_set_user_data(audio_toggle,track);
    line(left,16,108,190,1);
    center_text(text_at(left,panel_text(TXT_PC_VOLUME),12,131,196,&lv_font_montserrat_14,MUTED));
    volume=text_at(left,"-- %",12,162,196,&lv_font_montserrat_32,TEXT);center_text(volume);
    /* Two buttons over the width of the card, and nothing between them.
     * The number was there twice: once in the big label above, and once
     * again in a box between these two, which said the same thing in a
     * smaller font. The room it took is theirs now, and the sign on each
     * one grew with it. */
    controls[PANEL_VOLUME_DOWN]=button(left,LV_SYMBOL_MINUS,12,228,92,56,clicked,PANEL_VOLUME_DOWN);
    controls[PANEL_VOLUME_UP]=button(left,LV_SYMBOL_PLUS,116,228,92,56,clicked,PANEL_VOLUME_UP);
    lv_obj_set_style_text_font(controls[PANEL_VOLUME_DOWN],&lv_font_montserrat_24,0);
    lv_obj_set_style_text_font(controls[PANEL_VOLUME_UP],&lv_font_montserrat_24,0);
    icon(right,&icon_monitor,22,19,MUTED);
    text_at(right,panel_text(TXT_PC_CONTROL),60,23,160,&lv_font_montserrat_14,MUTED);
    line(right,14,64,196,1);
    controls[PANEL_SUSPEND]=power_button(right,panel_text(TXT_SUSPEND),&icon_moon,82,PANEL_SUSPEND);
    controls[PANEL_REBOOT]=power_button(right,panel_text(TXT_REBOOT),&icon_rotate_cw,156,PANEL_REBOOT);
    controls[PANEL_POWEROFF]=power_button(right,panel_text(TXT_POWEROFF),&icon_power,230,PANEL_POWEROFF);
    /* In the place of the first of them, and hidden while the PC answers.
     * Standby, restart and switch off mean nothing to a machine that is
     * already off, so the card shows this instead of three buttons that
     * cannot do anything. */
    wake_button=power_button(right,panel_text(TXT_WAKE),&icon_power,82,PANEL_WAKE);
    wake_what=text_at(right,panel_text(TXT_WAKE_WHAT),16,152,192,&lv_font_montserrat_12,MUTED);
    lv_label_set_long_mode(wake_what,LV_LABEL_LONG_WRAP);
    lv_obj_add_flag(wake_button,LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(wake_what,LV_OBJ_FLAG_HIDDEN);
    /* The second page: which session runs, and how full each drive is.
     * Two answers about the machine rather than about what is on it, which
     * is why they share a page. */
    lv_obj_t *mode_card=panel(page[1],10,0,460,104,CARD,true);
    icon(mode_card,&icon_monitor,14,18,MUTED);
    text_at(mode_card,panel_text(TXT_MODE),52,14,180,&lv_font_montserrat_12,MUTED);
    mode_now=text_at(mode_card,"--",52,34,180,&lv_font_montserrat_24,TEXT);
    mode_button=button(mode_card,"",236,20,208,64,clicked,PANEL_DESKTOP_MODE);
    mode_caption=text_at(mode_button,"",10,22,188,&lv_font_montserrat_16,TEXT);
    center_text(mode_caption);
    lv_obj_t *disk_card=panel(page[1],10,116,460,184,CARD,true);
    icon(disk_card,&icon_circuit_board,14,14,MUTED);
    text_at(disk_card,panel_text(TXT_DRIVES),52,16,240,&lv_font_montserrat_14,MUTED);
    line(disk_card,14,44,432,1);
    for(int i=0;i<PANEL_DRIVES;i++)drive_row(disk_card,i,58+i*46);
    no_drives=text_at(disk_card,panel_text(TXT_NO_DRIVES),14,70,432,&lv_font_montserrat_14,MUTED);
    lv_obj_add_flag(no_drives,LV_OBJ_FLAG_HIDDEN);
    /* The third page: what is on the machine. One card and one name, and
     * the room under it is deliberate: the picture Steam already keeps for
     * every game goes there, and that is a step of its own. */
    lv_obj_t *play_card=panel(page[2],10,0,460,300,CARD,true);
    icon(play_card,&icon_gamepad_2,14,14,MUTED);
    text_at(play_card,panel_text(TXT_PLAYING),52,16,240,&lv_font_montserrat_14,MUTED);
    line(play_card,14,44,432,1);
    playing_name=text_at(play_card,panel_text(TXT_NOTHING_PLAYING),20,64,420,&lv_font_montserrat_24,TEXT);
    lv_label_set_long_mode(playing_name,LV_LABEL_LONG_WRAP);
    lv_obj_t *foot=panel(s,10,386,460,48,CARD,true);
    icon(foot,&icon_cpu,12,12,MUTED);text_at(foot,"CPU",45,6,99,&lv_font_montserrat_12,MUTED);cpu_value=text_at(foot,"-- C",45,22,99,&lv_font_montserrat_18,BLUE);
    line(foot,151,9,1,30);icon(foot,&icon_circuit_board,165,12,MUTED);text_at(foot,"GPU",198,6,99,&lv_font_montserrat_12,MUTED);gpu_value=text_at(foot,"-- C",198,22,99,&lv_font_montserrat_18,BLUE);
    line(foot,304,9,1,30);icon(foot,&icon_zap,318,12,MUTED);text_at(foot,"GPU-WATT",350,6,98,&lv_font_montserrat_12,MUTED);power_value=text_at(foot,"-- W",350,22,98,&lv_font_montserrat_18,BLUE);
    message=text_at(s,panel_text(TXT_CONNECTING),12,451,188,&lv_font_montserrat_12,MUTED);
    lv_obj_set_height(message,18);
    lv_obj_t *settings_button=button(s,panel_text(TXT_SETTINGS),206,436,146,44,settings_clicked,0);
    lv_obj_set_style_bg_opa(settings_button,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(settings_button,0,0);
    lv_obj_set_style_text_font(settings_button,&lv_font_montserrat_14,0);
    lv_obj_t *setup=button(s,panel_text(TXT_SETUP),358,436,112,44,clicked,PANEL_SETUP);lv_obj_set_style_bg_opa(setup,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(setup,0,0);lv_obj_set_style_text_font(setup,&lv_font_montserrat_14,0);
}
/* A size a person reads, out of a count of bytes.
 *
 * Gibibytes, because that is what an operating system counts in and what
 * the number on the box does not. One decimal below a hundred and none
 * above it: "9.4 GB" and "916 GB" are both four characters of meaning, and
 * "916.3" is one of noise.
 */
static void say_size(char *out,size_t room,uint64_t bytes)
{
    double gib=(double)bytes/(1024.0*1024.0*1024.0);
    if(gib<100.0)snprintf(out,room,"%.1f GB",gib);
    else snprintf(out,room,"%.0f GB",gib);
}
void panel_ui_update(const panel_state_t *s)
{
    /* Repeated label_set_text_fmt calls allocate and invalidate even unchanged
     * values. Status is polled at 3 s; idle 200 ms UI ticks need no redraw.
     * A padding-only difference can merely cause an extra update, never hide one. */
    if(last_state_valid && memcmp(&last_state,s,sizeof(*s))==0)return;
    memcpy(&last_state,s,sizeof(*s));last_state_valid=true;
    if(sound_status)lv_label_set_text(sound_status,s->sound_error?panel_text(TXT_NO_AUDIO):panel_text(TXT_SPEAKER));
    if(s->setup){
        if(settings_screen){lv_obj_delete(settings_screen);settings_screen=NULL;brightness_label=NULL;sound_value=NULL;sound_status=NULL;}
        if(!setup_screen){
            if(overlay){lv_obj_delete(overlay);overlay=NULL;}
            setup_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
            text_at(setup_screen,panel_text(TXT_SETUP_TITLE),24,28,432,&lv_font_montserrat_24,BLUE);
            setup_text=text_at(setup_screen,"",24,96,432,&lv_font_montserrat_18,TEXT);lv_label_set_long_mode(setup_text,LV_LABEL_LONG_WRAP);
            text_at(setup_screen,panel_text(TXT_SETUP_STOP),24,428,432,&lv_font_montserrat_16,MUTED);
        }
        lv_label_set_text_fmt(setup_text,panel_text(TXT_SETUP_STEPS),s->setup_ssid,s->setup_password);return;
    }
    lv_label_set_text(connection,!s->wifi?panel_text(TXT_WIFI_OFFLINE):s->online?panel_text(TXT_PC_ONLINE):panel_text(TXT_PC_OFFLINE));
    lv_obj_set_style_bg_color(dot,lv_color_hex(s->online?0x70C256:0x60758A),0);
    if(s->online&&s->battery>=0)lv_label_set_text_fmt(battery,"%d %% %s",s->battery,s->charging?LV_SYMBOL_CHARGE:"");else lv_label_set_text(battery,"-- %");
    bool audio=s->online&&s->volume>=0;
    lv_label_set_text(audio_status,!audio?"--":s->muted?panel_text(TXT_MUTED):panel_text(TXT_ACTIVE));
    lv_obj_t *track=lv_obj_get_user_data(audio_toggle);lv_obj_set_style_bg_color(track,lv_color_hex(audio&&!s->muted?BLUE:EDGE),0);lv_obj_set_x(audio_knob,audio&&!s->muted?27:3);
    if(audio)lv_label_set_text_fmt(volume,"%d %%",s->volume);else lv_label_set_text(volume,"-- %");
    for(int i=0;i<6;i++){bool enabled=s->online&&(i>=3||audio);if(enabled)lv_obj_remove_state(controls[i],LV_STATE_DISABLED);else lv_obj_add_state(controls[i],LV_STATE_DISABLED);}
    /* One card, two faces. Offline with an address to wake at shows the
     * wake button; anything else shows the three, greyed where they cannot
     * be used. A panel that never met a PC with a wired card has no address
     * and keeps the three, because a wake button with nothing to name is
     * worse than none. */
    bool offer_wake=!s->online&&s->can_wake;
    for(int i=PANEL_SUSPEND;i<=PANEL_POWEROFF;i++){
        if(offer_wake)lv_obj_add_flag(controls[i],LV_OBJ_FLAG_HIDDEN);
        else lv_obj_remove_flag(controls[i],LV_OBJ_FLAG_HIDDEN);
    }
    if(offer_wake){lv_obj_remove_flag(wake_button,LV_OBJ_FLAG_HIDDEN);lv_obj_remove_flag(wake_what,LV_OBJ_FLAG_HIDDEN);}
    else{lv_obj_add_flag(wake_button,LV_OBJ_FLAG_HIDDEN);lv_obj_add_flag(wake_what,LV_OBJ_FLAG_HIDDEN);}
    if(s->online&&s->cpu_temp>=0)lv_label_set_text_fmt(cpu_value,"%d °C",s->cpu_temp);else lv_label_set_text(cpu_value,"-- °C");
    if(s->online&&s->gpu_temp>=0)lv_label_set_text_fmt(gpu_value,"%d °C",s->gpu_temp);else lv_label_set_text(gpu_value,"-- °C");
    if(s->online&&s->gpu_watts>=0)lv_label_set_text_fmt(power_value,"%d W",s->gpu_watts);else lv_label_set_text(power_value,"-- W");
    lv_label_set_text(message,s->message);
    /* The second page. Offline leaves every one of these at a dash rather
     * than at the last thing the PC said, which would read as current. */
    if(mode_now){
        lv_label_set_text(mode_now,!s->online?"--":
                          s->game_mode?panel_text(TXT_MODE_GAME):panel_text(TXT_MODE_DESKTOP));
        lv_label_set_text(mode_caption,s->game_mode?panel_text(TXT_TO_DESKTOP):panel_text(TXT_TO_GAME));
        /* The button carries where it goes, so the press is the target and
         * never "the other one". See PANEL_DESKTOP_MODE in ui.h. */
        lv_obj_remove_event_cb(mode_button,clicked);
        lv_obj_add_event_cb(mode_button,clicked,LV_EVENT_CLICKED,
                            (void *)(intptr_t)(s->game_mode?PANEL_DESKTOP_MODE:PANEL_GAME_MODE));
        if(s->online)lv_obj_remove_state(mode_button,LV_STATE_DISABLED);
        else lv_obj_add_state(mode_button,LV_STATE_DISABLED);
    }
    int shown=s->online&&s->drive_count>0?s->drive_count:0;
    if(shown>PANEL_DRIVES)shown=PANEL_DRIVES;
    for(int i=0;i<PANEL_DRIVES;i++){
        if(!drive_rows[i])break;
        if(i>=shown){lv_obj_add_flag(drive_rows[i],LV_OBJ_FLAG_HIDDEN);continue;}
        lv_obj_remove_flag(drive_rows[i],LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(drive_names[i],s->drives[i].name);
        char left[24],whole[24];
        say_size(left,sizeof(left),s->drives[i].free);
        say_size(whole,sizeof(whole),s->drives[i].total);
        lv_label_set_text_fmt(drive_free[i],"%s %s / %s",left,panel_text(TXT_FREE),whole);
        /* The bar fills with what is used, because a bar that fills as a
         * drive empties reads backwards. A total of nought would divide by
         * nought, and drives() never sends one. */
        uint64_t total=s->drives[i].total;
        uint64_t used=total>s->drives[i].free?total-s->drives[i].free:0;
        int width=total?(int)((used*436)/total):0;
        lv_obj_set_width(drive_bars[i],width);
        /* Red where a drive is nearly full, which is the one thing about a
         * drive somebody wants to see without reading. */
        lv_obj_set_style_bg_color(drive_bars[i],
                                  lv_color_hex(total&&used*10>=total*9?RED:BLUE),0);
    }
    if(no_drives){
        if(shown==0)lv_obj_remove_flag(no_drives,LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(no_drives,LV_OBJ_FLAG_HIDDEN);
    }
    /* The third page. */
    if(playing_name)
        lv_label_set_text(playing_name,
                          s->online&&s->playing[0]?s->playing:panel_text(TXT_NOTHING_PLAYING));
}
