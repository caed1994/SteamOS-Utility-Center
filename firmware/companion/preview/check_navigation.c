// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
static unsigned actions, settings, sounds;
static panel_setting_t last_key;
static int last_value;
static bool last_save;
static void action(panel_action_t a){(void)a;actions++;}
static void setting(panel_setting_t k,int v,bool save){settings++;last_key=k;last_value=v;last_save=save;}
static void sound(int volume){assert(volume==45);sounds++;}
static lv_obj_t *label(lv_obj_t *root,const char *text)
{
    if(lv_obj_check_type(root,&lv_label_class)&&strcmp(lv_label_get_text(root),text)==0)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){lv_obj_t *found=label(lv_obj_get_child(root,i),text);if(found)return found;}
    return NULL;
}
static lv_obj_t *kind(lv_obj_t *root,const lv_obj_class_t *cls,int *skip)
{
    if(lv_obj_check_type(root,cls)){if(*skip==0)return root;(*skip)--;}
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){lv_obj_t *found=kind(lv_obj_get_child(root,i),cls,skip);if(found)return found;}
    return NULL;
}
static void click(const char *text)
{
    lv_obj_t *l=label(lv_screen_active(),text);assert(l);
    lv_obj_t *b=lv_obj_get_parent(l);assert(lv_obj_check_type(b,&lv_button_class));
    lv_obj_send_event(b,LV_EVENT_CLICKED,NULL);
}
int main(void)
{
    lv_init();lv_display_create(480,480);
    panel_settings_t initial={.brightness=70,.sound_volume=30};
    panel_ui_create(action,setting,sound,&initial);
    panel_state_t offline={.battery=-1,.volume=-1,.cpu_temp=-1,.gpu_temp=-1,.gpu_watts=-1};
    panel_ui_update(&offline);
    assert(!label(lv_screen_active(),"Displayhelligkeit"));
    click("Einstellungen");
    assert(label(lv_screen_active(),"ESP-Einstellungen"));
    int skip=0;lv_obj_t *brightness=kind(lv_screen_active(),&lv_slider_class,&skip);assert(brightness);
    lv_slider_set_value(brightness,55,LV_ANIM_OFF);
    lv_obj_send_event(brightness,LV_EVENT_VALUE_CHANGED,NULL);
    assert(last_key==PANEL_BRIGHTNESS && last_value==55 && !last_save);
    lv_obj_send_event(brightness,LV_EVENT_RELEASED,NULL);assert(last_save);
    skip=1;lv_obj_t *volume=kind(lv_screen_active(),&lv_slider_class,&skip);assert(volume);
    lv_slider_set_value(volume,45,LV_ANIM_OFF);lv_obj_send_event(volume,LV_EVENT_RELEASED,NULL);
    assert(last_key==PANEL_SOUND_VOLUME && last_value==45 && last_save);
    click("Testton");assert(sounds==1 && actions==0);
    skip=0;lv_obj_t *sw=kind(lv_screen_active(),&lv_switch_class,&skip);assert(sw);
    lv_obj_add_state(sw,LV_STATE_CHECKED);lv_obj_send_event(sw,LV_EVENT_VALUE_CHANGED,NULL);
    assert(last_key==PANEL_TOUCH_TONES && last_value==1 && sounds==2);
    panel_ui_update(&offline);assert(label(lv_screen_active(),"ESP-Einstellungen"));
    click("< Zurueck");assert(!label(lv_screen_active(),"ESP-Einstellungen"));
    click("Einstellungen");
    assert(label(lv_screen_active(),"55 %") && label(lv_screen_active(),"45 %"));
    skip=0;sw=kind(lv_screen_active(),&lv_switch_class,&skip);assert(lv_obj_has_state(sw,LV_STATE_CHECKED));
    assert(settings==4 && actions==0);
    click("< Zurueck");
    click("Einrichten");assert(label(lv_screen_active(),"Einrichtung oeffnen?"));
    click("Abbrechen");assert(actions==0);
    puts("OK: Offline navigation, local callbacks, values retained, PC actions isolated, setup confirmation.");
    return 0;
}
