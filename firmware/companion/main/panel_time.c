// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The time of day for the clock page, from the clock chip of the board
// and from the network.
//
// The ESP starts at nought, which is 1970, and keeps time from there on
// its own clock, in a sleep and with the radio off as well. The clock
// chip of the board, a PCF85063, keeps time while the ESP restarts: see
// panel_rtc.h. Its time goes to the ESP at the start, before the screen
// is built.
//
// SNTP sets the time once the panel is on the network, and again every
// hour after that (CONFIG_LWIP_SNTP_UPDATE_DELAY), which is far more
// often than a clock on a crystal needs. The clock chip takes each of
// those times, so it keeps the time of the server for the next start.
//
// Two servers. The first is the one the router names in its DHCP answer,
// when it names one: a FRITZ!Box does, and a server inside the house
// answers even when the internet does not. The second is pool.ntp.org,
// for a router that names none. sdkconfig.defaults gives lwIP room for
// two and lets DHCP fill the first.
#include "panel_time.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <sys/time.h>
#include "esp_log.h"
#include "esp_netif_sntp.h"
#include "panel_rtc.h"

// Berlin: CET, and CEST from the last Sunday of March at 2:00 to the last
// Sunday of October at 3:00, in the form of POSIX TZ.
#define PANEL_TIME_ZONE "CET-1CEST,M3.5.0,M10.5.0/3"
#define PANEL_TIME_SERVER "pool.ntp.org"
// A clock that says a year before this has never been set.
#define PANEL_TIME_SET_YEAR 2024

static const char *tag = "panel_time";
// An answer of a time server that the clock chip has not taken yet.
static atomic_bool answered;

static void log_time(const char *from, time_t seconds)
{
    struct tm local;
    localtime_r(&seconds, &local);
    char text[32];
    strftime(text, sizeof text, "%Y-%m-%d %H:%M:%S %Z", &local);
    ESP_LOGI(tag, "The clock is set %s: %s", from, text);
}

// In the task of lwIP. The clock chip takes the time in the task of the
// network, because a stall on the I2C bus must not hold the network.
static void synced(struct timeval *tv)
{
    log_time("by the network", tv->tv_sec);
    atomic_store(&answered, true);
}

void panel_time_start(void)
{
    // Once, and before the tasks that read the local time exist: a change
    // of TZ while another task reads it is a race.
    setenv("TZ", PANEL_TIME_ZONE, 1);
    tzset();
    if (panel_rtc_init() != ESP_OK) return;
    time_t utc;
    if (!panel_rtc_read(&utc)) {
        ESP_LOGW(tag, "The clock chip holds no time to trust, so the clock waits for the network");
        return;
    }
    struct tm date;
    gmtime_r(&utc, &date);
    if (date.tm_year + 1900 < PANEL_TIME_SET_YEAR) {
        ESP_LOGW(tag, "The clock chip says %d, so the clock waits for the network",
                 date.tm_year + 1900);
        return;
    }
    const struct timeval now = {.tv_sec = utc};
    if (settimeofday(&now, NULL) == 0) log_time("by the clock chip", utc);
}

void panel_time_keep(void)
{
    if (!atomic_exchange(&answered, false)) return;
    struct tm local;
    if (!panel_time_now(&local)) return;
    esp_err_t err = panel_rtc_write(time(NULL));
    if (err == ESP_OK)
        ESP_LOGI(tag, "The clock chip has the time of the network");
    else if (err != ESP_ERR_INVALID_STATE)
        ESP_LOGW(tag, "The clock chip did not take the time: %s", esp_err_to_name(err));
}

void panel_time_init(void)
{
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
