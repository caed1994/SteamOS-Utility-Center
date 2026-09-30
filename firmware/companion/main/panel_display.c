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
#include <stdint.h>
#include "driver/ledc.h"

static lv_display_t *panel_screen;
static lv_indev_t *panel_input;
static bool is_asleep;

/* The lowest brightness this board holds steady, in percent.
 *
 * It has two readers. A sleeping panel goes here because it cannot go dark,
 * and the start of the display goes here because the board support lights
 * the panel at full before anything has been drawn. The long note above
 * backlight_off says why nought is not an option. */
#define BACKLIGHT_SLEEP_PERCENT 5

/* Two frame buffers, or this display never starts.
 *
 * esp_lvgl_port asks the panel for two of them when avoid_tearing is set,
 * and the panel holds as many as CONFIG_BSP_LCD_RGB_BUFFER_NUMS. The board
 * support defaults that number to one, with a range of one to three. A one
 * makes the request for the second buffer fail, and lvgl_port_add_disp_rgb
 * returns NULL.
 *
 * The number is set in firmware/companion/sdkconfig.defaults. Kconfig drops
 * a name it does not know and the build still passes, so the count is read
 * here. Then the build stops instead of the panel. */
_Static_assert(CONFIG_BSP_LCD_RGB_BUFFER_NUMS>=2,
               "avoid_tearing needs CONFIG_BSP_LCD_RGB_BUFFER_NUMS=2 in "
               "firmware/companion/sdkconfig.defaults");

/* True if p points inside the block of n bytes at base. */
static bool within(const void *p,const void *base,size_t n)
{
    const uint8_t *at=p,*from=base;
    return from && at>=from && at<from+n;
}

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
    /* Down, at once, before anything else runs.
     *
     * Reported from the board: the screen flashes white before the startup
     * animation. That flash is this line's absence. bsp_display_new sets up
     * the LEDC channel with a duty of 0, the input of this backlight is
     * inverted, and a duty of 0 is therefore full brightness. From that
     * instant the panel is lit at its maximum and showing a frame buffer
     * that nothing has written yet.
     *
     * Five percent and not nought: nought writes a duty of 1023, which
     * leaves one LOW slot in every period and makes the converter behind
     * the LEDs hiccup. Five percent is the lowest this board holds steady,
     * and it is the same number a sleeping panel uses. See
     * BACKLIGHT_SLEEP_PERCENT.
     *
     * app_main raises it once the first frame is on the screen. */
    bsp_display_brightness_set(BACKLIGHT_SLEEP_PERCENT);
    /* Board default is 16 MHz (~60 Hz). 12 MHz requests ~45 Hz and reduces
     * continuous pixel traffic by 25%; actual divider may round downward. */
    ESP_ERROR_CHECK(esp_lcd_rgb_panel_set_pclk(panel,12000000));

    /* LVGL draws into the panel's own frame buffers, and there are two.
     *
     * Reported from the board: small tears run through the startup
     * animation. 24 frames a second changed nothing, so the rate is not
     * the cause. The cause is the arrangement this replaces. One draw
     * buffer of 48 rows went row by row into the one frame buffer, and the
     * display scanned that same buffer out at the same time. The copy and
     * the scan met somewhere down the screen, and that line was the tear.
     *
     * avoid_tearing removes the copy. esp_lvgl_port asks the panel for its
     * two frame buffers and gives them to LVGL as its draw buffers, so
     * LVGL draws into the one the display does not read. The flush is then
     * a pointer and not a copy: esp_lcd_panel_draw_bitmap finds that the
     * buffer it holds is one of the panel's own, and moves cur_fb_index to
     * it. The filler behind the bounce buffers reads that at the end of the
     * frame it is in, where bb_fb_index takes the value of cur_fb_index. So
     * the display starts on the new buffer at a frame boundary, never in
     * the middle of one.
     *
     * direct_mode and not full_refresh, which is a change of mind with a
     * measurement behind it.
     *
     * full_refresh redraws the whole screen at every refresh: 480 by 480,
     * or 230400 pixels. The startup animation covers 320 by 320 of that,
     * which is 102400. The rest is the black behind it, drawn again at
     * every frame for nothing.
     *
     * The board measured that animation at 55 ms a frame where 40 was
     * asked, and 16 frames of 77 took about twice as long as the rest.
     * The network was ruled out first: the same numbers came back with
     * the Wi-Fi start held off until the animation was over.
     *
     * Direct mode draws only what was made invalid. The doubt about it
     * was that the two buffers drift apart, because LVGL draws into the
     * one the display does not read and that buffer is two frames old.
     * LVGL 9.5 answers that in refr_sync_areas: it keeps the areas it
     * drew last time and copies them into the other buffer. It also takes
     * away the areas it is about to draw again, with lv_area_diff, so it
     * copies nothing that an overwrite is coming for.
     *
     * lv_gif calls lv_obj_invalidate on the whole image at every frame.
     * So the area it draws and the area it keeps are the same 320 by 320
     * square, the difference of the two is empty, and no copy happens.
     * The animation draws 102400 pixels a frame instead of 230400 and
     * pays nothing for the change.
     *
     * What the board said afterwards, against the same animation with the
     * network held off in both runs:
     *
     *                        full_refresh   direct_mode
     *     average frame          55 ms          51 ms
     *     whole animation      4245 ms        3890 ms
     *     frames near 90 ms        16              2
     *     frames near 67 ms         5             17
     *
     * The heavy frames did not go. They came down one rung, and the step
     * a person sees went from twice the light frames to one and a half.
     *
     * The same numbers give the frame period of this panel, which nothing
     * on the board had ever said. Every gap fell into a heap at 45, 67 or
     * 90 ms, and those are 22 to 23 apart. So a period is about 22.5 ms
     * and the panel runs at about 44 Hz, which is what 12 MHz and the
     * timings of this panel work out at.
     *
     * That also says where the floor is. A frame holds for 40 ms in the
     * file and a flush lands on a boundary, so the fastest a frame goes is
     * two periods, or 45 ms. 51 is close to it. Reaching it asks the
     * heaviest frames to do their work in under 5 ms, which a GIF decoder
     * at 320 by 320 does not do. A faster pixel clock makes it worse
     * rather than better: at 16 MHz a period is 16.9 ms, and 40 ms then
     * lands on three of them, which is 50.7.
     *
     * avoid_tearing needs one of direct_mode and full_refresh. Without
     * either, esp_lvgl_port reaches the end of its chain and asks LVGL
     * for partial mode over a screen-sized buffer, which draws correctly
     * and tears again. tests/test_panel_display.py holds the pair.
     *
     * The flush waits for that frame boundary and has no timeout. The wait
     * ends only while the RGB DMA runs, and it does run this early: the
     * white flash this board showed before the animation was the display
     * scanning out a frame buffer with nothing in it, directly out of
     * bsp_display_new.
     *
     * buffer_size, buff_dma and buff_spiram have no effect below.
     * esp_lvgl_port replaces the size with the whole screen and allocates
     * nothing, because these buffers belong to the panel and sit in PSRAM.
     * The values say what happens rather than what is asked for. */
    const lvgl_port_display_cfg_t display={
        .panel_handle=panel,
        /* BSP auto-deletes the ST7701 command IO; RGB needs no IO handle. */
        .buffer_size=BSP_LCD_H_RES*BSP_LCD_V_RES,
        .double_buffer=false,
        .hres=BSP_LCD_H_RES,.vres=BSP_LCD_V_RES,
        .color_format=LV_COLOR_FORMAT_RGB565,
        .flags={.buff_dma=false,.buff_spiram=false,.sw_rotate=false,
                .direct_mode=true},
    };
    const lvgl_port_display_rgb_cfg_t rgb={.flags={.bb_mode=true,.avoid_tearing=true}};
    lv_display_t *screen=lvgl_port_add_disp_rgb(&display,&rgb);
    ESP_RETURN_ON_FALSE(screen,NULL,tag,"LVGL display allocation failed");
    /* Proof that the buffer swap really happened.
     *
     * A draw buffer outside these two is a flush that copies, and a copy is
     * the tearing back again with nothing to show that it returned. The
     * line this replaces demanded internal SRAM, which was right while
     * LVGL owned the buffer and the driver copied out of it. */
    void *first=NULL,*second=NULL;
    ESP_ERROR_CHECK(esp_lcd_rgb_panel_get_frame_buffer(panel,2,&first,&second));
    const size_t frame=(size_t)BSP_LCD_H_RES*BSP_LCD_V_RES*2;
    lvgl_port_lock(0);
    /* Black on the panel at the first moment there is a way to put it
     * there. A frame buffer holds whatever the memory held, and the board
     * showed that as white. The brightness above keeps it dim; this makes
     * it black, and between the two there is nothing to see until app_main
     * has a screen worth showing.
     *
     * Once for each frame buffer, because there are two of them now and
     * LVGL draws into them in turn. One refresh leaves the other buffer as
     * the memory left it, and the first real frame swaps to exactly that
     * one. The invalidate goes before each refresh: a refresh with nothing
     * invalid draws nothing.
     *
     * One window is left and it is not ours to close. bsp_display_new sets
     * the LEDC duty to 0, which is full brightness on this inverted input,
     * and it does that inside itself before returning. Everything after it
     * is as early as this code can be. */
    lv_obj_t *blank=lv_screen_active();
    if(blank){
        lv_obj_set_style_bg_color(blank,lv_color_black(),0);
        lv_obj_set_style_bg_opa(blank,LV_OPA_COVER,0);
        for(int i=0;i<CONFIG_BSP_LCD_RGB_BUFFER_NUMS;i++){
            lv_obj_invalidate(blank);
            lv_refr_now(screen);
        }
    }
    /* Read after the refreshes, so this is the buffer LVGL really drew in. */
    lv_draw_buf_t *draw=lv_display_get_buf_active(screen);
    bool own=draw && (within(draw->data,first,frame)
                      || within(draw->data,second,frame));
    lvgl_port_unlock();
    ESP_RETURN_ON_FALSE(own,NULL,tag,
                        "LVGL draws outside the panel frame buffers, so the "
                        "flush copies and the tearing stays");

    esp_lcd_touch_handle_t touch=NULL;
    ESP_ERROR_CHECK(bsp_touch_new(NULL,&touch));
    const lvgl_port_touch_cfg_t input={.disp=screen,.handle=touch};
    panel_input=lvgl_port_add_touch(&input);
    ESP_RETURN_ON_FALSE(panel_input,NULL,tag,"Touch allocation failed");
    panel_screen=screen;
    ESP_LOGI(tag,"RGB: requested PCLK=12MHz, bounce=%d rows, %d frame buffers "
             "at %p and %p, direct mode, core=1",
             CONFIG_BSP_LCD_RGB_BOUNCE_BUFFER_HEIGHT,
             CONFIG_BSP_LCD_RGB_BUFFER_NUMS,first,second);
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
 * Five is the floor the settings page already offers on its slider. It is
 * defined at the top of this file, because the start of the display uses it
 * too: the panel comes up at that brightness and stays there until the
 * first frame is drawn. */

static void backlight_off(void)
{
    /* One call, and nothing that touches the pin.
     *
     * The version before this read the pin back to prove what it did, and
     * to read a pin its input buffer has to be on, so it called
     * gpio_set_direction. That call routes the pad to the simple GPIO
     * output and takes it away from LEDC. After one sleep the backlight
     * was on no PWM at all: the brightness slider moved nothing and the
     * dimming did nothing, until the next restart put the board support's
     * channel back.
     *
     * The measurement had its use and it is over. It answered which of
     * ledc_stop, a pad of our own and a full duty holds the pin, and the
     * answer was all three and none of them dark. Keeping it cost the one
     * thing on this page that still worked. */
    esp_err_t err=bsp_display_brightness_set(BACKLIGHT_SLEEP_PERCENT);
    if(err!=ESP_OK)
        ESP_LOGW("panel_display","backlight to %d%% refused: %s",
                 BACKLIGHT_SLEEP_PERCENT,esp_err_to_name(err));
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
