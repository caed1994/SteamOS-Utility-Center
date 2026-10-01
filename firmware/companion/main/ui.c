// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
#include "icons.h"
#include "panel_text.h"
#include "panel_ui_sleep.h"
#include "panel_timer.h"

#define BG 0x0C1721
#define CARD 0x111F2B
#define EDGE 0x293D51
#define TEXT 0xEDF4FC
#define MUTED 0xAEC4DE
#define BLUE 0x49A8F7
#define RED 0xF06B79

static lv_obj_t *connection,*dot,*audio_status,*audio_toggle,*audio_knob,*volume,*brightness_label,*sleep_label,*message;
static lv_obj_t *controls[6],*overlay,*setup_screen,*setup_text,*cpu_value,*gpu_value,*power_value;
/* Not in controls[]: that table is indexed by the action, it holds the
 * six the service performs, and PANEL_WAKE is done by the panel. */
static lv_obj_t *wake_button,*wake_what;
/* The second and third pages. Not in controls[] either: that table is
 * indexed by the action and holds the six on the first page. */
static lv_obj_t *mode_now,*mode_button,*mode_caption,*playing_name,*achievement_count;
/* The room of the name on the third page: from under the line below "Now
 * playing" at 44 to the line over the achievements. */
#define NAME_TOP 45
#define NAME_ROOM 71
#define NAME_FONT (&lv_font_montserrat_26)
LV_FONT_DECLARE(panel_count_font);
static void name_show(const char *text);
static lv_obj_t *drive_rows[PANEL_DRIVES],*drive_names[PANEL_DRIVES];
static lv_obj_t *drive_bars[PANEL_DRIVES],*drive_free[PANEL_DRIVES];
static lv_obj_t *no_drives,*band,*esp_power,*wifi_mark;
/* The fourth page: the clock, and the timer under it. */
LV_FONT_DECLARE(panel_clock_font);
static lv_obj_t *clock_digits,*clock_date,*timer_value,*timer_minus,*timer_plus;
static lv_obj_t *timer_go,*timer_go_label,*timer_reset,*alarm_layer;
/* The timer itself is not part of the screen. panel_ui_create builds the
 * screen again when the language changes, and a timer that runs goes on
 * running through that. */
static panel_timer_t timer;
/* When a held + or - last counted on. LVGL repeats a held press every
 * 100 ms, and the steps of five come every TIMER_HOLD_EVERY_MS of those. */
static uint32_t hold_counted;
#define TIMER_HOLD_EVERY_MS 400
/* The alarm stays audible with the sound turned right down. */
#define ALARM_LEAST_VOLUME 40
_Static_assert(TXT_SATURDAY==TXT_SUNDAY+6,"the days of the week in a row, from Sunday as tm_wday counts");
_Static_assert(TXT_DECEMBER==TXT_JANUARY+11,"the months in a row");
static panel_action_cb_t send_action;
static panel_setting_cb_t save_setting;
static panel_sound_cb_t play_sound;
static panel_settings_t local;
static lv_obj_t *settings_screen, *sound_value, *sound_status;
/* The controllers in the head: two places, each an icon and a value, and
 * the whole of it one place to tap. */
#define PAD_HEAD 2
/* Where the two places stand in the head, from its left edge, and the room
 * of each value: "100 %" and the charge symbol, which check_pages
 * measures. */
#define PAD_HEAD_X 13
#define PAD_HEAD_STEP 118
#define PAD_VALUE_WIDTH 76
/* The cards of the page: four of them between the line under the title
 * and the bottom edge. */
#define PAD_CARD_TOP 78
#define PAD_CARD_STEP 96
#define PAD_CARD_HEIGHT 86
#define PAD_BAR_LEFT 56
#define PAD_BAR_WIDTH 368
static lv_obj_t *pad_area,*pad_icons[PAD_HEAD],*pad_values[PAD_HEAD];
/* The page of the controllers, one card for each of four. */
static lv_obj_t *pads_screen,*pads_none;
static lv_obj_t *pad_cards[PANEL_PADS],*pad_names[PANEL_PADS],*pad_levels[PANEL_PADS];
static lv_obj_t *pad_tracks[PANEL_PADS],*pad_bars[PANEL_PADS],*pad_unknown[PANEL_PADS];
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
/* What the slider for the sleep timeout stops at, in minutes.
 *
 * Stops and not every number between. A minute either way means nothing
 * at a quarter of an hour, and a slider that lands on 23 minutes reads
 * like a mistake. Nought is the first, because "never" belongs at the end
 * a slider starts from.
 *
 * The count of minutes is what is stored, not the place in this list. A
 * later firmware that offers other stops still reads what somebody picked
 * with this one. */
static const uint8_t sleep_choices[]={0,1,2,5,10,15,30,45,60};
#define SLEEP_CHOICES (int)(sizeof sleep_choices/sizeof *sleep_choices)

/* The nearest stop to a count of minutes.
 *
 * Nearest and not equal: the stored number comes from another firmware or
 * from a hand at nvs, and a value between two stops has to land on one of
 * them rather than on the first. */
static int sleep_index(int minutes)
{
    int best=0,gap=-1;
    for(int i=0;i<SLEEP_CHOICES;i++){
        int away=minutes>sleep_choices[i]?minutes-sleep_choices[i]
                                         :sleep_choices[i]-minutes;
        if(gap<0||away<gap){gap=away;best=i;}
    }
    return best;
}
static void sleep_words(char *out,size_t room,int minutes)
{
    if(minutes<=0)snprintf(out,room,"%s",panel_text(TXT_SLEEP_NEVER));
    else snprintf(out,room,"%d %s",minutes,panel_text(TXT_MINUTES));
}
static void setting_slider(lv_event_t *e)
{
    panel_setting_t key=(panel_setting_t)(intptr_t)lv_event_get_user_data(e);
    int value=lv_slider_get_value(lv_event_get_target(e));
    if(key==PANEL_BRIGHTNESS){local.brightness=value;lv_label_set_text_fmt(brightness_label,"%d %%",value);}
    else if(key==PANEL_SLEEP_AFTER){
        /* The slider stands on a place in the list; everything below this
         * line counts minutes. */
        char said[24];
        value=sleep_choices[value<0?0:value>=SLEEP_CHOICES?SLEEP_CHOICES-1:value];
        local.sleep_after=value;
        sleep_words(said,sizeof said,value);
        lv_label_set_text(sleep_label,said);
    }
    else {local.sound_volume=value;lv_label_set_text_fmt(sound_value,"%d %%",value);}
    bool save=lv_event_get_code(e)==LV_EVENT_RELEASED;
    if(save_setting)save_setting(key,value,save);
    if(save && key==PANEL_SOUND_VOLUME)feedback();
}
static void slider_range(lv_obj_t *parent,int y,int minimum,int maximum,int value,panel_setting_t key)
{
    lv_obj_t *slider=lv_slider_create(parent);lv_obj_set_pos(slider,28,y);lv_obj_set_size(slider,380,8);
    lv_slider_set_range(slider,minimum,maximum);lv_slider_set_value(slider,value,LV_ANIM_OFF);
    lv_obj_set_style_bg_color(slider,lv_color_hex(EDGE),LV_PART_MAIN);
    lv_obj_set_style_bg_color(slider,lv_color_hex(BLUE),LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(slider,lv_color_hex(TEXT),LV_PART_KNOB);
    lv_obj_set_style_pad_all(slider,7,LV_PART_KNOB);lv_obj_set_ext_click_area(slider,18);
    lv_obj_add_event_cb(slider,setting_slider,LV_EVENT_VALUE_CHANGED,(void *)(intptr_t)key);
    lv_obj_add_event_cb(slider,setting_slider,LV_EVENT_RELEASED,(void *)(intptr_t)key);
}
/* The two that run from a lowest value to a hundred, which is what a per
 * cent is. */
static void slider_at(lv_obj_t *parent,int y,int minimum,int value,panel_setting_t key)
{
    slider_range(parent,y,minimum,100,value,key);
}
static void tones_changed(lv_event_t *e)
{
    local.touch_tones=lv_obj_has_state(lv_event_get_target(e),LV_STATE_CHECKED);
    if(save_setting)save_setting(PANEL_TOUCH_TONES,local.touch_tones,true);
    feedback();
}
static void test_sound(lv_event_t *e){(void)e;if(play_sound)play_sound(local.sound_volume);}
/* Every pointer into the settings screen, dropped.
 *
 * One list and not four. The back button, the language button, the setup
 * screen and a rebuild all take the settings screen away, and each of
 * them kept its own list of labels to forget. The label of the sleep
 * timeout reached one of the four lists the day it was added and missed
 * the other three: a pointer to a deleted label in each, waiting for the
 * next thing to write to it.
 *
 * This only drops. A rebuild cleans the whole screen first and the
 * settings page goes with that clean, so deleting it again here would be
 * a second free of the same object. settings_forget below is for the
 * callers where the page is still there. */
static void settings_drop(void)
{
    settings_screen=NULL;
    brightness_label=NULL;sleep_label=NULL;sound_value=NULL;sound_status=NULL;
}
static void settings_forget(void)
{
    if(settings_screen)lv_obj_delete(settings_screen);
    settings_drop();
}
static void language_clicked(lv_event_t *e)
{
    (void)e;feedback();
    panel_language_t next=panel_text_language()==PANEL_ENGLISH?PANEL_GERMAN:PANEL_ENGLISH;
    panel_text_set(next);local.language=next;
    if(save_setting)save_setting(PANEL_LANGUAGE,(int)next,true);
    // Both screens are built one time, with the words of the language that
    // was current then. Every one of them is now wrong, so both are built
    // again. The person stays where they were, on the settings page.
    settings_forget();
    panel_ui_create(send_action,save_setting,play_sound,&local);
    panel_ui_settings_open();
}
static void settings_close(lv_event_t *e)
{
    (void)e;feedback();settings_forget();
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
    /* There is more here than a screen holds, so it scrolls. The band on
     * the main screen scrolls as well, so this is not a new thing to
     * learn. A slider takes the drag that lands on it, which is what
     * keeps the two apart. */
    lv_obj_add_flag(settings_screen,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(settings_screen,LV_DIR_VER);
    lv_obj_set_scrollbar_mode(settings_screen,LV_SCROLLBAR_MODE_AUTO);
    /* Two rows of the same shape. Each starts with its name, the line
     * under it 27 below, the slider 72 below, and 24 from the top of the
     * slider to whatever comes next: the line between the rows, or the
     * edge of the card. The second row was squeezed against the bottom
     * until the board showed it, and check_pages holds the two gaps
     * equal. */
    lv_obj_t *display=panel(settings_screen,20,78,440,228,CARD,true);
    icon(display,&icon_sun,16,18,MUTED);
    text_at(display,panel_text(TXT_BRIGHTNESS),62,16,268,&lv_font_montserrat_18,TEXT);
    brightness_label=text_at(display,"",338,16,88,&lv_font_montserrat_18,BLUE);
    lv_label_set_text_fmt(brightness_label,"%d %%",local.brightness);
    text_at(display,panel_text(TXT_BRIGHTNESS_WHAT),62,43,350,&lv_font_montserrat_12,MUTED);
    slider_at(display,88,5,local.brightness,PANEL_BRIGHTNESS);
    line(display,18,112,402,1);
    text_at(display,panel_text(TXT_SLEEP_AFTER),20,128,268,&lv_font_montserrat_18,TEXT);
    sleep_label=text_at(display,"",318,128,108,&lv_font_montserrat_18,BLUE);
    {
        char said[24];
        sleep_words(said,sizeof said,local.sleep_after);
        lv_label_set_text(sleep_label,said);
    }
    text_at(display,panel_text(TXT_SLEEP_AFTER_WHAT),20,155,404,&lv_font_montserrat_12,MUTED);
    slider_range(display,200,0,SLEEP_CHOICES-1,sleep_index(local.sleep_after),
                 PANEL_SLEEP_AFTER);
    lv_obj_t *sound=panel(settings_screen,20,320,440,216,CARD,true);
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
    /* The setup, which used to stand in a corner of the main screen.
     *
     * It is not an everyday button. It takes the panel off the network
     * until somebody finishes it, and a corner of the main screen is where
     * a stray finger lands. It still asks before it starts, the same
     * question as before, and the setup screen that follows closes this
     * one: see settings_forget in panel_ui_update. */
    lv_obj_t *link=panel(settings_screen,20,550,440,84,CARD,true);
    text_at(link,panel_text(TXT_CONNECTION),20,16,240,&lv_font_montserrat_18,TEXT);
    text_at(link,panel_text(TXT_SETUP_WHAT),20,44,240,&lv_font_montserrat_12,MUTED);
    button(link,panel_text(TXT_SETUP),276,20,144,44,clicked,PANEL_SETUP);
    text_at(settings_screen,panel_text(TXT_AUTOSAVE),22,648,440,&lv_font_montserrat_12,MUTED);
}
static void settings_clicked(lv_event_t *e){(void)e;feedback();panel_ui_settings_open();}
/* What a controller says in the head and on its card: the battery, the
 * charge symbol while it charges, and "--" where nobody reports one. */
static void pad_level(char *out,size_t room,const panel_pad_t *pad)
{
    if(pad->battery<0)snprintf(out,room,"-- %%");
    else snprintf(out,room,"%d %%%s",pad->battery,pad->charging?" " LV_SYMBOL_CHARGE:"");
}
/* How many controllers to draw. The list of a PC that does not answer is
 * the list of the last answer, and that is no list to show. */
static int pads_known(const panel_state_t *s)
{
    if(!s->online)return 0;
    return s->pad_count<0?0:s->pad_count>PANEL_PADS?PANEL_PADS:s->pad_count;
}
static void pads_head(const panel_state_t *s)
{
    if(!pad_area)return;
    int count=pads_known(s);
    for(int i=0;i<PAD_HEAD;i++){
        /* The first place shows "--" with no controller at all, so the
         * head says that there is none. The second is there only for a
         * second controller. */
        bool shown=i==0||i<count;
        if(shown){
            lv_obj_remove_flag(pad_icons[i],LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(pad_values[i],LV_OBJ_FLAG_HIDDEN);
        }else{
            lv_obj_add_flag(pad_icons[i],LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(pad_values[i],LV_OBJ_FLAG_HIDDEN);
        }
        char said[24];
        if(i<count)pad_level(said,sizeof said,&s->pads[i]);
        else snprintf(said,sizeof said,"-- %%");
        lv_label_set_text(pad_values[i],said);
    }
}
/* Every pointer into the page of the controllers, dropped. The same rule
 * as settings_drop: this only drops, and pads_forget deletes as well. */
static void pads_drop(void)
{
    pads_screen=NULL;pads_none=NULL;
    for(int i=0;i<PANEL_PADS;i++){
        pad_cards[i]=NULL;pad_names[i]=NULL;pad_levels[i]=NULL;
        pad_tracks[i]=NULL;pad_bars[i]=NULL;pad_unknown[i]=NULL;
    }
}
static void pads_forget(void)
{
    if(pads_screen)lv_obj_delete(pads_screen);
    pads_drop();
}
static void pads_show(const panel_state_t *s)
{
    if(!pads_screen)return;
    int count=pads_known(s);
    lv_label_set_text(pads_none,panel_text(s->online?TXT_NO_PADS:TXT_PC_OFFLINE));
    if(count>0)lv_obj_add_flag(pads_none,LV_OBJ_FLAG_HIDDEN);
    else lv_obj_remove_flag(pads_none,LV_OBJ_FLAG_HIDDEN);
    for(int i=0;i<PANEL_PADS;i++){
        if(i>=count){lv_obj_add_flag(pad_cards[i],LV_OBJ_FLAG_HIDDEN);continue;}
        const panel_pad_t *pad=&s->pads[i];
        char said[24];
        lv_obj_remove_flag(pad_cards[i],LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(pad_names[i],pad->name);
        pad_level(said,sizeof said,pad);
        lv_label_set_text(pad_levels[i],said);
        /* A bar for a battery, and words for a controller with none: an
         * empty bar reads as a flat battery. */
        if(pad->battery<0){
            lv_obj_add_flag(pad_tracks[i],LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(pad_unknown[i],LV_OBJ_FLAG_HIDDEN);
        }else{
            lv_obj_remove_flag(pad_tracks[i],LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(pad_unknown[i],LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_width(pad_bars[i],PAD_BAR_WIDTH*pad->battery/100);
        }
    }
}
static void pads_close(lv_event_t *e){(void)e;feedback();pads_forget();}
void panel_ui_pads_open(void)
{
    if(pads_screen||settings_screen||setup_screen)return;
    pads_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
    button(pads_screen,panel_text(TXT_BACK),12,8,112,44,pads_close,0);
    text_at(pads_screen,panel_text(TXT_CONTROLLERS),136,20,200,&lv_font_montserrat_20,TEXT);
    line(pads_screen,0,62,480,1);
    pads_none=text_at(pads_screen,"",20,220,440,&lv_font_montserrat_18,MUTED);
    center_text(pads_none);
    for(int i=0;i<PANEL_PADS;i++){
        lv_obj_t *card=panel(pads_screen,20,PAD_CARD_TOP+i*PAD_CARD_STEP,440,PAD_CARD_HEIGHT,CARD,true);
        lv_obj_remove_flag(card,LV_OBJ_FLAG_CLICKABLE);
        pad_cards[i]=card;
        icon(card,&icon_gamepad_2,16,16,MUTED);
        pad_names[i]=text_at(card,"",56,16,250,&lv_font_montserrat_18,TEXT);
        pad_levels[i]=text_at(card,"",306,16,118,&lv_font_montserrat_18,BLUE);
        lv_obj_set_style_text_align(pad_levels[i],LV_TEXT_ALIGN_RIGHT,0);
        pad_tracks[i]=panel(card,PAD_BAR_LEFT,54,PAD_BAR_WIDTH,10,EDGE,false);
        lv_obj_set_style_radius(pad_tracks[i],LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(pad_tracks[i],LV_OBJ_FLAG_CLICKABLE);
        pad_bars[i]=panel(pad_tracks[i],0,0,0,10,BLUE,false);
        lv_obj_set_style_radius(pad_bars[i],LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(pad_bars[i],LV_OBJ_FLAG_CLICKABLE);
        pad_unknown[i]=text_at(card,panel_text(TXT_NO_BATTERY),PAD_BAR_LEFT,50,PAD_BAR_WIDTH,&lv_font_montserrat_14,MUTED);
        lv_obj_add_flag(card,LV_OBJ_FLAG_HIDDEN);
    }
    /* What the last update said, at once. panel_ui_update draws nothing
     * for a state it saw before, so the page waits for no change. */
    if(last_state_valid)pads_show(&last_state);
}
static void pads_clicked(lv_event_t *e){(void)e;feedback();panel_ui_pads_open();}
const char *panel_ui_where(void)
{
    if(setup_screen)return "the setup";
    if(overlay)return "a question";
    if(settings_screen)return "the settings";
    if(pads_screen)return "the controllers";
    if(!band)return "no screen";
    /* Read from where the band stands: a swipe that did not carry far
     * enough left it on the page it was on. */
    static const char *const pages[PANEL_PAGES]={"the first page","the second page",
                                                 "the third page","the fourth page"};
    int32_t page=(lv_obj_get_scroll_x(band)+240)/480;
    if(page<0)page=0;
    if(page>PANEL_PAGES-1)page=PANEL_PAGES-1;
    return pages[page];
}

/* A label set only when its text is new. LVGL draws a label again at each
 * set, and the timer and the clock are asked five times a second. */
static void set_text(lv_obj_t *label,const char *text)
{
    if(label&&strcmp(lv_label_get_text(label),text)!=0)lv_label_set_text(label,text);
}
static void enable(lv_obj_t *o,bool on)
{
    if(!o)return;
    if(on)lv_obj_remove_state(o,LV_STATE_DISABLED);else lv_obj_add_state(o,LV_STATE_DISABLED);
}
/* What the timer shows: what is left in minutes and seconds, a second
 * rounded up, so a timer of five minutes starts at 05:00 and reaches 00:00
 * as it goes off. + and - stay usable while it is idle or paused, and the
 * start turns into a pause while it runs. */
static void timer_show(void)
{
    if(!timer_value)return;
    uint32_t left=panel_timer_left_ms(&timer,lv_tick_get());
    unsigned seconds=(unsigned)((left+999u)/1000u);
    char text[16];
    snprintf(text,sizeof text,"%02u:%02u",seconds/60u,seconds%60u);
    set_text(timer_value,text);
    bool still=timer.phase==PANEL_TIMER_IDLE||timer.phase==PANEL_TIMER_PAUSED;
    enable(timer_minus,still&&left>0);
    enable(timer_plus,still&&left<(uint32_t)PANEL_TIMER_MAX_MIN*60u*1000u);
    enable(timer_go,timer.phase==PANEL_TIMER_RUNNING||(still&&left>0));
    set_text(timer_go_label,panel_text(timer.phase==PANEL_TIMER_RUNNING?TXT_PAUSE:TXT_START));
    enable(timer_reset,timer.phase!=PANEL_TIMER_IDLE||left>0);
}
/* + and -, a tap and a press that is held. A tap is SHORT_CLICKED, which
 * LVGL sends only for a press that did not turn long, so the release of a
 * held press adds nothing. CLICKED comes after both and is left alone. */
static void timer_step(lv_event_t *e)
{
    lv_event_code_t code=lv_event_get_code(e);
    int sign=(int)(intptr_t)lv_event_get_user_data(e);
    int minutes=0;
    if(code==LV_EVENT_SHORT_CLICKED)minutes=PANEL_TIMER_TAP_MIN;
    else if(code==LV_EVENT_LONG_PRESSED){
        minutes=PANEL_TIMER_HOLD_MIN;hold_counted=lv_tick_get();
    }else if(code==LV_EVENT_LONG_PRESSED_REPEAT&&lv_tick_elaps(hold_counted)>=TIMER_HOLD_EVERY_MS){
        minutes=PANEL_TIMER_HOLD_MIN;hold_counted=lv_tick_get();
    }
    if(minutes&&panel_timer_adjust(&timer,sign*minutes)){feedback();timer_show();}
}
static void timer_go_clicked(lv_event_t *e)
{
    (void)e;
    uint32_t now=lv_tick_get();
    if(timer.phase==PANEL_TIMER_RUNNING)panel_timer_pause(&timer,now);
    else panel_timer_start(&timer,now);
    feedback();timer_show();
}
static void timer_reset_clicked(lv_event_t *e){(void)e;panel_timer_reset(&timer);feedback();timer_show();}
static void alarm_hide(void){if(alarm_layer){lv_obj_delete(alarm_layer);alarm_layer=NULL;}}
static void alarm_clicked(lv_event_t *e){(void)e;panel_ui_timer_stop();}
/* Over everything else on the screen, the settings and a question too,
 * because the timer that rings may not be the page somebody is on. A tap
 * anywhere on it stops it, and so does the button of the panel: see
 * ui_tick in main.c. */
static void alarm_show(void)
{
    if(alarm_layer)return;
    alarm_layer=panel(lv_screen_active(),0,0,480,480,BG,false);
    lv_obj_set_style_bg_opa(alarm_layer,LV_OPA_90,0);
    lv_obj_add_event_cb(alarm_layer,alarm_clicked,LV_EVENT_CLICKED,NULL);
    /* The card takes no press of its own, so a press on it reaches the
     * layer under it. */
    lv_obj_t *box=panel(alarm_layer,20,112,440,256,CARD,true);
    lv_obj_remove_flag(box,LV_OBJ_FLAG_CLICKABLE);
    center_text(text_at(box,panel_text(TXT_TIMER),20,26,400,&lv_font_montserrat_20,MUTED));
    center_text(text_at(box,panel_text(TXT_TIME_UP),20,64,400,&lv_font_montserrat_32,TEXT));
    lv_obj_t *stop=button(box,panel_text(TXT_STOP),70,152,300,72,alarm_clicked,0);
    lv_obj_set_style_bg_color(stop,lv_color_hex(BLUE),0);
    lv_obj_set_style_text_color(stop,lv_color_hex(BG),0);
    lv_obj_set_style_text_font(stop,&lv_font_montserrat_24,0);
}
panel_timer_news_t panel_ui_timer_tick(void)
{
    panel_timer_news_t news=panel_timer_tick(&timer,lv_tick_get());
    if(news.went_off)alarm_show();
    if(news.gave_up)alarm_hide();
    timer_show();
    return news;
}
bool panel_ui_timer_stop(void)
{
    if(!panel_timer_stop(&timer))return false;
    alarm_hide();
    timer_show();
    return true;
}
bool panel_ui_timer_ringing(void){return timer.phase==PANEL_TIMER_RINGING;}
int panel_ui_alarm_volume(void)
{
    return local.sound_volume>ALARM_LEAST_VOLUME?local.sound_volume:ALARM_LEAST_VOLUME;
}
/* How a drive row sits in its card.
 *
 * The card is 460 across. The icon and the line above it stand 14 in from
 * the left, so a row that starts at nought sits against the border on one
 * side and a long way off it on the other. Reported from the board, and it
 * is the same 14 on both sides now.
 *
 * The width is one name with two readers: this builds the track and
 * panel_ui_update fills it. Two numbers here drift apart, and a bar that
 * is full at nine tenths is a bar nobody can read. */
#define DRIVE_MARGIN 14
#define DRIVE_BAR_WIDTH (460 - 2 * DRIVE_MARGIN)
/* One drive, as a name, a bar and what is left of it. */
static void drive_row(lv_obj_t *parent,int index,int y)
{
    drive_rows[index]=panel(parent,DRIVE_MARGIN,y,DRIVE_BAR_WIDTH,44,CARD,false);
    lv_obj_set_style_bg_opa(drive_rows[index],LV_OPA_TRANSP,0);
    lv_obj_remove_flag(drive_rows[index],LV_OBJ_FLAG_CLICKABLE);
    drive_names[index]=text_at(drive_rows[index],"",0,0,150,&lv_font_montserrat_16,TEXT);
    drive_free[index]=text_at(drive_rows[index],"",152,0,DRIVE_BAR_WIDTH-152,&lv_font_montserrat_14,MUTED);
    lv_obj_set_style_text_align(drive_free[index],LV_TEXT_ALIGN_RIGHT,0);
    lv_obj_t *track=panel(drive_rows[index],0,26,DRIVE_BAR_WIDTH,10,EDGE,false);
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
    settings_drop();
    /* The page of the controllers too, for the same reason. */
    pads_drop();
    /* The band and everything on the second and third pages are children
     * of this screen too. A pointer kept past the clean above is a pointer
     * to freed memory, and panel_ui_update writes through these. */
    band=NULL;mode_now=NULL;mode_button=NULL;mode_caption=NULL;
    playing_name=NULL;achievement_count=NULL;no_drives=NULL;esp_power=NULL;wifi_mark=NULL;
    clock_digits=NULL;clock_date=NULL;timer_value=NULL;timer_minus=NULL;timer_plus=NULL;
    timer_go=NULL;timer_go_label=NULL;timer_reset=NULL;alarm_layer=NULL;
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
    line(s,234,16,1,28);
    /* The controllers, two side by side over the whole right of the head,
     * with no caption: the icon says what the number is. The value stands
     * at the height of the middle of its icon. A tap anywhere on the two
     * opens the page of the controllers, which has room for four. */
    pad_area=panel(s,235,0,245,57,BG,false);
    lv_obj_set_style_bg_opa(pad_area,LV_OPA_TRANSP,0);
    lv_obj_set_style_bg_color(pad_area,lv_color_hex(EDGE),LV_STATE_PRESSED);
    lv_obj_set_style_bg_opa(pad_area,LV_OPA_40,LV_STATE_PRESSED);
    lv_obj_add_event_cb(pad_area,pads_clicked,LV_EVENT_CLICKED,NULL);
    {
        int32_t high=lv_font_get_line_height(&lv_font_montserrat_16);
        for(int i=0;i<PAD_HEAD;i++){
            int x=PAD_HEAD_X+i*PAD_HEAD_STEP;
            pad_icons[i]=icon(pad_area,&icon_gamepad_2,x,19,MUTED);
            lv_obj_remove_flag(pad_icons[i],LV_OBJ_FLAG_CLICKABLE);
            pad_values[i]=text_at(pad_area,"-- %",x+32,19+12-high/2,PAD_VALUE_WIDTH,&lv_font_montserrat_16,TEXT);
            lv_obj_remove_flag(pad_values[i],LV_OBJ_FLAG_CLICKABLE);
        }
        lv_obj_add_flag(pad_icons[1],LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(pad_values[1],LV_OBJ_FLAG_HIDDEN);
    }
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
    lv_obj_t *page[PANEL_PAGES];
    for(int i=0;i<PANEL_PAGES;i++){
        page[i]=panel(band,i*480,0,480,300,BG,false);
        lv_obj_set_style_bg_opa(page[i],LV_OPA_TRANSP,0);
        lv_obj_remove_flag(page[i],LV_OBJ_FLAG_CLICKABLE);
    }
    /* No marks under the band for the page on the screen. There were
     * three, and its owner found them of no use and not good to look at.
     * check_pages holds the room between the band and the sensors empty. */
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
    no_drives=text_at(disk_card,panel_text(TXT_NO_DRIVES),DRIVE_MARGIN,70,DRIVE_BAR_WIDTH,&lv_font_montserrat_14,MUTED);
    lv_obj_add_flag(no_drives,LV_OBJ_FLAG_HIDDEN);
    /* The third page: what is on the machine. One card and one name, and
     * the room under it is deliberate: the picture Steam already keeps for
     * every game goes there, and that is a step of its own. */
    lv_obj_t *play_card=panel(page[2],10,0,460,300,CARD,true);
    icon(play_card,&icon_gamepad_2,14,14,MUTED);
    text_at(play_card,panel_text(TXT_PLAYING),52,16,240,&lv_font_montserrat_14,MUTED);
    line(play_card,14,44,432,1);
    /* The name of the game, in the middle of the room between the two
     * lines. See name_show, which also keeps it to two lines. */
    playing_name=text_at(play_card,"",20,NAME_TOP,420,NAME_FONT,TEXT);
    center_text(playing_name);
    lv_label_set_long_mode(playing_name,LV_LABEL_LONG_DOT);
    name_show(panel_text(TXT_NOTHING_PLAYING));
    /* The achievements of that game, where a mockup once had a frame
     * rate. The rate had no clean source on the PC; these come out of the
     * page the Steam client keeps for each game. See
     * steamapps.achievements.
     *
     * A name and a large number under it, the pair in the middle of the
     * room under the line. The number is Montserrat Medium like every other
     * text on this panel, at 64: larger than any size LVGL ships, so the
     * font is one of this firmware's own, with only the glyphs a count
     * needs. See panel_count_font.c. */
    line(play_card,14,NAME_TOP+NAME_ROOM,432,1);
    center_text(text_at(play_card,panel_text(TXT_ACHIEVEMENTS),20,160,420,&lv_font_montserrat_20,MUTED));
    achievement_count=text_at(play_card,"--",20,196,420,&panel_count_font,TEXT);
    center_text(achievement_count);
    /* The fourth page: the time of day, and a timer under it.
     *
     * The digits of the clock are Montserrat Medium at 96, one more font of
     * this firmware's own with only what a clock needs. See
     * panel_clock_font.c. What is left of the timer uses the font of the
     * achievements, which holds ":" for this. */
    lv_obj_t *clock_card=panel(page[3],10,0,460,136,CARD,true);
    clock_digits=text_at(clock_card,"--:--",20,14,420,&panel_clock_font,TEXT);
    center_text(clock_digits);
    clock_date=text_at(clock_card,panel_text(TXT_CLOCK_UNSET),20,96,420,&lv_font_montserrat_18,MUTED);
    center_text(clock_date);
    lv_obj_t *timer_card=panel(page[3],10,146,460,154,CARD,true);
    timer_minus=button(timer_card,LV_SYMBOL_MINUS,14,14,84,72,timer_step,-1);
    timer_plus=button(timer_card,LV_SYMBOL_PLUS,362,14,84,72,timer_step,1);
    lv_obj_t *steps[]={timer_minus,timer_plus};
    for(int i=0;i<2;i++){
        lv_obj_set_style_text_font(steps[i],&lv_font_montserrat_24,0);
        void *sign=(void *)(intptr_t)(i?1:-1);
        lv_obj_add_event_cb(steps[i],timer_step,LV_EVENT_SHORT_CLICKED,sign);
        lv_obj_add_event_cb(steps[i],timer_step,LV_EVENT_LONG_PRESSED,sign);
        lv_obj_add_event_cb(steps[i],timer_step,LV_EVENT_LONG_PRESSED_REPEAT,sign);
    }
    timer_value=text_at(timer_card,"00:00",98,20,264,&panel_count_font,TEXT);
    center_text(timer_value);
    timer_go=button(timer_card,panel_text(TXT_START),14,96,212,44,timer_go_clicked,0);
    timer_go_label=lv_obj_get_child(timer_go,0);
    timer_reset=button(timer_card,panel_text(TXT_RESET),234,96,212,44,timer_reset_clicked,0);
    timer_show();
    /* A new screen for a new language, while the timer rings. */
    if(timer.phase==PANEL_TIMER_RINGING)alarm_show();
    lv_obj_t *foot=panel(s,10,386,460,48,CARD,true);
    icon(foot,&icon_cpu,12,12,MUTED);text_at(foot,"CPU",45,6,99,&lv_font_montserrat_12,MUTED);cpu_value=text_at(foot,"-- C",45,22,99,&lv_font_montserrat_18,BLUE);
    line(foot,151,9,1,30);icon(foot,&icon_circuit_board,165,12,MUTED);text_at(foot,"GPU",198,6,99,&lv_font_montserrat_12,MUTED);gpu_value=text_at(foot,"-- C",198,22,99,&lv_font_montserrat_18,BLUE);
    line(foot,304,9,1,30);icon(foot,&icon_zap,318,12,MUTED);text_at(foot,"GPU-WATT",350,6,98,&lv_font_montserrat_12,MUTED);power_value=text_at(foot,"-- W",350,22,98,&lv_font_montserrat_18,BLUE);
    /* The bottom row: the settings on the left, what the panel has to
     * say in the middle, and the state of the panel itself on the right.
     *
     * The settings sit where a left thumb finds them. The caption goes to
     * the left edge of its button and not the middle, so it lines up with
     * the edge of the card above it. */
    lv_obj_t *settings_button=button(s,panel_text(TXT_SETTINGS),0,436,150,44,settings_clicked,0);
    lv_obj_set_style_bg_opa(settings_button,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(settings_button,0,0);
    lv_obj_set_style_text_font(settings_button,&lv_font_montserrat_14,0);
    lv_obj_align(lv_obj_get_child(settings_button,0),LV_ALIGN_LEFT_MID,12,0);
    /* Empty unless there is something to say. See the poll in main.c:
     * the state of the connection is the mark on the right now, and what
     * reaches this line is what a mark cannot say. */
    message=text_at(s,"",150,451,180,&lv_font_montserrat_12,MUTED);
    lv_obj_set_height(message,18);
    lv_obj_set_style_text_align(message,LV_TEXT_ALIGN_CENTER,0);
    lv_label_set_long_mode(message,LV_LABEL_LONG_DOT);
    lv_obj_add_flag(message,LV_OBJ_FLAG_HIDDEN);
    /* The network and then the battery, side by side from the right edge.
     *
     * A row that lays itself out, because the battery is a different width
     * at 5 and at 100 per cent and is not there at all on a board whose
     * power chip did not answer. The network mark stays against the
     * battery in every one of those, and against the edge when there is
     * no battery to stand against. */
    lv_obj_t *status=lv_obj_create(s);
    lv_obj_remove_style_all(status);
    lv_obj_set_pos(status,330,436);lv_obj_set_size(status,136,44);
    lv_obj_remove_flag(status,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(status,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_flex_flow(status,LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(status,LV_FLEX_ALIGN_END,LV_FLEX_ALIGN_CENTER,LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(status,10,0);
    wifi_mark=lv_label_create(status);
    lv_label_set_text(wifi_mark,LV_SYMBOL_WIFI);
    lv_obj_set_style_text_font(wifi_mark,&lv_font_montserrat_14,0);
    /* Red until the network is joined, which is the one state of it that
     * asks for a look. */
    lv_obj_set_style_text_color(wifi_mark,lv_color_hex(RED),0);
    /* The battery of this panel, and not of the controller: that one has
     * its place at the top. Hidden until the power chip answers. */
    esp_power=lv_label_create(status);
    lv_label_set_text(esp_power,"");
    lv_obj_set_style_text_font(esp_power,&lv_font_montserrat_14,0);
    lv_obj_set_style_text_color(esp_power,lv_color_hex(MUTED),0);
    lv_obj_add_flag(esp_power,LV_OBJ_FLAG_HIDDEN);
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
/* The name of the game, one line or two, in the middle of its room.
 *
 * An LVGL label centres across and not up and down, so a single line
 * would sit at the top of a box made for two. The text is measured
 * instead, and the label is made one line or two lines tall and placed in
 * the middle of the room between the line under "Now playing" and the
 * line over the achievements. Past two lines the rest is cut with an
 * ellipsis: a long name used to have the whole card, and it now stops
 * short of the count. */
static void name_show(const char *text)
{
    if(!playing_name)return;
    int32_t line=lv_font_get_line_height(NAME_FONT);
    lv_point_t size;
    lv_text_get_size(&size,text,NAME_FONT,0,0,420,LV_TEXT_FLAG_NONE);
    int32_t lines=size.y>line?2:1;
    lv_obj_set_height(playing_name,lines*line);
    lv_obj_set_y(playing_name,NAME_TOP+(NAME_ROOM-lines*line)/2);
    lv_label_set_text(playing_name,text);
}
/* The battery of this panel, in the corner of the main screen.
 *
 * Read off the panel itself and not off the PC, so it does not wait for
 * online the way the numbers beside it do: a panel on its battery with
 * the PC off is exactly the case where somebody wants to see it.
 *
 * A symbol of the level beside the number, in five steps, because a
 * glance at a corner reads a shape before a figure. The cable is a plug
 * and no number, because a board with no cell behind the chip has
 * nothing to count. */
static void esp_power_show(const panel_state_t *s)
{
    if(!esp_power)return;
    if(s->esp_supply==PANEL_SUPPLY_UNKNOWN){
        lv_obj_add_flag(esp_power,LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_remove_flag(esp_power,LV_OBJ_FLAG_HIDDEN);
    if(s->esp_supply==PANEL_SUPPLY_CABLE){
        lv_label_set_text(esp_power,LV_SYMBOL_USB);
        return;
    }
    int level=s->esp_battery<0?0:s->esp_battery>100?100:s->esp_battery;
    const char *shape=level>=90?LV_SYMBOL_BATTERY_FULL
                     :level>=65?LV_SYMBOL_BATTERY_3
                     :level>=40?LV_SYMBOL_BATTERY_2
                     :level>=15?LV_SYMBOL_BATTERY_1
                     :LV_SYMBOL_BATTERY_EMPTY;
    lv_label_set_text_fmt(esp_power,"%s%s %d %%",
                          s->esp_charging?LV_SYMBOL_CHARGE " ":"",shape,level);
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
        settings_forget();pads_forget();
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
    pads_head(s);
    pads_show(s);
    esp_power_show(s);
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
    if(s->message[0])lv_obj_remove_flag(message,LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(message,LV_OBJ_FLAG_HIDDEN);
    /* The mark for the network. It answers one question, whether the panel
     * is on the network, and leaves whether the PC answers to the dot at
     * the top: a mark that meant both would say nothing about either. */
    if(wifi_mark)lv_obj_set_style_text_color(wifi_mark,
        lv_color_hex(s->wifi?MUTED:RED),0);
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
        int width=total?(int)((used*DRIVE_BAR_WIDTH)/total):0;
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
        name_show(s->online&&s->playing[0]?s->playing:panel_text(TXT_NOTHING_PLAYING));
    /* A dash for nothing to count, the same dash the temperatures show.
     * Nought of sixty is a real answer about a game, and no game is not
     * that answer. */
    if(achievement_count){
        if(s->online&&s->playing[0]&&s->achievements_total>0)
            lv_label_set_text_fmt(achievement_count,"%d / %d",
                                  s->achievements_done,s->achievements_total);
        else lv_label_set_text(achievement_count,"--");
    }
    /* The fourth page: the time, and the date under it, or dashes and a
     * word until the network has set the clock. */
    if(clock_digits){
        bool known=s->clock_set&&s->weekday>=0&&s->weekday<=6&&s->month>=1&&s->month<=12;
        char text[64];
        if(known)snprintf(text,sizeof text,"%02d:%02d",s->hour,s->minute);
        else snprintf(text,sizeof text,"--:--");
        set_text(clock_digits,text);
        if(known)snprintf(text,sizeof text,panel_text(TXT_DATE_FORMAT),
                          panel_text((panel_text_id_t)(TXT_SUNDAY+s->weekday)),s->day,
                          panel_text((panel_text_id_t)(TXT_JANUARY+s->month-1)));
        else snprintf(text,sizeof text,"%s",panel_text(TXT_CLOCK_UNSET));
        set_text(clock_date,text);
    }
}
