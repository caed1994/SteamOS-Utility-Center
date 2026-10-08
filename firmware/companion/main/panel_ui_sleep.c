// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_ui_sleep.h"

#include <string.h>

#include "panel_fonts.h"

/* The black cover that a sleeping panel wears.
 *
 * The backlight of this board cannot go dark. Four ways were tried and
 * measured, and the lowest it goes is the five percent that the converter
 * still regulates. See panel_display.c.
 *
 * So what is left is to leave nothing on the screen for that light to show.
 * Stopping the drawing keeps the last frame, and a dimmed page of buttons
 * is a panel that looks switched on. A black object over the whole screen,
 * painted before the drawing stops, is a panel that looks switched off.
 *
 * It is made once and kept. Making one at each sleep is an allocation on a
 * path that has to work when memory is short, and this is the path that
 * makes memory short less often.
 *
 * The cover carries a clock: the time in the font of the clock page, and
 * the day and the date under it. Nothing new to hold in flash: both fonts
 * are in the firmware for the clock page and the band already. It costs a
 * sleeping panel one short draw a minute, of one line, and the light it
 * shows by is the five percent the backlight cannot go below anyway. */
static lv_obj_t *cover, *cover_time, *cover_date;
/* Between a sleep and the wake after it. */
static bool sleeping;

LV_FONT_DECLARE(panel_clock_font);
/* The colours of the clock page, TEXT and MUTED in ui.c. */
#define CLOCK_TIME_COLOUR 0xEDF4FC
#define CLOCK_DATE_COLOUR 0xAEC4DE
/* Between the time and the date. */
#define CLOCK_GAP 14

void panel_ui_sleep_reset(void)
{
    /* The screen was cleaned under us, so the cover went with its children.
     * Holding the pointer past that is a use of a deleted object at the
     * next sleep. See panel_ui_create, which cleans the screen when the
     * language changes. */
    cover = NULL;
    cover_time = NULL;
    cover_date = NULL;
}

/* One line of the clock, across the whole cover and in its middle. A fixed
 * size, so a new text redraws that line and nothing beside it, and a clip
 * rather than a wrap, so a long date stays one line. */
static lv_obj_t *clock_line(lv_obj_t *parent, int32_t width, const lv_font_t *font,
                           uint32_t colour, int32_t y)
{
    lv_obj_t *line = lv_label_create(parent);
    if (!line) return NULL;
    lv_label_set_text(line, "");
    lv_label_set_long_mode(line, LV_LABEL_LONG_MODE_CLIP);
    lv_obj_set_style_text_font(line, font, 0);
    lv_obj_set_style_text_color(line, lv_color_hex(colour), 0);
    lv_obj_set_style_text_align(line, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(line, 0, y);
    lv_obj_set_size(line, width, lv_font_get_line_height(font));
    return line;
}

static lv_obj_t *cover_for(lv_display_t *screen)
{
    if (cover) return cover;
    cover = lv_obj_create(lv_display_get_screen_active(screen));
    if (!cover) return NULL;
    lv_obj_remove_style_all(cover);
    lv_obj_set_pos(cover, 0, 0);
    lv_obj_set_size(cover, lv_display_get_horizontal_resolution(screen),
                    lv_display_get_vertical_resolution(screen));
    lv_obj_set_style_bg_color(cover, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(cover, LV_OPA_COVER, 0);
    lv_obj_remove_flag(cover, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(cover, LV_OBJ_FLAG_CLICKABLE);
    /* Hidden until a sleep shows it: the clock can make it while the panel
     * is awake, and a black screen over an awake panel is a panel that
     * looks switched off. */
    lv_obj_add_flag(cover, LV_OBJ_FLAG_HIDDEN);
    /* The two lines together in the middle of the screen. */
    int32_t time_height = lv_font_get_line_height(&panel_clock_font);
    int32_t date_height = lv_font_get_line_height(&panel_font_24);
    int32_t width = lv_display_get_horizontal_resolution(screen);
    int32_t top = (lv_display_get_vertical_resolution(screen) - time_height - CLOCK_GAP
                   - date_height) / 2;
    cover_time = clock_line(cover, width, &panel_clock_font, CLOCK_TIME_COLOUR, top);
    cover_date = clock_line(cover, width, &panel_font_24, CLOCK_DATE_COLOUR,
                            top + time_height + CLOCK_GAP);
    return cover;
}

void panel_ui_sleep(lv_display_t *screen,lv_indev_t *input,bool sleep)
{
    if(sleep==sleeping)return;
    lv_timer_t *refresh=lv_display_get_refr_timer(screen);
    lv_timer_t *touch=lv_indev_get_read_timer(input);
    if(sleep){
        lv_indev_reset(input,NULL);
        lv_indev_enable(input,false);
        if(touch)lv_timer_pause(touch);
        /* The cover goes on while the drawing still runs. After the pause
         * below, nothing reaches the screen. */
        lv_obj_t *black=cover_for(screen);
        if(black){
            lv_obj_remove_flag(black,LV_OBJ_FLAG_HIDDEN);
            lv_obj_move_foreground(black);
            lv_refr_now(screen);
        }
        lv_display_enable_invalidation(screen,false);
        if(refresh)lv_timer_pause(refresh);
        sleeping=true;
    }else{
        sleeping=false;
        lv_display_enable_invalidation(screen,true);
        if(refresh)lv_timer_resume(refresh);
        if(cover)lv_obj_add_flag(cover,LV_OBJ_FLAG_HIDDEN);
        lv_obj_invalidate(lv_display_get_screen_active(screen));
        lv_refr_now(screen);
        lv_indev_reset(input,NULL);
        lv_indev_wait_release(input);
        lv_indev_enable(input,true);
        if(touch)lv_timer_resume(touch);
    }
}

static bool set_line(lv_obj_t *line, const char *text)
{
    if (!line || strcmp(lv_label_get_text(line), text) == 0) return false;
    lv_label_set_text(line, text);
    return true;
}

void panel_ui_sleep_clock(lv_display_t *screen, const char *time, const char *date)
{
    if (!cover_for(screen) || !cover_time || !cover_date) return;
    if (!time) time = "";
    if (!date) date = "";
    if (strcmp(lv_label_get_text(cover_time), time) == 0 &&
        strcmp(lv_label_get_text(cover_date), date) == 0) return;
    /* A sleeping display takes no invalidation, so nothing reaches the
     * screen while it sleeps. The change takes it for its own two areas and
     * gives it back. Nothing else is dirty then: what changed under the
     * cover during the sleep was dropped, and the wake draws all of it. */
    if (sleeping) lv_display_enable_invalidation(screen, true);
    set_line(cover_time, time);
    set_line(cover_date, date);
    if (sleeping) {
        lv_refr_now(screen);
        lv_display_enable_invalidation(screen, false);
    }
}
