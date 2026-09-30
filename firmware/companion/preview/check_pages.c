// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The middle band, which scrolls, and the two pages that came with it.
//
// Nothing here draws: it builds the screens on a host LVGL and reads the
// words off them. What it holds is the part a person sees, which is the
// part a rule in Python cannot reach.
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include "lvgl.h"
#include "ui.h"
static unsigned actions;
static panel_action_t last_action;
static void action(panel_action_t a){actions++;last_action=a;}
static void setting(panel_setting_t k,int v,bool save){(void)k;(void)v;(void)save;}
static void sound(int volume){(void)volume;}
// A label somebody can see. The hidden ones are still in the tree, and a
// search that walks into them answers "there it is" about a card that is
// not on the screen. Every rule below reads this, so every one of them is
// about what is drawn.
static lv_obj_t *label(lv_obj_t *root,const char *text)
{
    if(lv_obj_has_flag(root,LV_OBJ_FLAG_HIDDEN))return NULL;
    if(lv_obj_check_type(root,&lv_label_class)&&strcmp(lv_label_get_text(root),text)==0)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){lv_obj_t *f=label(lv_obj_get_child(root,i),text);if(f)return f;}
    return NULL;
}
static void click(const char *text)
{
    lv_obj_t *l=label(lv_screen_active(),text);assert(l);
    lv_obj_t *b=lv_obj_get_parent(l);
    while(b&&!lv_obj_check_type(b,&lv_button_class))b=lv_obj_get_parent(b);
    assert(b);
    lv_obj_send_event(b,LV_EVENT_CLICKED,NULL);
}
// The band is the one object on the screen that scrolls sideways.
static lv_obj_t *find_band(lv_obj_t *root)
{
    if(lv_obj_get_scroll_dir(root)==LV_DIR_HOR&&lv_obj_get_child_count(root)==3)return root;
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){lv_obj_t *f=find_band(lv_obj_get_child(root,i));if(f)return f;}
    return NULL;
}
// How much memory this process really holds, out of the kernel.
//
// The second number in /proc/self/statm is the resident page count. It is
// here because the count the screen keeps of its own bytes cannot say
// whether they were freed, and that is the question.
static size_t resident_bytes(void)
{
    FILE *f=fopen("/proc/self/statm","r");
    if(!f)return 0;
    unsigned long total=0,resident=0;
    int read=fscanf(f,"%lu %lu",&total,&resident);
    fclose(f);
    if(read!=2)return 0;
    return (size_t)resident*(size_t)sysconf(_SC_PAGESIZE);
}
static void flushed(lv_display_t *d,const lv_area_t *a,uint8_t *p)
{(void)a;(void)p;lv_display_flush_ready(d);}
static lv_obj_t *find_image(lv_obj_t *root)
{
    if(lv_obj_check_type(root,&lv_image_class)){
        const void *s=lv_image_get_src(root);
        if(s&&lv_image_src_get_type(s)==LV_IMAGE_SRC_VARIABLE){
            const lv_image_dsc_t *d=s;
            if(d->header.cf==LV_COLOR_FORMAT_RAW)return root;
        }
    }
    for(unsigned i=0;i<lv_obj_get_child_count(root);i++){
        lv_obj_t *f=find_image(lv_obj_get_child(root,i));if(f)return f;}
    return NULL;
}
// A picture of a chosen length, out of the one on disk.
//
// The frame header of a JPEG sits at the front, so room after the file
// changes nothing that LVGL reads. This is how one small sample stands in
// for pictures of every size the panel meets, up to the ceiling the
// service applies.
// Everything LVGL complained about while this check ran.
//
// LVGL answers a picture it cannot open by drawing nothing and writing a
// line. The card then looks empty, which reads like a panel with no game
// on it. So the lines are counted, and a check that leaves one behind
// fails.
//
// This is the rule that would have found the shipped defect on the first
// run. The pixel rules below say the picture is right; this one says
// LVGL never had to give up on it.
static unsigned complaints;
static void complained(lv_log_level_t level,const char *text)
{
    if(level>=LV_LOG_LEVEL_WARN&&level!=LV_LOG_LEVEL_USER)complaints++;
    fputs(text,stderr);
}
// Where the kind of the frame header sits, in a baseline JPEG.
//
// Only the check needs this. It walks the markers the same way ui.c does,
// and stops at the one that says the picture is baseline.
static size_t sof_at(const uint8_t *bytes,size_t size)
{
    size_t at=2;
    while(at+3<size){
        if(bytes[at]!=0xFF)return 0;
        uint8_t kind=bytes[at+1];
        if(kind==0xFF){at++;continue;}
        if(kind==0xD8||kind==0x01||(kind>=0xD0&&kind<=0xD7)){at+=2;continue;}
        if(kind==0xC0)return at+1;
        at+=2+(((size_t)bytes[at+2]<<8)|bytes[at+3]);
    }
    return 0;
}
static void *copy_of(const uint8_t *sample,size_t sample_size,size_t room)
{
    uint8_t *bytes=malloc(room);
    assert(bytes);
    size_t take=room<sample_size?room:sample_size;
    memcpy(bytes,sample,take);
    if(room>take)memset(bytes+take,0,room-take);
    return bytes;
}
// How many different colours stand inside an object, on the screen as it
// was last drawn.
//
// A rectangle nothing drew into holds one. This counts up to a handful
// and stops, because the question is "more than a flat fill", not "how
// many".
static unsigned colours_in(const uint8_t *pixels,lv_obj_t *object)
{
    lv_area_t box;
    lv_obj_get_coords(object,&box);
    uint16_t seen[16];
    unsigned count=0;
    for(int32_t y=box.y1;y<=box.y2&&y<480;y++){
        for(int32_t x=box.x1;x<=box.x2&&x<480;x++){
            if(x<0||y<0)continue;
            size_t at=((size_t)y*480+(size_t)x)*2;
            uint16_t px=(uint16_t)(pixels[at]|(pixels[at+1]<<8));
            unsigned i=0;
            for(;i<count;i++)if(seen[i]==px)break;
            if(i==count){
                if(count==16)return count;
                seen[count++]=px;
            }
        }
    }
    return count;
}
// The mean brightness of the left eighth and of the right eighth of an
// object, on the screen as it was last drawn.
static void band_of(const uint8_t *pixels,lv_obj_t *object,
                    unsigned *left,unsigned *right)
{
    lv_area_t box;
    lv_obj_get_coords(object,&box);
    int32_t wide=box.x2-box.x1+1, eighth=wide/8;
    unsigned long sum[2]={0,0};unsigned long count[2]={0,0};
    for(int32_t y=box.y1;y<=box.y2&&y<480;y++){
        if(y<0)continue;
        for(int32_t x=box.x1;x<=box.x2&&x<480;x++){
            if(x<0)continue;
            int side=-1;
            if(x<box.x1+eighth)side=0;
            else if(x>box.x2-eighth)side=1;
            if(side<0)continue;
            size_t at=((size_t)y*480+(size_t)x)*2;
            uint16_t px=(uint16_t)(pixels[at]|(pixels[at+1]<<8));
            unsigned red=(px>>11)&0x1F,green=(px>>5)&0x3F,blue=px&0x1F;
            sum[side]+=red*2+green+blue*2;count[side]++;
        }
    }
    *left=count[0]?(unsigned)(sum[0]/count[0]):0;
    *right=count[1]?(unsigned)(sum[1]/count[1]):0;
}
static uint8_t *slurp(const char *path,size_t *size)
{
    FILE *f=fopen(path,"rb");if(!f){perror(path);exit(2);}
    fseek(f,0,SEEK_END);long n=ftell(f);fseek(f,0,SEEK_SET);
    uint8_t *bytes=malloc((size_t)n);
    if(!bytes||fread(bytes,1,(size_t)n,f)!=(size_t)n){exit(2);}
    fclose(f);*size=(size_t)n;return bytes;
}
static panel_state_t base(void)
{
    panel_state_t s={.online=true,.wifi=true,.battery=50,.volume=30,
                     .cpu_temp=40,.gpu_temp=45,.gpu_watts=60};
    return s;
}
int main(int argc,char **argv)
{
    const char *sample_path=argc>1?argv[1]
                           :"firmware/companion/preview/sample-header.jpg";
    lv_init();
    lv_log_register_print_cb(complained);
    static uint8_t pixels[480*480*2];
    lv_display_t *screen=lv_display_create(480,480);
    lv_display_set_color_format(screen,LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(screen,pixels,NULL,sizeof pixels,
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(screen,flushed);
    panel_settings_t settings={.brightness=70,.sound_volume=30,.language=PANEL_ENGLISH};
    panel_ui_create(action,setting,sound,&settings);

    // Three pages, and the band snaps so there is no place between two.
    lv_obj_t *band=find_band(lv_screen_active());
    assert(band);
    assert(lv_obj_get_child_count(band)==3);
    assert(lv_obj_has_flag(band,LV_OBJ_FLAG_SCROLL_ONE));
    // A band that takes a press swallows the one meant for a button on it.
    assert(!lv_obj_has_flag(band,LV_OBJ_FLAG_CLICKABLE));

    // Nothing playing is the ordinary case, and it says so.
    panel_state_t s=base();
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_NOTHING_PLAYING)));

    // A game that runs is named.
    snprintf(s.playing,sizeof(s.playing),"Portal 2");
    panel_ui_update(&s);
    assert(label(lv_screen_active(),"Portal 2"));
    assert(!label(lv_screen_active(),panel_text(TXT_NOTHING_PLAYING)));

    // The session, and the button that carries where it goes rather than
    // "the other one".
    s.game_mode=true;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_MODE_GAME)));
    assert(label(lv_screen_active(),panel_text(TXT_TO_DESKTOP)));
    actions=0;
    click(panel_text(TXT_TO_DESKTOP));
    // It asks first, the way standby and switch off do: a session that
    // goes takes what is open with it.
    assert(actions==0);
    assert(label(lv_screen_active(),panel_text(TXT_CONFIRM_MODE)));
    // The question and the two buttons, and nothing under it. The line
    // that stands under the power questions says where the press lands,
    // which a session question answers in its own words.
    assert(!label(lv_screen_active(),panel_text(TXT_CONFIRM_HERE)));
    assert(label(lv_screen_active(),panel_text(TXT_CANCEL)));
    click(panel_text(TXT_CONFIRM));
    assert(actions==1 && last_action==PANEL_DESKTOP_MODE);

    // And the other way around.
    s.game_mode=false;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_MODE_DESKTOP)));
    assert(label(lv_screen_active(),panel_text(TXT_TO_GAME)));
    actions=0;
    click(panel_text(TXT_TO_GAME));
    click(panel_text(TXT_CONFIRM));
    assert(actions==1 && last_action==PANEL_GAME_MODE);

    // The power questions keep theirs, so the rule above is about the
    // session and not about the line being gone everywhere.
    click(panel_text(TXT_POWEROFF));
    assert(label(lv_screen_active(),panel_text(TXT_CONFIRM_HERE)));
    click(panel_text(TXT_CANCEL));

    // The drives. Two of them, and the bar fills with what is used.
    s.drive_count=2;
    snprintf(s.drives[0].name,sizeof(s.drives[0].name),"SSD");
    s.drives[0].total=1000ULL*1024*1024*1024;
    s.drives[0].free=250ULL*1024*1024*1024;
    snprintf(s.drives[1].name,sizeof(s.drives[1].name),"SDCARD");
    s.drives[1].total=64ULL*1024*1024*1024;
    s.drives[1].free=8ULL*1024*1024*1024;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),"SSD"));
    assert(label(lv_screen_active(),"SDCARD"));
    // Below a hundred it carries one decimal, above it none. "916.3" is
    // one character of meaning and three of noise.
    char wanted[64];
    snprintf(wanted,sizeof(wanted),"250 GB %s / 1000 GB",panel_text(TXT_FREE));
    assert(label(lv_screen_active(),wanted));
    snprintf(wanted,sizeof(wanted),"8.0 GB %s / 64.0 GB",panel_text(TXT_FREE));
    assert(label(lv_screen_active(),wanted));
    assert(!label(lv_screen_active(),panel_text(TXT_NO_DRIVES)));

    // A bar stands the same distance from both borders of its card.
    // Reported from the board: the first version put the row at nought,
    // so it touched the left border and stood 24 off the right one. This
    // measures the drawn object rather than reading the source, because
    // the fault was in what the numbers add up to and not in any one.
    lv_obj_update_layout(lv_screen_active());
    lv_obj_t *named=label(lv_screen_active(),"SSD");
    assert(named);
    lv_obj_t *row=lv_obj_get_parent(named);
    lv_obj_t *card=lv_obj_get_parent(row);
    int32_t on_the_left=lv_obj_get_x(row);
    int32_t on_the_right=lv_obj_get_width(card)-on_the_left-lv_obj_get_width(row);
    assert(on_the_left>0);
    assert(on_the_left==on_the_right);

    // A machine that answers with no drive says so rather than showing
    // an empty bar, which reads as room.
    s.drive_count=0;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_NO_DRIVES)));

    // More drives than there is room for take the room there is.
    s.drive_count=PANEL_DRIVES+2;
    for(int i=0;i<PANEL_DRIVES;i++){
        snprintf(s.drives[i].name,sizeof(s.drives[i].name),"D%d",i);
        s.drives[i].total=100ULL*1024*1024*1024;s.drives[i].free=1;
    }
    panel_ui_update(&s);
    for(int i=0;i<PANEL_DRIVES;i++){
        char name[8];snprintf(name,sizeof(name),"D%d",i);
        assert(label(lv_screen_active(),name));
    }

    // Offline leaves the second page at a dash and the third at its word,
    // rather than at the last thing the PC said, which reads as current.
    s.online=false;
    panel_ui_update(&s);
    assert(label(lv_screen_active(),"--"));
    assert(label(lv_screen_active(),panel_text(TXT_NOTHING_PLAYING)));
    assert(label(lv_screen_active(),panel_text(TXT_NO_DRIVES)));

    // The language button rebuilds every screen, and a pointer kept past
    // that clean is a pointer to freed memory that a touch reaches.
    s.online=true;s.game_mode=true;
    panel_ui_update(&s);
    panel_settings_t german={.brightness=70,.sound_volume=30,.language=PANEL_GERMAN};
    panel_ui_create(action,setting,sound,&german);
    panel_ui_update(&s);
    assert(label(lv_screen_active(),panel_text(TXT_MODE_GAME)));
    assert(label(lv_screen_active(),"Portal 2"));

    // The picture, and what becomes of it.
    //
    // A real JPEG, because the thing under test is what LVGL makes of
    // what the screen hands it. Bytes that are not a picture proved
    // nothing: they went through a path that refuses them.
    size_t sample_size=0;
    uint8_t *sample=slurp(sample_path,&sample_size);
    assert(sample_size>16);

    // A picture of any length, out of the one on disk. The header sits at
    // the front, so trailing room does not change what LVGL reads, and
    // the length is what panel_ui_banner_bytes answers with.
    #define A_PICTURE(bytes) copy_of(sample,sample_size,(bytes))

    assert(panel_ui_banner_bytes()==0);
    panel_ui_banner(A_PICTURE(4000),4000);
    assert(panel_ui_banner_bytes()==4000);

    // The size LVGL will draw at, which is the whole reason this file
    // exists twice.
    //
    // For bytes in memory the JPEG decoder answers with the numbers out
    // of the descriptor and not out of the file. See decoder_info in
    // lv_tjpgd.c. The first firmware that shipped this card handed over a
    // descriptor of nought by nought, so LVGL sized the picture at
    // nought by nought and the panel drew that. Nothing here looked,
    // because nothing here drew.
    lv_obj_t *picture=find_image(lv_screen_active());
    assert(picture);
    const void *source=lv_image_get_src(picture);
    assert(source);
    lv_image_header_t said;
    assert(lv_image_decoder_get_info(source,&said)==LV_RESULT_OK);
    // The size of the file that sits next to this one. 460 across is
    // what Steam keeps and what the card is built for.
    assert(said.w==460 && said.h==214);

    // And it reaches the screen.
    //
    // A rectangle that was never drawn holds one colour. A picture of a
    // gradient holds many, so counting them says the decoder ran and the
    // pixels landed where the card is.
    // The card is on the third page, so the band goes there first. A
    // picture drawn off the side of the screen is a picture nobody sees,
    // and the rule below would then read the page that is up instead.
    //
    // The band is looked for again. The language rule above rebuilt every
    // screen, so the one found at the top of this file went with it.
    lv_obj_t *band_now=find_band(lv_screen_active());
    assert(band_now);
    assert(lv_obj_get_child_count(band_now)==3);
    lv_obj_scroll_to_view(lv_obj_get_child(band_now,2),LV_ANIM_OFF);
    lv_obj_update_layout(lv_screen_active());
    lv_refr_now(screen);
    assert(colours_in(pixels,picture)>4);

    // And it is the picture, and not what the bytes look like read as
    // pixels.
    //
    // Counting colours does not tell those apart: rubbish has plenty. So
    // the sample is built dark on the left and light on the right, and
    // this reads both ends back off the screen. It is the same rule
    // check_boot uses on the animation, which found a decoder writing a
    // background colour over a transparent one.
    //
    // Without LV_USE_FS_MEMFS the JPEG decoder refuses bytes in memory,
    // the built-in one takes them as a bitmap, and the card fills with
    // the file read as pixels. That is what the panel did, and this is
    // the rule that sees it.
    unsigned left=0,right=0;
    band_of(pixels,picture,&left,&right);
    assert(right>left+40);

    // And LVGL never gave up on it.
    assert(complaints==0);

    // A second picture frees the first. Nothing grows.
    void *second=A_PICTURE(5000);
    panel_ui_banner(second,5000);
    assert(panel_ui_banner_bytes()==5000);

    // The same pointer again is not a free and a take of the same memory.
    panel_ui_banner(second,5000);
    assert(panel_ui_banner_bytes()==5000);

    // The end of a game. This is the question somebody asked out loud:
    // the picture goes when the game does.
    panel_ui_banner(NULL,0);
    assert(panel_ui_banner_bytes()==0);

    // Bytes that are not a picture never reach LVGL. They arrive from the
    // network, so a half answer is a thing that happens, and a descriptor
    // built from one is what sized the card at nought.
    void *rubbish=malloc(1000);
    assert(rubbish);
    memset(rubbish,0xA5,1000);
    panel_ui_banner(rubbish,1000);
    assert(panel_ui_banner_bytes()==0);
    // A picture cut off after its first bytes is the same answer.
    panel_ui_banner(copy_of(sample,3,3),3);
    assert(panel_ui_banner_bytes()==0);

    // And a JPEG that is not baseline.
    //
    // TJPGD reads SOF0 and nothing else: SOF1 to SOF15 all come back
    // JDR_FMT3 from jd_prepare. Progressive JPEG is SOF2 and is what a
    // picture off the web usually is. Such a picture used to get in, and
    // LVGL then failed to open it at every single refresh.
    //
    // The file on disk is baseline, so the marker is moved here instead.
    // This is not a progressive picture and does not pretend to be one:
    // what is under test is the door, which reads the marker and nothing
    // else.
    {
        uint8_t *not_baseline=copy_of(sample,sample_size,sample_size);
        size_t marker=sof_at(not_baseline,sample_size);
        assert(marker>0);
        not_baseline[marker]=0xC2;
        panel_ui_banner(not_baseline,sample_size);
        assert(panel_ui_banner_bytes()==0);
    }
    // And it says so. A card that stays empty with nothing in the log is
    // a fault nobody can find from the panel.
    assert(complaints==3);
    complaints=0;

    // And a rebuild of the screens keeps the picture rather than asking
    // for it again. A picture is about the machine, not about the
    // language somebody reads.
    panel_ui_banner(A_PICTURE(6000),6000);
    panel_ui_create(action,setting,sound,&settings);
    assert(panel_ui_banner_bytes()==6000);
    panel_ui_banner(NULL,0);
    assert(panel_ui_banner_bytes()==0);

    // And the bytes really go.
    //
    // Everything above this reads panel_ui_banner_bytes, which is the
    // screen's own count and not the memory. Take the free out of
    // panel_ui_banner and every rule above still passes, so none of them
    // answers "is it freed".
    //
    // This does. Two hundred pictures of a quarter of a megabyte, taken
    // and dropped one after another. Freed, the allocator hands the same
    // block back and the resident size stays where it was. Leaked, it
    // grows by fifty megabytes, which no rounding hides.
    size_t before=resident_bytes();
    // A reading of nought is a reader that failed, and the comparison
    // below would then pass whatever happened. Silence is not success.
    assert(before>0);
    for(int i=0;i<200;i++){
        void *one=A_PICTURE(256*1024);
        panel_ui_banner(one,256*1024);
        assert(panel_ui_banner_bytes()==256*1024);
        panel_ui_banner(NULL,0);
    }
    size_t after=resident_bytes();
    assert(panel_ui_banner_bytes()==0);
    // Ten megabytes of room for the allocator and for everything else
    // this process does. A leak here is fifty.
    assert(after<before+10u*1024*1024);
    // Nothing else along the way gave LVGL something it could not use.
    assert(complaints==0);
    free(sample);

    puts("OK: three pages that snap, the session and its target button, the "
         "drives with their bars, every one of them offline, and a real "
         "picture that LVGL sizes, decodes and draws, that is taken, "
         "replaced, dropped, kept over a rebuild and really freed, with "
         "anything it cannot decode turned away at the door.");
    return 0;
}
