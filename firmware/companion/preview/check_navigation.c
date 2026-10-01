// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Navigation of the panel, one walk in each language it offers.
//
// This check clicked on words written into this file, and those words were
// the German ones. Then the panel learned English and answered in it, so
// every click here missed the button it wanted. Nothing said so, because
// nothing built this check at all.
//
// It asks panel_text for each word now, the same way the screen does. A word
// that changes in the table changes here with it, and a language the panel
// offers is a language this walks.
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
static panel_language_t other(panel_language_t language)
{
    return language==PANEL_ENGLISH?PANEL_GERMAN:PANEL_ENGLISH;
}
static void open_settings(void){click(panel_text(TXT_SETTINGS));}
// One walk of the panel, in the language given. It ends on the main screen,
// in the other language, because the walk presses the language button.
static void walk(panel_language_t language)
{
    actions=settings=sounds=0;
    // Start in the other language, so this walk asks panel_ui_create to
    // change it. A create that keeps whatever was there reads the same as a
    // correct one when the language happens to match already.
    panel_text_set(other(language));
    panel_settings_t initial={.brightness=70,.sound_volume=30,.language=language};
    panel_ui_create(action,setting,sound,&initial);
    assert(panel_text_language()==language);
    panel_state_t offline={.volume=-1,.cpu_temp=-1,.gpu_temp=-1,.gpu_watts=-1};
    panel_ui_update(&offline);
    assert(!label(lv_screen_active(),panel_text(TXT_BRIGHTNESS)));
    open_settings();
    assert(label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    int skip=0;lv_obj_t *brightness=kind(lv_screen_active(),&lv_slider_class,&skip);assert(brightness);
    lv_slider_set_value(brightness,55,LV_ANIM_OFF);
    lv_obj_send_event(brightness,LV_EVENT_VALUE_CHANGED,NULL);
    assert(last_key==PANEL_BRIGHTNESS && last_value==55 && !last_save);
    lv_obj_send_event(brightness,LV_EVENT_RELEASED,NULL);assert(last_save);
    // The second slider is the one that says when the display goes dark.
    //
    // It stands on a place in a list of stops and reports minutes, which
    // is what gets stored: a later firmware with other stops still reads
    // what somebody picked here. Nothing else in this panel reports a
    // number other than the one under the knob.
    skip=1;lv_obj_t *sleep=kind(lv_screen_active(),&lv_slider_class,&skip);
    assert(sleep);
    assert(label(lv_screen_active(),panel_text(TXT_SLEEP_NEVER)));
    lv_slider_set_value(sleep,4,LV_ANIM_OFF);
    lv_obj_send_event(sleep,LV_EVENT_RELEASED,NULL);
    assert(last_key==PANEL_SLEEP_AFTER && last_value==10 && last_save);
    assert(!label(lv_screen_active(),panel_text(TXT_SLEEP_NEVER)));
    // The top of the slider is the longest wait and not a wrong reading
    // past the end of the list.
    lv_slider_set_value(sleep,lv_slider_get_max_value(sleep),LV_ANIM_OFF);
    lv_obj_send_event(sleep,LV_EVENT_RELEASED,NULL);
    assert(last_key==PANEL_SLEEP_AFTER && last_value==60);
    lv_slider_set_value(sleep,0,LV_ANIM_OFF);
    lv_obj_send_event(sleep,LV_EVENT_RELEASED,NULL);
    assert(last_key==PANEL_SLEEP_AFTER && last_value==0);
    assert(label(lv_screen_active(),panel_text(TXT_SLEEP_NEVER)));
    lv_slider_set_value(sleep,4,LV_ANIM_OFF);
    lv_obj_send_event(sleep,LV_EVENT_RELEASED,NULL);

    skip=2;lv_obj_t *volume=kind(lv_screen_active(),&lv_slider_class,&skip);assert(volume);
    lv_slider_set_value(volume,45,LV_ANIM_OFF);lv_obj_send_event(volume,LV_EVENT_RELEASED,NULL);
    assert(last_key==PANEL_SOUND_VOLUME && last_value==45 && last_save);
    click(panel_text(TXT_TEST_TONE));assert(sounds==1 && actions==0);
    skip=0;lv_obj_t *sw=kind(lv_screen_active(),&lv_switch_class,&skip);assert(sw);
    lv_obj_add_state(sw,LV_STATE_CHECKED);lv_obj_send_event(sw,LV_EVENT_VALUE_CHANGED,NULL);
    assert(last_key==PANEL_TOUCH_TONES && last_value==1 && sounds==2);
    panel_ui_update(&offline);assert(label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    click(panel_text(TXT_BACK));assert(!label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    open_settings();
    assert(label(lv_screen_active(),"55 %") && label(lv_screen_active(),"45 %"));
    // And the wait it was left at, which comes back off the stored
    // count of minutes and not off the place of the knob.
    {
        char wanted[24];
        snprintf(wanted,sizeof wanted,"10 %s",panel_text(TXT_MINUTES));
        assert(label(lv_screen_active(),wanted));
    }
    skip=0;sw=kind(lv_screen_active(),&lv_switch_class,&skip);assert(lv_obj_has_state(sw,LV_STATE_CHECKED));
    assert(settings==8 && actions==0);
    // The button in the corner carries the name of the other language. A
    // press on it builds both screens again, and the person stays here.
    panel_language_t next=other(language);
    click(panel_language_name(next));
    assert(panel_text_language()==next);
    assert(last_key==PANEL_LANGUAGE && last_value==(int)next && last_save);
    assert(settings==9 && actions==0);
    assert(label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    assert(label(lv_screen_active(),"55 %") && label(lv_screen_active(),"45 %"));
    skip=0;sw=kind(lv_screen_active(),&lv_switch_class,&skip);assert(lv_obj_has_state(sw,LV_STATE_CHECKED));
    // The setup lives here now and no longer in a corner of the main
    // screen, where a stray finger lands. It still asks first, and the
    // question stands over the settings rather than behind them.
    click(panel_text(TXT_SETUP));assert(label(lv_screen_active(),panel_text(TXT_CONFIRM_SETUP)));
    click(panel_text(TXT_CANCEL));assert(actions==0);
    assert(label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    // The words below are the ones the button chose.
    click(panel_text(TXT_BACK));
    assert(!label(lv_screen_active(),panel_text(TXT_SETUP)));
}
// The walks above ask panel_text for the word and then look for that same
// word on the screen. So a table that answers with one language whatever it
// is asked passes every one of them: the screen and the check are wrong
// together. This reads the two columns against each other instead.
static void tables_differ(void)
{
    unsigned same=0;
    for(int id=0;id<TXT_COUNT;id++){
        panel_text_set(PANEL_ENGLISH);const char *english=panel_text(id);
        panel_text_set(PANEL_GERMAN);const char *german=panel_text(id);
        if(strcmp(english,german)==0)same++;
    }
    // A few of them are the same word in both, PC OFFLINE among them. A
    // quarter of the table is far above that and far below all of it.
    assert(same<TXT_COUNT/4);
}
int main(void)
{
    lv_init();lv_display_create(480,480);
    tables_differ();
    walk(PANEL_ENGLISH);
    walk(PANEL_GERMAN);
    // A build of the screens while the settings page is open. The clean in
    // panel_ui_create takes that page with it, and a pointer kept past it is
    // a settings page that never opens again.
    open_settings();
    assert(label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    panel_settings_t again={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
    panel_ui_create(action,setting,sound,&again);
    assert(!label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    open_settings();
    assert(label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    puts("OK: Offline navigation in each language, the language button, local "
         "callbacks, values retained, PC actions isolated, setup confirmation.");
    return 0;
}
