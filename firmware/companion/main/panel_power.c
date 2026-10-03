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
static void key_task(void *arg)
{
    (void)arg;
    panel_key_t key={0};
    bool read_failed=false;
    uint32_t last_ms=(uint32_t)(esp_timer_get_time()/1000);
    TickType_t next=xTaskGetTickCount();
    for(;;){
        uint32_t level=0;
        esp_err_t err=esp_io_expander_get_level(expander,PWRKEY_PIN,&level);
        uint32_t now=(uint32_t)(esp_timer_get_time()/1000);
        if(err==ESP_OK){
            /* What this turn of the loop actually cost, for the log. */
            uint32_t apart=now-last_ms;
            if(!read_failed && apart>atomic_load(&slowest_ms))
                atomic_store(&slowest_ms,apart);
            read_failed=false;
            if(panel_key_sample(&key,panel_key_pressed(level,PWRKEY_PIN),now)){
                atomic_fetch_add(&toggles,1);
                /* From the end of the settle at the press to the end of the
                 * settle at the release: the press, give or take a period.
                 * One line a press, so the log shows each one that counted. */
                ESP_LOGI("panel_power","PWRKEY short press of about %" PRIu32 " ms",
                         now-key.pressed_ms);
            }
        }else{
            panel_key_reset(&key);
            if(!read_failed)ESP_LOGW("panel_power","PWRKEY read failed: %s",esp_err_to_name(err));
            read_failed=true;
        }
        last_ms=now;
        /* I2C reads occur outside the LVGL thread; a bus timeout cannot stall rendering. */
        if(read_failed){
            next=xTaskGetTickCount();
            vTaskDelay(pdMS_TO_TICKS(1000));
        }else{
            vTaskDelayUntil(&next,pdMS_TO_TICKS(PWRKEY_PERIOD_MS));
        }
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
    /* Its stack in PSRAM: see panel_psram.h. */
    if(panel_psram_task(key_task,"panel_pwrkey",PWRKEY_TASK_STACK,PWRKEY_TASK_PRIORITY,tskNO_AFFINITY)!=pdPASS)
        return ESP_ERR_NO_MEM;
    ESP_LOGI("panel_power",
             "PWRKEY short press: display standby toggle (EXIO4, high while "
             "pressed), read every %d ms, the key is %s now",PWRKEY_PERIOD_MS,state);
    return ESP_OK;
}
bool panel_power_take_toggle(void){return (atomic_exchange(&toggles,0)&1U)!=0;}

uint32_t panel_power_slowest_read_ms(void){return atomic_exchange(&slowest_ms,0);}
