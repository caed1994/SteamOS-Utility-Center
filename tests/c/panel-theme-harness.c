// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// panel_theme.c, asked line by line by tests/test_panel_theme.py.
//
//   size                       prints PANEL_THEMES and PANEL_ACCENTS
//   palette <theme> <accent>   prints each colour of the palette as
//                              name=rrggbb, in the order of panel_palette_t
//   accent <accent>            prints the number of the text of its name
//   theme <theme>              prints the number of the text of its name
//   led <colour>               prints the number of the text of the name of
//                              that colour of the LED bar, from panel_led.c
//   text <number>              prints that text in English
#include <stdio.h>
#include <string.h>

#include "panel_led.h"
#include "panel_text.h"
#include "panel_theme.h"

int main(void)
{
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        int theme, accent, number;
        if (strncmp(line, "size", 4) == 0) {
            printf("%d %d\n", PANEL_THEMES, PANEL_ACCENTS);
        } else if (sscanf(line, "palette %d %d", &theme, &accent) == 2) {
            panel_palette_t p = panel_palette(theme, accent);
            printf("bg=%06x card=%06x edge=%06x text=%06x muted=%06x button=%06x "
                   "accent=%06x accent_text=%06x on_accent=%06x "
                   "knob=%06x knob_edge=%06x slider_knob=%06x "
                   "red=%06x danger=%06x danger_edge=%06x online=%06x offline=%06x "
                   "curve_cpu=%06x curve_gpu=%06x curve_watts=%06x\n",
                   (unsigned)p.bg, (unsigned)p.card, (unsigned)p.edge, (unsigned)p.text,
                   (unsigned)p.muted, (unsigned)p.button, (unsigned)p.accent,
                   (unsigned)p.accent_text, (unsigned)p.on_accent, (unsigned)p.knob,
                   (unsigned)p.knob_edge, (unsigned)p.slider_knob, (unsigned)p.red,
                   (unsigned)p.danger, (unsigned)p.danger_edge, (unsigned)p.online,
                   (unsigned)p.offline, (unsigned)p.curve_cpu, (unsigned)p.curve_gpu,
                   (unsigned)p.curve_watts);
        } else if (sscanf(line, "accent %d", &accent) == 1) {
            printf("%d\n", (int)panel_accent_name(accent));
        } else if (sscanf(line, "theme %d", &theme) == 1) {
            printf("%d\n", (int)panel_theme_name(theme));
        } else if (sscanf(line, "led %d", &number) == 1) {
            printf("%d\n", (int)panel_led_colour_name(number));
        } else if (sscanf(line, "text %d", &number) == 1) {
            printf("%s\n", panel_text((panel_text_id_t)number));
        } else {
            return 2;
        }
        fflush(stdout);
    }
    return 0;
}
