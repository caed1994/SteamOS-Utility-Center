// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The middle band, which scrolls, and the two pages that came with it.
//
// Nothing here draws: it builds the screens on a host LVGL and reads the
// words off them. What it holds is the part a person sees, which is the
// part a rule in Python cannot reach.
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
#include "panel_fonts.h"
#include "panel_frames.h"
static unsigned actions;
static panel_action_t last_action;
static void action(panel_action_t a){actions++;last_action=a;}
// The last setting the screen saved, for the choice of a sensor.
static panel_setting_t saved_key;
static int saved_value,saved_count;
static void setting(panel_setting_t k,int v,bool save){if(save){saved_key=k;saved_value=v;saved_count++;}}
static void sound(int volume){(void)volume;}
// The changes of the page of the LED bar, as main.c gets them.
static unsigned led_changes;
static char led_last[PANEL_LED_MODES][PANEL_LED_KEY];
static void led_change(const char *const effect[PANEL_LED_MODES])
{
    led_changes++;
    for(int m=0;m<PANEL_LED_MODES;m++)snprintf(led_last[m],PANEL_LED_KEY,"%s",effect[m]?effect[m]:"");
}
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
        // The cards under it keep their gap.
        lv_obj_t *sound_card=lv_obj_get_parent(label(lv_screen_active(),panel_text(TXT_TONES)));
        assert(lv_obj_get_y(sound_card)==lv_obj_get_y(card)+lv_obj_get_height(card)+14);
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
            PANEL_PAGE_SESSION,PANEL_PAGE_PLAYING,PANEL_PAGE_CARD,PANEL_PAGE_LED};
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
            TXT_PAGE_SESSION,TXT_PLAYING,TXT_PAGE_CARD,TXT_PAGE_LED};
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
        lv_obj_t *bottom=lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_LED)));
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
            PANEL_PAGE_SESSION,PANEL_PAGE_PLAYING,PANEL_PAGE_CARD,PANEL_PAGE_LED};
        assert(saved_count==1&&saved_key==PANEL_PAGE_ORDER);
        assert((uint32_t)saved_value==panel_pages_pack(controls_first));
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CONTROLS))==0);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CLOCK))==480);
        start=label(screen_now,panel_text(TXT_PAGES_START));
        assert(start&&lv_obj_get_parent(start)==lv_obj_get_parent(label(screen_now,panel_text(TXT_PAGE_CONTROLS))));
        // Up on the bottom row: the LED bar goes fifth.
        lv_obj_send_event(bottom_up,LV_EVENT_CLICKED,NULL);
        static const uint8_t led_fifth[PANEL_PAGES]={PANEL_PAGE_CONTROLS,PANEL_PAGE_CLOCK,
            PANEL_PAGE_SESSION,PANEL_PAGE_PLAYING,PANEL_PAGE_LED,PANEL_PAGE_CARD};
        assert((uint32_t)saved_value==panel_pages_pack(led_fifth));
        lv_obj_update_layout(lv_screen_active());
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_LED))==4*480);
        assert(lv_obj_get_x(lv_obj_get_child(band_now,PANEL_PAGE_CARD))==5*480);
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
        german.page_order=panel_pages_pack(led_fifth);
        panel_ui_create(action,setting,sound,&german);
        panel_ui_settings_open();
        panel_ui_arrange_open();
        screen_now=lv_obj_get_parent(label(lv_screen_active(),"Seiten anordnen"));
        assert(screen_now);
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        assert(label(screen_now,"Seiten anordnen")&&label(screen_now,"Startseite"));
        static const char *const german_names[]={"Steuerung","Uhr und Timer",
            "Sitzung und Datenträger","Läuft gerade","LED-Leiste","Grafikkarte und Verlauf"};
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
            TXT_PLAYING,TXT_PAGE_CLOCK,TXT_PAGE_CARD,TXT_PAGE_LED};
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
        assert(lv_obj_get_scroll_x(band_now)==0);
        // The band ends at the last page that is shown.
        lv_obj_scroll_to_x(band_now,PANEL_PAGES*480,LV_ANIM_OFF);
        assert(lv_obj_get_scroll_x(band_now)==4*480);
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
                             |(1<<PANEL_PAGE_LED)));
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
        assert(strcmp(panel_ui_where(),"the session")==0);
        lv_obj_scroll_to_x(band_now,PANEL_PAGES*480,LV_ANIM_OFF);
        assert(strcmp(panel_ui_where(),"the LED bar")==0);
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
        g.gpu_load=87;g.gpu_mhz=2450;g.vram_used=10522460160ULL;g.vram_total=17163091968ULL;
        panel_ui_update(&g);
        assert(label(page,"GPU load")&&label(page,"VRAM")&&label(page,"GPU clock"));
        assert(label(page,"87 %")&&label(page,"9.8 / 16.0 GB")&&label(page,"2450 MHz"));
        // Each bar as long as its share: 87 of 100, and 9.8 of 16.0 GB.
        lv_obj_update_layout(screen_now);
        lv_obj_t *gpu_card=lv_obj_get_parent(label(page,"87 %"));
        int bars=0;
        for(unsigned i=0;i<lv_obj_get_child_count(gpu_card);i++){
            lv_obj_t *track=lv_obj_get_child(gpu_card,i);
            if(lv_obj_get_height(track)!=8||lv_obj_get_child_count(track)!=1)continue;
            int32_t full=lv_obj_get_width(track),filled=lv_obj_get_width(lv_obj_get_child(track,0));
            assert(bars==0?filled==full*87/100:filled==(int32_t)(full*10522460160ULL/17163091968ULL));
            bars++;
        }
        assert(bars==2);
        // The longest of each fits its room, with no dots: a full card, the
        // memory of a card of 24 GB, and a clock past three thousand.
        g.gpu_load=100;g.gpu_mhz=3100;g.vram_used=25662623334ULL;g.vram_total=25769803776ULL;
        panel_ui_update(&g);
        lv_obj_update_layout(screen_now);
        lv_refr_now(screen);
        const char *longest[]={"100 %","23.9 / 24.0 GB","3100 MHz"};
        for(int i=0;i<3;i++){
            lv_obj_t *value=label(page,longest[i]);
            assert(value);
            lv_point_t size;
            lv_text_get_size(&size,longest[i],&panel_font_24,0,0,LV_COORD_MAX,LV_TEXT_FLAG_NONE);
            assert(size.x<=lv_obj_get_width(value));
            // And inside the card.
            assert(lv_obj_get_x(value)+size.x<=lv_obj_get_width(gpu_card)-8);
        }
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
        // The window: 30 minutes, then the hour.
        assert(label(page,"-30 min"));
        click("60 min");
        assert(label(page,"-60 min")&&!label(page,"-30 min"));
        // The chart takes no press, so a swipe over it moves the band.
        lv_obj_t *history_card=lv_obj_get_parent(label(page,"-60 min"));
        lv_obj_t *chart=NULL;
        for(unsigned i=0;i<lv_obj_get_child_count(history_card);i++)
            if(lv_obj_check_type(lv_obj_get_child(history_card,i),&lv_chart_class))
                chart=lv_obj_get_child(history_card,i);
        assert(chart&&!lv_obj_has_flag(chart,LV_OBJ_FLAG_CLICKABLE));
        assert(lv_chart_get_point_count(chart)==PANEL_HISTORY_DRAWN);
        lv_refr_now(screen);
        assert(complaints==0);
        // A new screen for a new language keeps the history and the window.
        panel_settings_t german=chosen;german.language=PANEL_GERMAN;
        panel_ui_create(action,setting,sound,&german);
        page=lv_obj_get_child(find_band(lv_screen_active()),4);
        assert(label(page,"GPU-Last")&&label(page,"Verlauf"));
        assert(label(page,"80 °C")&&label(page,"-60 Min"));
        assert(!label(page,"Noch keine Werte"));
        lv_refr_now(screen);
        assert(complaints==0);
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
        assert(label(desktop,"Ooze")&&label(desktop,panel_text(TXT_LED_APPLYING)));
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
        assert(label(desktop,"CPU and GPU load")&&label(desktop,panel_text(TXT_LED_APPLYING)));
        strcpy(t.led_effect[PANEL_LED_DESKTOP],"load");
        t.answers++;
        panel_ui_update(&t);
        assert(label(desktop,"CPU and GPU load")&&!label(desktop,panel_text(TXT_LED_APPLYING)));
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
        assert(label(game,"Ooze"));
        // A refusal takes the choice back, and says why.
        led_wait(1600);
        assert(led_changes==2&&strcmp(led_last[PANEL_LED_GAME],"ooze")==0&&!led_last[PANEL_LED_DESKTOP][0]);
        t.led_replies++;t.led_code=403;
        panel_ui_update(&t);
        assert(label(game,"Fire")&&label(game,panel_text(TXT_LED_NO_RULE)));
        // Each code of a refusal has its own reason.
        static const struct{int code;panel_text_id_t why;}refusals[]={
            {409,TXT_LED_BUSY},{501,TXT_LED_NO_MODULE},{502,TXT_LED_REFUSED},{0,TXT_LED_REFUSED}};
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
        assert(label(desktop,"Breathing")&&!label(desktop,panel_text(TXT_LED_APPLYING)));
        // In Game Mode its card says so.
        t.game_mode=true;
        panel_ui_update(&t);
        assert(!label(desktop,panel_text(TXT_LED_NOW))&&label(game,panel_text(TXT_LED_NOW)));
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
        assert(label(desktop,panel_text(TXT_LED_OLD_SERVICE))&&!label(desktop,panel_text(TXT_LED_NONE)));
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
            static const panel_text_id_t notes[]={TXT_LED_GAME_WHAT,TXT_LED_COLOUR_WHAT,TXT_LED_APPLYING,
                TXT_LED_NONE,TXT_LED_OLD_SERVICE,TXT_LED_NO_RULE,TXT_LED_BUSY,TXT_LED_NO_MODULE,TXT_LED_REFUSED,
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

    puts("OK: six pages that snap, in an order somebody can change, any of them "
         "but the last one hidden with an eye, the "
         "session and its target button, the "
         "drives with their bars, every one of them offline, every one of "
         "them drawn with nothing for LVGL to complain about, the battery of "
         "the panel in the corner with the network mark against it, the "
         "achievements of the game under its name, room under both "
         "display sliders, the clock with a timer that rings, and two "
         "controllers in the head with a page of four behind it, and the "
         "page of the PC that scrolls, and a choice of sensor for each tile "
         "of the temperatures, and the page of the panel with its update, "
         "its power chip in detail and its frames in movement, and the page "
         "of the card with its history, and the page of the LED bar with "
         "the effect of each mode of the PC.");
    return 0;
}
