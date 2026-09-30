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

/* The picture of the game, on its way from the network task to the one
 * that draws.
 *
 * panel_ui_banner touches LVGL objects, so it belongs to the LVGL thread
 * and the network task must not call it. The bytes are left here under
 * the lock and ui_tick takes them, which is the same shape as everything
 * else that crosses this line.
 *
 * ready with a NULL pointer is a real message and not an empty one: it
 * says the game ended, and the screen drops the picture it holds.
 *
 * Ownership walks with the pointer. Whoever takes it out of here owns it,
 * and panel_ui_banner takes it from there. */
static void *pending_art;
static size_t pending_art_size;
static bool pending_art_ready;

/* What the panel carries over the network and decodes. The same ceiling
 * the service applies, named again at this end so a change at one end
 * shows up as a picture that does not arrive rather than as a buffer
 * that overflows. */
#define PANEL_ART_LIMIT (256 * 1024)
typedef struct { uint8_t *data; size_t length, room; bool overflow; } image_t;

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
    void *art=NULL;size_t art_size=0;bool art_ready=false;
    xSemaphoreTake(lock,portMAX_DELAY);
    copy=state;
    if(pending_art_ready){
        art=pending_art;art_size=pending_art_size;art_ready=true;
        pending_art=NULL;pending_art_size=0;pending_art_ready=false;
    }
    xSemaphoreGive(lock);
    /* This thread draws, so this thread hands the bytes to the screen.
     * A NULL with art_ready is the end of a game and not an empty
     * message: it says to drop the picture that is up. */
    if(art_ready)panel_ui_banner(art,art_size);
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

static esp_err_t collect_image(esp_http_client_event_t *event)
{
    if (event->event_id==HTTP_EVENT_ON_HEADER) {
        remember_nonce(event);
        return ESP_OK;
    }
    if (event->event_id==HTTP_EVENT_ON_DATA) {
        image_t *out=event->user_data;
        if (event->data_len<0
            || out->length+(size_t)event->data_len>out->room) {
            out->overflow=true;
            return ESP_FAIL;
        }
        memcpy(out->data+out->length,event->data,event->data_len);
        out->length+=(size_t)event->data_len;
    }
    return ESP_OK;
}

/* The picture, which is bytes and not JSON.
 *
 * A reader of its own, because response_t is 4096 bytes on the stack of
 * the network task and a header.jpg is thirty to sixty thousand. The
 * buffer is PSRAM, taken at the ceiling and given back down to what
 * really arrived: a picture is held for as long as a game runs, and
 * holding a quarter of a megabyte to keep forty thousand bytes is a
 * quarter of a megabyte nobody else can have.
 *
 * Returns the bytes and their count, or NULL. The caller owns them.
 */
static void *fetch_artwork(size_t *size)
{
    *size=0;
    image_t out={0};
    out.room=PANEL_ART_LIMIT;
    out.data=heap_caps_malloc(out.room,MALLOC_CAP_SPIRAM);
    if (!out.data) {
        ESP_LOGW("panel_art","no room for a picture");
        return NULL;
    }
    char url[224], auth[PANEL_AUTH_HEX];
    snprintf(url,sizeof(url),"%s/v1/art",config.server);
    esp_http_client_config_t cfg={.url=url,.timeout_ms=6000,
        .event_handler=collect_image,.user_data=&out,
        .disable_auto_redirect=true};
    esp_http_client_handle_t client=esp_http_client_init(&cfg);
    if (!client) { heap_caps_free(out.data); return NULL; }
    if (panel_auth_sign(config.token,"GET","/v1/art",panel_nonce,"",0,auth)) {
        esp_http_client_set_header(client,PANEL_NONCE_HEADER,panel_nonce);
        esp_http_client_set_header(client,PANEL_AUTH_HEADER,auth);
    }
    esp_err_t err=esp_http_client_perform(client);
    int code=err==ESP_OK ? esp_http_client_get_status_code(client) : 0;
    esp_http_client_cleanup(client);
    /* 404 is the ordinary answer for a game whose picture Steam never
     * fetched, and for no game at all. Neither is a fault. */
    if (code!=200 || out.overflow || out.length==0) {
        heap_caps_free(out.data);
        if (code!=200 && code!=404)
            ESP_LOGW("panel_art","the picture came back %d",code);
        return NULL;
    }
    void *smaller=heap_caps_realloc(out.data,out.length,MALLOC_CAP_SPIRAM);
    *size=out.length;
    return smaller ? smaller : out.data;
}

/* Leave the picture where the drawing thread finds it. */
static void hand_over_artwork(void *bytes,size_t size)
{
    xSemaphoreTake(lock,portMAX_DELAY);
    /* One that nobody collected yet. The newer game wins, and the older
     * picture would otherwise be held for as long as the panel runs. */
    if (pending_art) heap_caps_free(pending_art);
    pending_art=bytes;pending_art_size=size;pending_art_ready=true;
    xSemaphoreGive(lock);
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
    /* The second and third pages. Each one is optional: a service that is
     * older than this firmware answers without them, and the panel then
     * shows those pages empty rather than nothing at all. */
    cJSON *session=cJSON_GetObjectItemCaseSensitive(root,"session");
    cJSON *playing=cJSON_GetObjectItemCaseSensitive(root,"playing");
    cJSON *drives=cJSON_GetObjectItemCaseSensitive(root,"drives");
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
    /* A word the service sends and not a word of any language on the
     * screen, the same rule the charge flag follows. See panel_state_t. */
    state.game_mode=cJSON_IsString(session)
        && strcmp(session->valuestring,"game")==0;
    snprintf(state.playing,sizeof(state.playing),"%s",
             cJSON_IsString(playing)?playing->valuestring:"");
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
    xSemaphoreGive(lock);
    learn_wake_address(cJSON_GetObjectItemCaseSensitive(root,"wake"));
    cJSON_Delete(root);
    return 200;
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
    case 8:   return "the AP is leaving";
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
        ESP_LOGW("panel_wifi","Disconnected, reason=%u: %s",
                 event->reason,wifi_reason_name(event->reason));
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
    /* Indexed by panel_action_t, and it has to hold every action below
     * PANEL_SETUP. The guard further down is that range, so a name added
     * to the enum and not to this table makes every button under it send
     * the name of another one. tests/test_panel_pages.py holds the two
     * lengths equal. */
    const char *names[]={"volume_down","mute","volume_up","suspend","reboot",
                         "poweroff","desktop_mode","game_mode"};
    /* The game the picture on the screen belongs to. A name and not a
     * flag: the panel has no number for a game, and the name is what
     * changes when the game does. */
    static char art_for[sizeof(state.playing)];
    art_for[0]=0;
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
            /* The picture follows the game and not the poll. A fetch
             * every three seconds is 40 KB over the air every three
             * seconds for a picture that did not change, and the panel
             * asks a machine somebody plays a game on. */
            char playing_now[sizeof(state.playing)];
            xSemaphoreTake(lock,portMAX_DELAY);
            snprintf(playing_now,sizeof(playing_now),"%s",
                     code==200 ? state.playing : "");
            xSemaphoreGive(lock);
            if (strcmp(playing_now,art_for)!=0) {
                snprintf(art_for,sizeof(art_for),"%s",playing_now);
                size_t got=0;
                void *bytes=playing_now[0] ? fetch_artwork(&got) : NULL;
                hand_over_artwork(bytes,got);
            }
            xSemaphoreTake(lock,portMAX_DELAY);
            state.online=code==200;
            if ((int32_t)(xTaskGetTickCount()-feedback_until)>=0) snprintf(state.message,sizeof(state.message),"%s",code==200 ? panel_text(TXT_UP_TO_DATE) : code==401 ? panel_text(TXT_CHECK_SETUP) : state.wifi ? panel_text(TXT_NO_ANSWER) : panel_text(TXT_JOINING));
            xSemaphoreGive(lock);
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
    /* An address kept from an earlier run. Without this the button appears
     * only after the PC has answered once, which is the case where it is
     * needed least. */
    {
        uint8_t kept[PANEL_WOL_MAC_BYTES];
        state.can_wake=panel_wol_parse(config.wol_mac,kept);
    }
    if (!panel_display_start()) ESP_ERROR_CHECK(ESP_FAIL);
    esp_err_t key_err=panel_power_init();
    if(key_err!=ESP_OK)ESP_LOGW("panel_power","PWRKEY unavailable: %s",esp_err_to_name(key_err));
    panel_settings_t settings=settings_load();
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
    setting_set(PANEL_BRIGHTNESS,settings.brightness,false);
    uint32_t network_began=esp_log_timestamp();
    WIFI_STEP("esp_netif_init",ESP_ERROR_CHECK(esp_netif_init()));
    WIFI_STEP("esp_event_loop_create_default",
              ESP_ERROR_CHECK(esp_event_loop_create_default()));
    WIFI_STEP("esp_netif_create_default_wifi_sta",
              esp_netif_create_default_wifi_sta());
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();
    WIFI_STEP("esp_wifi_init",ESP_ERROR_CHECK(esp_wifi_init(&init)));
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
    ESP_LOGI("panel_wifi","network brought up in %u ms, all channels "
             "scanned, strongest AP first",
             (unsigned)(esp_log_timestamp()-network_began));
    BaseType_t created=xTaskCreate(network_task,"panel_network",12288,NULL,4,NULL);
    assert(created==pdPASS);
}
