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
#include <stdlib.h>
#include <unistd.h>
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
// How much memory this process really holds, out of the kernel.
//
// The second number in /proc/self/statm is the resident page count. It is
// here because the count the screen keeps of its own bytes cannot say
// whether they were freed, and that is the question.
static size_t resident_bytes(void)
{
    FILE *f=fopen("/proc/self/statm","r");
    if(!f)return 0;
    unsigned long total=0,resident=0;
    int read=fscanf(f,"%lu %lu",&total,&resident);
    fclose(f);
    if(read!=2)return 0;
    return (size_t)resident*(size_t)sysconf(_SC_PAGESIZE);
}
static panel_state_t base(void)
{
    panel_state_t s={.online=true,.wifi=true,.battery=50,.volume=30,
                     .cpu_temp=40,.gpu_temp=45,.gpu_watts=60};
    return s;
}
int main(void)
{
    lv_init();lv_display_create(480,480);
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

    // The picture, and what becomes of it.
    //
    // The screen takes the bytes and frees them, which is a promise that
    // cannot be read off the source. panel_ui_banner_bytes says how many
    // are held, so every step below is measured rather than assumed.
    // These are not a real JPEG: what is under test is the bookkeeping,
    // and LVGL refusing to decode them changes none of it.
    assert(panel_ui_banner_bytes()==0);
    void *first=malloc(1000);assert(first);
    panel_ui_banner(first,1000);
    assert(panel_ui_banner_bytes()==1000);

    // A second picture frees the first. Nothing grows.
    void *second=malloc(2000);assert(second);
    panel_ui_banner(second,2000);
    assert(panel_ui_banner_bytes()==2000);

    // The same pointer again is not a free and a take of the same memory.
    panel_ui_banner(second,2000);
    assert(panel_ui_banner_bytes()==2000);

    // The end of a game. This is the question somebody asked out loud:
    // the picture goes when the game does.
    panel_ui_banner(NULL,0);
    assert(panel_ui_banner_bytes()==0);

    // And a rebuild of the screens keeps the picture rather than asking
    // for it again. A picture is about the machine, not about the
    // language somebody reads.
    void *third=malloc(3000);assert(third);
    panel_ui_banner(third,3000);
    panel_ui_create(action,setting,sound,&settings);
    assert(panel_ui_banner_bytes()==3000);
    panel_ui_banner(NULL,0);
    assert(panel_ui_banner_bytes()==0);

    // And the bytes really go.
    //
    // Everything above this reads panel_ui_banner_bytes, which is the
    // screen's own count and not the memory. Take the free out of
    // panel_ui_banner and every rule above still passes, so none of them
    // answers "is it freed".
    //
    // This does. Two hundred pictures of a quarter of a megabyte, taken
    // and dropped one after another. Freed, the allocator hands the same
    // block back and the resident size stays where it was. Leaked, it
    // grows by fifty megabytes, which no rounding hides.
    size_t before=resident_bytes();
    // A reading of nought is a reader that failed, and the comparison
    // below would then pass whatever happened. Silence is not success.
    assert(before>0);
    for(int i=0;i<200;i++){
        void *one=malloc(256*1024);assert(one);
        memset(one,i&0xFF,256*1024);   // touch it, so it is really resident
        panel_ui_banner(one,256*1024);
        panel_ui_banner(NULL,0);
    }
    size_t after=resident_bytes();
    assert(panel_ui_banner_bytes()==0);
    // Ten megabytes of room for the allocator and for everything else
    // this process does. A leak here is fifty.
    assert(after<before+10u*1024*1024);

    puts("OK: three pages that snap, the session and its target button, the "
         "drives with their bars, every one of them offline, and a picture "
         "that is taken, replaced, dropped, kept over a rebuild and really "
         "freed.");
    return 0;
}
