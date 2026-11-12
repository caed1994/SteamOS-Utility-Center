// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A random walk over the whole screen of the panel.
//
// The other checks take the ways that somebody thought of. This one takes
// ways at random: answers of the PC with each text and number that main.c
// lets through, taps, long presses, swipes, the keys, the timer, the alarm
// clock, the standby cover, time that passes, and something else that
// happens while a finger is down. It holds nothing but this: the screen
// does not stop, and it touches no memory that is not its own.
//
// The second half needs AddressSanitizer, so tools/panel-walk.sh builds
// this with it and walks many seeds. That run found a read past the text
// of a label, for a name of the PC that ends in the middle of a character,
// and a slider that wrote into a label of a page that was on its way out.
// The job of the workflow walks a few seeds with no sanitizer: a walk that
// stops fails there too.
//
//   check_walk [seed] [operations] [v]
//
// The same seed takes the same way each time. With "v" it writes each
// operation before it does it, so the last line is the one that failed.
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
#include "panel_ui_sleep.h"

static uint32_t pixels[480*480];
static void flush(lv_display_t *d,const lv_area_t *a,uint8_t *p){(void)a;(void)p;lv_display_flush_ready(d);}
static uint32_t ticks=1000;
static uint32_t tick(void){return ticks;}

static uint64_t seed_state;
static uint32_t rnd(void)
{
    seed_state^=seed_state<<13;seed_state^=seed_state>>7;seed_state^=seed_state<<17;
    return (uint32_t)(seed_state>>16);
}
static int upto(int n){return n<=0?0:(int)(rnd()%(uint32_t)n);}
static bool chance(int percent){return upto(100)<percent;}
static int between(int low,int high){return low+upto(high-low+1);}

static bool verbose;
static unsigned long op_count;
#define SAY(...) do{if(verbose){fprintf(stderr,"%lu: ",op_count);fprintf(stderr,__VA_ARGS__);fputc('\n',stderr);}}while(0)

static panel_state_t s;
static lv_display_t *display;
static lv_indev_t *input;
static lv_point_t touch_at;
static bool touch_down;
static bool asleep;
static void read_touch(lv_indev_t *i,lv_indev_data_t *data)
{
    (void)i;
    data->point=touch_at;
    data->state=touch_down?LV_INDEV_STATE_PRESSED:LV_INDEV_STATE_RELEASED;
}

/* What main.c does with the callbacks of the screen, as far as the screen
 * can see it. */
static void action(panel_action_t a)
{
    SAY("  action %d",(int)a);
    /* Most of the time the queue of the board is full, so the walk goes on. */
    if(a==PANEL_SETUP&&chance(6)){s.setup=true;s.online=false;s.wifi=false;
        snprintf(s.setup_ssid,sizeof s.setup_ssid,"SteamOS-Panel-A1B2");
        snprintf(s.setup_password,sizeof s.setup_password,"ABCDEFGH2345");}
    if(a==PANEL_PAIR)s.pairing=PANEL_PAIRING_SEARCH;
    if(a==PANEL_PAIR_CANCEL)s.pairing=PANEL_PAIRING_NONE;
}
static void setting(panel_setting_t k,int v,bool save){SAY("  setting %d=%d save=%d",(int)k,v,(int)save);}
static void sound(int v){(void)v;}
static void led(const panel_led_change_t *c){(void)c;s.led_replies+=chance(60);s.led_code=chance(60)?200:chance(50)?0:403;}
static void cpu(int p){(void)p;s.cpu_replies+=chance(60);s.cpu_code=chance(60)?200:chance(50)?0:409;}

static void step(int ms)
{
    while(ms>0){
        int d=between(3,20);
        if(d>ms)d=ms;
        ticks+=(uint32_t)d;ms-=d;
        lv_timer_handler();
    }
}

/* A text as snprintf("%s") of main.c leaves it: any bytes but nought, cut
 * at the room of the field, so a character of more than one byte can end
 * in its middle. */
static void text(char *out,size_t room)
{
    char raw[400];
    size_t want=chance(25)?0:chance(35)?room+upto(40):(size_t)upto((int)room);
    if(want>sizeof raw-8)want=sizeof raw-8;
    int kind=upto(6);
    size_t n=0;
    while(n<want){
        int k=kind==5?upto(5):kind;
        if(k==0)raw[n++]=(char)between(32,126);
        else if(k==1){static const char *u[]={"ä","ö","ü","ß","Ä","é","°","€","日","本","→","😀","Ж"};
            const char *c=u[upto(13)];size_t l=strlen(c);memcpy(raw+n,c,l);n+=l;}
        else if(k==2)raw[n++]=(char)between(128,255);
        else if(k==3){static const char *w[]={"%","%s","%d","%n","#ff0000 ","\n","\t","\\","\"","  ","-","/"};
            const char *c=w[upto(12)];size_t l=strlen(c);memcpy(raw+n,c,l);n+=l;}
        else raw[n++]=(char)between(1,31);
    }
    raw[n]=0;
    snprintf(out,room,"%s",raw);
}
static void pick(char *out,size_t room,const char *const *list,int count)
{
    if(chance(15))text(out,room);else snprintf(out,room,"%s",list[upto(count)]);
}
static uint64_t big(void){uint64_t v=((uint64_t)rnd()<<32)|rnd();return chance(50)?v>>upto(60):v;}

static void new_state(void)
{
    int what=upto(100);
    if(what<4){memset(&s,0,sizeof s);s.volume=s.cpu_temp=s.gpu_temp=s.gpu_watts=-1;s.gpu_load=s.gpu_mhz=s.gpu_mhz_max=-1;
        s.esp_detail=(panel_power_detail_t){.vbat_mv=-1,.vbus_mv=-1,.vsys_mv=-1,.die_c=PANEL_NO_DEGREES,.phase=-1,.charge_ma=-1,.charge_mv=-1,.input_ma=-1};}
    if(chance(8))s.wifi=chance(80);
    if(chance(10))s.online=s.wifi&&chance(75);
    /* The setup ends with a restart on the board, so it stays. */
    if(upto(1000)<2)s.setup=true;
    if(s.setup){s.online=false;s.wifi=false;}
    s.sound_error=chance(3);s.can_wake=chance(70);
    if(chance(5))text(s.message,sizeof s.message);else if(chance(30))s.message[0]=0;
    if(chance(4))text(s.setup_ssid,sizeof s.setup_ssid);
    if(chance(4))text(s.setup_password,sizeof s.setup_password);
    /* The panel itself, every five seconds on the board. */
    if(chance(30)){
        text(s.self.version,sizeof s.self.version);
        if(chance(60))snprintf(s.self.version,sizeof s.self.version,"%d-%07x",between(0,999),(unsigned)rnd()&0xfffffff);
        text(s.self.ssid,sizeof s.self.ssid);text(s.self.ip,sizeof s.self.ip);
        text(s.self.mac,sizeof s.self.mac);text(s.self.server,sizeof s.self.server);
        s.self.rssi=-upto(129);s.self.uptime_s=rnd()>>upto(32);s.self.heap_free=rnd()>>upto(32);
        s.self.heap_least=rnd()>>upto(32);s.self.psram_free=rnd()>>upto(32);
        s.esp_supply=(panel_supply_t)upto(3);s.esp_battery=between(-1,100);
        s.esp_charging=chance(50);s.esp_cable=chance(50);
        s.esp_detail.vbat_mv=between(-1,8191);s.esp_detail.vbus_mv=between(-1,16383);
        s.esp_detail.vsys_mv=between(-1,16383);s.esp_detail.die_c=chance(20)?PANEL_NO_DEGREES:between(-40,125);
        s.esp_detail.phase=between(-1,7);s.esp_detail.held_heat=chance(20);
        s.esp_detail.held_current=chance(20);s.esp_detail.held_voltage=chance(20);
        s.esp_detail.charge_ma=between(-1,1000);s.esp_detail.charge_mv=between(-1,5000);
        s.esp_detail.input_ma=between(-1,2000);
    }
    /* The update of the firmware. */
    if(chance(10)){
        static const panel_text_id_t why[]={TXT_UPDATE_POWER,TXT_UPDATE_NO_ANSWER,TXT_UPDATE_WRITE,TXT_UPDATE_BROKEN,TXT_UPDATE_FAILED};
        if(chance(60))snprintf(s.update.offered,sizeof s.update.offered,"%d-%07x",between(1,9999),(unsigned)rnd()&0xfffffff);
        else if(chance(50))s.update.offered[0]=0;else text(s.update.offered,sizeof s.update.offered);
        s.update.phase=(panel_update_phase_t)upto(4);s.update.percent=between(0,100);
        s.update.failure=why[upto(5)];
    }
    /* The pairing. */
    if(chance(4)){
        s.pairing=(panel_pairing_t)upto(10);
        if(s.pairing==PANEL_PAIRING_WAIT)snprintf(s.pair_code,sizeof s.pair_code,"%06d",upto(1000000));else s.pair_code[0]=0;
        text(s.pair_pc,sizeof s.pair_pc);text(s.pair_address,sizeof s.pair_address);
        s.pair_can_cancel=chance(50);
    }else if(chance(20))s.pairing=PANEL_PAIRING_NONE;
    /* The clock. */
    s.clock_set=chance(92);
    s.hour=between(0,23);s.minute=between(0,59);s.weekday=between(0,6);s.day=between(1,31);s.month=between(1,12);
    if(!s.online)return;
    /* An answer of the PC, each field as request() of main.c leaves it. */
    s.answers++;
    s.volume=between(-1,100);s.muted=chance(30);
    s.cpu_temp=between(-1,150);s.gpu_temp=between(-1,150);s.gpu_watts=between(-1,2000);
    s.gpu_load=between(-1,100);s.gpu_mhz=between(-1,10000);s.gpu_mhz_max=between(-1,10000);
    if(chance(70)){s.vram_total=big()|1;s.vram_used=big()%(s.vram_total+1);}else s.vram_total=s.vram_used=0;
    s.boost_here=chance(70);s.boost_on=s.boost_here&&chance(50);
    s.zero_rpm_here=chance(70);s.zero_rpm_on=s.zero_rpm_here&&chance(50);
    text(s.host,sizeof s.host);
    s.pad_count=between(0,PANEL_PADS);
    memset(s.pads,0,sizeof s.pads);
    for(int i=0;i<s.pad_count;i++){
        text(s.pads[i].name,sizeof s.pads[i].name);
        if(!s.pads[i].name[0])snprintf(s.pads[i].name,sizeof s.pads[i].name,"Controller");
        s.pads[i].battery=between(-1,100);s.pads[i].charging=chance(40);
    }
    memset(&s.pc,0,sizeof s.pc);
    if(chance(85)){
        text(s.pc.os,sizeof s.pc.os);text(s.pc.build,sizeof s.pc.build);text(s.pc.channel,sizeof s.pc.channel);
        text(s.pc.kernel,sizeof s.pc.kernel);text(s.pc.cpu,sizeof s.pc.cpu);text(s.pc.gpu,sizeof s.pc.gpu);
        text(s.pc.ip,sizeof s.pc.ip);text(s.pc.mac,sizeof s.pc.mac);
        s.pc.uptime_s=chance(10)?-1:(int32_t)(rnd()%316224001u);
        s.pc.cpu_load=between(-1,100);s.pc.fan_rpm=between(-1,100000);s.pc.gpu_fan_rpm=between(-1,100000);
        if(chance(80)){s.pc.memory_total=big()|1;s.pc.memory_used=big()%(s.pc.memory_total+1);}
        s.pc.link=(panel_link_t)upto(3);s.pc.link_mbit=between(-1,1000000);
    }else{s.pc.uptime_s=s.pc.cpu_load=s.pc.fan_rpm=s.pc.gpu_fan_rpm=s.pc.link_mbit=-1;}
    s.pc.answer_ms=between(0,15000);
    for(int which=0;which<2;which++){
        panel_sensor_t *list=which?s.gpu_sensors:s.cpu_sensors;
        int count=between(0,PANEL_SENSORS);
        memset(list,0,sizeof(panel_sensor_t)*PANEL_SENSORS);
        for(int i=0;i<count;i++){
            text(list[i].id,sizeof list[i].id);
            if(!list[i].id[0])snprintf(list[i].id,sizeof list[i].id,"sensor%d",i);
            if(chance(80))snprintf(list[i].id,sizeof list[i].id,"k10temp/temp%d",i);
            text(list[i].name,sizeof list[i].name);
            if(!list[i].name[0])snprintf(list[i].name,sizeof list[i].name,"%.23s",list[i].id);
            list[i].celsius=between(-1,150);
        }
        if(which)s.gpu_sensor_count=count;else s.cpu_sensor_count=count;
    }
    s.game_mode=chance(50);
    if(chance(60))text(s.playing,sizeof s.playing);else s.playing[0]=0;
    if(chance(60)){s.achievements_total=1+(int)(rnd()>>(1+upto(31)));s.achievements_done=upto(s.achievements_total+1);
        if(s.achievements_total<1){s.achievements_total=1;s.achievements_done=0;}}
    else s.achievements_total=s.achievements_done=0;
    s.drive_count=between(0,PANEL_DRIVES);
    for(int i=0;i<s.drive_count;i++){
        text(s.drives[i].name,sizeof s.drives[i].name);
        if(!s.drives[i].name[0])snprintf(s.drives[i].name,sizeof s.drives[i].name,"?");
        s.drives[i].total=big()|1;s.drives[i].free=big()%(s.drives[i].total+1);
    }
    /* The CPU. */
    s.cpu_known=chance(90);s.cpu_here=s.cpu_known&&chance(85);
    {
        const char *keys[PANEL_CPU_PROFILES];
        for(int p=0;p<PANEL_CPU_PROFILES;p++)keys[p]=panel_cpu_key(p);
        if(s.cpu_here)pick(s.cpu_profile,sizeof s.cpu_profile,keys,PANEL_CPU_PROFILES);else s.cpu_profile[0]=0;
        s.cpu_offers=s.cpu_here?(uint8_t)(rnd()&((1u<<PANEL_CPU_PROFILES)-1)):0;
        if(s.cpu_here){text(s.cpu_governor,sizeof s.cpu_governor);text(s.cpu_epp,sizeof s.cpu_epp);text(s.cpu_driver,sizeof s.cpu_driver);}
        else s.cpu_governor[0]=s.cpu_epp[0]=s.cpu_driver[0]=0;
    }
    /* The LED bar and its mirror. */
    s.led_known=chance(90);s.led_here=s.led_known&&chance(85);
    for(int m=0;m<PANEL_LED_MODES;m++){
        const char *keys[32];int count=panel_led_count((panel_led_mode_t)m);
        for(int i=0;i<count&&i<32;i++)keys[i]=panel_led_key((panel_led_mode_t)m,i);
        if(s.led_here){
            if(chance(35))snprintf(s.led_effect[m],sizeof s.led_effect[m],"mirror");
            else pick(s.led_effect[m],sizeof s.led_effect[m],keys,count<32?count:32);
        }else s.led_effect[m][0]=0;
        static const char *const profiles[]={"pop","cinematic","solid"};
        if(s.led_here&&chance(85))pick(s.led_profile[m],sizeof s.led_profile[m],profiles,3);else s.led_profile[m][0]=0;
    }
    s.led_look=s.led_here&&chance(75);
    if(s.led_look){
        if(chance(50))snprintf(s.led_colour,sizeof s.led_colour,"%s",panel_led_colour(upto(PANEL_LED_COLOURS)));
        else snprintf(s.led_colour,sizeof s.led_colour,"#%06x",(unsigned)rnd()&0xffffff);
        s.led_brightness=between(0,255);
    }else{s.led_colour[0]=0;s.led_brightness=-1;}
    {
        static const char *const states[]={"running","waiting","starting","asking","refused","no-portal","busy",
            "no-plugin","failed","off","idle","no-gstreamer","no-screen","gone",""};
        if(s.led_here)pick(s.led_mirror.state,sizeof s.led_mirror.state,states,15);else s.led_mirror.state[0]=0;
        text(s.led_mirror.detail,sizeof s.led_mirror.detail);text(s.led_mirror.source,sizeof s.led_mirror.source);
        s.led_mirror.fps=between(-1,1000);s.led_mirror.cpu=between(-1,100000);
    }
}

/* Each object that takes a press and is on the screen now. */
static lv_obj_t *found[400];
static int found_count;
static void collect(lv_obj_t *o)
{
    if(lv_obj_has_flag(o,LV_OBJ_FLAG_HIDDEN))return;
    if(lv_obj_has_flag(o,LV_OBJ_FLAG_CLICKABLE)&&lv_obj_get_event_count(o)>0&&found_count<400)found[found_count++]=o;
    for(uint32_t i=0;i<lv_obj_get_child_count(o);i++)collect(lv_obj_get_child(o,i));
}
static lv_point_t somewhere(void)
{
    lv_point_t p={(int32_t)between(0,479),(int32_t)between(0,479)};
    if(chance(75)){
        found_count=0;
        collect(lv_screen_active());
        if(found_count){
            lv_area_t c;
            lv_obj_get_coords(found[upto(found_count)],&c);
            p.x=(int32_t)between(c.x1,c.x2);p.y=(int32_t)between(c.y1,c.y2);
            if(p.x<0)p.x=0;
            if(p.x>479)p.x=479;
            if(p.y<0)p.y=0;
            if(p.y>479)p.y=479;
        }
    }
    return p;
}

static panel_alarm_clock_t wall;
static void tick_clocks(void)
{
    /* As ui_tick of main.c: the timer, the alarm clock, and the keys. */
    uint32_t seconds=ticks/1000;
    wall.known=s.clock_set;
    wall.second=(uint8_t)(seconds%60);wall.minute=(uint8_t)(seconds/60%60);wall.hour=(uint8_t)(seconds/3600%24);
    wall.day=(int32_t)(126000+seconds/86400);wall.weekday=(uint8_t)((seconds/86400+4)%7);
    panel_timer_news_t news=panel_ui_timer_tick();
    panel_alarm_news_t wake=panel_ui_alarm_clock_tick(&wall);
    if((news.went_off||wake.went_off)&&asleep){panel_ui_sleep(display,input,false);asleep=false;SAY("  a ring wakes the display");}
    if(news.beep||wake.beep)panel_ui_alarm_volume();
    panel_ui_alarm_clock_take_snooze();
}

int main(int argc,char **argv)
{
    seed_state=argc>1?strtoull(argv[1],NULL,0):1;
    if(!seed_state)seed_state=1;
    seed_state*=0x9E3779B97F4A7C15ull;
    unsigned long operations=argc>2?strtoul(argv[2],NULL,0):2000;
    verbose=argc>3;
    lv_init();
    lv_tick_set_cb(tick);
    display=lv_display_create(480,480);
    lv_display_set_color_format(display,LV_COLOR_FORMAT_XRGB8888);
    lv_display_set_buffers(display,pixels,NULL,sizeof(pixels),LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display,flush);
    input=lv_indev_create();
    lv_indev_set_type(input,LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(input,read_touch);
    static panel_settings_t settings;
    settings=(panel_settings_t){.brightness=70,.sound_volume=30,.touch_tones=chance(50),.lift_wake=true,
        .language=(panel_language_t)upto(2),.sleep_after=upto(5),.page_order=rnd(),.page_hidden=rnd(),
        .theme=(panel_theme_t)upto(3),.accent=(panel_accent_t)upto(9),.alarm=rnd(),
        .cpu_sensor=rnd(),.gpu_sensor=rnd()};
    static panel_history_t history;
    panel_history_reset(&history);
    panel_ui_history_use(&history);
    panel_ui_slides(!chance(15));
    panel_ui_create(action,setting,sound,&settings);
    panel_ui_led_use(led);
    panel_ui_cpu_use(cpu);
    memset(&s,0,sizeof s);
    s.wifi=true;s.online=true;
    new_state();
    panel_ui_update(&s);
    step(100);
    int in_setup=0;
    for(op_count=0;op_count<operations;op_count++){
        int op=upto(100);
        if(s.setup&&++in_setup>40)break;
        if(asleep){
            /* A sleeping panel: time passes, the clock of the cover changes,
             * and a key or a touch wakes it. */
            if(op<70){step(between(50,3000));tick_clocks();
                char hours[8],date[64],next[24];
                snprintf(hours,sizeof hours,"%02d:%02d",wall.hour,wall.minute);
                panel_text_date(date,sizeof date,wall.weekday,between(1,31),between(1,12));
                panel_ui_alarm_clock_next(next,sizeof next);
                panel_ui_sleep_clock(display,chance(90)?hours:"",date,next);
                if(chance(20))panel_ui_history_tick(&s,ticks);
                if(chance(10)){new_state();}
            }else{SAY("wake");panel_ui_sleep(display,input,false);asleep=false;panel_ui_update(&s);}
            continue;
        }
        if(op<30){
            lv_point_t p=somewhere();
            SAY("tap %d,%d on %s",(int)p.x,(int)p.y,panel_ui_where());
            touch_at=p;touch_down=true;step(between(30,120));
            touch_down=false;step(between(30,200));
        }else if(op<35){
            lv_point_t p=somewhere();
            SAY("long press %d,%d",(int)p.x,(int)p.y);
            touch_at=p;touch_down=true;step(between(400,1500));
            touch_down=false;step(between(30,200));
        }else if(op<52){
            lv_point_t from=somewhere(),to;
            if(chance(60)){to.x=(int32_t)between(0,479);to.y=from.y+(int32_t)between(-30,30);}
            else if(chance(70)){to.x=from.x+(int32_t)between(-30,30);to.y=(int32_t)between(0,479);}
            else{to.x=(int32_t)between(0,479);to.y=(int32_t)between(0,479);}
            if(to.x<0)to.x=0;
            if(to.x>479)to.x=479;
            if(to.y<0)to.y=0;
            if(to.y>479)to.y=479;
            int steps=between(2,12);
            SAY("swipe %d,%d to %d,%d",(int)from.x,(int)from.y,(int)to.x,(int)to.y);
            touch_at=from;touch_down=true;step(between(15,40));
            for(int i=1;i<=steps;i++){
                touch_at.x=from.x+(to.x-from.x)*i/steps;touch_at.y=from.y+(to.y-from.y)*i/steps;
                step(between(10,35));
            }
            touch_down=false;step(between(20,600));
        }else if(op<72){
            SAY("a new state");
            new_state();
            tick_clocks();
            if(chance(40))panel_ui_history_tick(&s,ticks);
            panel_ui_update(&s);
            step(between(0,250));
        }else if(op<80){
            int ms=chance(20)?between(1000,70000):between(50,1500);
            SAY("%d ms pass",ms);
            /* Time in the turns of ui_tick. */
            while(ms>0){int d=ms>200?200:ms;step(d);ms-=d;tick_clocks();if(chance(30))panel_ui_update(&s);}
        }else if(op<83){
            SAY("the home key");
            bool stopped=panel_ui_timer_stop();
            bool snoozed=panel_ui_alarm_clock_snooze();
            if(!stopped&&!snoozed)panel_ui_home();
            step(between(0,400));
        }else if(op<85){
            SAY("the standby key");
            bool stopped=panel_ui_timer_stop();
            bool snoozed=panel_ui_alarm_clock_snooze();
            if(!stopped&&!snoozed&&s.update.phase!=PANEL_UPDATE_RUNNING){panel_ui_sleep(display,input,true);asleep=true;}
        }else if(op<88){
            int which=upto(7);
            SAY("open %d",which);
            if(which==0)panel_ui_settings_open();
            else if(which==1)panel_ui_pads_open();
            else if(which==2)panel_ui_pc_open();
            else if(which==3)panel_ui_self_open();
            else if(which==4)panel_ui_arrange_open();
            else if(which==5)panel_ui_confirm((panel_action_t)between(PANEL_SUSPEND,PANEL_GAME_MODE));
            else (void)panel_ui_where();
            step(between(0,400));
        }else if(op<89){
            SAY("draw now");
            lv_obj_invalidate(lv_screen_active());
            lv_refr_now(display);
        }else{
            /* Something else happens while a finger is down, and the finger
             * then moves and goes up: an answer of the PC, a key, a page
             * that opens or closes, a ring, the standby. */
            int what=upto(8);
            SAY("a touch held through event %d",what);
            touch_at=somewhere();touch_down=true;step(between(20,120));
            if(what==0){new_state();panel_ui_update(&s);}
            else if(what==1){bool stopped=panel_ui_timer_stop();bool snoozed=panel_ui_alarm_clock_snooze();
                if(!stopped&&!snoozed)panel_ui_home();}
            else if(what==2)panel_ui_settings_open();
            else if(what==3){int which=upto(4);if(which==0)panel_ui_pads_open();else if(which==1)panel_ui_pc_open();
                else if(which==2)panel_ui_self_open();else panel_ui_arrange_open();}
            else if(what==4)panel_ui_confirm((panel_action_t)between(PANEL_SUSPEND,PANEL_GAME_MODE));
            else if(what==5){tick_clocks();}
            else if(what==6){s.pairing=(panel_pairing_t)upto(10);
                if(s.pairing==PANEL_PAIRING_WAIT)snprintf(s.pair_code,sizeof s.pair_code,"%06d",upto(1000000));
                panel_ui_update(&s);}
            else{panel_ui_sleep(display,input,true);step(between(50,400));panel_ui_sleep(display,input,false);panel_ui_update(&s);}
            step(between(10,150));
            /* The finger moves on, a little or far. */
            int moves=upto(6);
            for(int i=0;i<moves;i++){
                touch_at.x+=(int32_t)between(-60,60);touch_at.y+=(int32_t)between(-25,25);
                if(touch_at.x<0)touch_at.x=0;
                if(touch_at.x>479)touch_at.x=479;
                if(touch_at.y<0)touch_at.y=0;
                if(touch_at.y>479)touch_at.y=479;
                step(between(10,60));
            }
            if(chance(30)){new_state();panel_ui_update(&s);step(between(10,250));}
            touch_down=false;step(between(20,300));
        }
        const char *where=panel_ui_where();
        assert(where&&where[0]);
    }
    printf("ok: seed %s, %lu operations, %u ms of panel time, on %s\n",argc>1?argv[1]:"1",op_count,ticks,panel_ui_where());
    return 0;
}
