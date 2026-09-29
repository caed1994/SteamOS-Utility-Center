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
#include "esp_rom_sys.h"

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

/* The backlight of this board, and why a sleeping panel is not dark.
 *
 * The numbers come out of the board support, which the build prints in
 * .github/workflows/companion-firmware.yml, and none of it is in any
 * repository:
 *
 *     .gpio_num        = GPIO_NUM_4
 *     .duty_resolution = LEDC_TIMER_10_BIT     full scale is 1024
 *     .freq_hz         = 5000
 *     bsp_display_brightness_set(p):
 *         duty = 1023 * (100 - p) / 100
 *
 * The input is inverted, so a low is light. brightness_set(0) writes 1023
 * of 1024, which leaves one low slot in every period.
 * bsp_display_backlight_off() is brightness_set(0), so the board support
 * has no way to go further than that.
 *
 * Three ways of going further were tried on the board and measured:
 *
 *     ledc_stop at an idle high   the pin reads high on 240 of 240 samples,
 *                                 and the screen swung between dark and dim
 *     a pad of our own, held high 240 of 240 as well, and the same swinging
 *     a duty of 1024              wraps to 0 in a ten bit register, so the
 *                                 pin went low and the screen came up at
 *                                 full brightness
 *
 * And the supply is out of reach: the board support names no power chip,
 * and its expander pins are the LCD's SPI, the audio amplifier and the
 * panel reset. There is no backlight enable to switch.
 *
 * So a level is not a request this driver answers. A pin held high is a
 * PWM of zero on-time, and a boost converter that carries no energy in a
 * period never reaches regulation: it starts, gives up, starts again. The
 * swinging is the hardware doing what it does when it is asked for
 * nothing, and a pin held low is the other end of the same thing.
 *
 * What is left is the lowest brightness the converter still regulates,
 * which is steady. See BACKLIGHT_SLEEP_PERCENT. */
#define BACKLIGHT_PIN BSP_LCD_BACKLIGHT
#define BACKLIGHT_CHANNEL CONFIG_BSP_DISPLAY_BRIGHTNESS_LEDC_CH

/* How the pin is measured, and why a single read is not a measurement.
 *
 * The backlight runs at 5 kHz, so one read of the pin lands at one point of
 * a 200 us period and says nothing about the rest of it. A duty of 1023 of
 * 1024 reads high on 1023 tries out of 1024, which is indistinguishable
 * from a pin that is held high, and that one slot in a thousand is the
 * whole fault here.
 *
 * So the pin is read many times at a step that does not divide the period,
 * which walks the phase across it. Constant high gives every sample, a
 * constant low gives none, and anything between the two is a pin that
 * still moves. Approximately seven milliseconds in total, once per sleep. */
#define BACKLIGHT_SAMPLES 240
#define BACKLIGHT_SAMPLE_STEP_US 37

static int backlight_high_reads(void)
{
    int high=0;
    for(int i=0;i<BACKLIGHT_SAMPLES;i++){
        if(gpio_get_level(BACKLIGHT_PIN))high++;
        esp_rom_delay_us(BACKLIGHT_SAMPLE_STEP_US);
    }
    return high;
}

/* What a sleeping panel looks like on this board, and why it is not dark.
 *
 * Three measurements decide it, and each one came off the board:
 *
 *   pin held low      full brightness. A duty of 1024 wraps to 0 in a ten
 *                     bit register, and the screen came up bright.
 *   pin held high     240 of 240 reads, and the screen swung between dark
 *                     and dim for as long as it slept.
 *   the rails         the board support names no power chip and no
 *                     backlight enable. Its expander pins are the LCD's
 *                     SPI, the audio amplifier and the panel reset.
 *
 * A level is not a request this driver can answer. Holding the pin high is
 * a PWM of zero on-time, and a boost converter that carries no energy in a
 * period never reaches regulation: it starts, gives up and starts again.
 * That is the swinging, and it is what the hardware does when it is asked
 * for nothing. Holding the pin low is the other end, which is everything.
 *
 * Nothing in software reaches the supply behind those LEDs, so the screen
 * cannot go dark. What it can do is go to the lowest brightness the
 * converter still regulates, which is steady. So sleep dims rather than
 * switches off, and the window says so rather than leaving somebody to
 * wonder why the wall glows.
 *
 * Five is the floor the settings page already offers on its slider. */
#define BACKLIGHT_SLEEP_PERCENT 5

static void backlight_off(void)
{
    esp_err_t err=bsp_display_brightness_set(BACKLIGHT_SLEEP_PERCENT);
    /* The input buffer, so the reads below are reads. ledc_set_pin leaves
     * the pad output only, and gpio_get_level on such a pad gives 0 for
     * every state of it. The routing is untouched by this. */
    gpio_set_direction(BACKLIGHT_PIN,GPIO_MODE_INPUT_OUTPUT);
    int high=backlight_high_reads();
    /* Between none and all of the reads is a pin that carries a real PWM,
     * which is the whole point: a converter with something to regulate is
     * a converter that holds still. All of them, or none, is the state
     * that swings. */
    ESP_LOGW("panel_display",
             "backlight at %d%%: pin %d high on %d of %d reads, set=%s",
             BACKLIGHT_SLEEP_PERCENT,(int)BACKLIGHT_PIN,high,
             BACKLIGHT_SAMPLES,esp_err_to_name(err));
}

static esp_err_t backlight_on(int brightness)
{
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
        ESP_LOGI("panel_display",
                 "Display asleep: backlight down to %d%%, which is as dark "
                 "as this board goes",BACKLIGHT_SLEEP_PERCENT);
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
