// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The time of day for the clock page, from the network.
//
// The chip starts at nought, which is 1970, and keeps time from there on
// its own clock, in a sleep and with the radio off as well. SNTP sets it
// once the panel is on the network, and again every hour after that
// (CONFIG_LWIP_SNTP_UPDATE_DELAY), which is far more often than a clock
// on a crystal needs.
//
// Two servers. The first is the one the router names in its DHCP answer,
// when it names one: a FRITZ!Box does, and a server inside the house
// answers even when the internet does not. The second is pool.ntp.org,
// for a router that names none. sdkconfig.defaults gives lwIP room for
// two and lets DHCP fill the first.
#include "panel_time.h"
#include <stdlib.h>
#include <sys/time.h>
#include "esp_log.h"
#include "esp_netif_sntp.h"

// Berlin: CET, and CEST from the last Sunday of March at 2:00 to the last
// Sunday of October at 3:00, in the form of POSIX TZ.
#define PANEL_TIME_ZONE "CET-1CEST,M3.5.0,M10.5.0/3"
#define PANEL_TIME_SERVER "pool.ntp.org"
// A clock that says a year before this has never been set.
#define PANEL_TIME_SET_YEAR 2024

static const char *tag = "panel_time";

static void synced(struct timeval *tv)
{
    struct tm local;
    time_t seconds = tv->tv_sec;
    localtime_r(&seconds, &local);
    char text[32];
    strftime(text, sizeof text, "%Y-%m-%d %H:%M:%S %Z", &local);
    ESP_LOGI(tag, "The clock is set: %s", text);
}

void panel_time_init(void)
{
    setenv("TZ", PANEL_TIME_ZONE, 1);
    tzset();
    esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG(PANEL_TIME_SERVER);
    // The server of DHCP goes into place nought, and the one named here is
    // put into place one after every new address.
    config.server_from_dhcp = true;
    config.renew_servers_after_new_IP = true;
    config.index_of_first_server = 1;
    config.ip_event_to_renew = IP_EVENT_STA_GOT_IP;
    // Nothing waits for the first answer: the clock page shows that it has
    // none yet.
    config.wait_for_sync = false;
    config.sync_cb = synced;
    esp_err_t err = esp_netif_sntp_init(&config);
    if (err != ESP_OK)
        ESP_LOGW(tag, "No time from the network: %s", esp_err_to_name(err));
}

bool panel_time_now(struct tm *now)
{
    time_t seconds = time(NULL);
    localtime_r(&seconds, now);
    return now->tm_year + 1900 >= PANEL_TIME_SET_YEAR;
}
