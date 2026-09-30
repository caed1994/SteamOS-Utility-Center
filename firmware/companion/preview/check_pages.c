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
static unsigned actions;
static panel_action_t last_action;
static void action(panel_action_t a){actions++;last_action=a;}
static void setting(panel_setting_t k,int v,bool save){(void)k;(void)v;(void)save;}
static void sound(int volume){(void)volume;}
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
static void click(const char *text)
{
    lv_obj_t *l=label(lv_screen_active(),text);assert(l);
    lv_obj_t *b=lv_obj_get_parent(l);
    while(b&&!lv_obj_check_type(b,&lv_button_class))b=lv_obj_get_parent(b);
    assert(b);
    lv_obj_send_event(b,LV_EVENT_CLICKED,NULL);
}
// The band is the one object on the screen that scrolls sideways.
static lv_obj_t *find_band(lv_obj_t *root)
{
    if(lv_obj_get_scroll_dir(root)==LV_DIR_HOR&&lv_obj_get_child_count(root)==3)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){lv_obj_t *f=find_band(lv_obj_get_child(root,i));if(f)return f;}
    return NULL;
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
static panel_state_t base(void)
{
    panel_state_t s={.online=true,.wifi=true,.battery=50,.volume=30,
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
    panel_ui_create(action,setting,sound,&settings);

    // Three pages, and the band snaps so there is no place between two.
    lv_obj_t *band=find_band(lv_screen_active());
    assert(band);
    assert(lv_obj_get_child_count(band)==3);
    assert(lv_obj_has_flag(band,LV_OBJ_FLAG_SCROLL_ONE));
    // A band that takes a press swallows the one meant for a button on it.
    assert(!lv_obj_has_flag(band,LV_OBJ_FLAG_CLICKABLE));

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
    assert(lv_obj_get_child_count(band_now)==3);
    for(unsigned page=0;page<3;page++){
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
        int32_t second_room=lv_obj_get_height(card)-lv_obj_get_y(second);
        assert(first_room>0);
        assert(second_room>=first_room);
        // The setup stands in the settings now, and still asks first: a
        // cancel sends nothing.
        unsigned before=actions;
        click(panel_text(TXT_SETUP));
        assert(label(lv_screen_active(),panel_text(TXT_CONFIRM_SETUP)));
        click(panel_text(TXT_CANCEL));
        assert(actions==before);
    }

    puts("OK: three pages that snap, the session and its target button, the "
         "drives with their bars, every one of them offline, every one of "
         "them drawn with nothing for LVGL to complain about, the battery of "
         "the panel in the corner with the network mark against it, the "
         "achievements of the game under its name, and room under both "
         "display sliders.");
    return 0;
}
