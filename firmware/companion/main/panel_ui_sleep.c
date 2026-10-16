// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_ui_sleep.h"

#include <string.h>

#include "icons.h"
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
 * shows by is the five percent the backlight cannot go below anyway.
 *
 * Under the date, the next ring of the alarm clock: its icon and the time.
 * The row shows only while an alarm is set, and the three lines then share
 * the middle of the screen. */
static lv_obj_t *cover, *cover_time, *cover_date, *cover_alarm, *cover_alarm_text;
/* Between a sleep and the wake after it. */
static bool sleeping;

LV_FONT_DECLARE(panel_clock_font);
/* The text and the words of the dark theme, in either theme: the cover is
 * black in both, and a light cover would be a panel that looks switched
 * on. See panel_theme.h; tests/test_panel_theme.py holds the two equal. */
#define CLOCK_TIME_COLOUR 0xEDF4FC
#define CLOCK_DATE_COLOUR 0xAEC4DE
/* Between the time and the date, between the date and the alarm, and
 * between the icon of the alarm and its time. */
#define CLOCK_GAP 14
#define ALARM_GAP 18
#define ALARM_ICON_GAP 8

void panel_ui_sleep_reset(void)
{
    /* The screen was cleaned under us, so the cover went with its children.
     * Holding the pointer past that is a use of a deleted object at the
     * next sleep. See panel_ui_create, which cleans the screen when the
     * language changes. */
    cover = NULL;
    cover_time = NULL;
    cover_date = NULL;
    cover_alarm = NULL;
    cover_alarm_text = NULL;
}

static int32_t alarm_height(void)
{
    int32_t text = lv_font_get_line_height(&panel_font_24);
    return text > (int32_t)icon_alarm_clock.header.h ? text : (int32_t)icon_alarm_clock.header.h;
}

/* The lines together in the middle of the screen, and the row of the alarm
 * with them when it shows. */
static void place_lines(lv_display_t *screen, bool alarm)
{
    int32_t time_height = lv_font_get_line_height(&panel_clock_font);
    int32_t date_height = lv_font_get_line_height(&panel_font_24);
    int32_t high = time_height + CLOCK_GAP + date_height;
    if (alarm) high += ALARM_GAP + alarm_height();
    int32_t top = (lv_display_get_vertical_resolution(screen) - high) / 2;
    lv_obj_set_y(cover_time, top);
    lv_obj_set_y(cover_date, top + time_height + CLOCK_GAP);
    if (cover_alarm)
        lv_obj_set_y(cover_alarm, top + time_height + CLOCK_GAP + date_height + ALARM_GAP);
}

/* The row of the alarm: the icon and the time beside it, the two together
 * in the middle, in the colour of the date. Hidden until an alarm is set. */
static void alarm_row(lv_obj_t *parent, int32_t width)
{
    cover_alarm = lv_obj_create(parent);
    if (!cover_alarm) return;
    lv_obj_remove_style_all(cover_alarm);
    lv_obj_set_size(cover_alarm, width, alarm_height());
    lv_obj_remove_flag(cover_alarm, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(cover_alarm, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(cover_alarm, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_flex_flow(cover_alarm, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(cover_alarm, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(cover_alarm, ALARM_ICON_GAP, 0);
    lv_obj_t *bell = lv_image_create(cover_alarm);
    lv_obj_t *text = lv_label_create(cover_alarm);
    if (!bell || !text) {
        lv_obj_delete(cover_alarm);
        cover_alarm = NULL;
        return;
    }
    lv_image_set_src(bell, &icon_alarm_clock);
    lv_obj_set_style_image_recolor(bell, lv_color_hex(CLOCK_DATE_COLOUR), 0);
    lv_obj_set_style_image_recolor_opa(bell, LV_OPA_COVER, 0);
    lv_label_set_text(text, "");
    lv_obj_set_style_text_font(text, &panel_font_24, 0);
    lv_obj_set_style_text_color(text, lv_color_hex(CLOCK_DATE_COLOUR), 0);
    cover_alarm_text = text;
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
    int32_t width = lv_display_get_horizontal_resolution(screen);
    cover_time = clock_line(cover, width, &panel_clock_font, CLOCK_TIME_COLOUR, 0);
    cover_date = clock_line(cover, width, &panel_font_24, CLOCK_DATE_COLOUR, 0);
    if (cover_time && cover_date) {
        alarm_row(cover, width);
        place_lines(screen, false);
    }
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

void panel_ui_sleep_clock(lv_display_t *screen, const char *time, const char *date,
                          const char *alarm)
{
    if (!cover_for(screen) || !cover_time || !cover_date) return;
    if (!time) time = "";
    if (!date) date = "";
    if (!alarm || !cover_alarm_text) alarm = "";
    if (strcmp(lv_label_get_text(cover_time), time) == 0 &&
        strcmp(lv_label_get_text(cover_date), date) == 0 &&
        (!cover_alarm_text || strcmp(lv_label_get_text(cover_alarm_text), alarm) == 0)) return;
    /* A sleeping display takes no invalidation, so nothing reaches the
     * screen while it sleeps. The change takes it for its own two areas and
     * gives it back. Nothing else is dirty then: what changed under the
     * cover during the sleep was dropped, and the wake draws all of it. */
    if (sleeping) lv_display_enable_invalidation(screen, true);
    set_line(cover_time, time);
    set_line(cover_date, date);
    /* An alarm that comes or goes moves the lines, to keep them in the
     * middle together. That redraws the clock, and only then. */
    if (set_line(cover_alarm_text, alarm)) {
        bool show = alarm[0] != 0;
        if (show == lv_obj_has_flag(cover_alarm, LV_OBJ_FLAG_HIDDEN)) {
            /* Hidden while it moves, and the layout done before it shows.
             * A row that shows before the layout runs draws the place it
             * leaves, and that place is under the clock. */
            lv_obj_add_flag(cover_alarm, LV_OBJ_FLAG_HIDDEN);
            place_lines(screen, show);
            lv_obj_update_layout(cover);
            if (show) lv_obj_remove_flag(cover_alarm, LV_OBJ_FLAG_HIDDEN);
        }
    }
    if (sleeping) {
        lv_refr_now(screen);
        lv_display_enable_invalidation(screen, false);
    }
}
