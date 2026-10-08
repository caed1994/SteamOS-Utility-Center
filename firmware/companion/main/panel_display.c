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
#include <inttypes.h>
#include <stdint.h>
#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/ledc.h"
#include "panel_boot.h"
#include "panel_frames.h"
#include "panel_taps.h"

static lv_display_t *panel_screen;
static lv_indev_t *panel_input;
/* Kept, so that something can read the touch while LVGL does not.
 * See panel_display_touched. */
static esp_lcd_touch_handle_t panel_touch;
static bool is_asleep;

/* The pixel clock of the display: in the startup animation, awake, and in
 * a sleep.
 *
 * 12 MHz is about 45 Hz on this panel, a frame every 22.1 ms, and 16 MHz,
 * the default of the board, is about 60 Hz, a frame every 16.6 ms. See
 * PANEL_FRAME_CLOCKS. A flush waits for the end of a frame, so what a
 * frame of LVGL costs is a whole number of them.
 *
 * The startup animation holds each of its frames for 40 ms. That lands on
 * two frames at 12 MHz, 44.2 ms, and on three at 16 MHz, 49.7 ms, so it
 * plays at 12 MHz. See the long note in panel_display_start.
 *
 * A scroll is the other way round. The page of the panel measured 29 ms
 * of drawing for a frame of it. That is two frames at either clock, 44.2
 * ms at 12 MHz and 33.2 ms at 16 MHz, so after the animation the panel
 * runs at 16 MHz. The scan-out takes a third more of PSRAM then, and the
 * card of the frames says what that costs the drawing.
 *
 * In a sleep the screen shows
 * the black cover and nothing else, and the board still scans it out at
 * the full rate: the bounce buffers are filled by an interrupt on the CPU,
 * which copies every frame out of PSRAM, and while it copies the clock of
 * the CPU runs at 240 MHz. Read off the board, the CPU spent only about
 * 55 % of a sleep at the low speed, at 12 MHz awake. 4 MHz is a third of
 * that clock and a quarter of 16 MHz, and so is the copying. The driver
 * takes a new pixel clock at the next VSYNC (lcd_rgb_panel_try_update_pclk),
 * so no change cuts a frame. */
#define PANEL_PCLK_BOOT_HZ   12000000
#define PANEL_PCLK_HZ        16000000
#define PANEL_PCLK_SLEEP_HZ   4000000
static esp_lcd_panel_handle_t panel_rgb;
/* The clock of an awake panel: the one of the animation until it is over.
 * Read and written by the LVGL task alone. */
static uint32_t pclk_awake=PANEL_PCLK_BOOT_HZ;

/* The pixel clocks of a frame of the panel: 520 to a line and 510 lines,
 * each with its pulse and porches. They are those of
 * ST7701_480_480_PANEL_60HZ_RGB_TIMING, which the board support gives the
 * panel: 480+10+10+20 by 480+10+10+10.
 *
 * The page of the panel agrees with them to the millisecond. At 16 MHz it
 * read frame intervals of 66 and 99 ms, which are four and six frames of
 * 16.58 ms, and at 12 MHz 66 and 88 ms, three and four of 22.1 ms. The
 * notes before them said 16.9 and 22.5, read off the rough heaps of the
 * startup animation.
 *
 * The count of the frames takes the frame of an awake panel, for the
 * periods of each frame of a movement. A sleeping one shows nothing that
 * moves. See panel_frames.h. */
#define PANEL_FRAME_CLOCKS (520 * 510)
static int64_t frame_us(uint32_t pclk_hz)
{
    return (int64_t)PANEL_FRAME_CLOCKS*1000000/pclk_hz;
}

/* The lowest brightness this board holds steady, in percent.
 *
 * It has two readers. A sleeping panel goes here because it cannot go dark,
 * and the start of the display goes here because the board support lights
 * the panel at full before anything has been drawn. The long note above
 * backlight_off says why nought is not an option.
 *
 * Measured: a firmware with the slider of the settings page down to one per
 * cent went to the board, and five was the lowest brightness that held
 * steady. The slider stops at the same number, PANEL_BRIGHTNESS_MIN, so no
 * panel is set darker than it sleeps. */
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
/* LVGL's log, through the same door as everything else.
 *
 * Read off the board: a line of LVGL's and a line of the Wi-Fi driver's
 * arrived cut into each other, one inside the middle word of the other.
 * LV_LOG_PRINTF writes with printf from the LVGL task while ESP_LOG writes
 * from whatever task had something to say, and the two share a UART and no
 * lock. Two writers, one wire.
 *
 * ESP_LOG takes a lock. So this hands LVGL's lines to it and the interleave
 * cannot happen. It also gives them the timestamp and the tag that every
 * other line has.
 *
 * The trailing newline goes: ESP_LOG adds its own, and LVGL ends its
 * buffer with one. */
/* The same line again and again, which is what a fault in the draw path
 * looks like.
 *
 * LVGL draws about thirty times a second, so a complaint that belongs to
 * one object is thirty lines a second, for as long as that object is on
 * the screen. Every one of them is a write to the UART from the task that
 * draws, and that task has a frame to fill before the panel asks for the
 * next one. Enough of them and the screen tears and the watchdog fires.
 *
 * So a repeat is counted rather than written, and the count goes out with
 * the next one that gets through. Nothing is lost that a person needs:
 * the first line says what is wrong, and the count says it did not stop.
 */
#define LOG_REPEATS 64
static char last_line[80];
static uint32_t repeats;
static void lvgl_log(lv_log_level_t level,const char *text)
{
    size_t len=strlen(text);
    while(len && (text[len-1]=='\n' || text[len-1]=='\r')) len--;
    /* As much of the line as is kept, which is what two lines are
     * compared on. Two different lines that agree over the first eighty
     * characters count as one, and that costs a count rather than a
     * line. */
    size_t keep=len<sizeof(last_line)-1?len:sizeof(last_line)-1;
    if(strlen(last_line)==keep && strncmp(text,last_line,keep)==0){
        if(++repeats%LOG_REPEATS)return;
    }else{
        memcpy(last_line,text,keep);last_line[keep]=0;
        repeats=0;
    }
    /* USER before ERROR, because USER stands above it.
     *
     * The order in LVGL is TRACE, INFO, WARN, ERROR, USER, NONE, so a
     * test of "at least ERROR" catches USER as well. The board showed
     * that: the timing of the startup animation, which panel_boot.c
     * writes with LV_LOG_USER, arrived in the log as an error. */
    if(level==LV_LOG_LEVEL_USER)
        ESP_LOGI("lvgl","%.*s%s",(int)len,text,repeats?" and again":"");
    else if(level>=LV_LOG_LEVEL_ERROR)
        ESP_LOGE("lvgl","%.*s%s",(int)len,text,repeats?" and again":"");
    else if(level==LV_LOG_LEVEL_WARN)
        ESP_LOGW("lvgl","%.*s%s",(int)len,text,repeats?" and again":"");
    else
        ESP_LOGI("lvgl","%.*s%s",(int)len,text,repeats?" and again":"");
}

/* Sixteen kilobytes for the LVGL task: the most it used on the board, 9124
 * bytes, and 7 KB over that. See panel_display_start. */
#define PANEL_LVGL_STACK (16 * 1024)

size_t panel_display_stack_bytes(void){return PANEL_LVGL_STACK;}

/* The frames for panel_frames.h, at the three moments it asks for.
 *
 * LV_EVENT_REFR_START opens a refresh. The flush of the last area of a
 * frame hands that frame to the panel, and the port waits inside it for
 * the end of the frame on the glass. So the start of that flush is the end
 * of the work, and its end is the moment the frame is on the screen. The
 * other areas of a frame only draw: in direct mode the port acts on the
 * last one alone.
 *
 * The startup animation is no scroll, so its frames do not count. */
static void frame_begun(lv_event_t *e)
{
    (void)e;
    panel_frames_begin(&panel_frames,esp_timer_get_time());
}
static void frame_flush(lv_event_t *e)
{
    if(lv_display_flush_is_last(lv_event_get_target(e)))
        panel_frames_drawn(&panel_frames,esp_timer_get_time());
}
static void frame_flushed(lv_event_t *e)
{
    if(!lv_display_flush_is_last(lv_event_get_target(e)))return;
    if(panel_boot_playing())panel_frames_break(&panel_frames);
    else panel_frames_shown(&panel_frames,esp_timer_get_time());
}

/* The clock of LVGL, in whole milliseconds out of the system timer.
 *
 * esp_lvgl_port counts the clock itself: a timer of its own adds
 * timer_period_ms to it each time it fires, and that is 5 ms by default
 * (ESP_LVGL_PORT_INIT_CONFIG). So the clock moved in steps of 5 ms. An
 * animation of LVGL, such as the snap of the band, works out where it is
 * from that clock at each frame, and a frame of 33 ms took 30 or 35 ms of
 * it. With this the clock is the time that passed, to the millisecond.
 *
 * The count of the port goes on and nothing reads it: lv_tick_get takes
 * this function when there is one. The clock jumps forward once, by the
 * time from the start of the chip to the start of the port, and that is
 * before anything is on the screen. It runs over after 49 days, which
 * LVGL takes: lv_tick_diff counts across the wrap. */
static uint32_t lvgl_tick_ms(void)
{
    return (uint32_t)(esp_timer_get_time()/1000);
}

/* The touch, read by LVGL every LV_DEF_REFR_PERIOD between two frames.
 *
 * In place of the reader of esp_lvgl_port, for two reasons. That one wraps
 * the read in ESP_ERROR_CHECK, so a single read that the shared I2C bus
 * refused restarted the whole panel. Here such a read changes nothing: the
 * finger stays where the read before it put it, and the count of errors on
 * the page of the panel goes up. And each read goes to panel_taps, which
 * measures what happens to a press. See panel_taps.h. */
static bool touch_down;
static lv_point_t touch_at;
static void touch_read(lv_indev_t *indev,lv_indev_data_t *data)
{
    (void)indev;
    uint32_t now=(uint32_t)(esp_timer_get_time()/1000);
    esp_lcd_touch_point_data_t point={0};
    uint8_t count=0;
    esp_err_t err=esp_lcd_touch_read_data(panel_touch);
    if(err==ESP_OK)err=esp_lcd_touch_get_data(panel_touch,&point,&count,1);
    panel_taps_press_t done;
    bool over;
    if(err!=ESP_OK){
        over=panel_taps_read(&panel_taps,now,false,touch_down,touch_at.x,touch_at.y,-1,&done);
    }else{
        touch_down=count>0;
        if(touch_down){touch_at.x=point.x;touch_at.y=point.y;}
        over=panel_taps_read(&panel_taps,now,true,touch_down,point.x,point.y,
                             touch_down?point.strength:-1,&done);
    }
    data->point=touch_at;
    data->state=touch_down?LV_INDEV_STATE_PRESSED:LV_INDEV_STATE_RELEASED;
    if(over){
        static const char *const ends[]={"nothing to tap","tap","swipe","LOST tap"};
        ESP_LOGI("panel_touch","%s: %" PRIu32 " ms, moved %d px, smallest contact %d",
                 ends[done.end],done.ms,done.moved,done.weakest);
    }
}
/* What LVGL made of the press on its way. PRESSED says what it came down
 * on, and something that takes a tap is something with a handler of its
 * own: the cards under the buttons have none. RELEASED comes with the
 * object being scrolled still set for a swipe, and CLICKED after it for a
 * tap. */
static void touch_event(lv_event_t *e)
{
    lv_event_code_t code=lv_event_get_code(e);
    lv_obj_t *on=lv_event_get_param(e);
    if(code==LV_EVENT_PRESSED)panel_taps_pressed(&panel_taps,on&&lv_obj_get_event_count(on)>0);
    else if(code==LV_EVENT_RELEASED)panel_taps_released(&panel_taps,lv_indev_get_scroll_obj(panel_input)!=NULL);
    else if(code==LV_EVENT_CLICKED)panel_taps_clicked(&panel_taps);
}
/* The configuration of the controller, read once, for the page of the
 * panel: the thresholds a finger has to cross and the period of the
 * reports. Read only. Nothing here writes to the controller. */
static void touch_chip_read(void)
{
    uint8_t config[PANEL_TAPS_CHIP_LENGTH];
    esp_err_t err=esp_lcd_panel_io_rx_param(panel_touch->io,PANEL_TAPS_CHIP_START,config,sizeof config);
    if(err!=ESP_OK||!panel_taps_chip_parse(config,sizeof config,&panel_taps_chip)){
        ESP_LOGW("panel_touch","The configuration of the touch controller could not be read: %s",
                 err!=ESP_OK?esp_err_to_name(err):"its checksum does not hold");
        return;
    }
    ESP_LOGI("panel_touch","Touch controller: configuration %c, thresholds %d down and %d up, "
             "a report every %d ms",panel_taps_chip.version,panel_taps_chip.touch_level,
             panel_taps_chip.leave_level,panel_taps_chip.report_ms);
}

lv_display_t *panel_display_start(void)
{
    const char *tag="panel_display";
    ESP_RETURN_ON_FALSE(xPortGetCoreID()==1,NULL,tag,"Display must initialize on core 1");
    lvgl_port_cfg_t port=ESP_LVGL_PORT_INIT_CONFIG();
    port.task_affinity=1;
    /* The stack of the task that draws, said here rather than taken.
     *
     * Reported from the board, in the one line that named it:
     *
     *     ***ERROR*** A stack overflow in task taskLVGL has been detected.
     *
     * It took the panel down again and again, at the end of the startup
     * animation and at the moment the screen went to standby, and each
     * restart ran into the next one.
     *
     * ESP_LVGL_PORT_INIT_CONFIG carries a number of its own and Espressif
     * has raised it at least once, so a panel that depends on it depends on
     * something that moves under it. This says the number, and internal
     * memory pays for it: see panel_psram.h.
     *
     * ui_tick measures what is really left, from inside this task, and says
     * so. A number here without that is a guess that nobody checks.
     *
     * Twelve kilobytes stood here first, and the overflow did not come
     * back. Sixteen and then twenty-four followed, on readings of 708 and
     * then 716 bytes left. Those were not of this task. app_main calls
     * ui_tick once itself, on the start task, and the reading of that call
     * was the 3584 bytes of the start task. watch_stack now reads from the
     * LVGL timer only, and the health line says what this task really
     * uses.
     *
     * Two health lines from the board read 15548 and then 15452 of 24576
     * bytes left, after a standby and after the end of the startup
     * animation, so the task used 9124 bytes at the most. Sixteen
     * kilobytes leave 7 KB over that, for the ways the panel did not take
     * while it was read. The pixels are not drawn on this stack: LVGL
     * draws in its thread "swdraw", on a stack of its own. */
    port.task_stack=PANEL_LVGL_STACK;
    ESP_ERROR_CHECK(lvgl_port_init(&port));
    /* After lvgl_port_init, which is what calls lv_init. */
    lv_log_register_print_cb(lvgl_log);
    /* Under the lock, so the clock does not change in the middle of a turn
     * of the LVGL task. See lvgl_tick_ms. */
    lvgl_port_lock(0);
    lv_tick_set_cb(lvgl_tick_ms);
    lvgl_port_unlock();

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
    /* The clock of the startup animation first. See PANEL_PCLK_HZ and
     * panel_display_boot_over. */
    ESP_ERROR_CHECK(esp_lcd_rgb_panel_set_pclk(panel,PANEL_PCLK_BOOT_HZ));
    panel_frames_period(&panel_frames,frame_us(PANEL_PCLK_BOOT_HZ));
    panel_rgb=panel;

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
     * or 230400 pixels. The startup animation covers 256 by 256 of that,
     * which is 65536. The rest is the black behind it, drawn again at
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
     * So the area it draws and the area it keeps are the same square, the difference of the two is empty, and no copy happens.
     * The animation draws 65536 pixels a frame instead of 230400 and
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
     * 90 ms, and those are 22 to 23 apart. So a period is about 22 ms and
     * the panel runs at about 45 Hz. The timings of this panel work out
     * at 22.1 ms at 12 MHz, and the card of the frames later read that to
     * the millisecond. See PANEL_FRAME_CLOCKS.
     *
     * That also says where the floor is. A frame holds for 40 ms in the
     * file and a flush lands on a boundary, so the fastest a frame goes is
     * two periods, or 44.2 ms. 51 is close to it. Reaching it asks the
     * heaviest frames to do their work in under 5 ms, which a GIF decoder
     * at this size does not do. A faster pixel clock makes it worse
     * rather than better: at 16 MHz a period is 16.6 ms, and 40 ms then
     * lands on three of them, which is 49.7.
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
    panel_touch=touch;
    const lvgl_port_touch_cfg_t input={.disp=screen,.handle=touch};
    panel_input=lvgl_port_add_touch(&input);
    ESP_RETURN_ON_FALSE(panel_input,NULL,tag,"Touch allocation failed");
    touch_chip_read();
    panel_taps_reset(&panel_taps);
    lvgl_port_lock(0);
    lv_indev_set_read_cb(panel_input,touch_read);
    lv_indev_add_event_cb(panel_input,touch_event,LV_EVENT_ALL,NULL);
    lv_display_add_event_cb(screen,frame_begun,LV_EVENT_REFR_START,NULL);
    lv_display_add_event_cb(screen,frame_flush,LV_EVENT_FLUSH_START,NULL);
    lv_display_add_event_cb(screen,frame_flushed,LV_EVENT_FLUSH_FINISH,NULL);
    lvgl_port_unlock();
    panel_screen=screen;
    ESP_LOGI(tag,"RGB: requested PCLK=%dMHz until the animation ends, then %dMHz, "
             "bounce=%d rows, %d frame buffers "
             "at %p and %p, direct mode, core=1",
             PANEL_PCLK_BOOT_HZ/1000000,PANEL_PCLK_HZ/1000000,
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

void panel_display_boot_over(void)
{
    if(pclk_awake==PANEL_PCLK_HZ)return;
    pclk_awake=PANEL_PCLK_HZ;
    panel_frames_period(&panel_frames,frame_us(pclk_awake));
    /* A sleeping panel stays at the clock of the sleep, and its wake takes
     * this one. */
    if(panel_rgb && !is_asleep)esp_lcd_rgb_panel_set_pclk(panel_rgb,pclk_awake);
    ESP_LOGI("panel_display","The startup animation is over, so the pixel clock is %d MHz",
             PANEL_PCLK_HZ/1000000);
}

/* Whether a finger is on the glass, asked of the controller itself.
 *
 * A sleeping panel stops reading the touch: panel_ui_sleep turns the input
 * device off and pauses the timer that reads it. What it does not do is
 * switch the controller off. The GT911 stays on the I2C bus and still
 * knows what it feels, and nobody asks. This asks.
 *
 * Meant for the sleeping panel and for nothing else. Call it while LVGL
 * reads the same controller on its own timer and two readers share one
 * bus, so this answers false while the panel is awake rather than leave
 * that to a caller who forgets.
 */
bool panel_display_touched(void)
{
    if(!panel_touch || !is_asleep)return false;
    if(esp_lcd_touch_read_data(panel_touch)!=ESP_OK)return false;
    uint16_t x=0,y=0,strength=0;
    uint8_t count=0;
    return esp_lcd_touch_get_coordinates(panel_touch,&x,&y,&strength,&count,1)
           && count>0;
}

void panel_display_sleep_clock(const char *time,const char *date)
{
    if(panel_screen)panel_ui_sleep_clock(panel_screen,time,date);
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
        /* LVGL reads no touch while the panel sleeps, and the gap is no
         * late read. */
        panel_taps_break(&panel_taps);
        backlight_off();
        /* After the cover is on the screen, so the slow frames are black
         * ones. See PANEL_PCLK_SLEEP_HZ. */
        if(panel_rgb)esp_lcd_rgb_panel_set_pclk(panel_rgb,PANEL_PCLK_SLEEP_HZ);
        ESP_LOGI("panel_display",
                 "Display asleep: backlight down to %d%%, which is as dark "
                 "as this board goes, pixel clock %d MHz",BACKLIGHT_SLEEP_PERCENT,
                 PANEL_PCLK_SLEEP_HZ/1000000);
    }else{
        /* The full pixel clock before the first frame that shows anything. */
        if(panel_rgb)esp_lcd_rgb_panel_set_pclk(panel_rgb,pclk_awake);
        panel_taps_break(&panel_taps);
        panel_ui_sleep(panel_screen,panel_input,false);
        esp_err_t err=backlight_on(brightness);
        if(err!=ESP_OK){
            backlight_off();
            panel_ui_sleep(panel_screen,panel_input,true);
            if(panel_rgb)esp_lcd_rgb_panel_set_pclk(panel_rgb,PANEL_PCLK_SLEEP_HZ);
            return err;
        }
        ESP_LOGI("panel_display","Backlight ON: PWM restored to %d%%",brightness);
    }
    is_asleep=sleep;
    return ESP_OK;
}
