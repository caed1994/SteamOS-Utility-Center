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
// VSYNC when one is missing (lcd_rgb_panel_try_restart_transmission). A
// restart that comes late shifts the picture and keeps it shifted. With a
// black cover that looked the same; with the clock on the cover it did not,
// so panel_display.c starts the stream again at each change of the pixel
// clock and after each draw of a sleeping panel, and keeps the CPU at full
// speed until the sleeping pixel clock is in. The clock is at full speed
// again before the display wakes.
//
// How it works: esp_pm runs the CPU at the low speed when no lock asks for
// more. One lock of ours asks for the full speed while the display is
// awake. The Wi-Fi driver takes locks of its own when it needs them.

#include "panel_clock.h"
#include "sdkconfig.h"
#include "esp_log.h"
#include "esp_pm.h"
#include "esp_cpu.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"

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

/* How fast the clock really ran, measured and not asked.
 *
 * Read off the board: the health line said cpu=240MHz while the display
 * slept. It asked esp_clk_cpu_freq, and that answer is always 240 from
 * code that runs. esp_pm holds a lock for the full speed on each core for
 * as long as that core is not idle, and lets it go only in the idle task
 * (rtos0 and rtos1 in components/esp_pm/pm_impl.c). The low speed is the
 * speed of the pauses, and a question asked from inside a task is never
 * asked in a pause.
 *
 * The cycle counter of a core counts at whatever speed the clock has, in
 * the pauses as well. So the cycles between two readings, over the time
 * between them, is the mean speed of that stretch. While the display is
 * awake, panel_awake holds the full speed in the pauses too, and the mean
 * is then 240: a check of the measurement that comes for free.
 *
 * Each core has a counter of its own, and the task that reads them is not
 * pinned to one. So each core keeps its last reading, and a stretch counts
 * only between two readings of the same core. The counter is 32 bits wide
 * and turns over after 17.9 seconds at 240 MHz, so a stretch longer than
 * STRETCH_MAX_US is dropped and not guessed at. */
#define STRETCH_MAX_US (10 * 1000 * 1000)

static portMUX_TYPE readings_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t last_cycles[portNUM_PROCESSORS];
static int64_t last_us[portNUM_PROCESSORS];
static uint64_t sum_cycles, sum_us;
/* The same sums once more, set to nought when the clock goes down and read
 * when it goes up, so they hold one sleep alone. The health line mixes the
 * end of a sleep with the start of the time awake, and this says what the
 * sleep itself did. */
static uint64_t sleep_cycles, sleep_us;

void panel_clock_sample(void)
{
    /* One core, the counter and the time read together: no other task
     * runs on this core in between, so the three belong to one moment. */
    portENTER_CRITICAL(&readings_lock);
    int core = esp_cpu_get_core_id();
    uint32_t cycles = esp_cpu_get_cycle_count();
    int64_t now = esp_timer_get_time();
    if (last_us[core] != 0 && now > last_us[core] &&
        now - last_us[core] < STRETCH_MAX_US) {
        uint32_t stretch_cycles = cycles - last_cycles[core];
        uint64_t stretch_us = (uint64_t)(now - last_us[core]);
        sum_cycles += stretch_cycles;
        sum_us += stretch_us;
        sleep_cycles += stretch_cycles;
        sleep_us += stretch_us;
    }
    last_cycles[core] = cycles;
    last_us[core] = now;
    portEXIT_CRITICAL(&readings_lock);
}

/* The mean of a sum of stretches, and its share at the low speed. */
static void mean_of(uint64_t cycles, uint64_t us, unsigned *mhz,
                    unsigned *low_percent)
{
    *mhz = 0;
    *low_percent = 0;
    if (us == 0) return;
    unsigned mean = (unsigned)(cycles / us);
    *mhz = mean;
    /* Between the two speeds, the mean says how much of the time was low. */
    if (mean <= PANEL_CLOCK_LOW_MHZ) *low_percent = 100;
    else if (mean < PANEL_CLOCK_HIGH_MHZ)
        *low_percent = (PANEL_CLOCK_HIGH_MHZ - mean) * 100
                     / (PANEL_CLOCK_HIGH_MHZ - PANEL_CLOCK_LOW_MHZ);
}

void panel_clock_average(unsigned *mhz, unsigned *low_percent)
{
    portENTER_CRITICAL(&readings_lock);
    uint64_t cycles = sum_cycles, us = sum_us;
    sum_cycles = 0;
    sum_us = 0;
    portEXIT_CRITICAL(&readings_lock);
    mean_of(cycles, us, mhz, low_percent);
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
    /* The sums of the sleep start at the clock going down and are read at
     * the clock going up, one line for each sleep. */
    portENTER_CRITICAL(&readings_lock);
    uint64_t cycles = sleep_cycles, us = sleep_us;
    sleep_cycles = 0;
    sleep_us = 0;
    portEXIT_CRITICAL(&readings_lock);
    if (!low && us > 0) {
        unsigned mhz, low_percent;
        mean_of(cycles, us, &mhz, &low_percent);
        ESP_LOGI("panel_clock","The sleep ran at a mean of %u MHz, %u %% of "
                 "it at the low speed, over %u s",mhz,low_percent,
                 (unsigned)(us/1000000));
    }
}
