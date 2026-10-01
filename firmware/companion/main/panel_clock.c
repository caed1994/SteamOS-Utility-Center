// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The clock of the CPU: 240 MHz while the display is awake, 80 while it
// sleeps.
//
// Asked for: less power while the display sleeps. Without this file the
// CPU runs at 240 MHz at all times, in a sleep too, where nothing draws.
//
// Light sleep is not possible here, and this is why. The RGB panel driver
// of ESP-IDF 5.5.5 takes an ESP_PM_NO_LIGHT_SLEEP lock when it creates the
// panel, and keeps it for the whole life of the panel
// (components/esp_lcd/rgb/esp_lcd_panel_rgb.c). The display is never
// deleted, so the chip never sleeps. What is left is the speed of the
// clock, which esp_pm changes between the two numbers below.
//
// Why 80 and not 40. On the ESP32-S3 the PSRAM clock comes from the same
// source as the CPU clock. Below 80 MHz the CPU runs from the crystal, and
// then esp_pm also puts the PSRAM to 20 MHz
// (esp_clk_utils_mspi_speed_mode_sync_before_cpu_freq_switching in
// components/esp_hw_support/clk_utils.c). The frame buffers are in PSRAM,
// and an interrupt copies them into the bounce buffers of the display at
// every frame. At a quarter of the speed of the PSRAM, those copies come
// late. 80 MHz still runs from the PLL, so the PSRAM stays at 80 MHz.
//
// The copies run at 80 MHz too, and they can still come late. The driver
// counts the copies of each frame and starts the frame again at the next
// VSYNC when one is missing (lcd_rgb_panel_try_restart_transmission). While
// the display sleeps it shows black, and a black frame started again looks
// the same. The clock is at full speed again before the display wakes.
//
// How it works: esp_pm runs the CPU at the low speed when no lock asks for
// more. One lock of ours asks for the full speed while the display is
// awake. The Wi-Fi driver takes locks of its own when it needs them.

#include "panel_clock.h"
#include "sdkconfig.h"
#include "esp_log.h"
#include "esp_pm.h"
#include "esp_private/esp_clk.h"

#if !CONFIG_PM_ENABLE
#error "CONFIG_PM_ENABLE is off, so esp_pm cannot change the clock. See sdkconfig.defaults."
#endif

#define PANEL_CLOCK_HIGH_MHZ 240
#define PANEL_CLOCK_LOW_MHZ 80

static esp_pm_lock_handle_t awake;
static bool is_low;

esp_err_t panel_clock_init(void)
{
    esp_err_t err=esp_pm_lock_create(ESP_PM_CPU_FREQ_MAX,0,"panel_awake",&awake);
    if(err!=ESP_OK){awake=NULL;return err;}
    /* The lock first and the configuration after it. The other way round,
     * the CPU drops to the low speed for the moment between the two. */
    err=esp_pm_lock_acquire(awake);
    if(err!=ESP_OK){esp_pm_lock_delete(awake);awake=NULL;return err;}
    esp_pm_config_t config={
        .max_freq_mhz=PANEL_CLOCK_HIGH_MHZ,
        .min_freq_mhz=PANEL_CLOCK_LOW_MHZ,
        .light_sleep_enable=false,
    };
    return esp_pm_configure(&config);
}

void panel_clock_low(bool low)
{
    if(!awake || low==is_low)return;
    esp_err_t err=low?esp_pm_lock_release(awake):esp_pm_lock_acquire(awake);
    if(err!=ESP_OK){
        ESP_LOGW("panel_clock","The clock did not go %s: %s",low?"down":"up",
                 esp_err_to_name(err));
        return;
    }
    is_low=low;
}

unsigned panel_clock_mhz(void)
{
    return (unsigned)(esp_clk_cpu_freq()/1000000);
}
