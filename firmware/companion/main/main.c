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
#include "panel_power.h"
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_wifi.h"
#include "esp_netif.h"
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

/* The startup animation, put in the image by main/CMakeLists.txt. It
 * belongs to Valve and not to this project; assets/ORIGIN-BOOT-ANIMATION
 * says what it is and how to take it out. Deleting the file leaves these
 * two the same, and panel_boot_show does nothing when they are. */
extern const uint8_t boot_animation_start[] asm("_binary_boot_steam_gif_start");
extern const uint8_t boot_animation_end[] asm("_binary_boot_steam_gif_end");

static atomic_uint ui_heartbeat_ms;
static atomic_bool display_asleep;
static int display_brightness=70; /* Updated only by the LVGL thread after startup. */
static QueueHandle_t actions;
static QueueHandle_t sounds;
static SemaphoreHandle_t lock;
static panel_state_t state;
static panel_config_t config;

typedef struct { char data[4096]; size_t length; bool overflow; } response_t;

static panel_settings_t settings_load(void)
{
    panel_settings_t settings={.brightness=70,.sound_volume=30,
                               .touch_tones=false,
                               .language=PANEL_ENGLISH};
    nvs_handle_t h;
    if(nvs_open("panel_ui",NVS_READONLY,&h)==ESP_OK){
        uint8_t value;
        if(nvs_get_u8(h,"brightness",&value)==ESP_OK && value>=5 && value<=100)settings.brightness=value;
        if(nvs_get_u8(h,"sound_volume",&value)==ESP_OK && value<=100)settings.sound_volume=value;
        if(nvs_get_u8(h,"touch_tones",&value)==ESP_OK)settings.touch_tones=value==1;
        // Anything this firmware does not know about reads as English,
        // which is what a board with nothing stored answers in.
        if(nvs_get_u8(h,"language",&value)==ESP_OK && value<PANEL_LANGUAGE_COUNT)
            settings.language=(panel_language_t)value;
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
                     key==PANEL_LANGUAGE?"language":"touch_tones";
    esp_err_t result=ESP_OK;
    if(key==PANEL_BRIGHTNESS){
        if(!atomic_load(&display_asleep))result=bsp_display_brightness_set(value);
        if(result==ESP_OK)display_brightness=value;
    }
    if(result==ESP_OK && save){
        nvs_handle_t h;
        result=nvs_open("panel_ui",NVS_READWRITE,&h);
        if(result==ESP_OK){
            result=nvs_set_u8(h,name,(uint8_t)value);
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

static void ui_tick(lv_timer_t *timer)
{
    (void)timer;
    if(panel_power_take_toggle()){
        bool sleep=!atomic_load(&display_asleep);
        esp_err_t err=panel_display_standby(sleep,display_brightness);
        if(err==ESP_OK){
            atomic_store(&display_asleep,sleep);
            if(sleep && sounds)xQueueReset(sounds);
            ESP_LOGI("panel_power","Display %s; Wi-Fi and PC polling remain active",sleep?"standby":"awake");
        }else{
            ESP_LOGW("panel_power","Standby change failed: %s",esp_err_to_name(err));
        }
    }
    atomic_store(&ui_heartbeat_ms,(uint32_t)(esp_timer_get_time()/1000));
    if(atomic_load(&display_asleep))return;
    panel_state_t copy;
    xSemaphoreTake(lock,portMAX_DELAY); copy=state; xSemaphoreGive(lock);
    panel_ui_update(&copy);
}

static void action_send(panel_action_t action)
{
    if (xQueueSend(actions,&action,0)!=pdTRUE) {
        xSemaphoreTake(lock,portMAX_DELAY);
        snprintf(state.message,sizeof(state.message),panel_text(TXT_WAIT));
        xSemaphoreGive(lock);
    }
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

static esp_err_t collect_data(esp_http_client_event_t *event)
{
    if (event->event_id==HTTP_EVENT_ON_HEADER) {
        if (event->header_key && event->header_value
            && same_header(event->header_key,PANEL_NONCE_HEADER)) {
            size_t length=strlen(event->header_value);
            if (length>0 && length<sizeof(panel_nonce))
                memcpy(panel_nonce,event->header_value,length+1);
        }
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

// One attempt. The token itself never goes on the wire: what goes is a
// signature over the method, the path and the body, with the nonce that the
// service last gave out. See panel_auth.h.
static int attempt(const char *path, const char *action, response_t *out)
{
    char url[224], body[96], auth[PANEL_AUTH_HEX];
    const char *payload="";
    memset(out,0,sizeof(*out));
    snprintf(url,sizeof(url),"%s%s",config.server,path);
    if (action) {
        snprintf(body,sizeof(body),"{\"action\":\"%s\"}",action);
        payload=body;
    }
    esp_http_client_config_t cfg={.url=url,.timeout_ms=4000,.event_handler=collect_data,.user_data=out,.disable_auto_redirect=true};
    esp_http_client_handle_t client=esp_http_client_init(&cfg);
    if (!client) return 0;
    if (panel_auth_sign(config.token,action ? "POST" : "GET",path,panel_nonce,
                        payload,strlen(payload),auth)) {
        esp_http_client_set_header(client,PANEL_NONCE_HEADER,panel_nonce);
        esp_http_client_set_header(client,PANEL_AUTH_HEADER,auth);
    }
    if (action) {
        esp_http_client_set_method(client,HTTP_METHOD_POST);
        esp_http_client_set_header(client,"Content-Type","application/json");
        esp_http_client_set_post_field(client,payload,strlen(payload));
    }
    esp_err_t err=esp_http_client_perform(client);
    int code=err==ESP_OK && !out->overflow ? esp_http_client_get_status_code(client) : 0;
    esp_http_client_cleanup(client);
    return code;
}

static int request(const char *path, const char *action)
{
    response_t *out=calloc(1,sizeof(*out));
    if (!out) return 0;
    int code=attempt(path,action,out);
    // 401 is the nonce, not the secret: it was spent, or the service
    // restarted and forgot it. The answer carried a fresh one, so one more
    // attempt is the whole recovery. A rejected request ran nothing, so
    // sending an action again is safe.
    if (code==401) code=attempt(path,action,out);
    if (code!=200 || action) { free(out); return code; }
    cJSON *root=cJSON_Parse(out->data);
    free(out);
    if (!cJSON_IsObject(root)) { cJSON_Delete(root); return 0; }
    cJSON *items=cJSON_GetObjectItemCaseSensitive(root,"controllers");
    cJSON *audio=cJSON_GetObjectItemCaseSensitive(root,"audio");
    cJSON *host=cJSON_GetObjectItemCaseSensitive(root,"host");
    if (!cJSON_IsArray(items)||!cJSON_IsObject(audio)||!cJSON_IsString(host)) { cJSON_Delete(root); return 0; }
    cJSON *first=cJSON_GetArrayItem(items,0);
    cJSON *battery=cJSON_GetObjectItemCaseSensitive(first,"percent");
    cJSON *name=cJSON_GetObjectItemCaseSensitive(first,"name");
    cJSON *charging=cJSON_GetObjectItemCaseSensitive(first,"status");
    cJSON *volume=cJSON_GetObjectItemCaseSensitive(audio,"percent");
    cJSON *muted=cJSON_GetObjectItemCaseSensitive(audio,"muted");
    // The word the service sends, and not a word of any language on this
    // screen. See panel_state_t.
    bool charge=cJSON_IsString(charging)
        && strcmp(charging->valuestring,"Charging")==0;
    xSemaphoreTake(lock,portMAX_DELAY);
    state.battery=cJSON_IsNumber(battery) && battery->valueint>=0 && battery->valueint<=100 ? battery->valueint : -1;
    state.volume=cJSON_IsNumber(volume) && volume->valueint>=0 && volume->valueint<=100 ? volume->valueint : -1;
    state.muted=cJSON_IsTrue(muted);
    cJSON *telemetry=cJSON_GetObjectItemCaseSensitive(root,"telemetry");
    state.cpu_temp=metric(telemetry,"cpu_c",150);
    state.gpu_temp=metric(telemetry,"gpu_c",150);
    state.gpu_watts=metric(telemetry,"gpu_w",2000);
    snprintf(state.controller,sizeof(state.controller),"%s",cJSON_IsString(name) ? name->valuestring : "Controller");
    snprintf(state.host,sizeof(state.host),"%s",host->valuestring);
    state.charging=charge;
    xSemaphoreGive(lock);
    cJSON_Delete(root);
    return 200;
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base==WIFI_EVENT && id==WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event=data;
        ESP_LOGW("panel_wifi","Disconnected, reason=%u",event->reason);
        xSemaphoreTake(lock,portMAX_DELAY);
        state.wifi=false; state.online=false; bool reconnect=!state.setup;
        xSemaphoreGive(lock);
        if (reconnect) esp_wifi_connect();
    }
    if (base==IP_EVENT && id==IP_EVENT_STA_GOT_IP) {
        xSemaphoreTake(lock,portMAX_DELAY); state.wifi=true; xSemaphoreGive(lock);
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

static void network_task(void *arg)
{
    (void)arg;
    if (!config.ssid[0]) portal_start();
    const char *names[]={"volume_down","mute","volume_up","suspend","reboot","poweroff"};
    TickType_t last_poll=xTaskGetTickCount()-pdMS_TO_TICKS(3000);
    TickType_t feedback_until=0;
    TickType_t last_health=xTaskGetTickCount();
    for (;;) {
        if(xTaskGetTickCount()-last_health>=pdMS_TO_TICKS(30000)){
            last_health=xTaskGetTickCount();
            uint32_t now_ms=(uint32_t)(esp_timer_get_time()/1000);
            xSemaphoreTake(lock,portMAX_DELAY);
            bool wifi=state.wifi,online=state.online;
            xSemaphoreGive(lock);
            ESP_LOGI("panel_health","up=%" PRIu32 "s ui_age=%" PRIu32 "ms heap=%u internal=%u largest=%u min=%u net_stack=%u wifi=%d pc=%d standby=%d key_slowest=%ums",
                now_ms/1000,now_ms-atomic_load(&ui_heartbeat_ms),
                (unsigned)esp_get_free_heap_size(),
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
                (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
                (unsigned)esp_get_minimum_free_heap_size(),
                (unsigned)uxTaskGetStackHighWaterMark(NULL),wifi,online,
                atomic_load(&display_asleep),
                /* The slowest turn of the key loop since the last line.
                 * The shortest press the panel can see is about twice
                 * this, so a number far above PWRKEY_PERIOD_MS is why a
                 * press did nothing. See panel_power.c. */
                (unsigned)panel_power_slowest_read_ms());
        }
        panel_action_t action;
        if (xQueueReceive(actions,&action,pdMS_TO_TICKS(100))==pdTRUE) {
            if (action==PANEL_SETUP) { portal_start(); continue; }
            xSemaphoreTake(lock,portMAX_DELAY); bool online=state.online; xSemaphoreGive(lock);
            if (online && connected() && action>=0 && action<PANEL_SETUP) {
                int code=request("/v1/action",names[action]);
                xSemaphoreTake(lock,portMAX_DELAY);
                snprintf(state.message,sizeof(state.message),"%s",code==200 ? panel_text(TXT_SENT) : code==401 ? panel_text(TXT_CHECK_TOKEN) : panel_text(TXT_NOT_CONFIRMED));
                xSemaphoreGive(lock);
                feedback_until=xTaskGetTickCount()+pdMS_TO_TICKS(5000);
                last_poll=xTaskGetTickCount()-pdMS_TO_TICKS(3000);
            }
        }
        if (xTaskGetTickCount()-last_poll>=pdMS_TO_TICKS(3000)) {
            last_poll=xTaskGetTickCount();
            int code=connected() ? request("/v1/status",NULL) : 0;
            xSemaphoreTake(lock,portMAX_DELAY);
            state.online=code==200;
            if ((int32_t)(xTaskGetTickCount()-feedback_until)>=0) snprintf(state.message,sizeof(state.message),"%s",code==200 ? panel_text(TXT_UP_TO_DATE) : code==401 ? panel_text(TXT_CHECK_SETUP) : state.wifi ? panel_text(TXT_NO_ANSWER) : panel_text(TXT_JOINING));
            xSemaphoreGive(lock);
        }
    }
}

void app_main(void)
{
    ESP_LOGI("panel_boot","version=%s reset_reason=%d",esp_app_get_description()->version,(int)esp_reset_reason());
    esp_err_t err=nvs_flash_init();
    if (err==ESP_ERR_NVS_NO_FREE_PAGES || err==ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err=nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    if (!panel_config_load(&config)) memset(&config,0,sizeof(config));
    lock=xSemaphoreCreateMutex();
    actions=xQueueCreate(1,sizeof(panel_action_t));
    assert(lock && actions);
    state.battery=-1; state.volume=-1; state.cpu_temp=-1; state.gpu_temp=-1; state.gpu_watts=-1;
    state.setup=config.ssid[0]==0;
    if (!panel_display_start()) ESP_ERROR_CHECK(ESP_FAIL);
    esp_err_t key_err=panel_power_init();
    if(key_err!=ESP_OK)ESP_LOGW("panel_power","PWRKEY unavailable: %s",esp_err_to_name(key_err));
    panel_settings_t settings=settings_load();
    setting_set(PANEL_BRIGHTNESS,settings.brightness,false);
    sounds=xQueueCreate(1,sizeof(int));
    assert(sounds);
    BaseType_t sound_created=xTaskCreate(sound_task,"panel_sound",6144,NULL,3,NULL);
    assert(sound_created==pdPASS);
    bsp_display_lock(0);
    panel_ui_create(action_send,setting_set,sound_send,&settings);
    lv_timer_create(ui_tick,200,NULL);
    ui_tick(NULL);
    /* Over the finished screen, not in front of building it. Everything
     * below this joins the network and waits for the PC, and the panel
     * spent those seconds showing a page with no numbers in it. Now it
     * shows the animation instead, and the page is ready underneath when
     * the animation ends. */
    panel_boot_show(boot_animation_start,
                    (size_t)(boot_animation_end-boot_animation_start));
    bsp_display_unlock();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    /* Keep association; the driver wakes the radio for AP DTIM beacons. */
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_MIN_MODEM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,WIFI_EVENT_STA_DISCONNECTED,wifi_event,NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,NULL));
    if (config.ssid[0]) {
        wifi_config_t wifi={0};
        memcpy(wifi.sta.ssid,config.ssid,strlen(config.ssid));
        memcpy(wifi.sta.password,config.password,strlen(config.password));
        wifi.sta.threshold.authmode=WIFI_AUTH_WPA2_PSK;
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&wifi));
        ESP_ERROR_CHECK(esp_wifi_start());
        ESP_ERROR_CHECK(esp_wifi_connect());
    }
    BaseType_t created=xTaskCreate(network_task,"panel_network",12288,NULL,4,NULL);
    assert(created==pdPASS);
}
