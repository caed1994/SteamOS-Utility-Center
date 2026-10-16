// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The middle band, which scrolls, and the two pages that came with it.
//
// Nothing here draws: it builds the screens on a host LVGL and reads the
// words off them. What it holds is the part a person sees, which is the
// part a rule in Python cannot reach.
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
#include "icons.h"
#include "panel_fonts.h"
#include "panel_frames.h"
#include "panel_taps.h"
static unsigned actions;
static panel_action_t last_action;
static void action(panel_action_t a){actions++;last_action=a;}
// The last setting the screen saved, for the choice of a sensor.
static panel_setting_t saved_key;
static int saved_value,saved_count;
static void setting(panel_setting_t k,int v,bool save){if(save){saved_key=k;saved_value=v;saved_count++;}}
static void sound(int volume){(void)volume;}
// The changes of the page of the LED bar, as main.c gets them.
static lv_obj_t *slider_at_place(lv_obj_t *root,int *skip);
static unsigned led_changes;
static char led_last[PANEL_LED_MODES][PANEL_LED_KEY];
static char led_last_colour[PANEL_LED_COLOUR];
static int led_last_brightness=-1;
static char led_last_profile[PANEL_LED_MODES][PANEL_LED_KEY];
static void led_change(const panel_led_change_t *change)
{
    led_changes++;
    for(int m=0;m<PANEL_LED_MODES;m++)snprintf(led_last[m],PANEL_LED_KEY,"%s",change->effect[m]);
    snprintf(led_last_colour,sizeof led_last_colour,"%s",change->colour);
    led_last_brightness=change->brightness;
    for(int m=0;m<PANEL_LED_MODES;m++)snprintf(led_last_profile[m],PANEL_LED_KEY,"%s",change->profile[m]);
}
// The profiles of the page of the CPU, as main.c gets them.
static unsigned cpu_changes;
static int cpu_last=-1;
static void cpu_change(int profile){cpu_changes++;cpu_last=profile;}
// The wait of the page after the last tap, and the timers of LVGL that
// it holds back.
static void led_wait(uint32_t ms){lv_tick_inc(ms);lv_timer_handler();}
// The history of the page of the card, as main.c keeps one.
static panel_history_t history;
// A label somebody can see. The hidden ones are still in the tree, and a
// search that walks into them answers "there it is" about a card that is
// not on the screen. Every rule below reads this, so every one of them is
// about what is drawn.
static lv_obj_t *label(lv_obj_t *root,const char *text)
{
    if(lv_obj_has_flag(root,LV_OBJ_FLAG_HIDDEN))return NULL;
    if(lv_obj_check_type(root,&lv_label_class)&&strcmp(lv_label_get_text(root),text)==0)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){lv_obj_t *f=label(lv_obj_get_child(root,i),text);if(f)return f;}
    return NULL;
}
static void click_in(lv_obj_t *root,const char *text)
{
    lv_obj_t *l=label(root,text);assert(l);
    lv_obj_t *b=lv_obj_get_parent(l);
    while(b&&!lv_obj_check_type(b,&lv_button_class))b=lv_obj_get_parent(b);
    assert(b);
    lv_obj_send_event(b,LV_EVENT_CLICKED,NULL);
}
static void click(const char *text){click_in(lv_screen_active(),text);}
// The box of the menu of the profiles of the mirror, or NULL with no menu.
static lv_obj_t *profile_box(void)
{
    lv_obj_t *title=label(lv_screen_active(),panel_text(TXT_PROFILE_TITLE));
    return title?lv_obj_get_parent(title):NULL;
}
// Where the one sign in "holder" starts that stands from "start" on and
// ends before "words": the sign of a third of the card of the sensors.
static int32_t sign_before(lv_obj_t *holder,int32_t start,int32_t words)
{
    int32_t found=LV_COORD_MAX;
    for(unsigned i=0;i<lv_obj_get_child_count(holder);i++){
        lv_obj_t *o=lv_obj_get_child(holder,i);
        if(!lv_obj_check_type(o,&lv_image_class))continue;
        lv_area_t at;
        lv_obj_get_coords(o,&at);
        if(at.x1<start||at.x2>=words)continue;
        assert(found==LV_COORD_MAX);
        found=at.x1;
    }
    assert(found!=LV_COORD_MAX);
    return found;
}
// The band is the one object on the screen that scrolls sideways.
static lv_obj_t *find_band(lv_obj_t *root)
{
    if(lv_obj_get_scroll_dir(root)==LV_DIR_HOR&&lv_obj_get_child_count(root)==PANEL_PAGES)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){lv_obj_t *f=find_band(lv_obj_get_child(root,i));if(f)return f;}
    return NULL;
}
// A name in a row of the screen of the order: whole on its line, and left
// of the buttons of its row.
static bool name_fits(lv_obj_t *name)
{
    lv_point_t size;
    lv_text_get_size(&size,lv_label_get_text(name),lv_obj_get_style_text_font(name,0),0,0,
                     LV_COORD_MAX,LV_TEXT_FLAG_NONE);
    if(size.x>lv_obj_get_width(name))return false;
    lv_obj_t *row=lv_obj_get_parent(name);
    for(unsigned i=0;i<lv_obj_get_child_count(row);i++){
        lv_obj_t *c=lv_obj_get_child(row,i);
        if(lv_obj_check_type(c,&lv_button_class)&&lv_obj_get_x(name)+size.x>lv_obj_get_x(c))return false;
    }
    return true;
}
// The button in a row whose caption is that text, or NULL.
static lv_obj_t *button_with(lv_obj_t *row,const char *caption)
{
    for(unsigned i=0;i<lv_obj_get_child_count(row);i++){
        lv_obj_t *c=lv_obj_get_child(row,i);
        if(lv_obj_check_type(c,&lv_button_class)&&label(c,caption))return c;
    }
    return NULL;
}
// The image under root that shows that picture, or NULL.
static lv_obj_t *image_of(lv_obj_t *root,const lv_image_dsc_t *picture)
{
    if(lv_obj_check_type(root,&lv_image_class)&&lv_image_get_src(root)==picture)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){
        lv_obj_t *found=image_of(lv_obj_get_child(root,i),picture);
        if(found)return found;
    }
    return NULL;
}
static int32_t middle_of(lv_obj_t *o)
{
    lv_area_t at;
    lv_obj_get_coords(o,&at);
    return (at.x1+at.x2)/2;
}
// Whether the knob of a switch stands in the right half of its track: on.
static bool knob_right(lv_obj_t *knob)
{
    return lv_obj_get_x(knob)+lv_obj_get_width(knob)/2>lv_obj_get_width(lv_obj_get_parent(knob))/2;
}
// The button of one profile on the page of the CPU.
static lv_obj_t *cpu_button(lv_obj_t *page,int profile)
{
    lv_obj_t *caption=label(page,panel_text(panel_cpu_name(profile)));
    assert(caption);
    return lv_obj_get_parent(caption);
}
// Whether a button of the page of the CPU is lit: the colour of its
// background against the colour of the buttons that are not.
static bool cpu_lit_one(lv_obj_t *button,lv_color_t dark)
{
    return !lv_color_eq(lv_obj_get_style_bg_color(button,0),dark);
}
// The layer of the colour and the brightness, or NULL when it is closed:
// the one object on the screen with the name of a colour on it.
static lv_obj_t *look_layer_of(void)
{
    lv_obj_t *found=label(lv_screen_active(),panel_text(TXT_LED_DONE));
    if(!found)return NULL;
    lv_obj_t *layer=found;
    while(lv_obj_get_parent(layer)!=lv_screen_active())layer=lv_obj_get_parent(layer);
    return layer;
}
// The button of a colour in that layer, and whether it is the chosen one:
// the chosen colour has a blue outline.
static lv_obj_t *swatch(lv_obj_t *layer,int colour)
{
    lv_obj_t *name=label(layer,panel_text(panel_led_colour_name(colour)));
    return name?lv_obj_get_parent(name):NULL;
}
static bool swatch_chosen(lv_obj_t *layer,int colour)
{
    return lv_obj_get_style_outline_width(swatch(layer,colour),0)>0;
}
// The words of the button of the colour and the brightness, for a colour
// and a per cent, or for the brightness alone. Two answers in turn have
// rooms of their own, so one rule can compare two of them; a rule that
// keeps one for longer copies it.
static const char *look_words_for(panel_text_id_t colour,int percent,bool coloured)
{
    static char said[2][48];
    static unsigned turn;
    char *out=said[turn++%2];
    if(coloured)snprintf(out,sizeof said[0],"%s • %d %%",panel_text(colour),percent);
    else snprintf(out,sizeof said[0],"%s %d %%",panel_text(TXT_LED_BRIGHTNESS),percent);
    return out;
}
// The dot of the colour in the button of the colour and the brightness:
// the one child that is no label.
static lv_obj_t *look_dot_of(lv_obj_t *look)
{
    for(unsigned i=0;i<lv_obj_get_child_count(look);i++)
        if(!lv_obj_check_type(lv_obj_get_child(look,i),&lv_label_class))return lv_obj_get_child(look,i);
    return NULL;
}
// A move of the slider of the layer to a per cent, and the finger off it.
static void look_slide(lv_obj_t *layer,int percent)
{
    int skip=0;
    lv_obj_t *slider=slider_at_place(layer,&skip);
    assert(slider);
    lv_slider_set_value(slider,percent,LV_ANIM_OFF);
    lv_obj_send_event(slider,LV_EVENT_VALUE_CHANGED,NULL);
    lv_obj_send_event(slider,LV_EVENT_RELEASED,NULL);
}
// One press as the touch reader and LVGL give it to the count of the
// touches, a read every 15 ms: down at the start, the finger "moved" px
// along, up, and the read after it. late adds that much to one of the
// gaps.
static uint32_t taps_now=1000;
static void taps_press(int moved,int strength,bool target,bool swipe,bool click,uint32_t late)
{
    panel_taps_press_t done;
    panel_taps_read(&panel_taps,taps_now,true,true,100,100,strength,&done);
    panel_taps_pressed(&panel_taps,target);
    taps_now+=15+late;
    panel_taps_read(&panel_taps,taps_now,true,true,100+moved,100,strength+2,&done);
    taps_now+=15;
    panel_taps_read(&panel_taps,taps_now,true,false,0,0,-1,&done);
    panel_taps_released(&panel_taps,swipe);
    if(click)panel_taps_clicked(&panel_taps);
    taps_now+=15;
    panel_taps_read(&panel_taps,taps_now,true,false,0,0,-1,&done);
}
// The value in the row of a card of the page of the panel that has this
// name: the label at the height of the name and right of it.
static const char *row_value(lv_obj_t *card,panel_text_id_t name)
{
    lv_obj_update_layout(card);
    lv_obj_t *named=label(card,panel_text(name));
    assert(named);
    for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
        lv_obj_t *c=lv_obj_get_child(card,i);
        if(c!=named&&lv_obj_check_type(c,&lv_label_class)&&lv_obj_get_y(c)==lv_obj_get_y(named)
           &&lv_obj_get_x(c)>lv_obj_get_x(named))
            return lv_label_get_text(c);
    }
    return NULL;
}
// The card of the page of the LED bar for one mode, and its arrows.
static lv_obj_t *led_card_of(lv_obj_t *page,panel_led_mode_t mode)
{
    return lv_obj_get_parent(label(page,panel_text(mode==PANEL_LED_GAME?TXT_LED_GAME:TXT_LED_DESKTOP)));
}
static void led_tap(lv_obj_t *page,panel_led_mode_t mode,const char *arrow)
{
    lv_obj_t *arrow_button=button_with(led_card_of(page,mode),arrow);
    assert(arrow_button);
    lv_obj_send_event(arrow_button,LV_EVENT_CLICKED,NULL);
}
// The end of a frame, which this display takes and does nothing with. The
// pixels stay in the buffer that main hands LVGL, so a rule can read them.
static void flushed(lv_display_t *d,const lv_area_t *a,uint8_t *p)
{(void)a;(void)p;lv_display_flush_ready(d);}
// Everything LVGL complained about while this check ran.
//
// LVGL answers something it cannot draw by writing a line and drawing
// nothing, and the screen then just looks empty. The lines are counted and
// the check fails on one.
static unsigned complaints;
static void complained(lv_log_level_t level,const char *text)
{
    if(level>=LV_LOG_LEVEL_WARN&&level!=LV_LOG_LEVEL_USER)complaints++;
    fputs(text,stderr);
}
// The slider after skip others, in the order they were built.
static lv_obj_t *slider_at_place(lv_obj_t *root,int *skip)
{
    if(lv_obj_check_type(root,&lv_slider_class)){
        if(*skip==0)return root;
        (*skip)--;
    }
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){
        lv_obj_t *f=slider_at_place(lv_obj_get_child(root,i),skip);
        if(f)return f;
    }
    return NULL;
}
// A line of one pixel across a card, which is how ui.c draws a divider.
static lv_obj_t *thin_line(lv_obj_t *card)
{
    for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
        lv_obj_t *c=lv_obj_get_child(card,i);
        if(lv_obj_get_height(c)==1&&lv_obj_get_width(c)>100)return c;
    }
    return NULL;
}
// The label under the title of the count, in the same card.
static lv_obj_t *count_under(lv_obj_t *card,lv_obj_t *title)
{
    for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
        lv_obj_t *c=lv_obj_get_child(card,i);
        if(c!=title&&lv_obj_check_type(c,&lv_label_class)
           &&lv_obj_get_y(c)>lv_obj_get_y(title))return c;
    }
    return NULL;
}
// The last line of one pixel in the card that stands above a height.
static lv_obj_t *line_below(lv_obj_t *card,int32_t above)
{
    lv_obj_t *found=NULL;
    for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
        lv_obj_t *c=lv_obj_get_child(card,i);
        if(lv_obj_get_height(c)==1&&lv_obj_get_y(c)<above)found=c;
    }
    return found;
}
// The label of the name: the one that stands between the two lines.
static lv_obj_t *name_above(lv_obj_t *card,lv_obj_t *between)
{
    for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
        lv_obj_t *c=lv_obj_get_child(card,i);
        if(lv_obj_check_type(c,&lv_label_class)&&lv_obj_get_y(c)>44
           &&lv_obj_get_y(c)<lv_obj_get_y(between))return c;
    }
    return NULL;
}
// Four frames of a scroll at 16 MHz, after the frame that starts it. The
// numbers the card of the frames shows for them, worked out by hand:
//   rate      4 frames in 182.3 ms, 22 a second
//   interval  33.15, 49.7, 33.15 and 66.3 ms: mean 45, 95 % 66, most 66
//   draw      29, 31, 30 and 45 ms: mean 33, 95 % 45, most 45
//   lead      2, 3, 2 and 9 ms: mean 4, 95 % 9, most 9
//   periods   two, three, two and four of 16.575 ms: 0, 50, 25 and 25 %
static void count_some_frames(void)
{
    static const int64_t frames[][3]={{2000,29000,33150},{3000,31000,49725},
                                       {2000,30000,33150},{9000,45000,66300}};
    panel_frames_reset(&panel_frames);
    panel_frames_period(&panel_frames,16575);
    int64_t shown=1000000;
    panel_frames_begin(&panel_frames,shown-20000);
    panel_frames_drawn(&panel_frames,shown-10000);
    panel_frames_shown(&panel_frames,shown);
    for(unsigned i=0;i<sizeof frames/sizeof *frames;i++){
        panel_frames_begin(&panel_frames,shown+frames[i][0]);
        panel_frames_drawn(&panel_frames,shown+frames[i][0]+frames[i][1]);
        shown+=frames[i][2];
        panel_frames_shown(&panel_frames,shown);
    }
    assert(panel_frames.counted==4);
}
static panel_state_t base(void)
{
    panel_state_t s={.online=true,.wifi=true,.volume=30,
                     .cpu_temp=40,.gpu_temp=45,.gpu_watts=60};
    return s;
}
// A colour of LVGL as panel_theme.h writes one, 0xRRGGBB.
static uint32_t rgb_of(lv_color_t colour)
{
    return (uint32_t)colour.red<<16|(uint32_t)colour.green<<8|colour.blue;
}
// The contrast of two colours as WCAG 2 counts it: 1 for one colour on
// itself, 21 for black on white.
static double channel(unsigned value)
{
    double c=value/255.0;
    return c<=0.04045?c/12.92:pow((c+0.055)/1.055,2.4);
}
static double luminance(uint32_t rgb)
{
    return 0.2126*channel(rgb>>16&255)+0.7152*channel(rgb>>8&255)+0.0722*channel(rgb&255);
}
static double contrast(uint32_t a,uint32_t b)
{
    double x=luminance(a)+0.05,y=luminance(b)+0.05;
    return x>y?x/y:y/x;
}
// The labels under root that do not read, each printed, as a count.
//
// A label against what it is drawn on: the first thing under it that
// covers. 4.5 for words, as WCAG 2 asks, and 3 for the large ones of 24 px
// and up. A label in a greyed button is left out, which is meant to read as
// out of use, and so is a hidden one.
static unsigned unreadable(lv_obj_t *root,const char *where)
{
    if(lv_obj_has_flag(root,LV_OBJ_FLAG_HIDDEN))return 0;
    if(lv_obj_get_style_opa(root,LV_PART_MAIN)<LV_OPA_COVER)return 0;
    unsigned bad=0;
    if(lv_obj_check_type(root,&lv_label_class)&&lv_label_get_text(root)[0]){
        lv_obj_t *under=lv_obj_get_parent(root);
        while(under&&lv_obj_get_style_bg_opa(under,LV_PART_MAIN)<LV_OPA_90)under=lv_obj_get_parent(under);
        assert(under);
        uint32_t words=rgb_of(lv_obj_get_style_text_color_filtered(root,LV_PART_MAIN));
        uint32_t ground=rgb_of(lv_obj_get_style_bg_color(under,LV_PART_MAIN));
        const lv_font_t *font=lv_obj_get_style_text_font(root,LV_PART_MAIN);
        double least=lv_font_get_line_height(font)>=lv_font_get_line_height(&panel_font_24)?3.0:4.5;
        double seen=contrast(words,ground);
        if(seen<least){
            bad++;
            printf("%s: \"%s\" in #%06X on #%06X reads %.2f, and %.1f is the least\n",where,
                   lv_label_get_text(root),(unsigned)words,(unsigned)ground,seen,least);
        }
    }
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++)bad+=unreadable(lv_obj_get_child(root,i),where);
    return bad;
}
// Whether a text is whole in one line of that font and that width.
static bool fits(const char *text,const lv_font_t *font,int32_t width)
{
    lv_point_t size;
    lv_text_get_size(&size,text,font,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
    return size.x<=width;
}
// The card of the theme and the accent on the open settings, and the round
// button of one accent in it: the buttons as wide as they are high, in the
// order of the accents.
static lv_obj_t *appearance_card(void)
{
    lv_obj_t *title=label(lv_screen_active(),panel_text(TXT_APPEARANCE));
    assert(title);
    return lv_obj_get_parent(title);
}
static lv_obj_t *accent_button(lv_obj_t *card,int accent)
{
    lv_obj_update_layout(card);
    for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
        lv_obj_t *c=lv_obj_get_child(card,i);
        if(!lv_obj_check_type(c,&lv_button_class)||lv_obj_get_width(c)!=lv_obj_get_height(c))continue;
        if(accent--==0)return c;
    }
    return NULL;
}
// The settings page, which holds that card.
static lv_obj_t *settings_page(void)
{
    lv_obj_t *card=appearance_card();
    return lv_obj_get_parent(card);
}
int main(void)
{
    lv_init();
    lv_log_register_print_cb(complained);
    static uint8_t pixels[480*480*2];
    lv_display_t *screen=lv_display_create(480,480);
    lv_display_set_color_format(screen,LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(screen,pixels,NULL,sizeof pixels,
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(screen,flushed);
    panel_settings_t settings={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
    panel_history_reset(&history);
    panel_ui_history_use(&history);
    panel_ui_create(action,setting,sound,&settings);

    // The pages, and the band snaps so there is no place between two.
    lv_obj_t *band=find_band(lv_screen_active());
    assert(band);
    assert(lv_obj_get_child_count(band)==PANEL_PAGES);
    assert(lv_obj_has_flag(band,LV_OBJ_FLAG_SCROLL_ONE));
    // A band that takes a press swallows the one meant for a button on it.
    assert(!lv_obj_has_flag(band,LV_OBJ_FLAG_CLICKABLE));
    // Nothing between the band and the row of sensors under it. Three
    // marks for the page stood there, and its owner had them taken out.
    {
        lv_obj_update_layout(lv_screen_active());
        lv_obj_t *screen=lv_screen_active();
        int32_t band_end=lv_obj_get_y(band)+lv_obj_get_height(band);
        // The row of sensors: the first object under the band that is as
        // wide as most of the screen.
        int32_t foot=LV_COORD_MAX;
        for(unsigned i=0;i<lv_obj_get_child_count(screen);i++){
            lv_obj_t *c=lv_obj_get_child(screen,i);
            if(lv_obj_get_y(c)>=band_end&&lv_obj_get_width(c)>=240
               &&lv_obj_get_y(c)<foot)foot=lv_obj_get_y(c);
        }
        assert(foot!=LV_COORD_MAX&&foot>band_end);
        for(unsigned i=0;i<lv_obj_get_child_count(screen);i++){
            lv_obj_t *c=lv_obj_get_child(screen,i);
            if(lv_obj_has_flag(c,LV_OBJ_FLAG_HIDDEN))continue;
            int32_t top=lv_obj_get_y(c),end=top+lv_obj_get_height(c);
            assert(top>=foot||end<=band_end);
        }
    }

    // Nothing playing is the ordinary case, and it says so.
    panel_state_t s=base();
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_NOTHING_PLAYING)));

    // A game that runs is named.
    snprintf(s.playing,sizeof(s.playing),"Portal 2");
    panel_ui_update(&s);
    assert(label(lv_screen_active(),"Portal 2"));
    assert(!label(lv_screen_active(),panel_text(TXT_NOTHING_PLAYING)));

    // The session, and the button that carries where it goes rather than
    // "the other one".
    s.game_mode=true;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_MODE_GAME)));
    assert(label(lv_screen_active(),panel_text(TXT_TO_DESKTOP)));
    actions=0;
    click(panel_text(TXT_TO_DESKTOP));
    // It asks first, the way standby and switch off do: a session that
    // goes takes what is open with it.
    assert(actions==0);
    assert(label(lv_screen_active(),panel_text(TXT_CONFIRM_MODE)));
    // The question and the two buttons, and nothing under it. The line
    // that stands under the power questions says where the press lands,
    // which a session question answers in its own words.
    assert(!label(lv_screen_active(),panel_text(TXT_CONFIRM_HERE)));
    assert(label(lv_screen_active(),panel_text(TXT_CANCEL)));
    click(panel_text(TXT_CONFIRM));
    assert(actions==1 && last_action==PANEL_DESKTOP_MODE);

    // And the other way around.
    s.game_mode=false;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_MODE_DESKTOP)));
    assert(label(lv_screen_active(),panel_text(TXT_TO_GAME)));
    actions=0;
    click(panel_text(TXT_TO_GAME));
    click(panel_text(TXT_CONFIRM));
    assert(actions==1 && last_action==PANEL_GAME_MODE);

    // The power questions keep theirs, so the rule above is about the
    // session and not about the line being gone everywhere.
    click(panel_text(TXT_POWEROFF));
    assert(label(lv_screen_active(),panel_text(TXT_CONFIRM_HERE)));
    click(panel_text(TXT_CANCEL));

    // The drives. Two of them, and the bar fills with what is used.
    s.drive_count=2;
    snprintf(s.drives[0].name,sizeof(s.drives[0].name),"SSD");
    s.drives[0].total=1000ULL*1024*1024*1024;
    s.drives[0].free=250ULL*1024*1024*1024;
    snprintf(s.drives[1].name,sizeof(s.drives[1].name),"SDCARD");
    s.drives[1].total=64ULL*1024*1024*1024;
    s.drives[1].free=8ULL*1024*1024*1024;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),"SSD"));
    assert(label(lv_screen_active(),"SDCARD"));
    // Below a hundred it carries one decimal, above it none. "916.3" is
    // one character of meaning and three of noise.
    char wanted[64];
    snprintf(wanted,sizeof(wanted),"250 GB %s / 1000 GB",panel_text(TXT_FREE));
    assert(label(lv_screen_active(),wanted));
    snprintf(wanted,sizeof(wanted),"8.0 GB %s / 64.0 GB",panel_text(TXT_FREE));
    assert(label(lv_screen_active(),wanted));
    assert(!label(lv_screen_active(),panel_text(TXT_NO_DRIVES)));

    // A bar stands the same distance from both borders of its card.
    // Reported from the board: the first version put the row at nought,
    // so it touched the left border and stood 24 off the right one. This
    // measures the drawn object rather than reading the source, because
    // the fault was in what the numbers add up to and not in any one.
    lv_obj_update_layout(lv_screen_active());
    lv_obj_t *named=label(lv_screen_active(),"SSD");
    assert(named);
    lv_obj_t *row=lv_obj_get_parent(named);
    lv_obj_t *card=lv_obj_get_parent(row);
    int32_t on_the_left=lv_obj_get_x(row);
    int32_t on_the_right=lv_obj_get_width(card)-on_the_left-lv_obj_get_width(row);
    assert(on_the_left>0);
    assert(on_the_left==on_the_right);

    // A machine that answers with no drive says so rather than showing
    // an empty bar, which reads as room.
    s.drive_count=0;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_NO_DRIVES)));

    // More drives than there is room for take the room there is.
    s.drive_count=PANEL_DRIVES+2;
    for(int i=0;i<PANEL_DRIVES;i++){
        snprintf(s.drives[i].name,sizeof(s.drives[i].name),"D%d",i);
        s.drives[i].total=100ULL*1024*1024*1024;s.drives[i].free=1;
    }
    panel_ui_update(&s);
    for(int i=0;i<PANEL_DRIVES;i++){
        char name[8];snprintf(name,sizeof(name),"D%d",i);
        assert(label(lv_screen_active(),name));
    }

    // Offline leaves the second page at a dash and the third at its word,
    // rather than at the last thing the PC said, which reads as current.
    s.online=false;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),"--"));
    assert(label(lv_screen_active(),panel_text(TXT_NOTHING_PLAYING)));
    assert(label(lv_screen_active(),panel_text(TXT_NO_DRIVES)));

    // The language button rebuilds every screen, and a pointer kept past
    // that clean is a pointer to freed memory that a touch reaches.
    s.online=true;s.game_mode=true;
    panel_ui_update(&s);
    panel_settings_t german={.brightness=70,.sound_volume=30,.language=PANEL_GERMAN};
    panel_ui_create(action,setting,sound,&german);
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_MODE_GAME)));
    assert(label(lv_screen_active(),"Portal 2"));

    // And every page really draws.
    //
    // This check once made a display with no buffers and no flush
    // callback, so it never drew a pixel and every rule in it was about a
    // tree of objects rather than about a screen. LVGL answers something
    // it cannot draw by writing a line and drawing nothing, and complained
    // counts those.
    //
    // The band goes to each page in turn, because a page that is off the
    // side of the screen is a page nothing draws.
    lv_obj_t *band_now=find_band(lv_screen_active());
    assert(band_now);
    assert(lv_obj_get_child_count(band_now)==PANEL_PAGES);
    for(unsigned page=0;page<PANEL_PAGES;page++){
        lv_obj_scroll_to_view(lv_obj_get_child(band_now,page),LV_ANIM_OFF);
        lv_obj_update_layout(lv_screen_active());
        lv_refr_now(screen);
    }
    assert(complaints==0);

    // The battery of this panel, in the corner the setup stood in.
    //
    // Nothing until the power chip answers: a battery drawn on a board
    // whose chip said nothing is a battery that may not be there.
    s=base();
    panel_ui_update(&s);
    assert(!label(lv_screen_active(),LV_SYMBOL_USB));
    assert(!label(lv_screen_active(),panel_text(TXT_SETUP)));
    // A chip with no cell behind it is a panel on its cable, and a plug
    // with no number says so.
    s.esp_supply=PANEL_SUPPLY_CABLE;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),LV_SYMBOL_USB));
    // A cell: its level as a shape, then the number.
    s.esp_supply=PANEL_SUPPLY_BATTERY;s.esp_battery=87;
    panel_ui_update(&s);
    assert(!label(lv_screen_active(),LV_SYMBOL_USB));
    assert(label(lv_screen_active(),LV_SYMBOL_BATTERY_3 " 87 %"));
    s.esp_charging=true;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),LV_SYMBOL_CHARGE " " LV_SYMBOL_BATTERY_3 " 87 %"));
    s.esp_charging=false;s.esp_battery=100;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),LV_SYMBOL_BATTERY_FULL " 100 %"));
    s.esp_battery=5;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),LV_SYMBOL_BATTERY_EMPTY " 5 %"));
    // Read off the panel and not off the PC, so it stays when the PC goes.
    // A panel on its battery with the PC off is exactly when somebody
    // looks.
    s.online=false;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),LV_SYMBOL_BATTERY_EMPTY " 5 %"));
    // And the chip going silent takes it away again rather than leaving
    // the last reading up as if it were current.
    s.esp_supply=PANEL_SUPPLY_UNKNOWN;
    panel_ui_update(&s);
    assert(!label(lv_screen_active(),LV_SYMBOL_BATTERY_EMPTY " 5 %"));

    // The bottom row: the settings on the left, and on the right the mark
    // for the network standing directly against the battery.
    s=base();
    s.esp_supply=PANEL_SUPPLY_BATTERY;s.esp_battery=87;
    panel_ui_update(&s);
    lv_obj_update_layout(lv_screen_active());
    {
        lv_obj_t *settings_caption=label(lv_screen_active(),panel_text(TXT_SETTINGS));
        assert(settings_caption);
        lv_area_t where;lv_obj_get_coords(settings_caption,&where);
        assert(where.x1<60);                     // on the left, not the middle
        lv_obj_t *net=label(lv_screen_active(),LV_SYMBOL_WIFI);
        lv_obj_t *cell=label(lv_screen_active(),LV_SYMBOL_BATTERY_3 " 87 %");
        assert(net && cell);
        lv_area_t a,b;lv_obj_get_coords(net,&a);lv_obj_get_coords(cell,&b);
        // Directly left of it, on the same row, with a small gap and no
        // other mark between.
        assert(a.x2<b.x1);
        assert(b.x1-a.x2<=16);
        assert(a.y1<b.y2 && b.y1<a.y2);
        // And the pair at the right edge, where the setup button stood.
        assert(b.x2>=440);
        // A board whose power chip said nothing has no battery to stand
        // against, and the mark goes to the edge instead of floating.
        s.esp_supply=PANEL_SUPPLY_UNKNOWN;
        panel_ui_update(&s);
        lv_obj_update_layout(lv_screen_active());
        lv_obj_get_coords(net,&a);
        assert(a.x2>=440);
    }
    // The mark says whether the panel is on the network, in a colour that
    // asks for a look when it is not.
    {
        s=base();s.wifi=true;
        panel_ui_update(&s);
        lv_obj_t *net=label(lv_screen_active(),LV_SYMBOL_WIFI);
        assert(net);
        lv_color_t on=lv_obj_get_style_text_color(net,0);
        s.wifi=false;s.online=false;
        panel_ui_update(&s);
        lv_color_t off=lv_obj_get_style_text_color(net,0);
        assert(!lv_color_eq(on,off));
        assert(off.red>off.green && off.red>off.blue);
    }
    // The line in the middle stays empty in the ordinary case: the state
    // of the connection is the mark now. It comes up for what a mark cannot
    // say, and goes again when that is over.
    {
        s=base();
        panel_ui_update(&s);
        assert(!label(lv_screen_active(),panel_text(TXT_CHECK_SETUP)));
        snprintf(s.message,sizeof s.message,"%s",panel_text(TXT_CHECK_SETUP));
        panel_ui_update(&s);
        assert(label(lv_screen_active(),panel_text(TXT_CHECK_SETUP)));
        s.message[0]=0;
        panel_ui_update(&s);
        assert(!label(lv_screen_active(),panel_text(TXT_CHECK_SETUP)));
    }

    // How many achievements of the game that runs are unlocked, under its
    // name on the third page.
    {
        s=base();
        snprintf(s.playing,sizeof s.playing,"DragonSword : Awakening");
        s.achievements_done=49;s.achievements_total=60;
        panel_ui_update(&s);
        lv_obj_t *title=label(lv_screen_active(),panel_text(TXT_ACHIEVEMENTS));
        assert(title);
        assert(label(lv_screen_active(),"49 / 60"));
        lv_obj_t *card=lv_obj_get_parent(title);
        lv_obj_t *count=count_under(card,title);
        assert(count);
        // Nought of sixty is a real answer about a game.
        s.achievements_done=0;
        panel_ui_update(&s);
        assert(strcmp(lv_label_get_text(count),"0 / 60")==0);
        // And a dash for everything with nothing to count: a game with no
        // achievements, no game at all, and a PC that does not answer.
        s.achievements_total=0;
        panel_ui_update(&s);
        assert(strcmp(lv_label_get_text(count),"--")==0);
        s.achievements_done=49;s.achievements_total=60;s.playing[0]=0;
        panel_ui_update(&s);
        assert(strcmp(lv_label_get_text(count),"--")==0);
        snprintf(s.playing,sizeof s.playing,"DragonSword : Awakening");
        s.online=false;
        panel_ui_update(&s);
        assert(strcmp(lv_label_get_text(count),"--")==0);

        // The name stops short of the line between it and the count, however
        // long it is: two lines at most.
        s=base();
        // W is the widest letter there is, so fifty of them run past two
        // lines of this card and still fit the 64 bytes a name has here.
        snprintf(s.playing,sizeof s.playing,
                 "WWWWWWWWWW WWWWWWWWWW WWWWWWWWWW WWWWWWWWWW WWWWWWWWWW");
        panel_ui_update(&s);
        lv_obj_update_layout(lv_screen_active());
        lv_obj_t *between=line_below(card,lv_obj_get_y(title)-1);
        assert(between);
        lv_obj_t *name=name_above(card,between);
        assert(name);
        assert(lv_obj_get_y(name)+lv_obj_get_height(name)<=lv_obj_get_y(between));
        assert(lv_obj_get_y(title)>lv_obj_get_y(between));
        lv_obj_t *over=line_below(card,lv_obj_get_y(name));
        assert(over&&over!=between);
        int32_t room_middle=(lv_obj_get_y(over)+1+lv_obj_get_y(between))/2;
        int32_t two_lines=lv_obj_get_height(name);
        assert(LV_ABS(lv_obj_get_y(name)+two_lines/2-room_middle)<=1);

        // A name of one line stands in the middle of that room too, and not
        // at the top of a box made for two. Across, each text of the card
        // is centred on the card.
        snprintf(s.playing,sizeof s.playing,"DragonSword : Awakening");
        panel_ui_update(&s);
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_height(name)<two_lines);
        assert(LV_ABS(lv_obj_get_y(name)+lv_obj_get_height(name)/2-room_middle)<=1);
        int32_t card_middle=lv_obj_get_width(card)/2;
        lv_obj_t *texts[]={name,title,count};
        for(unsigned i=0;i<3;i++){
            assert(lv_obj_get_style_text_align(texts[i],LV_PART_MAIN)==LV_TEXT_ALIGN_CENTER);
            assert(LV_ABS(lv_obj_get_x(texts[i])+lv_obj_get_width(texts[i])/2-card_middle)<=1);
        }

        // The count is the large thing on the card: its digits are at least
        // twice as tall as the name's, and the pair of title and count
        // stands in the middle of the room under the line, inside the card.
        const lv_font_t *digits=lv_obj_get_style_text_font(count,LV_PART_MAIN);
        const lv_font_t *words=lv_obj_get_style_text_font(name,LV_PART_MAIN);
        assert(lv_font_get_line_height(digits)>=2*lv_font_get_line_height(words));
        assert(lv_obj_get_height(count)>=lv_font_get_line_height(digits));
        int32_t pair_top=lv_obj_get_y(title);
        int32_t pair_end=lv_obj_get_y(count)+lv_obj_get_height(count);
        assert(pair_end<=lv_obj_get_height(card));
        int32_t below_middle=(lv_obj_get_y(between)+1+lv_obj_get_height(card))/2;
        assert(LV_ABS((pair_top+pair_end)/2-below_middle)<=2);
    }

    // The two sliders of the display card, and the room under each.
    //
    // The board showed the second one pressed against the bottom edge of
    // the card. The first has the line between the rows under it, the
    // second has the edge; the gap to each has to be the same, measured
    // from the top of the track.
    panel_ui_settings_open();
    lv_obj_update_layout(lv_screen_active());
    {
        int skip=0;
        lv_obj_t *first=slider_at_place(lv_screen_active(),&skip);
        skip=1;
        lv_obj_t *second=slider_at_place(lv_screen_active(),&skip);
        assert(first && second);
        lv_obj_t *card=lv_obj_get_parent(first);
        assert(card==lv_obj_get_parent(second));
        lv_obj_t *between=thin_line(card);
        assert(between);
        int32_t first_room=lv_obj_get_y(between)-lv_obj_get_y(first);
        assert(first_room>0);
        // Under the second slider is the line over the row of the lift
        // now, at the same gap.
        lv_obj_t *under=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
            lv_obj_t *c=lv_obj_get_child(card,i);
            if(lv_obj_get_height(c)==1&&lv_obj_get_width(c)>100&&lv_obj_get_y(c)>lv_obj_get_y(second))under=c;
        }
        assert(under);
        assert(lv_obj_get_y(under)-lv_obj_get_y(second)==first_room);
        // The row of the lift: its name, what it does, and its switch,
        // all inside the card.
        lv_obj_t *lift_name=label(card,panel_text(TXT_LIFT_WAKE));
        lv_obj_t *lift_what=label(card,panel_text(TXT_LIFT_WAKE_WHAT));
        assert(lift_name&&lift_what&&lv_obj_get_y(lift_name)>lv_obj_get_y(under));
        assert(lv_obj_get_y(lift_what)+lv_obj_get_height(lift_what)<lv_obj_get_height(card));
        lv_obj_t *lift_switch=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(card);i++)
            if(lv_obj_check_type(lv_obj_get_child(card,i),&lv_switch_class))lift_switch=lv_obj_get_child(card,i);
        assert(lift_switch&&lv_obj_get_y(lift_switch)>lv_obj_get_y(under));
        // What it does fits one line beside nothing: the switch stands
        // above its end.
        lv_point_t what_size;
        lv_text_get_size(&what_size,panel_text(TXT_LIFT_WAKE_WHAT),&panel_font_12,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
        assert(what_size.x<=lv_obj_get_width(lift_what));
        assert(lv_obj_get_x(lift_what)+lv_obj_get_width(lift_what)<=lv_obj_get_x(lift_switch));
        // The cards under it keep their gap: the colours of the screen,
        // and the sound under those.
        lv_obj_t *look_card=lv_obj_get_parent(label(lv_screen_active(),panel_text(TXT_APPEARANCE)));
        assert(lv_obj_get_y(look_card)==lv_obj_get_y(card)+lv_obj_get_height(card)+14);
        lv_obj_t *sound_card=lv_obj_get_parent(label(lv_screen_active(),panel_text(TXT_TONES)));
        assert(lv_obj_get_y(sound_card)==lv_obj_get_y(look_card)+lv_obj_get_height(look_card)+14);
        // The switch shows the setting the screen was built with: off here,
        // and on for a panel that has it on.
        assert(!lv_obj_has_state(lift_switch,LV_STATE_CHECKED));
        panel_settings_t lifting={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH,.lift_wake=true};
        panel_ui_create(action,setting,sound,&lifting);
        panel_ui_settings_open();
        lv_obj_t *display_card=lv_obj_get_parent(label(lv_screen_active(),panel_text(TXT_LIFT_WAKE)));
        lift_switch=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(display_card);i++)
            if(lv_obj_check_type(lv_obj_get_child(display_card,i),&lv_switch_class))
                lift_switch=lv_obj_get_child(display_card,i);
        assert(lift_switch&&lv_obj_has_state(lift_switch,LV_STATE_CHECKED));
        // The setup stands in the settings now, and still asks first: a
        // cancel sends nothing.
        unsigned before=actions;
        click(panel_text(TXT_SETUP));
        assert(label(lv_screen_active(),panel_text(TXT_CONFIRM_SETUP)));
        click(panel_text(TXT_CANCEL));
        assert(actions==before);
    }

    // The fourth page: the clock, and the timer under it.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        s=base();
        panel_ui_update(&s);
        lv_obj_t *band4=find_band(lv_screen_active());
        assert(band4);
        lv_obj_t *page4=lv_obj_get_child(band4,3);
        lv_obj_scroll_to_view(page4,LV_ANIM_OFF);
        lv_obj_update_layout(lv_screen_active());
        assert(strcmp(panel_ui_where(),"the clock")==0);
        // Not set by the network yet: dashes and a word, and no date
        // made up out of nought.
        assert(label(page4,"--:--"));
        assert(label(page4,panel_text(TXT_CLOCK_UNSET)));
        s.clock_set=true;s.hour=7;s.minute=5;s.weekday=3;s.day=1;s.month=10;
        panel_ui_update(&s);
        assert(label(page4,"07:05"));
        assert(label(page4,"Wednesday, 1 October"));
        // A month or a day out of its range is a clock that is not set,
        // and not a read past the end of the table of names.
        s.month=13;
        panel_ui_update(&s);
        assert(label(page4,"--:--"));
        s.month=10;s.weekday=7;
        panel_ui_update(&s);
        assert(label(page4,"--:--"));
        s.weekday=3;

        // The timer: a tap is a minute, a held press is five at once and
        // five more every 400 ms, and the release of a held press adds
        // nothing.
        lv_obj_t *plus=lv_obj_get_parent(label(page4,LV_SYMBOL_PLUS));
        lv_obj_t *minus=lv_obj_get_parent(label(page4,LV_SYMBOL_MINUS));
        assert(lv_obj_check_type(plus,&lv_button_class));
        assert(lv_obj_check_type(minus,&lv_button_class));
        assert(label(page4,"00:00"));
        assert(lv_obj_has_state(minus,LV_STATE_DISABLED));
        lv_obj_send_event(plus,LV_EVENT_SHORT_CLICKED,NULL);
        lv_obj_send_event(plus,LV_EVENT_CLICKED,NULL);
        assert(label(page4,"01:00"));
        lv_obj_send_event(plus,LV_EVENT_LONG_PRESSED,NULL);
        assert(label(page4,"06:00"));
        for(int i=0;i<3;i++){lv_tick_inc(100);lv_obj_send_event(plus,LV_EVENT_LONG_PRESSED_REPEAT,NULL);}
        assert(label(page4,"06:00"));
        lv_tick_inc(100);lv_obj_send_event(plus,LV_EVENT_LONG_PRESSED_REPEAT,NULL);
        assert(label(page4,"11:00"));
        lv_obj_send_event(plus,LV_EVENT_CLICKED,NULL);
        assert(label(page4,"11:00"));
        lv_obj_send_event(minus,LV_EVENT_SHORT_CLICKED,NULL);
        assert(label(page4,"10:00"));

        // Start: + and - wait, and the start is a pause now.
        click(panel_text(TXT_START));
        assert(label(page4,panel_text(TXT_PAUSE)));
        assert(lv_obj_has_state(plus,LV_STATE_DISABLED));
        assert(lv_obj_has_state(minus,LV_STATE_DISABLED));
        lv_tick_inc(61*1000);
        panel_ui_timer_tick();
        assert(label(page4,"08:59"));
        click(panel_text(TXT_PAUSE));
        assert(label(page4,panel_text(TXT_START)));
        assert(!lv_obj_has_state(plus,LV_STATE_DISABLED));
        click(panel_text(TXT_RESET));
        assert(label(page4,"10:00"));

        // To the end: it rings over the whole screen, a tap anywhere on it
        // stops it, and the timer is set up again as it was started.
        assert(!panel_ui_timer_stop());
        click(panel_text(TXT_START));
        lv_tick_inc(10*60*1000);
        panel_timer_news_t news=panel_ui_timer_tick();
        assert(news.went_off&&news.beep&&!news.gave_up);
        assert(panel_ui_timer_ringing());
        lv_obj_t *up=label(lv_screen_active(),panel_text(TXT_TIME_UP));
        assert(up);
        lv_obj_t *layer=lv_obj_get_parent(lv_obj_get_parent(up));
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_width(layer)==480&&lv_obj_get_height(layer)==480);
        assert(lv_obj_get_parent(layer)==lv_screen_active());
        assert(lv_obj_get_index(layer)==(int32_t)lv_obj_get_child_count(lv_screen_active())-1);
        // A new screen for a new language keeps the timer, and the alarm
        // on it.
        panel_settings_t german={.brightness=70,.sound_volume=30,.language=PANEL_GERMAN};
        panel_ui_create(action,setting,sound,&german);
        panel_ui_update(&s);
        up=label(lv_screen_active(),panel_text(TXT_TIME_UP));
        assert(up);
        layer=lv_obj_get_parent(lv_obj_get_parent(up));
        lv_obj_send_event(layer,LV_EVENT_CLICKED,NULL);
        assert(!panel_ui_timer_ringing());
        assert(!label(lv_screen_active(),panel_text(TXT_TIME_UP)));
        band4=find_band(lv_screen_active());
        page4=lv_obj_get_child(band4,3);
        assert(label(page4,"10:00"));
        assert(label(page4,"Mittwoch, 1. Oktober"));

        // The alarm stays audible with the sound turned right down, and
        // follows the volume above that.
        panel_settings_t quiet={.brightness=70,.sound_volume=5,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&quiet);
        assert(panel_ui_alarm_volume()==40);
        panel_settings_t loud={.brightness=70,.sound_volume=80,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&loud);
        assert(panel_ui_alarm_volume()==80);

        // Nobody stops it: a minute of ringing, and it gives up.
        click(panel_text(TXT_START));
        lv_tick_inc(10*60*1000);
        news=panel_ui_timer_tick();
        assert(news.went_off);
        lv_tick_inc(60*1000);
        news=panel_ui_timer_tick();
        assert(news.gave_up&&!panel_ui_timer_ringing());
        assert(!label(lv_screen_active(),panel_text(TXT_TIME_UP)));
        lv_refr_now(screen);
        assert(complaints==0);
    }

    // The alarm clock. A button in the corner of the clock card opens the
    // layer that sets it. The wheels and the days change what the layer
    // shows, and the close sets it and stores it. It rings over the whole
    // screen, a tap anywhere on it snoozes it, and Off ends it.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_alarm_clock_t wednesday={.known=true,.day=1,.weekday=3,.hour=18,.minute=42};
        panel_alarm_news_t news=panel_ui_alarm_clock_tick(&wednesday);
        assert(!news.went_off&&!panel_ui_alarm_clock_ringing());
        char next[24];
        panel_ui_alarm_clock_next(next,sizeof next);
        assert(next[0]==0);
        lv_obj_t *card=lv_obj_get_child(lv_obj_get_child(find_band(lv_screen_active()),3),0);
        lv_obj_t *button=lv_obj_get_child(card,2);
        assert(lv_obj_check_type(button,&lv_button_class));
        lv_obj_t *bell=lv_obj_get_child(button,0);
        lv_color_t off_colour=lv_obj_get_style_image_recolor(bell,0);
        lv_obj_send_event(button,LV_EVENT_CLICKED,NULL);
        lv_obj_t *title=label(lv_screen_active(),panel_text(TXT_ALARM_TITLE));
        assert(title);
        lv_obj_t *layer=lv_obj_get_parent(lv_obj_get_parent(title));
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_width(layer)==480&&lv_obj_get_height(layer)==480);
        assert(lv_obj_get_index(layer)==(int32_t)lv_obj_get_child_count(lv_screen_active())-1);
        assert(strcmp(panel_ui_where(),"the alarm clock")==0);
        // The two wheels: the hours, then the minutes. A turn switches the
        // alarm on in the layer, and the line under the days says when it
        // rings. Nothing is stored before the close.
        lv_obj_t *box=lv_obj_get_parent(title),*wheels[2]={NULL,NULL};
        for(unsigned i=0,n=0;i<lv_obj_get_child_count(box)&&n<2;i++)
            if(lv_obj_check_type(lv_obj_get_child(box,i),&lv_roller_class))wheels[n++]=lv_obj_get_child(box,i);
        assert(wheels[0]&&wheels[1]);
        assert(lv_roller_get_selected(wheels[0])==7&&lv_roller_get_selected(wheels[1])==0);
        unsigned before=saved_count;
        lv_roller_set_selected(wheels[0],6,LV_ANIM_OFF);lv_obj_send_event(wheels[0],LV_EVENT_VALUE_CHANGED,NULL);
        lv_roller_set_selected(wheels[1],30,LV_ANIM_OFF);lv_obj_send_event(wheels[1],LV_EVENT_VALUE_CHANGED,NULL);
        assert(label(layer,"Rings Th 06:30"));
        click(panel_text(TXT_MONDAY_SHORT));
        assert(label(layer,"Rings Mo 06:30"));
        assert(saved_count==before);
        click(panel_text(TXT_ALARM_DONE));
        assert(!label(lv_screen_active(),panel_text(TXT_ALARM_TITLE)));
        assert(saved_count==before+1&&saved_key==PANEL_ALARM);
        assert((uint32_t)saved_value==panel_alarm_pack((panel_alarm_set_t){.on=true,.hour=6,.minute=30,.days=1}));
        assert(!lv_color_eq(lv_obj_get_style_image_recolor(bell,0),off_colour));
        panel_ui_alarm_clock_next(next,sizeof next);
        assert(strcmp(next,"Mo 06:30")==0);
        // Monday at 6:30: it rings, over everything, and a new screen for a
        // new language keeps the ring.
        panel_alarm_clock_t monday={.known=true,.day=6,.weekday=1,.hour=6,.minute=30};
        news=panel_ui_alarm_clock_tick(&monday);
        assert(news.went_off&&news.beep&&panel_ui_alarm_clock_ringing());
        assert(label(lv_screen_active(),panel_text(TXT_SNOOZE)));
        panel_settings_t german={.brightness=70,.sound_volume=30,.language=PANEL_GERMAN};
        panel_ui_create(action,setting,sound,&german);
        lv_obj_t *snooze=label(lv_screen_active(),panel_text(TXT_SNOOZE));
        assert(snooze&&label(lv_screen_active(),"06:30"));
        // A tap beside the buttons snoozes it, and main.c hears of it one
        // time.
        layer=lv_obj_get_parent(lv_obj_get_parent(lv_obj_get_parent(snooze)));
        assert(lv_obj_get_parent(layer)==lv_screen_active());
        lv_obj_send_event(layer,LV_EVENT_CLICKED,NULL);
        assert(!panel_ui_alarm_clock_ringing()&&!label(lv_screen_active(),panel_text(TXT_SNOOZE)));
        assert(panel_ui_alarm_clock_take_snooze()&&!panel_ui_alarm_clock_take_snooze());
        panel_ui_alarm_clock_next(next,sizeof next);
        assert(strcmp(next,"Mo 06:35")==0);
        // The layer during a snooze says so, and ends it on request. The
        // alarm of each Monday stays.
        card=lv_obj_get_child(lv_obj_get_child(find_band(lv_screen_active()),3),0);
        lv_obj_send_event(lv_obj_get_child(card,2),LV_EVENT_CLICKED,NULL);
        assert(label(lv_screen_active(),"Schlummert bis Mo 06:35"));
        click(panel_text(TXT_SNOOZE_END));
        assert(!label(lv_screen_active(),panel_text(TXT_ALARM_TITLE)));
        panel_ui_alarm_clock_next(next,sizeof next);
        assert(strcmp(next,"Mo 06:30")==0);
        // The next Monday: Off ends it, and a key would have snoozed it.
        monday.day=13;
        news=panel_ui_alarm_clock_tick(&monday);
        assert(news.went_off);
        click(panel_text(TXT_ALARM_OFF));
        assert(!panel_ui_alarm_clock_ringing()&&!panel_ui_alarm_clock_snooze());
        assert(!panel_ui_alarm_clock_take_snooze());
        // The home key closes the layer, and sets what it shows.
        before=saved_count;
        lv_obj_send_event(lv_obj_get_child(card,2),LV_EVENT_CLICKED,NULL);
        title=label(lv_screen_active(),panel_text(TXT_ALARM_TITLE));
        assert(title);
        box=lv_obj_get_parent(title);
        for(unsigned i=0;i<lv_obj_get_child_count(box);i++)
            if(lv_obj_check_type(lv_obj_get_child(box,i),&lv_roller_class)){
                lv_roller_set_selected(lv_obj_get_child(box,i),7,LV_ANIM_OFF);
                lv_obj_send_event(lv_obj_get_child(box,i),LV_EVENT_VALUE_CHANGED,NULL);
                break;
            }
        assert(panel_ui_home());
        assert(!label(lv_screen_active(),panel_text(TXT_ALARM_TITLE)));
        assert(saved_count==before+1&&saved_key==PANEL_ALARM);
        assert((uint32_t)saved_value==panel_alarm_pack((panel_alarm_set_t){.on=true,.hour=7,.minute=30,.days=1}));
        lv_refr_now(screen);
        assert(complaints==0);
    }

    // The controllers: two in the head with no caption, and a page of four
    // that a tap on the head opens.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        static const panel_pad_t four[]={{"Steam Controller 1",93,false},
                                          {"PlayStation Controller",100,true},
                                          {"Steam Controller 2",8,false},
                                          {"Xbox Controller",-1,false}};
        const char *charged="100 % " LV_SYMBOL_CHARGE;
        panel_state_t c=base();
        memcpy(c.pads,four,sizeof four);
        c.pad_count=1;
        panel_ui_update(&c);
        lv_obj_t *screen_now=lv_screen_active();
        assert(!label(screen_now,"CONTROLLER")&&!label(screen_now,panel_text(TXT_CONTROLLERS)));
        // One controller: one value, at the height of the middle of its
        // icon, and no second place.
        lv_obj_t *first=label(screen_now,"93 %");
        assert(first);
        assert(!label(screen_now,"-- %"));
        lv_obj_t *head=lv_obj_get_parent(first);
        lv_obj_update_layout(screen_now);
        lv_obj_t *mark=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(head);i++){
            lv_obj_t *o=lv_obj_get_child(head,i);
            if(lv_obj_check_type(o,&lv_image_class)){mark=o;break;}
        }
        assert(mark);
        lv_area_t icon_box,value_box;
        lv_obj_get_coords(mark,&icon_box);
        int32_t font_high=lv_font_get_line_height(&panel_font_16);
        lv_obj_get_coords(first,&value_box);
        int32_t icon_middle=(icon_box.y1+icon_box.y2+1)/2;
        int32_t value_middle=value_box.y1+font_high/2;
        assert(value_middle-icon_middle<=1&&icon_middle-value_middle<=1);
        // Two: side by side, both in the head, right of the line at 234,
        // and the longest value fits its room.
        c.pad_count=2;
        panel_ui_update(&c);
        lv_obj_t *second=label(screen_now,charged);
        assert(label(screen_now,"93 %")&&second);
        lv_obj_update_layout(screen_now);
        lv_area_t one,two;
        lv_obj_get_coords(label(screen_now,"93 %"),&one);
        lv_obj_get_coords(second,&two);
        assert(one.x1>234&&two.x1>one.x2&&two.x2<480);
        assert(one.y1==two.y1);
        lv_point_t room;
        lv_text_get_size(&room,charged,&panel_font_16,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
        assert(room.x<=lv_obj_get_width(second));
        // Four: the head still shows two, and the page all four.
        c.pad_count=4;
        panel_ui_update(&c);
        assert(!label(screen_now,"8 %")&&!label(screen_now,"Steam Controller 1"));
        // None, and a PC that does not answer: "--" in the first place.
        c.pad_count=0;
        panel_ui_update(&c);
        assert(label(screen_now,"-- %")&&!label(screen_now,"93 %"));
        c.pad_count=4;c.online=false;
        panel_ui_update(&c);
        assert(label(screen_now,"-- %")&&!label(screen_now,"93 %"));
        c.online=true;
        panel_ui_update(&c);
        // A tap anywhere on the head opens the page.
        lv_obj_send_event(head,LV_EVENT_CLICKED,NULL);
        assert(label(screen_now,panel_text(TXT_CONTROLLERS)));
        assert(strcmp(panel_ui_where(),"the controllers")==0);
        for(int i=0;i<4;i++)assert(label(screen_now,four[i].name));
        assert(label(screen_now,"8 %")&&label(screen_now,charged));
        assert(label(screen_now,"-- %")&&label(screen_now,panel_text(TXT_NO_BATTERY)));
        assert(!label(screen_now,panel_text(TXT_NO_PADS)));
        lv_refr_now(screen);
        assert(complaints==0);
        // The bar of a battery is as long as its charge, and a controller
        // with no battery has words and no bar.
        lv_obj_t *card=lv_obj_get_parent(label(screen_now,"Steam Controller 1"));
        lv_obj_t *track=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
            lv_obj_t *o=lv_obj_get_child(card,i);
            if(lv_obj_get_child_count(o)==1&&!lv_obj_check_type(o,&lv_label_class))track=o;
        }
        assert(track);
        lv_obj_t *bar=lv_obj_get_child(track,0);
        assert(lv_obj_get_width(bar)==lv_obj_get_width(track)*93/100);
        lv_obj_t *xbox=lv_obj_get_parent(label(screen_now,"Xbox Controller"));
        assert(label(xbox,panel_text(TXT_NO_BATTERY)));
        for(unsigned i=0;i<lv_obj_get_child_count(xbox);i++){
            lv_obj_t *o=lv_obj_get_child(xbox,i);
            if(lv_obj_get_child_count(o)==1&&!lv_obj_check_type(o,&lv_label_class))
                assert(lv_obj_has_flag(o,LV_OBJ_FLAG_HIDDEN));
        }
        // A name too long for its line loses "Wireless" and "Controller",
        // and never down to one word. Each name is one line.
        static const panel_pad_t long_names[]={{"8BitDo Ultimate 2C Wireless Controller",-1,false},
                                               {"Steam Controller",93,false},
                                               {"Supercalifragilistic Controller",50,false}};
        panel_state_t named=c;
        memcpy(named.pads,long_names,sizeof long_names);named.pad_count=3;
        panel_ui_update(&named);
        assert(label(screen_now,"8BitDo Ultimate 2C"));
        assert(label(screen_now,"Steam Controller"));
        // That one fits alone and not with its second word, and it keeps both.
        assert(!label(screen_now,"Supercalifragilistic"));
        lv_obj_t *long_one=lv_obj_get_parent(label(screen_now,"8BitDo Ultimate 2C"));
        lv_obj_t *third=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(lv_obj_get_parent(long_one));i++){
            lv_obj_t *card_i=lv_obj_get_child(lv_obj_get_parent(long_one),i);
            for(unsigned j=0;j<lv_obj_get_child_count(card_i);j++){
                lv_obj_t *o=lv_obj_get_child(card_i,j);
                if(lv_obj_check_type(o,&lv_label_class)&&strncmp(lv_label_get_text(o),"Supercali",9)==0)third=o;
            }
        }
        assert(third&&lv_obj_get_height(third)==lv_font_get_line_height(&panel_font_18));
        // LVGL writes the dots once the label has its size.
        lv_obj_update_layout(screen_now);
        assert(strstr(lv_label_get_text(third),"...")&&strncmp(lv_label_get_text(third),"Supercalifragilistic C",22)==0);
        lv_obj_t *steam_name=label(screen_now,"Steam Controller");
        assert(lv_obj_get_height(steam_name)==lv_font_get_line_height(&panel_font_18));
        panel_ui_update(&c);
        // The page follows the state while it is open.
        c.pad_count=1;
        panel_ui_update(&c);
        assert(label(screen_now,"Steam Controller 1")&&!label(screen_now,"Steam Controller 2"));
        c.pad_count=0;
        panel_ui_update(&c);
        assert(label(screen_now,panel_text(TXT_NO_PADS)));
        c.pad_count=4;c.online=false;
        panel_ui_update(&c);
        assert(label(screen_now,panel_text(TXT_PC_OFFLINE)));
        assert(!label(lv_obj_get_child(screen_now,-1),"Steam Controller 1"));
        c.online=true;
        panel_ui_update(&c);
        // Back closes it, and the head is there again.
        click(panel_text(TXT_BACK));
        assert(!label(screen_now,panel_text(TXT_CONTROLLERS)));
        assert(label(screen_now,"93 %"));
        // A new screen for a new language while the page is open drops it,
        // and the page opens again after that.
        panel_ui_pads_open();
        panel_settings_t german={.brightness=70,.sound_volume=30,.language=PANEL_GERMAN};
        panel_ui_create(action,setting,sound,&german);
        assert(!label(lv_screen_active(),panel_text(TXT_CONTROLLERS)));
        panel_ui_update(&c);
        panel_ui_pads_open();
        assert(label(lv_screen_active(),"Controller"));
        assert(label(lv_screen_active(),"Kein Akkustand"));
        // The setup takes the page away, as it does the settings.
        c.setup=true;
        panel_ui_update(&c);
        assert(!label(lv_screen_active(),"Kein Akkustand"));
        c.setup=false;
        panel_ui_create(action,setting,sound,&english);
        lv_refr_now(screen);
        assert(complaints==0);
    }

    // The page of the PC: the left of the head opens it, and it scrolls
    // up and down through the system, the hardware and the network.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_state_t c=base();
        strcpy(c.host,"FractalMachine");
        panel_pc_t pc={.os="SteamOS 3.9.2",.build="20260925.100",.channel="Beta",
            .kernel="7.2.7-valve1-1-neptune-72-gc8730d37f9c6",.cpu="AMD Ryzen 7 9800X3D",
            .gpu="Radeon RX 9070/9070 XT/9070 GRE",.ip="192.168.178.42",.mac="a8:a1:59:3c:21:7e",
            .uptime_s=2*86400+4*3600+13*60,.cpu_load=12,.fan_rpm=1180,.gpu_fan_rpm=0,
            .memory_used=10ULL<<30,.memory_total=32ULL<<30,.link=PANEL_LINK_WIRED,
            .link_mbit=1000,.answer_ms=38};
        c.pc=pc;
        panel_ui_update(&c);
        lv_obj_t *screen_now=lv_screen_active();
        lv_obj_t *left=lv_obj_get_parent(label(screen_now,panel_text(TXT_PC_ONLINE)));
        assert(left&&left!=screen_now);
        lv_obj_send_event(left,LV_EVENT_CLICKED,NULL);
        assert(label(screen_now,panel_text(TXT_PC_DETAILS)));
        assert(strcmp(panel_ui_where(),"the PC")==0);
        // The other page does not open over this one.
        panel_ui_pads_open();
        assert(strcmp(panel_ui_where(),"the PC")==0);
        lv_obj_t *page=lv_obj_get_child(screen_now,-1);
        static const char *const shown[]={"FractalMachine","SteamOS 3.9.2","20260925.100",
            "Beta","2 d 4 h 13 min","AMD Ryzen 7 9800X3D","12 %",
            "Radeon RX 9070/9070 XT/9070 GRE","10.0 / 32.0 GB","1180 rpm","0 rpm",
            "192.168.178.42","Ethernet, 1 Gbit/s","a8:a1:59:3c:21:7e","38 ms"};
        for(unsigned i=0;i<sizeof shown/sizeof *shown;i++)assert(label(page,shown[i]));
        // In the order of the page: the system, the hardware, the network.
        lv_obj_update_layout(screen_now);
        lv_area_t system_at,hardware_at,network_at;
        lv_obj_get_coords(label(page,panel_text(TXT_PC_SYSTEM)),&system_at);
        lv_obj_get_coords(label(page,panel_text(TXT_PC_HARDWARE)),&hardware_at);
        lv_obj_get_coords(label(page,panel_text(TXT_PC_NETWORK)),&network_at);
        assert(system_at.y1<hardware_at.y1&&hardware_at.y1<network_at.y1);
        // More than a screen, so it scrolls, and only up and down.
        assert(lv_obj_has_flag(page,LV_OBJ_FLAG_SCROLLABLE));
        assert(lv_obj_get_scroll_dir(page)==LV_DIR_VER);
        assert(lv_obj_get_scroll_bottom(page)>0);
        // Each row is one line. Its value fits, and the name of the card
        // does.
        // The kernel is longer than its room and ends in dots, which LVGL
        // writes into the text. Its label is the one after its name.
        lv_obj_t *kernel_name=label(page,panel_text(TXT_PC_KERNEL));
        lv_obj_t *kernel=lv_obj_get_child(lv_obj_get_parent(kernel_name),
                                          lv_obj_get_index(kernel_name)+1);
        assert(strncmp(lv_label_get_text(kernel),"7.2.7-valve1",12)==0);
        assert(lv_obj_get_height(kernel)==lv_font_get_line_height(&panel_font_14));
        lv_point_t room;
        lv_obj_t *gpu=label(page,"Radeon RX 9070/9070 XT/9070 GRE");
        lv_text_get_size(&room,lv_label_get_text(gpu),&panel_font_14,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
        assert(room.x<=lv_obj_get_width(gpu));
        // The memory is a row of text and nothing more: no bar under it,
        // and the next row 30 below it, as everywhere else.
        lv_obj_t *memory_row=label(page,"10.0 / 32.0 GB");
        lv_obj_t *card=lv_obj_get_parent(memory_row);
        for(unsigned i=0;i<lv_obj_get_child_count(card);i++)
            assert(lv_obj_check_type(lv_obj_get_child(card,i),&lv_label_class));
        assert(lv_obj_get_y(label(card,panel_text(TXT_PC_FAN)))-
               lv_obj_get_y(label(card,panel_text(TXT_PC_MEMORY)))==30);
        // A number nobody sent is "--", and so is a text.
        panel_pc_t none={.uptime_s=-1,.cpu_load=-1,.fan_rpm=-1,.gpu_fan_rpm=-1,.link_mbit=-1,.answer_ms=-1};
        c.pc=none;
        panel_ui_update(&c);
        unsigned dashes=0;
        for(unsigned g=0;g<lv_obj_get_child_count(page);g++){
            lv_obj_t *one=lv_obj_get_child(page,g);
            for(unsigned i=0;i<lv_obj_get_child_count(one);i++){
                lv_obj_t *o=lv_obj_get_child(one,i);
                if(lv_obj_check_type(o,&lv_label_class)&&strcmp(lv_label_get_text(o),"--")==0)dashes++;
            }
        }
        // Every row but the name, which the PC sends with every answer.
        assert(dashes==15);
        assert(!label(page,"10.0 / 32.0 GB"));
        // A PC that does not answer: the page says so and shows no card.
        c.pc=pc;c.online=false;
        panel_ui_update(&c);
        assert(label(page,panel_text(TXT_PC_OFFLINE)));
        assert(!label(page,"SteamOS 3.9.2")&&!label(page,panel_text(TXT_PC_SYSTEM)));
        c.online=true;
        panel_ui_update(&c);
        assert(label(page,"SteamOS 3.9.2"));
        lv_refr_now(screen);
        assert(complaints==0);
        click(panel_text(TXT_BACK));
        assert(!label(screen_now,panel_text(TXT_PC_DETAILS)));
        // German, and a link of 2.5 Gbit/s. Every name of a row fits its
        // room in both languages.
        panel_settings_t german={.brightness=70,.sound_volume=30,.language=PANEL_GERMAN};
        panel_ui_create(action,setting,sound,&german);
        c.pc.link_mbit=2500;
        panel_ui_update(&c);
        panel_ui_pc_open();
        assert(label(lv_screen_active(),"PC-Details"));
        assert(label(lv_screen_active(),"LAN, 2.5 Gbit/s"));
        assert(label(lv_screen_active(),"2 T. 4 Std. 13 Min."));
        assert(label(lv_screen_active(),"1180 U/min"));
        for(int language=0;language<2;language++){
            panel_text_set(language==0?PANEL_ENGLISH:PANEL_GERMAN);
            static const panel_text_id_t names[]={TXT_PC_NAME,TXT_PC_OS,TXT_PC_BUILD,
                TXT_PC_CHANNEL,TXT_PC_KERNEL,TXT_PC_UPTIME,TXT_PC_CPU,TXT_PC_LOAD,
                TXT_PC_GPU,TXT_PC_MEMORY,TXT_PC_FAN,TXT_PC_GPU_FAN,TXT_PC_IP,
                TXT_PC_LINK,TXT_PC_MAC,TXT_PC_ANSWER};
            for(unsigned i=0;i<sizeof names/sizeof *names;i++){
                lv_text_get_size(&room,panel_text(names[i]),&panel_font_14,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
                assert(room.x<=140);
            }
        }
        panel_text_set(PANEL_GERMAN);
        // The setup takes the page away, and a new screen drops it.
        c.setup=true;
        panel_ui_update(&c);
        assert(!label(lv_screen_active(),"PC-Details"));
        c.setup=false;
        panel_ui_create(action,setting,sound,&english);
        panel_ui_pc_open();
        panel_ui_create(action,setting,sound,&english);
        assert(!label(lv_screen_active(),panel_text(TXT_PC_DETAILS)));
        panel_ui_pc_open();
        assert(label(lv_screen_active(),panel_text(TXT_PC_DETAILS)));
        lv_refr_now(screen);
        assert(complaints==0);
        panel_ui_create(action,setting,sound,&english);
    }

    // The temperatures and the power of the card: one card across the
    // screen, three fields of the same width, a short line between each
    // two. A tap on the processor, or on the card or its power, opens the
    // choice of its sensor.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_state_t t=base();
        t.cpu_temp=49;t.gpu_temp=56;t.gpu_watts=78;
        static const panel_sensor_t cpus[]={{"k10temp/Tctl","Tctl",49},{"k10temp/Tccd1","CCD 1",47}};
        static const panel_sensor_t gpus[]={{"amdgpu/edge","Edge",56},
            {"amdgpu/junction","Junction (Hotspot)",68},{"amdgpu/mem","VRAM",60}};
        memcpy(t.cpu_sensors,cpus,sizeof cpus);t.cpu_sensor_count=2;
        memcpy(t.gpu_sensors,gpus,sizeof gpus);t.gpu_sensor_count=3;
        panel_ui_update(&t);
        lv_obj_t *screen_now=lv_screen_active();
        lv_obj_t *cpu_tile=lv_obj_get_parent(label(screen_now,"49 °C"));
        lv_obj_t *gpu_tile=lv_obj_get_parent(label(screen_now,"56 °C"));
        assert(cpu_tile!=gpu_tile&&lv_obj_get_parent(label(screen_now,"78 W"))==gpu_tile);
        // One card for the three, across the screen, and not a place for a
        // tap of its own.
        lv_obj_t *foot=lv_obj_get_parent(cpu_tile);
        assert(lv_obj_get_parent(gpu_tile)==foot&&lv_obj_get_parent(foot)==screen_now);
        assert(!lv_obj_has_flag(foot,LV_OBJ_FLAG_CLICKABLE));
        lv_obj_update_layout(screen_now);
        lv_area_t across;
        lv_obj_get_coords(foot,&across);
        assert(across.x1==10&&lv_area_get_width(&across)==460);
        // A line at a third of it and one at two thirds, and nothing else
        // as thin.
        int32_t lines[3];
        unsigned line_count=0;
        lv_obj_t *holders[2]={foot,gpu_tile};
        for(unsigned h=0;h<2;h++)
            for(unsigned i=0;i<lv_obj_get_child_count(holders[h]);i++){
                lv_obj_t *o=lv_obj_get_child(holders[h],i);
                if(lv_obj_get_width(o)!=1||lv_obj_get_height(o)!=30)continue;
                lv_area_t at;
                lv_obj_get_coords(o,&at);
                assert(line_count<2);
                lines[line_count++]=at.x1-across.x1;
            }
        assert(line_count==2);
        assert((lines[0]==153&&lines[1]==306)||(lines[0]==306&&lines[1]==153));
        // Each third holds its sign, its caption and its reading as one
        // block in its middle: the room before the sign is the room after
        // the block, or one less. The block is as wide as the wider of the
        // caption and the widest reading of the third, two digits for a
        // temperature and three for the power.
        static const char *const readings[]={"49 °C","56 °C","78 W"};
        static const char *const captions[]={"CPU","GPU","GPU-WATT"};
        static const char *const widest[]={"00 °C","00 °C","000 W"};
        int32_t signs[3];
        for(unsigned i=0;i<3;i++){
            lv_obj_t *reading=label(screen_now,readings[i]),*caption=label(screen_now,captions[i]);
            lv_area_t words,said;
            lv_obj_get_coords(reading,&words);
            lv_obj_get_coords(caption,&said);
            // The caption over the reading, from the same edge.
            assert(said.x1==words.x1);
            int32_t start=across.x1+1+153*(int32_t)i,end=start+152;
            signs[i]=sign_before(lv_obj_get_parent(reading),start,words.x1);
            lv_point_t a,b;
            lv_text_get_size(&a,captions[i],lv_obj_get_style_text_font(caption,0),0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
            lv_text_get_size(&b,widest[i],lv_obj_get_style_text_font(reading,0),0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
            int32_t before=signs[i]-start,after=end-(words.x1+LV_MAX(a.x,b.x));
            assert(after-before==0||after-before==1);
        }
        // A reading of another width moves nothing. A block as wide as the
        // reading of the moment would move its sign at each change of the
        // number.
        {
            panel_state_t other=t;
            other.cpu_temp=51;other.gpu_temp=100;other.gpu_watts=245;
            panel_ui_update(&other);
            lv_obj_update_layout(screen_now);
            static const char *const changed[]={"51 °C","100 °C","245 W"};
            for(unsigned i=0;i<3;i++){
                lv_obj_t *reading=label(screen_now,changed[i]);
                assert(reading);
                lv_area_t words;
                lv_obj_get_coords(reading,&words);
                int32_t start=across.x1+1+153*(int32_t)i;
                assert(sign_before(lv_obj_get_parent(reading),start,words.x1)==signs[i]);
            }
            panel_ui_update(&t);
        }
        // The processor: the choice of the service and both sensors, with
        // a mark on the choice of the service.
        lv_obj_send_event(cpu_tile,LV_EVENT_CLICKED,NULL);
        assert(label(screen_now,panel_text(TXT_CPU_TEMPERATURE)));
        assert(strcmp(panel_ui_where(),"a choice of sensor")==0);
        assert(label(screen_now,LV_SYMBOL_OK "  Automatic"));
        assert(label(screen_now,"Tctl")&&label(screen_now,"CCD 1")&&label(screen_now,"47 °C"));
        // The other choices do not open over it, and neither does a second
        // menu.
        lv_obj_send_event(cpu_tile,LV_EVENT_CLICKED,NULL);
        panel_ui_pads_open();
        assert(strcmp(panel_ui_where(),"a choice of sensor")==0);
        // A new answer while the menu is open brings the sensors in another
        // order; a row still chooses the sensor it names.
        panel_state_t moved=t;
        panel_sensor_t other_way[]={{"k10temp/Tccd1","CCD 1",47},{"k10temp/Tctl","Tctl",49}};
        memcpy(moved.cpu_sensors,other_way,sizeof other_way);
        panel_ui_update(&moved);
        saved_count=0;
        click("CCD 1");
        assert(!label(screen_now,panel_text(TXT_CPU_TEMPERATURE)));
        assert(saved_count==1&&saved_key==PANEL_CPU_SENSOR);
        assert((uint32_t)saved_value==panel_sensor_key("k10temp/Tccd1"));
        assert(label(screen_now,"47 °C")&&!label(screen_now,"49 °C"));
        // The choice follows its sensor through new answers, in another
        // order too.
        t.cpu_temp=50;
        panel_sensor_t turned[]={{"k10temp/Tccd1","CCD 1",48},{"k10temp/Tctl","Tctl",50}};
        memcpy(t.cpu_sensors,turned,sizeof turned);
        panel_ui_update(&t);
        assert(label(screen_now,"48 °C"));
        // A new screen with the stored key shows the same sensor, and the
        // menu marks it.
        panel_settings_t stored=english;stored.cpu_sensor=panel_sensor_key("k10temp/Tccd1");
        panel_ui_create(action,setting,sound,&stored);
        panel_ui_update(&t);
        screen_now=lv_screen_active();
        assert(label(screen_now,"48 °C"));
        lv_obj_send_event(lv_obj_get_parent(label(screen_now,"48 °C")),LV_EVENT_CLICKED,NULL);
        assert(label(screen_now,LV_SYMBOL_OK "  CCD 1")&&label(screen_now,"Automatic"));
        // Back to the choice of the service.
        click("Automatic");
        assert(saved_key==PANEL_CPU_SENSOR&&saved_value==0);
        assert(label(screen_now,"50 °C"));
        // A key that no sensor has any more is the choice of the service.
        stored.cpu_sensor=panel_sensor_key("k10temp/Tdie");
        panel_ui_create(action,setting,sound,&stored);
        panel_ui_update(&t);
        assert(label(lv_screen_active(),"50 °C"));
        // The card, and a tap beside the box closes the menu.
        screen_now=lv_screen_active();
        lv_obj_send_event(lv_obj_get_parent(label(screen_now,"78 W")),LV_EVENT_CLICKED,NULL);
        assert(label(screen_now,panel_text(TXT_GPU_TEMPERATURE)));
        assert(label(screen_now,"Junction (Hotspot)")&&label(screen_now,"68 °C"));
        lv_refr_now(screen);
        assert(complaints==0);
        lv_obj_send_event(lv_obj_get_child(screen_now,-1),LV_EVENT_CLICKED,NULL);
        assert(!label(screen_now,panel_text(TXT_GPU_TEMPERATURE)));
        // A PC that does not answer: the rows have no reading.
        t.online=false;
        panel_ui_update(&t);
        lv_obj_send_event(lv_obj_get_parent(label(screen_now,"-- W")),LV_EVENT_CLICKED,NULL);
        assert(label(screen_now,panel_text(TXT_GPU_TEMPERATURE))&&!label(screen_now,"68 °C"));
        // A new screen for a new language drops the menu, and the setup
        // takes it away.
        panel_ui_create(action,setting,sound,&english);
        assert(!label(lv_screen_active(),panel_text(TXT_GPU_TEMPERATURE)));
        t.online=true;
        panel_ui_update(&t);
        screen_now=lv_screen_active();
        lv_obj_send_event(lv_obj_get_parent(label(screen_now,"78 W")),LV_EVENT_CLICKED,NULL);
        assert(label(screen_now,panel_text(TXT_GPU_TEMPERATURE)));
        t.setup=true;
        panel_ui_update(&t);
        assert(!label(screen_now,panel_text(TXT_GPU_TEMPERATURE)));
        t.setup=false;
        panel_ui_create(action,setting,sound,&english);
        lv_refr_now(screen);
        assert(complaints==0);
    }

    // The page of the panel itself: a tap on its network and battery opens
    // it, and it offers an update only when the PC offers a newer one.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_state_t u=base();
        static const panel_self_t self={.version="61-1eec536",.ssid="FRITZ!Box 7590",
            .ip="192.168.178.57",.mac="24:58:7c:12:ab:cd",.server="192.168.178.42:8765",
            .rssi=-58,.uptime_s=3*3600+12*60,.heap_free=142*1024,.psram_free=6400*1024};
        u.self=self;u.esp_supply=PANEL_SUPPLY_BATTERY;u.esp_battery=87;
        panel_ui_update(&u);
        lv_obj_t *screen_now=lv_screen_active();
        lv_obj_t *corner=lv_obj_get_parent(label(screen_now,LV_SYMBOL_WIFI));
        assert(corner&&corner!=screen_now);
        lv_obj_send_event(corner,LV_EVENT_CLICKED,NULL);
        assert(label(screen_now,panel_text(TXT_SELF_TITLE)));
        assert(strcmp(panel_ui_where(),"the panel")==0);
        static const char *const rows[]={"Build 61 (1eec536)","3 h 12 min","142 KB, PSRAM 6.2 MB",
            "FRITZ!Box 7590","-58 dBm","192.168.178.57","24:58:7c:12:ab:cd",
            "192.168.178.42:8765","87 %"};
        for(unsigned i=0;i<sizeof rows/sizeof *rows;i++)assert(label(screen_now,rows[i]));
        assert(label(screen_now,panel_text(TXT_ON_BATTERY)));
        // No offer, no card of the update, and the cards close up.
        assert(!label(screen_now,panel_text(TXT_UPDATE_NOW)));
        lv_obj_update_layout(screen_now);
        int32_t network_alone=lv_obj_get_y(lv_obj_get_parent(label(screen_now,panel_text(TXT_PC_NETWORK))));
        // An offer: the card under the firmware, with its build and its
        // button.
        snprintf(u.update.offered,sizeof u.update.offered,"64-2b7f0c1");
        panel_ui_update(&u);
        lv_obj_update_layout(screen_now);
        assert(label(screen_now,"Build 64 (2b7f0c1)"));
        lv_obj_t *now=lv_obj_get_parent(label(screen_now,panel_text(TXT_UPDATE_NOW)));
        assert(!lv_obj_has_state(now,LV_STATE_DISABLED));
        int32_t update_at=lv_obj_get_y(lv_obj_get_parent(label(screen_now,panel_text(TXT_UPDATE))));
        int32_t firmware_at=lv_obj_get_y(lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_FIRMWARE))));
        int32_t network_after=lv_obj_get_y(lv_obj_get_parent(label(screen_now,panel_text(TXT_PC_NETWORK))));
        assert(firmware_at<update_at&&update_at<network_after&&network_alone<network_after);
        // It asks first, and the answer sends the update.
        click(panel_text(TXT_UPDATE_NOW));
        assert(label(screen_now,panel_text(TXT_CONFIRM_UPDATE)));
        actions=0;
        click(panel_text(TXT_CONFIRM));
        assert(actions==1&&last_action==PANEL_UPDATE);
        // The battery guard: below 20 per cent on the cell, the button waits
        // and the card says why. Charging or a cable lets it go.
        u.esp_battery=12;
        panel_ui_update(&u);
        assert(lv_obj_has_state(now,LV_STATE_DISABLED));
        assert(label(screen_now,panel_text(TXT_UPDATE_POWER)));
        u.esp_charging=true;
        panel_ui_update(&u);
        assert(!lv_obj_has_state(now,LV_STATE_DISABLED)&&!label(screen_now,panel_text(TXT_UPDATE_POWER)));
        u.esp_charging=false;u.esp_cable=true;
        panel_ui_update(&u);
        assert(!lv_obj_has_state(now,LV_STATE_DISABLED));
        assert(label(screen_now,panel_text(TXT_CHARGED)));
        u.esp_cable=false;u.esp_battery=20;
        panel_ui_update(&u);
        assert(!lv_obj_has_state(now,LV_STATE_DISABLED));
        // A PC that does not answer has nothing to send.
        u.online=false;
        panel_ui_update(&u);
        assert(lv_obj_has_state(now,LV_STATE_DISABLED));
        u.online=true;
        // The screen while it writes, over everything, with its share.
        u.update.phase=PANEL_UPDATE_RUNNING;u.update.percent=45;
        panel_ui_update(&u);
        assert(strcmp(panel_ui_where(),"an update")==0);
        assert(label(screen_now,panel_text(TXT_UPDATE_RUNNING))&&label(screen_now,"45 %"));
        assert(label(screen_now,panel_text(TXT_UPDATE_KEEP_ON)));
        lv_obj_update_layout(screen_now);
        lv_obj_t *layer=lv_obj_get_child(screen_now,-1);
        assert(lv_obj_get_width(layer)==480&&lv_obj_get_height(layer)==480);
        u.update.phase=PANEL_UPDATE_RESTARTING;u.update.percent=100;
        panel_ui_update(&u);
        assert(label(screen_now,panel_text(TXT_UPDATE_RESTART))&&label(screen_now,"100 %"));
        // A failure takes the screen away and says why on the card.
        u.update.phase=PANEL_UPDATE_FAILED;u.update.failure=TXT_UPDATE_BROKEN;
        panel_ui_update(&u);
        assert(!label(screen_now,panel_text(TXT_UPDATE_RUNNING)));
        assert(label(screen_now,"Update failed: The firmware arrived damaged."));
        assert(!lv_obj_has_state(now,LV_STATE_DISABLED));
        // A failure with no offer left keeps the card, without a button
        // that works.
        u.update.offered[0]=0;
        panel_ui_update(&u);
        assert(label(screen_now,"Update failed: The firmware arrived damaged."));
        assert(lv_obj_has_state(now,LV_STATE_DISABLED));
        lv_refr_now(screen);
        assert(complaints==0);
        // German, then the setup takes the page away.
        panel_settings_t german={.brightness=70,.sound_volume=30,.language=PANEL_GERMAN};
        panel_ui_create(action,setting,sound,&german);
        assert(!label(lv_screen_active(),"Panel-Info"));
        panel_ui_update(&u);
        panel_ui_self_open();
        assert(label(lv_screen_active(),"Panel-Info"));
        assert(label(lv_screen_active(),"Update fehlgeschlagen: Die Firmware kam beschädigt an."));
        u.setup=true;
        panel_ui_update(&u);
        assert(!label(lv_screen_active(),"Panel-Info"));
        u.setup=false;
        panel_ui_create(action,setting,sound,&english);
        lv_refr_now(screen);
        assert(complaints==0);
    }

    // The order of the pages: the band stands in the order somebody chose,
    // and the screen in the settings changes it a place at a time.
    {
        static const uint8_t clock_first[PANEL_PAGES]={PANEL_PAGE_CLOCK,PANEL_PAGE_CONTROLS,
            PANEL_PAGE_SESSION,PANEL_PAGE_PLAYING,PANEL_PAGE_CARD,PANEL_PAGE_LED,PANEL_PAGE_CPU};
        panel_settings_t ordered={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH,
                                  .page_order=panel_pages_pack(clock_first)};
        panel_ui_create(action,setting,sound,&ordered);
        lv_obj_t *band_now=find_band(lv_screen_active());
        assert(band_now);
        lv_obj_update_layout(lv_screen_active());
        // The clock is the start page now: at the left, and where the band
        // stands at the start.
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CLOCK))==0);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CONTROLS))==480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CARD))==4*480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_LED))==5*480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CPU))==6*480);
        assert(strcmp(panel_ui_where(),"the clock")==0);
        // The screen of the order, behind a button in the settings.
        panel_ui_settings_open();
        assert(label(lv_screen_active(),panel_text(TXT_PAGES)));
        assert(label(lv_screen_active(),panel_text(TXT_PAGES_WHAT)));
        click(panel_text(TXT_PAGES_ARRANGE));
        assert(strcmp(panel_ui_where(),"the order of the pages")==0);
        // The search stays on that screen: the band behind it has names
        // like these too.
        lv_obj_t *screen_now=lv_obj_get_parent(label(lv_screen_active(),panel_text(TXT_PAGES_TITLE)));
        assert(screen_now&&lv_obj_get_parent(screen_now)==lv_screen_active());
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        // A row for each place, in that order, the start page marked.
        static const panel_text_id_t first_names[PANEL_PAGES]={TXT_PAGE_CLOCK,TXT_PAGE_CONTROLS,
            TXT_PAGE_SESSION,TXT_PLAYING,TXT_PAGE_CARD,TXT_PAGE_LED,TXT_PAGE_CPU};
        int32_t last_y=-1;
        for(int place=0;place<PANEL_PAGES;place++){
            lv_obj_t *name=label(screen_now,panel_text(first_names[place]));
            assert(name);
            lv_obj_t *row=lv_obj_get_parent(name);
            assert(lv_obj_get_y(row)>last_y);
            last_y=lv_obj_get_y(row);
            assert(lv_obj_get_y(row)+lv_obj_get_height(row)<=480);
            assert(name_fits(name));
        }
        lv_obj_t *start=label(screen_now,panel_text(TXT_PAGES_START));
        assert(start&&lv_obj_get_parent(start)==lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CLOCK))));
        // The top row has no way up, and the bottom row no way down.
        lv_obj_t *top=lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CLOCK)));
        lv_obj_t *bottom=lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CPU)));
        lv_obj_t *top_up=NULL,*top_down=NULL,*bottom_up=NULL,*bottom_down=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(top);i++){
            lv_obj_t *c=lv_obj_get_child(top,i);
            if(!lv_obj_check_type(c,&lv_button_class))continue;
            if(label(c,LV_SYMBOL_UP))top_up=c;
            if(label(c,LV_SYMBOL_DOWN))top_down=c;
        }
        for(unsigned i=0;i<lv_obj_get_child_count(bottom);i++){
            lv_obj_t *c=lv_obj_get_child(bottom,i);
            if(!lv_obj_check_type(c,&lv_button_class))continue;
            if(label(c,LV_SYMBOL_UP))bottom_up=c;
            if(label(c,LV_SYMBOL_DOWN))bottom_down=c;
        }
        assert(top_up&&top_down&&bottom_up&&bottom_down);
        assert(lv_obj_has_state(top_up,LV_STATE_DISABLED)&&!lv_obj_has_state(top_down,LV_STATE_DISABLED));
        assert(lv_obj_has_state(bottom_down,LV_STATE_DISABLED)&&!lv_obj_has_state(bottom_up,LV_STATE_DISABLED));
        // Down on the top row: the clock goes second and the controls are
        // the start page. The order is saved and the band moves at once.
        saved_count=0;
        lv_obj_send_event(top_down,LV_EVENT_CLICKED,NULL);
        static const uint8_t controls_first[PANEL_PAGES]={PANEL_PAGE_CONTROLS,PANEL_PAGE_CLOCK,
            PANEL_PAGE_SESSION,PANEL_PAGE_PLAYING,PANEL_PAGE_CARD,PANEL_PAGE_LED,PANEL_PAGE_CPU};
        assert(saved_count==1&&saved_key==PANEL_PAGE_ORDER);
        assert((uint32_t)saved_value==panel_pages_pack(controls_first));
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CONTROLS))==0);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CLOCK))==480);
        start=label(screen_now,panel_text(TXT_PAGES_START));
        assert(start&&lv_obj_get_parent(start)==lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CONTROLS))));
        // Up on the bottom row: the CPU goes sixth.
        lv_obj_send_event(bottom_up,LV_EVENT_CLICKED,NULL);
        static const uint8_t cpu_sixth[PANEL_PAGES]={PANEL_PAGE_CONTROLS,PANEL_PAGE_CLOCK,
            PANEL_PAGE_SESSION,PANEL_PAGE_PLAYING,PANEL_PAGE_CARD,PANEL_PAGE_CPU,PANEL_PAGE_LED};
        assert((uint32_t)saved_value==panel_pages_pack(cpu_sixth));
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CPU))==5*480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_LED))==6*480);
        // A press on a disabled end moves nothing and saves nothing.
        int before=saved_count;
        lv_obj_send_event(top_up,LV_EVENT_CLICKED,NULL);
        assert(saved_count==before);
        lv_refr_now(screen);
        assert(complaints==0);
        // Back to the settings, and they are still open.
        click_in(screen_now,panel_text(TXT_BACK));
        assert(strcmp(panel_ui_where(),"the settings")==0);
        // The next language keeps the order, in the words of that language
        // and each name whole.
        panel_settings_t german=ordered;german.language=PANEL_GERMAN;
        german.page_order=panel_pages_pack(cpu_sixth);
        panel_ui_create(action,setting,sound,&german);
        panel_ui_settings_open();
        panel_ui_arrange_open();
        screen_now=lv_obj_get_parent(label(lv_screen_active(),"Seiten anordnen"));
        assert(screen_now);
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        assert(label(screen_now,"Seiten anordnen")&&label(screen_now,"Startseite"));
        static const char *const german_names[]={"Steuerung","Uhr und Timer",
            "Sitzung und Datenträger","Läuft gerade","Grafikkarte und Verlauf","CPU-Energie",
            "LED-Leiste"};
        last_y=-1;
        for(int place=0;place<PANEL_PAGES;place++){
            lv_obj_t *name=label(screen_now,german_names[place]);
            assert(name&&lv_obj_get_y(lv_obj_get_parent(name))>last_y);
            last_y=lv_obj_get_y(lv_obj_get_parent(name));
            assert(name_fits(name));
        }
        // The setup takes the screen of the order away with the settings.
        panel_state_t up=base();up.setup=true;
        panel_ui_update(&up);
        assert(!label(lv_screen_active(),"Seiten anordnen"));
        up.setup=false;
        // A stored number that no firmware wrote still gives every page
        // once.
        panel_settings_t garbled={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH,
                                  .page_order=0x44444444u};
        panel_ui_create(action,setting,sound,&garbled);
        band_now=find_band(lv_screen_active());
        lv_obj_update_layout(lv_screen_active());
        bool taken[PANEL_PAGES]={false};
        for(int i=0;i<PANEL_PAGES;i++){
            int32_t x=lv_obj_get_x(lv_obj_get_child(band_now,i));
            assert(x%480==0&&x/480<PANEL_PAGES&&!taken[x/480]);
            taken[x/480]=true;
        }
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CARD))==0);
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
    }

    // A page can be hidden: an eye on each row beside the arrows, and the
    // eye with a stroke through it on a hidden page. The band holds only
    // the pages that are shown, the first of them is the start page, and
    // the last page that is shown cannot go.
    {
        static const panel_text_id_t names[PANEL_PAGES]={TXT_PAGE_CONTROLS,TXT_PAGE_SESSION,
            TXT_PLAYING,TXT_PAGE_CLOCK,TXT_PAGE_CARD,TXT_PAGE_LED,TXT_PAGE_CPU};
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        lv_obj_t *band_now=find_band(lv_screen_active());
        lv_obj_update_layout(lv_screen_active());
        // On the session, away from the start page.
        lv_obj_scroll_to_x(band_now,480,LV_ANIM_OFF);
        assert(strcmp(panel_ui_where(),"the session")==0);
        panel_ui_settings_open();
        panel_ui_arrange_open();
        lv_obj_t *screen_now=lv_obj_get_parent(label(lv_screen_active(),panel_text(TXT_PAGES_TITLE)));
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        // Each row has an open eye left of its arrows, and its name whole
        // and left of the eye.
        for(int page=0;page<PANEL_PAGES;page++){
            lv_obj_t *name=label(screen_now,panel_text(names[page]));
            lv_obj_t *row=lv_obj_get_parent(name);
            lv_obj_t *eye=button_with(row,LV_SYMBOL_EYE_OPEN),*up=button_with(row,LV_SYMBOL_UP);
            assert(eye&&up&&button_with(row,LV_SYMBOL_DOWN));
            assert(!button_with(row,LV_SYMBOL_EYE_CLOSE));
            assert(lv_obj_get_x(eye)+lv_obj_get_width(eye)<=lv_obj_get_x(up));
            assert(!lv_obj_has_state(eye,LV_STATE_DISABLED));
            assert(name_fits(name));
        }
        lv_obj_t *start=label(screen_now,panel_text(TXT_PAGES_START));
        lv_color_t grey=lv_obj_get_style_text_color(start,0);
        // The eye of the session: saved at once, the eye with a stroke,
        // the name in grey, and the page out of the band. The pages after
        // it move up a place, and the band, whose page went, goes to the
        // start page.
        lv_obj_t *session=label(screen_now,panel_text(TXT_PAGE_SESSION));
        lv_obj_t *session_row=lv_obj_get_parent(session);
        saved_count=0;
        lv_obj_send_event(button_with(session_row,LV_SYMBOL_EYE_OPEN),LV_EVENT_CLICKED,NULL);
        assert(saved_count==1&&saved_key==PANEL_PAGE_HIDDEN&&saved_value==1<<PANEL_PAGE_SESSION);
        assert(button_with(session_row,LV_SYMBOL_EYE_CLOSE)&&!button_with(session_row,LV_SYMBOL_EYE_OPEN));
        assert(lv_color_eq(lv_obj_get_style_text_color(session,0),grey));
        assert(!lv_color_eq(lv_obj_get_style_text_color(label(screen_now,panel_text(TXT_PAGE_CLOCK)),0),grey));
        assert(lv_obj_has_flag(lv_obj_get_child(band_now,PANEL_PAGE_SESSION),LV_OBJ_FLAG_HIDDEN));
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CONTROLS))==0);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_PLAYING))==480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CLOCK))==2*480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CARD))==3*480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_LED))==4*480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CPU))==5*480);
        assert(lv_obj_get_scroll_x(band_now)==0);
        // The band ends at the last page that is shown.
        lv_obj_scroll_to_x(band_now,PANEL_PAGES*480,LV_ANIM_OFF);
        assert(lv_obj_get_scroll_x(band_now)==5*480);
        // A move keeps the band on the page it shows, at its new place.
        lv_obj_scroll_to_x(band_now,3*480,LV_ANIM_OFF);
        assert(lv_obj_get_scroll_x(band_now)==3*480);
        lv_obj_t *card_row=lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CARD)));
        lv_obj_send_event(button_with(card_row,LV_SYMBOL_UP),LV_EVENT_CLICKED,NULL);
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CARD))==2*480);
        assert(lv_obj_get_scroll_x(band_now)==2*480);
        lv_obj_send_event(button_with(lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CARD))),
                                      LV_SYMBOL_DOWN),LV_EVENT_CLICKED,NULL);
        // The controls hidden as well: the start page is the first page
        // that is shown, the game, and its row has the line that says so.
        lv_obj_t *controls_row=lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CONTROLS)));
        lv_obj_send_event(button_with(controls_row,LV_SYMBOL_EYE_OPEN),LV_EVENT_CLICKED,NULL);
        assert(saved_value==((1<<PANEL_PAGE_SESSION)|(1<<PANEL_PAGE_CONTROLS)));
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_PLAYING))==0);
        start=label(screen_now,panel_text(TXT_PAGES_START));
        assert(lv_obj_get_parent(start)==lv_obj_get_parent(label(screen_now,panel_text(TXT_PLAYING))));
        unsigned starts=0;
        for(int page=0;page<PANEL_PAGES;page++){
            lv_obj_t *row=lv_obj_get_parent(label(screen_now,panel_text(names[page])));
            for(unsigned i=0;i<lv_obj_get_child_count(row);i++){
                lv_obj_t *c=lv_obj_get_child(row,i);
                if(lv_obj_check_type(c,&lv_label_class)&&!lv_obj_has_flag(c,LV_OBJ_FLAG_HIDDEN)&&
                   strcmp(lv_label_get_text(c),panel_text(TXT_PAGES_START))==0)starts++;
            }
        }
        assert(starts==1);
        // A hidden page still moves: it keeps its place in the order.
        lv_obj_send_event(button_with(controls_row,LV_SYMBOL_DOWN),LV_EVENT_CLICKED,NULL);
        assert(saved_key==PANEL_PAGE_ORDER);
        lv_obj_send_event(button_with(lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CONTROLS))),
                                      LV_SYMBOL_UP),LV_EVENT_CLICKED,NULL);
        // All but the card hidden: the card is the start page and the only
        // page of the band, and its eye does nothing.
        lv_obj_send_event(button_with(lv_obj_get_parent(label(screen_now,panel_text(TXT_PLAYING))),
                                      LV_SYMBOL_EYE_OPEN),LV_EVENT_CLICKED,NULL);
        lv_obj_send_event(button_with(lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_LED))),
                                      LV_SYMBOL_EYE_OPEN),LV_EVENT_CLICKED,NULL);
        lv_obj_send_event(button_with(lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CPU))),
                                      LV_SYMBOL_EYE_OPEN),LV_EVENT_CLICKED,NULL);
        lv_obj_send_event(button_with(lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CLOCK))),
                                      LV_SYMBOL_EYE_OPEN),LV_EVENT_CLICKED,NULL);
        card_row=lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CARD)));
        lv_obj_t *last_eye=button_with(card_row,LV_SYMBOL_EYE_OPEN);
        assert(last_eye&&lv_obj_has_state(last_eye,LV_STATE_DISABLED));
        int before=saved_count;
        lv_obj_send_event(last_eye,LV_EVENT_CLICKED,NULL);
        assert(saved_count==before);
        assert(!lv_obj_has_flag(lv_obj_get_child(band_now,PANEL_PAGE_CARD),LV_OBJ_FLAG_HIDDEN));
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CARD))==0);
        lv_obj_scroll_to_x(band_now,PANEL_PAGES*480,LV_ANIM_OFF);
        assert(lv_obj_get_scroll_x(band_now)==0);
        // The session shown again, at its place, and the card's eye works
        // again.
        lv_obj_send_event(button_with(session_row,LV_SYMBOL_EYE_CLOSE),LV_EVENT_CLICKED,NULL);
        assert(saved_value==((1<<PANEL_PAGE_CONTROLS)|(1<<PANEL_PAGE_PLAYING)|(1<<PANEL_PAGE_CLOCK)
                             |(1<<PANEL_PAGE_LED)|(1<<PANEL_PAGE_CPU)));
        lv_obj_update_layout(lv_screen_active());
        assert(!lv_obj_has_flag(lv_obj_get_child(band_now,PANEL_PAGE_SESSION),LV_OBJ_FLAG_HIDDEN));
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_SESSION))==0);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CARD))==480);
        assert(!lv_obj_has_state(button_with(card_row,LV_SYMBOL_EYE_OPEN),LV_STATE_DISABLED));
        lv_refr_now(screen);
        // A panel that starts with hidden pages builds the band without
        // them, and starts on the first page that is shown.
        panel_settings_t stored=english;
        stored.page_hidden=(1u<<PANEL_PAGE_CONTROLS)|(1u<<PANEL_PAGE_PLAYING);
        panel_ui_create(action,setting,sound,&stored);
        band_now=find_band(lv_screen_active());
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_has_flag(lv_obj_get_child(band_now,PANEL_PAGE_CONTROLS),LV_OBJ_FLAG_HIDDEN));
        assert(lv_obj_has_flag(lv_obj_get_child(band_now,PANEL_PAGE_PLAYING),LV_OBJ_FLAG_HIDDEN));
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_SESSION))==0);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CLOCK))==480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CARD))==2*480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_LED))==3*480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CPU))==4*480);
        assert(strcmp(panel_ui_where(),"the session")==0);
        lv_obj_scroll_to_x(band_now,PANEL_PAGES*480,LV_ANIM_OFF);
        assert(strcmp(panel_ui_where(),"the CPU")==0);
        // A stored number that hides every page hides none.
        stored.page_hidden=0xFFFFFFFFu;
        panel_ui_create(action,setting,sound,&stored);
        band_now=find_band(lv_screen_active());
        for(int page=0;page<PANEL_PAGES;page++)
            assert(!lv_obj_has_flag(lv_obj_get_child(band_now,page),LV_OBJ_FLAG_HIDDEN));
        // In German, the same eyes, and each name whole.
        panel_settings_t german=stored;german.language=PANEL_GERMAN;
        german.page_hidden=1u<<PANEL_PAGE_CARD;
        panel_ui_create(action,setting,sound,&german);
        panel_ui_settings_open();
        panel_ui_arrange_open();
        screen_now=lv_obj_get_parent(label(lv_screen_active(),"Seiten anordnen"));
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        lv_obj_t *card=label(screen_now,"Grafikkarte und Verlauf");
        assert(card&&name_fits(card)&&button_with(lv_obj_get_parent(card),LV_SYMBOL_EYE_CLOSE));
        lv_obj_t *drives=label(screen_now,"Sitzung und Datenträger");
        assert(drives&&name_fits(drives)&&button_with(lv_obj_get_parent(drives),LV_SYMBOL_EYE_OPEN));
        assert(complaints==0);
        panel_ui_create(action,setting,sound,&english);
    }

    // The frames in movement, on the page of the panel: five rows and the
    // line that says what they are, each whole. The page reads the count
    // itself as it opens, and not the state: a state that changes at every
    // frame made panel_ui_update do all of its work at every tick of a
    // scroll. The count stands still while the page is open, and starts
    // again when it closes.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_state_t p=base();
        p.self=(panel_self_t){.version="61-1eec536",.heap_free=142*1024,
                              .psram_free=6400*1024,.heap_least=98*1024};
        panel_ui_update(&p);
        // No frame counted yet: dashes in each row.
        panel_ui_self_open();
        lv_obj_t *screen_now=lv_screen_active();
        lv_obj_t *card=lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_MOTION)));
        assert(card);
        unsigned dashes=0;
        for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
            lv_obj_t *c=lv_obj_get_child(card,i);
            if(lv_obj_check_type(c,&lv_label_class)&&strcmp(lv_label_get_text(c),"--")==0)dashes++;
        }
        assert(dashes==5);
        click_in(screen_now,panel_text(TXT_BACK));
        // Four frames, and the page shows what they work out at.
        count_some_frames();
        panel_ui_self_open();
        screen_now=lv_screen_active();
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        static const char *const shown[]={"22 fps (4 frames)","45 / 66 / 66 ms","33 / 45 / 45 ms",
            "4 / 9 / 9 ms","0 / 50 / 25 / 25 %","142 KB (min 98 KB), PSRAM 6.2 MB"};
        for(unsigned i=0;i<sizeof shown/sizeof *shown;i++){
            lv_obj_t *value=label(screen_now,shown[i]);
            assert(value&&name_fits(value));
        }
        card=lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_MOTION)));
        for(unsigned i=0;i<5;i++)assert(lv_obj_get_parent(label(screen_now,shown[i]))==card);
        static const panel_text_id_t names[]={TXT_SELF_FPS,TXT_SELF_INTERVAL,TXT_SELF_DRAW,
                                              TXT_SELF_LEAD,TXT_SELF_PERIODS};
        for(unsigned i=0;i<sizeof names/sizeof *names;i++)
            assert(name_fits(label(card,panel_text(names[i]))));
        // Under the firmware and above the network, on the first screen
        // of the page with no update offered: no scroll to read it.
        int32_t firmware_at=lv_obj_get_y(lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_FIRMWARE))));
        int32_t network_at=lv_obj_get_y(lv_obj_get_parent(label(screen_now,panel_text(TXT_PC_NETWORK))));
        assert(firmware_at<lv_obj_get_y(card)&&lv_obj_get_y(card)<network_at);
        lv_area_t card_area;
        lv_obj_get_coords(card,&card_area);
        assert(card_area.y2<480);
        // The line under the rows fits two lines and the card holds it.
        lv_obj_t *note=label(card,panel_text(TXT_SELF_MOTION_WHAT));
        assert(note);
        int32_t line_high=lv_font_get_line_height(&panel_font_12);
        assert(lv_obj_get_height(note)<=2*line_high);
        assert(lv_obj_get_y(note)+lv_obj_get_height(note)<=lv_obj_get_height(card));
        // A new state changes the rest of the page and not the frames.
        p.self.heap_least=0;
        panel_ui_update(&p);
        assert(label(screen_now,"142 KB, PSRAM 6.2 MB"));
        assert(label(screen_now,"22 fps (4 frames)"));
        // The page holds the count: frames while it is open do not count.
        assert(panel_frames.held);
        panel_frames_begin(&panel_frames,3000000);panel_frames_drawn(&panel_frames,3010000);
        panel_frames_shown(&panel_frames,3020000);
        panel_frames_begin(&panel_frames,3020000);panel_frames_drawn(&panel_frames,3030000);
        panel_frames_shown(&panel_frames,3040000);
        assert(panel_frames.counted==4);
        // Back, and the count starts again and counts, with the period
        // of the panel kept.
        click_in(screen_now,panel_text(TXT_BACK));
        assert(strcmp(panel_ui_where(),"the panel")!=0);
        assert(!panel_frames.held&&panel_frames.counted==0&&panel_frames.period_us==16575);
        panel_frames_begin(&panel_frames,4000000);panel_frames_drawn(&panel_frames,4010000);
        panel_frames_shown(&panel_frames,4020000);
        panel_frames_begin(&panel_frames,4020000);panel_frames_drawn(&panel_frames,4030000);
        panel_frames_shown(&panel_frames,4053150);
        assert(panel_frames.counted==1&&panel_frames.periods[1]==1);
        // In German, the same: each row whole and the line in two.
        panel_settings_t german=english;german.language=PANEL_GERMAN;
        panel_ui_create(action,setting,sound,&german);
        p.self.heap_least=98*1024;
        panel_ui_update(&p);
        count_some_frames();
        panel_ui_self_open();
        screen_now=lv_screen_active();
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        card=lv_obj_get_parent(label(screen_now,"ANZEIGE IN BEWEGUNG"));
        assert(card);
        assert(lv_obj_get_parent(label(screen_now,"22 fps (4 Bilder)"))==card);
        static const char *const german_names[]={"Bildrate","Bildabstand","Zeichenzeit","Vorlauf",
                                                 "Panelbilder"};
        for(unsigned i=0;i<sizeof german_names/sizeof *german_names;i++)
            assert(name_fits(label(card,german_names[i])));
        note=label(card,panel_text(TXT_SELF_MOTION_WHAT));
        assert(note&&lv_obj_get_height(note)<=2*line_high);
        assert(lv_obj_get_y(note)+lv_obj_get_height(note)<=lv_obj_get_height(card));
        lv_obj_get_coords(card,&card_area);
        assert(card_area.y2<480);
        assert(complaints==0);
        panel_ui_create(action,setting,sound,&english);
    }

    // The touches, on the page of the panel, under the frames: seven rows
    // and the line that says what they are, each whole. As the frames, the
    // page reads the count as it opens, holds it while it is open, and
    // starts it again when it closes.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_state_t p=base();
        panel_ui_update(&p);
        panel_taps_chip=(panel_taps_chip_t){0};
        // Nothing counted and no controller read: a dash in each row.
        panel_ui_self_open();
        lv_obj_t *screen_now=lv_screen_active();
        lv_obj_t *card=lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_TOUCH)));
        assert(card);
        unsigned dashes=0;
        for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
            lv_obj_t *c=lv_obj_get_child(card,i);
            if(lv_obj_check_type(c,&lv_label_class)&&strcmp(lv_label_get_text(c),"--")==0)dashes++;
        }
        assert(dashes==7);
        click_in(screen_now,panel_text(TXT_BACK));
        // Only reads, and no press: the reads have their rows, and the
        // presses none yet.
        {
            panel_taps_press_t done;
            panel_taps_read(&panel_taps,taps_now,true,false,0,0,-1,&done);
            taps_now+=15;
            panel_taps_read(&panel_taps,taps_now,true,false,0,0,-1,&done);
            taps_now+=15;
        }
        panel_ui_self_open();
        screen_now=lv_screen_active();
        card=lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_TOUCH)));
        assert(strcmp(row_value(card,TXT_SELF_PRESSES),"--")==0);
        assert(strcmp(row_value(card,TXT_SELF_LATE),"0, longest gap 15 ms")==0);
        assert(strcmp(row_value(card,TXT_SELF_READ_ERRORS),"0")==0);
        click_in(screen_now,panel_text(TXT_BACK));
        // Two taps, a swipe, two lost taps with a late read in one of them,
        // and a read the bus refused, from a controller that the start of
        // the panel read.
        taps_press(2,40,true,false,true,0);
        taps_press(1,42,true,false,true,0);
        taps_press(120,44,true,true,false,0);
        taps_press(3,31,true,false,false,55);
        taps_press(4,36,true,false,false,0);
        {
            panel_taps_press_t done;
            taps_now+=15;
            assert(!panel_taps_read(&panel_taps,taps_now,false,false,0,0,-1,&done));
        }
        panel_taps_chip=(panel_taps_chip_t){.known=true,.version='A',.touch_level=80,.leave_level=50,
                                            .report_ms=10};
        panel_ui_self_open();
        screen_now=lv_screen_active();
        lv_obj_update_layout(screen_now);
        card=lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_TOUCH)));
        static const panel_text_id_t names[]={TXT_SELF_PRESSES,TXT_SELF_LOST,TXT_SELF_SHORTEST,
            TXT_SELF_LATE,TXT_SELF_WEAKEST,TXT_SELF_READ_ERRORS,TXT_SELF_THRESHOLDS};
        static const char *const shown[]={"5: 2 taps, 1 swipes","2","30 ms","1, longest gap 70 ms",
                                          "31","1","80 down, 50 up, 10 ms"};
        for(unsigned i=0;i<sizeof names/sizeof *names;i++){
            assert(strcmp(row_value(card,names[i]),shown[i])==0);
            assert(name_fits(label(card,shown[i])));
        }
        for(unsigned i=0;i<sizeof names/sizeof *names;i++)
            assert(name_fits(label(card,panel_text(names[i]))));
        // Under the frames and above the network.
        int32_t motion_at=lv_obj_get_y(lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_MOTION))));
        int32_t network_at=lv_obj_get_y(lv_obj_get_parent(label(screen_now,panel_text(TXT_PC_NETWORK))));
        assert(motion_at<lv_obj_get_y(card)&&lv_obj_get_y(card)<network_at);
        // The line under the rows fits two lines and the card holds it.
        lv_obj_t *note=label(card,panel_text(TXT_SELF_TOUCH_WHAT));
        int32_t line_high=lv_font_get_line_height(&panel_font_12);
        assert(note&&lv_obj_get_height(note)<=2*line_high);
        assert(lv_obj_get_y(note)+lv_obj_get_height(note)<=lv_obj_get_height(card));
        // The page holds the count: a press while it is open does not
        // count, and the count starts again when it closes.
        assert(panel_taps.held);
        taps_press(1,40,true,false,true,0);
        assert(panel_taps.presses==5&&panel_taps.errors==1);
        click_in(screen_now,panel_text(TXT_BACK));
        assert(!panel_taps.held&&panel_taps.presses==0&&panel_taps.weakest_ever==-1);
        taps_press(1,40,true,false,true,0);
        assert(panel_taps.presses==1&&panel_taps.taps==1);
        // In German, each row whole.
        panel_settings_t german=english;german.language=PANEL_GERMAN;
        panel_ui_create(action,setting,sound,&german);
        panel_ui_update(&p);
        taps_press(2,40,true,false,true,0);
        panel_ui_self_open();
        screen_now=lv_screen_active();
        lv_obj_update_layout(screen_now);
        card=lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_TOUCH)));
        for(unsigned i=0;i<sizeof names/sizeof *names;i++)
            assert(name_fits(label(card,panel_text(names[i]))));
        assert(name_fits(label(card,"80 an, 50 aus, 10 ms")));
        note=label(card,panel_text(TXT_SELF_TOUCH_WHAT));
        assert(note&&lv_obj_get_height(note)<=2*line_high);
        assert(lv_obj_get_y(note)+lv_obj_get_height(note)<=lv_obj_get_height(card));
        assert(complaints==0);
        panel_ui_create(action,setting,sound,&english);
    }

    // The power chip in detail, on the page of the panel: its voltages,
    // the temperature of the chip, the phase of the charge and what holds
    // it down, and the settings of the charger in a card of their own.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_state_t p=base();
        p.esp_supply=PANEL_SUPPLY_BATTERY;p.esp_battery=87;p.esp_charging=true;p.esp_cable=true;
        p.esp_detail=(panel_power_detail_t){.vbat_mv=3984,.vbus_mv=5011,.vsys_mv=3714,
            .die_c=38,.phase=2,.held_current=true,.charge_ma=1000,.charge_mv=4200,.input_ma=1500};
        panel_ui_update(&p);
        panel_ui_self_open();
        lv_obj_t *screen_now=lv_screen_active();
        static const char *const shown[]={"3.98 V","Constant current","5.01 V","3.71 V",
            "38 °C","USB current","1000 mA","4.20 V","1500 mA"};
        for(unsigned i=0;i<sizeof shown/sizeof *shown;i++)assert(label(screen_now,shown[i]));
        static const panel_text_id_t names[]={TXT_SELF_VBAT,TXT_SELF_PHASE,TXT_SELF_VBUS,
            TXT_SELF_VSYS,TXT_SELF_DIE,TXT_SELF_HELD,TXT_SELF_CHARGER,TXT_SELF_CHARGE_MA,
            TXT_SELF_CHARGE_MV,TXT_SELF_INPUT_MA};
        for(unsigned i=0;i<sizeof names/sizeof *names;i++)assert(label(screen_now,panel_text(names[i])));
        // The charger stands under the power, in a card of its own.
        lv_obj_update_layout(screen_now);
        lv_obj_t *power_card=lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_POWER)));
        lv_obj_t *charger_card=lv_obj_get_parent(label(screen_now,panel_text(TXT_SELF_CHARGER)));
        assert(power_card!=charger_card&&lv_obj_get_y(power_card)<lv_obj_get_y(charger_card));
        assert(lv_obj_get_parent(label(screen_now,"3.98 V"))==power_card);
        assert(lv_obj_get_parent(label(screen_now,"1500 mA"))==charger_card);
        // Nothing holds the charge down, and then all three at once: the
        // longest, which fits its row.
        p.esp_detail.held_current=false;
        panel_ui_update(&p);
        assert(label(screen_now,"Nothing"));
        p.esp_detail.held_heat=p.esp_detail.held_current=p.esp_detail.held_voltage=true;
        panel_ui_update(&p);
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        assert(label(screen_now,"Heat, USB current, USB voltage"));
        // Each phase by its name, in the order of the chip.
        for(int phase=0;phase<=5;phase++){
            p.esp_detail.phase=phase;
            panel_ui_update(&p);
            assert(label(screen_now,panel_text((panel_text_id_t)(TXT_PHASE_TRICKLE+phase))));
        }
        // What the chip did not give is "--": no input, no reading of the
        // die, no cell.
        p.esp_detail.vbus_mv=-1;p.esp_detail.die_c=PANEL_NO_DEGREES;p.esp_detail.phase=-1;
        p.esp_detail.vbat_mv=-1;
        panel_ui_update(&p);
        assert(!label(screen_now,"5.01 V")&&!label(screen_now,"38 °C")&&!label(screen_now,"3.98 V"));
        assert(!label(screen_now,panel_text(TXT_PHASE_DONE)));
        assert(label(screen_now,"3.71 V"));
        // A chip that never answered: every row of it a dash, and no reason
        // for a hold it cannot know.
        p.esp_supply=PANEL_SUPPLY_UNKNOWN;
        p.esp_detail=(panel_power_detail_t){.vbat_mv=-1,.vbus_mv=-1,.vsys_mv=-1,
            .die_c=PANEL_NO_DEGREES,.phase=-1,.charge_ma=-1,.charge_mv=-1,.input_ma=-1};
        panel_ui_update(&p);
        assert(!label(screen_now,"Nothing")&&!label(screen_now,"1000 mA")&&!label(screen_now,"3.71 V"));
        // German, with the longest reason in its row.
        panel_settings_t german={.brightness=70,.sound_volume=30,.language=PANEL_GERMAN};
        panel_ui_create(action,setting,sound,&german);
        p.esp_supply=PANEL_SUPPLY_BATTERY;
        p.esp_detail=(panel_power_detail_t){.vbat_mv=3984,.vbus_mv=5011,.vsys_mv=3714,
            .die_c=38,.phase=3,.held_heat=true,.held_current=true,.held_voltage=true,
            .charge_ma=1000,.charge_mv=4200,.input_ma=1500};
        panel_ui_update(&p);
        panel_ui_self_open();
        screen_now=lv_screen_active();
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        assert(label(screen_now,"Hitze, USB-Strom, USB-Spannung"));
        assert(label(screen_now,"Konstantspannung")&&label(screen_now,"LADEGERÄT"));
        assert(label(screen_now,"PMU-Temperatur")&&label(screen_now,"Ladeschluss"));
        assert(complaints==0);
        panel_ui_create(action,setting,sound,&english);
    }

    // The fifth page: the load, the memory and the clock of the card, and
    // the history of the temperatures and the power under them.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        // The choice of the junction for the tile of the card, which the
        // curve of the card follows.
        panel_settings_t chosen=english;chosen.gpu_sensor=panel_sensor_key("amdgpu/junction");
        panel_history_reset(&history);
        panel_ui_history_use(&history);
        panel_ui_create(action,setting,sound,&chosen);
        lv_obj_t *screen_now=lv_screen_active();
        lv_obj_t *band_now=find_band(screen_now);
        assert(band_now);
        lv_obj_t *page=lv_obj_get_child(band_now,4);
        lv_obj_update_layout(screen_now);
        lv_obj_scroll_to_view(page,LV_ANIM_OFF);
        lv_obj_update_layout(screen_now);
        assert(strcmp(panel_ui_where(),"the card")==0);
        panel_state_t g=base();
        g.gpu_load=87;g.gpu_mhz=2450;g.gpu_mhz_max=2970;
        g.vram_used=10522460160ULL;g.vram_total=17163091968ULL;
        panel_ui_update(&g);
        const char *names[3]={"GPU load","VRAM","GPU clock"},*values[3]={"87 %","9.8 / 16.0 GB","2450 MHz"};
        for(int i=0;i<3;i++)assert(label(page,names[i])&&label(page,values[i]));
        // Each bar as long as its share: 87 of 100, 9.8 of 16.0 GB, and 2450
        // of the 2970 MHz of the highest level of the clock. The three are
        // one length with one gap between them, as far from each side of
        // the card. The name and the value of each stand in the middle
        // over it.
        lv_obj_update_layout(screen_now);
        lv_obj_t *gpu_card=lv_obj_get_parent(label(page,"87 %"));
        const uint64_t share[3][2]={{87,100},{10522460160ULL,17163091968ULL},{2450,2970}};
        lv_area_t inside,at[3];
        lv_obj_get_content_coords(gpu_card,&inside);
        int bars=0;
        for(unsigned i=0;i<lv_obj_get_child_count(gpu_card);i++){
            lv_obj_t *track=lv_obj_get_child(gpu_card,i);
            if(lv_obj_get_height(track)!=8||lv_obj_get_child_count(track)!=1)continue;
            assert(bars<3&&!lv_obj_has_flag(track,LV_OBJ_FLAG_HIDDEN));
            int32_t full=lv_obj_get_width(track),filled=lv_obj_get_width(lv_obj_get_child(track,0));
            assert(filled==(int32_t)(full*share[bars][0]/share[bars][1]));
            lv_obj_get_coords(track,&at[bars]);
            lv_obj_t *over[2]={label(page,names[bars]),label(page,values[bars])};
            for(int k=0;k<2;k++){
                assert(lv_obj_get_style_text_align(over[k],0)==LV_TEXT_ALIGN_CENTER);
                assert(abs(middle_of(over[k])-middle_of(track))<=1);
            }
            bars++;
        }
        assert(bars==3);
        assert(lv_area_get_width(&at[0])==lv_area_get_width(&at[1])&&
               lv_area_get_width(&at[1])==lv_area_get_width(&at[2]));
        assert(at[1].x1-at[0].x2==at[2].x1-at[1].x2);
        assert(at[0].x1-inside.x1==inside.x2-at[2].x2);
        // A clock past its highest level fills its bar, and no more.
        g.gpu_mhz=3100;
        panel_ui_update(&g);
        lv_obj_update_layout(screen_now);
        lv_obj_t *clock_track=lv_obj_get_child(gpu_card,-1);
        assert(lv_obj_get_width(lv_obj_get_child(clock_track,0))==lv_obj_get_width(clock_track));
        // A service older than this firmware sends no highest level: the
        // clock, and no bar under it.
        g.gpu_mhz_max=-1;
        panel_ui_update(&g);
        assert(label(page,"3100 MHz")&&lv_obj_has_flag(clock_track,LV_OBJ_FLAG_HIDDEN));
        // The longest of each fits its room, with no dots: a full card, the
        // memory of a card of 24 GB, and the widest clock of four digits.
        // Each stays clear of the next and inside the card.
        int widest_mhz=1000;
        lv_coord_t widest=0;
        for(int mhz=1000;mhz<=9999;mhz++){
            char said[16];
            snprintf(said,sizeof said,"%d MHz",mhz);
            lv_point_t size;
            lv_text_get_size(&size,said,&panel_font_24,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
            if(size.x>widest){widest=size.x;widest_mhz=mhz;}
        }
        g.gpu_load=100;g.gpu_mhz=widest_mhz;g.gpu_mhz_max=widest_mhz;
        g.vram_used=25662623334ULL;g.vram_total=25769803776ULL;
        panel_ui_update(&g);
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        char clock_said[16];
        snprintf(clock_said,sizeof clock_said,"%d MHz",widest_mhz);
        const char *longest[]={"100 %","23.9 / 24.0 GB",clock_said};
        int32_t end=inside.x1+8-6;
        for(int i=0;i<3;i++){
            lv_obj_t *value=label(page,longest[i]);
            assert(value);
            lv_point_t size;
            lv_text_get_size(&size,longest[i],&panel_font_24,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
            assert(size.x<=lv_obj_get_width(value));
            int32_t start=middle_of(value)-size.x/2;
            assert(start>=end+6);
            end=start+size.x;
        }
        assert(end<=inside.x2-8);
        // What the service did not send is "--", and so is all of it while
        // the PC is gone; the bars go.
        g.gpu_load=-1;g.gpu_mhz=-1;g.vram_used=0;g.vram_total=0;
        panel_ui_update(&g);
        unsigned dashes=0;
        for(unsigned i=0;i<lv_obj_get_child_count(gpu_card);i++){
            lv_obj_t *o=lv_obj_get_child(gpu_card,i);
            if(lv_obj_check_type(o,&lv_label_class)&&strcmp(lv_label_get_text(o),"--")==0)dashes++;
            if(lv_obj_get_height(o)==8)assert(lv_obj_has_flag(o,LV_OBJ_FLAG_HIDDEN));
        }
        assert(dashes==3);
        g.gpu_load=87;g.gpu_mhz=2450;g.vram_used=10522460160ULL;g.vram_total=17163091968ULL;
        g.online=false;
        panel_ui_update(&g);
        assert(!label(page,"87 %")&&!label(page,"2450 MHz")&&!label(page,"9.8 / 16.0 GB"));
        g.online=true;
        // No history yet: a note in the middle, and no scale.
        panel_ui_update(&g);
        assert(label(page,"No readings yet"));
        assert(!label(page,"0 W"));
        // The curve moves on without a new state: a PC that is gone sends
        // none, and its gaps still move the time. So the screen draws a
        // new point when it is handed the state it already has.
        {
            panel_state_t fed=g;
            for(uint32_t at=0;at<=10000;at+=1000){
                if(at%3000==0)fed.answers++;
                if(panel_history_due(&history,at))panel_ui_history_tick(&fed,at);
            }
            assert(history.count==2);
            panel_ui_update(&g);
            assert(!label(page,"No readings yet")&&label(page,"0 W"));
            panel_history_reset(&history);
            panel_ui_history_use(&history);
            panel_ui_update(&g);
            assert(label(page,"No readings yet"));
        }
        // A minute of answers every three seconds: twelve points, with the
        // reading of the sensor of each tile.
        static const panel_sensor_t cpu_list[]={{"k10temp/Tctl","Tctl",50},{"k10temp/Tccd1","CCD 1",47}};
        static const panel_sensor_t gpu_list[]={{"amdgpu/edge","Edge",56},{"amdgpu/junction","Junction (Hotspot)",68}};
        memcpy(g.cpu_sensors,cpu_list,sizeof cpu_list);g.cpu_sensor_count=2;
        memcpy(g.gpu_sensors,gpu_list,sizeof gpu_list);g.gpu_sensor_count=2;
        g.cpu_temp=50;g.gpu_temp=56;g.gpu_watts=245;
        uint32_t now=0;
        for(;now<=60000;now+=1000){
            if(now%3000==0)g.answers++;
            if(panel_history_due(&history,now))panel_ui_history_tick(&g,now);
        }
        assert(history.count==12);
        int last=(history.next+PANEL_HISTORY_POINTS-1)%PANEL_HISTORY_POINTS;
        assert(history.points[PANEL_HISTORY_CPU][last]==50);
        assert(history.points[PANEL_HISTORY_GPU][last]==68);
        assert(history.points[PANEL_HISTORY_WATTS][last]==245);
        panel_ui_update(&g);
        assert(!label(page,"No readings yet"));
        // The scale: tens of degrees around 50 to 68, and watts from nought
        // with room above 245.
        assert(label(page,"80 °C")&&label(page,"40 °C"));
        assert(label(page,"300 W")&&label(page,"0 W"));
        // A PC that is gone sends nothing new, and its steps are gaps, not
        // the last reading again.
        g.online=false;
        for(;now<=70000;now+=1000)
            if(panel_history_due(&history,now))panel_ui_history_tick(&g,now);
        last=(history.next+PANEL_HISTORY_POINTS-1)%PANEL_HISTORY_POINTS;
        assert(history.count==14&&history.points[PANEL_HISTORY_CPU][last]==PANEL_HISTORY_GAP);
        g.online=true;
        panel_ui_update(&g);
        // The window: the 30 minutes of the history, and no button that
        // chooses another. The buttons of the card are the three of the fan.
        assert(label(page,"-30 min"));
        lv_obj_t *history_card=lv_obj_get_parent(label(page,"-30 min"));
        lv_obj_t *chart=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(history_card);i++){
            lv_obj_t *o=lv_obj_get_child(history_card,i);
            assert(!lv_obj_check_type(o,&lv_button_class)||image_of(o,&icon_snowflake)||
                   image_of(o,&icon_fan_off)||
                   strcmp(lv_label_get_text(lv_obj_get_child(o,0)),panel_text(TXT_FAN_AUTO))==0);
            if(lv_obj_check_type(o,&lv_chart_class))chart=o;
        }
        // The chart takes no press, so a swipe over it moves the band.
        assert(chart&&!lv_obj_has_flag(chart,LV_OBJ_FLAG_CLICKABLE));
        assert(lv_chart_get_point_count(chart)==PANEL_HISTORY_DRAWN);
        lv_refr_now(screen);
        assert(complaints==0);
        // A new screen for a new language keeps the history.
        panel_settings_t german=chosen;german.language=PANEL_GERMAN;
        panel_ui_create(action,setting,sound,&german);
        page=lv_obj_get_child(find_band(lv_screen_active()),4);
        assert(label(page,"GPU-Last")&&!label(page,"Verlauf"));
        assert(label(page,"80 °C")&&label(page,"-30 Min"));
        assert(!label(page,"Noch keine Werte"));
        lv_refr_now(screen);
        assert(complaints==0);
        panel_ui_create(action,setting,sound,&english);
    }

    // The card of the history, as the owner drew it. On the left the chart
    // with no title over it, the time under it and the legend under the
    // time: from the left edge of the chart to its right edge, with one gap
    // between a name and the next dot. On the right a column of three
    // squares of one size for the fan of the card: zero RPM, Auto and
    // Cooling Boost, from the top of the card to its foot, there where the
    // PC has LACT with a card. Each sends where to go at a tap and asks
    // nothing first.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        for(int language=0;language<2;language++){
            panel_settings_t in_it=english;in_it.language=language?PANEL_GERMAN:PANEL_ENGLISH;
            panel_ui_create(action,setting,sound,&in_it);
            panel_palette_t colours=panel_palette(in_it.theme,in_it.accent);
            panel_state_t t=base();
            t.pc.gpu_fan_rpm=2950;
            lv_obj_t *page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_CARD);
            lv_obj_t *flake=image_of(page,&icon_snowflake),*crossed=image_of(page,&icon_fan_off);
            assert(flake&&crossed);
            lv_obj_t *button=lv_obj_get_parent(flake),*zero=lv_obj_get_parent(crossed);
            assert(lv_obj_check_type(button,&lv_button_class)&&lv_obj_check_type(zero,&lv_button_class));
            lv_obj_t *card=lv_obj_get_parent(button);
            // A PC without LACT, or a service older than this firmware: no
            // column.
            panel_ui_update(&t);
            assert(lv_obj_has_flag(button,LV_OBJ_FLAG_HIDDEN)&&lv_obj_has_flag(zero,LV_OBJ_FLAG_HIDDEN));
            assert(!label(card,panel_text(TXT_FAN_AUTO)));
            t.boost_here=true;t.answers++;
            panel_ui_update(&t);
            lv_obj_t *auto_caption=label(card,panel_text(TXT_FAN_AUTO));
            assert(auto_caption);
            lv_obj_t *automatic=lv_obj_get_parent(auto_caption);
            assert(lv_obj_check_type(automatic,&lv_button_class));
            lv_obj_t *column[3]={zero,automatic,button};
            for(int i=0;i<3;i++)assert(!lv_obj_has_flag(column[i],LV_OBJ_FLAG_HIDDEN));
            lv_obj_update_layout(page);
            // No title, and no fan reading.
            char speed[24];
            snprintf(speed,sizeof speed,panel_text(TXT_RPM),2950);
            assert(!label(page,"History")&&!label(page,"Verlauf"));
            assert(!label(page,panel_text(TXT_PC_GPU_FAN))&&!label(page,speed));
            // The column: three squares of one size, each with one thing in
            // it, one gap between them, from 10 under the top of the card to
            // 10 over its foot, at its right edge. Nothing else of the card
            // is right of the column.
            lv_area_t at_card,at[3];
            lv_obj_get_coords(card,&at_card);
            for(int i=0;i<3;i++){
                lv_obj_get_coords(column[i],&at[i]);
                assert(lv_area_get_width(&at[i])==lv_area_get_height(&at[i]));
                assert(lv_area_get_width(&at[i])==lv_area_get_width(&at[0])&&at[i].x1==at[0].x1);
                assert(lv_area_get_width(&at[i])>=48&&lv_obj_get_child_count(column[i])==1);
            }
            assert(at[1].y1-at[0].y2==at[2].y1-at[1].y2);
            assert(at[0].y1-at_card.y1==at_card.y2-at[2].y2&&at[0].y1-at_card.y1<=12);
            assert(at_card.x2-at[0].x2<=12);
            lv_obj_t *chart=NULL;
            for(unsigned i=0;i<lv_obj_get_child_count(card);i++){
                lv_obj_t *o=lv_obj_get_child(card,i);
                if(lv_obj_check_type(o,&lv_chart_class))chart=o;
                if(o==zero||o==automatic||o==button)continue;
                lv_area_t at_o;lv_obj_get_coords(o,&at_o);
                assert(at_o.x2<at[0].x1);
            }
            // The chart at the top, the time under it, and the legend under
            // the time, its foot on the foot of the column.
            assert(chart);
            lv_area_t at_chart,at_time;
            lv_obj_get_coords(chart,&at_chart);
            assert(at_chart.y1-at_card.y1<=16);
            char ago[16];
            snprintf(ago,sizeof ago,"-%d %s",PANEL_HISTORY_MINUTES,panel_text(TXT_MINUTES));
            lv_obj_get_coords(label(card,ago),&at_time);
            assert(at_time.y1>at_chart.y2);
            // The legend: three dots and three names in one line, the first
            // dot on the left edge of the chart, the last name to its right
            // edge, and one gap from each name to the next dot.
            const char *names[PANEL_HISTORY_SERIES]={"CPU °C","GPU °C","GPU W"};
            int32_t gaps[PANEL_HISTORY_SERIES]={0},next=at_chart.x1;
            for(int i=0;i<PANEL_HISTORY_SERIES;i++){
                lv_obj_t *name=label(card,names[i]);
                assert(name);
                lv_obj_t *dot=lv_obj_get_child(card,lv_obj_get_index(name)-1);
                lv_area_t at_name,at_dot;
                lv_obj_get_coords(name,&at_name);lv_obj_get_coords(dot,&at_dot);
                assert(lv_area_get_width(&at_dot)==10&&lv_area_get_height(&at_dot)==10);
                assert(at_name.y1>at_time.y2&&at_name.y2==at[2].y2);
                assert(abs((at_dot.y1+at_dot.y2)/2-(at_name.y1+at_name.y2)/2)<=1);
                assert(at_dot.x2<at_name.x1);
                gaps[i]=at_dot.x1-next;
                lv_point_t size;
                lv_text_get_size(&size,names[i],lv_obj_get_style_text_font(name,0),0,0,LV_COORD_MAX,
                                 LV_TEXT_FLAG_NONE);
                assert(size.x<=lv_obj_get_width(name));
                next=at_name.x1+size.x;
            }
            assert(gaps[0]==0&&gaps[1]>=16&&abs(gaps[2]-gaps[1])<=1);
            assert(next==at_chart.x2+1);
            // Of Auto and Cooling Boost one is lit, the profile that the
            // fan runs. Zero RPM is lit while it is on, whatever the
            // profile. Lit is the face and the edge in the accent, and the
            // rest is grey. With no boost the fan runs in Auto. A card
            // without zero RPM has its button dim, and a tap on it sends
            // nothing.
            #define LIT(profile,zero) do{ \
                for(int k=0;k<3;k++){ \
                    bool on=k?k==(profile):(zero); \
                    uint32_t want=on?colours.accent_text:colours.muted; \
                    if(k==1)assert(rgb_of(lv_obj_get_style_text_color(auto_caption,0))==want); \
                    else assert(rgb_of(lv_obj_get_style_image_recolor(k?flake:crossed,0))==want); \
                    assert(rgb_of(lv_obj_get_style_border_color(column[k],0))== \
                           (on?colours.accent_text:colours.edge)); \
                } \
            }while(0)
            LIT(1,false);
            assert(lv_obj_has_state(zero,LV_STATE_DISABLED));
            assert(!lv_obj_has_state(automatic,LV_STATE_DISABLED));
            actions=0;
            lv_obj_send_event(zero,LV_EVENT_CLICKED,NULL);
            assert(actions==0);
            // A card with zero RPM, and it is off: a tap asks for on.
            t.zero_rpm_here=true;t.zero_rpm_on=false;t.answers++;
            panel_ui_update(&t);
            assert(!lv_obj_has_state(zero,LV_STATE_DISABLED));
            LIT(1,false);
            lv_obj_send_event(zero,LV_EVENT_CLICKED,NULL);
            assert(actions==1&&last_action==PANEL_GPU_ZERO_RPM_ON);
            // A tap on the profile that runs asks for nothing.
            lv_obj_send_event(automatic,LV_EVENT_CLICKED,NULL);
            assert(actions==1);
            // The buttons change when the status says so, and not before.
            LIT(1,false);
            t.zero_rpm_on=true;t.answers++;
            panel_ui_update(&t);
            LIT(1,true);
            // The snowflake asks for Cooling Boost at once, with no question.
            lv_obj_send_event(button,LV_EVENT_CLICKED,NULL);
            assert(actions==2&&last_action==PANEL_GPU_BOOST_ON);
            assert(!label(lv_screen_active(),panel_text(TXT_CONFIRM)));
            LIT(1,true);
            t.boost_on=true;t.answers++;
            panel_ui_update(&t);
            LIT(2,true);
            lv_obj_send_event(button,LV_EVENT_CLICKED,NULL);
            assert(actions==2);
            // Zero RPM goes off and on again under the boost, and the boost
            // stays lit.
            lv_obj_send_event(zero,LV_EVENT_CLICKED,NULL);
            assert(actions==3&&last_action==PANEL_GPU_ZERO_RPM_OFF);
            t.zero_rpm_on=false;t.answers++;
            panel_ui_update(&t);
            LIT(2,false);
            // Auto ends the boost.
            lv_obj_send_event(automatic,LV_EVENT_CLICKED,NULL);
            assert(actions==4&&last_action==PANEL_GPU_BOOST_OFF);
            LIT(2,false);
            t.zero_rpm_on=true;t.answers++;
            panel_ui_update(&t);
            // A PC that does not answer: the column stays, grey and dim,
            // and a tap sends nothing.
            t.online=false;
            panel_ui_update(&t);
            for(int i=0;i<3;i++){
                assert(!lv_obj_has_flag(column[i],LV_OBJ_FLAG_HIDDEN));
                assert(lv_obj_has_state(column[i],LV_STATE_DISABLED));
            }
            LIT(3,false);
            for(int i=0;i<3;i++)lv_obj_send_event(column[i],LV_EVENT_CLICKED,NULL);
            assert(actions==4);
            t.online=true;
            panel_ui_update(&t);
            assert(!lv_obj_has_state(button,LV_STATE_DISABLED));
            LIT(2,true);
            t.boost_on=false;t.answers++;
            panel_ui_update(&t);
            LIT(1,true);
            #undef LIT
            // LACT gone from the PC: the column goes with it.
            t.boost_here=false;t.boost_on=false;t.answers++;
            panel_ui_update(&t);
            for(int i=0;i<3;i++)assert(lv_obj_has_flag(column[i],LV_OBJ_FLAG_HIDDEN));
            lv_refr_now(screen);
            assert(complaints==0);
        }
        panel_ui_create(action,setting,sound,&english);
    }

    // The page of the CPU: a button for each profile, the one of the PC lit,
    // and what runs under them. A tap sends the profile at once. The page
    // keeps the choice lit until the status shows it, and takes it back
    // when the PC refuses it or no answer shows it in time.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_ui_cpu_use(cpu_change);
        cpu_changes=0;
        panel_state_t t=base();
        t.cpu_known=t.cpu_here=true;
        strcpy(t.cpu_profile,"balanced");
        t.cpu_offers=(uint8_t)((1u<<PANEL_CPU_PROFILES)-1);
        strcpy(t.cpu_governor,"powersave");strcpy(t.cpu_epp,"balance_performance");
        strcpy(t.cpu_driver,"amd-pstate-epp");
        panel_ui_update(&t);
        lv_obj_t *page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_CPU);
        lv_obj_update_layout(page);
        lv_color_t dark=lv_obj_get_style_bg_color(cpu_button(page,PANEL_CPU_POWERSAVE),0);
        // The profile of the PC lit, and only that one.
        for(int p=0;p<PANEL_CPU_PROFILES;p++){
            assert(cpu_lit_one(cpu_button(page,p),dark)==(p==PANEL_CPU_BALANCED));
            assert(!lv_obj_has_state(cpu_button(page,p),LV_STATE_DISABLED));
        }
        assert(label(page,"powersave / balance_performance"));
        assert(label(page,"Driver: amd-pstate-epp"));
        assert(label(page,panel_text(TXT_CPU_RUNNING)));
        // A tap sends at once and lights its button.
        lv_obj_send_event(cpu_button(page,PANEL_CPU_PERFORMANCE),LV_EVENT_CLICKED,NULL);
        assert(cpu_changes==1&&cpu_last==PANEL_CPU_PERFORMANCE);
        assert(cpu_lit_one(cpu_button(page,PANEL_CPU_PERFORMANCE),dark));
        assert(!cpu_lit_one(cpu_button(page,PANEL_CPU_BALANCED),dark));
        assert(label(page,panel_text(TXT_CHANGE_APPLYING)));
        // The answer, and a status from before it: still the choice.
        t.cpu_replies++;t.cpu_code=200;
        panel_ui_update(&t);
        assert(cpu_lit_one(cpu_button(page,PANEL_CPU_PERFORMANCE),dark));
        assert(label(page,panel_text(TXT_CHANGE_APPLYING)));
        // The status that shows it ends it.
        strcpy(t.cpu_profile,"performance");strcpy(t.cpu_governor,"performance");
        t.answers++;
        panel_ui_update(&t);
        assert(cpu_lit_one(cpu_button(page,PANEL_CPU_PERFORMANCE),dark));
        assert(!label(page,panel_text(TXT_CHANGE_APPLYING)));
        assert(label(page,"performance / balance_performance"));
        // The profile the PC has already is no change.
        lv_obj_send_event(cpu_button(page,PANEL_CPU_PERFORMANCE),LV_EVENT_CLICKED,NULL);
        assert(cpu_changes==1);
        // A refusal takes the choice back, and says why, for each code.
        static const struct{int code;panel_text_id_t why;}refusals[]={
            {403,TXT_CHANGE_NO_RULE},{409,TXT_CHANGE_BUSY},{501,TXT_CPU_NO_MODULE},
            {502,TXT_CHANGE_REFUSED},{0,TXT_CHANGE_REFUSED}};
        for(unsigned i=0;i<sizeof refusals/sizeof *refusals;i++){
            lv_obj_send_event(cpu_button(page,PANEL_CPU_POWERSAVE),LV_EVENT_CLICKED,NULL);
            assert(cpu_last==PANEL_CPU_POWERSAVE);
            t.cpu_replies++;t.cpu_code=refusals[i].code;
            panel_ui_update(&t);
            assert(cpu_lit_one(cpu_button(page,PANEL_CPU_PERFORMANCE),dark));
            assert(!cpu_lit_one(cpu_button(page,PANEL_CPU_POWERSAVE),dark));
            assert(label(page,panel_text(refusals[i].why)));
        }
        // A new choice takes the reason of the last refusal away, so the
        // reason does not come back once the PC shows the new choice.
        lv_obj_send_event(cpu_button(page,PANEL_CPU_BALANCED),LV_EVENT_CLICKED,NULL);
        strcpy(t.cpu_profile,"balanced");t.answers++;
        panel_ui_update(&t);
        assert(cpu_lit_one(cpu_button(page,PANEL_CPU_BALANCED),dark));
        assert(!label(page,panel_text(TXT_CHANGE_REFUSED))&&!label(page,panel_text(TXT_CHANGE_APPLYING)));
        strcpy(t.cpu_profile,"performance");t.answers++;
        panel_ui_update(&t);
        // The reason of a refusal stays for some seconds, and then goes.
        lv_obj_send_event(cpu_button(page,PANEL_CPU_POWERSAVE),LV_EVENT_CLICKED,NULL);
        t.cpu_replies++;t.cpu_code=409;
        panel_ui_update(&t);
        assert(label(page,panel_text(TXT_CHANGE_BUSY)));
        lv_tick_inc(9000);
        t.answers++;
        panel_ui_update(&t);
        assert(!label(page,panel_text(TXT_CHANGE_BUSY)));
        // A choice that no status shows in time goes back too.
        unsigned before=cpu_changes;
        lv_obj_send_event(cpu_button(page,PANEL_CPU_STEAMOS),LV_EVENT_CLICKED,NULL);
        assert(cpu_changes==before+1&&cpu_last==PANEL_CPU_STEAMOS);
        assert(cpu_lit_one(cpu_button(page,PANEL_CPU_STEAMOS),dark));
        lv_tick_inc(21000);
        t.answers++;
        panel_ui_update(&t);
        assert(!cpu_lit_one(cpu_button(page,PANEL_CPU_STEAMOS),dark));
        assert(cpu_lit_one(cpu_button(page,PANEL_CPU_PERFORMANCE),dark));
        // A setting of the control panel that no profile is: nothing lit,
        // and a line that says so.
        strcpy(t.cpu_profile,"custom");strcpy(t.cpu_governor,"powersave");
        strcpy(t.cpu_epp,"balance_power");t.answers++;
        panel_ui_update(&t);
        for(int p=0;p<PANEL_CPU_PROFILES;p++)assert(!cpu_lit_one(cpu_button(page,p),dark));
        assert(label(page,panel_text(TXT_CPU_CUSTOM)));
        // A driver with no preference: no power saving profile to press, and
        // the governor alone under it.
        strcpy(t.cpu_profile,"balanced");strcpy(t.cpu_governor,"schedutil");t.cpu_epp[0]=0;
        t.cpu_offers=(uint8_t)((1u<<PANEL_CPU_BALANCED)|(1u<<PANEL_CPU_PERFORMANCE)|(1u<<PANEL_CPU_STEAMOS));
        t.answers++;
        panel_ui_update(&t);
        assert(lv_obj_has_state(cpu_button(page,PANEL_CPU_POWERSAVE),LV_STATE_DISABLED));
        assert(!lv_obj_has_state(cpu_button(page,PANEL_CPU_BALANCED),LV_STATE_DISABLED));
        assert(label(page,"schedutil"));
        before=cpu_changes;
        lv_obj_send_event(cpu_button(page,PANEL_CPU_POWERSAVE),LV_EVENT_CLICKED,NULL);
        assert(cpu_changes==before);
        // A PC with no power module, and a service older than this
        // firmware: no button to press, and the reason.
        t.cpu_here=false;t.answers++;
        panel_ui_update(&t);
        assert(label(page,panel_text(TXT_CPU_NONE))&&label(page,"--"));
        assert(!label(page,"Driver: amd-pstate-epp"));
        for(int p=0;p<PANEL_CPU_PROFILES;p++){
            assert(lv_obj_has_state(cpu_button(page,p),LV_STATE_DISABLED));
            assert(!cpu_lit_one(cpu_button(page,p),dark));
        }
        lv_obj_send_event(cpu_button(page,PANEL_CPU_PERFORMANCE),LV_EVENT_CLICKED,NULL);
        assert(cpu_changes==before);
        t.cpu_known=false;t.answers++;
        panel_ui_update(&t);
        assert(label(page,panel_text(TXT_PC_TOO_OLD))&&!label(page,panel_text(TXT_CPU_NONE)));
        // A PC that does not answer: no button, no reason.
        t.cpu_known=t.cpu_here=true;t.online=false;
        panel_ui_update(&t);
        assert(label(page,"--")&&!label(page,"Driver: amd-pstate-epp"));
        assert(!label(page,panel_text(TXT_CPU_NONE))&&!label(page,panel_text(TXT_PC_TOO_OLD)));
        for(int p=0;p<PANEL_CPU_PROFILES;p++)
            assert(lv_obj_has_state(cpu_button(page,p),LV_STATE_DISABLED));
        lv_obj_send_event(cpu_button(page,PANEL_CPU_PERFORMANCE),LV_EVENT_CLICKED,NULL);
        assert(cpu_changes==before);
        // A new screen, as after a change of the language, starts with no
        // choice of its own: the status of the PC says what is lit.
        t.online=true;t.answers++;
        panel_ui_update(&t);
        lv_obj_send_event(cpu_button(page,PANEL_CPU_PERFORMANCE),LV_EVENT_CLICKED,NULL);
        assert(cpu_changes==before+1&&label(page,panel_text(TXT_CHANGE_APPLYING)));
        panel_ui_create(action,setting,sound,&english);
        panel_ui_update(&t);
        page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_CPU);
        assert(cpu_lit_one(cpu_button(page,PANEL_CPU_BALANCED),dark));
        assert(!cpu_lit_one(cpu_button(page,PANEL_CPU_PERFORMANCE),dark));
        assert(!label(page,panel_text(TXT_CHANGE_APPLYING)));
        lv_refr_now(screen);
        assert(complaints==0);
        // Each name whole in its button, and each line whole in its card, in
        // both languages.
        for(int language=0;language<2;language++){
            panel_settings_t in_it=english;in_it.language=language?PANEL_GERMAN:PANEL_ENGLISH;
            panel_ui_create(action,setting,sound,&in_it);
            page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_CPU);
            lv_obj_update_layout(page);
            for(int p=0;p<PANEL_CPU_PROFILES;p++){
                lv_obj_t *button=cpu_button(page,p),*caption=lv_obj_get_child(button,0);
                lv_point_t size;
                lv_text_get_size(&size,lv_label_get_text(caption),lv_obj_get_style_text_font(button,0),
                                 0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
                assert(size.x<lv_obj_get_width(button)-8);
                assert(lv_obj_get_height(caption)<=lv_font_get_line_height(lv_obj_get_style_text_font(button,0)));
            }
            static const panel_text_id_t lines[]={TXT_CHANGE_APPLYING,TXT_CHANGE_NO_RULE,TXT_CHANGE_BUSY,
                TXT_CPU_NO_MODULE,TXT_CHANGE_REFUSED,TXT_CPU_CUSTOM,TXT_CPU_NONE,TXT_PC_TOO_OLD};
            for(unsigned i=0;i<sizeof lines/sizeof *lines;i++){
                lv_point_t size;
                lv_text_get_size(&size,panel_text(lines[i]),&panel_font_12,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
                assert(size.x<=428);
            }
            lv_point_t size;
            lv_text_get_size(&size,"performance / balance_performance",&panel_font_18,0,0,LV_COORD_MAX,
                             LV_TEXT_FLAG_NONE);
            assert(size.x<=428);
        }
        panel_ui_create(action,setting,sound,&english);
    }

    // The page of the LED bar: the effect of the PC on the desktop and in
    // the rainbow entry of Steam in Game Mode, with an arrow on each side.
    // A tap shows the next effect at once, and the change goes to main.c
    // after the last tap and its wait. The page shows the choice until an
    // answer shows it, and takes it back when the PC refuses it.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_ui_led_use(led_change);
        led_changes=0;
        panel_state_t t=base();
        t.led_known=t.led_here=true;
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"aurora");
        strcpy(t.led_effect[PANEL_LED_GAME],"fire");
        panel_ui_update(&t);
        lv_obj_t *page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_LED);
        lv_obj_update_layout(page);
        lv_obj_t *desktop=led_card_of(page,PANEL_LED_DESKTOP),*game=led_card_of(page,PANEL_LED_GAME);
        assert(desktop&&game&&desktop!=game);
        assert(lv_obj_get_parent(label(desktop,"Aurora"))==desktop);
        assert(lv_obj_get_parent(label(game,"Fire"))==game);
        // The card of the mode the PC is in says so, and only that one.
        assert(label(desktop,panel_text(TXT_LED_NOW))&&!label(game,panel_text(TXT_LED_NOW)));
        assert(label(game,panel_text(TXT_LED_GAME_WHAT)));
        // Three taps: each shows its effect at once, and none goes yet.
        led_tap(page,PANEL_LED_DESKTOP,LV_SYMBOL_RIGHT);
        assert(label(desktop,"Ooze")&&label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        led_tap(page,PANEL_LED_DESKTOP,LV_SYMBOL_RIGHT);
        led_wait(1000);
        led_tap(page,PANEL_LED_DESKTOP,LV_SYMBOL_RIGHT);
        led_wait(1000);
        assert(led_changes==0&&label(desktop,"CPU and GPU load"));
        // The wait after the last tap: one change, with the last effect.
        led_wait(600);
        assert(led_changes==1&&strcmp(led_last[PANEL_LED_DESKTOP],"load")==0&&!led_last[PANEL_LED_GAME][0]);
        // The answer that it came through, and a status from before it:
        // the page keeps the choice until a status shows it.
        t.led_replies++;t.led_code=200;
        panel_ui_update(&t);
        assert(label(desktop,"CPU and GPU load")&&label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"load");
        t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,"CPU and GPU load")&&!label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        // An effect in the desktop colour says where the colour comes from.
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"breath");
        t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,"Breathing")&&label(desktop,panel_text(TXT_LED_COLOUR_WHAT)));
        // Back round the start of the list: the rainbow of Steam is first.
        led_tap(page,PANEL_LED_GAME,LV_SYMBOL_LEFT);
        led_tap(page,PANEL_LED_GAME,LV_SYMBOL_LEFT);
        led_tap(page,PANEL_LED_GAME,LV_SYMBOL_LEFT);
        led_tap(page,PANEL_LED_GAME,LV_SYMBOL_LEFT);
        assert(label(game,"Mirror"));
        // A refusal takes the choice back, and says why.
        led_wait(1600);
        assert(led_changes==2&&strcmp(led_last[PANEL_LED_GAME],"mirror")==0&&!led_last[PANEL_LED_DESKTOP][0]);
        t.led_replies++;t.led_code=403;
        panel_ui_update(&t);
        assert(label(game,"Fire")&&label(game,panel_text(TXT_CHANGE_NO_RULE)));
        // Each code of a refusal has its own reason.
        static const struct{int code;panel_text_id_t why;}refusals[]={
            {409,TXT_CHANGE_BUSY},{501,TXT_LED_NO_MODULE},{502,TXT_CHANGE_REFUSED},{0,TXT_CHANGE_REFUSED}};
        for(unsigned i=0;i<sizeof refusals/sizeof *refusals;i++){
            led_tap(page,PANEL_LED_GAME,LV_SYMBOL_RIGHT);
            led_wait(1600);
            t.led_replies++;t.led_code=refusals[i].code;
            panel_ui_update(&t);
            assert(label(game,"Fire")&&label(game,panel_text(refusals[i].why)));
        }
        // A choice of the effect that the PC has already is no change.
        unsigned before=led_changes;
        led_tap(page,PANEL_LED_GAME,LV_SYMBOL_RIGHT);
        led_tap(page,PANEL_LED_GAME,LV_SYMBOL_LEFT);
        led_wait(1600);
        assert(led_changes==before&&label(game,"Fire"));
        // A change that no status shows in time goes back as well.
        led_tap(page,PANEL_LED_DESKTOP,LV_SYMBOL_RIGHT);
        led_wait(1600);
        assert(led_changes==before+1&&label(desktop,"Patrol"));
        lv_tick_inc(21000);
        t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,"Breathing")&&!label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        // In Game Mode its card says so.
        t.game_mode=true;
        panel_ui_update(&t);
        assert(!label(desktop,panel_text(TXT_LED_NOW))&&label(game,panel_text(TXT_LED_NOW)));
        // The mirror says what it does on the PC, in place of the usual
        // line of its card.
        strcpy(t.led_effect[PANEL_LED_GAME],"mirror");
        t.led_mirror=(panel_led_mirror_t){.state="running",.fps=15,.cpu=12,.source="1280x800"};
        t.answers++;
        panel_ui_update(&t);
        assert(label(game,"Mirror")&&label(game,"Mirror runs: 15 fps, CPU 1.2 %, 1280x800"));
        // With no profile from the PC, no button of the profile.
        assert(!label(game,"Color Pop"));
        // The profile: a button beside the name of the mirror. A tap opens
        // the menu of the profiles, each with what it does and a mark on
        // the profile of the PC.
        strcpy(t.led_profile[PANEL_LED_GAME],"pop");
        t.answers++;
        panel_ui_update(&t);
        assert(label(game,"Mirror")&&label(game,"Color Pop")&&!profile_box());
        before=led_changes;
        click_in(game,"Color Pop");
        lv_obj_t *box=profile_box();
        assert(box&&strcmp(panel_ui_where(),"the profile of the mirror")==0);
        assert(label(box,"Cinematic")&&label(box,LV_SYMBOL_OK "  Color Pop")&&label(box,"Solid"));
        for(int i=0;i<PANEL_LED_PROFILES;i++)assert(label(box,panel_text(panel_led_profile_what(i))));
        // A second tap on the button opens no second menu.
        uint32_t layers=lv_obj_get_child_count(lv_screen_active());
        click_in(game,"Color Pop");
        assert(lv_obj_get_child_count(lv_screen_active())==layers);
        // A row chooses and closes the menu, and the choice goes to the PC
        // as an effect does.
        click_in(box,"Solid");
        assert(!profile_box()&&strcmp(panel_ui_where(),"the profile of the mirror")!=0);
        assert(label(game,"Solid")&&label(game,panel_text(TXT_CHANGE_APPLYING)));
        led_wait(1600);
        assert(led_changes==before+1&&strcmp(led_last_profile[PANEL_LED_GAME],"solid")==0);
        assert(!led_last[PANEL_LED_GAME][0]&&!led_last_profile[PANEL_LED_DESKTOP][0]);
        strcpy(t.led_profile[PANEL_LED_GAME],"solid");
        t.answers++;
        panel_ui_update(&t);
        assert(label(game,"Solid")&&!label(game,panel_text(TXT_CHANGE_APPLYING)));
        // The profile of the PC is no change, and neither is a tap beside
        // the rows, which closes the menu.
        click_in(game,"Solid");
        click_in(profile_box(),LV_SYMBOL_OK "  Solid");
        assert(!profile_box()&&!label(game,panel_text(TXT_CHANGE_APPLYING)));
        click_in(game,"Solid");
        lv_obj_send_event(lv_obj_get_parent(profile_box()),LV_EVENT_CLICKED,NULL);
        assert(!profile_box());
        led_wait(1600);
        assert(led_changes==before+1&&label(game,"Solid"));
        // A profile that the PC takes from somewhere else moves the mark of
        // the open menu.
        click_in(game,"Solid");
        strcpy(t.led_profile[PANEL_LED_GAME],"cinematic");
        t.answers++;
        panel_ui_update(&t);
        box=profile_box();
        assert(box&&label(box,LV_SYMBOL_OK "  Cinematic")&&label(box,"Solid")&&!label(box,LV_SYMBOL_OK "  Solid"));
        // A refusal takes the profile back, and says why.
        click_in(box,"Color Pop");
        led_wait(1600);
        assert(led_changes==before+2&&strcmp(led_last_profile[PANEL_LED_GAME],"pop")==0);
        t.led_replies++;t.led_code=403;
        panel_ui_update(&t);
        assert(label(game,"Cinematic")&&label(game,panel_text(TXT_CHANGE_NO_RULE)));
        lv_tick_inc(9000);
        t.answers++;
        panel_ui_update(&t);
        // A service with no profiles: no button, and the open menu closes.
        click_in(game,"Cinematic");
        assert(profile_box());
        t.led_profile[PANEL_LED_GAME][0]=0;
        t.answers++;
        panel_ui_update(&t);
        assert(!profile_box());
        assert(label(game,"Mirror")&&!label(game,"Solid")&&!label(game,"Cinematic"));
        strcpy(t.led_mirror.state,"busy");strcpy(t.led_mirror.detail,"steam");
        t.answers++;
        panel_ui_update(&t);
        assert(label(game,"Mirror paused: steam reads the screen"));
        // A service older than this firmware sends no status.
        t.led_mirror.state[0]=0;
        t.answers++;
        panel_ui_update(&t);
        assert(label(game,panel_text(TXT_LED_GAME_WHAT)));
        // A different effect never shows the status of the mirror.
        strcpy(t.led_mirror.state,"failed");
        strcpy(t.led_effect[PANEL_LED_GAME],"fire");
        t.answers++;
        panel_ui_update(&t);
        assert(label(game,panel_text(TXT_LED_GAME_WHAT))&&!label(game,"Mirror error: steam"));
        // The mirror of the desktop. Its card has the button of the profile
        // too, and the line of the mirror until the mirror runs: a person
        // must allow the share of the screen on the PC. The line is on the
        // card of the mode that the PC is in.
        t.game_mode=false;t.led_look=true;t.led_brightness=128;
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"mirror");
        strcpy(t.led_effect[PANEL_LED_GAME],"mirror");
        // Each mode has its own profile.
        strcpy(t.led_profile[PANEL_LED_DESKTOP],"pop");
        strcpy(t.led_profile[PANEL_LED_GAME],"cinematic");
        t.led_mirror=(panel_led_mirror_t){.state="asking"};
        t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,"Mirror")&&label(desktop,"Color Pop"));
        assert(label(desktop,panel_text(TXT_MIRROR_ASKING)));
        assert(!label(desktop,look_words_for(TXT_COLOUR_RED,50,false)));
        assert(label(game,"Cinematic")&&label(game,panel_text(TXT_LED_GAME_WHAT)));
        assert(!label(game,panel_text(TXT_MIRROR_ASKING)));
        static const struct { const char *state; panel_text_id_t line; } desktop_lines[]={
            {"refused",TXT_MIRROR_REFUSED},{"no-portal",TXT_MIRROR_NO_PORTAL},
            {"starting",TXT_MIRROR_STARTING}};
        for(unsigned i=0;i<sizeof desktop_lines/sizeof desktop_lines[0];i++){
            strcpy(t.led_mirror.state,desktop_lines[i].state);
            t.answers++;
            panel_ui_update(&t);
            assert(label(desktop,panel_text(desktop_lines[i].line)));
        }
        // A mirror that runs gives the line to the button of the brightness.
        t.led_mirror=(panel_led_mirror_t){.state="running",.fps=15,.cpu=9,.source="2194x1234"};
        t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,look_words_for(TXT_COLOUR_RED,50,false)));
        assert(!label(desktop,"Mirror runs: 15 fps, CPU 0.9 %, 2194x1234"));
        // The menu of each card marks the profile of its own mode.
        click_in(game,"Cinematic");
        assert(label(profile_box(),LV_SYMBOL_OK "  Cinematic"));
        // A new answer of the PC keeps the mark of the card of the menu.
        t.answers++;
        panel_ui_update(&t);
        assert(label(profile_box(),LV_SYMBOL_OK "  Cinematic"));
        assert(!label(profile_box(),LV_SYMBOL_OK "  Color Pop"));
        lv_obj_send_event(lv_obj_get_parent(profile_box()),LV_EVENT_CLICKED,NULL);
        // A profile chosen on the card of the desktop: that card says that
        // it goes, and only its own button shows it. One change goes, for
        // the profile of the desktop alone.
        before=led_changes;
        click_in(desktop,"Color Pop");
        assert(label(profile_box(),LV_SYMBOL_OK "  Color Pop"));
        t.answers++;
        panel_ui_update(&t);
        assert(label(profile_box(),LV_SYMBOL_OK "  Color Pop"));
        assert(!label(profile_box(),LV_SYMBOL_OK "  Cinematic"));
        click_in(profile_box(),"Solid");
        assert(label(desktop,panel_text(TXT_CHANGE_APPLYING))&&!label(game,panel_text(TXT_CHANGE_APPLYING)));
        assert(label(desktop,"Solid")&&label(game,"Cinematic"));
        led_wait(1600);
        assert(led_changes==before+1&&strcmp(led_last_profile[PANEL_LED_DESKTOP],"solid")==0);
        assert(!led_last_profile[PANEL_LED_GAME][0]);
        // Its refusal goes to the same card.
        t.led_replies++;t.led_code=403;
        panel_ui_update(&t);
        assert(label(desktop,panel_text(TXT_CHANGE_NO_RULE))&&!label(game,panel_text(TXT_CHANGE_NO_RULE)));
        assert(label(desktop,"Color Pop")&&label(game,"Cinematic"));
        lv_tick_inc(9000);
        // The profile of Game Mode, chosen on its card, goes alone too.
        t.answers++;
        panel_ui_update(&t);
        before=led_changes;
        click_in(game,"Cinematic");
        click_in(profile_box(),"Solid");
        assert(label(game,"Solid")&&label(desktop,"Color Pop"));
        led_wait(1600);
        assert(led_changes==before+1&&strcmp(led_last_profile[PANEL_LED_GAME],"solid")==0);
        assert(!led_last_profile[PANEL_LED_DESKTOP][0]);
        strcpy(t.led_profile[PANEL_LED_GAME],"solid");
        t.answers++;
        panel_ui_update(&t);
        // In Game Mode the line goes to the card of Game Mode, and the card
        // of the desktop has the button of the brightness.
        t.game_mode=true;
        t.led_mirror=(panel_led_mirror_t){.state="waiting"};
        t.answers++;
        panel_ui_update(&t);
        assert(label(game,panel_text(TXT_MIRROR_WAITING))&&!label(desktop,panel_text(TXT_MIRROR_WAITING)));
        assert(label(desktop,look_words_for(TXT_COLOUR_RED,50,false)));
        // A different scene of the desktop has no button of the profile.
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"aurora");
        t.answers++;
        panel_ui_update(&t);
        assert(!label(desktop,"Color Pop")&&label(game,"Solid"));
        strcpy(t.led_effect[PANEL_LED_GAME],"fire");t.led_look=false;
        t.led_profile[PANEL_LED_DESKTOP][0]=0;t.led_profile[PANEL_LED_GAME][0]=0;
        t.answers++;
        panel_ui_update(&t);
        // A PC with no LED module: no effect, no arrow to press, and the
        // reason once.
        t.led_here=false;t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,panel_text(TXT_LED_NONE))&&!label(game,panel_text(TXT_LED_NONE)));
        for(int m=0;m<PANEL_LED_MODES;m++){
            lv_obj_t *card=led_card_of(page,(panel_led_mode_t)m);
            assert(lv_obj_has_state(button_with(card,LV_SYMBOL_LEFT),LV_STATE_DISABLED));
            assert(lv_obj_has_state(button_with(card,LV_SYMBOL_RIGHT),LV_STATE_DISABLED));
        }
        before=led_changes;
        led_tap(page,PANEL_LED_DESKTOP,LV_SYMBOL_RIGHT);
        led_wait(1600);
        assert(led_changes==before);
        // A service of the PC older than this firmware says nothing about
        // an LED bar at all, and the page says what to do about that.
        t.led_known=false;t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,panel_text(TXT_PC_TOO_OLD))&&!label(desktop,panel_text(TXT_LED_NONE)));
        assert(lv_obj_has_state(button_with(desktop,LV_SYMBOL_RIGHT),LV_STATE_DISABLED));
        t.led_known=true;
        // A PC that does not answer: a dash, and nothing to press.
        t.led_here=true;t.online=false;
        panel_ui_update(&t);
        assert(!label(desktop,"Breathing")&&!label(desktop,panel_text(TXT_LED_NONE)));
        assert(lv_obj_has_state(button_with(desktop,LV_SYMBOL_RIGHT),LV_STATE_DISABLED));
        assert(!label(desktop,panel_text(TXT_LED_NOW))&&!label(game,panel_text(TXT_LED_NOW)));
        // A key of a later service has no name here, and shows as it is.
        t.online=true;strcpy(t.led_effect[PANEL_LED_DESKTOP],"plasma");
        panel_ui_update(&t);
        assert(label(desktop,"plasma"));
        lv_refr_now(screen);
        assert(complaints==0);
        // Every effect of each list, in each language, whole between its
        // arrows, and each line under it whole.
        for(int language=0;language<2;language++){
            panel_settings_t in_it=english;in_it.language=language?PANEL_GERMAN:PANEL_ENGLISH;
            panel_ui_create(action,setting,sound,&in_it);
            page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_LED);
            for(int m=0;m<PANEL_LED_MODES;m++)
                for(int i=0;i<panel_led_count((panel_led_mode_t)m);i++){
                    strcpy(t.led_effect[m],panel_led_key((panel_led_mode_t)m,i));
                    t.answers++;
                    panel_ui_update(&t);
                    lv_obj_update_layout(page);
                    lv_obj_t *card=led_card_of(page,(panel_led_mode_t)m);
                    lv_obj_t *name=label(card,panel_text(panel_led_name((panel_led_mode_t)m,i)));
                    assert(name);
                    lv_point_t size;
                    lv_text_get_size(&size,lv_label_get_text(name),lv_obj_get_style_text_font(name,0),
                                     0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
                    assert(size.x<=lv_obj_get_width(name));
                    lv_area_t at,left,right;
                    lv_obj_get_coords(name,&at);
                    lv_obj_get_coords(button_with(card,LV_SYMBOL_LEFT),&left);
                    lv_obj_get_coords(button_with(card,LV_SYMBOL_RIGHT),&right);
                    assert(at.x1>left.x2&&at.x2<right.x1);
                }
            static const panel_text_id_t notes[]={TXT_LED_GAME_WHAT,TXT_LED_COLOUR_WHAT,TXT_CHANGE_APPLYING,
                TXT_LED_NONE,TXT_PC_TOO_OLD,TXT_CHANGE_NO_RULE,TXT_CHANGE_BUSY,TXT_LED_NO_MODULE,TXT_CHANGE_REFUSED,
                TXT_LED_DESKTOP,TXT_LED_GAME};
            for(unsigned i=0;i<sizeof notes/sizeof *notes;i++){
                lv_point_t size;
                lv_text_get_size(&size,panel_text(notes[i]),&panel_font_12,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
                assert(size.x<=430);
                lv_text_get_size(&size,panel_text(notes[i]),&panel_font_14,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
                assert(notes[i]!=TXT_LED_DESKTOP&&notes[i]!=TXT_LED_GAME?true:size.x<=290);
            }
        }
        panel_ui_create(action,setting,sound,&english);
    }

    // The colour and the brightness of the desktop scenes: a button under
    // the effect of the desktop, and a layer with the nine colours and a
    // slider. A choice goes after the wait with the effects, and the page
    // shows it until a status does, as it does for an effect.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_ui_led_use(led_change);
        led_changes=0;
        panel_state_t t=base();
        t.led_known=t.led_here=t.led_look=true;
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"breath");
        strcpy(t.led_effect[PANEL_LED_GAME],"fire");
        strcpy(t.led_colour,"#ff0000");t.led_brightness=128;
        panel_ui_update(&t);
        lv_obj_t *page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_LED);
        lv_obj_update_layout(page);
        lv_obj_t *desktop=led_card_of(page,PANEL_LED_DESKTOP),*game=led_card_of(page,PANEL_LED_GAME);
        // The button says the colour and the brightness in place of the line
        // that said where the colour comes from. The card of Game Mode has
        // none: Steam sets both there.
        char red[48];
        snprintf(red,sizeof red,"%s",look_words_for(TXT_COLOUR_RED,50,true));
        assert(label(desktop,red)&&!label(desktop,panel_text(TXT_LED_COLOUR_WHAT)));
        assert(!label(game,red)&&label(game,panel_text(TXT_LED_GAME_WHAT)));
        // Across the card under the arrows, as wide as the row of the
        // arrows, with room under it: a button that sat at the edge of the
        // card looked like no part of it. The dot and the words stand
        // together in its middle.
        {
            lv_obj_t *look=lv_obj_get_parent(label(desktop,red));
            lv_area_t at,card,left,right,dot,words;
            lv_obj_get_coords(look,&at);lv_obj_get_coords(desktop,&card);
            lv_obj_get_coords(button_with(desktop,LV_SYMBOL_LEFT),&left);
            lv_obj_get_coords(button_with(desktop,LV_SYMBOL_RIGHT),&right);
            assert(at.x1==left.x1&&at.x2==right.x2&&at.y1>left.y2);
            assert(card.y2-at.y2>=10);
            // And the two cards still one above the other on the page.
            lv_area_t other,whole;
            lv_obj_get_coords(game,&other);lv_obj_get_coords(page,&whole);
            assert(card.y2<other.y1&&other.y2<=whole.y2);
            assert(lv_obj_get_style_radius(look,0)==lv_obj_get_style_radius(button_with(desktop,LV_SYMBOL_LEFT),0));
            lv_obj_get_coords(look_dot_of(look),&dot);lv_obj_get_coords(label(desktop,red),&words);
            int32_t before=dot.x1-at.x1,after=at.x2-words.x2;
            assert(before-after<=2&&after-before<=2);
            lv_point_t size;
            lv_text_get_size(&size,red,&panel_font_16,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
            assert(lv_obj_get_width(label(desktop,red))>=size.x);
        }
        // A tap opens the layer: the nine colours, red chosen, the slider at
        // the brightness of the PC.
        assert(!look_layer_of());
        click_in(desktop,red);
        lv_obj_t *layer=look_layer_of();
        assert(layer&&label(layer,panel_text(TXT_LED_COLOUR))&&label(layer,"50 %"));
        for(int i=0;i<PANEL_LED_COLOURS;i++){
            assert(swatch(layer,i));
            assert(swatch_chosen(layer,i)==(i==0));
        }
        {
            int skip=0;
            assert(lv_slider_get_value(slider_at_place(layer,&skip))==50);
        }
        // A colour is chosen at once, and goes after the wait, alone.
        lv_obj_send_event(swatch(layer,5),LV_EVENT_CLICKED,NULL);
        assert(swatch_chosen(layer,5)&&!swatch_chosen(layer,0));
        assert(led_changes==0&&label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        led_wait(1600);
        assert(led_changes==1&&strcmp(led_last_colour,"#0000ff")==0&&led_last_brightness<0);
        assert(!led_last[PANEL_LED_DESKTOP][0]&&!led_last[PANEL_LED_GAME][0]);
        // The answer, and a status from before it: still the choice.
        t.led_replies++;t.led_code=200;
        panel_ui_update(&t);
        assert(swatch_chosen(layer,5)&&label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        // The status that shows it ends it.
        strcpy(t.led_colour,"#0000ff");t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,look_words_for(TXT_COLOUR_BLUE,50,true)));
        assert(!label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        // The slider says its per cent while it moves, and sends nothing
        // until the finger is off. Then its brightness goes after the wait.
        {
            int skip=0;
            lv_obj_t *slider=slider_at_place(layer,&skip);
            lv_slider_set_value(slider,70,LV_ANIM_OFF);
            lv_obj_send_event(slider,LV_EVENT_VALUE_CHANGED,NULL);
            assert(label(layer,"70 %"));
            led_wait(1600);
            assert(led_changes==1);
        }
        look_slide(layer,80);
        assert(label(layer,"80 %"));
        led_wait(1600);
        assert(led_changes==2&&led_last_brightness==panel_led_brightness(80)&&!led_last_colour[0]);
        t.led_brightness=panel_led_brightness(80);t.led_replies++;t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,look_words_for(TXT_COLOUR_BLUE,80,true)));
        // A second choice while the first is on its way goes too.
        lv_obj_send_event(swatch(layer,3),LV_EVENT_CLICKED,NULL);
        led_wait(1600);
        assert(led_changes==3&&strcmp(led_last_colour,"#00ff00")==0);
        lv_obj_send_event(swatch(layer,4),LV_EVENT_CLICKED,NULL);
        led_wait(1600);
        assert(led_changes==4&&strcmp(led_last_colour,"#00ffff")==0);
        t.led_replies+=2;strcpy(t.led_colour,"#00ffff");t.answers++;
        panel_ui_update(&t);
        assert(swatch_chosen(layer,4)&&!label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        // Blue again, from the control panel.
        strcpy(t.led_colour,"#0000ff");t.answers++;
        panel_ui_update(&t);
        // Two choices in quick turn go as one change, and a refusal takes
        // both back and says why on the card of the desktop.
        lv_obj_send_event(swatch(layer,3),LV_EVENT_CLICKED,NULL);
        look_slide(layer,30);
        led_wait(1600);
        assert(led_changes==5&&strcmp(led_last_colour,"#00ff00")==0&&led_last_brightness==panel_led_brightness(30));
        t.led_replies++;t.led_code=403;
        panel_ui_update(&t);
        assert(swatch_chosen(layer,5)&&!swatch_chosen(layer,3)&&label(layer,"80 %"));
        {
            int skip=0;
            assert(lv_slider_get_value(slider_at_place(layer,&skip))==80);
        }
        assert(label(desktop,panel_text(TXT_CHANGE_NO_RULE)));
        // A new choice takes the reason away, and the reason does not come
        // back once the PC shows the choice.
        lv_obj_send_event(swatch(layer,8),LV_EVENT_CLICKED,NULL);
        assert(!label(desktop,panel_text(TXT_CHANGE_NO_RULE)));
        led_wait(1600);
        assert(led_changes==6&&strcmp(led_last_colour,"#ffffff")==0);
        t.led_replies++;t.led_code=200;strcpy(t.led_colour,"#ffffff");t.answers++;
        panel_ui_update(&t);
        assert(!label(desktop,panel_text(TXT_CHANGE_NO_RULE)));
        assert(label(desktop,look_words_for(TXT_COLOUR_WHITE,80,true)));
        strcpy(t.led_colour,"#0000ff");t.answers++;
        panel_ui_update(&t);
        // The colour and the brightness of the PC are no change.
        lv_obj_send_event(swatch(layer,5),LV_EVENT_CLICKED,NULL);
        look_slide(layer,80);
        led_wait(1600);
        assert(led_changes==6);
        // A choice that no status shows in time goes back.
        lv_obj_send_event(swatch(layer,1),LV_EVENT_CLICKED,NULL);
        led_wait(1600);
        assert(led_changes==7&&strcmp(led_last_colour,"#ff8000")==0);
        lv_tick_inc(21000);
        t.answers++;
        panel_ui_update(&t);
        assert(swatch_chosen(layer,5)&&!label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        // A brightness too.
        look_slide(layer,60);
        led_wait(1600);
        assert(led_changes==8&&led_last_brightness==panel_led_brightness(60));
        lv_tick_inc(21000);
        t.answers++;
        panel_ui_update(&t);
        assert(label(layer,"80 %")&&!label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        {
            int skip=0;
            assert(lv_slider_get_value(slider_at_place(layer,&skip))==80);
        }
        // Done closes the layer, and so does a tap beside the box.
        click_in(layer,panel_text(TXT_LED_DONE));
        assert(!look_layer_of());
        const char *blue=look_words_for(TXT_COLOUR_BLUE,80,true);
        lv_obj_t *look=lv_obj_get_parent(label(desktop,blue));
        lv_obj_send_event(look,LV_EVENT_CLICKED,NULL);
        layer=look_layer_of();
        assert(layer);
        lv_obj_send_event(layer,LV_EVENT_CLICKED,NULL);
        assert(!look_layer_of());
        // One layer at a time: the choice of a sensor and this one keep
        // each other closed.
        {
            t.cpu_temp=53;t.answers++;
            panel_ui_update(&t);
            lv_obj_t *tile=lv_obj_get_parent(label(lv_screen_active(),"53 °C"));
            lv_obj_send_event(tile,LV_EVENT_CLICKED,NULL);
            lv_obj_t *title=label(lv_screen_active(),panel_text(TXT_CPU_TEMPERATURE));
            assert(title);
            lv_obj_send_event(look,LV_EVENT_CLICKED,NULL);
            assert(!look_layer_of());
            lv_obj_t *menu=title;
            while(lv_obj_get_parent(menu)!=lv_screen_active())menu=lv_obj_get_parent(menu);
            lv_obj_send_event(menu,LV_EVENT_CLICKED,NULL);
            assert(!label(lv_screen_active(),panel_text(TXT_CPU_TEMPERATURE)));
            lv_obj_send_event(look,LV_EVENT_CLICKED,NULL);
            assert(look_layer_of());
            lv_obj_send_event(tile,LV_EVENT_CLICKED,NULL);
            assert(!label(lv_screen_active(),panel_text(TXT_CPU_TEMPERATURE)));
        }
        // A new screen, as after a change of the language, starts with no
        // choice of its own, and with no layer.
        layer=look_layer_of();
        lv_obj_send_event(swatch(layer,2),LV_EVENT_CLICKED,NULL);
        assert(label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        panel_ui_create(action,setting,sound,&english);
        panel_ui_update(&t);
        page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_LED);
        lv_obj_update_layout(page);
        desktop=led_card_of(page,PANEL_LED_DESKTOP);
        assert(!look_layer_of()&&!label(desktop,panel_text(TXT_CHANGE_APPLYING)));
        assert(label(desktop,look_words_for(TXT_COLOUR_BLUE,80,true)));
        led_wait(1600);
        assert(led_changes==8);
        // A scene that makes its own colours has the brightness alone.
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"fire");t.answers++;
        panel_ui_update(&t);
        char level[48];
        snprintf(level,sizeof level,"%s",look_words_for(TXT_COLOUR_OWN,80,false));
        assert(label(desktop,level));
        click_in(desktop,level);
        layer=look_layer_of();
        assert(layer&&!label(layer,panel_text(TXT_LED_COLOUR))&&!swatch(layer,0)&&label(layer,"80 %"));
        // A status with a scene that takes the colour closes that layer:
        // it has no colours to choose.
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"patrol");t.answers++;
        panel_ui_update(&t);
        assert(!look_layer_of()&&label(desktop,look_words_for(TXT_COLOUR_BLUE,80,true)));
        // A scene that uses neither has no button.
        static const char *const plain[]={"steam","off","load"};
        for(unsigned i=0;i<sizeof plain/sizeof *plain;i++){
            strcpy(t.led_effect[PANEL_LED_DESKTOP],plain[i]);t.answers++;
            panel_ui_update(&t);
            assert(!label(desktop,look_words_for(TXT_COLOUR_BLUE,80,true))&&!label(desktop,level));
        }
        // A colour from the file that is not in the list: its own dot, its
        // own name, and no colour chosen in the layer.
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"color");strcpy(t.led_colour,"#25d366");t.answers++;
        panel_ui_update(&t);
        char own[48];
        snprintf(own,sizeof own,"%s",look_words_for(TXT_COLOUR_OWN,80,true));
        assert(label(desktop,own));
        {
            lv_obj_t *dot=look_dot_of(lv_obj_get_parent(label(desktop,own)));
            assert(dot&&!lv_obj_has_flag(dot,LV_OBJ_FLAG_HIDDEN));
            assert(lv_color_eq(lv_obj_get_style_bg_color(dot,0),lv_color_hex(0x25D366)));
        }
        click_in(desktop,own);
        layer=look_layer_of();
        for(int i=0;i<PANEL_LED_COLOURS;i++)assert(!swatch_chosen(layer,i));
        // A PC that goes closes the layer and the button.
        t.online=false;
        panel_ui_update(&t);
        assert(!look_layer_of()&&!label(desktop,own));
        unsigned before=led_changes;
        // A service of the PC older than this firmware: no button, and the
        // line that says where the colour comes from.
        t.online=true;t.led_look=false;t.answers++;
        panel_ui_update(&t);
        assert(!label(desktop,own)&&label(desktop,panel_text(TXT_LED_COLOUR_WHAT)));
        assert(led_changes==before);
        // That line is for a PC that answers.
        t.online=false;
        panel_ui_update(&t);
        assert(!label(desktop,panel_text(TXT_LED_COLOUR_WHAT)));
        t.online=true;
        lv_refr_now(screen);
        assert(complaints==0);
        // The start of setup closes the layer: the screen of setup goes over
        // everything, and a layer under it would come back after it.
        t.led_look=true;t.answers++;
        panel_ui_update(&t);
        click_in(desktop,own);
        assert(look_layer_of());
        t.setup=true;
        panel_ui_update(&t);
        assert(!look_layer_of());
        t.setup=false;
        // A first button with the brightness alone has no dot.
        panel_ui_create(action,setting,sound,&english);
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"fire");t.answers++;
        panel_ui_update(&t);
        page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_LED);
        desktop=led_card_of(page,PANEL_LED_DESKTOP);
        {
            lv_obj_t *words=label(desktop,look_words_for(TXT_COLOUR_OWN,80,false));
            assert(words);
            lv_obj_t *dot=look_dot_of(lv_obj_get_parent(words));
            assert(dot&&lv_obj_has_flag(dot,LV_OBJ_FLAG_HIDDEN));
        }
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"color");
        // Each name whole in its button, and the button whole in the card,
        // for every colour at the widest per cent, in both languages.
        for(int language=0;language<2;language++){
            panel_settings_t in_it=english;in_it.language=language?PANEL_GERMAN:PANEL_ENGLISH;
            panel_ui_create(action,setting,sound,&in_it);
            page=lv_obj_get_child(find_band(lv_screen_active()),PANEL_PAGE_LED);
            desktop=led_card_of(page,PANEL_LED_DESKTOP);
            t.led_look=true;t.led_brightness=255;
            for(int i=-1;i<PANEL_LED_COLOURS;i++){
                strcpy(t.led_colour,i<0?"#25d366":panel_led_colour(i));t.answers++;
                panel_ui_update(&t);
                lv_obj_update_layout(page);
                lv_obj_t *words=label(desktop,look_words_for(panel_led_colour_name(i),100,true));
                assert(words);
                lv_area_t at,card;
                lv_obj_get_coords(lv_obj_get_parent(words),&at);lv_obj_get_coords(desktop,&card);
                assert(at.x1>card.x1+8&&at.x2<card.x2-8);
                lv_point_t size;
                lv_text_get_size(&size,lv_label_get_text(words),&panel_font_16,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
                assert(lv_obj_get_width(words)>=size.x);
            }
            click_in(desktop,look_words_for(TXT_COLOUR_WHITE,100,true));
            layer=look_layer_of();
            lv_obj_update_layout(layer);
            for(int i=0;i<PANEL_LED_COLOURS;i++){
                lv_obj_t *name=label(layer,panel_text(panel_led_colour_name(i)));
                lv_point_t size;
                lv_text_get_size(&size,lv_label_get_text(name),&panel_font_16,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
                assert(size.x<=lv_obj_get_width(name));
                lv_area_t at,inside;
                lv_obj_get_coords(name,&at);lv_obj_get_coords(swatch(layer,i),&inside);
                assert(at.x2<inside.x2&&at.y2<inside.y2);
            }
            lv_point_t size;
            lv_text_get_size(&size,panel_text(TXT_LED_DESKTOP),&panel_font_20,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
            assert(size.x<=400);
        }
        panel_ui_create(action,setting,sound,&english);
    }

    // The colours of the screen: a dark theme and a light one, and an
    // accent in eight colours. A card in the settings under the display:
    // the two themes are two buttons, the chosen one lit, and the accents a
    // row of round buttons, the chosen one with a tick and a ring. A tap
    // saves the choice at once and builds the screen again in its colours,
    // and the settings stay open as far down as they were.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_state_t t=base();
        panel_ui_update(&t);
        panel_ui_settings_open();
        lv_obj_update_layout(lv_screen_active());
        lv_obj_t *card=appearance_card();
        // Nothing chosen: the dark theme in its blue, the panel as it was.
        panel_palette_t dark=panel_palette(PANEL_THEME_DARK,PANEL_ACCENT_BLUE);
        assert(dark.bg==0x0C1721&&dark.accent==0x49A8F7);
        assert(rgb_of(lv_obj_get_style_bg_color(lv_screen_active(),0))==dark.bg);
        lv_obj_t *dark_button=button_with(card,panel_text(TXT_THEME_DARK));
        lv_obj_t *light_button=button_with(card,panel_text(TXT_THEME_LIGHT));
        assert(dark_button&&light_button);
        assert(rgb_of(lv_obj_get_style_bg_color(dark_button,0))==dark.accent);
        assert(rgb_of(lv_obj_get_style_bg_color(light_button,0))==dark.button);
        assert(label(card,panel_text(TXT_COLOUR_BLUE)));
        // Eight round buttons in a row inside the card, each in the tone of
        // its accent in this theme. The gap between two belongs to the
        // touch of both, so a finger between them still finds one.
        lv_area_t inside;
        lv_obj_get_coords(card,&inside);
        lv_area_t touch_before={0};
        for(int a=0;a<PANEL_ACCENTS;a++){
            lv_obj_t *b=accent_button(card,a);
            assert(b&&lv_obj_get_width(b)>=38);
            lv_area_t at,touch;
            lv_obj_get_coords(b,&at);lv_obj_get_click_area(b,&touch);
            assert(at.x1>inside.x1&&at.x2<inside.x2&&at.y1>inside.y1&&at.y2<inside.y2);
            if(a){
                lv_area_t before_at;
                lv_obj_get_coords(accent_button(card,a-1),&before_at);
                assert(at.x1>before_at.x2);
                assert(touch.x1<=touch_before.x2+1);
            }
            touch_before=touch;
            assert(rgb_of(lv_obj_get_style_bg_color(b,0))==panel_palette(PANEL_THEME_DARK,a).accent);
            bool chosen=a==PANEL_ACCENT_BLUE;
            assert((label(b,LV_SYMBOL_OK)!=NULL)==chosen);
            assert((lv_obj_get_style_outline_width(b,0)>0)==chosen);
        }
        assert(!accent_button(card,PANEL_ACCENTS));
        // The words of the card whole on their line, in each language, and
        // the name of every accent in its room.
        for(int language=0;language<PANEL_LANGUAGE_COUNT;language++){
            panel_text_set((panel_language_t)language);
            assert(fits(panel_text(TXT_APPEARANCE),&panel_font_18,248));
            assert(fits(panel_text(TXT_APPEARANCE_WHAT),&panel_font_12,248));
            assert(fits(panel_text(TXT_ACCENT),&panel_font_18,268));
            assert(fits(panel_text(TXT_ACCENT_WHAT),&panel_font_12,400));
            // A theme in its button of 70, with 4 of the button on each side
            // of it inside the border: "Dunkel" takes 59.
            for(int theme=0;theme<PANEL_THEMES;theme++)
                assert(fits(panel_text(panel_theme_name(theme)),&panel_font_16,70-2-2*4));
            for(int a=0;a<PANEL_ACCENTS;a++)
                assert(fits(panel_text(panel_accent_name(a)),&panel_font_18,108));
        }
        panel_text_set(PANEL_ENGLISH);
        // The light theme: saved at once, and the screen built again in its
        // colours, with the settings open as far down as they were.
        lv_obj_t *page=settings_page();
        lv_obj_scroll_to_y(page,300,LV_ANIM_OFF);
        int32_t scrolled=lv_obj_get_scroll_y(page);
        assert(scrolled==300);
        saved_count=0;
        lv_obj_send_event(light_button,LV_EVENT_CLICKED,NULL);
        assert(saved_count==1&&saved_key==PANEL_THEME&&saved_value==PANEL_THEME_LIGHT);
        panel_palette_t light=panel_palette(PANEL_THEME_LIGHT,PANEL_ACCENT_BLUE);
        assert(rgb_of(lv_obj_get_style_bg_color(lv_screen_active(),0))==light.bg);
        assert(strcmp(panel_ui_where(),"the settings")==0);
        assert(lv_obj_get_scroll_y(settings_page())==scrolled);
        card=appearance_card();
        assert(rgb_of(lv_obj_get_style_bg_color(card,0))==light.card);
        light_button=button_with(card,panel_text(TXT_THEME_LIGHT));
        assert(rgb_of(lv_obj_get_style_bg_color(light_button,0))==light.accent);
        assert(rgb_of(lv_obj_get_style_bg_color(button_with(card,panel_text(TXT_THEME_DARK)),0))==light.button);
        // The same tap again is no change: nothing saved, nothing built.
        lv_obj_send_event(light_button,LV_EVENT_CLICKED,NULL);
        assert(saved_count==1&&appearance_card()==card);
        // An accent: saved at once, and the sliders and the switches in it.
        lv_obj_send_event(accent_button(card,PANEL_ACCENT_ORANGE),LV_EVENT_CLICKED,NULL);
        assert(saved_count==2&&saved_key==PANEL_ACCENT&&saved_value==PANEL_ACCENT_ORANGE);
        assert(lv_obj_get_scroll_y(settings_page())==scrolled);
        panel_palette_t orange=panel_palette(PANEL_THEME_LIGHT,PANEL_ACCENT_ORANGE);
        card=appearance_card();
        assert(label(card,panel_text(TXT_COLOUR_ORANGE)));
        assert(label(accent_button(card,PANEL_ACCENT_ORANGE),LV_SYMBOL_OK));
        assert(!label(accent_button(card,PANEL_ACCENT_BLUE),LV_SYMBOL_OK));
        assert(rgb_of(lv_obj_get_style_bg_color(accent_button(card,PANEL_ACCENT_ORANGE),0))==orange.accent);
        for(int i=0;i<3;i++){
            int skip=i;
            lv_obj_t *slider=slider_at_place(settings_page(),&skip);
            assert(slider);
            assert(rgb_of(lv_obj_get_style_bg_color(slider,LV_PART_INDICATOR))==orange.accent);
            assert(rgb_of(lv_obj_get_style_bg_color(slider,LV_PART_KNOB))==orange.slider_knob);
        }
        lv_obj_t *lift=NULL;
        lv_obj_t *display_card=lv_obj_get_parent(label(lv_screen_active(),panel_text(TXT_LIFT_WAKE)));
        for(unsigned i=0;i<lv_obj_get_child_count(display_card);i++)
            if(lv_obj_check_type(lv_obj_get_child(display_card,i),&lv_switch_class))lift=lv_obj_get_child(display_card,i);
        assert(lift&&!lv_obj_has_state(lift,LV_STATE_CHECKED));
        assert(rgb_of(lv_obj_get_style_bg_color(lift,LV_PART_MAIN))==orange.edge);
        assert(rgb_of(lv_obj_get_style_bg_color(lift,LV_PART_KNOB))==orange.knob);
        lv_obj_add_state(lift,LV_STATE_CHECKED);
        assert(rgb_of(lv_obj_get_style_bg_color(lift,LV_PART_INDICATOR))==orange.accent);
        // Back on the band, in the new colours: the page, the cards, the
        // readings of the sensors and the switch of the sound.
        // 49 and not the 40 of base: the scale of the history can say 40.
        click(panel_text(TXT_BACK));
        assert(!label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
        t.cpu_temp=49;
        panel_ui_update(&t);
        assert(rgb_of(lv_obj_get_style_bg_color(lv_screen_active(),0))==orange.bg);
        lv_obj_t *reading=label(lv_screen_active(),"49 °C");
        assert(reading&&rgb_of(lv_obj_get_style_text_color(reading,0))==orange.accent_text);
        assert(rgb_of(lv_obj_get_style_bg_color(lv_obj_get_parent(lv_obj_get_parent(reading)),0))==orange.card);
        // A new language keeps the colours.
        panel_ui_settings_open();
        click(panel_language_name(PANEL_GERMAN));
        assert(saved_key==PANEL_LANGUAGE);
        assert(rgb_of(lv_obj_get_style_bg_color(lv_screen_active(),0))==orange.bg);
        assert(label(appearance_card(),panel_text(TXT_COLOUR_ORANGE)));
        click(panel_language_name(PANEL_ENGLISH));
        // And back to the dark theme in blue: the panel as it was.
        lv_obj_send_event(button_with(appearance_card(),panel_text(TXT_THEME_DARK)),LV_EVENT_CLICKED,NULL);
        lv_obj_send_event(accent_button(appearance_card(),PANEL_ACCENT_BLUE),LV_EVENT_CLICKED,NULL);
        assert(saved_key==PANEL_ACCENT&&saved_value==PANEL_ACCENT_BLUE);
        assert(rgb_of(lv_obj_get_style_bg_color(lv_screen_active(),0))==dark.bg);
        assert(rgb_of(lv_obj_get_style_bg_color(appearance_card(),0))==dark.card);
        // A theme or an accent that this firmware does not have, from a
        // later one: the dark theme in blue, and the card says so.
        panel_settings_t later=english;
        later.theme=(panel_theme_t)7;later.accent=(panel_accent_t)99;
        panel_ui_create(action,setting,sound,&later);
        panel_ui_settings_open();
        assert(rgb_of(lv_obj_get_style_bg_color(lv_screen_active(),0))==dark.bg);
        card=appearance_card();
        assert(rgb_of(lv_obj_get_style_bg_color(button_with(card,panel_text(TXT_THEME_DARK)),0))==dark.accent);
        assert(label(accent_button(card,PANEL_ACCENT_BLUE),LV_SYMBOL_OK));
        lv_refr_now(screen);
        assert(complaints==0);
    }

    // Every label of every page reads, in each theme and each accent: the
    // band with the PC there and with the PC gone, the pages over it, the
    // settings with the order of the pages, the question, the choice of a
    // sensor, the colour of the LED bar, the alarm, an update that writes
    // and the setup. The light theme is new, and a colour of it that nobody
    // saw on a page of its own is what this is for.
    {
        unsigned bad=0;
        for(int theme=0;theme<PANEL_THEMES;theme++)for(int accent=0;accent<PANEL_ACCENTS;accent++){
            panel_settings_t chosen={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH,
                                     .theme=(panel_theme_t)theme,.accent=(panel_accent_t)accent};
            panel_ui_create(action,setting,sound,&chosen);
            panel_ui_led_use(led_change);
            panel_ui_cpu_use(cpu_change);
            char where[64];
            panel_state_t s=base();
            s.cpu_temp=49;s.volume=42;
            static const panel_pad_t pads[]={{"Steam Controller",93,false},{"PlayStation Controller",100,true},
                                              {"Xbox Controller",-1,false}};
            memcpy(s.pads,pads,sizeof pads);s.pad_count=3;
            static const panel_sensor_t cpus[]={{"k10temp/Tctl","Tctl",49},{"k10temp/Tccd1","CCD 1",47}};
            memcpy(s.cpu_sensors,cpus,sizeof cpus);s.cpu_sensor_count=2;
            // A drive that is nearly full, in red, and one that is not.
            s.drive_count=2;
            strcpy(s.drives[0].name,"Internal");s.drives[0].total=512ULL<<30;s.drives[0].free=20ULL<<30;
            strcpy(s.drives[1].name,"SD card");s.drives[1].total=256ULL<<30;s.drives[1].free=200ULL<<30;
            strcpy(s.playing,"Portal 2");s.achievements_done=10;s.achievements_total=51;
            s.clock_set=true;s.hour=18;s.minute=42;s.weekday=3;s.day=1;s.month=10;
            s.gpu_load=87;s.gpu_mhz=2450;s.vram_used=8ULL<<30;s.vram_total=16ULL<<30;
            s.boost_here=s.boost_on=true;
            s.led_known=s.led_here=s.led_look=true;
            strcpy(s.led_effect[PANEL_LED_DESKTOP],"breath");strcpy(s.led_effect[PANEL_LED_GAME],"fire");
            strcpy(s.led_colour,"#ff8000");s.led_brightness=128;
            s.cpu_known=s.cpu_here=true;strcpy(s.cpu_profile,"balanced");
            s.cpu_offers=(uint8_t)((1u<<PANEL_CPU_PROFILES)-1);
            strcpy(s.cpu_governor,"powersave");strcpy(s.cpu_epp,"balance_performance");strcpy(s.cpu_driver,"amd-pstate-epp");
            s.esp_supply=PANEL_SUPPLY_BATTERY;s.esp_battery=87;
            snprintf(s.update.offered,sizeof s.update.offered,"64-2b7f0c1");
            s.update.phase=PANEL_UPDATE_FAILED;s.update.failure=TXT_UPDATE_BROKEN;
            strcpy(s.message,panel_text(TXT_SENT));
            strcpy(s.host,"FractalMachine");
            panel_ui_update(&s);
            #define READ_ALL(what) do{snprintf(where,sizeof where,"%s, %s, %s",panel_text(panel_theme_name(theme)), \
                panel_text(panel_accent_name(accent)),what);bad+=unreadable(lv_screen_active(),where);}while(0)
            READ_ALL("the band");
            panel_ui_settings_open();panel_ui_arrange_open();READ_ALL("the settings and the order");
            assert(panel_ui_home());
            panel_ui_pads_open();READ_ALL("the controllers");assert(panel_ui_home());
            panel_ui_pc_open();READ_ALL("the PC");assert(panel_ui_home());
            panel_ui_self_open();READ_ALL("the panel");assert(panel_ui_home());
            panel_ui_confirm(PANEL_POWEROFF);READ_ALL("a question");assert(panel_ui_home());
            lv_obj_t *tile=label(lv_screen_active(),"49 °C");
            assert(tile);
            lv_obj_send_event(lv_obj_get_parent(tile),LV_EVENT_CLICKED,NULL);
            assert(strcmp(panel_ui_where(),"a choice of sensor")==0);
            READ_ALL("a choice of sensor");assert(panel_ui_home());
            click(look_words_for(TXT_COLOUR_ORANGE,50,true));
            assert(strcmp(panel_ui_where(),"the colour of the LED bar")==0);
            READ_ALL("the colour of the LED bar");assert(panel_ui_home());
            // The timer, to its end. Its + is on the fourth page: the + of
            // the volume of the PC comes first on the screen.
            lv_obj_t *clock_page=lv_obj_get_child(find_band(lv_screen_active()),3);
            lv_obj_send_event(lv_obj_get_parent(label(clock_page,LV_SYMBOL_PLUS)),LV_EVENT_SHORT_CLICKED,NULL);
            click(panel_text(TXT_START));
            for(int i=0;i<200&&!panel_ui_timer_ringing();i++){lv_tick_inc(60*1000);panel_ui_timer_tick();}
            assert(panel_ui_timer_ringing());
            READ_ALL("the alarm");
            assert(panel_ui_timer_stop());
            panel_ui_timer_tick();
            click(panel_text(TXT_RESET));
            // The PC gone, with an address to wake it at.
            panel_state_t gone=s;gone.online=false;gone.can_wake=true;
            panel_ui_update(&gone);READ_ALL("the band without the PC");
            panel_state_t writing=s;writing.update.phase=PANEL_UPDATE_RUNNING;writing.update.percent=45;
            panel_ui_update(&writing);READ_ALL("an update");
            panel_state_t setup=s;setup.setup=true;
            strcpy(setup.setup_ssid,"SteamOS-Panel-3A12");strcpy(setup.setup_password,"ABCD2345EFGH");
            panel_ui_update(&setup);READ_ALL("the setup");
            // The pairing, with the code and both buttons.
            panel_state_t pairing=s;pairing.pairing=PANEL_PAIRING_WAIT;pairing.pair_can_cancel=true;
            strcpy(pairing.pair_code,"482913");strcpy(pairing.pair_pc,"steamdeck");
            strcpy(pairing.pair_address,"192.168.178.20:8765");
            panel_ui_update(&pairing);READ_ALL("the pairing");
            pairing.pairing=PANEL_PAIRING_NOT_FOUND;pairing.pair_code[0]=0;
            panel_ui_update(&pairing);READ_ALL("the pairing that found no PC");
            #undef READ_ALL
            lv_refr_now(screen);
        }
        assert(bad==0);
        assert(complaints==0);
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
    }

    // The pairing with the PC: a screen over everything, with the code to
    // compare, and a button for each way out that the moment has.
    {
        panel_settings_t english={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
        panel_ui_create(action,setting,sound,&english);
        panel_state_t p=base();
        p.pairing=PANEL_PAIRING_WAIT;p.pair_can_cancel=true;
        strcpy(p.pair_code,"482913");strcpy(p.pair_pc,"steamdeck");strcpy(p.pair_address,"192.168.178.20:8765");
        panel_ui_update(&p);
        lv_obj_t *screen=lv_screen_active();
        assert(label(screen,panel_text(TXT_PAIR_TITLE))&&label(screen,panel_text(TXT_PAIR_WAIT)));
        // Three and three, which is easier to compare than six.
        assert(label(screen,"482 913"));
        assert(label(screen,"PC: steamdeck (192.168.178.20:8765)"));
        // A panel with a secret of its own can go back to it.
        lv_obj_t *page=lv_obj_get_child(screen,-1);
        lv_obj_t *cancel=button_with(page,panel_text(TXT_CANCEL));
        assert(cancel&&button_with(page,panel_text(TXT_SETUP)));
        actions=0;
        lv_obj_send_event(cancel,LV_EVENT_CLICKED,NULL);
        assert(actions==1&&last_action==PANEL_PAIR_CANCEL);
        // One with none has nothing to go back to.
        p.pair_can_cancel=false;
        panel_ui_update(&p);
        assert(!button_with(page,panel_text(TXT_CANCEL)));
        // An end with no secret offers a new try.
        p.pairing=PANEL_PAIRING_EXPIRED;p.pair_code[0]=0;
        panel_ui_update(&p);
        assert(label(screen,panel_text(TXT_PAIR_EXPIRED))&&!label(screen,"482 913"));
        lv_obj_t *again=button_with(page,panel_text(TXT_PAIR_AGAIN));
        assert(again);
        lv_obj_send_event(again,LV_EVENT_CLICKED,NULL);
        assert(actions==2&&last_action==PANEL_PAIR);
        // The search, and a search that found nothing: the setup takes an
        // address by hand.
        p.pairing=PANEL_PAIRING_SEARCH;p.pair_pc[0]=p.pair_address[0]=0;
        panel_ui_update(&p);
        assert(label(screen,panel_text(TXT_PAIR_SEARCH))&&!button_with(page,panel_text(TXT_PAIR_AGAIN)));
        p.pairing=PANEL_PAIRING_NOT_FOUND;
        panel_ui_update(&p);
        assert(label(screen,panel_text(TXT_PAIR_NOT_FOUND))&&button_with(page,panel_text(TXT_SETUP)));
        // The end that worked has no button: it closes by itself.
        p.pairing=PANEL_PAIRING_DONE;p.pair_can_cancel=true;
        panel_ui_update(&p);
        assert(label(screen,panel_text(TXT_PAIR_DONE)));
        assert(!button_with(page,panel_text(TXT_SETUP))&&!button_with(page,panel_text(TXT_CANCEL)));
        // And then the screen goes, and the band is back.
        p.pairing=PANEL_PAIRING_NONE;
        panel_ui_update(&p);
        assert(!label(screen,panel_text(TXT_PAIR_TITLE))&&find_band(screen));
        // The settings start a new pairing, and ask nothing first: the
        // secret of the panel stays until the PC gives a new one.
        panel_ui_settings_open();
        lv_obj_t *settings=lv_obj_get_child(screen,-1);
        lv_obj_t *pair_button=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(settings)&&!pair_button;i++)
            pair_button=button_with(lv_obj_get_child(settings,i),panel_text(TXT_PAIR_START));
        assert(pair_button);
        actions=0;
        lv_obj_send_event(pair_button,LV_EVENT_CLICKED,NULL);
        assert(actions==1&&last_action==PANEL_PAIR);
        assert(panel_ui_home());
    }

    puts("OK: seven pages that snap, in an order somebody can change, any of them "
         "but the last one hidden with an eye, the "
         "session and its target button, the "
         "drives with their bars, every one of them offline, every one of "
         "them drawn with nothing for LVGL to complain about, the battery of "
         "the panel in the corner with the network mark against it, the "
         "achievements of the game under its name, room under both "
         "display sliders, the clock with a timer that rings and an alarm that snoozes, and two "
         "controllers in the head with a page of four behind it, and the "
         "page of the PC that scrolls, and a choice of sensor for each tile "
         "of the temperatures, and the page of the panel with its update, "
         "its power chip in detail and its frames in movement, and the page "
         "of the card with its history and its Cooling Boost, the page of "
         "the LED bar with the effect of each mode of the PC and the colour and the brightness of the desktop, and the page "
         "of the energy profile of its CPU, and the pairing with the PC and its "
         "code, and all of it in a dark theme and a "
         "light one, each in eight accents that a card of the settings chooses, "
         "with every label of every page readable in each.");
    return 0;
}
