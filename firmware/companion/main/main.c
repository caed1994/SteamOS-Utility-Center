// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <math.h>
#include <stdatomic.h>
#include <inttypes.h>
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_app_desc.h"
#include "panel_display.h"
#include "panel_frames.h"
#include "panel_power.h"
#include "panel_battery.h"
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include "nvs_flash.h"
#include "nvs.h"
#include "cJSON.h"
#include "lvgl.h"
#include "bsp/esp-bsp.h"
#include "bsp/display.h"
#include "ui.h"
#include "config.h"
#include "panel_auth.h"
#include "panel_text.h"
#include "panel_boot.h"
#include "panel_wol.h"
#include "panel_clock.h"
#include "panel_time.h"
#include "panel_update.h"
#include "panel_ota.h"
#include "panel_history.h"
#include "panel_motion.h"
#include "panel_psram.h"
#include "esp_ota_ops.h"

/* The startup animation, put in the image by main/CMakeLists.txt. It
 * belongs to Valve and not to this project; assets/ORIGIN-BOOT-ANIMATION
 * says what it is and how to take it out. Deleting the file leaves these
 * two the same, and panel_boot_show does nothing when they are. */
extern const uint8_t boot_animation_start[] asm("_binary_boot_steam_gif_start");
extern const uint8_t boot_animation_end[] asm("_binary_boot_steam_gif_end");

static atomic_uint ui_heartbeat_ms;
static atomic_bool display_asleep;
static int display_brightness=70; /* Updated only by the LVGL thread after startup. */
/* Minutes of no touch before the display goes dark, and nought for never.
 * Written by setting_set and read by ui_tick, both on the LVGL thread. */
static int display_sleep_after;
/* Why the display sleeps.
 *
 * A panel that went dark by itself comes back at a touch, which is the
 * whole point of a timeout. A panel somebody switched off with the button
 * has to stay off: a touch there is the sleeve of whoever walks past, and
 * waking to that is the opposite of what the button was pressed for.
 *
 * So the reason is kept and not only the state. The button is the only
 * way back from a sleep the button started. */
static atomic_bool asleep_by_hand;
/* The radio, at rest while the display sleeps by the button.
 *
 * Asked for: a panel switched off by hand spends nothing on the network.
 * One that went down after the set time stays on it, so its numbers are
 * current the moment a touch brings it back. The button is the only way
 * back from the first, and the radio joins again then. That takes some
 * seconds, and the network mark is red until it has.
 *
 * Written by the network task alone, which is the one that stops and
 * starts the radio. Read by wifi_event on the event task: the disconnect
 * that esp_wifi_stop causes is no reason to connect again. */
static atomic_bool radio_resting;
/* When the radio came back, for the line that says how long the join took
 * after it. Nought when no join after a rest is under way. */
static atomic_uint radio_back_ms;
/* Whether a lift wakes a display that went dark after the set time. The
 * setting, as the screen sets it; see panel_motion.c. */
static atomic_bool lift_wake;
/* The firmware the PC offers and this panel takes, see panel_update.c, and
 * whether an update runs. The network task alone writes the offer; the
 * flag is read by ui_tick, which keeps the display on while it is set. */
static panel_offer_t offer_taken;
static atomic_bool updating;
/* The history of the page of the card, in PSRAM. Written by ui_tick and
 * drawn by the screen, both in the LVGL task. */
static panel_history_t *history;
static QueueHandle_t actions;
static QueueHandle_t sounds;
static SemaphoreHandle_t lock;
static panel_state_t state;
/* The frames in movement for the health line, under lock as state is.
 * Beside the state and not in it: see the end of panel_state_t. */
static panel_frame_stats_t health_frames;
static panel_config_t config;

/* took_us is the time of the request, from the first byte out to the
 * last one in. The page of the PC shows it as the time the PC takes to
 * answer. */
typedef struct { char data[8192]; size_t length; bool overflow; int64_t took_us; } response_t;

static panel_settings_t settings_load(void)
{
    panel_settings_t settings={.brightness=70,.sound_volume=30,
                               .touch_tones=false,
                               .language=PANEL_ENGLISH,
                               /* Off by itself is what somebody asks for
                                * rather than what they get, so a panel
                                * with nothing stored stays lit. */
                               .sleep_after=0,
                               /* Asked for, so on until somebody switches
                                * it off. It acts only after the timeout. */
                               .lift_wake=true,
                               .page_order=PANEL_PAGES_UNSET,
                               /* Every page in the band. */
                               .page_hidden=0};
    nvs_handle_t h;
    if(nvs_open("panel_ui",NVS_READONLY,&h)==ESP_OK){
        uint8_t value;
        if(nvs_get_u8(h,"brightness",&value)==ESP_OK && value>=PANEL_BRIGHTNESS_MIN && value<=100)
            settings.brightness=value;
        if(nvs_get_u8(h,"sound_volume",&value)==ESP_OK && value<=100)settings.sound_volume=value;
        if(nvs_get_u8(h,"touch_tones",&value)==ESP_OK)settings.touch_tones=value==1;
        // Anything this firmware does not know about reads as English,
        // which is what a board with nothing stored answers in.
        if(nvs_get_u8(h,"language",&value)==ESP_OK && value<PANEL_LANGUAGE_COUNT)
            settings.language=(panel_language_t)value;
        /* Minutes, so anything past an hour is a number this firmware did
         * not write. */
        if(nvs_get_u8(h,"sleep_after",&value)==ESP_OK && value<=60)
            settings.sleep_after=value;
        /* The sensor of each tile, as a key. A key no sensor has any more
         * is the choice of the service: see sensor_shown in ui.c. */
        uint32_t key;
        if(nvs_get_u32(h,"cpu_sensor",&key)==ESP_OK)settings.cpu_sensor=key;
        if(nvs_get_u32(h,"gpu_sensor",&key)==ESP_OK)settings.gpu_sensor=key;
        if(nvs_get_u8(h,"lift_wake",&value)==ESP_OK)settings.lift_wake=value==1;
        /* The order of the pages. Whatever it holds is read with care:
         * see panel_pages_order. */
        if(nvs_get_u32(h,"page_order",&key)==ESP_OK)settings.page_order=key;
        /* The hidden pages, read with the same care: see
         * panel_pages_hidden. */
        if(nvs_get_u32(h,"page_hidden",&key)==ESP_OK)settings.page_hidden=key;
        nvs_close(h);
    }
    // Here, and not where the screen is built. The setup portal opens
    // before that and serves a page of its own, and it has to serve the
    // one that matches. See index_get in config.c.
    panel_text_set(settings.language);
    return settings;
}
static void setting_set(panel_setting_t key,int value,bool save)
{
    const char *name=key==PANEL_BRIGHTNESS?"brightness":
                     key==PANEL_SOUND_VOLUME?"sound_volume":
                     key==PANEL_LANGUAGE?"language":
                     key==PANEL_SLEEP_AFTER?"sleep_after":
                     key==PANEL_CPU_SENSOR?"cpu_sensor":
                     key==PANEL_GPU_SENSOR?"gpu_sensor":
                     key==PANEL_LIFT_WAKE?"lift_wake":
                     key==PANEL_PAGE_ORDER?"page_order":
                     key==PANEL_PAGE_HIDDEN?"page_hidden":"touch_tones";
    bool wide=key==PANEL_CPU_SENSOR||key==PANEL_GPU_SENSOR||key==PANEL_PAGE_ORDER||
              key==PANEL_PAGE_HIDDEN;
    esp_err_t result=ESP_OK;
    if(key==PANEL_BRIGHTNESS){
        if(!atomic_load(&display_asleep))result=bsp_display_brightness_set(value);
        if(result==ESP_OK)display_brightness=value;
    }
    if(key==PANEL_LIFT_WAKE){
        atomic_store(&lift_wake,value!=0);
        if(!value)panel_motion_watch(false);
    }
    if(key==PANEL_SLEEP_AFTER){
        display_sleep_after=value;
        /* A fresh start, so that a timeout somebody just set
         * does not count the minutes before they set it. */
        lv_display_trigger_activity(NULL);
    }
    if(result==ESP_OK && save){
        nvs_handle_t h;
        result=nvs_open("panel_ui",NVS_READWRITE,&h);
        if(result==ESP_OK){
            result=wide?nvs_set_u32(h,name,(uint32_t)value):nvs_set_u8(h,name,(uint8_t)value);
            if(result==ESP_OK)result=nvs_commit(h);
            nvs_close(h);
        }
    }
    if(result!=ESP_OK){
        xSemaphoreTake(lock,portMAX_DELAY);
        snprintf(state.message,sizeof(state.message),panel_text(TXT_NOT_CONFIRMED));
        xSemaphoreGive(lock);
    }
}
static void sound_send(int volume)
{
    if(!atomic_load(&display_asleep) && sounds && volume>0 && volume<=100)xQueueOverwrite(sounds,&volume);
}
static void sound_task(void *unused)
{
    (void)unused;
    esp_codec_dev_handle_t speaker=NULL;
    bool attempted=false,ready=false;
    static int16_t samples[1323]; /* 60 ms, 22.05 kHz; smooth envelope avoids clicks. */
    for(int i=0;i<1323;i++){
        float envelope=sinf(3.14159265f*i/1322.0f);
        samples[i]=(int16_t)(6000.0f*envelope*envelope*sinf(2.0f*3.14159265f*880.0f*i/22050.0f));
    }
    for(;;){
        int volume;
        if(xQueueReceive(sounds,&volume,portMAX_DELAY)!=pdTRUE)continue;
        if(atomic_load(&display_asleep))continue;
        if(!attempted){
            attempted=true;
            speaker=bsp_audio_codec_speaker_init();
            esp_codec_dev_sample_info_t format={.sample_rate=22050,.channel=1,.bits_per_sample=16};
            ready=speaker && esp_codec_dev_open(speaker,&format)==ESP_OK;
            if(ready)esp_codec_dev_set_out_mute(speaker,true);
        }
        bool ok=ready;
        if(ok)ok=esp_codec_dev_set_out_vol(speaker,volume)==ESP_OK;
        if(ok)ok=esp_codec_dev_set_out_mute(speaker,false)==ESP_OK;
        if(ok)ok=esp_codec_dev_write(speaker,samples,sizeof(samples))==ESP_OK;
        /* Wait for DMA to drain before muting the codec. */
        if(ready){vTaskDelay(pdMS_TO_TICKS(90));esp_codec_dev_set_out_mute(speaker,true);}
        xSemaphoreTake(lock,portMAX_DELAY);state.sound_error=!ok;xSemaphoreGive(lock);
    }
}
static int metric(cJSON *object,const char *key,int limit)
{
    cJSON *value=cJSON_GetObjectItemCaseSensitive(object,key);
    return cJSON_IsNumber(value)&&value->valuedouble>=0&&value->valuedouble<=limit?value->valueint:-1;
}

/* How little stack the task that draws has had left.
 *
 * The health line already carries this for the network task, and the task
 * that ran out was the other one:
 *
 *     ***ERROR*** A stack overflow in task taskLVGL has been detected.
 *
 * This runs from an LVGL timer, which is that task, so NULL asks about it
 * and not about whoever prints the line. Nothing outside the task can be
 * asked this without its handle, so the reading is taken here and left in
 * a number the health line reads.
 *
 * A warning goes out once the headroom passes below the floor. Above it,
 * a line goes out each time the headroom sinks by PANEL_STACK_STEP, with
 * what the panel showed then.
 *
 * The deepest point falls between two ticks, so the line names what the
 * screen showed at the tick after it. The steps keep it to a few lines
 * over the life of the panel, most of them at the start.
 *
 * Only from the LVGL timer, which runs in the drawing task. app_main calls
 * ui_tick once itself, and that call runs on the start task: its reading
 * was the stack of the start task, 3584 bytes with about 700 left, set
 * against the stack of the drawing task. Read off the board as 716 of
 * 24576 "on the first page" at 1.9 s, and as 708 of 12288 at 1.8 s before
 * that. The number only ever goes down, so that one reading stood on the
 * health line for good. See ui_tick. */
#define PANEL_STACK_FLOOR 1024
#define PANEL_STACK_STEP 1024
static atomic_uint ui_stack_left;

static const char *panel_place(void)
{
    if (panel_boot_playing()) return "the startup animation";
    if (atomic_load(&display_asleep)) return "the standby";
    return panel_ui_where();
}

static void watch_stack(void)
{
    static unsigned logged;
    UBaseType_t left=uxTaskGetStackHighWaterMark(NULL);
    unsigned was=atomic_load(&ui_stack_left);
    if (was!=0 && (unsigned)left>=was) return;
    atomic_store(&ui_stack_left,(unsigned)left);
    if ((unsigned)left<PANEL_STACK_FLOOR)
        ESP_LOGW("panel_stack",
                 "the drawing task is down to %u of %u bytes of stack, on %s",
                 (unsigned)left,(unsigned)panel_display_stack_bytes(),
                 panel_place());
    else if (logged==0 || logged-(unsigned)left>=PANEL_STACK_STEP) {
        logged=(unsigned)left;
        ESP_LOGI("panel_stack",
                 "the drawing task has had %u of %u bytes of stack left at "
                 "the least, on %s",(unsigned)left,
                 (unsigned)panel_display_stack_bytes(),panel_place());
    }
}

/* Put the display down or bring it back, and remember why.
 *
 * One door for the button and for the timeout, so that the state, the
 * sound queue and the log line cannot drift apart between them. by_hand
 * is read only on the way down; on the way up the reason is over.
 */
static void display_sleeping(bool sleep,bool by_hand)
{
    if(sleep==atomic_load(&display_asleep))return;
    /* The clock at full speed before the display comes back, so the first
     * frame is drawn at it. Low only once the display is down, and back
     * low when it did not come up. See panel_clock.c. */
    if(!sleep)panel_clock_low(false);
    esp_err_t err=panel_display_standby(sleep,display_brightness);
    if(err!=ESP_OK){
        ESP_LOGW("panel_power","Standby change failed: %s",esp_err_to_name(err));
        if(!sleep)panel_clock_low(true);
        return;
    }
    if(sleep)panel_clock_low(true);
    atomic_store(&display_asleep,sleep);
    atomic_store(&asleep_by_hand,sleep && by_hand);
    /* The accelerometer watches a sleep after the timeout, with the
     * setting on, and nothing else: a display the button switched off
     * stays off, whatever moves it. */
    panel_motion_watch(sleep && !by_hand && atomic_load(&lift_wake));
    if(sleep && sounds)xQueueReset(sounds);
    /* The clock starts at the moment of waking. Without this the panel
     * counts the whole sleep as time without a touch and goes straight
     * back down. */
    if(!sleep)lv_display_trigger_activity(NULL);
    if(!sleep)ESP_LOGI("panel_power","Display awake");
    else if(by_hand)
        ESP_LOGI("panel_power","Display standby by the button; Wi-Fi and PC "
                 "polling stop until the button wakes it");
    else
        ESP_LOGI("panel_power","Display standby after the set time; Wi-Fi "
                 "and PC polling remain active");
}

/* Whether the timer that rings woke the display, and from which sleep.
 * A timer nobody stopped puts the display back where it found it: nobody
 * is there to look. The LVGL task alone reads and writes these. */
static bool alarm_woke,alarm_woke_by_hand;

static void ui_tick(lv_timer_t *timer)
{
    /* A call with no timer is the one from app_main, on the start task.
     * See watch_stack. */
    if(timer)watch_stack();
    /* From the LVGL timer only: the call from app_main comes before the
     * startup animation begins. See panel_display_boot_over. */
    if(timer && !panel_boot_playing())panel_display_boot_over();
    /* The timer of the fourth page, first and in a sleep as well: it runs
     * on while the display is dark, and its end wakes the display, from
     * the sleep of the button too. The wake ends the rest of the radio on
     * its own: asleep_by_hand goes false with it. */
    panel_timer_news_t news=panel_ui_timer_tick();
    if(news.went_off){
        alarm_woke=atomic_load(&display_asleep);
        alarm_woke_by_hand=atomic_load(&asleep_by_hand);
        display_sleeping(false,false);
        ESP_LOGI("panel_timer","The timer went off%s",
                 alarm_woke?", and woke the display":"");
    }
    if(news.beep)sound_send(panel_ui_alarm_volume());
    if(news.gave_up){
        ESP_LOGI("panel_timer","Nobody stopped the timer, so it is quiet again");
        if(alarm_woke)display_sleeping(true,alarm_woke_by_hand);
        alarm_woke=false;
    }
    if(panel_power_take_toggle()){
        /* The button stops a timer that rings, and does nothing else then:
         * the hand that reaches for it wants the noise to end. */
        if(panel_ui_timer_stop()){
            alarm_woke=false;
            ESP_LOGI("panel_timer","Stopped by the button");
        }else if(atomic_load(&updating)){
            /* The progress stays in view. A dark panel in the middle of an
             * update reads as one that is off. */
            ESP_LOGI("panel_power","The button waits for the update");
        }else display_sleeping(!atomic_load(&display_asleep),true);
    }
    if(atomic_load(&display_asleep)){
        /* A touch brings back a display that went down on its own, and
         * leaves one that the button switched off where it is. A lift does
         * what a touch does, with its setting on. The sensor is read by a
         * task of its own, and this only takes what it saw. */
        if(!atomic_load(&asleep_by_hand)){
            bool lifted=panel_motion_take_lift();
            if(lifted)ESP_LOGI("panel_motion","Lifted, so the display wakes");
            if(lifted || panel_display_touched())display_sleeping(false,false);
        }
    }else if(display_sleep_after>0 && !panel_ui_timer_ringing() &&
             !atomic_load(&updating) &&
             lv_display_get_inactive_time(NULL)
                 >= (uint32_t)display_sleep_after*60u*1000u){
        /* Not while it rings: a minute of no touch is a minute of ringing
         * too, and the display would go dark under the alarm. */
        display_sleeping(true,false);
    }
    uint32_t now_ms=(uint32_t)(esp_timer_get_time()/1000);
    atomic_store(&ui_heartbeat_ms,now_ms);
    /* The history goes on while the display sleeps: after the set time the
     * PC is still asked. So a dark display copies the state once for each
     * step of it, and not at every tick. */
    bool due=history&&panel_history_due(history,now_ms);
    if(atomic_load(&display_asleep)&&!due)return;
    /* The frames in movement, counted in this task by the events of the
     * display, for the health line of the network task. See
     * panel_frames.h. */
    panel_frame_stats_t frames;
    panel_frames_stats(&panel_frames,&frames);
    panel_state_t copy;
    xSemaphoreTake(lock,portMAX_DELAY); health_frames=frames; copy=state; xSemaphoreGive(lock);
    if(due)panel_ui_history_tick(&copy,now_ms);
    if(atomic_load(&display_asleep))return;
    /* The time of day, read here and not kept in state: it is the clock of
     * this chip, and nothing else writes it. */
    struct tm now;
    copy.clock_set=panel_time_now(&now);
    if(copy.clock_set){
        copy.hour=now.tm_hour;copy.minute=now.tm_min;
        copy.weekday=now.tm_wday;copy.day=now.tm_mday;copy.month=now.tm_mon+1;
    }
    panel_ui_update(&copy);
}

/* The address of the wired card of the PC, taken from a status answer.
 *
 * It is learnt and not typed in. The panel needs it when the PC is off,
 * which is the one moment it cannot ask, so it reads it while the PC is up
 * and keeps it. Written only when it differs: this runs at every poll, and
 * flash that is rewritten every three seconds is flash that wears out.
 *
 * A service with no wired card sends null here and the stored address stays
 * as it was. Somebody who changes the card of their PC gets the new one at
 * the next poll. */
static void learn_wake_address(const cJSON *wake)
{
    if (!cJSON_IsObject(wake)) return;
    const cJSON *mac=cJSON_GetObjectItemCaseSensitive(wake,"mac");
    if (!cJSON_IsString(mac) || !mac->valuestring) return;
    uint8_t unused[PANEL_WOL_MAC_BYTES];
    if (!panel_wol_parse(mac->valuestring,unused)) {
        ESP_LOGW("panel_wol","the PC sent an address this cannot read");
        return;
    }
    if (strcmp(config.wol_mac,mac->valuestring)==0) return;
    snprintf(config.wol_mac,sizeof(config.wol_mac),"%s",mac->valuestring);
    esp_err_t err=panel_config_save_wol(config.wol_mac);
    if (err!=ESP_OK)
        ESP_LOGW("panel_wol","could not keep the address: %s",esp_err_to_name(err));
    else
        ESP_LOGI("panel_wol","the PC wakes at %s",config.wol_mac);
    xSemaphoreTake(lock,portMAX_DELAY);
    state.can_wake=true;
    xSemaphoreGive(lock);
}

/* The magic packet, sent by the panel and not by the PC.
 *
 * This is the one thing the panel does without the service, because the
 * service is not there when it is wanted. Nothing signs it and nothing can:
 * a magic packet is six bytes of 0xFF and an address sixteen times over,
 * and anybody on this network can send one. That is Wake on LAN, and not a
 * hole of ours. See panel_wol.c.
 *
 * Twice, to two addresses. The all-ones broadcast is what everybody writes
 * and some access points drop. The broadcast of this subnet, which the
 * panel works out from its own address and mask, goes through where that
 * one does not. */
static bool wake_the_pc(void)
{
    uint8_t address[PANEL_WOL_MAC_BYTES];
    uint8_t packet[PANEL_WOL_PACKET_BYTES];
    if (!panel_wol_parse(config.wol_mac,address)) return false;
    if (panel_wol_packet(address,packet,sizeof(packet))!=sizeof(packet)) return false;

    int sock=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    if (sock<0) return false;
    int yes=1;
    setsockopt(sock,SOL_SOCKET,SO_BROADCAST,&yes,sizeof(yes));

    uint32_t targets[2]={0xFFFFFFFFu,0xFFFFFFFFu};
    esp_netif_ip_info_t info;
    esp_netif_t *netif=esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (netif && esp_netif_get_ip_info(netif,&info)==ESP_OK && info.ip.addr)
        targets[1]=info.ip.addr | ~info.netmask.addr;

    bool sent=false;
    for (int i=0;i<2;i++) {
        if (i==1 && targets[1]==targets[0]) break;
        struct sockaddr_in where={0};
        where.sin_family=AF_INET;
        where.sin_port=htons(PANEL_WOL_PORT);
        where.sin_addr.s_addr=targets[i];
        if (sendto(sock,packet,sizeof(packet),0,
                   (struct sockaddr *)&where,sizeof(where))==(int)sizeof(packet))
            sent=true;
    }
    close(sock);
    ESP_LOGI("panel_wol","wake for %s: %s",config.wol_mac,sent?"sent":"refused");
    return sent;
}

static void action_send(panel_action_t action)
{
    if (xQueueSend(actions,&action,0)!=pdTRUE) {
        xSemaphoreTake(lock,portMAX_DELAY);
        snprintf(state.message,sizeof(state.message),panel_text(TXT_WAIT));
        xSemaphoreGive(lock);
    }
}

/* The change of the page of the LED bar that waits for the network task,
 * as panel_led.h says: an empty key or colour, and a brightness below
 * nought, keep what the PC has. Under the lock. A second change before the
 * task takes the first adds to it, so a change of each mode, of the colour
 * and of the brightness in quick turn goes as one. */
static panel_led_change_t led_wanted={.brightness=-1};
static bool led_due;

/* From the LVGL task. See panel_ui_led_use. */
static void led_change(const panel_led_change_t *change)
{
    xSemaphoreTake(lock,portMAX_DELAY);
    for (int mode=0; mode<PANEL_LED_MODES; mode++)
        if (change->effect[mode][0])
            snprintf(led_wanted.effect[mode],sizeof(led_wanted.effect[mode]),"%s",change->effect[mode]);
    if (change->colour[0])
        snprintf(led_wanted.colour,sizeof(led_wanted.colour),"%s",change->colour);
    if (change->brightness>=0) led_wanted.brightness=change->brightness;
    led_due=true;
    xSemaphoreGive(lock);
}

/* The profile of the page of the CPU that waits for the network task, or
 * -1. Under the lock. A second tap before the task takes the first one
 * replaces it: the last tap is what somebody wants. */
static int cpu_wanted=-1;

/* From the LVGL task. See panel_ui_cpu_use. */
static void cpu_change(int profile)
{
    xSemaphoreTake(lock,portMAX_DELAY);
    cpu_wanted=profile;
    xSemaphoreGive(lock);
}

static bool connected(void)
{
    xSemaphoreTake(lock,portMAX_DELAY); bool result=state.wifi && !state.setup; xSemaphoreGive(lock);
    return result;
}

// The nonce that the service last gave out, and the name it sends it under.
//
// One buffer and no lock. esp_http_client_perform is synchronous and the
// poll task is the only caller, so the header arrives on the task that is
// waiting for it. Empty at the first request after a start, which the
// service answers with 401 and a fresh nonce. See request().
#define PANEL_NONCE_HEADER "X-Panel-Nonce"
#define PANEL_AUTH_HEADER "X-Panel-Auth"
static char panel_nonce[PANEL_AUTH_HEX];

static bool same_header(const char *given, const char *wanted)
{
    // The names of headers do not depend on case, and servers differ.
    for (; *given && *wanted; given++, wanted++) {
        char a=*given, b=*wanted;
        if (a>='A' && a<='Z') a=(char)(a-'A'+'a');
        if (b>='A' && b<='Z') b=(char)(b-'A'+'a');
        if (a!=b) return false;
    }
    return *given==0 && *wanted==0;
}

/* Every answer carries the next nonce, and both readers below need it.
 * A reader that forgets one costs the panel a 401 on whatever it asks
 * next, which it then recovers from at the price of a round trip. */
static void remember_nonce(esp_http_client_event_t *event)
{
    if (event->header_key && event->header_value
        && same_header(event->header_key,PANEL_NONCE_HEADER)) {
        size_t length=strlen(event->header_value);
        if (length>0 && length<sizeof(panel_nonce))
            memcpy(panel_nonce,event->header_value,length+1);
    }
}

static esp_err_t collect_data(esp_http_client_event_t *event)
{
    if (event->event_id==HTTP_EVENT_ON_HEADER) {
        remember_nonce(event);
        return ESP_OK;
    }
    if (event->event_id==HTTP_EVENT_ON_DATA) {
        response_t *out=event->user_data;
        if (event->data_len<0 || out->length+(size_t)event->data_len>=sizeof(out->data)) {
            out->overflow=true;
            return ESP_FAIL;
        }
        memcpy(out->data+out->length,event->data,event->data_len);
        out->length+=event->data_len;
        out->data[out->length]=0;
    }
    return ESP_OK;
}

// How the last attempt ended, for the line that says the PC stopped
// answering. The network task alone writes and reads it.
static esp_err_t last_http_error;

// How long a request waits for its answer. A change of the LED bar or the
// CPU waits longer: the service answers it once the applier of the module
// is done, and the LED service then runs again, which takes a second or two.
#define PANEL_ASK_MS 4000
#define PANEL_CHANGE_WAIT_MS 15000
#define PANEL_LED_PATH "/v1/led"
#define PANEL_CPU_PATH "/v1/cpu"

// One attempt. The token itself never goes on the wire: what goes is a
// signature over the method, the path and the body, with the nonce that the
// service last gave out. See panel_auth.h.
//
// A body makes it a POST, and no body a GET.
static int attempt(const char *path, const char *body, int wait_ms, response_t *out)
{
    char url[224], auth[PANEL_AUTH_HEX];
    const char *payload=body ? body : "";
    memset(out,0,sizeof(*out));
    snprintf(url,sizeof(url),"%s%s",config.server,path);
    esp_http_client_config_t cfg={.url=url,.timeout_ms=wait_ms,.event_handler=collect_data,.user_data=out,.disable_auto_redirect=true};
    esp_http_client_handle_t client=esp_http_client_init(&cfg);
    if (!client) return 0;
    if (panel_auth_sign(config.token,body ? "POST" : "GET",path,panel_nonce,
                        payload,strlen(payload),auth)) {
        esp_http_client_set_header(client,PANEL_NONCE_HEADER,panel_nonce);
        esp_http_client_set_header(client,PANEL_AUTH_HEADER,auth);
    }
    if (body) {
        esp_http_client_set_method(client,HTTP_METHOD_POST);
        esp_http_client_set_header(client,"Content-Type","application/json");
        esp_http_client_set_post_field(client,payload,strlen(payload));
    }
    int64_t began=esp_timer_get_time();
    esp_err_t err=esp_http_client_perform(client);
    out->took_us=esp_timer_get_time()-began;
    int status=esp_http_client_get_status_code(client);
    /* A 401 is an answer and not a failure. esp_http_client takes it for
     * HTTP authentication of its own, finds no header for that and fails
     * the request (esp_http_client_add_auth in ESP-IDF 5.5.5). Its status
     * is still the 401 of the service, with the fresh nonce in it, and
     * request() and the message on the screen are written for exactly
     * that. Taking the error alone turned it into "no answer". */
    int code=out->overflow ? 0 : err==ESP_OK || status==401 ? status : 0;
    last_http_error=err;
    esp_http_client_cleanup(client);
    return code;
}

/* The sensors of one tile to choose from, up to PANEL_SENSORS. A service
 * older than this firmware sends none, and the menu then offers the
 * choice of the service alone. */
static int sensors_read(panel_sensor_t *out,const cJSON *list)
{
    memset(out,0,sizeof(panel_sensor_t)*PANEL_SENSORS);
    int count=0;
    cJSON *item;
    cJSON_ArrayForEach(item,list){
        if(count>=PANEL_SENSORS)break;
        const cJSON *id=cJSON_GetObjectItemCaseSensitive(item,"id");
        const cJSON *name=cJSON_GetObjectItemCaseSensitive(item,"name");
        if(!cJSON_IsString(id)||!id->valuestring[0])continue;
        panel_sensor_t *sensor=&out[count++];
        snprintf(sensor->id,sizeof sensor->id,"%s",id->valuestring);
        snprintf(sensor->name,sizeof sensor->name,"%s",
                 cJSON_IsString(name)&&name->valuestring[0]?name->valuestring:id->valuestring);
        sensor->celsius=metric(item,"c",150);
    }
    return count;
}
/* A text of the page of the PC, cut to its room, or nothing. */
static void pc_text(char *out,size_t room,const cJSON *object,const char *key)
{
    const cJSON *value=cJSON_GetObjectItemCaseSensitive(object,key);
    snprintf(out,room,"%s",cJSON_IsString(value)?value->valuestring:"");
}
/* A count of the page of the PC, or -1 for none and for one past limit. */
static int pc_number(const cJSON *object,const char *key,double limit)
{
    const cJSON *value=cJSON_GetObjectItemCaseSensitive(object,key);
    return cJSON_IsNumber(value)&&value->valuedouble>=0&&value->valuedouble<=limit
        ?(int)value->valuedouble:-1;
}
/* The page of the PC out of its object. A service older than this firmware
 * sends none, and the page then shows "--" in each row. */
static void pc_read(panel_pc_t *pc,const cJSON *object)
{
    memset(pc,0,sizeof *pc);
    pc_text(pc->os,sizeof pc->os,object,"os");
    pc_text(pc->build,sizeof pc->build,object,"build");
    pc_text(pc->channel,sizeof pc->channel,object,"channel");
    pc_text(pc->kernel,sizeof pc->kernel,object,"kernel");
    pc_text(pc->cpu,sizeof pc->cpu,object,"cpu");
    pc_text(pc->gpu,sizeof pc->gpu,object,"gpu");
    /* Ten years of seconds, and a count past that is not an uptime. */
    pc->uptime_s=pc_number(object,"uptime",10.0*366*24*3600);
    pc->cpu_load=pc_number(object,"cpu_load",100);
    pc->fan_rpm=pc_number(object,"fan",100000);
    pc->gpu_fan_rpm=pc_number(object,"gpu_fan",100000);
    const cJSON *memory=cJSON_GetObjectItemCaseSensitive(object,"memory");
    const cJSON *used=cJSON_GetObjectItemCaseSensitive(memory,"used");
    const cJSON *total=cJSON_GetObjectItemCaseSensitive(memory,"total");
    if(cJSON_IsNumber(used)&&cJSON_IsNumber(total)&&total->valuedouble>0
       &&used->valuedouble>=0&&used->valuedouble<=total->valuedouble){
        pc->memory_used=(uint64_t)used->valuedouble;
        pc->memory_total=(uint64_t)total->valuedouble;
    }
    const cJSON *network=cJSON_GetObjectItemCaseSensitive(object,"network");
    pc_text(pc->ip,sizeof pc->ip,network,"ip");
    pc_text(pc->mac,sizeof pc->mac,network,"mac");
    const cJSON *kind=cJSON_GetObjectItemCaseSensitive(network,"kind");
    pc->link=!cJSON_IsString(kind)?PANEL_LINK_UNKNOWN
        :strcmp(kind->valuestring,"wired")==0?PANEL_LINK_WIRED
        :strcmp(kind->valuestring,"wireless")==0?PANEL_LINK_WIRELESS:PANEL_LINK_UNKNOWN;
    pc->link_mbit=pc_number(network,"speed",1000000);
    pc->answer_ms=-1;
}

/* The firmware of the offer, taken when panel_update_wanted says so, and
 * dropped otherwise. A service older than this firmware sends none. */
static void offer_read(const cJSON *firmware)
{
    panel_offer_t offer;
    memset(&offer,0,sizeof offer);
    const cJSON *build=cJSON_GetObjectItemCaseSensitive(firmware,"build");
    const cJSON *size=cJSON_GetObjectItemCaseSensitive(firmware,"size");
    if(cJSON_IsNumber(build)&&cJSON_IsNumber(size)&&build->valuedouble>0
       &&build->valuedouble<1e8&&size->valuedouble>0&&size->valuedouble<=PANEL_UPDATE_SLOT_BYTES){
        offer.build=(int)build->valuedouble;
        offer.size=(uint32_t)size->valuedouble;
        pc_text(offer.version,sizeof offer.version,firmware,"version");
        pc_text(offer.sha256,sizeof offer.sha256,firmware,"sha256");
        pc_text(offer.sign,sizeof offer.sign,firmware,"sign");
    }
    bool wanted=panel_update_wanted(config.token,panel_update_build(panel_ota_version()),&offer);
    if(!wanted)memset(&offer,0,sizeof offer);
    offer_taken=offer;
    const char *now=wanted?offer.version:"";
    xSemaphoreTake(lock,portMAX_DELAY);
    /* A failure belongs to the offer it failed with. Another offer, or
     * none, starts with a clean card. */
    if(strcmp(state.update.offered,now)!=0&&state.update.phase==PANEL_UPDATE_FAILED)
        state.update.phase=PANEL_UPDATE_NONE;
    snprintf(state.update.offered,sizeof state.update.offered,"%s",now);
    xSemaphoreGive(lock);
}
// A request, and the status out of the answer to a GET. A body makes it a
// POST, whose answer is its code alone.
static int request(const char *path, const char *body, int wait_ms)
{
    /* 8 KB at every poll, which the internal memory gave and took back
     * every few seconds. See panel_psram.h. */
    response_t *out=panel_psram_calloc(1,sizeof(*out));
    if (!out) return 0;
    int code=attempt(path,body,wait_ms,out);
    // 401 is the nonce, not the secret: it was spent, or the service
    // restarted and forgot it. The answer carried a fresh one, so one more
    // attempt is the whole recovery. A rejected request ran nothing, so
    // sending an action again is safe.
    if (code==401) code=attempt(path,body,wait_ms,out);
    if (code!=200 || body) { free(out); return code; }
    cJSON *root=cJSON_Parse(out->data);
    int answer_ms=(int)(out->took_us/1000);
    free(out);
    if (!cJSON_IsObject(root)) { cJSON_Delete(root); return 0; }
    cJSON *items=cJSON_GetObjectItemCaseSensitive(root,"controllers");
    cJSON *audio=cJSON_GetObjectItemCaseSensitive(root,"audio");
    cJSON *host=cJSON_GetObjectItemCaseSensitive(root,"host");
    if (!cJSON_IsArray(items)||!cJSON_IsObject(audio)||!cJSON_IsString(host)) { cJSON_Delete(root); return 0; }
    /* Up to four controllers, in the order the service sends them: the
     * head shows the first two and the page of the controllers all four.
     * A controller with no number for its battery is on the list all the
     * same, and the screen writes "--" for it. */
    panel_pad_t pads[PANEL_PADS]={0};
    int pad_count=0;
    cJSON *item;
    cJSON_ArrayForEach(item,items){
        if(pad_count>=PANEL_PADS)break;
        if(!cJSON_IsObject(item))continue;
        cJSON *battery=cJSON_GetObjectItemCaseSensitive(item,"percent");
        cJSON *name=cJSON_GetObjectItemCaseSensitive(item,"name");
        cJSON *charging=cJSON_GetObjectItemCaseSensitive(item,"status");
        panel_pad_t *pad=&pads[pad_count++];
        snprintf(pad->name,sizeof pad->name,"%s",
                 cJSON_IsString(name)&&name->valuestring[0]?name->valuestring:"Controller");
        pad->battery=cJSON_IsNumber(battery)&&battery->valueint>=0&&battery->valueint<=100
            ?battery->valueint:-1;
        // The word the service sends, and not a word of any language on
        // this screen. See panel_state_t.
        pad->charging=cJSON_IsString(charging)
            &&strcmp(charging->valuestring,"Charging")==0;
    }
    panel_pc_t pc;
    pc_read(&pc,cJSON_GetObjectItemCaseSensitive(root,"pc"));
    pc.answer_ms=answer_ms;
    offer_read(cJSON_GetObjectItemCaseSensitive(root,"firmware"));
    cJSON *volume=cJSON_GetObjectItemCaseSensitive(audio,"percent");
    cJSON *muted=cJSON_GetObjectItemCaseSensitive(audio,"muted");
    /* The second and third pages. Each one is optional: a service that is
     * older than this firmware answers without them, and the panel then
     * shows those pages empty rather than nothing at all. */
    cJSON *session=cJSON_GetObjectItemCaseSensitive(root,"session");
    cJSON *playing=cJSON_GetObjectItemCaseSensitive(root,"playing");
    cJSON *drives=cJSON_GetObjectItemCaseSensitive(root,"drives");
    /* The LED bar, for its page: an object where the PC has the LED
     * module, null where it has none, and nothing at all from a service
     * older than this firmware. The page says which of the last two it
     * is. */
    cJSON *led=cJSON_GetObjectItemCaseSensitive(root,"led");
    /* The CPU, for its page, the same way: an object where the PC has the
     * power module, null where it has none or no cpufreq, and nothing at
     * all from a service older than this firmware. */
    cJSON *cpu=cJSON_GetObjectItemCaseSensitive(root,"cpu");
    xSemaphoreTake(lock,portMAX_DELAY);
    memcpy(state.pads,pads,sizeof state.pads);
    state.pad_count=pad_count;
    state.pc=pc;
    state.volume=cJSON_IsNumber(volume) && volume->valueint>=0 && volume->valueint<=100 ? volume->valueint : -1;
    state.muted=cJSON_IsTrue(muted);
    cJSON *telemetry=cJSON_GetObjectItemCaseSensitive(root,"telemetry");
    state.cpu_temp=metric(telemetry,"cpu_c",150);
    state.gpu_temp=metric(telemetry,"gpu_c",150);
    state.gpu_watts=metric(telemetry,"gpu_w",2000);
    /* The rest of the card, for its page. The memory is bytes and passes
     * an int, so it is read off the double, both or neither. */
    state.gpu_load=metric(telemetry,"gpu_load",100);
    state.gpu_mhz=metric(telemetry,"gpu_mhz",10000);
    cJSON *vram_used=cJSON_GetObjectItemCaseSensitive(telemetry,"vram_used");
    cJSON *vram_total=cJSON_GetObjectItemCaseSensitive(telemetry,"vram_total");
    bool vram=cJSON_IsNumber(vram_used)&&cJSON_IsNumber(vram_total)&&vram_total->valuedouble>0
        &&vram_used->valuedouble>=0&&vram_used->valuedouble<=vram_total->valuedouble;
    state.vram_used=vram?(uint64_t)vram_used->valuedouble:0;
    state.vram_total=vram?(uint64_t)vram_total->valuedouble:0;
    /* Cooling Boost: true or false where the PC has LACT with a card, and
     * null or nothing at all where it has none. */
    cJSON *boost=cJSON_GetObjectItemCaseSensitive(root,"boost");
    state.boost_here=cJSON_IsBool(boost);
    state.boost_on=cJSON_IsTrue(boost);
    state.answers++;
    state.cpu_sensor_count=sensors_read(state.cpu_sensors,
        cJSON_GetObjectItemCaseSensitive(telemetry,"cpu_sensors"));
    state.gpu_sensor_count=sensors_read(state.gpu_sensors,
        cJSON_GetObjectItemCaseSensitive(telemetry,"gpu_sensors"));
    snprintf(state.host,sizeof(state.host),"%s",host->valuestring);
    /* A word the service sends and not a word of any language on the
     * screen, the same rule the charge flag follows. See panel_state_t. */
    state.game_mode=cJSON_IsString(session)
        && strcmp(session->valuestring,"game")==0;
    snprintf(state.playing,sizeof(state.playing),"%s",
             cJSON_IsString(playing)?playing->valuestring:"");
    /* The two counts, both or neither. steamapps.achievements holds the
     * same rules at its end, and this is the second reader of them rather
     * than trust in the first: a count past its total is not drawn. */
    cJSON *unlocked=cJSON_GetObjectItemCaseSensitive(root,"achievements");
    cJSON *got=cJSON_GetObjectItemCaseSensitive(unlocked,"achieved");
    cJSON *of=cJSON_GetObjectItemCaseSensitive(unlocked,"total");
    bool counts=cJSON_IsNumber(got)&&cJSON_IsNumber(of)
        &&of->valueint>0&&got->valueint>=0&&got->valueint<=of->valueint;
    state.achievements_done=counts?got->valueint:0;
    state.achievements_total=counts?of->valueint:0;
    state.drive_count=0;
    if(cJSON_IsArray(drives)){
        cJSON *one=NULL;
        cJSON_ArrayForEach(one,drives){
            if(state.drive_count>=PANEL_DRIVES)break;
            cJSON *name_of=cJSON_GetObjectItemCaseSensitive(one,"name");
            cJSON *total=cJSON_GetObjectItemCaseSensitive(one,"total");
            cJSON *room=cJSON_GetObjectItemCaseSensitive(one,"free");
            /* A drive with no size is not a drive. drives() leaves those
             * out already, and this is the second reader of the same
             * rule rather than trust in the first. */
            if(!cJSON_IsNumber(total)||total->valuedouble<=0)continue;
            panel_drive_t *into=&state.drives[state.drive_count++];
            snprintf(into->name,sizeof(into->name),"%s",
                     cJSON_IsString(name_of)?name_of->valuestring:"?");
            /* valuedouble and not valueint: a drive passes what an int
             * holds, and cJSON stores a large number in the double. */
            into->total=(uint64_t)total->valuedouble;
            into->free=cJSON_IsNumber(room)&&room->valuedouble>=0
                ?(uint64_t)room->valuedouble:0;
            if(into->free>into->total)into->free=into->total;
        }
    }
    state.cpu_known=cpu!=NULL;
    state.cpu_here=cJSON_IsObject(cpu);
    pc_text(state.cpu_profile,sizeof state.cpu_profile,cpu,"profile");
    pc_text(state.cpu_governor,sizeof state.cpu_governor,cpu,"governor");
    pc_text(state.cpu_epp,sizeof state.cpu_epp,cpu,"epp");
    pc_text(state.cpu_driver,sizeof state.cpu_driver,cpu,"driver");
    state.cpu_offers=0;
    cJSON *offered=NULL;
    cJSON_ArrayForEach(offered,cJSON_GetObjectItemCaseSensitive(cpu,"offers")){
        int profile=cJSON_IsString(offered)?panel_cpu_find(offered->valuestring):-1;
        if(profile>=0)state.cpu_offers|=(uint8_t)(1u<<profile);
    }
    state.led_known=led!=NULL;
    state.led_here=cJSON_IsObject(led);
    for(int mode=0;mode<PANEL_LED_MODES;mode++){
        cJSON *effect=cJSON_GetObjectItemCaseSensitive(led,panel_led_mode_name((panel_led_mode_t)mode));
        snprintf(state.led_effect[mode],sizeof state.led_effect[mode],"%s",
                 cJSON_IsString(effect)?effect->valuestring:"");
    }
    /* The colour and the brightness of the desktop scenes. A service older
     * than this firmware sends neither, and the page then keeps to the
     * effects. */
    cJSON *colour=cJSON_GetObjectItemCaseSensitive(led,PANEL_LED_COLOUR_KEY);
    cJSON *brightness=cJSON_GetObjectItemCaseSensitive(led,PANEL_LED_BRIGHTNESS_KEY);
    state.led_look=cJSON_IsString(colour)&&panel_led_rgb(colour->valuestring,NULL)
                   &&cJSON_IsNumber(brightness)&&brightness->valuedouble>=0
                   &&brightness->valuedouble<=255;
    snprintf(state.led_colour,sizeof state.led_colour,"%s",state.led_look?colour->valuestring:"");
    state.led_brightness=state.led_look?(int)brightness->valuedouble:-1;
    xSemaphoreGive(lock);
    learn_wake_address(cJSON_GetObjectItemCaseSensitive(root,"wake"));
    cJSON_Delete(root);
    return 200;
}

/* A change of the LED bar, sent to the PC. Answers the HTTP code, and
 * nought for nothing to send. */
static int led_request(const panel_led_change_t *change)
{
    char body[160];
    if (!panel_led_body(body,sizeof(body),change)) return 0;
    return request(PANEL_LED_PATH,body,PANEL_CHANGE_WAIT_MS);
}

/* What a disconnect number means, in words.
 *
 * Every one of these has cost somebody a search through a header. The list
 * holds the ones this panel has really reported and the neighbours that
 * mean something different enough to act on. Anything else still prints as
 * its number, which is what wifi_err_reason_t is indexed by. */
static const char *wifi_reason_name(uint8_t reason)
{
    switch (reason) {
    case 4:   return "the AP dropped an idle station";
    /* The sender leaves the network. Read off the board, it is the panel
     * itself when it stops its radio for the rest, and wifi_event says so
     * without a warning then. */
    case 8:   return "the sender left the network";
    case 15:  return "the four way handshake timed out";
    case 16:  return "the group key update timed out";
    case 23:  return "802.1X refused it";
    case 200: return "the beacons stopped";
    case 201: return "no AP of this name was found";
    case 202: return "authentication failed";
    case 203: return "association failed";
    case 204: return "the handshake timed out";
    case 205: return "the connection failed";
    default:  return "see wifi_err_reason_t";
    }
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base==WIFI_EVENT && id==WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event=data;
        /* The disconnect of a radio rest is the panel leaving on purpose,
         * and the board showed it as a warning. */
        if (atomic_load(&radio_resting))
            ESP_LOGI("panel_wifi","Disconnected for the radio rest, reason=%u: %s",
                     event->reason,wifi_reason_name(event->reason));
        else
            ESP_LOGW("panel_wifi","Disconnected, reason=%u: %s",
                     event->reason,wifi_reason_name(event->reason));
        xSemaphoreTake(lock,portMAX_DELAY);
        state.wifi=false; state.online=false;
        bool reconnect=!state.setup && !atomic_load(&radio_resting);
        xSemaphoreGive(lock);
        if (reconnect) esp_wifi_connect();
    }
    if (base==IP_EVENT && id==IP_EVENT_STA_GOT_IP) {
        xSemaphoreTake(lock,portMAX_DELAY); state.wifi=true; xSemaphoreGive(lock);
        unsigned back=atomic_exchange(&radio_back_ms,0u);
        if (back)
            ESP_LOGI("panel_wifi","Joined again %u ms after the radio came back",
                     (unsigned)esp_log_timestamp()-back);
    }
}

static void portal_start(void)
{
    xSemaphoreTake(lock,portMAX_DELAY);
    state.setup=true; state.online=false; state.wifi=false;
    xSemaphoreGive(lock);
    char ssid[32], password[32];
    ESP_ERROR_CHECK(panel_config_portal(ssid,sizeof(ssid),password,sizeof(password)));
    xSemaphoreTake(lock,portMAX_DELAY);
    snprintf(state.setup_ssid,sizeof(state.setup_ssid),"%s",ssid);
    snprintf(state.setup_password,sizeof(state.setup_password),"%s",password);
    xSemaphoreGive(lock);
}

/* Stop the radio or start it again, from the network task alone.
 *
 * esp_wifi_stop and esp_wifi_start wait for the driver, and the task that
 * draws must not wait. Called once for each change of what is wanted, so a
 * call that fails writes one warning and not one every turn of the loop.
 * The configuration stays in the driver over a stop, and the start finds
 * the same network with the same rules as the first join. */
static void radio_rest(bool rest)
{
    if (rest) {
        atomic_store(&radio_resting,true);
        atomic_store(&radio_back_ms,0u);
        esp_err_t err=esp_wifi_stop();
        if (err!=ESP_OK) {
            atomic_store(&radio_resting,false);
            ESP_LOGW("panel_wifi","The radio did not stop: %s",esp_err_to_name(err));
            return;
        }
        xSemaphoreTake(lock,portMAX_DELAY);
        state.wifi=false; state.online=false;
        xSemaphoreGive(lock);
        ESP_LOGI("panel_wifi","Radio off while the display sleeps by the button");
        return;
    }
    if (!atomic_load(&radio_resting)) return;
    atomic_store(&radio_resting,false);
    atomic_store(&radio_back_ms,(unsigned)esp_log_timestamp());
    esp_err_t err=esp_wifi_start();
    if (err==ESP_OK) err=esp_wifi_connect();
    if (err!=ESP_OK) {
        atomic_store(&radio_back_ms,0u);
        ESP_LOGW("panel_wifi","The radio did not start again: %s",esp_err_to_name(err));
        return;
    }
    ESP_LOGI("panel_wifi","Radio on again, joining the network");
}

/* The nonce of an answer and nothing else, for the download of a firmware:
 * its body goes to the slot and not to a buffer. */
static esp_err_t nonce_only(esp_http_client_event_t *event)
{
    if (event->event_id==HTTP_EVENT_ON_HEADER) remember_nonce(event);
    return ESP_OK;
}
static void update_phase(panel_update_phase_t phase,int percent,panel_text_id_t failure)
{
    xSemaphoreTake(lock,portMAX_DELAY);
    state.update.phase=phase;state.update.percent=percent;state.update.failure=failure;
    xSemaphoreGive(lock);
}
/* The image of the offer, from the PC into the other slot.
 *
 * Signed like every other request, with the nonce of the last answer, and
 * once more on a 401, which carries a fresh one. The slot was erased
 * before this asks, so the blocks go to the flash as fast as they come and
 * the service never waits long on one. */
static bool download(const panel_offer_t *offer,panel_text_id_t *why)
{
    *why=TXT_UPDATE_NO_ANSWER;
    for(int round=0;round<2;round++){
        char url[224],auth[PANEL_AUTH_HEX];
        snprintf(url,sizeof(url),"%s%s",config.server,PANEL_UPDATE_PATH);
        esp_http_client_config_t cfg={.url=url,.timeout_ms=10000,.event_handler=nonce_only,
                                      .disable_auto_redirect=true,.buffer_size=4096};
        esp_http_client_handle_t client=esp_http_client_init(&cfg);
        if(!client)return false;
        if(panel_auth_sign(config.token,"GET",PANEL_UPDATE_PATH,panel_nonce,"",0,auth)){
            esp_http_client_set_header(client,PANEL_NONCE_HEADER,panel_nonce);
            esp_http_client_set_header(client,PANEL_AUTH_HEADER,auth);
        }
        if(esp_http_client_open(client,0)!=ESP_OK){
            esp_http_client_cleanup(client);
            return false;
        }
        int64_t length=esp_http_client_fetch_headers(client);
        int status=esp_http_client_get_status_code(client);
        if(status==401&&round==0){
            esp_http_client_close(client);esp_http_client_cleanup(client);
            continue;
        }
        if(status!=200||length!=(int64_t)offer->size){
            ESP_LOGW("panel_update","The PC answered %d with %" PRId64 " bytes for %" PRIu32,
                     status,length,offer->size);
            esp_http_client_close(client);esp_http_client_cleanup(client);
            return false;
        }
        char *block=malloc(PANEL_UPDATE_BLOCK);
        if(!block)*why=TXT_UPDATE_WRITE;
        uint32_t got=0;
        int shown=-1;
        while(block&&got<offer->size){
            int read=esp_http_client_read(client,block,PANEL_UPDATE_BLOCK);
            if(read<=0)break;
            if(panel_ota_write(block,(size_t)read)!=ESP_OK){*why=TXT_UPDATE_WRITE;break;}
            got+=(uint32_t)read;
            int percent=(int)((uint64_t)got*100/offer->size);
            if(percent!=shown){shown=percent;update_phase(PANEL_UPDATE_RUNNING,percent,TXT_UPDATE_FAILED);}
        }
        free(block);
        esp_http_client_close(client);esp_http_client_cleanup(client);
        return got==offer->size;
    }
    return false;
}
/* An update, from the tap on the panel to the restart.
 *
 * The power is asked again here and not only on the screen, which can be
 * a few seconds behind. A failure leaves the running firmware as it was
 * and says why on the page of the panel; the offer stays, so a tap tries
 * again. */
static void firmware_update(void)
{
    panel_offer_t offer=offer_taken;
    if(!offer.build)return;
    xSemaphoreTake(lock,portMAX_DELAY);
    bool on_battery=state.esp_supply==PANEL_SUPPLY_BATTERY&&!state.esp_cable;
    int percent=state.esp_battery;bool charging=state.esp_charging;
    bool online=state.online;
    xSemaphoreGive(lock);
    if(!panel_update_power_ok(on_battery,percent,charging)){
        update_phase(PANEL_UPDATE_FAILED,0,TXT_UPDATE_POWER);
        return;
    }
    if(!online||!connected()){
        update_phase(PANEL_UPDATE_FAILED,0,TXT_UPDATE_NO_ANSWER);
        return;
    }
    atomic_store(&updating,true);
    update_phase(PANEL_UPDATE_RUNNING,0,TXT_UPDATE_FAILED);
    ESP_LOGI("panel_update","Updating from %s to %s",panel_ota_version(),offer.version);
    panel_text_id_t why=TXT_UPDATE_WRITE;
    if(panel_ota_begin(offer.size)==ESP_OK&&download(&offer,&why)){
        esp_err_t err=panel_ota_finish(offer.sha256);
        if(err==ESP_OK){
            update_phase(PANEL_UPDATE_RESTARTING,100,TXT_UPDATE_FAILED);
            ESP_LOGI("panel_update","%s is written; restarting into it",offer.version);
            /* Long enough to read that it restarts. */
            vTaskDelay(pdMS_TO_TICKS(2500));
            esp_restart();
        }
        why=err==ESP_ERR_INVALID_CRC||err==ESP_ERR_INVALID_SIZE||err==ESP_ERR_OTA_VALIDATE_FAILED
            ?TXT_UPDATE_BROKEN:TXT_UPDATE_WRITE;
    }
    panel_ota_abort();
    ESP_LOGW("panel_update","The update to %s failed; %s stays",offer.version,panel_ota_version());
    update_phase(PANEL_UPDATE_FAILED,0,why);
    atomic_store(&updating,false);
}
/* The panel itself, for its page: the firmware, the network and the
 * memory. With the battery, every five seconds. */
static void self_read(void)
{
    panel_self_t self;
    memset(&self,0,sizeof self);
    snprintf(self.version,sizeof self.version,"%s",panel_ota_version());
    snprintf(self.ssid,sizeof self.ssid,"%s",config.ssid);
    const char *server=config.server;
    if(strncmp(server,"http://",7)==0)server+=7;
    snprintf(self.server,sizeof self.server,"%.63s",server);
    esp_netif_t *netif=esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    esp_netif_ip_info_t info;
    if(netif&&esp_netif_get_ip_info(netif,&info)==ESP_OK&&info.ip.addr)
        snprintf(self.ip,sizeof self.ip,IPSTR,IP2STR(&info.ip));
    uint8_t mac[6];
    if(esp_wifi_get_mac(WIFI_IF_STA,mac)==ESP_OK)
        snprintf(self.mac,sizeof self.mac,"%02x:%02x:%02x:%02x:%02x:%02x",
                 mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    wifi_ap_record_t ap;
    if(connected()&&esp_wifi_sta_get_ap_info(&ap)==ESP_OK)self.rssi=ap.rssi;
    self.uptime_s=(uint32_t)(esp_timer_get_time()/1000000);
    self.heap_free=(uint32_t)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
    self.heap_least=(uint32_t)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
    self.psram_free=(uint32_t)heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    xSemaphoreTake(lock,portMAX_DELAY);state.self=self;xSemaphoreGive(lock);
}

/* The priority of the network task: under the thread that draws, which
 * LVGL starts at tskIDLE_PRIORITY plus CONFIG_LV_DRAW_THREAD_PRIO (see
 * lv_thread_init in lv_freertos.c). The build stops if the two meet. */
#define PANEL_NETWORK_PRIORITY 3
_Static_assert(PANEL_NETWORK_PRIORITY<tskIDLE_PRIORITY+CONFIG_LV_DRAW_THREAD_PRIO,
               "the network task stands above the thread that draws");

static void network_task(void *arg)
{
    (void)arg;
    if (!config.ssid[0]) portal_start();
    /* Indexed by panel_action_t, and it has to hold every action below
     * PANEL_SETUP. The guard further down is that range, so a name added
     * to the enum and not to this table makes every button under it send
     * the name of another one. tests/test_panel_pages.py holds the two
     * lengths equal. */
    const char *names[]={"volume_down","mute","volume_up","suspend","reboot",
                         "poweroff","desktop_mode","game_mode","gpu_boost_on",
                         "gpu_boost_off"};
    TickType_t last_poll=xTaskGetTickCount()-pdMS_TO_TICKS(3000);
    TickType_t feedback_until=0;
    TickType_t last_health=xTaskGetTickCount();
    /* Due at once, so the corner of the screen fills at the first turn
     * and not five seconds after the rest. */
    TickType_t last_battery=xTaskGetTickCount()-pdMS_TO_TICKS(5000);
    bool rest_wanted=false,was_connected=false,trial_over=false;
    /* The answer of the last poll, for the line when it changes. */
    int answered=-1;
    for (;;) {
        /* A reading of the clock at every turn of this loop, which is ten a
         * second or so. See panel_clock_sample. */
        panel_clock_sample();
        /* The clock chip takes the time of a server that just answered. */
        panel_time_keep();
        /* The radio rests while the display sleeps by the button, and not
         * during the setup: a phone talks to the access point of the setup,
         * whatever the screen does. */
        xSemaphoreTake(lock,portMAX_DELAY); bool setup=state.setup; xSemaphoreGive(lock);
        bool rest=atomic_load(&asleep_by_hand) && !setup;
        if (rest!=rest_wanted) { rest_wanted=rest; radio_rest(rest); }
        /* Ask the PC as soon as the network is there, and not up to three
         * seconds later. After a rest that is the wait somebody sees. */
        bool now_connected=connected();
        if (now_connected && !was_connected)
            last_poll=xTaskGetTickCount()-pdMS_TO_TICKS(3000);
        was_connected=now_connected;
        /* The battery of the panel.
         *
         * Here and not in the LVGL timer. This is an I2C read on the bus
         * the touch and the codec share, and a bus that stalls must stall
         * this task and not the one that draws. Every five seconds,
         * because a gauge moves by the minute and a cable is plugged in
         * by hand: five seconds is before anybody looks twice. */
        if(xTaskGetTickCount()-last_battery>=pdMS_TO_TICKS(5000)){
            last_battery=xTaskGetTickCount();
            panel_supply_t supply;int percent;bool charging;
            panel_battery_read(&supply,&percent,&charging);
            bool cable=panel_battery_cable();
            /* The voltages, the temperature of the chip and its charger,
             * for the page of the panel. */
            panel_power_detail_t detail;
            panel_battery_detail(&detail);
            self_read();
            xSemaphoreTake(lock,portMAX_DELAY);
            panel_supply_t was=state.esp_supply;
            state.esp_supply=supply;state.esp_battery=percent;
            state.esp_charging=charging;state.esp_cable=cable;
            state.esp_detail=detail;
            xSemaphoreGive(lock);
            /* A line when the supply changes and not at every reading: a
             * cable in or out is an event, a gauge at 87 is not. */
            if(supply!=was && was!=PANEL_SUPPLY_UNKNOWN)
                ESP_LOGI("panel_battery","now on %s",
                         supply==PANEL_SUPPLY_BATTERY?"its cell":
                         supply==PANEL_SUPPLY_CABLE?"its cable":
                         "nothing the chip reports");
        }
        if(xTaskGetTickCount()-last_health>=pdMS_TO_TICKS(30000)){
            last_health=xTaskGetTickCount();
            uint32_t now_ms=(uint32_t)(esp_timer_get_time()/1000);
            unsigned clock_mhz=0,clock_low=0;
            panel_clock_average(&clock_mhz,&clock_low);
            xSemaphoreTake(lock,portMAX_DELAY);
            bool wifi=state.wifi,online=state.online;
            panel_frame_stats_t frames=health_frames;
            xSemaphoreGive(lock);
            ESP_LOGI("panel_health","up=%" PRIu32 "s ui_age=%" PRIu32 "ms heap=%u internal=%u internal_min=%u largest=%u min=%u net_stack=%u ui_stack=%u/%u wifi=%d pc=%d standby=%d radio_rest=%d cpu_avg=%uMHz low=%u%% key_slowest=%ums frames=%u fps=%d gap=%d/%d/%dms draw=%d/%d/%dms lead=%d/%d/%dms periods=%d/%d/%d/%d%%",
                now_ms/1000,now_ms-atomic_load(&ui_heartbeat_ms),
                (unsigned)esp_get_free_heap_size(),
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
                /* The least internal memory since the start, which says
                 * what room a change that takes some of it has. */
                (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
                (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
                (unsigned)esp_get_minimum_free_heap_size(),
                (unsigned)uxTaskGetStackHighWaterMark(NULL),
                /* The thinnest the drawing task has been, against what it
                 * was given. See watch_stack. */
                atomic_load(&ui_stack_left),
                (unsigned)panel_display_stack_bytes(),wifi,online,
                atomic_load(&display_asleep),atomic_load(&radio_resting),
                /* The mean speed of the clock since the last line, and the
                 * share of that time at the low speed. See
                 * panel_clock_average. */
                clock_mhz,clock_low,
                /* The slowest turn of the key loop since the last line.
                 * The shortest press the panel can see is about twice
                 * this, so a number far above PWRKEY_PERIOD_MS is why a
                 * press did nothing. See panel_power.c. */
                (unsigned)panel_power_slowest_read_ms(),
                /* The frames in movement since the page of the panel was
                 * last closed: mean, 95th percentile and most, and the
                 * share that took one, two, three, and four or more
                 * frames of the panel. */
                (unsigned)frames.frames,frames.fps,
                frames.interval_mean_ms,frames.interval_p95_ms,frames.interval_most_ms,
                frames.draw_mean_ms,frames.draw_p95_ms,frames.draw_most_ms,
                frames.lead_mean_ms,frames.lead_p95_ms,frames.lead_most_ms,
                frames.periods_pct[0],frames.periods_pct[1],frames.periods_pct[2],
                frames.periods_pct[3]);
        }
        panel_action_t action;
        if (xQueueReceive(actions,&action,pdMS_TO_TICKS(100))==pdTRUE) {
            if (action==PANEL_SETUP) { portal_start(); continue; }
            if (action==PANEL_UPDATE) {
                firmware_update();
                last_poll=xTaskGetTickCount()-pdMS_TO_TICKS(3000);
                continue;
            }
            if (action==PANEL_WAKE) {
                bool sent=wake_the_pc();
                xSemaphoreTake(lock,portMAX_DELAY);
                snprintf(state.message,sizeof(state.message),"%s",
                         sent?panel_text(TXT_WAKE_SENT):panel_text(TXT_WAKE_FAILED));
                xSemaphoreGive(lock);
                feedback_until=xTaskGetTickCount()+pdMS_TO_TICKS(5000);
                /* Ask again soon. A machine that woke answers in seconds,
                 * and waiting the full three for the next poll reads as a
                 * button that did nothing. */
                last_poll=xTaskGetTickCount()-pdMS_TO_TICKS(2000);
                continue;
            }
            xSemaphoreTake(lock,portMAX_DELAY); bool online=state.online; xSemaphoreGive(lock);
            if (online && connected() && action>=0 && action<PANEL_SETUP) {
                char body[64];
                snprintf(body,sizeof(body),"{\"action\":\"%s\"}",names[action]);
                int code=request("/v1/action",body,PANEL_ASK_MS);
                xSemaphoreTake(lock,portMAX_DELAY);
                snprintf(state.message,sizeof(state.message),"%s",code==200 ? panel_text(TXT_SENT) : code==401 ? panel_text(TXT_CHECK_TOKEN) : panel_text(TXT_NOT_CONFIRMED));
                xSemaphoreGive(lock);
                feedback_until=xTaskGetTickCount()+pdMS_TO_TICKS(5000);
                last_poll=xTaskGetTickCount()-pdMS_TO_TICKS(3000);
            }
        }
        /* A change of the page of the LED bar. The page takes back a
         * change that did not go out, so one with no network to go over
         * gets an answer of nought. The poll comes at once after it, so
         * the page shows the effect the PC really has. */
        xSemaphoreTake(lock,portMAX_DELAY);
        bool led_now=led_due;
        panel_led_change_t led_next=led_wanted;
        led_wanted=(panel_led_change_t){.brightness=-1};
        led_due=false;
        bool led_online=state.online;
        xSemaphoreGive(lock);
        if (led_now) {
            int code=led_online && connected() ? led_request(&led_next) : 0;
            ESP_LOGI("panel_led","desktop=%s game=%s colour=%s brightness=%d: %d",
                     led_next.effect[PANEL_LED_DESKTOP][0]?led_next.effect[PANEL_LED_DESKTOP]:"-",
                     led_next.effect[PANEL_LED_GAME][0]?led_next.effect[PANEL_LED_GAME]:"-",
                     led_next.colour[0]?led_next.colour:"-",led_next.brightness,code);
            xSemaphoreTake(lock,portMAX_DELAY);
            state.led_code=code;
            state.led_replies++;
            xSemaphoreGive(lock);
            last_poll=xTaskGetTickCount()-pdMS_TO_TICKS(3000);
        }
        /* A profile of the page of the CPU, the same way. */
        xSemaphoreTake(lock,portMAX_DELAY);
        int cpu_now=cpu_wanted;
        cpu_wanted=-1;
        bool cpu_online=state.online;
        xSemaphoreGive(lock);
        if (cpu_now>=0) {
            char body[48];
            int code=0;
            if (cpu_online && connected() && panel_cpu_body(body,sizeof(body),cpu_now))
                code=request(PANEL_CPU_PATH,body,PANEL_CHANGE_WAIT_MS);
            ESP_LOGI("panel_cpu","profile=%s: %d",panel_cpu_key(cpu_now),code);
            xSemaphoreTake(lock,portMAX_DELAY);
            state.cpu_code=code;
            state.cpu_replies++;
            xSemaphoreGive(lock);
            last_poll=xTaskGetTickCount()-pdMS_TO_TICKS(3000);
        }
        if (!atomic_load(&radio_resting) &&
            xTaskGetTickCount()-last_poll>=pdMS_TO_TICKS(3000)) {
            last_poll=xTaskGetTickCount();
            int code=connected() ? request("/v1/status",NULL,PANEL_ASK_MS) : 0;
            /* A firmware on trial is kept once the PC answered it: it
             * starts, draws, joins the network and talks to the service.
             * Until then a restart goes back to the firmware before it.
             * See panel_ota.h. */
            if (code==200 && !trial_over) { trial_over=true; panel_ota_confirm(); }
            xSemaphoreTake(lock,portMAX_DELAY);
            state.online=code==200;
            /* Something to say, and nothing where there is nothing.
             *
             * This line used to carry the state of the connection at
             * every poll: up to date, no answer, joining the network. The
             * screen shows that now without words, a mark for the network
             * at the bottom and the state of the PC at the top, and a
             * sentence that says the same thing again is one somebody
             * learns to read past. So the line stays empty, and what
             * reaches it is what neither mark can say: the token the PC
             * refused, and the answer to a button, which is written above
             * and held for five seconds. */
            if ((int32_t)(xTaskGetTickCount()-feedback_until)>=0)
                snprintf(state.message,sizeof(state.message),"%s",
                         code==401 ? panel_text(TXT_CHECK_SETUP) : "");
            xSemaphoreGive(lock);
            /* A line when the answer of the PC changes, and not at every
             * poll. esp_http_client is quiet now, see app_main, and this
             * says once what it said at every poll. */
            if (code!=answered) {
                answered=code;
                if (code==200)
                    ESP_LOGI("panel_pc","The PC answers");
                else if (code==401)
                    ESP_LOGW("panel_pc","The PC refuses this panel: the token "
                             "of the setup does not match");
                else if (code==0 && !connected())
                    ESP_LOGI("panel_pc","No network, so no question to the PC");
                else if (code==0)
                    ESP_LOGW("panel_pc","The PC does not answer: %s",
                             last_http_error==ESP_OK
                                 ? "an answer this panel could not read"
                                 : esp_err_to_name(last_http_error));
                else
                    ESP_LOGW("panel_pc","The PC answers %d",code);
            }
        }
    }
}

/* How long each step of joining the network takes.
 *
 * Read off the board: between "wifi driver task" and "wifi firmware
 * version", two lines the driver prints from inside esp_wifi_init, the log
 * held a hole of 2.9 seconds in one run and 6.8 and 7.2 in two more. A
 * hundred milliseconds is the usual figure for that call.
 *
 * The hole is inside one call and no step here was ever timed, so which
 * call it is has been a guess. This times each one and says so when it is
 * slow. A healthy start prints the total and nothing else.
 *
 * Fifty milliseconds, because these calls set registers and allocate, and
 * none of them has an honest reason to take longer. */
#define WIFI_STEP_LOUD_MS 50
#define WIFI_STEP(what, call) do { \
        uint32_t at__=esp_log_timestamp(); \
        call; \
        uint32_t spent__=esp_log_timestamp()-at__; \
        if(spent__>=WIFI_STEP_LOUD_MS) \
            ESP_LOGW("panel_wifi","%s took %u ms",what,(unsigned)spent__); \
    } while (0)

/* Why the panel started, in words.
 *
 * The number was here before and nobody can read it. This line is the
 * first thing in the log and the only thing that says what happened the
 * last time round, which matters because a person reaches for the cable
 * after the fault and not before it.
 *
 * The four that are worth telling apart: a panic is a fault in this
 * firmware, a watchdog is work that did not finish, a brownout is the
 * power supply and not the code at all, and a power-on is somebody at the
 * wall socket. */
static const char *reset_reason_name(esp_reset_reason_t reason)
{
    switch (reason) {
    case ESP_RST_POWERON:  return "power came on";
    case ESP_RST_EXT:      return "the reset pin";
    case ESP_RST_SW:       return "this firmware asked for it";
    case ESP_RST_PANIC:    return "a panic, so a fault in this firmware";
    case ESP_RST_INT_WDT:  return "the interrupt watchdog";
    case ESP_RST_TASK_WDT: return "the task watchdog, so work that ran long";
    case ESP_RST_WDT:      return "another watchdog";
    case ESP_RST_DEEPSLEEP:return "deep sleep ended";
    case ESP_RST_BROWNOUT: return "a brownout, so the power supply";
    case ESP_RST_SDIO:     return "SDIO";
    default:               return "see esp_reset_reason_t";
    }
}

/* The internal memory free after each step of the start, in KB, for one
 * line of the log at its end. Asked for: where the internal memory goes.
 * The health line says the least since the start, and this says which
 * step took what. */
static char ram_steps[320];
static void ram_step(const char *step)
{
    size_t used=strlen(ram_steps);
    snprintf(ram_steps+used,sizeof ram_steps-used," %s=%u",step,
             (unsigned)(heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)/1024));
}
/* The JSON of the answers of the PC out of PSRAM: hundreds of small
 * blocks at every poll. See panel_psram.h. */
static void *json_alloc(size_t size){return panel_psram_malloc(size);}

void app_main(void)
{
    esp_reset_reason_t why=esp_reset_reason();
    ESP_LOGI("panel_boot","version=%s, started because %s (reset_reason=%d)",
             esp_app_get_description()->version,reset_reason_name(why),(int)why);
    esp_err_t err=nvs_flash_init();
    if (err==ESP_ERR_NVS_NO_FREE_PAGES || err==ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err=nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    if (!panel_config_load(&config)) memset(&config,0,sizeof(config));
    cJSON_Hooks json={.malloc_fn=json_alloc,.free_fn=heap_caps_free};
    cJSON_InitHooks(&json);
    ram_step("start");
    /* Before the display, so the full speed is held before anything draws. */
    esp_err_t clock_err=panel_clock_init();
    if (clock_err!=ESP_OK)
        ESP_LOGW("panel_clock","The clock stays at full speed: %s",
                 esp_err_to_name(clock_err));
    lock=xSemaphoreCreateMutex();
    actions=xQueueCreate(1,sizeof(panel_action_t));
    assert(lock && actions);
    state.volume=-1; state.cpu_temp=-1; state.gpu_temp=-1; state.gpu_watts=-1;
    state.gpu_load=-1; state.gpu_mhz=-1;
    state.esp_detail=(panel_power_detail_t){.vbat_mv=-1,.vbus_mv=-1,.vsys_mv=-1,
        .die_c=PANEL_NO_DEGREES,.phase=-1,.charge_ma=-1,.charge_mv=-1,.input_ma=-1};
    state.setup=config.ssid[0]==0;
    /* An address kept from an earlier run. Without this the button appears
     * only after the PC has answered once, which is the case where it is
     * needed least. */
    {
        uint8_t kept[PANEL_WOL_MAC_BYTES];
        state.can_wake=panel_wol_parse(config.wol_mac,kept);
    }
    if (!panel_display_start()) ESP_ERROR_CHECK(ESP_FAIL);
    ram_step("display");
    esp_err_t key_err=panel_power_init();
    if(key_err!=ESP_OK)ESP_LOGW("panel_power","PWRKEY unavailable: %s",esp_err_to_name(key_err));
    /* After the key, whose IO expander brings the I2C bus up. Not finding
     * the chip leaves the corner of the screen empty and nothing else. */
    panel_battery_init();
    /* The same bus, and nothing on the screen depends on it. */
    panel_motion_init();
    ram_step("sensors");
    /* The same bus, and before the screen is built: the clock page has the
     * time of the clock chip at once. See panel_time.c. */
    panel_time_start();
    panel_settings_t settings=settings_load();
    atomic_store(&lift_wake,settings.lift_wake);
    display_brightness=settings.brightness;
    display_sleep_after=settings.sleep_after;
    sounds=xQueueCreate(1,sizeof(int));
    assert(sounds);
    BaseType_t sound_created=panel_psram_task(sound_task,"panel_sound",6144,3,tskNO_AFFINITY);
    assert(sound_created==pdPASS);
    ram_step("sound");
    /* The history of the page of the card: an hour of points and what the
     * chart draws of it, about 6.5 KB. PSRAM, because the internal memory
     * is for the network and the drawing. A panel with no PSRAM to spare
     * shows the page without curves. */
    history=heap_caps_calloc(1,sizeof(panel_history_t),MALLOC_CAP_SPIRAM);
    if(history)panel_history_reset(history);
    else ESP_LOGW("panel_history","No PSRAM for the history; the page shows no curves");
    panel_ui_history_use(history);
    bsp_display_lock(0);
    panel_ui_create(action_send,setting_set,sound_send,&settings);
    panel_ui_led_use(led_change);
    panel_ui_cpu_use(cpu_change);
    lv_timer_create(ui_tick,200,NULL);
    ui_tick(NULL);
    /* Over the finished screen, not in front of building it. Everything
     * below this joins the network and waits for the PC, and the panel
     * spent those seconds showing a page with no numbers in it. Now it
     * shows the animation instead, and the page is ready underneath when
     * the animation ends. */
    panel_boot_show(boot_animation_start,
                    (size_t)(boot_animation_end-boot_animation_start));
    /* Draw it here, in this task, before the light comes up.
     *
     * The screen has been at the lowest brightness since the display
     * started, because the board support lights the panel at full over a
     * frame buffer that nothing has written, and the board showed that as a
     * flash of white. This is the first frame that is worth seeing, so the
     * light goes up after it and not before. Without lv_refr_now the frame
     * is drawn by the LVGL task at some later moment, and the brightness
     * below would beat it there. */
    lv_refr_now(NULL);
    bsp_display_unlock();
    ram_step("screen");
    setting_set(PANEL_BRIGHTNESS,settings.brightness,false);
    uint32_t network_began=esp_log_timestamp();
    WIFI_STEP("esp_netif_init",ESP_ERROR_CHECK(esp_netif_init()));
    WIFI_STEP("esp_event_loop_create_default",
              ESP_ERROR_CHECK(esp_event_loop_create_default()));
    WIFI_STEP("esp_netif_create_default_wifi_sta",
              esp_netif_create_default_wifi_sta());
    /* After the event loop, which it hangs a handler on, and before the
     * radio joins: it asks DHCP for a time server. See panel_time.c. */
    panel_time_init();
    ram_step("netif");
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();
    WIFI_STEP("esp_wifi_init",ESP_ERROR_CHECK(esp_wifi_init(&init)));
    ram_step("wifi_init");
    WIFI_STEP("esp_wifi_set_storage",
              ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM)));
    /* Keep association; the driver wakes the radio for AP DTIM beacons. */
    WIFI_STEP("esp_wifi_set_ps",
              ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_MIN_MODEM)));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,WIFI_EVENT_STA_DISCONNECTED,wifi_event,NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,NULL));
    if (config.ssid[0]) {
        wifi_config_t wifi={0};
        memcpy(wifi.sta.ssid,config.ssid,strlen(config.ssid));
        memcpy(wifi.sta.password,config.password,strlen(config.password));
        wifi.sta.threshold.authmode=WIFI_AUTH_WPA2_PSK;
        /* Every channel, and the strongest of what they hold.
         *
         * The default is WIFI_FAST_SCAN, which the header describes as a
         * scan that ends at the first AP of this name. A first match is
         * not a best match, and the board showed the difference: it
         * associated on channel 9, the four way handshake timed out
         * there, and the join that worked five seconds later was on
         * channel 6 at -58 dBm. Four joins failed in that one start.
         *
         * sort_method and failure_retry_cnt do nothing without a scan of
         * all the channels. The header says so at both of them, so the
         * three belong together or not at all.
         *
         * The cost is the scan itself, which now reads every channel
         * rather than stopping at the first hit. The starts it replaces
         * spent fifteen seconds failing. */
        wifi.sta.scan_method=WIFI_ALL_CHANNEL_SCAN;
        wifi.sta.sort_method=WIFI_CONNECT_AP_BY_SIGNAL;
        /* And a floor under what counts as an AP at all.
         *
         * Four starts off the board named two APs behind one name:
         *
         *     3c:37:12:35:dd:95   channel 6   -51 to -55 dBm
         *     2c:91:ab:94:1c:9e   channel 9   -85 to -86 dBm
         *
         * The sort above works: every one of the four began on channel 6,
         * which is the near one. Three of them were then refused there,
         * and failure_retry_cnt sent them on to the far one. Two joined
         * it. One of those two associated and never got an address in
         * twenty seconds.
         *
         * So the far AP is not a worse answer than the near one, it is
         * not an answer. A floor keeps it out of the list, and the retry
         * count then does what it was added for: two more goes at the
         * near AP inside one connect, rather than a full scan of every
         * channel between each go.
         *
         * -75 sits well below the near AP and well above the far one.
         * The header reads a value of nought or more as -127, which is
         * the same as no floor at all, so nought was never neutral. A
         * panel that has to live on a weaker link than this needs this
         * one number changed. */
        wifi.sta.threshold.rssi=-75;
        wifi.sta.failure_retry_cnt=2;
        WIFI_STEP("esp_wifi_set_mode",
                  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA)));
        WIFI_STEP("esp_wifi_set_config",
                  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&wifi)));
        WIFI_STEP("esp_wifi_start",ESP_ERROR_CHECK(esp_wifi_start()));
        WIFI_STEP("esp_wifi_connect",ESP_ERROR_CHECK(esp_wifi_connect()));
    }
    ram_step("wifi_start");
    ESP_LOGI("panel_wifi","network brought up in %u ms, all channels "
             "scanned, strongest AP first",
             (unsigned)(esp_log_timestamp()-network_began));
    /* esp_http_client writes two lines at every 401, which is how the
     * service hands out its first nonce, and one at every poll the PC does
     * not answer. The network task writes a line of its own when the
     * answer of the PC changes, with the reason. See network_task. */
    esp_log_level_set("HTTP_CLIENT",ESP_LOG_NONE);
    /* On core 0 with the radio, and under the drawing. LVGL draws in a
     * thread of its own, "swdraw", at CONFIG_LV_DRAW_THREAD_PRIO, and that
     * thread takes either core. A poll of the PC parses its answer for
     * some milliseconds, and at the priority of the drawing or above it,
     * that parse held a frame back while somebody scrolled.
     *
     * Its stack is internal memory, and not PSRAM like the stacks of
     * panel_psram.h. This task writes the updates of the firmware and
     * confirms a new one, and each of those reads the state of the
     * partitions through esp_partition_mmap. A map of flash freezes the
     * caches and stops at an assert when the stack is not internal
     * (esp_mmu_map, esp_cache_utils.c). Reported from the board, with the
     * stack in PSRAM: the first answer of the PC restarted the panel, and
     * every start after it did the same. */
    BaseType_t created=xTaskCreatePinnedToCore(network_task,"panel_network",12288,NULL,
                                               PANEL_NETWORK_PRIORITY,NULL,0);
    assert(created==pdPASS);
    ram_step("network");
    ESP_LOGI("panel_ram","internal KB free after each step of the start:%s, least %u",
             ram_steps,
             (unsigned)(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT)/1024));
    /* The start task as well, once, at its end. It is freed when app_main
     * returns, so its size costs nothing after this. */
    ESP_LOGI("panel_stack","the start used %u of %u bytes of its stack",
             (unsigned)(CONFIG_ESP_MAIN_TASK_STACK_SIZE-uxTaskGetStackHighWaterMark(NULL)),
             (unsigned)CONFIG_ESP_MAIN_TASK_STACK_SIZE);
}
