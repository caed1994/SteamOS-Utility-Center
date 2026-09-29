// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_display.h"
#include "panel_ui_sleep.h"
#include "bsp/esp-bsp.h"
#include "bsp/display.h"
#include "esp_lcd_touch.h"
#include "bsp/touch.h"
#include "esp_check.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_lvgl_port.h"
#include "esp_memory_utils.h"
#include "driver/ledc.h"
#include "driver/gpio.h"

static lv_display_t *panel_screen;
static lv_indev_t *panel_input;
static bool is_asleep;

/* Keep RGB DMA interrupts and LVGL on core 1. The main task is pinned there
 * by sdkconfig; esp_lcd allocates its interrupts on the calling core.
 * Wi-Fi uses core 0. Board pins and ST7701 commands remain owned by the BSP. */
lv_display_t *panel_display_start(void)
{
    const char *tag="panel_display";
    ESP_RETURN_ON_FALSE(xPortGetCoreID()==1,NULL,tag,"Display must initialize on core 1");
    lvgl_port_cfg_t port=ESP_LVGL_PORT_INIT_CONFIG();
    port.task_affinity=1;
    ESP_ERROR_CHECK(lvgl_port_init(&port));

    esp_lcd_panel_handle_t panel=NULL;
    esp_lcd_panel_io_handle_t io=NULL;
    bsp_display_config_t board={0};
    ESP_ERROR_CHECK(bsp_display_new(&board,&panel,&io));
    /* Board default is 16 MHz (~60 Hz). 12 MHz requests ~45 Hz and reduces
     * continuous pixel traffic by 25%; actual divider may round downward. */
    ESP_ERROR_CHECK(esp_lcd_rgb_panel_set_pclk(panel,12000000));

    const lvgl_port_display_cfg_t display={
        .panel_handle=panel,
        /* BSP auto-deletes the ST7701 command IO; RGB needs no IO handle. */
        .buffer_size=BSP_LCD_H_RES*48,
        .double_buffer=false,
        .hres=BSP_LCD_H_RES,.vres=BSP_LCD_V_RES,
        .color_format=LV_COLOR_FORMAT_RGB565,
        /* MALLOC_CAP_DMA keeps this buffer in internal SRAM on ESP32-S3.
         * DEFAULT allocations larger than 16 KiB previously went to PSRAM. */
        .flags={.buff_dma=true,.buff_spiram=false,.sw_rotate=false},
    };
    const lvgl_port_display_rgb_cfg_t rgb={.flags={.bb_mode=true,.avoid_tearing=false}};
    lv_display_t *screen=lvgl_port_add_disp_rgb(&display,&rgb);
    ESP_RETURN_ON_FALSE(screen,NULL,tag,"LVGL display allocation failed");
    lvgl_port_lock(0);
    lv_draw_buf_t *draw=lv_display_get_buf_active(screen);
    bool internal=draw && esp_ptr_internal(draw->data);
    lvgl_port_unlock();
    ESP_RETURN_ON_FALSE(internal,NULL,tag,"Draw buffer must reside in internal SRAM");

    esp_lcd_touch_handle_t touch=NULL;
    ESP_ERROR_CHECK(bsp_touch_new(NULL,&touch));
    const lvgl_port_touch_cfg_t input={.disp=screen,.handle=touch};
    panel_input=lvgl_port_add_touch(&input);
    ESP_RETURN_ON_FALSE(panel_input,NULL,tag,"Touch allocation failed");
    panel_screen=screen;
    ESP_LOGI(tag,"RGB: requested PCLK=12MHz, bounce=%d rows, SRAM draw=48 rows, core=1",
             CONFIG_BSP_LCD_RGB_BOUNCE_BUFFER_HEIGHT);
    return screen;
}

/* The backlight of this board, and why turning it off needs more than the
 * board support offers.
 *
 * Read out of the board support by the build, and printed by the step in
 * .github/workflows/companion-firmware.yml that says what it does:
 *
 *     .gpio_num        = GPIO_NUM_4
 *     .duty_resolution = LEDC_TIMER_10_BIT     full scale is 1024
 *     .freq_hz         = 5000
 *     bsp_display_brightness_set(p):
 *         duty = 1023 * (100 - p) / 100
 *
 * The input is inverted, so a LOW is light. At p=0 the duty is 1023 of
 * 1024, which leaves one LOW slot in every period: an enable pulse of
 * about 200 ns, five thousand times a second. The boost converter behind
 * the LEDs takes that as a request to start, cannot reach regulation on
 * it, shuts down and tries again. On the board that reads as a display
 * that swings between dark and dim for as long as it is asleep.
 *
 * bsp_display_backlight_off() is brightness_set(0), so the board support
 * has no way to stop this. The version before this one called ledc_stop at
 * an idle HIGH, and on the board the swinging stayed.
 *
 * So the pin leaves the LEDC matrix altogether while the panel sleeps, and
 * is held HIGH as a plain output. Whatever the reason ledc_stop was not
 * enough, the LEDC hardware is no longer connected to the pin and can put
 * no pulse on it. Waking gives the pin back to LEDC and sets the
 * brightness again. */
#define BACKLIGHT_PIN BSP_LCD_BACKLIGHT
#define BACKLIGHT_OFF_LEVEL 1       /* inverted: HIGH is dark */
#define BACKLIGHT_CHANNEL CONFIG_BSP_DISPLAY_BRIGHTNESS_LEDC_CH
#define BACKLIGHT_TIMER LEDC_TIMER_1
/* Ten bits, from the board support. Full scale is one more than
 * the largest value it ever writes, and that one count is the
 * pulse this removes. */
#define BACKLIGHT_DUTY_BITS 10
#define BACKLIGHT_FULL_DUTY (1 << BACKLIGHT_DUTY_BITS)

static void backlight_off(void)
{
    /* Full scale, and not ledc_stop and not a pad of our own.
     *
     * The board support writes 1023 for "off", and full scale at ten bits
     * is 1024. That one count is the whole fault: it leaves one LOW slot in
     * every period, which is an enable pulse of about 200 ns at five
     * thousand a second, and the boost converter behind the LEDs takes it
     * as a request to start. LEDC takes 2^resolution as a duty and holds
     * the output steady at it, which is the pulse gone.
     *
     * Two other ways were tried on the board and neither worked. ledc_stop
     * at an idle HIGH left the swinging. Taking the pad away from LEDC left
     * it too, and the log then said "GPIO 4 is not usable, maybe conflict
     * with others" when LEDC wanted the pin back on the next wake, because
     * a pad that a driver reserved does not come back quietly. This way
     * uses the driver as it is meant to be used and touches no routing. */
    esp_err_t err=ledc_set_duty(LEDC_LOW_SPEED_MODE,BACKLIGHT_CHANNEL,
                                BACKLIGHT_FULL_DUTY);
    if(err==ESP_OK)err=ledc_update_duty(LEDC_LOW_SPEED_MODE,BACKLIGHT_CHANNEL);
    /* GPIO_MODE_INPUT_OUTPUT on the read below, and this is why.
     *
     * The version before this configured the pad as GPIO_MODE_OUTPUT and
     * then read it with gpio_get_level. That mode switches the input buffer
     * off, so the read gave 0 whatever the pad was doing, and the log said
     * the pin was not held when nothing had measured it. The reading has to
     * come from a pin whose input stays on. */
    gpio_set_direction(BACKLIGHT_PIN,GPIO_MODE_INPUT_OUTPUT);
    ESP_LOGW("panel_display",
             "backlight duty %d of %d, set=%s, pin %d reads %d, wanted %d",
             (int)BACKLIGHT_FULL_DUTY,(int)BACKLIGHT_FULL_DUTY,
             esp_err_to_name(err),(int)BACKLIGHT_PIN,
             gpio_get_level(BACKLIGHT_PIN),BACKLIGHT_OFF_LEVEL);
}

static esp_err_t backlight_on(int brightness)
{
    /* Nothing to give back: the pin never left LEDC. The board support
     * writes the duty and calls ledc_update_duty, which is all this needs. */
    return bsp_display_brightness_set(brightness);
}

esp_err_t panel_display_standby(bool sleep,int brightness)
{
    if(!panel_screen || !panel_input)return ESP_ERR_INVALID_STATE;
    if(sleep==is_asleep)return ESP_OK;
    if(sleep){
        /* The drawing stops before the light does. The backlight fades over
         * some milliseconds, and a half-drawn frame during that fade is
         * visible. */
        panel_ui_sleep(panel_screen,panel_input,true);
        backlight_off();
        ESP_LOGI("panel_display","Backlight OFF: pin %d held high, off the LEDC matrix",
                 (int)BACKLIGHT_PIN);
    }else{
        panel_ui_sleep(panel_screen,panel_input,false);
        esp_err_t err=backlight_on(brightness);
        if(err!=ESP_OK){
            backlight_off();
            panel_ui_sleep(panel_screen,panel_input,true);
            return err;
        }
        ESP_LOGI("panel_display","Backlight ON: PWM restored to %d%%",brightness);
    }
    is_asleep=sleep;
    return ESP_OK;
}
