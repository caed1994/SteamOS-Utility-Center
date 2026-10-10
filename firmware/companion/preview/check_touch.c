// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Where a press lands, on every screen of the panel.
//
// Asked for: taps that do not land on some places. Each point of each
// screen goes through the hit test of LVGL, the one the touch uses, and the
// points that reach one object make its zone. A zone must be 48 px each
// way, about 7 mm on this screen. A zone at the edge of the screen needs
// 44 in that direction: a finger that goes past the edge still lands on it.
// The rooms past the edges of the buttons come from ui.c: see BUTTON_REACH.
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "lvgl.h"
#include "src/misc/lv_area_private.h"
#include "ui.h"

#define ZONE 48
#define EDGE_ZONE 44
#define MOST 256

static uint32_t pixels[480*480];
static void flush(lv_display_t *d,const lv_area_t *a,uint8_t *p){(void)a;(void)p;lv_display_flush_ready(d);}
static uint32_t ticks;
static uint32_t tick(void){return ticks;}
static void action(panel_action_t a){(void)a;}
static void setting(panel_setting_t k,int v,bool s){(void)k;(void)v;(void)s;}
static void sound(int v){(void)v;}

static unsigned targets,screens;
/* The page that scrolls under screen(), or NULL for a screen that does not
 * scroll. See scrolled(). */
static lv_obj_t *scrolling;

static const char *first_text(lv_obj_t *o)
{
    if(lv_obj_check_type(o,&lv_label_class))return lv_label_get_text(o);
    for(uint32_t i=0;i<lv_obj_get_child_count(o);i++){
        const char *t=first_text(lv_obj_get_child(o,i));
        if(t&&t[0])return t;
    }
    return NULL;
}

/* An object that a page scrolls part of the way out of view. Another place
 * of the scroll shows it whole, and its zone is measured there. */
static bool cut(lv_obj_t *o)
{
    lv_area_t c;
    lv_obj_get_coords(o,&c);
    for(lv_obj_t *a=lv_obj_get_parent(o);a;a=lv_obj_get_parent(a)){
        lv_area_t ac;
        lv_obj_get_coords(a,&ac);
        if(!lv_area_is_in(&c,&ac,0))return true;
    }
    return false;
}

static void screen(const char *name)
{
    struct{lv_obj_t *o;int count,x1,y1,x2,y2;}zone[MOST];
    int found=0;
    lv_obj_update_layout(lv_screen_active());
    for(int y=0;y<480;y++)for(int x=0;x<480;x++){
        lv_point_t p={x,y};
        lv_obj_t *o=lv_indev_search_obj(lv_screen_active(),&p);
        /* A press on something with no handler of its own does nothing. */
        if(!o||lv_obj_get_event_count(o)==0)continue;
        int k=0;
        while(k<found&&zone[k].o!=o)k++;
        if(k==found){
            assert(found<MOST);
            zone[found].o=o;zone[found].count=0;
            zone[found].x1=zone[found].x2=x;zone[found].y1=zone[found].y2=y;
            found++;
        }
        zone[k].count++;
        if(x<zone[k].x1)zone[k].x1=x;
        if(x>zone[k].x2)zone[k].x2=x;
        if(y<zone[k].y1)zone[k].y1=y;
        if(y>zone[k].y2)zone[k].y2=y;
    }
    for(int k=0;k<found;k++){
        if(cut(zone[k].o))continue;
        /* A zone that ends at the top or the foot of a page that scrolls on
         * past it: the next place of the scroll has the rest of it. */
        if(scrolling){
            lv_area_t page;
            lv_obj_get_coords(scrolling,&page);
            if((zone[k].y1<=page.y1&&lv_obj_get_scroll_top(scrolling)>0)||
               (zone[k].y2>=page.y2&&lv_obj_get_scroll_bottom(scrolling)>0))continue;
        }
        /* A layer over the whole screen takes the taps beside its box: no
         * button, and its zone is the frame around the box. */
        if(lv_obj_get_width(zone[k].o)>=480&&lv_obj_get_height(zone[k].o)>=480)continue;
        int w=zone[k].x2-zone[k].x1+1,h=zone[k].y2-zone[k].y1+1;
        int least_w=zone[k].x1==0||zone[k].x2==479?EDGE_ZONE:ZONE;
        int least_h=zone[k].y1==0||zone[k].y2==479?EDGE_ZONE:ZONE;
        /* Most of the box is the zone itself: a box that the zone of
         * another object eats into is a zone smaller than it looks. */
        bool whole=zone[k].count*10>=w*h*8;
        if(w<least_w||h<least_h||!whole){
            const char *text=first_text(zone[k].o);
            fprintf(stderr,"%s: \"%s\" takes a press over %dx%d at %d,%d (%d of %d points)\n",
                    name,text?text:"",w,h,zone[k].x1,zone[k].y1,zone[k].count,w*h);
        }
        assert(w>=least_w&&h>=least_h&&whole);
        targets++;
    }
    screens++;
}

static lv_obj_t *find_band(lv_obj_t *root)
{
    if(lv_obj_has_flag(root,LV_OBJ_FLAG_SCROLL_ONE))return root;
    for(uint32_t i=0;i<lv_obj_get_child_count(root);i++){
        lv_obj_t *f=find_band(lv_obj_get_child(root,i));
        if(f)return f;
    }
    return NULL;
}

static lv_obj_t *find_label(lv_obj_t *root,const char *text)
{
    if(lv_obj_check_type(root,&lv_label_class)&&strcmp(lv_label_get_text(root),text)==0)return root;
    for(uint32_t i=0;i<lv_obj_get_child_count(root);i++){
        lv_obj_t *f=find_label(lv_obj_get_child(root,i),text);
        if(f)return f;
    }
    return NULL;
}

/* A page that scrolls, at each place of its scroll: steps short enough
 * that each object is whole at one of them. */
static void scrolled(lv_obj_t *page,const char *name)
{
    scrolling=page;
    for(int32_t y=0;;y+=300){
        lv_obj_scroll_to_y(page,y,LV_ANIM_OFF);
        lv_obj_update_layout(page);
        screen(name);
        if(lv_obj_get_scroll_bottom(page)<=0)break;
    }
    scrolling=NULL;
}

int main(void)
{
    lv_init();
    lv_tick_set_cb(tick);
    lv_display_t *d=lv_display_create(480,480);
    lv_display_set_color_format(d,LV_COLOR_FORMAT_XRGB8888);
    lv_display_set_buffers(d,pixels,NULL,sizeof(pixels),LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(d,flush);
    /* German, which has the longer words. */
    panel_settings_t settings={.brightness=70,.sound_volume=30,.lift_wake=true,.language=PANEL_GERMAN};
    static panel_history_t history;
    panel_history_reset(&history);
    panel_ui_history_use(&history);
    panel_ui_create(action,setting,sound,&settings);
    /* Every page with all it can show: the PC up, two controllers, the LED
     * bar, the energy profiles and Cooling Boost. */
    static panel_state_t s={.wifi=true,.online=true,.volume=42,.cpu_temp=49,.gpu_temp=56,.gpu_watts=78,
        .gpu_load=87,.gpu_mhz=2450,.vram_used=10522460160ULL,.vram_total=17163091968ULL,.can_wake=true,
        .boost_here=true,.clock_set=true,.hour=18,.minute=42,.weekday=3,.day=1,.month=10,
        .esp_supply=PANEL_SUPPLY_BATTERY,.esp_battery=87};
    strcpy(s.host,"FractalMachine");
    static const panel_pad_t pads[]={{"Steam Controller 1",93,false},{"PlayStation Controller",100,true}};
    memcpy(s.pads,pads,sizeof pads);
    s.pad_count=2;
    s.led_known=true;s.led_here=true;s.led_look=true;s.led_brightness=128;
    snprintf(s.led_colour,sizeof s.led_colour,"#ff8000");
    snprintf(s.led_effect[PANEL_LED_DESKTOP],PANEL_LED_KEY,"breath");
    snprintf(s.led_effect[PANEL_LED_GAME],PANEL_LED_KEY,"fire");
    s.cpu_known=true;s.cpu_here=true;
    snprintf(s.cpu_profile,sizeof s.cpu_profile,"balanced");
    s.cpu_offers=(uint8_t)((1u<<PANEL_CPU_PROFILES)-1);
    panel_ui_update(&s);

    /* The seven pages of the band, with the head and the foot. */
    static const char *const pages[PANEL_PAGES]={"the controls","the session","the game","the clock",
                                                 "the card","the LED bar","the CPU"};
    lv_obj_t *band=find_band(lv_screen_active());
    assert(band);
    for(int p=0;p<PANEL_PAGES;p++){
        lv_obj_update_layout(band);
        lv_obj_scroll_to_view(lv_obj_get_child(band,p),LV_ANIM_OFF);
        screen(pages[p]);
    }
    /* The LED bar with the mirror, which has the button of its profile. */
    snprintf(s.led_effect[PANEL_LED_GAME],PANEL_LED_KEY,"mirror");
    snprintf(s.led_profile,sizeof s.led_profile,"pop");
    s.answers++;
    panel_ui_update(&s);
    assert(find_label(lv_screen_active(),"Color Pop"));
    lv_obj_update_layout(band);
    lv_obj_scroll_to_view(lv_obj_get_child(band,5),LV_ANIM_OFF);
    screen("the LED bar with the mirror");
    snprintf(s.led_effect[PANEL_LED_GAME],PANEL_LED_KEY,"fire");
    s.answers++;
    panel_ui_update(&s);
    /* The alarm, from its button in the corner of the clock card. */
    lv_obj_scroll_to_view(lv_obj_get_child(band,3),LV_ANIM_OFF);
    lv_obj_update_layout(band);
    lv_obj_t *clock_card=lv_obj_get_child(lv_obj_get_child(band,3),0);
    lv_obj_send_event(lv_obj_get_child(clock_card,2),LV_EVENT_CLICKED,NULL);
    assert(find_label(lv_screen_active(),panel_text(TXT_ALARM_TITLE)));
    screen("the alarm");
    panel_ui_home();
    /* The choice of the sensor of a tile, from the tile. */
    lv_obj_t *gpu=find_label(lv_screen_active(),"GPU");
    assert(gpu);
    lv_obj_send_event(lv_obj_get_parent(gpu),LV_EVENT_CLICKED,NULL);
    screen("the sensors");
    panel_ui_home();
    /* The colour of the LED bar, from its button on the LED page. */
    lv_obj_scroll_to_view(lv_obj_get_child(band,5),LV_ANIM_OFF);
    lv_obj_update_layout(band);
    char look[48];
    snprintf(look,sizeof look,"%s • %d %%",panel_text(TXT_COLOUR_ORANGE),50);
    lv_obj_t *words=find_label(lv_screen_active(),look);
    assert(words);
    lv_obj_send_event(lv_obj_get_parent(words),LV_EVENT_CLICKED,NULL);
    screen("the colour");
    panel_ui_home();
    panel_ui_confirm(PANEL_POWEROFF);
    screen("a question");
    panel_ui_home();
    panel_ui_settings_open();
    scrolled(lv_obj_get_child(lv_screen_active(),-1),"the settings");
    panel_ui_arrange_open();
    scrolled(lv_obj_get_child(lv_screen_active(),-1),"the order");
    panel_ui_home();
    panel_ui_pads_open();
    screen("the controllers");
    panel_ui_home();
    panel_ui_pc_open();
    scrolled(lv_obj_get_child(lv_screen_active(),-1),"the PC");
    panel_ui_home();
    panel_ui_self_open();
    scrolled(lv_obj_get_child(lv_screen_active(),-1),"the panel");
    panel_ui_home();
    /* The pairing with the PC, with both of its buttons. */
    s.pairing=PANEL_PAIRING_EXPIRED;
    panel_ui_update(&s);
    screen("the pairing");
    s.pairing=PANEL_PAIRING_NONE;
    panel_ui_update(&s);
    printf("OK: every place that takes a tap on %u screens of the panel, %u of them, takes it "
           "over %d px each way, %d at the edge of the screen.\n",screens,targets,ZONE,EDGE_ZONE);
    return 0;
}
