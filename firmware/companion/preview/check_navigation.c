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
#include "panel_taps.h"
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
    // Down to five per cent, the lowest brightness the backlight holds
    // steady, and no further.
    assert(lv_slider_get_min_value(brightness)==PANEL_BRIGHTNESS_MIN&&PANEL_BRIGHTNESS_MIN==5);
    lv_slider_set_value(brightness,0,LV_ANIM_OFF);
    lv_obj_send_event(brightness,LV_EVENT_RELEASED,NULL);
    assert(last_key==PANEL_BRIGHTNESS && last_value==5 && last_save);
    assert(label(lv_screen_active(),"5 %"));
    lv_slider_set_value(brightness,55,LV_ANIM_OFF);
    lv_obj_send_event(brightness,LV_EVENT_RELEASED,NULL);
    assert(last_value==55);
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
    // The switch of the tones is the second one: the first is the lift,
    // in the card of the display above it.
    skip=1;lv_obj_t *sw=kind(lv_screen_active(),&lv_switch_class,&skip);assert(sw);
    lv_obj_add_state(sw,LV_STATE_CHECKED);lv_obj_send_event(sw,LV_EVENT_VALUE_CHANGED,NULL);
    assert(last_key==PANEL_TOUCH_TONES && last_value==1 && sounds==2);
    // The lift: off as the settings came, on with a tap, and saved each
    // way.
    skip=0;lv_obj_t *lift=kind(lv_screen_active(),&lv_switch_class,&skip);
    assert(lift && lift!=sw && !lv_obj_has_state(lift,LV_STATE_CHECKED));
    assert(label(lv_screen_active(),panel_text(TXT_LIFT_WAKE)));
    lv_obj_add_state(lift,LV_STATE_CHECKED);lv_obj_send_event(lift,LV_EVENT_VALUE_CHANGED,NULL);
    assert(last_key==PANEL_LIFT_WAKE && last_value==1 && last_save);
    lv_obj_remove_state(lift,LV_STATE_CHECKED);lv_obj_send_event(lift,LV_EVENT_VALUE_CHANGED,NULL);
    assert(last_key==PANEL_LIFT_WAKE && last_value==0 && last_save);
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
    skip=1;sw=kind(lv_screen_active(),&lv_switch_class,&skip);assert(lv_obj_has_state(sw,LV_STATE_CHECKED));
    // The lift as it was left: off again.
    skip=0;lift=kind(lv_screen_active(),&lv_switch_class,&skip);
    assert(lift && !lv_obj_has_state(lift,LV_STATE_CHECKED));
    assert(settings==12 && actions==0);
    // The button in the corner carries the name of the other language. A
    // press on it builds both screens again, and the person stays here.
    panel_language_t next=other(language);
    click(panel_language_name(next));
    assert(panel_text_language()==next);
    assert(last_key==PANEL_LANGUAGE && last_value==(int)next && last_save);
    assert(settings==13 && actions==0);
    assert(label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    assert(label(lv_screen_active(),"55 %") && label(lv_screen_active(),"45 %"));
    skip=1;sw=kind(lv_screen_active(),&lv_switch_class,&skip);assert(lv_obj_has_state(sw,LV_STATE_CHECKED));
    // The setup lives here now and no longer in a corner of the main
    // screen, where a stray finger lands. It still asks first, and the
    // question stands over the settings rather than behind them.
    click(panel_text(TXT_SETUP));assert(label(lv_screen_active(),panel_text(TXT_CONFIRM_SETUP)));
    click(panel_text(TXT_CANCEL));assert(actions==0);
    assert(label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    // The colours of the screen: a theme is saved at a tap and builds both
    // screens again, the way a language does, and the person stays on the
    // settings with every value as it was.
    click(panel_text(TXT_THEME_LIGHT));
    assert(last_key==PANEL_THEME && last_value==PANEL_THEME_LIGHT && last_save);
    assert(label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    assert(label(lv_screen_active(),"55 %") && label(lv_screen_active(),"45 %"));
    skip=1;sw=kind(lv_screen_active(),&lv_switch_class,&skip);assert(lv_obj_has_state(sw,LV_STATE_CHECKED));
    click(panel_text(TXT_THEME_DARK));
    assert(last_key==PANEL_THEME && last_value==PANEL_THEME_DARK && last_save);
    assert(settings==15 && actions==0);
    // The words below are the ones the button chose.
    click(panel_text(TXT_BACK));
    assert(!label(lv_screen_active(),panel_text(TXT_SETUP)));
}
// The band is the one object on the screen that scrolls sideways.
static lv_obj_t *find_band(lv_obj_t *root)
{
    if(lv_obj_get_scroll_dir(root)==LV_DIR_HOR&&lv_obj_get_child_count(root)==PANEL_PAGES)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){lv_obj_t *f=find_band(lv_obj_get_child(root,i));if(f)return f;}
    return NULL;
}
// The animations to their end. Nothing here draws, so this moves the
// clock and the animations and not the display.
static void settle(void){for(int i=0;i<100;i++){lv_tick_inc(10);lv_anim_refr_now();}}
static bool at(const char *where){return strcmp(panel_ui_where(),where)==0;}
// The home key, the lower key on the side of the panel: the start page
// from wherever the panel is, with all that stands over the band closed.
// The setup and an update that writes stay: those end on their own.
static void home_key(void)
{
    panel_settings_t initial={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
    panel_ui_create(action,setting,sound,&initial);
    panel_state_t offline={.volume=-1,.cpu_temp=-1,.gpu_temp=-1,.gpu_watts=-1};
    panel_ui_update(&offline);
    lv_obj_t *band=find_band(lv_screen_active());assert(band);
    char start[32];snprintf(start,sizeof start,"%s",panel_ui_where());
    // From the third page, under the order of the pages, which stands on
    // the settings.
    lv_obj_scroll_to_x(band,2*480,LV_ANIM_OFF);
    assert(!at(start));
    panel_ui_settings_open();panel_ui_arrange_open();
    assert(at("the order of the pages"));
    assert(panel_ui_home());
    assert(!label(lv_screen_active(),panel_text(TXT_SETTINGS_TITLE)));
    assert(!label(lv_screen_active(),panel_text(TXT_PAGES_TITLE)));
    settle();
    assert(lv_obj_get_scroll_x(band)==0 && at(start));
    // A question closes with no answer: nothing goes to the PC.
    actions=0;
    panel_ui_confirm(PANEL_REBOOT);assert(at("a question"));
    assert(panel_ui_home() && at(start) && actions==0);
    // The pages that a tap on the head and on the battery open.
    panel_ui_pc_open();assert(at("the PC"));
    assert(panel_ui_home() && at(start));
    panel_ui_pads_open();assert(at("the controllers"));
    assert(panel_ui_home() && at(start));
    panel_ui_self_open();assert(at("the panel"));
    assert(panel_ui_home() && at(start));
    // The choice of a sensor, which a tap on a tile of the foot opens, and
    // the colour of the LED bar, which its button on the fifth page opens.
    panel_state_t online={.online=true,.wifi=true,.volume=30,
                          .cpu_temp=49,.gpu_temp=45,.gpu_watts=60};
    static const panel_sensor_t cpus[]={{"k10temp/Tctl","Tctl",49}};
    memcpy(online.cpu_sensors,cpus,sizeof cpus);online.cpu_sensor_count=1;
    online.led_known=online.led_here=online.led_look=true;
    strcpy(online.led_effect[PANEL_LED_DESKTOP],"breath");
    strcpy(online.led_effect[PANEL_LED_GAME],"fire");
    strcpy(online.led_colour,"#ff0000");online.led_brightness=128;
    panel_ui_update(&online);
    lv_obj_t *tile=label(lv_screen_active(),"49 °C");assert(tile);
    lv_obj_send_event(lv_obj_get_parent(tile),LV_EVENT_CLICKED,NULL);
    assert(at("a choice of sensor"));
    assert(panel_ui_home() && at(start));
    char red[48];
    snprintf(red,sizeof red,"%s • %d %%",panel_text(TXT_COLOUR_RED),50);
    lv_obj_t *look=label(lv_screen_active(),red);assert(look);
    lv_obj_send_event(lv_obj_get_parent(look),LV_EVENT_CLICKED,NULL);
    assert(at("the colour of the LED bar"));
    assert(panel_ui_home() && at(start));
    // Already there: nothing to close, and the band stays. The counts of
    // the page of the panel stay too: a press of the key is no visit of
    // that page.
    panel_taps.presses=3;
    assert(panel_ui_home());settle();
    assert(lv_obj_get_scroll_x(band)==0 && at(start) && panel_taps.presses==3);
    // An update that writes stays over everything until the restart.
    panel_state_t writing=offline;
    writing.update.phase=PANEL_UPDATE_RUNNING;writing.update.percent=40;
    panel_ui_update(&writing);assert(at("an update"));
    lv_obj_scroll_to_x(band,480,LV_ANIM_OFF);
    assert(!panel_ui_home() && at("an update"));
    settle();assert(lv_obj_get_scroll_x(band)==480);
    panel_ui_update(&offline);assert(!at("an update"));
    // And the setup ends with the setup.
    panel_state_t setup=offline;setup.setup=true;
    panel_ui_update(&setup);assert(at("the setup"));
    assert(!panel_ui_home() && at("the setup"));
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
    home_key();
    puts("OK: Offline navigation in each language, the language button, local "
         "callbacks, values retained, PC actions isolated, setup confirmation, "
         "the theme buttons, the home key.");
    return 0;
}
