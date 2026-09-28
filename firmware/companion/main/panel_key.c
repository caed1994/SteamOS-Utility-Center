// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_key.h"
#include <string.h>
void panel_key_reset(panel_key_t *key){memset(key,0,sizeof(*key));}
bool panel_key_sample(panel_key_t *key,bool pressed,uint32_t now)
{
    if(!key->initialized){
        key->initialized=true;key->raw=pressed;key->changed_ms=now;return false;
    }
    if(pressed!=key->raw){key->raw=pressed;key->changed_ms=now;return false;}
    if((uint32_t)(now-key->changed_ms)<PANEL_KEY_SETTLE_MS)return false;
    if(!key->ready){if(!pressed){key->ready=true;key->stable=false;}return false;}
    if(pressed==key->stable)return false;
    key->stable=pressed;
    if(pressed){key->pressed_ms=now;key->down=true;return false;}
    bool short_press=key->down
        && (uint32_t)(now-key->pressed_ms)>=PANEL_KEY_SHORTEST_MS
        && (uint32_t)(now-key->pressed_ms)<=PANEL_KEY_LONGEST_MS;
    key->down=false;
    return short_press;
}
