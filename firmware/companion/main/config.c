// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>
#include <sys/socket.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_http_server.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_random.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "nvs.h"
#include "cJSON.h"
#include "config.h"
#include "panel_text.h"

extern const char setup_page_start[] asm("_binary_setup_html_start");
extern const char setup_page_end[] asm("_binary_setup_html_end");
extern const char setup_page_de_start[] asm("_binary_setup_de_html_start");
extern const char setup_page_de_end[] asm("_binary_setup_de_html_end");
static bool portal_running;
static esp_netif_t *ap_netif;

bool panel_config_load(panel_config_t *config)
{
    nvs_handle_t handle;
    memset(config, 0, sizeof(*config));
    if (nvs_open("panel", NVS_READONLY, &handle) != ESP_OK) return false;
    size_t len=sizeof(config->ssid);
    esp_err_t ok=nvs_get_str(handle, "ssid", config->ssid, &len);
    len=sizeof(config->password); ok |= nvs_get_str(handle, "password", config->password, &len);
    len=sizeof(config->server); ok |= nvs_get_str(handle, "server", config->server, &len);
    len=sizeof(config->token); ok |= nvs_get_str(handle, "token", config->token, &len);
    /* On its own, and its result thrown away. A panel that has never met a
     * PC with a wired card has no address stored, and that is a panel that
     * works. Folded into ok above, a missing key would read as a panel that
     * is not set up at all. */
    len=sizeof(config->wol_mac);
    if (nvs_get_str(handle, "wol_mac", config->wol_mac, &len) != ESP_OK)
        config->wol_mac[0]='\0';
    nvs_close(handle);
    /* A network is the setup. The address and the secret can be empty: the
     * panel then finds the PC and pairs with it. A secret that is there
     * has the length of one. */
    size_t token=strlen(config->token);
    return ok == ESP_OK && strlen(config->ssid)>0 && (token==0 || token>=32);
}

/* The address and the secret of a pairing, in one commit. */
esp_err_t panel_config_save_pairing(const char *server, const char *token)
{
    nvs_handle_t handle;
    if (!server || !token) return ESP_ERR_INVALID_ARG;
    esp_err_t err=nvs_open("panel", NVS_READWRITE, &handle);
    if (err!=ESP_OK) return err;
    err=nvs_set_str(handle,"server",server);
    if (err==ESP_OK) err=nvs_set_str(handle,"token",token);
    if (err==ESP_OK) err=nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t panel_config_save_server(const char *server)
{
    nvs_handle_t handle;
    if (!server) return ESP_ERR_INVALID_ARG;
    esp_err_t err=nvs_open("panel", NVS_READWRITE, &handle);
    if (err!=ESP_OK) return err;
    err=nvs_set_str(handle,"server",server);
    if (err==ESP_OK) err=nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t panel_config_save_wol(const char *mac)
{
    nvs_handle_t handle;
    if (!mac) return ESP_ERR_INVALID_ARG;
    esp_err_t err=nvs_open("panel", NVS_READWRITE, &handle);
    if (err!=ESP_OK) return err;
    err=nvs_set_str(handle,"wol_mac",mac);
    if (err==ESP_OK) err=nvs_commit(handle);
    nvs_close(handle);
    return err;
}

static esp_err_t index_get(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    httpd_resp_set_hdr(req, "X-Frame-Options", "DENY");
    // The page in the language the panel is set to. Two files and not one
    // with a switch in it: this is served by a phone that has just joined
    // an access point with no way out, so nothing on it can be fetched.
    if (panel_text_language() == PANEL_GERMAN)
        return httpd_resp_send(req, setup_page_de_start,
                               setup_page_de_end-setup_page_de_start-1);
    return httpd_resp_send(req, setup_page_start, setup_page_end-setup_page_start-1);
}

static void restart_task(void *arg)
{
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(1800));
    esp_restart();
}

static esp_err_t error_reply(httpd_req_t *req, const char *error)
{
    httpd_resp_set_status(req, "400 Bad Request");
    httpd_resp_set_type(req, "text/plain; charset=utf-8");
    return httpd_resp_sendstr(req, error);
}

static bool copy_json(cJSON *root, const char *key, char *target, size_t capacity, size_t min)
{
    cJSON *v=cJSON_GetObjectItemCaseSensitive(root,key);
    if (!cJSON_IsString(v)) return false;
    size_t size=strlen(v->valuestring);
    if (size < min || size >= capacity) return false;
    memcpy(target, v->valuestring, size+1);
    return true;
}

static bool valid_server(const char *url)
{
    // Deliberately accept only an IPv4/hostname + optional port, no path or credentials.
    if (strncmp(url, "http://", 7) != 0 || !url[7]) return false;
    for (const char *p=url+7; *p; p++) if (!isalnum((unsigned char)*p) && *p!='.' && *p!='-' && *p!=':') return false;
    return true;
}

static esp_err_t save_post(httpd_req_t *req)
{
    char type[64];
    if (httpd_req_get_hdr_value_str(req,"Content-Type",type,sizeof(type))!=ESP_OK || strcmp(type,"application/json")!=0)
        return error_reply(req,panel_text(TXT_FORM_PLEASE));
    if (req->content_len<=0 || req->content_len>1024) return error_reply(req,"Daten zu lang.");
    char body[1025];
    int received=0;
    while (received<req->content_len) {
        int n=httpd_req_recv(req,body+received,req->content_len-received);
        if (n<=0) return ESP_FAIL;
        received+=n;
    }
    body[received]=0;
    panel_config_t config={0};
    cJSON *root=cJSON_Parse(body);
    /* The address and the token can be empty: the panel then finds the PC
     * by itself and pairs with it. A value that is there must be valid. */
    bool ok=copy_json(root,"ssid",config.ssid,sizeof(config.ssid),1)
        && copy_json(root,"password",config.password,sizeof(config.password),8)
        && copy_json(root,"server",config.server,sizeof(config.server),0)
        && copy_json(root,"token",config.token,sizeof(config.token),0);
    cJSON_Delete(root);
    size_t slen=strlen(config.server), tlen=strlen(config.token);
    if (slen && config.server[slen-1]=='/') config.server[slen-1]=0;
    if (!ok || (slen && !valid_server(config.server)) || (tlen && tlen<32))
        return error_reply(req,panel_text(TXT_FORM_BAD));
    for (const char *p=config.token; *p; p++) if (!isalnum((unsigned char)*p) && *p!='_' && *p!='-') return error_reply(req,panel_text(TXT_TOKEN_BAD));
    nvs_handle_t handle;
    esp_err_t err=nvs_open("panel", NVS_READWRITE, &handle);
    if (err==ESP_OK) {
        err=nvs_set_str(handle,"ssid",config.ssid);
        if (err==ESP_OK) err=nvs_set_str(handle,"password",config.password);
        if (err==ESP_OK) err=nvs_set_str(handle,"server",config.server);
        if (err==ESP_OK) err=nvs_set_str(handle,"token",config.token);
        if (err==ESP_OK) err=nvs_commit(handle);
        nvs_close(handle);
    }
    memset(&config,0,sizeof(config));
    memset(body,0,sizeof(body));
    if (err!=ESP_OK) {
        httpd_resp_set_status(req,"500 Internal Server Error");
        return httpd_resp_sendstr(req,"Speichern fehlgeschlagen.");
    }
    httpd_resp_set_type(req,"text/plain; charset=utf-8");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    esp_err_t sent=httpd_resp_sendstr(req,panel_text(TXT_FORM_SAVED));
    xTaskCreate(restart_task,"restart",2048,NULL,5,NULL);
    return sent;
}

esp_err_t panel_config_portal(char *ssid, size_t ssid_size, char *password, size_t password_size)
{
    if (portal_running) return ESP_OK;
    uint8_t mac[6];
    esp_read_mac(mac,ESP_MAC_WIFI_SOFTAP);
    snprintf(ssid,ssid_size,"SteamOS-Panel-%02X%02X",mac[4],mac[5]);
    const char alphabet[]="ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    uint8_t random[12];
    esp_fill_random(random,sizeof(random));
    if (password_size<13) return ESP_ERR_INVALID_ARG;
    for (size_t i=0;i<12;i++) password[i]=alphabet[random[i]&31];
    password[12]=0;
    if (!ap_netif) ap_netif=esp_netif_create_default_wifi_ap();
    if (!ap_netif) return ESP_FAIL;
    esp_wifi_stop();
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    wifi_config_t ap={0};
    memcpy(ap.ap.ssid,ssid,strlen(ssid));
    ap.ap.ssid_len=strlen(ssid);
    memcpy(ap.ap.password,password,strlen(password));
    ap.ap.authmode=WIFI_AUTH_WPA2_PSK;
    ap.ap.max_connection=2;
    ap.ap.channel=1;
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP,&ap));
    ESP_ERROR_CHECK(esp_wifi_start());
    httpd_config_t cfg=HTTPD_DEFAULT_CONFIG();
    cfg.stack_size=8192;
    cfg.max_uri_handlers=2;
    cfg.recv_wait_timeout=5;
    cfg.lru_purge_enable=true;
    httpd_handle_t server=NULL;
    esp_err_t err=httpd_start(&server,&cfg);
    if (err!=ESP_OK) return err;
    httpd_uri_t index={.uri="/",.method=HTTP_GET,.handler=index_get};
    httpd_uri_t save={.uri="/save",.method=HTTP_POST,.handler=save_post};
    httpd_register_uri_handler(server,&index);
    httpd_register_uri_handler(server,&save);
    portal_running=true;
    return ESP_OK;
}
