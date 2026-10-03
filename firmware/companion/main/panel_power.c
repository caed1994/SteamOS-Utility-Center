// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_power.h"
#include "panel_key.h"
#include <inttypes.h>
#include <stdatomic.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "bsp/esp-bsp.h"
#include "esp_io_expander.h"
#include "driver/gpio.h"
#include "panel_psram.h"

/* Official 4B schematic: PWR reaches EXIO4 of the TCA9554 through T1, and
 * the pin reads high while the key is pressed. See panel_key_pressed.
 * Do not drive this pin: it is also connected to the AXP2101 power-key circuit. */
#define PWRKEY_PIN IO_EXPANDER_PIN_NUM_4
static atomic_uint toggles;
static esp_io_expander_handle_t expander;

/* How often the key is read, and the rate this task really keeps.
 *
 * vTaskDelayUntil and not vTaskDelay. The delay measures the gap between
 * two turns of the loop, so the I2C read was added on top of it: the real
 * period was 20 ms plus whatever the bus gave back, and the bus is shared
 * with the touch screen and the audio codec. The shortest press this can
 * see is about twice that period, so a slow bus can turn an ordinary tap
 * into nothing.
 *
 * The priority goes with it. At 2 this task sat below the LVGL task, and
 * a task that is not run does not sample. */
#define PWRKEY_PERIOD_MS 15
#define PWRKEY_TASK_PRIORITY 5
/* The loop writes a log line for each press, and one when a read fails,
 * and a log line goes through vprintf. The motion task, which logs from
 * its loop too, has the same. In PSRAM, so the room costs nothing. */
#define PWRKEY_TASK_STACK 4096

/* What the loop measures about itself, for the log below. A period that is
 * far from PWRKEY_PERIOD_MS would lose short presses, and it says so rather
 * than leaving somebody to find it with a button. */
static atomic_uint slowest_ms;

/* BOOT, the lower key on the side of the panel: the home key, which goes
 * back to the start page. GPIO0, read by the same loop as the standby key,
 * low while pressed: see panel_key_home_pressed.
 *
 * GPIO0 also picks the boot mode, so a press held while the board starts
 * starts the loader of the ROM instead of this firmware. Read only once
 * the firmware runs, and never driven. */
#define HOME_PIN GPIO_NUM_0
static atomic_uint homes;
static bool home_usable;

/* After a read of the expander that failed, the next one a second later.
 * The loop keeps its rate for the home key, which is not on the bus. */
#define PWRKEY_RETRY_MS 1000

static uint32_t clock_ms(void){return (uint32_t)(esp_timer_get_time()/1000);}

static void key_task(void *arg)
{
    (void)arg;
    panel_key_t key={0},home={0};
    bool read_failed=false;
    uint32_t last_ms=clock_ms(),failed_ms=0;
    TickType_t next=xTaskGetTickCount();
    for(;;){
        /* The home key first: a register of the chip, so it works when the
         * expander does not answer. */
        uint32_t now=clock_ms();
        if(home_usable &&
           panel_key_sample(&home,panel_key_home_pressed(gpio_get_level(HOME_PIN)),now)){
            atomic_store(&homes,1);
            ESP_LOGI("panel_power","Home key short press of about %" PRIu32 " ms",
                     now-home.pressed_ms);
        }
        /* I2C reads occur outside the LVGL thread; a bus timeout cannot
         * stall rendering. */
        if(!read_failed || now-failed_ms>=PWRKEY_RETRY_MS){
            uint32_t level=0;
            esp_err_t err=esp_io_expander_get_level(expander,PWRKEY_PIN,&level);
            now=clock_ms();
            if(err==ESP_OK){
                /* What this turn of the loop actually cost, for the log. */
                uint32_t apart=now-last_ms;
                if(!read_failed && apart>atomic_load(&slowest_ms))
                    atomic_store(&slowest_ms,apart);
                read_failed=false;
                if(panel_key_sample(&key,panel_key_pressed(level,PWRKEY_PIN),now)){
                    atomic_fetch_add(&toggles,1);
                    /* From the end of the settle at the press to the end of
                     * the settle at the release: the press, give or take a
                     * period. One line a press, so the log shows each one
                     * that counted. */
                    ESP_LOGI("panel_power","PWRKEY short press of about %" PRIu32 " ms",
                             now-key.pressed_ms);
                }
            }else{
                panel_key_reset(&key);
                if(!read_failed)ESP_LOGW("panel_power","PWRKEY read failed: %s",esp_err_to_name(err));
                read_failed=true;
                failed_ms=now;
                /* A read that failed can take long. The rate starts again
                 * from here rather than in a burst of turns that catch up. */
                next=xTaskGetTickCount();
            }
            last_ms=now;
        }
        vTaskDelayUntil(&next,pdMS_TO_TICKS(PWRKEY_PERIOD_MS));
    }
}
esp_err_t panel_power_init(void)
{
    expander=bsp_io_expander_init();
    if(!expander)return ESP_FAIL;
    esp_err_t err=esp_io_expander_set_dir(expander,PWRKEY_PIN,IO_EXPANDER_INPUT);
    if(err!=ESP_OK)return err;
    /* The level at the start, for the line below. Nobody holds the key at
     * this point, apart from a hand that is still on it from switching the
     * board on, so "down" here with the hand away says the level is read the
     * wrong way round. */
    uint32_t level=0;
    const char *state=esp_io_expander_get_level(expander,PWRKEY_PIN,&level)!=ESP_OK
        ? "not read" : panel_key_pressed(level,PWRKEY_PIN) ? "down" : "up";
    /* The home key. The standby key works without it, so a pin that does
     * not take its settings is a line in the log and not a failure. The
     * board pulls the pin up with R4, and the pull-up of the chip only
     * adds to that. */
    const gpio_config_t home={.pin_bit_mask=1ULL<<HOME_PIN,.mode=GPIO_MODE_INPUT,
                              .pull_up_en=GPIO_PULLUP_ENABLE,
                              .pull_down_en=GPIO_PULLDOWN_DISABLE,
                              .intr_type=GPIO_INTR_DISABLE};
    esp_err_t home_err=gpio_config(&home);
    home_usable=home_err==ESP_OK;
    /* Its stack in PSRAM: see panel_psram.h. */
    if(panel_psram_task(key_task,"panel_pwrkey",PWRKEY_TASK_STACK,PWRKEY_TASK_PRIORITY,tskNO_AFFINITY)!=pdPASS)
        return ESP_ERR_NO_MEM;
    ESP_LOGI("panel_power",
             "PWRKEY short press: display standby toggle (EXIO4, high while "
             "pressed), read every %d ms, the key is %s now",PWRKEY_PERIOD_MS,state);
    if(home_usable)
        ESP_LOGI("panel_power",
                 "Home key short press: the start page (BOOT, GPIO0, low while "
                 "pressed), the key is %s now",
                 panel_key_home_pressed(gpio_get_level(HOME_PIN))?"down":"up");
    else
        ESP_LOGW("panel_power","Home key unavailable: %s",esp_err_to_name(home_err));
    return ESP_OK;
}
bool panel_power_take_toggle(void){return (atomic_exchange(&toggles,0)&1U)!=0;}

uint32_t panel_power_slowest_read_ms(void){return atomic_exchange(&slowest_ms,0);}

bool panel_power_take_home(void){return atomic_exchange(&homes,0)!=0;}
