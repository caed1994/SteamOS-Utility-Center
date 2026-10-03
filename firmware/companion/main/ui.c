// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
#include "icons.h"
#include "panel_frames.h"
#include "panel_text.h"
#include "panel_ui_sleep.h"
#include "panel_timer.h"
#include "panel_fonts.h"
#include "panel_update.h"

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
#define NAME_FONT (&panel_font_26)
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
/* The fifth page: the card, and the history of the temperatures and the
 * power under it. See panel_history.h. The history is main.c's and
 * outlives a new screen; the objects are children of the screen and go
 * with a clean, and so does what was drawn. */
static panel_history_t *history;
static uint32_t history_answers,history_drawn;
static bool history_stale=true;
/* The window the page shows, in minutes. Not stored: a restart starts the
 * history again in any case. */
static int history_minutes=30;
#define HISTORY_WINDOWS 3
static const int history_windows[HISTORY_WINDOWS]={15,30,60};
static lv_obj_t *gpu_load_value,*gpu_load_track,*gpu_load_bar,*vram_value,*vram_track,*vram_bar,*gpu_clock_value;
/* Cooling Boost, under the clock of the card: the field that takes the tap,
 * and the track and the knob of its switch. boost_shown is what they show,
 * -1 for nothing yet, 0 off and 1 on, so that only a change goes to LVGL. */
static lv_obj_t *boost_field,*boost_track,*boost_knob;
static int boost_shown=-1;
static lv_obj_t *history_chart,*history_empty,*history_ago,*history_axis[4],*history_buttons[HISTORY_WINDOWS];
static lv_chart_series_t *history_series[PANEL_HISTORY_SERIES];
/* The colours of the three curves, and the legend that names them. The
 * processor in the blue of the tiles; the card in orange and its power in
 * green, which read apart from the blue and from each other. */
#define CURVE_GPU 0xF5A25D
#define CURVE_WATTS 0x70C256
static const uint32_t curve_colors[PANEL_HISTORY_SERIES]={BLUE,CURVE_GPU,CURVE_WATTS};
/* The card of the GPU: three columns, each a name, a value and, for the
 * load and the memory, a bar. The room of each value is its longest at
 * 24 px, which check_pages measures: "100 %", the 162 px of "23.9 / 24.0
 * GB" and "2450 MHz". The chart under it: its place in its card, with the
 * degrees on the left of it and the watts on the right. */
#define GPU_COLUMN_X0 16
#define GPU_COLUMN_X1 146
#define GPU_COLUMN_X2 326
#define GPU_BAR_WIDTH 116
/* The row of Cooling Boost under the clock of the card: from 62 down to the
 * border, around the line of the bars at 72, and its switch. "Cooling Boost"
 * takes 85 of the 126 of the column in the 12 point font, and the switch
 * takes the rest but a gap of 5. */
#define BOOST_Y 62
#define BOOST_HEIGHT 30
#define BOOST_TRACK_WIDTH 36
#define BOOST_TRACK_HEIGHT 20
#define BOOST_KNOB_OFF 2
#define BOOST_KNOB_ON (BOOST_TRACK_WIDTH-BOOST_TRACK_HEIGHT+2)
#define CHART_X 52
#define CHART_Y 66
#define CHART_WIDTH 356
#define CHART_HEIGHT 92
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
#define PAD_NAME_WIDTH 250
#define PAD_BAR_WIDTH 368
static lv_obj_t *pad_area,*pad_icons[PAD_HEAD],*pad_values[PAD_HEAD];
/* The page of the panel itself: its firmware, an update when the PC offers
 * one, its network and its power. A column, so the card of the update
 * takes no room while there is none. */
enum { SELF_VERSION, SELF_UPTIME, SELF_MEMORY,
       SELF_WIFI, SELF_SIGNAL, SELF_IP, SELF_MAC, SELF_SERVER,
       SELF_CHARGE, SELF_SUPPLY, SELF_VBAT, SELF_PHASE, SELF_VBUS,
       SELF_VSYS, SELF_DIE, SELF_HELD,
       SELF_CHARGE_MA, SELF_CHARGE_MV, SELF_INPUT_MA,
       SELF_FPS, SELF_INTERVAL, SELF_DRAW, SELF_LEAD, SELF_PERIODS, SELF_ROWS };
/* The phases of the charge in a row, as the power chip counts them: see
 * panel_power_detail_t. */
_Static_assert(TXT_PHASE_IDLE==TXT_PHASE_TRICKLE+5,"the six phases of the charge in a row");
static lv_obj_t *self_screen,*self_values[SELF_ROWS];
static lv_obj_t *update_card,*update_offered,*update_note,*update_button;
/* The screen over everything while an update writes, which nothing closes:
 * the panel restarts at its end, or the page says why it did not. */
static lv_obj_t *update_layer,*update_title,*update_bar,*update_percent,*update_hint;
/* The order of the pages of the band: the page at each place, the pages
 * that are hidden, and the pages themselves, which stand at their place in
 * the band. See panel_pages.h. */
static uint8_t page_order[PANEL_PAGES];
static uint32_t page_hidden;
static lv_obj_t *band_pages[PANEL_PAGES];
/* The screen that puts them in order: a row for each place, with the name
 * of the page there, a button that hides or shows it, and a button up and
 * one down. */
static lv_obj_t *arrange_screen,*arrange_names[PANEL_PAGES],*arrange_starts[PANEL_PAGES];
static lv_obj_t *arrange_eyes[PANEL_PAGES],*arrange_up[PANEL_PAGES],*arrange_down[PANEL_PAGES];
static const panel_text_id_t page_names[PANEL_PAGES]={TXT_PAGE_CONTROLS,TXT_PAGE_SESSION,
    TXT_PLAYING,TXT_PAGE_CLOCK,TXT_PAGE_CARD,TXT_PAGE_LED,TXT_PAGE_CPU};
static void arrange_forget(void);
/* The layer of the colour and the brightness of the LED bar. See look_open. */
static lv_obj_t *look_layer;
/* The menu that chooses the sensor of a tile, and which tile it is for. */
static lv_obj_t *sensor_layer;
static bool sensor_gpu;
/* The key of each row of the open menu, kept when it opens: a new state
 * while it is open can bring the list in another order. */
static uint32_t sensor_keys[PANEL_SENSORS+1];
/* The left of the head, the PC and its connection, which opens the page of
 * the PC. */
static lv_obj_t *pc_area;
/* The page of the PC: three cards, the system, the hardware and the
 * network, with a row for each thing in them. */
enum { PC_NAME, PC_OS, PC_BUILD, PC_CHANNEL, PC_KERNEL, PC_UPTIME,
       PC_CPU, PC_LOAD, PC_GPU, PC_MEMORY, PC_FAN, PC_GPU_FAN,
       PC_IP, PC_LINK, PC_MAC, PC_ANSWER, PC_ROWS };
#define PC_GROUPS 3
static const struct { uint8_t group; panel_text_id_t name; } pc_rows[PC_ROWS]={
    {0,TXT_PC_NAME},{0,TXT_PC_OS},{0,TXT_PC_BUILD},{0,TXT_PC_CHANNEL},
    {0,TXT_PC_KERNEL},{0,TXT_PC_UPTIME},
    {1,TXT_PC_CPU},{1,TXT_PC_LOAD},{1,TXT_PC_GPU},{1,TXT_PC_MEMORY},
    {1,TXT_PC_FAN},{1,TXT_PC_GPU_FAN},
    {2,TXT_PC_IP},{2,TXT_PC_LINK},{2,TXT_PC_MAC},{2,TXT_PC_ANSWER}};
static const panel_text_id_t pc_titles[PC_GROUPS]={TXT_PC_SYSTEM,TXT_PC_HARDWARE,TXT_PC_NETWORK};
static lv_obj_t *pc_screen,*pc_none,*pc_cards[PC_GROUPS],*pc_values[PC_ROWS];
/* The cards of the page of the PC: the title of a card, a row for each
 * thing 30 apart, and the room at the end of a card and between two. A row
 * is one line at 14 px, its name on the left and its value on the right:
 * "Radeon RX 9070/9070 XT/9070 GRE" fits the value at that size, and a
 * longer one ends in dots.
 *
 * The memory is its row of text and nothing more. A bar under it said the
 * same thing again, and its owner had it taken out. */
/* The menu of the sensors: the title, a row of 44 for each choice 50
 * apart, and the end of the box. Seven rows at the most, the choice of the
 * service and six sensors, fit the screen. */
#define SENSOR_TITLE_ROOM 62
#define SENSOR_ROW_STEP 50
#define SENSOR_BOX_END 14
/* The card of the update: its row, two lines for what it has to say, and
 * the button at its end. */
#define UPDATE_CARD_HEIGHT 172
#define PC_CARD_TOP 78
#define PC_TITLE_ROOM 40
#define PC_ROW_STEP 30
#define PC_CARD_END 10
#define PC_CARD_GAP 14
#define PC_NAME_WIDTH 140
#define PC_VALUE_X 150
#define PC_VALUE_WIDTH 272
static void say_size(char *out,size_t room,uint64_t bytes);
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
    lv_obj_set_style_text_color(b,lv_color_hex(TEXT),0);lv_obj_set_style_text_font(b,&panel_font_16,0);
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
    const char *caption=action==PANEL_SUSPEND?panel_text(TXT_CONFIRM_SUSPEND):action==PANEL_REBOOT?panel_text(TXT_CONFIRM_REBOOT):action==PANEL_POWEROFF?panel_text(TXT_CONFIRM_OFF):(action==PANEL_DESKTOP_MODE||action==PANEL_GAME_MODE)?panel_text(TXT_CONFIRM_MODE):action==PANEL_UPDATE?panel_text(TXT_CONFIRM_UPDATE):panel_text(TXT_CONFIRM_SETUP);
    lv_obj_t *box=panel(overlay,20,132,440,216,CARD,true);
    text_at(box,caption,20,26,400,&panel_font_20,TEXT);
    /* A second line only where there is something to say. Switching the
     * session says it in the question, and a sentence under it that
     * repeats the obvious is a sentence somebody reads once and then
     * reads past. */
    const char *what=action==PANEL_SETUP?panel_text(TXT_SETUP_WHAT)
        :action==PANEL_UPDATE?panel_text(TXT_UPDATE_WHAT)
        :(action==PANEL_DESKTOP_MODE||action==PANEL_GAME_MODE)?""
        :panel_text(TXT_CONFIRM_HERE);
    if(what[0])text_at(box,what,20,66,400,&panel_font_16,MUTED);
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
/* A slider of the panel, 380 wide. cb gets each move and the release. */
static lv_obj_t *slider_with(lv_obj_t *parent,int x,int y,int minimum,int maximum,int value,
                             lv_event_cb_t cb,intptr_t data)
{
    lv_obj_t *slider=lv_slider_create(parent);lv_obj_set_pos(slider,x,y);lv_obj_set_size(slider,380,8);
    lv_slider_set_range(slider,minimum,maximum);lv_slider_set_value(slider,value,LV_ANIM_OFF);
    lv_obj_set_style_bg_color(slider,lv_color_hex(EDGE),LV_PART_MAIN);
    lv_obj_set_style_bg_color(slider,lv_color_hex(BLUE),LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(slider,lv_color_hex(TEXT),LV_PART_KNOB);
    lv_obj_set_style_pad_all(slider,7,LV_PART_KNOB);lv_obj_set_ext_click_area(slider,18);
    lv_obj_add_event_cb(slider,cb,LV_EVENT_VALUE_CHANGED,(void *)data);
    lv_obj_add_event_cb(slider,cb,LV_EVENT_RELEASED,(void *)data);
    return slider;
}
static void slider_range(lv_obj_t *parent,int y,int minimum,int maximum,int value,panel_setting_t key)
{
    slider_with(parent,28,y,minimum,maximum,value,setting_slider,key);
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
static void lift_changed(lv_event_t *e)
{
    local.lift_wake=lv_obj_has_state(lv_event_get_target(e),LV_STATE_CHECKED);
    if(save_setting)save_setting(PANEL_LIFT_WAKE,local.lift_wake,true);
    feedback();
}
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
    /* The order of the pages stands on the settings, and goes with them. */
    arrange_forget();
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
/* The screen that puts the pages in order, and hides the ones nobody uses.
 *
 * A row for each place, with the name of the page there and three buttons:
 * an eye, one up and one down. Up or down moves the page one place and the
 * page there to the place it left, saves the order, and moves the pages of
 * the band at once. The top row has no way up and the bottom row no way
 * down.
 *
 * The eye hides the page or shows it again, and saves that at once. A
 * hidden page has the eye with a stroke through it and its name in grey,
 * and it keeps its place in the order. The band holds only the pages that
 * are shown, and the first of them is the start page. The last page that
 * is shown cannot go: its eye does nothing.
 *
 * The names are in the 16 point font. Three buttons leave 212 points for a
 * name, and the longest, "Graphics card and history", takes 206 in it and
 * 232 in the 18 point font.
 *
 * Every row on the screen, with no scroll: the room under the title, 8 over
 * the bottom edge, shared by the pages, with a gap of ARRANGE_GAP between
 * two rows. Seven pages give rows of 52, and eight would give 44, the
 * height of the buttons. The name of the start page and the line under it
 * that says so stand in the middle of the row together. See arrange_name_y. */
#define ARRANGE_TOP 72
#define ARRANGE_GAP 6
#define ARRANGE_STEP ((480-8-ARRANGE_TOP+ARRANGE_GAP)/PANEL_PAGES)
#define ARRANGE_HEIGHT (ARRANGE_STEP-ARRANGE_GAP)
_Static_assert(ARRANGE_HEIGHT>=44,"a row of the order has no room for its buttons");
/* The name of the start page, with the line that says so 2 under it. */
static int32_t arrange_name_y(void)
{
    return (ARRANGE_HEIGHT-lv_font_get_line_height(&panel_font_16)-2
            -lv_font_get_line_height(&panel_font_12))/2;
}
static void arrange_drop(void)
{
    arrange_screen=NULL;
    for(int i=0;i<PANEL_PAGES;i++){
        arrange_names[i]=NULL;arrange_starts[i]=NULL;arrange_eyes[i]=NULL;
        arrange_up[i]=NULL;arrange_down[i]=NULL;
    }
}
static void arrange_forget(void)
{
    if(arrange_screen)lv_obj_delete(arrange_screen);
    arrange_drop();
}
/* The page the band shows now, read from where the band stands: a swipe
 * that did not carry far enough left it on the page it was on. The start
 * page while there is no band. */
static int band_page(void)
{
    int32_t place=band?(lv_obj_get_scroll_x(band)+240)/480:0;
    return panel_pages_band_page(page_order,page_hidden,place);
}
/* Each page of the band at its place now: the pages that are shown next to
 * each other in the order, and the hidden ones out of the band. A hidden
 * object is not drawn, not touched, and not a place the band snaps to.
 *
 * The band stays on the page it showed, which is at another place after a
 * move, or goes to the start page when that page was hidden. */
static void band_arrange(int showing)
{
    for(int i=0;i<PANEL_PAGES;i++){
        if(!band_pages[i])continue;
        int place=panel_pages_band_place(page_order,page_hidden,i);
        if(place<0){lv_obj_add_flag(band_pages[i],LV_OBJ_FLAG_HIDDEN);continue;}
        lv_obj_remove_flag(band_pages[i],LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_x(band_pages[i],place*480);
    }
    if(!band)return;
    /* lv_obj_scroll_to_x brings the layout up to date before it bounds
     * the scroll, so the new places count. */
    int place=panel_pages_band_place(page_order,page_hidden,showing);
    lv_obj_scroll_to_x(band,(place<0?0:place)*480,LV_ANIM_OFF);
}
static void arrange_show(void)
{
    if(!arrange_screen)return;
    int start=panel_pages_place(page_order,panel_pages_band_page(page_order,page_hidden,0));
    bool last=panel_pages_shown(page_hidden)==1;
    for(int place=0;place<PANEL_PAGES;place++){
        int page=page_order[place];
        bool hidden=(page_hidden>>page)&1;
        lv_label_set_text(arrange_names[place],panel_text(page_names[page]));
        lv_obj_set_style_text_color(arrange_names[place],lv_color_hex(hidden?MUTED:TEXT),0);
        /* The start page has a second line, and the others have their name
         * in the middle of the row. */
        lv_obj_set_y(arrange_names[place],place==start?arrange_name_y():
                     (ARRANGE_HEIGHT-lv_font_get_line_height(&panel_font_16))/2);
        if(place==start)lv_obj_remove_flag(arrange_starts[place],LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(arrange_starts[place],LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(lv_obj_get_child(arrange_eyes[place],0),
                          hidden?LV_SYMBOL_EYE_CLOSE:LV_SYMBOL_EYE_OPEN);
        if(!hidden&&last)lv_obj_add_state(arrange_eyes[place],LV_STATE_DISABLED);
        else lv_obj_remove_state(arrange_eyes[place],LV_STATE_DISABLED);
        if(place==0)lv_obj_add_state(arrange_up[place],LV_STATE_DISABLED);
        else lv_obj_remove_state(arrange_up[place],LV_STATE_DISABLED);
        if(place==PANEL_PAGES-1)lv_obj_add_state(arrange_down[place],LV_STATE_DISABLED);
        else lv_obj_remove_state(arrange_down[place],LV_STATE_DISABLED);
    }
}
static void arrange_move(lv_event_t *e)
{
    int code=(int)(intptr_t)lv_event_get_user_data(e);
    int place=code/2,step=code%2?1:-1;
    feedback();
    int showing=band_page();
    if(!panel_pages_move(page_order,place,step))return;
    local.page_order=panel_pages_pack(page_order);
    if(save_setting)save_setting(PANEL_PAGE_ORDER,(int)local.page_order,true);
    band_arrange(showing);
    arrange_show();
}
static void arrange_eye(lv_event_t *e)
{
    int place=(int)(intptr_t)lv_event_get_user_data(e);
    feedback();
    int showing=band_page();
    if(!panel_pages_toggle(&page_hidden,page_order[place]))return;
    local.page_hidden=page_hidden;
    if(save_setting)save_setting(PANEL_PAGE_HIDDEN,(int)local.page_hidden,true);
    band_arrange(showing);
    arrange_show();
}
static void arrange_close(lv_event_t *e){(void)e;feedback();arrange_forget();}
void panel_ui_arrange_open(void)
{
    if(arrange_screen||!settings_screen)return;
    arrange_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
    button(arrange_screen,panel_text(TXT_BACK),12,8,112,44,arrange_close,0);
    text_at(arrange_screen,panel_text(TXT_PAGES_TITLE),136,20,320,&panel_font_20,TEXT);
    line(arrange_screen,0,62,480,1);
    for(int place=0;place<PANEL_PAGES;place++){
        lv_obj_t *row=panel(arrange_screen,20,ARRANGE_TOP+place*ARRANGE_STEP,440,ARRANGE_HEIGHT,CARD,true);
        lv_obj_remove_flag(row,LV_OBJ_FLAG_CLICKABLE);
        char number[4];
        snprintf(number,sizeof number,"%d",place+1);
        text_at(row,number,16,(ARRANGE_HEIGHT-lv_font_get_line_height(&panel_font_24))/2,24,&panel_font_24,BLUE);
        arrange_names[place]=text_at(row,"",52,arrange_name_y(),212,&panel_font_16,TEXT);
        lv_obj_set_height(arrange_names[place],lv_font_get_line_height(&panel_font_16));
        arrange_starts[place]=text_at(row,panel_text(TXT_PAGES_START),52,
                                      arrange_name_y()+lv_font_get_line_height(&panel_font_16)+2,
                                      212,&panel_font_12,MUTED);
        int32_t button_y=(ARRANGE_HEIGHT-44)/2;
        arrange_eyes[place]=button(row,LV_SYMBOL_EYE_OPEN,270,button_y,48,44,arrange_eye,place);
        arrange_up[place]=button(row,LV_SYMBOL_UP,324,button_y,48,44,arrange_move,place*2);
        arrange_down[place]=button(row,LV_SYMBOL_DOWN,378,button_y,48,44,arrange_move,place*2+1);
    }
    arrange_show();
}
static void arrange_clicked(lv_event_t *e){(void)e;feedback();panel_ui_arrange_open();}
void panel_ui_settings_open(void)
{
    if(settings_screen)return;
    last_state_valid=false;
    settings_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
    button(settings_screen,panel_text(TXT_BACK),12,8,112,44,settings_close,0);
    text_at(settings_screen,panel_text(TXT_SETTINGS_TITLE),136,20,200,&panel_font_20,TEXT);
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
     * equal. A third row under them holds the switch for a lift. */
    lv_obj_t *display=panel(settings_screen,20,78,440,300,CARD,true);
    icon(display,&icon_sun,16,18,MUTED);
    text_at(display,panel_text(TXT_BRIGHTNESS),62,16,268,&panel_font_18,TEXT);
    brightness_label=text_at(display,"",338,16,88,&panel_font_18,BLUE);
    lv_label_set_text_fmt(brightness_label,"%d %%",local.brightness);
    text_at(display,panel_text(TXT_BRIGHTNESS_WHAT),62,43,350,&panel_font_12,MUTED);
    slider_at(display,88,5,local.brightness,PANEL_BRIGHTNESS);
    line(display,18,112,402,1);
    text_at(display,panel_text(TXT_SLEEP_AFTER),20,128,268,&panel_font_18,TEXT);
    sleep_label=text_at(display,"",318,128,108,&panel_font_18,BLUE);
    {
        char said[24];
        sleep_words(said,sizeof said,local.sleep_after);
        lv_label_set_text(sleep_label,said);
    }
    text_at(display,panel_text(TXT_SLEEP_AFTER_WHAT),20,155,404,&panel_font_12,MUTED);
    slider_range(display,200,0,SLEEP_CHOICES-1,sleep_index(local.sleep_after),
                 PANEL_SLEEP_AFTER);
    /* A lift brings the display back, after the set time and not after
     * the button. It belongs to the time: it is the other way out of the
     * sleep that time starts. */
    line(display,18,224,402,1);
    text_at(display,panel_text(TXT_LIFT_WAKE),20,240,330,&panel_font_18,TEXT);
    text_at(display,panel_text(TXT_LIFT_WAKE_WHAT),20,268,336,&panel_font_12,MUTED);
    lv_obj_t *lift=lv_switch_create(display);lv_obj_set_pos(lift,358,241);lv_obj_set_size(lift,58,30);
    lv_obj_set_style_bg_color(lift,lv_color_hex(BLUE),LV_PART_INDICATOR|LV_STATE_CHECKED);
    lv_obj_set_ext_click_area(lift,8);
    if(local.lift_wake)lv_obj_add_state(lift,LV_STATE_CHECKED);
    lv_obj_add_event_cb(lift,lift_changed,LV_EVENT_VALUE_CHANGED,NULL);
    lv_obj_t *sound=panel(settings_screen,20,392,440,216,CARD,true);
    icon(sound,&icon_volume_2,12,12,MUTED);
    text_at(sound,panel_text(TXT_TONES),70,16,240,&panel_font_18,TEXT);
    text_at(sound,panel_text(TXT_TONES_WHAT),70,44,340,&panel_font_12,MUTED);
    lv_obj_t *sw=lv_switch_create(sound);lv_obj_set_pos(sw,358,17);lv_obj_set_size(sw,58,30);
    lv_obj_set_style_bg_color(sw,lv_color_hex(BLUE),LV_PART_INDICATOR|LV_STATE_CHECKED);
    lv_obj_set_ext_click_area(sw,8);
    if(local.touch_tones)lv_obj_add_state(sw,LV_STATE_CHECKED);
    lv_obj_add_event_cb(sw,tones_changed,LV_EVENT_VALUE_CHANGED,NULL);
    line(sound,18,76,402,1);
    text_at(sound,panel_text(TXT_ESP_VOLUME),20,92,296,&panel_font_16,TEXT);
    sound_value=text_at(sound,"",338,92,88,&panel_font_18,BLUE);
    lv_label_set_text_fmt(sound_value,"%d %%",local.sound_volume);
    slider_at(sound,138,0,local.sound_volume,PANEL_SOUND_VOLUME);
    button(sound,panel_text(TXT_TEST_TONE),276,164,144,44,test_sound,0);
    sound_status=text_at(sound,panel_text(TXT_SPEAKER),20,176,248,&panel_font_12,MUTED);
    /* The setup, which used to stand in a corner of the main screen.
     *
     * It is not an everyday button. It takes the panel off the network
     * until somebody finishes it, and a corner of the main screen is where
     * a stray finger lands. It still asks before it starts, the same
     * question as before, and the setup screen that follows closes this
     * one: see settings_forget in panel_ui_update. */
    /* The order of the pages, on a screen of its own. */
    lv_obj_t *pages=panel(settings_screen,20,622,440,84,CARD,true);
    text_at(pages,panel_text(TXT_PAGES),20,16,240,&panel_font_18,TEXT);
    text_at(pages,panel_text(TXT_PAGES_WHAT),20,44,248,&panel_font_12,MUTED);
    button(pages,panel_text(TXT_PAGES_ARRANGE),276,20,144,44,arrange_clicked,0);
    lv_obj_t *link=panel(settings_screen,20,720,440,84,CARD,true);
    text_at(link,panel_text(TXT_CONNECTION),20,16,240,&panel_font_18,TEXT);
    text_at(link,panel_text(TXT_SETUP_WHAT),20,44,240,&panel_font_12,MUTED);
    button(link,panel_text(TXT_SETUP),276,20,144,44,clicked,PANEL_SETUP);
    text_at(settings_screen,panel_text(TXT_AUTOSAVE),22,818,440,&panel_font_12,MUTED);
}
static void settings_clicked(lv_event_t *e){(void)e;feedback();panel_ui_settings_open();}
/* What a controller says in the head and on its card: the battery, the
 * charge symbol while it charges, and "--" where nobody reports one. */
static void pad_level(char *out,size_t room,const panel_pad_t *pad)
{
    if(pad->battery<0)snprintf(out,room,"-- %%");
    else snprintf(out,room,"%d %%%s",pad->battery,pad->charging?" " LV_SYMBOL_CHARGE:"");
}
/* Whether a text is as narrow as a room, in one line of that font. */
static bool fits(const char *text,const lv_font_t *font,int32_t width)
{
    lv_point_t size;
    lv_text_get_size(&size,text,font,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
    return size.x<=width;
}
/* A text without one word wherever it stands alone, and how many words
 * are left. */
static int without_word(char *out,size_t room,const char *text,const char *word)
{
    size_t used=0;int words=0;
    out[0]=0;
    for(const char *at=text;*at;){
        while(*at==' ')at++;
        const char *end=at;
        while(*end&&*end!=' ')end++;
        size_t length=(size_t)(end-at);
        bool drop=length==strlen(word)&&strncmp(at,word,length)==0;
        if(length&&!drop&&used+length+2<room){
            if(used)out[used++]=' ';
            memcpy(out+used,at,length);used+=length;out[used]=0;
            words++;
        }
        at=end;
    }
    return words;
}
/* The name of a controller, made to fit its line.
 *
 * A name that fits stays as it is. One that does not loses "Wireless" and
 * then "Controller", which say what every line on this page is: "8BitDo
 * Ultimate 2C Wireless Controller" reads "8BitDo Ultimate 2C". A word goes
 * only while two words stay, so a "Steam Controller" never reads "Steam".
 * What still does not fit ends in dots. */
static void pad_fit(char *out,size_t room,const char *name,const lv_font_t *font,int32_t width)
{
    static const char *const fillers[]={"Wireless","Controller"};
    snprintf(out,room,"%s",name);
    for(unsigned i=0;i<sizeof fillers/sizeof *fillers&&!fits(out,font,width);i++){
        char shorter[PANEL_PAD_NAME];
        if(without_word(shorter,sizeof shorter,out,fillers[i])>=2)snprintf(out,room,"%s",shorter);
    }
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
        char name[PANEL_PAD_NAME];
        pad_fit(name,sizeof name,pad->name,&panel_font_18,PAD_NAME_WIDTH);
        lv_label_set_text(pad_names[i],name);
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
    if(pads_screen||pc_screen||self_screen||settings_screen||setup_screen)return;
    pads_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
    button(pads_screen,panel_text(TXT_BACK),12,8,112,44,pads_close,0);
    text_at(pads_screen,panel_text(TXT_CONTROLLERS),136,20,200,&panel_font_20,TEXT);
    line(pads_screen,0,62,480,1);
    pads_none=text_at(pads_screen,"",20,220,440,&panel_font_18,MUTED);
    center_text(pads_none);
    for(int i=0;i<PANEL_PADS;i++){
        lv_obj_t *card=panel(pads_screen,20,PAD_CARD_TOP+i*PAD_CARD_STEP,440,PAD_CARD_HEIGHT,CARD,true);
        lv_obj_remove_flag(card,LV_OBJ_FLAG_CLICKABLE);
        pad_cards[i]=card;
        icon(card,&icon_gamepad_2,16,16,MUTED);
        /* One line, with the height of one: a label as wide as its text
         * wraps, and the dots of LONG_DOT need the height. */
        pad_names[i]=text_at(card,"",56,16,PAD_NAME_WIDTH,&panel_font_18,TEXT);
        lv_obj_set_height(pad_names[i],lv_font_get_line_height(&panel_font_18));
        pad_levels[i]=text_at(card,"",306,16,118,&panel_font_18,BLUE);
        lv_obj_set_style_text_align(pad_levels[i],LV_TEXT_ALIGN_RIGHT,0);
        pad_tracks[i]=panel(card,PAD_BAR_LEFT,54,PAD_BAR_WIDTH,10,EDGE,false);
        lv_obj_set_style_radius(pad_tracks[i],LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(pad_tracks[i],LV_OBJ_FLAG_CLICKABLE);
        pad_bars[i]=panel(pad_tracks[i],0,0,0,10,BLUE,false);
        lv_obj_set_style_radius(pad_bars[i],LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(pad_bars[i],LV_OBJ_FLAG_CLICKABLE);
        pad_unknown[i]=text_at(card,panel_text(TXT_NO_BATTERY),PAD_BAR_LEFT,50,PAD_BAR_WIDTH,&panel_font_14,MUTED);
        lv_obj_add_flag(card,LV_OBJ_FLAG_HIDDEN);
    }
    /* What the last update said, at once. panel_ui_update draws nothing
     * for a state it saw before, so the page waits for no change. */
    if(last_state_valid)pads_show(&last_state);
}
static void pads_clicked(lv_event_t *e){(void)e;feedback();panel_ui_pads_open();}
/* A place of the head that opens a page: no face of its own, and a shade
 * while a finger is on it. */
static lv_obj_t *head_area(lv_obj_t *s,int x,int width,lv_event_cb_t opens)
{
    lv_obj_t *o=panel(s,x,0,width,57,BG,false);
    lv_obj_set_style_bg_opa(o,LV_OPA_TRANSP,0);
    lv_obj_set_style_bg_color(o,lv_color_hex(EDGE),LV_STATE_PRESSED);
    lv_obj_set_style_bg_opa(o,LV_OPA_40,LV_STATE_PRESSED);
    lv_obj_add_event_cb(o,opens,LV_EVENT_CLICKED,NULL);
    return o;
}
/* Every pointer into the page of the PC, dropped. The rule of
 * settings_drop: this only drops, and pc_forget deletes as well. */
static void pc_drop(void)
{
    pc_screen=NULL;pc_none=NULL;
    for(int i=0;i<PC_GROUPS;i++)pc_cards[i]=NULL;
    for(int i=0;i<PC_ROWS;i++)pc_values[i]=NULL;
}
static void pc_forget(void)
{
    if(pc_screen)lv_obj_delete(pc_screen);
    pc_drop();
}
static void pc_say(int row,const char *text)
{
    if(pc_values[row])lv_label_set_text(pc_values[row],text&&text[0]?text:"--");
}
/* The uptime in days, hours and minutes, and with no days below one. */
static void pc_uptime(char *out,size_t room,int32_t seconds)
{
    if(seconds<0){snprintf(out,room,"--");return;}
    int days=(int)(seconds/86400),hours=(int)(seconds%86400/3600),minutes=(int)(seconds%3600/60);
    if(days>0)snprintf(out,room,panel_text(TXT_UPTIME_DAYS),days,hours,minutes);
    else snprintf(out,room,panel_text(TXT_UPTIME_HOURS),hours,minutes);
}
static void pc_count(char *out,size_t room,const char *format,int value)
{
    if(value<0)snprintf(out,room,"--");
    else snprintf(out,room,format,value);
}
/* The card the PC answers through: what it is, and how fast where the
 * kernel says. 1000 Mbit/s and up is written in Gbit/s, as a box says it. */
static void pc_link(char *out,size_t room,const panel_pc_t *pc)
{
    if(pc->link==PANEL_LINK_UNKNOWN){snprintf(out,room,"--");return;}
    const char *kind=panel_text(pc->link==PANEL_LINK_WIRED?TXT_WIRED:TXT_WIRELESS);
    if(pc->link_mbit<=0)snprintf(out,room,"%s",kind);
    else if(pc->link_mbit>=1000&&pc->link_mbit%1000==0)snprintf(out,room,"%s, %d Gbit/s",kind,pc->link_mbit/1000);
    else if(pc->link_mbit>=1000)snprintf(out,room,"%s, %d.%d Gbit/s",kind,pc->link_mbit/1000,pc->link_mbit%1000/100);
    else snprintf(out,room,"%s, %d Mbit/s",kind,pc->link_mbit);
}
static void pc_show(const panel_state_t *s)
{
    if(!pc_screen)return;
    /* What a PC that does not answer said last is no answer to show. */
    for(int i=0;i<PC_GROUPS;i++){
        if(s->online)lv_obj_remove_flag(pc_cards[i],LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(pc_cards[i],LV_OBJ_FLAG_HIDDEN);
    }
    if(s->online)lv_obj_add_flag(pc_none,LV_OBJ_FLAG_HIDDEN);
    else lv_obj_remove_flag(pc_none,LV_OBJ_FLAG_HIDDEN);
    if(!s->online)return;
    const panel_pc_t *pc=&s->pc;
    char said[64];
    pc_say(PC_NAME,s->host);
    pc_say(PC_OS,pc->os);
    pc_say(PC_BUILD,pc->build);
    pc_say(PC_CHANNEL,pc->channel);
    pc_say(PC_KERNEL,pc->kernel);
    pc_uptime(said,sizeof said,pc->uptime_s);pc_say(PC_UPTIME,said);
    pc_say(PC_CPU,pc->cpu);
    pc_count(said,sizeof said,"%d %%",pc->cpu_load);pc_say(PC_LOAD,said);
    pc_say(PC_GPU,pc->gpu);
    if(pc->memory_total>0){
        char used[16],total[16];
        say_size(used,sizeof used,pc->memory_used);
        say_size(total,sizeof total,pc->memory_total);
        /* One unit for both: "9.2 / 31.3 GB" and not "9.2 GB / 31.3 GB". */
        char *unit=strstr(used," GB");
        if(unit)*unit=0;
        snprintf(said,sizeof said,"%s / %s",used,total);
        pc_say(PC_MEMORY,said);
    }else pc_say(PC_MEMORY,"");
    pc_count(said,sizeof said,panel_text(TXT_RPM),pc->fan_rpm);pc_say(PC_FAN,said);
    pc_count(said,sizeof said,panel_text(TXT_RPM),pc->gpu_fan_rpm);pc_say(PC_GPU_FAN,said);
    pc_say(PC_IP,pc->ip);
    pc_link(said,sizeof said,pc);pc_say(PC_LINK,said);
    pc_say(PC_MAC,pc->mac);
    pc_count(said,sizeof said,"%d ms",pc->answer_ms);pc_say(PC_ANSWER,said);
}
static void pc_close(lv_event_t *e){(void)e;feedback();pc_forget();}
void panel_ui_pc_open(void)
{
    if(pc_screen||pads_screen||self_screen||settings_screen||setup_screen)return;
    pc_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
    button(pc_screen,panel_text(TXT_BACK),12,8,112,44,pc_close,0);
    text_at(pc_screen,panel_text(TXT_PC_DETAILS),136,20,320,&panel_font_20,TEXT);
    line(pc_screen,0,62,480,1);
    /* More than a screen holds, so it scrolls up and down, the way the
     * settings do. */
    lv_obj_add_flag(pc_screen,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(pc_screen,LV_DIR_VER);
    lv_obj_set_scrollbar_mode(pc_screen,LV_SCROLLBAR_MODE_AUTO);
    lv_obj_set_style_pad_bottom(pc_screen,20,0);
    pc_none=text_at(pc_screen,panel_text(TXT_PC_OFFLINE),20,220,440,&panel_font_18,MUTED);
    center_text(pc_none);
    int top=PC_CARD_TOP;
    for(int g=0;g<PC_GROUPS;g++){
        int rows=0;
        for(int r=0;r<PC_ROWS;r++)if(pc_rows[r].group==g)rows++;
        int height=PC_TITLE_ROOM+rows*PC_ROW_STEP+PC_CARD_END;
        lv_obj_t *card=panel(pc_screen,20,top,440,height,CARD,true);
        lv_obj_remove_flag(card,LV_OBJ_FLAG_CLICKABLE);
        pc_cards[g]=card;
        text_at(card,panel_text(pc_titles[g]),18,14,300,&panel_font_12,MUTED);
        int y=PC_TITLE_ROOM;
        for(int r=0;r<PC_ROWS;r++){
            if(pc_rows[r].group!=g)continue;
            /* One line each, with a height of one line: a label as wide as
             * its text wraps, and the dots of LONG_DOT need the height. */
            int32_t high=lv_font_get_line_height(&panel_font_14);
            lv_obj_t *name=text_at(card,panel_text(pc_rows[r].name),18,y,PC_NAME_WIDTH,&panel_font_14,MUTED);
            lv_obj_set_height(name,high);
            pc_values[r]=text_at(card,"--",PC_VALUE_X,y,PC_VALUE_WIDTH,&panel_font_14,TEXT);
            lv_obj_set_height(pc_values[r],high);
            lv_obj_set_style_text_align(pc_values[r],LV_TEXT_ALIGN_RIGHT,0);
            y+=PC_ROW_STEP;
        }
        top+=height+PC_CARD_GAP;
    }
    if(last_state_valid)pc_show(&last_state);
}
static void pc_clicked(lv_event_t *e){(void)e;feedback();panel_ui_pc_open();}
uint32_t panel_sensor_key(const char *id)
{
    uint32_t key=2166136261u;
    for(const unsigned char *at=(const unsigned char *)id;*at;at++){key^=*at;key*=16777619u;}
    return key?key:1u;
}
/* The reading a tile shows: the one of the sensor somebody chose, while
 * the service still lists it, and otherwise the one the service chose. A
 * stored key no sensor has any more is the choice of the service, which
 * is what an update of the PC that renames a sensor comes to. */
static int sensor_shown(const panel_sensor_t *list,int count,uint32_t chosen,int otherwise)
{
    if(chosen)for(int i=0;i<count&&i<PANEL_SENSORS;i++)
        if(panel_sensor_key(list[i].id)==chosen)return list[i].celsius;
    return otherwise;
}
static void temperatures_show(const panel_state_t *s)
{
    int cpu=sensor_shown(s->cpu_sensors,s->cpu_sensor_count,local.cpu_sensor,s->cpu_temp);
    int gpu=sensor_shown(s->gpu_sensors,s->gpu_sensor_count,local.gpu_sensor,s->gpu_temp);
    if(s->online&&cpu>=0)lv_label_set_text_fmt(cpu_value,"%d °C",cpu);else lv_label_set_text(cpu_value,"-- °C");
    if(s->online&&gpu>=0)lv_label_set_text_fmt(gpu_value,"%d °C",gpu);else lv_label_set_text(gpu_value,"-- °C");
}
void panel_ui_history_use(panel_history_t *kept){history=kept;history_stale=true;}
void panel_ui_history_tick(const panel_state_t *s,uint32_t now_ms)
{
    if(!history)return;
    /* A point is an answer. The state keeps the last reading while the PC
     * is gone, and that reading again is not a measurement. */
    if(s->online&&s->answers!=history_answers){
        int values[PANEL_HISTORY_SERIES]={
            sensor_shown(s->cpu_sensors,s->cpu_sensor_count,local.cpu_sensor,s->cpu_temp),
            sensor_shown(s->gpu_sensors,s->gpu_sensor_count,local.gpu_sensor,s->gpu_temp),
            s->gpu_watts};
        panel_history_offer(history,values);
    }
    history_answers=s->answers;
    panel_history_tick(history,now_ms);
}
/* A scale with room around the curve: tens of degrees at least 20 apart,
 * and watts from nought in steps of 50. */
static int floor_to(int value,int step){return value>=0?value/step*step:-((-value+step-1)/step*step);}
static int ceil_to(int value,int step){return -floor_to(-value,step);}
static void history_show(void)
{
    if(!history_chart)return;
    if(!history_stale&&(!history||history_drawn==history->version))return;
    history_stale=false;
    for(int i=0;i<HISTORY_WINDOWS;i++){
        bool on=history_windows[i]==history_minutes;
        lv_obj_set_style_border_color(history_buttons[i],lv_color_hex(on?BLUE:EDGE),0);
        lv_obj_set_style_text_color(history_buttons[i],lv_color_hex(on?BLUE:TEXT),0);
    }
    lv_label_set_text_fmt(history_ago,"-%d %s",history_minutes,panel_text(TXT_MINUTES));
    int found=0,low=0,high=0,cpu_low=0,cpu_high=0,watts_low=0,watts_high=0;
    if(history){
        history_drawn=history->version;
        for(int i=0;i<PANEL_HISTORY_SERIES;i++){
            int32_t *points=history->drawn[i];
            found+=panel_history_read(history,(panel_history_series_t)i,history_minutes,points,PANEL_HISTORY_DRAWN);
            for(int k=0;k<PANEL_HISTORY_DRAWN;k++)if(points[k]==PANEL_HISTORY_GAP)points[k]=LV_CHART_POINT_NONE;
        }
    }
    bool cpu=history&&panel_history_range(history,PANEL_HISTORY_CPU,history_minutes,&cpu_low,&cpu_high);
    bool gpu=history&&panel_history_range(history,PANEL_HISTORY_GPU,history_minutes,&low,&high);
    if(cpu&&(!gpu||cpu_low<low))low=cpu_low;
    if(cpu&&(!gpu||cpu_high>high))high=cpu_high;
    bool watts=history&&panel_history_range(history,PANEL_HISTORY_WATTS,history_minutes,&watts_low,&watts_high);
    int bottom=30,top=90,most=300;
    if(cpu||gpu){
        bottom=floor_to(low-3,10);top=ceil_to(high+3,10);
        if(top-bottom<20)top=bottom+20;
    }
    if(watts){most=ceil_to(watts_high+watts_high/10+1,50);if(most<50)most=50;}
    lv_chart_set_axis_range(history_chart,LV_CHART_AXIS_PRIMARY_Y,bottom,top);
    lv_chart_set_axis_range(history_chart,LV_CHART_AXIS_SECONDARY_Y,0,most);
    /* A scale with no curve on it is empty: the note in the middle says
     * why. */
    if(cpu||gpu){
        lv_label_set_text_fmt(history_axis[0],"%d °C",top);
        lv_label_set_text_fmt(history_axis[1],"%d °C",bottom);
    }else{lv_label_set_text(history_axis[0],"");lv_label_set_text(history_axis[1],"");}
    if(watts){
        lv_label_set_text_fmt(history_axis[2],"%d W",most);
        lv_label_set_text(history_axis[3],"0 W");
    }else{lv_label_set_text(history_axis[2],"");lv_label_set_text(history_axis[3],"");}
    if(found)lv_obj_add_flag(history_empty,LV_OBJ_FLAG_HIDDEN);
    else lv_obj_remove_flag(history_empty,LV_OBJ_FLAG_HIDDEN);
    lv_chart_refresh(history_chart);
}
static void history_window_clicked(lv_event_t *e)
{
    int minutes=(int)(intptr_t)lv_event_get_user_data(e);
    feedback();
    if(minutes==history_minutes)return;
    history_minutes=minutes;history_stale=true;
    history_show();
}
/* The load, the memory and the clock of the card. "--" where the
 * service sent nothing, as on the page of the PC, and for all of them
 * while the PC is gone: the last reading would read as current. */
/* The switch of Cooling Boost: there where the PC has LACT with a card, as
 * the last answer said, and usable while the PC answers. On is blue with the
 * knob at the right, as the switch of the audio. */
static void boost_show(const panel_state_t *s)
{
    if(!boost_field)return;
    if(s->boost_here==lv_obj_has_flag(boost_field,LV_OBJ_FLAG_HIDDEN)){
        if(s->boost_here)lv_obj_remove_flag(boost_field,LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(boost_field,LV_OBJ_FLAG_HIDDEN);
    }
    if(s->online==lv_obj_has_state(boost_field,LV_STATE_DISABLED)){
        if(s->online)lv_obj_remove_state(boost_field,LV_STATE_DISABLED);
        else lv_obj_add_state(boost_field,LV_STATE_DISABLED);
    }
    int on=s->online&&s->boost_on;
    if(on==boost_shown)return;
    boost_shown=on;
    lv_obj_set_style_bg_color(boost_track,lv_color_hex(on?BLUE:EDGE),0);
    lv_obj_set_x(boost_knob,on?BOOST_KNOB_ON:BOOST_KNOB_OFF);
}
/* A tap asks for the other state than the one the switch shows. The switch
 * moves when the next status says so, which comes at once after the press:
 * a switch that moved before the PC took it would show a fan that is not.
 *
 * Not through clicked, whose range asks first and holds these two: a fan at
 * full speed interrupts nothing. */
static void boost_clicked(lv_event_t *e)
{
    (void)e;
    if(!last_state_valid||!last_state.online||!last_state.boost_here)return;
    feedback();
    if(send_action)send_action(last_state.boost_on?PANEL_GPU_BOOST_OFF:PANEL_GPU_BOOST_ON);
}
static void card_show(const panel_state_t *s)
{
    if(!gpu_load_value)return;
    if(s->online&&s->gpu_load>=0){
        lv_label_set_text_fmt(gpu_load_value,"%d %%",s->gpu_load);
        lv_obj_remove_flag(gpu_load_track,LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_width(gpu_load_bar,GPU_BAR_WIDTH*(s->gpu_load>100?100:s->gpu_load)/100);
    }else{
        lv_label_set_text(gpu_load_value,"--");
        lv_obj_add_flag(gpu_load_track,LV_OBJ_FLAG_HIDDEN);
    }
    if(s->online&&s->vram_total>0&&s->vram_used<=s->vram_total){
        char used[16],total[16],said[40];
        say_size(used,sizeof used,s->vram_used);
        say_size(total,sizeof total,s->vram_total);
        /* One unit for both, as on the page of the PC. */
        char *unit=strstr(used," GB");
        if(unit)*unit=0;
        snprintf(said,sizeof said,"%s / %s",used,total);
        lv_label_set_text(vram_value,said);
        lv_obj_remove_flag(vram_track,LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_width(vram_bar,(int32_t)(GPU_BAR_WIDTH*s->vram_used/s->vram_total));
    }else{
        lv_label_set_text(vram_value,"--");
        lv_obj_add_flag(vram_track,LV_OBJ_FLAG_HIDDEN);
    }
    if(s->online&&s->gpu_mhz>=0)lv_label_set_text_fmt(gpu_clock_value,"%d MHz",s->gpu_mhz);
    else lv_label_set_text(gpu_clock_value,"--");
    boost_show(s);
}
static void sensor_close(void){if(sensor_layer){lv_obj_delete(sensor_layer);sensor_layer=NULL;}}
static void sensor_outside(lv_event_t *e){(void)e;sensor_close();}
/* A row of the menu, by its place: row nought is the choice of the
 * service. */
static void sensor_chosen(lv_event_t *e)
{
    int row=(int)(intptr_t)lv_event_get_user_data(e);
    uint32_t key=row>=0&&row<=PANEL_SENSORS?sensor_keys[row]:0;
    if(sensor_gpu)local.gpu_sensor=key;else local.cpu_sensor=key;
    if(save_setting)save_setting(sensor_gpu?PANEL_GPU_SENSOR:PANEL_CPU_SENSOR,(int)key,true);
    feedback();
    sensor_close();
    if(last_state_valid)temperatures_show(&last_state);
}
static void sensor_row(lv_obj_t *box,int row,int y,const char *name,int celsius,bool chosen)
{
    lv_obj_t *b=button(box,"",20,y,400,44,sensor_chosen,row);
    uint32_t color=chosen?BLUE:TEXT;
    char said[48];
    snprintf(said,sizeof said,"%s%s",chosen?LV_SYMBOL_OK "  ":"",name);
    lv_obj_t *left=text_at(b,said,14,12,250,&panel_font_16,color);
    lv_obj_set_height(left,lv_font_get_line_height(&panel_font_16));
    if(celsius>=0)snprintf(said,sizeof said,"%d °C",celsius);else snprintf(said,sizeof said,"-- °C");
    lv_obj_t *right=text_at(b,said,270,12,116,&panel_font_16,color);
    lv_obj_set_style_text_align(right,LV_TEXT_ALIGN_RIGHT,0);
}
/* The choice of the sensor of a tile: the choice of the service first,
 * with what it reads now, then each sensor with its reading. A tap on a
 * row chooses and closes, and a tap beside the box closes. Over the whole
 * screen, as a question is. */
static void sensor_menu(bool gpu)
{
    if(sensor_layer||look_layer||overlay||settings_screen||pads_screen||pc_screen||self_screen||update_layer
       ||setup_screen)return;
    const panel_state_t *s=&last_state;
    int count=!last_state_valid?0:gpu?s->gpu_sensor_count:s->cpu_sensor_count;
    if(count<0)count=0;
    if(count>PANEL_SENSORS)count=PANEL_SENSORS;
    const panel_sensor_t *list=gpu?s->gpu_sensors:s->cpu_sensors;
    uint32_t chosen=gpu?local.gpu_sensor:local.cpu_sensor;
    bool known=false;
    for(int i=0;i<count;i++)if(panel_sensor_key(list[i].id)==chosen)known=true;
    sensor_gpu=gpu;
    sensor_layer=panel(lv_screen_active(),0,0,480,480,BG,false);
    lv_obj_set_style_bg_opa(sensor_layer,LV_OPA_90,0);
    lv_obj_add_event_cb(sensor_layer,sensor_outside,LV_EVENT_CLICKED,NULL);
    int high=SENSOR_TITLE_ROOM+(count+1)*SENSOR_ROW_STEP+SENSOR_BOX_END;
    lv_obj_t *box=panel(sensor_layer,20,(480-high)/2,440,high,CARD,true);
    lv_obj_remove_flag(box,LV_OBJ_FLAG_CLICKABLE);
    text_at(box,panel_text(gpu?TXT_GPU_TEMPERATURE:TXT_CPU_TEMPERATURE),20,18,400,&panel_font_20,TEXT);
    int automatic=!last_state_valid||!s->online?-1:gpu?s->gpu_temp:s->cpu_temp;
    sensor_keys[0]=0;
    sensor_row(box,0,SENSOR_TITLE_ROOM,panel_text(TXT_SENSOR_AUTO),automatic,!known);
    for(int i=0;i<count;i++)sensor_keys[i+1]=panel_sensor_key(list[i].id);
    for(int i=0;i<count;i++)
        sensor_row(box,i+1,SENSOR_TITLE_ROOM+(i+1)*SENSOR_ROW_STEP,list[i].name,
                   s->online?list[i].celsius:-1,known&&panel_sensor_key(list[i].id)==chosen);
}
static void cpu_tile_clicked(lv_event_t *e){(void)e;feedback();sensor_menu(false);}
/* A third of the card of the sensors, which is 460 wide: the processor
 * from 0, the card from 153 and its power from 306, with a line of 1 at
 * 153 and at 306. What stands in the card counts from inside its border,
 * one further in, so those lines are at 152 and 305 there, and each third
 * is SENSOR_FIELD-1 wide. See the card in panel_ui_create. */
#define SENSOR_FIELD 153
/* From the sign of a third to its words. */
#define SENSOR_GAP 9
/* How wide a text is in a font. */
static int32_t text_width(const char *text,const lv_font_t *font)
{
    lv_point_t size;
    lv_text_get_size(&size,text,font,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
    return size.x;
}
/* The sign, the caption and the reading of the third that starts at
 * "from", as one block in the middle of the third. Returns the reading.
 *
 * Reported from the board: the readings stood at the left of their
 * thirds, and the rest of each third was empty.
 *
 * The block is as wide as the wider of the caption and "widest", a
 * reading as wide as the ones the third shows, and not as wide as the
 * reading of the moment. The digits of this font are not all of one
 * width, and a block that followed the reading would move its sign by
 * three pixels from 49 to 51 degrees. */
static lv_obj_t *sensor_reading(lv_obj_t *field,int from,const lv_image_dsc_t *sign,
                                const char *caption,const char *widest,const char *first)
{
    int32_t words=LV_MAX(text_width(caption,&panel_font_12),text_width(widest,&panel_font_18));
    int32_t x=from+(SENSOR_FIELD-1-(int32_t)sign->header.w-SENSOR_GAP-words)/2;
    int32_t text=x+(int32_t)sign->header.w+SENSOR_GAP,room=from+SENSOR_FIELD-1-text;
    lv_obj_remove_flag(icon(field,sign,x,12,MUTED),LV_OBJ_FLAG_CLICKABLE);
    text_at(field,caption,text,6,room,&panel_font_12,MUTED);
    return text_at(field,first,text,22,room,&panel_font_18,BLUE);
}
/* A part of that card that a tap opens a choice from: clear, and lit while
 * it is pressed. */
static lv_obj_t *sensor_field(lv_obj_t *card,int x,int w,lv_event_cb_t cb)
{
    lv_obj_t *f=lv_obj_create(card);lv_obj_remove_style_all(f);
    lv_obj_set_pos(f,x,0);lv_obj_set_size(f,w,46);
    lv_obj_remove_flag(f,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_radius(f,5,0);
    lv_obj_set_style_bg_color(f,lv_color_hex(0x1B2B3C),LV_STATE_PRESSED);
    lv_obj_set_style_bg_opa(f,LV_OPA_COVER,LV_STATE_PRESSED);
    lv_obj_add_event_cb(f,cb,LV_EVENT_CLICKED,NULL);
    return f;
}
/* "Build 61 (1eec536)", out of the version "61-1eec536". */
static void say_version(char *out,size_t room,const char *version)
{
    if(!version[0]){snprintf(out,room,"--");return;}
    char number[16]="";
    size_t length=strcspn(version,"-");
    if(length>=sizeof number)length=sizeof number-1;
    memcpy(number,version,length);number[length]=0;
    const char *rest=version[length]=='-'?version+length+1:"";
    snprintf(out,room,panel_text(TXT_SELF_BUILD),number,rest[0]?rest:"--");
}
static void self_drop(void)
{
    self_screen=NULL;update_card=NULL;update_offered=NULL;update_note=NULL;update_button=NULL;
    for(int i=0;i<SELF_ROWS;i++)self_values[i]=NULL;
    /* The page went, so the count of the frames starts again: the next
     * visit shows the movement between the two. */
    panel_frames_reset(&panel_frames);
}
static void self_forget(void)
{
    if(self_screen)lv_obj_delete(self_screen);
    self_drop();
}
static void self_say(int row,const char *text)
{
    if(self_values[row])lv_label_set_text(self_values[row],text&&text[0]?text:"--");
}
/* Millivolts as volts with two places, "3.98 V", and nothing for none. */
static void say_volts(char *out,size_t room,int mv)
{
    if(mv<0){out[0]=0;return;}
    int centivolts=(mv+5)/10;
    snprintf(out,room,"%d.%02d V",centivolts/100,centivolts%100);
}
static void say_milliamps(char *out,size_t room,int ma)
{
    if(ma<0)out[0]=0;
    else snprintf(out,room,"%d mA",ma);
}
/* The power chip in detail: the rows under the charge and the supply,
 * and the settings of the charger in a card of their own. */
static void self_detail_show(const panel_power_detail_t *d)
{
    char said[96];
    say_volts(said,sizeof said,d->vbat_mv);self_say(SELF_VBAT,said);
    self_say(SELF_PHASE,d->phase>=0&&d->phase<=5?panel_text((panel_text_id_t)(TXT_PHASE_TRICKLE+d->phase)):"");
    say_volts(said,sizeof said,d->vbus_mv);self_say(SELF_VBUS,said);
    say_volts(said,sizeof said,d->vsys_mv);self_say(SELF_VSYS,said);
    if(d->die_c!=PANEL_NO_DEGREES)snprintf(said,sizeof said,"%d °C",d->die_c);else said[0]=0;
    self_say(SELF_DIE,said);
    /* What holds the charge current down, and "nothing" for nothing:
     * a chip that answered says so as much as one that names a reason. */
    if(d->charge_ma<0)said[0]=0;
    else{
        const panel_text_id_t why[3]={TXT_HELD_HEAT,TXT_HELD_CURRENT,TXT_HELD_VOLTAGE};
        const bool held[3]={d->held_heat,d->held_current,d->held_voltage};
        said[0]=0;
        for(int i=0;i<3;i++){
            if(!held[i])continue;
            if(said[0])strncat(said,", ",sizeof said-strlen(said)-1);
            strncat(said,panel_text(why[i]),sizeof said-strlen(said)-1);
        }
        if(!said[0])snprintf(said,sizeof said,"%s",panel_text(TXT_HELD_NOTHING));
    }
    self_say(SELF_HELD,said);
    say_milliamps(said,sizeof said,d->charge_ma);self_say(SELF_CHARGE_MA,said);
    say_volts(said,sizeof said,d->charge_mv);self_say(SELF_CHARGE_MV,said);
    say_milliamps(said,sizeof said,d->input_ma);self_say(SELF_INPUT_MA,said);
}
static bool update_power_ok(const panel_state_t *s)
{
    bool on_battery=s->esp_supply==PANEL_SUPPLY_BATTERY&&!s->esp_cable;
    return !on_battery||s->esp_charging||s->esp_battery>=PANEL_UPDATE_LEAST_BATTERY;
}
static void self_show(const panel_state_t *s)
{
    if(!self_screen)return;
    const panel_self_t *self=&s->self;
    char said[64];
    say_version(said,sizeof said,self->version);self_say(SELF_VERSION,said);
    pc_uptime(said,sizeof said,(int32_t)self->uptime_s);self_say(SELF_UPTIME,said);
    unsigned psram_mb=(unsigned)(self->psram_free/1048576),
             psram_tenth=(unsigned)(self->psram_free%1048576*10/1048576);
    if(self->heap_least)
        snprintf(said,sizeof said,"%u KB (min %u KB), PSRAM %u.%u MB",(unsigned)(self->heap_free/1024),
                 (unsigned)(self->heap_least/1024),psram_mb,psram_tenth);
    else
        snprintf(said,sizeof said,"%u KB, PSRAM %u.%u MB",(unsigned)(self->heap_free/1024),
                 psram_mb,psram_tenth);
    self_say(SELF_MEMORY,self->heap_free?said:"");
    self_say(SELF_WIFI,self->ssid);
    if(self->rssi<0){snprintf(said,sizeof said,"%d dBm",self->rssi);self_say(SELF_SIGNAL,said);}
    else self_say(SELF_SIGNAL,"");
    self_say(SELF_IP,self->ip);
    self_say(SELF_MAC,self->mac);
    self_say(SELF_SERVER,self->server);
    if(s->esp_supply==PANEL_SUPPLY_BATTERY){
        snprintf(said,sizeof said,"%d %%%s",s->esp_battery,s->esp_charging?" " LV_SYMBOL_CHARGE:"");
        self_say(SELF_CHARGE,said);
    }else self_say(SELF_CHARGE,"");
    self_say(SELF_SUPPLY,s->esp_supply==PANEL_SUPPLY_UNKNOWN?""
             :s->esp_supply==PANEL_SUPPLY_CABLE?panel_text(TXT_SELF_CABLE)
             :s->esp_charging?panel_text(TXT_CHARGING)
             :s->esp_cable?panel_text(TXT_CHARGED)
             :panel_text(TXT_ON_BATTERY));
    self_detail_show(&s->esp_detail);
    /* The card of the update: there for an offer and for an update that
     * failed, and nowhere else. */
    const panel_update_t *update=&s->update;
    bool failed=update->phase==PANEL_UPDATE_FAILED;
    if(!update->offered[0]&&!failed){lv_obj_add_flag(update_card,LV_OBJ_FLAG_HIDDEN);return;}
    lv_obj_remove_flag(update_card,LV_OBJ_FLAG_HIDDEN);
    say_version(said,sizeof said,update->offered);
    lv_label_set_text(update_offered,update->offered[0]?said:"--");
    /* What stands in the way, or what went wrong the last time. The
     * battery first: it is the one somebody can change now. */
    bool power=update_power_ok(s);
    char note[128]="";
    uint32_t color=MUTED;
    if(!power)snprintf(note,sizeof note,"%s",panel_text(TXT_UPDATE_POWER));
    else if(failed&&update->failure!=TXT_UPDATE_POWER){
        snprintf(note,sizeof note,panel_text(TXT_UPDATE_FAILED),panel_text(update->failure));
        color=RED;
    }
    lv_label_set_text(update_note,note);
    lv_obj_set_style_text_color(update_note,lv_color_hex(color),0);
    bool can=s->online&&update->offered[0]&&power;
    if(can)lv_obj_remove_state(update_button,LV_STATE_DISABLED);
    else lv_obj_add_state(update_button,LV_STATE_DISABLED);
}
/* The frames in movement, read off the count itself and not off the state:
 * see the end of panel_state_t. Once, as the page opens. The page holds
 * the count while it is open, so the numbers stay as they are.
 *
 * Each time row is the mean, the 95th percentile and the most, and the
 * last row the share of the frames that took one, two, three, and four or
 * more frames of the panel. The line under the card says both. */
static void self_frames_show(void)
{
    panel_frame_stats_t frames;
    panel_frames_stats(&panel_frames,&frames);
    bool any=frames.frames>0;
    char said[64];
    snprintf(said,sizeof said,panel_text(TXT_SELF_FPS_SAID),frames.fps,(unsigned)frames.frames);
    self_say(SELF_FPS,any?said:"");
    snprintf(said,sizeof said,"%d / %d / %d ms",frames.interval_mean_ms,
             frames.interval_p95_ms,frames.interval_most_ms);
    self_say(SELF_INTERVAL,any?said:"");
    snprintf(said,sizeof said,"%d / %d / %d ms",frames.draw_mean_ms,
             frames.draw_p95_ms,frames.draw_most_ms);
    self_say(SELF_DRAW,any?said:"");
    snprintf(said,sizeof said,"%d / %d / %d ms",frames.lead_mean_ms,
             frames.lead_p95_ms,frames.lead_most_ms);
    self_say(SELF_LEAD,any?said:"");
    const int *share=frames.periods_pct;
    snprintf(said,sizeof said,"%d / %d / %d / %d %%",share[0],share[1],share[2],share[3]);
    self_say(SELF_PERIODS,share[0]+share[1]+share[2]+share[3]?said:"");
}
static void update_clicked(lv_event_t *e){(void)e;feedback();panel_ui_confirm(PANEL_UPDATE);}
static void self_close(lv_event_t *e){(void)e;feedback();self_forget();}
/* A card of the page, its title and a row for each of its rows. */
static lv_obj_t *self_card(lv_obj_t *column,panel_text_id_t title,const int *rows,int count,const panel_text_id_t *names)
{
    lv_obj_t *card=panel(column,0,0,440,PC_TITLE_ROOM+count*PC_ROW_STEP+PC_CARD_END,CARD,true);
    lv_obj_remove_flag(card,LV_OBJ_FLAG_CLICKABLE);
    text_at(card,panel_text(title),18,14,300,&panel_font_12,MUTED);
    int32_t high=lv_font_get_line_height(&panel_font_14);
    for(int i=0;i<count;i++){
        int y=PC_TITLE_ROOM+i*PC_ROW_STEP;
        lv_obj_t *name=text_at(card,panel_text(names[i]),18,y,PC_NAME_WIDTH,&panel_font_14,MUTED);
        lv_obj_set_height(name,high);
        self_values[rows[i]]=text_at(card,"--",PC_VALUE_X,y,PC_VALUE_WIDTH,&panel_font_14,TEXT);
        lv_obj_set_height(self_values[rows[i]],high);
        lv_obj_set_style_text_align(self_values[rows[i]],LV_TEXT_ALIGN_RIGHT,0);
    }
    return card;
}
void panel_ui_self_open(void)
{
    if(self_screen||pc_screen||pads_screen||settings_screen||setup_screen||sensor_layer||look_layer)return;
    self_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
    button(self_screen,panel_text(TXT_BACK),12,8,112,44,self_close,0);
    text_at(self_screen,panel_text(TXT_SELF_TITLE),136,20,320,&panel_font_20,TEXT);
    line(self_screen,0,62,480,1);
    lv_obj_add_flag(self_screen,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(self_screen,LV_DIR_VER);
    lv_obj_set_scrollbar_mode(self_screen,LV_SCROLLBAR_MODE_AUTO);
    lv_obj_set_style_pad_bottom(self_screen,20,0);
    lv_obj_t *column=lv_obj_create(self_screen);
    lv_obj_remove_style_all(column);
    lv_obj_set_pos(column,20,PC_CARD_TOP);
    lv_obj_set_size(column,440,LV_SIZE_CONTENT);
    lv_obj_remove_flag(column,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(column,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_flex_flow(column,LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(column,PC_CARD_GAP,0);
    static const int firmware[]={SELF_VERSION,SELF_UPTIME,SELF_MEMORY};
    static const panel_text_id_t firmware_names[]={TXT_SELF_VERSION,TXT_PC_UPTIME,TXT_SELF_MEMORY};
    self_card(column,TXT_SELF_FIRMWARE,firmware,3,firmware_names);
    /* The update, under the firmware it replaces. */
    update_card=panel(column,0,0,440,UPDATE_CARD_HEIGHT,CARD,true);
    lv_obj_remove_flag(update_card,LV_OBJ_FLAG_CLICKABLE);
    text_at(update_card,panel_text(TXT_UPDATE),18,14,300,&panel_font_12,MUTED);
    lv_obj_t *name=text_at(update_card,panel_text(TXT_UPDATE_OFFERED),18,PC_TITLE_ROOM,PC_NAME_WIDTH,&panel_font_14,MUTED);
    lv_obj_set_height(name,lv_font_get_line_height(&panel_font_14));
    update_offered=text_at(update_card,"--",PC_VALUE_X,PC_TITLE_ROOM,PC_VALUE_WIDTH,&panel_font_14,BLUE);
    lv_obj_set_style_text_align(update_offered,LV_TEXT_ALIGN_RIGHT,0);
    update_note=text_at(update_card,"",18,PC_TITLE_ROOM+PC_ROW_STEP,404,&panel_font_14,MUTED);
    lv_label_set_long_mode(update_note,LV_LABEL_LONG_WRAP);
    update_button=button(update_card,panel_text(TXT_UPDATE_NOW),18,UPDATE_CARD_HEIGHT-58,404,44,update_clicked,0);
    lv_obj_set_style_bg_color(update_button,lv_color_hex(BLUE),0);
    lv_obj_set_style_text_color(update_button,lv_color_hex(BG),0);
    lv_obj_add_flag(update_card,LV_OBJ_FLAG_HIDDEN);
    /* The frames in movement, with a line under the rows that says what
     * the numbers are and since when they count. */
    static const int motion[]={SELF_FPS,SELF_INTERVAL,SELF_DRAW,SELF_LEAD,SELF_PERIODS};
    static const panel_text_id_t motion_names[]={TXT_SELF_FPS,TXT_SELF_INTERVAL,TXT_SELF_DRAW,
                                                 TXT_SELF_LEAD,TXT_SELF_PERIODS};
    lv_obj_t *motion_card=self_card(column,TXT_SELF_MOTION,motion,5,motion_names);
    int32_t note_top=PC_TITLE_ROOM+5*PC_ROW_STEP;
    lv_obj_t *note=text_at(motion_card,panel_text(TXT_SELF_MOTION_WHAT),18,note_top,404,&panel_font_12,MUTED);
    lv_label_set_long_mode(note,LV_LABEL_LONG_WRAP);
    lv_obj_set_height(motion_card,note_top+2*lv_font_get_line_height(&panel_font_12)+PC_CARD_END+4);
    static const int network[]={SELF_WIFI,SELF_SIGNAL,SELF_IP,SELF_MAC,SELF_SERVER};
    static const panel_text_id_t network_names[]={TXT_WIRELESS,TXT_SELF_SIGNAL,TXT_PC_IP,TXT_PC_MAC,TXT_SELF_SERVER};
    self_card(column,TXT_PC_NETWORK,network,5,network_names);
    static const int power[]={SELF_CHARGE,SELF_SUPPLY,SELF_VBAT,SELF_PHASE,
                              SELF_VBUS,SELF_VSYS,SELF_DIE,SELF_HELD};
    static const panel_text_id_t power_names[]={TXT_SELF_CHARGE,TXT_SELF_SUPPLY,
        TXT_SELF_VBAT,TXT_SELF_PHASE,TXT_SELF_VBUS,TXT_SELF_VSYS,TXT_SELF_DIE,TXT_SELF_HELD};
    self_card(column,TXT_SELF_POWER,power,8,power_names);
    /* What the charger is set to: the current and the voltage it charges
     * at, and the most it takes from the cable. */
    static const int charger[]={SELF_CHARGE_MA,SELF_CHARGE_MV,SELF_INPUT_MA};
    static const panel_text_id_t charger_names[]={TXT_SELF_CHARGE_MA,TXT_SELF_CHARGE_MV,TXT_SELF_INPUT_MA};
    self_card(column,TXT_SELF_CHARGER,charger,3,charger_names);
    /* What the page shows stays as it was while it is open: its own frames,
     * its scroll among them, are not the movement it reports. */
    panel_frames_hold(&panel_frames,true);
    self_frames_show();
    if(last_state_valid)self_show(&last_state);
}
static void self_clicked(lv_event_t *e){(void)e;feedback();panel_ui_self_open();}
/* The screen of an update that writes, over everything, with its share
 * done. It stays until the restart; a failure takes it away and the page
 * of the panel says why. */
static void update_layer_show(const panel_state_t *s)
{
    bool busy=s->update.phase==PANEL_UPDATE_RUNNING||s->update.phase==PANEL_UPDATE_RESTARTING;
    if(!busy){
        if(update_layer){lv_obj_delete(update_layer);update_layer=NULL;}
        return;
    }
    if(!update_layer){
        update_layer=panel(lv_screen_active(),0,0,480,480,BG,false);
        lv_obj_t *box=panel(update_layer,20,140,440,200,CARD,true);
        lv_obj_remove_flag(box,LV_OBJ_FLAG_CLICKABLE);
        update_title=text_at(box,"",20,22,400,&panel_font_20,TEXT);
        lv_obj_t *track=panel(box,20,78,400,12,EDGE,false);
        lv_obj_set_style_radius(track,LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(track,LV_OBJ_FLAG_CLICKABLE);
        update_bar=panel(track,0,0,0,12,BLUE,false);
        lv_obj_set_style_radius(update_bar,LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(update_bar,LV_OBJ_FLAG_CLICKABLE);
        update_percent=text_at(box,"",20,104,400,&panel_font_24,BLUE);
        update_hint=text_at(box,"",20,150,400,&panel_font_16,MUTED);
    }
    bool restarting=s->update.phase==PANEL_UPDATE_RESTARTING;
    int percent=s->update.percent<0?0:s->update.percent>100?100:s->update.percent;
    lv_label_set_text(update_title,panel_text(TXT_UPDATE_RUNNING));
    lv_obj_set_width(update_bar,400*percent/100);
    lv_label_set_text_fmt(update_percent,"%d %%",percent);
    lv_label_set_text(update_hint,panel_text(restarting?TXT_UPDATE_RESTART:TXT_UPDATE_KEEP_ON));
}
static void gpu_tile_clicked(lv_event_t *e){(void)e;feedback();sensor_menu(true);}
const char *panel_ui_where(void)
{
    if(setup_screen)return "the setup";
    if(overlay)return "a question";
    if(sensor_layer)return "a choice of sensor";
    if(look_layer)return "the colour of the LED bar";
    if(arrange_screen)return "the order of the pages";
    if(settings_screen)return "the settings";
    if(pads_screen)return "the controllers";
    if(pc_screen)return "the PC";
    if(update_layer)return "an update";
    if(self_screen)return "the panel";
    if(!band)return "no screen";
    /* The name is the one of the page and not of its place, which
     * somebody can change. See band_page. */
    static const char *const pages[PANEL_PAGES]={"the controls","the session",
                                                 "the game","the clock","the card",
                                                 "the LED bar","the CPU"};
    return pages[band_page()];
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
/* The page of the LED bar: a card for each mode of the PC, with its
 * effect between two arrows.
 *
 * A tap shows the next effect at once, and the change goes to the PC
 * LED_WAIT_MS after the last tap. Each change starts the LED service of
 * the PC again, and somebody who steps through four effects to reach the
 * fifth means the fifth. The page shows the choice until the PC shows it
 * back. It goes back to the effect of the PC when the PC refuses the
 * change, and when no answer shows the change in LED_SHOWN_MS. */
#define LED_WAIT_MS 1500
#define LED_SHOWN_MS 20000
/* The two cards, one above the other with a gap of 8. The card of the
 * desktop has the button of the colour and the brightness under its arrows,
 * across the card as the button of SteamOS on the page of the CPU is, and
 * the card of Game Mode a line in that place. */
#define LED_DESKTOP_HIGH 158
#define LED_GAME_HIGH 134
/* In the button: the dot of the colour, and the room after it. */
#define LOOK_DOT 14
#define LOOK_GAP 8
/* Their layer: the title, the colours in three rows, and the brightness with
 * its slider and Done. */
#define LOOK_TOP 62
#define LOOK_COLOURS_ROOM (24+3*54+8)
#define LOOK_LEVEL_ROOM (62+44+16)
/* How long the reason for a refusal stays under the effect. */
#define LED_REFUSAL_MS 8000
typedef struct {
    lv_obj_t *now,*back,*next,*name,*note;
    /* The place of the effect somebody chose and the PC does not show
     * yet, or -1. sent: it went to main.c, at sent_at. */
    int wanted;
    bool sent;
    uint32_t sent_at;
    /* Why the PC did not take the last change, since refused_at. */
    bool refused;
    panel_text_id_t refusal;
    uint32_t refused_at;
} led_card_t;
static led_card_t led_cards[PANEL_LED_MODES];
static panel_led_cb_t led_send;
static lv_timer_t *led_timer;
/* A colour or a brightness of the desktop scenes that somebody chose and
 * the PC does not show yet, as for an effect: wanted is the place of the
 * colour, or the brightness from 0 to 255, and -1 for none. They go with
 * the effects, and a refusal of them goes on the card of the desktop. */
typedef struct { int wanted; bool sent; uint32_t sent_at; } led_pick_t;
static led_pick_t look_colour={.wanted=-1},look_level={.wanted=-1};
/* The button under the effect of the desktop, with the dot of the colour
 * and its words, and the colour the dot has: -1 for none yet. */
static lv_obj_t *look_button,*look_dot,*look_words;
static int32_t look_dot_rgb=-1;
/* The layer that chooses the two, over the whole screen as the choice of a
 * sensor is. It has the colours only for a scene in the desktop colour.
 * look_lit is what each colour shows: -1 for nothing yet, 0, 1 chosen. */
static lv_obj_t *look_slider,*look_value,*look_swatches[PANEL_LED_COLOURS];
static int8_t look_lit[PANEL_LED_COLOURS];
static bool look_with_colours;
/* The count of the answers to changes that the page has seen. */
static uint32_t led_replies_seen;
void panel_ui_led_use(panel_led_cb_t callback){led_send=callback;}
/* What the code of an answer to a change means to somebody at a page:
 * the page of the LED bar or of the CPU, which name their own module. */
static panel_text_id_t change_refusal(int code,panel_text_id_t no_module)
{
    switch(code){
    case 403:return TXT_CHANGE_NO_RULE;
    case 409:return TXT_CHANGE_BUSY;
    case 501:return no_module;
    default:return TXT_CHANGE_REFUSED;
    }
}
static void look_button_show(const panel_state_t *s,int index,bool show);
static void look_show(const panel_state_t *s);
static void led_show(const panel_state_t *s)
{
    if(!led_cards[PANEL_LED_DESKTOP].name)return;
    /* An answer to a change: a refusal takes back each choice that went
     * with it. A choice made after it went is not in it, and stays. */
    if(s->led_replies!=led_replies_seen){
        led_replies_seen=s->led_replies;
        for(int m=0;m<PANEL_LED_MODES&&s->led_code!=200;m++){
            led_card_t *c=&led_cards[m];
            if(c->wanted<0||!c->sent)continue;
            c->wanted=-1;c->sent=false;
            c->refused=true;c->refusal=change_refusal(s->led_code,TXT_LED_NO_MODULE);c->refused_at=lv_tick_get();
        }
        for(int i=0;i<2&&s->led_code!=200;i++){
            led_pick_t *pick=i?&look_level:&look_colour;
            if(pick->wanted<0||!pick->sent)continue;
            pick->wanted=-1;pick->sent=false;
            led_card_t *c=&led_cards[PANEL_LED_DESKTOP];
            c->refused=true;c->refusal=change_refusal(s->led_code,TXT_LED_NO_MODULE);c->refused_at=lv_tick_get();
        }
    }
    /* A colour or a brightness shown by the PC, or not shown in time. */
    const char *colour=panel_led_colour(look_colour.wanted);
    if(look_colour.sent&&(!colour||strcmp(s->led_colour,colour)==0
                          ||lv_tick_elaps(look_colour.sent_at)>LED_SHOWN_MS)){look_colour.wanted=-1;look_colour.sent=false;}
    if(look_level.sent&&(s->led_brightness==look_level.wanted
                         ||lv_tick_elaps(look_level.sent_at)>LED_SHOWN_MS)){look_level.wanted=-1;look_level.sent=false;}
    bool usable=s->online&&s->led_here;
    for(int m=0;m<PANEL_LED_MODES;m++){
        led_card_t *c=&led_cards[m];
        const char *chosen=panel_led_key((panel_led_mode_t)m,c->wanted);
        /* Shown by the PC, or not shown in time: the choice is over. */
        if(c->sent&&(!chosen||strcmp(s->led_effect[m],chosen)==0
                     ||lv_tick_elaps(c->sent_at)>LED_SHOWN_MS)){c->wanted=-1;c->sent=false;}
        if(c->refused&&lv_tick_elaps(c->refused_at)>LED_REFUSAL_MS)c->refused=false;
        int index=c->wanted>=0?c->wanted:panel_led_find((panel_led_mode_t)m,s->led_effect[m]);
        /* A key of a later service has no name here, and shows as it is. */
        set_text(c->name,!usable?panel_text(TXT_LED_UNKNOWN)
                 :index>=0?panel_text(panel_led_name((panel_led_mode_t)m,index))
                 :s->led_effect[m][0]?s->led_effect[m]:panel_text(TXT_LED_UNKNOWN));
        enable(c->back,usable);enable(c->next,usable);
        /* The card of the mode the PC is in. A flag set or taken again
         * draws the label again, at each answer of the PC, so only a
         * change goes to LVGL. */
        bool now=s->online&&(m==PANEL_LED_GAME)==s->game_mode;
        if(now==lv_obj_has_flag(c->now,LV_OBJ_FLAG_HIDDEN)){
            if(now)lv_obj_remove_flag(c->now,LV_OBJ_FLAG_HIDDEN);else lv_obj_add_flag(c->now,LV_OBJ_FLAG_HIDDEN);
        }
        const char *note="";
        bool look=false;
        if(c->wanted>=0||(m==PANEL_LED_DESKTOP&&(look_colour.wanted>=0||look_level.wanted>=0)))
            note=panel_text(TXT_CHANGE_APPLYING);
        else if(c->refused)note=panel_text(c->refusal);
        else if(s->online&&!s->led_here){
            /* Once, on the first card: no LED module, or a service of the PC
             * that is older than this firmware and knows no page of this
             * kind. A firmware that comes before the update of the PC is
             * the usual way to get the second. */
            if(m==PANEL_LED_DESKTOP)note=panel_text(s->led_known?TXT_LED_NONE:TXT_PC_TOO_OLD);
        }
        else if(m==PANEL_LED_GAME)note=panel_text(TXT_LED_GAME_WHAT);
        /* The button of the colour and the brightness takes the place of
         * the line, for a scene that uses them. A service that sends
         * neither keeps the line that says where the colour comes from. */
        else if(usable&&s->led_look&&panel_led_lit((panel_led_mode_t)m,index))look=true;
        else if(usable&&panel_led_coloured((panel_led_mode_t)m,index))note=panel_text(TXT_LED_COLOUR_WHAT);
        set_text(c->note,note);
        if(m==PANEL_LED_DESKTOP)look_button_show(s,index,look);
    }
    look_show(s);
}
/* LED_WAIT_MS after the last tap: each choice that is new goes to main.c
 * in one change. A choice of the effect the PC has already is no change. */
static void led_due(lv_timer_t *timer)
{
    lv_timer_pause(timer);
    panel_led_change_t change={.brightness=-1};
    bool any=false;
    for(int m=0;m<PANEL_LED_MODES;m++){
        led_card_t *c=&led_cards[m];
        if(c->wanted<0||c->sent)continue;
        const char *chosen=panel_led_key((panel_led_mode_t)m,c->wanted);
        if(!chosen||(last_state_valid&&strcmp(last_state.led_effect[m],chosen)==0)){c->wanted=-1;continue;}
        snprintf(change.effect[m],sizeof change.effect[m],"%s",chosen);
        c->sent=true;c->sent_at=lv_tick_get();any=true;
    }
    /* The colour and the brightness, the same way. */
    if(look_colour.wanted>=0&&!look_colour.sent){
        const char *chosen=panel_led_colour(look_colour.wanted);
        if(!chosen||(last_state_valid&&strcmp(last_state.led_colour,chosen)==0))look_colour.wanted=-1;
        else{
            snprintf(change.colour,sizeof change.colour,"%s",chosen);
            look_colour.sent=true;look_colour.sent_at=lv_tick_get();any=true;
        }
    }
    if(look_level.wanted>=0&&!look_level.sent){
        if(last_state_valid&&last_state.led_brightness==look_level.wanted)look_level.wanted=-1;
        else{change.brightness=look_level.wanted;look_level.sent=true;look_level.sent_at=lv_tick_get();any=true;}
    }
    if(any&&led_send)led_send(&change);
    if(last_state_valid)led_show(&last_state);
}
/* The wait after a choice of the page starts again. */
static void led_later(void)
{
    if(!led_timer)led_timer=lv_timer_create(led_due,LED_WAIT_MS,NULL);
    lv_timer_reset(led_timer);lv_timer_resume(led_timer);
}
static void led_step(lv_event_t *e)
{
    int data=(int)(intptr_t)lv_event_get_user_data(e);
    panel_led_mode_t m=(panel_led_mode_t)(data/2);
    if(!last_state_valid||!last_state.online||!last_state.led_here)return;
    feedback();
    led_card_t *c=&led_cards[m];
    int from=c->wanted>=0?c->wanted:panel_led_find(m,last_state.led_effect[m]);
    c->wanted=panel_led_step(m,from,data%2?1:-1);
    c->sent=false;c->refused=false;
    led_later();
    led_show(&last_state);
}
/* The effect that the card of the desktop shows: the choice, or the PC's. */
static int look_scene(const panel_state_t *s)
{
    const led_card_t *c=&led_cards[PANEL_LED_DESKTOP];
    return c->wanted>=0?c->wanted:panel_led_find(PANEL_LED_DESKTOP,s->led_effect[PANEL_LED_DESKTOP]);
}
/* The colour and the brightness that the page shows: the choice, or the
 * PC's. The colour is its place, or -1 for one that is not in the list. */
static int look_colour_shown(const panel_state_t *s)
{
    return look_colour.wanted>=0?look_colour.wanted:panel_led_colour_find(s->led_colour);
}
static int look_level_shown(const panel_state_t *s)
{
    return look_level.wanted>=0?look_level.wanted:s->led_brightness;
}
static void look_button_show(const panel_state_t *s,int index,bool show)
{
    if(!look_button)return;
    if(show==lv_obj_has_flag(look_button,LV_OBJ_FLAG_HIDDEN)){
        if(show)lv_obj_remove_flag(look_button,LV_OBJ_FLAG_HIDDEN);else lv_obj_add_flag(look_button,LV_OBJ_FLAG_HIDDEN);
    }
    if(!show)return;
    /* The colour and the brightness for a scene in the desktop colour, and
     * the brightness alone for one that makes its own colours. */
    bool coloured=panel_led_coloured(PANEL_LED_DESKTOP,index);
    int colour=look_colour_shown(s);
    int percent=panel_led_percent(look_level_shown(s));
    char said[48];
    if(coloured)snprintf(said,sizeof said,"%s • %d %%",panel_text(panel_led_colour_name(colour)),percent);
    else snprintf(said,sizeof said,"%s %d %%",panel_text(TXT_LED_BRIGHTNESS),percent);
    uint32_t rgb=0;
    bool dot=coloured&&panel_led_rgb(colour>=0?panel_led_colour(colour):s->led_colour,&rgb);
    int32_t dot_now=dot?(int32_t)rgb:-1;
    if(dot_now==look_dot_rgb&&strcmp(lv_label_get_text(look_words),said)==0)return;
    if(dot_now!=look_dot_rgb){
        if(dot){
            lv_obj_set_style_bg_color(look_dot,lv_color_hex(rgb),0);
            lv_obj_remove_flag(look_dot,LV_OBJ_FLAG_HIDDEN);
        }
        else lv_obj_add_flag(look_dot,LV_OBJ_FLAG_HIDDEN);
        look_dot_rgb=dot_now;
    }
    set_text(look_words,said);
    /* The dot and the words together in the middle of the button, which
     * is 428 wide inside its border. */
    int32_t from=(428-(dot?LOOK_DOT+LOOK_GAP:0)-text_width(said,&panel_font_16))/2;
    lv_obj_set_x(look_dot,from);
    lv_obj_set_x(look_words,from+(dot?LOOK_DOT+LOOK_GAP:0));
}
static void look_close(void)
{
    if(!look_layer)return;
    lv_obj_delete(look_layer);look_layer=NULL;look_slider=NULL;look_value=NULL;
    for(int i=0;i<PANEL_LED_COLOURS;i++)look_swatches[i]=NULL;
}
static void look_outside(lv_event_t *e){(void)e;look_close();}
static void look_done(lv_event_t *e){(void)e;feedback();look_close();}
static void look_show(const panel_state_t *s)
{
    if(!look_layer)return;
    /* A PC that goes, or a scene that takes another set of the two: the
     * layer has nothing left to set. */
    int index=look_scene(s);
    if(!s->online||!s->led_here||!s->led_look||!panel_led_lit(PANEL_LED_DESKTOP,index)
       ||panel_led_coloured(PANEL_LED_DESKTOP,index)!=look_with_colours){look_close();return;}
    int colour=look_colour_shown(s);
    for(int i=0;look_with_colours&&i<PANEL_LED_COLOURS;i++){
        int8_t lit=i==colour;
        if(lit==look_lit[i])continue;
        look_lit[i]=lit;
        /* An outline and not a wider border, which would move what the
         * button holds. */
        lv_obj_set_style_outline_width(look_swatches[i],lit?2:0,0);
    }
    /* Not under a finger that moves it. */
    if(lv_obj_has_state(look_slider,LV_STATE_PRESSED))return;
    int percent=panel_led_percent(look_level_shown(s));
    if(lv_slider_get_value(look_slider)!=percent)lv_slider_set_value(look_slider,percent,LV_ANIM_OFF);
    char said[16];
    snprintf(said,sizeof said,"%d %%",percent);
    set_text(look_value,said);
}
/* A tap on a colour and the release of the slider. Each status that shows
 * a PC that cannot take them closes the layer, so the layer that takes a
 * tap belongs to a PC that can. */
static void look_pick(lv_event_t *e)
{
    feedback();
    look_colour.wanted=(int)(intptr_t)lv_event_get_user_data(e);look_colour.sent=false;
    led_cards[PANEL_LED_DESKTOP].refused=false;
    led_later();
    led_show(&last_state);
}
static void look_slid(lv_event_t *e)
{
    int percent=lv_slider_get_value(look_slider);
    char said[16];
    snprintf(said,sizeof said,"%d %%",percent);
    set_text(look_value,said);
    if(lv_event_get_code(e)!=LV_EVENT_RELEASED)return;
    look_level.wanted=panel_led_brightness(percent);look_level.sent=false;
    led_cards[PANEL_LED_DESKTOP].refused=false;
    led_later();
    led_show(&last_state);
}
/* The colours from the top, three in a row, and the brightness under them.
 * A tap on a colour or the release of the slider chooses, and the choice
 * goes after LED_WAIT_MS with whatever else the page chose. Done, or a tap
 * beside the box, closes it. */
static void look_open(void)
{
    if(look_layer||sensor_layer||overlay||settings_screen||pads_screen||pc_screen||self_screen
       ||update_layer||setup_screen)return;
    int index=look_scene(&last_state);
    look_with_colours=panel_led_coloured(PANEL_LED_DESKTOP,index);
    int colours=look_with_colours?LOOK_COLOURS_ROOM:0;
    int high=LOOK_TOP+colours+LOOK_LEVEL_ROOM;
    look_layer=panel(lv_screen_active(),0,0,480,480,BG,false);
    lv_obj_set_style_bg_opa(look_layer,LV_OPA_90,0);
    lv_obj_add_event_cb(look_layer,look_outside,LV_EVENT_CLICKED,NULL);
    /* The box takes a tap of its own, so a tap beside the slider does not
     * close it. */
    lv_obj_t *box=panel(look_layer,20,(480-high)/2,440,high,CARD,true);
    text_at(box,panel_text(TXT_LED_DESKTOP),20,16,400,&panel_font_20,TEXT);
    line(box,20,50,398,1);
    for(int i=0;look_with_colours&&i<PANEL_LED_COLOURS;i++){
        if(i==0)text_at(box,panel_text(TXT_LED_COLOUR),20,LOOK_TOP,400,&panel_font_14,MUTED);
        lv_obj_t *b=button(box,"",20+(i%3)*136,LOOK_TOP+24+(i/3)*54,128,46,look_pick,i);
        lv_obj_set_style_outline_color(b,lv_color_hex(BLUE),0);
        lv_obj_set_style_outline_pad(b,1,0);
        uint32_t rgb=0;
        panel_led_rgb(panel_led_colour(i),&rgb);
        lv_obj_t *dot=panel(b,12,15,16,16,rgb,false);
        lv_obj_set_style_radius(dot,LV_RADIUS_CIRCLE,0);
        lv_obj_set_style_border_width(dot,1,0);lv_obj_set_style_border_color(dot,lv_color_hex(MUTED),0);
        lv_obj_remove_flag(dot,LV_OBJ_FLAG_CLICKABLE);
        lv_obj_t *name=text_at(b,panel_text(panel_led_colour_name(i)),36,
                               (46-lv_font_get_line_height(&panel_font_16))/2-1,86,&panel_font_16,TEXT);
        lv_obj_set_height(name,lv_font_get_line_height(&panel_font_16));
        look_swatches[i]=b;look_lit[i]=-1;
    }
    int y=LOOK_TOP+colours;
    text_at(box,panel_text(TXT_LED_BRIGHTNESS),20,y,280,&panel_font_14,MUTED);
    look_value=text_at(box,"",300,y,118,&panel_font_14,TEXT);
    lv_obj_set_style_text_align(look_value,LV_TEXT_ALIGN_RIGHT,0);
    look_slider=slider_with(box,29,y+34,0,100,panel_led_percent(look_level_shown(&last_state)),look_slid,0);
    button(box,panel_text(TXT_LED_DONE),149,y+62,140,44,look_done,0);
    look_show(&last_state);
}
/* The button shows only for a PC that can take the two. */
static void look_clicked(lv_event_t *e)
{
    (void)e;
    feedback();
    look_open();
}
/* The page of the CPU: a button for each profile, and under them what runs.
 *
 * A tap sends the profile at once: one tap is one choice, and nothing here
 * starts a service again. The button of the choice is lit until the status
 * shows the profile, and the page goes back to the profile of the PC when
 * the PC refuses it or no answer shows it in LED_SHOWN_MS, as the page of
 * the LED bar does. A profile that the PC does not offer is grey: a driver
 * with no preference has no power saving profile. See power.PROFILES. */
static lv_obj_t *cpu_buttons[PANEL_CPU_PROFILES],*cpu_running,*cpu_driver_line,*cpu_note;
/* What each button shows: -1 for nothing yet, 0 dark, 1 lit. */
static int8_t cpu_lit[PANEL_CPU_PROFILES];
static panel_cpu_cb_t cpu_send;
/* The profile somebody chose and the PC does not show yet, or -1, sent at
 * cpu_sent_at; and why the PC did not take the last one. */
static int cpu_wanted=-1;
static uint32_t cpu_sent_at,cpu_refused_at,cpu_replies_seen;
static bool cpu_refused;
static panel_text_id_t cpu_refusal;
void panel_ui_cpu_use(panel_cpu_cb_t callback){cpu_send=callback;}
static void cpu_show(const panel_state_t *s)
{
    if(!cpu_note)return;
    if(s->cpu_replies!=cpu_replies_seen){
        cpu_replies_seen=s->cpu_replies;
        if(s->cpu_code!=200&&cpu_wanted>=0){
            cpu_wanted=-1;
            cpu_refused=true;cpu_refusal=change_refusal(s->cpu_code,TXT_CPU_NO_MODULE);
            cpu_refused_at=lv_tick_get();
        }
    }
    int current=panel_cpu_find(s->cpu_profile);
    /* Shown by the PC, or not shown in time: the choice is over. */
    if(cpu_wanted>=0&&(cpu_wanted==current||lv_tick_elaps(cpu_sent_at)>LED_SHOWN_MS))cpu_wanted=-1;
    if(cpu_refused&&lv_tick_elaps(cpu_refused_at)>LED_REFUSAL_MS)cpu_refused=false;
    bool usable=s->online&&s->cpu_here;
    int selected=!usable?-1:cpu_wanted>=0?cpu_wanted:current;
    for(int p=0;p<PANEL_CPU_PROFILES;p++){
        enable(cpu_buttons[p],usable&&((s->cpu_offers>>p)&1));
        int8_t lit=p==selected;
        if(lit==cpu_lit[p])continue;
        cpu_lit[p]=lit;
        lv_obj_set_style_bg_color(cpu_buttons[p],lv_color_hex(lit?BLUE:0x1B2B3C),0);
        lv_obj_set_style_text_color(cpu_buttons[p],lv_color_hex(lit?BG:TEXT),0);
    }
    char running[56];
    if(usable&&s->cpu_governor[0])
        snprintf(running,sizeof running,s->cpu_epp[0]?"%s / %s":"%s%s",s->cpu_governor,s->cpu_epp);
    else snprintf(running,sizeof running,"--");
    set_text(cpu_running,running);
    char driver[48]="";
    if(usable&&s->cpu_driver[0])snprintf(driver,sizeof driver,panel_text(TXT_CPU_DRIVER),s->cpu_driver);
    set_text(cpu_driver_line,driver);
    const char *note="";
    if(cpu_wanted>=0)note=panel_text(TXT_CHANGE_APPLYING);
    else if(cpu_refused)note=panel_text(cpu_refusal);
    else if(s->online&&!s->cpu_here)note=panel_text(s->cpu_known?TXT_CPU_NONE:TXT_PC_TOO_OLD);
    else if(usable&&current<0&&s->cpu_profile[0])note=panel_text(TXT_CPU_CUSTOM);
    set_text(cpu_note,note);
}
static void cpu_clicked(lv_event_t *e)
{
    int profile=(int)(intptr_t)lv_event_get_user_data(e);
    if(!last_state_valid||!last_state.online||!last_state.cpu_here
       ||!((last_state.cpu_offers>>profile)&1))return;
    feedback();
    cpu_refused=false;
    /* The profile the PC has already is no change. */
    if(cpu_wanted<0&&profile==panel_cpu_find(last_state.cpu_profile)){cpu_show(&last_state);return;}
    cpu_wanted=profile;cpu_sent_at=lv_tick_get();
    if(cpu_send)cpu_send(profile);
    cpu_show(&last_state);
}
static void cpu_page(lv_obj_t *page)
{
    lv_obj_t *card=panel(page,10,0,460,170,CARD,true);
    icon(card,&icon_cpu,14,14,MUTED);
    text_at(card,panel_text(TXT_CPU_TITLE),52,16,380,&panel_font_14,MUTED);
    line(card,14,44,432,1);
    /* The three from the least power to the most, side by side, and the way
     * back to SteamOS under them across the card. */
    for(int p=0;p<PANEL_CPU_STEAMOS;p++)
        cpu_buttons[p]=button(card,panel_text(panel_cpu_name(p)),14+p*146,56,138,56,cpu_clicked,p);
    cpu_buttons[PANEL_CPU_STEAMOS]=button(card,panel_text(TXT_CPU_STEAMOS),14,120,430,40,
                                          cpu_clicked,PANEL_CPU_STEAMOS);
    lv_obj_set_style_text_font(cpu_buttons[PANEL_CPU_STEAMOS],&panel_font_14,0);
    for(int p=0;p<PANEL_CPU_PROFILES;p++){cpu_lit[p]=-1;enable(cpu_buttons[p],false);}
    lv_obj_t *now=panel(page,10,180,460,120,CARD,true);
    text_at(now,panel_text(TXT_CPU_RUNNING),16,12,300,&panel_font_14,MUTED);
    cpu_running=text_at(now,"--",16,34,428,&panel_font_18,TEXT);
    cpu_driver_line=text_at(now,"",16,62,428,&panel_font_12,MUTED);
    cpu_note=text_at(now,"",16,88,428,&panel_font_12,MUTED);
}
/* One card of the page, "y" down the page. */
static void led_card(lv_obj_t *page,panel_led_mode_t m,int y)
{
    led_card_t *c=&led_cards[m];
    lv_obj_t *card=panel(page,10,y,460,m==PANEL_LED_DESKTOP?LED_DESKTOP_HIGH:LED_GAME_HIGH,CARD,true);
    icon(card,m==PANEL_LED_GAME?&icon_gamepad_2:&icon_monitor,14,14,MUTED);
    text_at(card,panel_text(m==PANEL_LED_GAME?TXT_LED_GAME:TXT_LED_DESKTOP),52,16,290,&panel_font_14,MUTED);
    c->now=text_at(card,panel_text(TXT_LED_NOW),346,16,100,&panel_font_14,BLUE);
    lv_obj_set_style_text_align(c->now,LV_TEXT_ALIGN_RIGHT,0);
    lv_obj_add_flag(c->now,LV_OBJ_FLAG_HIDDEN);
    line(card,14,40,432,1);
    c->back=button(card,LV_SYMBOL_LEFT,14,48,72,52,led_step,m*2);
    c->next=button(card,LV_SYMBOL_RIGHT,372,48,72,52,led_step,m*2+1);
    lv_obj_set_style_text_font(c->back,&panel_font_24,0);
    lv_obj_set_style_text_font(c->next,&panel_font_24,0);
    enable(c->back,false);enable(c->next,false);
    c->name=text_at(card,panel_text(TXT_LED_UNKNOWN),94,48+(52-lv_font_get_line_height(&panel_font_24))/2,
                    270,&panel_font_24,TEXT);
    center_text(c->name);
    c->note=text_at(card,"",14,m==PANEL_LED_DESKTOP?118:108,430,&panel_font_12,MUTED);
    center_text(c->note);
    if(m!=PANEL_LED_DESKTOP)return;
    /* Hidden until a scene that uses it. look_button_show sets what it holds,
     * and where. */
    look_button=button(card,"",14,108,430,36,look_clicked,0);
    lv_obj_add_flag(look_button,LV_OBJ_FLAG_HIDDEN);
    look_dot=panel(look_button,0,(36-2-LOOK_DOT)/2,LOOK_DOT,LOOK_DOT,TEXT,false);
    lv_obj_set_style_radius(look_dot,LV_RADIUS_CIRCLE,0);
    lv_obj_set_style_border_width(look_dot,1,0);lv_obj_set_style_border_color(look_dot,lv_color_hex(MUTED),0);
    lv_obj_remove_flag(look_dot,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(look_dot,LV_OBJ_FLAG_HIDDEN);
    look_words=text_at(look_button,"",0,(36-2-lv_font_get_line_height(&panel_font_16))/2,
                       LV_SIZE_CONTENT,&panel_font_16,TEXT);
    look_dot_rgb=-1;
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
    center_text(text_at(box,panel_text(TXT_TIMER),20,26,400,&panel_font_20,MUTED));
    center_text(text_at(box,panel_text(TXT_TIME_UP),20,64,400,&panel_font_32,TEXT));
    lv_obj_t *stop=button(box,panel_text(TXT_STOP),70,152,300,72,alarm_clicked,0);
    lv_obj_set_style_bg_color(stop,lv_color_hex(BLUE),0);
    lv_obj_set_style_text_color(stop,lv_color_hex(BG),0);
    lv_obj_set_style_text_font(stop,&panel_font_24,0);
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
    drive_names[index]=text_at(drive_rows[index],"",0,0,150,&panel_font_16,TEXT);
    drive_free[index]=text_at(drive_rows[index],"",152,0,DRIVE_BAR_WIDTH-152,&panel_font_14,MUTED);
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
    text_at(b,caption,54,18,136,&panel_font_16,color);
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
    lv_obj_clean(s);overlay=NULL;setup_screen=NULL;setup_text=NULL;sensor_layer=NULL;
    look_layer=NULL;look_slider=NULL;look_value=NULL;
    for(int i=0;i<PANEL_LED_COLOURS;i++)look_swatches[i]=NULL;
    /* The settings page is a child of this screen too, so the clean
     * above took it. Kept, its pointer is the reason that
     * panel_ui_settings_open returns at once and the page never opens
     * again. check_navigation builds the screens with that page open. */
    settings_drop();
    /* The pages of the controllers and of the PC too, for the same
     * reason. */
    pads_drop();pc_drop();self_drop();
    update_layer=NULL;
    /* The band and everything on the second and third pages are children
     * of this screen too. A pointer kept past the clean above is a pointer
     * to freed memory, and panel_ui_update writes through these. */
    band=NULL;mode_now=NULL;mode_button=NULL;mode_caption=NULL;
    for(int i=0;i<PANEL_PAGES;i++)band_pages[i]=NULL;
    arrange_drop();
    /* The cards of the LED bar, and a choice that waits to go: a change
     * that the old screen made goes with it. */
    for(int m=0;m<PANEL_LED_MODES;m++)led_cards[m]=(led_card_t){.wanted=-1};
    look_colour=look_level=(led_pick_t){.wanted=-1};
    look_button=NULL;look_dot=NULL;look_words=NULL;
    if(led_timer)lv_timer_pause(led_timer);
    for(int p=0;p<PANEL_CPU_PROFILES;p++){cpu_buttons[p]=NULL;cpu_lit[p]=-1;}
    cpu_running=NULL;cpu_driver_line=NULL;cpu_note=NULL;cpu_wanted=-1;cpu_refused=false;
    playing_name=NULL;achievement_count=NULL;no_drives=NULL;esp_power=NULL;wifi_mark=NULL;
    clock_digits=NULL;clock_date=NULL;timer_value=NULL;timer_minus=NULL;timer_plus=NULL;
    timer_go=NULL;timer_go_label=NULL;timer_reset=NULL;alarm_layer=NULL;
    gpu_load_value=NULL;gpu_load_track=NULL;gpu_load_bar=NULL;
    vram_value=NULL;vram_track=NULL;vram_bar=NULL;gpu_clock_value=NULL;
    boost_field=NULL;boost_track=NULL;boost_knob=NULL;boost_shown=-1;
    history_chart=NULL;history_empty=NULL;history_ago=NULL;
    for(int i=0;i<4;i++)history_axis[i]=NULL;
    for(int i=0;i<HISTORY_WINDOWS;i++)history_buttons[i]=NULL;
    for(int i=0;i<PANEL_HISTORY_SERIES;i++)history_series[i]=NULL;
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
    /* The font of a label that names none, so that no text on this screen
     * falls back to a built-in font without the German letters. */
    lv_obj_set_style_text_font(s,&panel_font_16,0);
    /* The PC and its connection, and the whole of it one place to tap: the
     * page of the PC opens from it. */
    pc_area=head_area(s,0,234,pc_clicked);
    lv_obj_t *monitor=icon(pc_area,&icon_monitor,14,19,MUTED);
    lv_obj_remove_flag(monitor,LV_OBJ_FLAG_CLICKABLE);
    line(pc_area,50,16,1,28);
    connection=text_at(pc_area,panel_text(TXT_PC_OFFLINE),62,22,140,&panel_font_14,TEXT);
    lv_obj_remove_flag(connection,LV_OBJ_FLAG_CLICKABLE);
    dot=panel(pc_area,202,26,9,9,0x60758A,false);lv_obj_set_style_radius(dot,LV_RADIUS_CIRCLE,0);
    lv_obj_remove_flag(dot,LV_OBJ_FLAG_CLICKABLE);
    line(s,234,16,1,28);
    /* The controllers, two side by side over the whole right of the head,
     * with no caption: the icon says what the number is. The value stands
     * at the height of the middle of its icon. A tap anywhere on the two
     * opens the page of the controllers, which has room for four. */
    pad_area=head_area(s,235,245,pads_clicked);
    {
        int32_t high=lv_font_get_line_height(&panel_font_16);
        for(int i=0;i<PAD_HEAD;i++){
            int x=PAD_HEAD_X+i*PAD_HEAD_STEP;
            pad_icons[i]=icon(pad_area,&icon_gamepad_2,x,19,MUTED);
            lv_obj_remove_flag(pad_icons[i],LV_OBJ_FLAG_CLICKABLE);
            pad_values[i]=text_at(pad_area,"-- %",x+32,19+12-high/2,PAD_VALUE_WIDTH,&panel_font_16,TEXT);
            lv_obj_remove_flag(pad_values[i],LV_OBJ_FLAG_CLICKABLE);
        }
        lv_obj_add_flag(pad_icons[1],LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(pad_values[1],LV_OBJ_FLAG_HIDDEN);
    }
    line(s,0,57,480,1);
    /* The middle band, which scrolls sideways. Seven pages of one screen
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
    /* Each page at its place, in the order somebody chose. The pages are
     * built in the order of the firmware and stand where their place is,
     * so the snap and the swipe follow the order and nothing else does. */
    panel_pages_order(local.page_order,page_order);
    page_hidden=panel_pages_hidden(local.page_hidden);
    lv_obj_t *page[PANEL_PAGES];
    for(int i=0;i<PANEL_PAGES;i++){
        page[i]=panel(band,0,0,480,300,BG,false);
        lv_obj_set_style_bg_opa(page[i],LV_OPA_TRANSP,0);
        lv_obj_remove_flag(page[i],LV_OBJ_FLAG_CLICKABLE);
        band_pages[i]=page[i];
    }
    /* Each at its place, and the hidden ones out of the band. The band
     * starts on the start page, the first that is shown. */
    band_arrange(panel_pages_band_page(page_order,page_hidden,0));
    /* No marks under the band for the page on the screen. There were
     * three, and its owner found them of no use and not good to look at.
     * check_pages holds the room between the band and the sensors empty. */
    lv_obj_t *left=panel(page[0],10,0,222,300,CARD,true);
    lv_obj_t *right=panel(page[0],244,0,226,300,CARD,true);
    icon(left,&icon_volume_2,12,26,MUTED);text_at(left,panel_text(TXT_PC_AUDIO),70,19,78,&panel_font_12,MUTED);
    audio_status=text_at(left,"--",70,40,82,&panel_font_18,TEXT);
    audio_toggle=button(left,"",154,24,54,48,clicked,PANEL_MUTE);controls[PANEL_MUTE]=audio_toggle;
    lv_obj_set_style_bg_opa(audio_toggle,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(audio_toggle,0,0);
    lv_obj_t *track=panel(audio_toggle,0,10,52,28,BLUE,false);lv_obj_remove_flag(track,LV_OBJ_FLAG_CLICKABLE);lv_obj_set_style_radius(track,LV_RADIUS_CIRCLE,0);
    audio_knob=panel(track,27,3,22,22,TEXT,false);lv_obj_remove_flag(audio_knob,LV_OBJ_FLAG_CLICKABLE);lv_obj_set_style_radius(audio_knob,LV_RADIUS_CIRCLE,0);
    lv_obj_set_user_data(audio_toggle,track);
    line(left,16,108,190,1);
    center_text(text_at(left,panel_text(TXT_PC_VOLUME),12,131,196,&panel_font_14,MUTED));
    volume=text_at(left,"-- %",12,162,196,&panel_font_32,TEXT);center_text(volume);
    /* Two buttons over the width of the card, and nothing between them.
     * The number was there twice: once in the big label above, and once
     * again in a box between these two, which said the same thing in a
     * smaller font. The room it took is theirs now, and the sign on each
     * one grew with it. */
    controls[PANEL_VOLUME_DOWN]=button(left,LV_SYMBOL_MINUS,12,228,92,56,clicked,PANEL_VOLUME_DOWN);
    controls[PANEL_VOLUME_UP]=button(left,LV_SYMBOL_PLUS,116,228,92,56,clicked,PANEL_VOLUME_UP);
    lv_obj_set_style_text_font(controls[PANEL_VOLUME_DOWN],&panel_font_24,0);
    lv_obj_set_style_text_font(controls[PANEL_VOLUME_UP],&panel_font_24,0);
    icon(right,&icon_monitor,22,19,MUTED);
    text_at(right,panel_text(TXT_PC_CONTROL),60,23,160,&panel_font_14,MUTED);
    line(right,14,64,196,1);
    controls[PANEL_SUSPEND]=power_button(right,panel_text(TXT_SUSPEND),&icon_moon,82,PANEL_SUSPEND);
    controls[PANEL_REBOOT]=power_button(right,panel_text(TXT_REBOOT),&icon_rotate_cw,156,PANEL_REBOOT);
    controls[PANEL_POWEROFF]=power_button(right,panel_text(TXT_POWEROFF),&icon_power,230,PANEL_POWEROFF);
    /* In the place of the first of them, and hidden while the PC answers.
     * Standby, restart and switch off mean nothing to a machine that is
     * already off, so the card shows this instead of three buttons that
     * cannot do anything. */
    wake_button=power_button(right,panel_text(TXT_WAKE),&icon_power,82,PANEL_WAKE);
    wake_what=text_at(right,panel_text(TXT_WAKE_WHAT),16,152,192,&panel_font_12,MUTED);
    lv_label_set_long_mode(wake_what,LV_LABEL_LONG_WRAP);
    lv_obj_add_flag(wake_button,LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(wake_what,LV_OBJ_FLAG_HIDDEN);
    /* The second page: which session runs, and how full each drive is.
     * Two answers about the machine rather than about what is on it, which
     * is why they share a page. */
    lv_obj_t *mode_card=panel(page[1],10,0,460,104,CARD,true);
    icon(mode_card,&icon_monitor,14,18,MUTED);
    text_at(mode_card,panel_text(TXT_MODE),52,14,180,&panel_font_12,MUTED);
    mode_now=text_at(mode_card,"--",52,34,180,&panel_font_24,TEXT);
    mode_button=button(mode_card,"",236,20,208,64,clicked,PANEL_DESKTOP_MODE);
    mode_caption=text_at(mode_button,"",10,22,188,&panel_font_16,TEXT);
    center_text(mode_caption);
    lv_obj_t *disk_card=panel(page[1],10,116,460,184,CARD,true);
    icon(disk_card,&icon_circuit_board,14,14,MUTED);
    text_at(disk_card,panel_text(TXT_DRIVES),52,16,240,&panel_font_14,MUTED);
    line(disk_card,14,44,432,1);
    for(int i=0;i<PANEL_DRIVES;i++)drive_row(disk_card,i,58+i*46);
    no_drives=text_at(disk_card,panel_text(TXT_NO_DRIVES),DRIVE_MARGIN,70,DRIVE_BAR_WIDTH,&panel_font_14,MUTED);
    lv_obj_add_flag(no_drives,LV_OBJ_FLAG_HIDDEN);
    /* The third page: what is on the machine. One card and one name, and
     * the room under it is deliberate: the picture Steam already keeps for
     * every game goes there, and that is a step of its own. */
    lv_obj_t *play_card=panel(page[2],10,0,460,300,CARD,true);
    icon(play_card,&icon_gamepad_2,14,14,MUTED);
    text_at(play_card,panel_text(TXT_PLAYING),52,16,240,&panel_font_14,MUTED);
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
    center_text(text_at(play_card,panel_text(TXT_ACHIEVEMENTS),20,160,420,&panel_font_20,MUTED));
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
    clock_date=text_at(clock_card,panel_text(TXT_CLOCK_UNSET),20,96,420,&panel_font_18,MUTED);
    center_text(clock_date);
    lv_obj_t *timer_card=panel(page[3],10,146,460,154,CARD,true);
    timer_minus=button(timer_card,LV_SYMBOL_MINUS,14,14,84,72,timer_step,-1);
    timer_plus=button(timer_card,LV_SYMBOL_PLUS,362,14,84,72,timer_step,1);
    lv_obj_t *steps[]={timer_minus,timer_plus};
    for(int i=0;i<2;i++){
        lv_obj_set_style_text_font(steps[i],&panel_font_24,0);
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
    /* The fifth page: the card, and the history under it.
     *
     * Three columns over the card: its load and its memory, each with a
     * bar, and its clock. Under them the history of the two temperatures
     * and the power, with the degrees on the left and the watts on the
     * right, and the choice of the window over it. */
    lv_obj_t *gpu_card=panel(page[4],10,0,460,96,CARD,true);
    const panel_text_id_t gpu_names[3]={TXT_GPU_LOAD,TXT_GPU_VRAM,TXT_GPU_CLOCK};
    const int gpu_x[3]={GPU_COLUMN_X0,GPU_COLUMN_X1,GPU_COLUMN_X2};
    const int gpu_room[3]={GPU_COLUMN_X1-GPU_COLUMN_X0-12,GPU_COLUMN_X2-GPU_COLUMN_X1-10,460-8-GPU_COLUMN_X2};
    lv_obj_t *gpu_values[3];
    for(int i=0;i<3;i++){
        text_at(gpu_card,panel_text(gpu_names[i]),gpu_x[i],12,gpu_room[i],&panel_font_14,MUTED);
        gpu_values[i]=text_at(gpu_card,"--",gpu_x[i],34,gpu_room[i],&panel_font_24,TEXT);
        lv_obj_set_height(gpu_values[i],lv_font_get_line_height(&panel_font_24));
    }
    gpu_load_value=gpu_values[0];vram_value=gpu_values[1];gpu_clock_value=gpu_values[2];
    lv_obj_t **tracks[2]={&gpu_load_track,&vram_track},**bars[2]={&gpu_load_bar,&vram_bar};
    for(int i=0;i<2;i++){
        *tracks[i]=panel(gpu_card,gpu_x[i],72,GPU_BAR_WIDTH,8,EDGE,false);
        lv_obj_set_style_radius(*tracks[i],LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(*tracks[i],LV_OBJ_FLAG_CLICKABLE);
        *bars[i]=panel(*tracks[i],0,0,0,8,BLUE,false);
        lv_obj_set_style_radius(*bars[i],LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(*bars[i],LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_flag(*tracks[i],LV_OBJ_FLAG_HIDDEN);
    }
    /* Cooling Boost, under the clock, where the other two columns have
     * their bars: its name and a switch, and the whole row one place to
     * tap. See boost_show. */
    boost_field=lv_obj_create(gpu_card);lv_obj_remove_style_all(boost_field);
    lv_obj_set_pos(boost_field,GPU_COLUMN_X2-6,BOOST_Y);lv_obj_set_size(boost_field,gpu_room[2]+6,BOOST_HEIGHT);
    lv_obj_remove_flag(boost_field,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_radius(boost_field,5,0);
    lv_obj_set_style_bg_color(boost_field,lv_color_hex(0x1B2B3C),LV_STATE_PRESSED);
    lv_obj_set_style_bg_opa(boost_field,LV_OPA_COVER,LV_STATE_PRESSED);
    lv_obj_set_style_opa(boost_field,LV_OPA_40,LV_STATE_DISABLED);
    lv_obj_add_event_cb(boost_field,boost_clicked,LV_EVENT_CLICKED,NULL);
    lv_obj_t *boost_name=text_at(boost_field,panel_text(TXT_GPU_BOOST),6,
                                 (BOOST_HEIGHT-lv_font_get_line_height(&panel_font_12))/2,
                                 gpu_room[2]-BOOST_TRACK_WIDTH-4,&panel_font_12,MUTED);
    lv_obj_set_height(boost_name,lv_font_get_line_height(&panel_font_12));
    lv_obj_remove_flag(boost_name,LV_OBJ_FLAG_CLICKABLE);
    boost_track=panel(boost_field,gpu_room[2]+6-BOOST_TRACK_WIDTH,(BOOST_HEIGHT-BOOST_TRACK_HEIGHT)/2,
                      BOOST_TRACK_WIDTH,BOOST_TRACK_HEIGHT,EDGE,false);
    lv_obj_set_style_radius(boost_track,LV_RADIUS_CIRCLE,0);
    lv_obj_remove_flag(boost_track,LV_OBJ_FLAG_CLICKABLE);
    boost_knob=panel(boost_track,BOOST_KNOB_OFF,2,BOOST_TRACK_HEIGHT-4,BOOST_TRACK_HEIGHT-4,TEXT,false);
    lv_obj_set_style_radius(boost_knob,LV_RADIUS_CIRCLE,0);
    lv_obj_remove_flag(boost_knob,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(boost_field,LV_OBJ_FLAG_HIDDEN);
    lv_obj_t *history_card=panel(page[4],10,106,460,194,CARD,true);
    text_at(history_card,panel_text(TXT_HISTORY),16,14,120,&panel_font_14,MUTED);
    for(int i=0;i<HISTORY_WINDOWS;i++){
        char caption[16];
        snprintf(caption,sizeof caption,"%d %s",history_windows[i],panel_text(TXT_MINUTES));
        history_buttons[i]=button(history_card,caption,252+i*66,8,62,32,history_window_clicked,history_windows[i]);
        lv_obj_set_style_text_font(history_buttons[i],&panel_font_14,0);
    }
    /* The legend, one dot and one name for each curve. */
    const char *legend[PANEL_HISTORY_SERIES]={"CPU °C","GPU °C","GPU W"};
    for(int i=0;i<PANEL_HISTORY_SERIES;i++){
        lv_obj_t *mark=panel(history_card,16+i*92,49,10,10,curve_colors[i],false);
        lv_obj_set_style_radius(mark,LV_RADIUS_CIRCLE,0);
        lv_obj_remove_flag(mark,LV_OBJ_FLAG_CLICKABLE);
        text_at(history_card,legend[i],32+i*92,45,72,&panel_font_12,MUTED);
    }
    history_chart=lv_chart_create(history_card);
    lv_obj_set_pos(history_chart,CHART_X,CHART_Y);lv_obj_set_size(history_chart,CHART_WIDTH,CHART_HEIGHT);
    /* Not a place to press: a swipe over it moves the band. */
    lv_obj_remove_flag(history_chart,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(history_chart,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_opa(history_chart,LV_OPA_TRANSP,0);
    lv_obj_set_style_border_width(history_chart,0,0);
    lv_obj_set_style_radius(history_chart,0,0);
    lv_obj_set_style_pad_hor(history_chart,0,0);
    lv_obj_set_style_pad_ver(history_chart,2,0);
    lv_obj_set_style_line_color(history_chart,lv_color_hex(EDGE),LV_PART_MAIN);
    lv_obj_set_style_line_width(history_chart,1,LV_PART_MAIN);
    lv_obj_set_style_line_width(history_chart,2,LV_PART_ITEMS);
    lv_obj_set_style_width(history_chart,0,LV_PART_INDICATOR);
    lv_obj_set_style_height(history_chart,0,LV_PART_INDICATOR);
    lv_chart_set_type(history_chart,LV_CHART_TYPE_LINE);
    lv_chart_set_div_line_count(history_chart,3,0);
    lv_chart_set_point_count(history_chart,PANEL_HISTORY_DRAWN);
    for(int i=0;i<PANEL_HISTORY_SERIES;i++){
        history_series[i]=lv_chart_add_series(history_chart,lv_color_hex(curve_colors[i]),
            i==PANEL_HISTORY_WATTS?LV_CHART_AXIS_SECONDARY_Y:LV_CHART_AXIS_PRIMARY_Y);
        /* The points of the history in place, in PSRAM. Without a history
         * the chart keeps its own, which are empty. */
        if(history)lv_chart_set_series_ext_y_array(history_chart,history_series[i],history->drawn[i]);
    }
    /* The ends of the two scales, beside the chart. */
    for(int i=0;i<4;i++){
        bool right=i>=2,low=i%2;
        history_axis[i]=text_at(history_card,"",right?CHART_X+CHART_WIDTH+6:0,
                                low?CHART_Y+CHART_HEIGHT-16:CHART_Y-2,right?44:CHART_X-6,&panel_font_12,MUTED);
        lv_obj_set_style_text_align(history_axis[i],right?LV_TEXT_ALIGN_LEFT:LV_TEXT_ALIGN_RIGHT,0);
    }
    history_ago=text_at(history_card,"",CHART_X,CHART_Y+CHART_HEIGHT+6,120,&panel_font_12,MUTED);
    lv_obj_t *now=text_at(history_card,panel_text(TXT_HISTORY_NOW),CHART_X+CHART_WIDTH-120,
                          CHART_Y+CHART_HEIGHT+6,120,&panel_font_12,MUTED);
    lv_obj_set_style_text_align(now,LV_TEXT_ALIGN_RIGHT,0);
    history_empty=text_at(history_card,panel_text(TXT_HISTORY_EMPTY),CHART_X,CHART_Y+CHART_HEIGHT/2-10,
                          CHART_WIDTH,&panel_font_16,MUTED);
    center_text(history_empty);
    history_stale=true;
    history_show();
    /* The sixth page: the effect of the LED bar of the PC, a card for the
     * desktop and one for Game Mode. See led_show. */
    led_card(page[PANEL_PAGE_LED],PANEL_LED_DESKTOP,0);
    led_card(page[PANEL_PAGE_LED],PANEL_LED_GAME,LED_DESKTOP_HIGH+8);
    /* The seventh page: the energy profile of the CPU of the PC. See
     * cpu_show. */
    cpu_page(page[PANEL_PAGE_CPU]);
    /* The temperatures and the power of the card, in one card across the
     * screen: three fields of the same width, the processor, the card and
     * its power, with a short line between each two. Two tiles stood
     * here, the processor and the card with its power, and its owner found
     * the gap between them not of a piece with the rest.
     *
     * A tap on the processor opens the choice of its temperature sensor,
     * and a tap on the card or its power the choice of the card's. Each of
     * the two is a field of its own that lights up while it is pressed. */
    lv_obj_t *foot=panel(s,10,386,460,48,CARD,true);
    lv_obj_remove_flag(foot,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_t *cpu_tile=sensor_field(foot,0,SENSOR_FIELD-1,cpu_tile_clicked);
    lv_obj_t *gpu_tile=sensor_field(foot,SENSOR_FIELD,2*SENSOR_FIELD-1,gpu_tile_clicked);
    cpu_value=sensor_reading(cpu_tile,0,&icon_cpu,"CPU","00 °C","-- °C");
    line(foot,SENSOR_FIELD-1,9,1,30);
    gpu_value=sensor_reading(gpu_tile,0,&icon_circuit_board,"GPU","00 °C","-- °C");
    line(gpu_tile,SENSOR_FIELD-1,9,1,30);
    power_value=sensor_reading(gpu_tile,SENSOR_FIELD,&icon_zap,"GPU-WATT","000 W","-- W");
    /* The bottom row: the settings on the left, what the panel has to
     * say in the middle, and the state of the panel itself on the right.
     *
     * The settings sit where a left thumb finds them. The caption goes to
     * the left edge of its button and not the middle, so it lines up with
     * the edge of the card above it. */
    lv_obj_t *settings_button=button(s,panel_text(TXT_SETTINGS),0,436,150,44,settings_clicked,0);
    lv_obj_set_style_bg_opa(settings_button,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(settings_button,0,0);
    lv_obj_set_style_text_font(settings_button,&panel_font_14,0);
    lv_obj_align(lv_obj_get_child(settings_button,0),LV_ALIGN_LEFT_MID,12,0);
    /* Empty unless there is something to say. See the poll in main.c:
     * the state of the connection is the mark on the right now, and what
     * reaches this line is what a mark cannot say. */
    message=text_at(s,"",150,451,180,&panel_font_12,MUTED);
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
    /* A tap on the network and the battery of the panel opens the page of
     * the panel itself. */
    lv_obj_set_style_bg_color(status,lv_color_hex(EDGE),LV_STATE_PRESSED);
    lv_obj_set_style_bg_opa(status,LV_OPA_40,LV_STATE_PRESSED);
    lv_obj_set_style_radius(status,6,0);
    lv_obj_add_event_cb(status,self_clicked,LV_EVENT_CLICKED,NULL);
    lv_obj_set_flex_flow(status,LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(status,LV_FLEX_ALIGN_END,LV_FLEX_ALIGN_CENTER,LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(status,10,0);
    wifi_mark=lv_label_create(status);
    lv_label_set_text(wifi_mark,LV_SYMBOL_WIFI);
    lv_obj_set_style_text_font(wifi_mark,&panel_font_14,0);
    /* Red until the network is joined, which is the one state of it that
     * asks for a look. */
    lv_obj_set_style_text_color(wifi_mark,lv_color_hex(RED),0);
    /* The battery of this panel, and not of the controller: that one has
     * its place at the top. Hidden until the power chip answers. */
    esp_power=lv_label_create(status);
    lv_label_set_text(esp_power,"");
    lv_obj_set_style_text_font(esp_power,&panel_font_14,0);
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
    /* Before the test for a new state: the history moves on without one,
     * and a PC that is gone sends none. */
    history_show();
    /* Repeated label_set_text_fmt calls allocate and invalidate even unchanged
     * values. Status is polled at 3 s; idle 200 ms UI ticks need no redraw.
     * A padding-only difference can merely cause an extra update, never hide one. */
    if(last_state_valid && memcmp(&last_state,s,sizeof(*s))==0)return;
    memcpy(&last_state,s,sizeof(*s));last_state_valid=true;
    if(sound_status)lv_label_set_text(sound_status,s->sound_error?panel_text(TXT_NO_AUDIO):panel_text(TXT_SPEAKER));
    if(s->setup){
        settings_forget();pads_forget();pc_forget();sensor_close();look_close();self_forget();
        if(!setup_screen){
            if(overlay){lv_obj_delete(overlay);overlay=NULL;}
            setup_screen=panel(lv_screen_active(),0,0,480,480,BG,false);
            text_at(setup_screen,panel_text(TXT_SETUP_TITLE),24,28,432,&panel_font_24,BLUE);
            setup_text=text_at(setup_screen,"",24,96,432,&panel_font_18,TEXT);lv_label_set_long_mode(setup_text,LV_LABEL_LONG_WRAP);
            text_at(setup_screen,panel_text(TXT_SETUP_STOP),24,428,432,&panel_font_16,MUTED);
        }
        lv_label_set_text_fmt(setup_text,panel_text(TXT_SETUP_STEPS),s->setup_ssid,s->setup_password);return;
    }
    lv_label_set_text(connection,!s->wifi?panel_text(TXT_WIFI_OFFLINE):s->online?panel_text(TXT_PC_ONLINE):panel_text(TXT_PC_OFFLINE));
    lv_obj_set_style_bg_color(dot,lv_color_hex(s->online?0x70C256:0x60758A),0);
    pads_head(s);
    pads_show(s);
    led_show(s);
    cpu_show(s);
    pc_show(s);
    self_show(s);
    update_layer_show(s);
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
    temperatures_show(s);
    if(s->online&&s->gpu_watts>=0)lv_label_set_text_fmt(power_value,"%d W",s->gpu_watts);else lv_label_set_text(power_value,"-- W");
    card_show(s);
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
