// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_power.h"
#include "panel_key.h"
#include <stdatomic.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "bsp/esp-bsp.h"
#include "esp_io_expander.h"

/* Official 4B schematic: PWR -> TCA9554 EXIO4, active low.
 * Do not drive this pin: it is also connected to the AXP2101 power-key circuit. */
#define PWRKEY_PIN IO_EXPANDER_PIN_NUM_4
static atomic_uint toggles;
static esp_io_expander_handle_t expander;
static void key_task(void *arg)
{
    (void)arg;
    panel_key_t key={0};
    bool read_failed=false;
    for(;;){
        uint32_t level=0;
        esp_err_t err=esp_io_expander_get_level(expander,PWRKEY_PIN,&level);
        if(err==ESP_OK){
            read_failed=false;
            if(panel_key_sample(&key,(level&PWRKEY_PIN)==0,(uint32_t)(esp_timer_get_time()/1000))){
                atomic_fetch_add(&toggles,1);
            }
        }else{
            panel_key_reset(&key);
            if(!read_failed)ESP_LOGW("panel_power","PWRKEY read failed: %s",esp_err_to_name(err));
            read_failed=true;
        }
        /* I2C reads occur outside the LVGL thread; a bus timeout cannot stall rendering. */
        vTaskDelay(pdMS_TO_TICKS(read_failed?1000:20));
    }
}
esp_err_t panel_power_init(void)
{
    expander=bsp_io_expander_init();
    if(!expander)return ESP_FAIL;
    esp_err_t err=esp_io_expander_set_dir(expander,PWRKEY_PIN,IO_EXPANDER_INPUT);
    if(err!=ESP_OK)return err;
    if(xTaskCreate(key_task,"panel_pwrkey",3072,NULL,2,NULL)!=pdPASS)return ESP_ERR_NO_MEM;
    ESP_LOGI("panel_power","PWRKEY short press: display standby toggle (EXIO4)");
    return ESP_OK;
}
bool panel_power_take_toggle(void){return (atomic_exchange(&toggles,0)&1U)!=0;}
