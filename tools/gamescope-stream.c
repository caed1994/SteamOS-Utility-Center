// SPDX-FileCopyrightText: 2026 caed1994
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A PipeWire stream like the stream of gamescope, for tests of the mirror
// on a machine with no gamescope. It follows src/pipewire.cpp of gamescope:
// the node name, the formats (BGRx and NV12, each with and without the
// LINEAR modifier), the rate 0/1, the props of gamescope, the buffers in a
// memfd and a header with no time. It sends a moving bar at 60 Hz.
//
// Build:
//   P=$(pkg-config --cflags --libs libpipewire-0.3)
//   gcc -O2 -o gamescope tools/gamescope-stream.c $P
// The program must have the name "gamescope": PipeWire gives the node the
// name of the program.
//
// Run, with PipeWire and WirePlumber of the same runtime directory. The path
// of the socket must be shorter than 108 bytes:
//   export XDG_RUNTIME_DIR=/tmp/pwr; mkdir -p -m 700 $XDG_RUNTIME_DIR
//   pipewire &
//   D=$(dbus-daemon --session --fork --print-address)
//   export DBUS_SESSION_BUS_ADDRESS=$D
//   wireplumber &
//   ./gamescope 1920 1080 [reneg-after-N]
//
// SIGUSR1 stops the pictures and starts them again: gamescope sends no
// picture while the screen does not change. reneg-after-N makes the
// picture smaller after N pictures, as gamescope does when its output
// changes.
#define _GNU_SOURCE
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#include <pipewire/pipewire.h>
#include <spa/buffer/meta.h>
#include <spa/debug/types.h>
#include <spa/param/buffers.h>
#include <spa/param/video/format-utils.h>
#include <spa/param/video/type-info.h>
#include <spa/pod/builder.h>

// The props of gamescope, from src/pipewire_gamescope.hpp.
#define FORMAT_REQUESTED_SIZE 0x70000
#define FORMAT_FOCUS_APPID 0x70001
#define META_REQUESTED_SIZE_SCALE 0x70000
#define MODIFIER_LINEAR 0ULL

typedef struct {
    int fd;
    void *data;
    size_t size;
    int stride;
    uint32_t width, height;
} picture_t;

static struct pw_main_loop *loop;
static struct pw_stream *stream;
static struct spa_video_info_raw info;
static int stride;
static bool streaming;
static bool paused;
static uint32_t sequence;
static uint32_t width, height;
static int smaller_after = -1;
static int count;

static void add_formats(struct spa_pod_builder *b, uint32_t format,
                        const struct spa_pod **params, int *n)
{
    struct spa_rectangle size = SPA_RECTANGLE(width, height);
    struct spa_rectangle least = {0, 0}, most = {UINT32_MAX, UINT32_MAX};
    struct spa_fraction rate = SPA_FRACTION(0, 1);
    struct spa_pod_frame object, choice;
    for (int linear = 1; linear >= 0; linear--) {
        spa_pod_builder_push_object(b, &object, SPA_TYPE_OBJECT_Format,
                                    SPA_PARAM_EnumFormat);
        spa_pod_builder_add(b,
            SPA_FORMAT_mediaType, SPA_POD_Id(SPA_MEDIA_TYPE_video),
            SPA_FORMAT_mediaSubtype, SPA_POD_Id(SPA_MEDIA_SUBTYPE_raw),
            SPA_FORMAT_VIDEO_format, SPA_POD_Id(format),
            SPA_FORMAT_VIDEO_size, SPA_POD_Rectangle(&size),
            SPA_FORMAT_VIDEO_framerate, SPA_POD_Fraction(&rate),
            FORMAT_REQUESTED_SIZE,
            SPA_POD_CHOICE_RANGE_Rectangle(&least, &least, &most),
            FORMAT_FOCUS_APPID,
            SPA_POD_CHOICE_RANGE_Long(0ll, INT64_MIN, INT64_MAX), 0);
        if (format == SPA_VIDEO_FORMAT_NV12) {
            spa_pod_builder_add(b,
                SPA_FORMAT_VIDEO_colorMatrix, SPA_POD_CHOICE_ENUM_Id(3,
                    SPA_VIDEO_COLOR_MATRIX_BT601, SPA_VIDEO_COLOR_MATRIX_BT601,
                    SPA_VIDEO_COLOR_MATRIX_BT709),
                SPA_FORMAT_VIDEO_colorRange, SPA_POD_CHOICE_ENUM_Id(3,
                    SPA_VIDEO_COLOR_RANGE_16_235, SPA_VIDEO_COLOR_RANGE_16_235,
                    SPA_VIDEO_COLOR_RANGE_0_255), 0);
        }
        if (linear) {
            // A DMA-BUF, which this program cannot give. A reader that
            // chooses it gets no picture, and the log says so.
            spa_pod_builder_prop(b, SPA_FORMAT_VIDEO_modifier,
                                 SPA_POD_PROP_FLAG_MANDATORY);
            spa_pod_builder_push_choice(b, &choice, SPA_CHOICE_Enum, 0);
            spa_pod_builder_long(b, MODIFIER_LINEAR);
            spa_pod_builder_long(b, MODIFIER_LINEAR);
            spa_pod_builder_pop(b, &choice);
        }
        params[(*n)++] = spa_pod_builder_pop(b, &object);
    }
}

static int formats(struct spa_pod_builder *b, const struct spa_pod **params)
{
    int n = 0;
    add_formats(b, SPA_VIDEO_FORMAT_BGRx, params, &n);
    add_formats(b, SPA_VIDEO_FORMAT_NV12, params, &n);
    return n;
}

static void on_state(void *data, enum pw_stream_state old,
                     enum pw_stream_state state, const char *error)
{
    (void)data;
    (void)old;
    fprintf(stderr, "gamescope-stream: %s %s\n",
            pw_stream_state_as_string(state), error ? error : "");
    streaming = state == PW_STREAM_STATE_STREAMING;
    if (state == PW_STREAM_STATE_PAUSED) sequence = 0;
}

static void on_param(void *data, uint32_t id, const struct spa_pod *param)
{
    (void)data;
    if (!param || id != SPA_PARAM_Format) return;
    struct spa_rectangle requested = {0, 0};
    int64_t appid = 0;
    memset(&info, 0, sizeof(info));
    if (spa_pod_parse_object(param, SPA_TYPE_OBJECT_Format, NULL,
            SPA_FORMAT_VIDEO_format, SPA_POD_Id(&info.format),
            SPA_FORMAT_VIDEO_modifier, SPA_POD_OPT_Long(&info.modifier),
            SPA_FORMAT_VIDEO_size, SPA_POD_Rectangle(&info.size),
            SPA_FORMAT_VIDEO_framerate, SPA_POD_Fraction(&info.framerate),
            FORMAT_REQUESTED_SIZE, SPA_POD_OPT_Rectangle(&requested),
            FORMAT_FOCUS_APPID, SPA_POD_OPT_Long(&appid)) < 0) {
        fprintf(stderr, "gamescope-stream: a format it cannot read\n");
        return;
    }
    int bpp = info.format == SPA_VIDEO_FORMAT_NV12 ? 1 : 4;
    stride = SPA_ROUND_UP_N(info.size.width * bpp, 4);
    bool dmabuf = spa_pod_find_prop(param, NULL, SPA_FORMAT_VIDEO_modifier);
    int size = stride * info.size.height;
    if (info.format == SPA_VIDEO_FORMAT_NV12)
        size += ((info.size.height + 1) / 2) * stride;
    fprintf(stderr, "gamescope-stream: format %s %ux%u, rate %u/%u, "
            "requested %ux%u, DMA-BUF %d\n",
            spa_debug_type_find_short_name(spa_type_video_format, info.format),
            info.size.width, info.size.height, info.framerate.num,
            info.framerate.denom, requested.width, requested.height, dmabuf);
    uint8_t buffer[1024];
    struct spa_pod_builder b = SPA_POD_BUILDER_INIT(buffer, sizeof(buffer));
    const struct spa_pod *params[3];
    int type = dmabuf ? 1 << SPA_DATA_DmaBuf : 1 << SPA_DATA_MemFd;
    params[0] = spa_pod_builder_add_object(&b,
        SPA_TYPE_OBJECT_ParamBuffers, SPA_PARAM_Buffers,
        SPA_PARAM_BUFFERS_buffers, SPA_POD_CHOICE_RANGE_Int(4, 1, 8),
        SPA_PARAM_BUFFERS_blocks, SPA_POD_Int(1),
        SPA_PARAM_BUFFERS_size, SPA_POD_Int(size),
        SPA_PARAM_BUFFERS_stride, SPA_POD_Int(stride),
        SPA_PARAM_BUFFERS_dataType, SPA_POD_CHOICE_FLAGS_Int(type));
    params[1] = spa_pod_builder_add_object(&b,
        SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
        SPA_PARAM_META_type, SPA_POD_Id(SPA_META_Header),
        SPA_PARAM_META_size, SPA_POD_Int(sizeof(struct spa_meta_header)));
    params[2] = spa_pod_builder_add_object(&b,
        SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
        SPA_PARAM_META_type, SPA_POD_Id(META_REQUESTED_SIZE_SCALE),
        SPA_PARAM_META_size, SPA_POD_Int(sizeof(float)));
    pw_stream_update_params(stream, params, 3);
}

static void on_add(void *data, struct pw_buffer *buffer)
{
    (void)data;
    struct spa_data *first = &buffer->buffer->datas[0];
    if (!(first->type & (1 << SPA_DATA_MemFd))) {
        fprintf(stderr, "gamescope-stream: the reader wants a DMA-BUF\n");
        first->type = SPA_DATA_Invalid;
        return;
    }
    picture_t *own = calloc(1, sizeof(*own));
    if (!own) abort();
    own->size = (size_t)stride * info.size.height;
    if (info.format == SPA_VIDEO_FORMAT_NV12)
        own->size += (size_t)stride * ((info.size.height + 1) / 2);
    own->fd = memfd_create("gamescope-stream", MFD_CLOEXEC);
    if (own->fd < 0 || ftruncate(own->fd, (off_t)own->size) != 0) abort();
    own->data = mmap(NULL, own->size, PROT_READ | PROT_WRITE, MAP_SHARED,
                     own->fd, 0);
    if (own->data == MAP_FAILED) abort();
    own->stride = stride;
    own->width = info.size.width;
    own->height = info.size.height;
    first->type = SPA_DATA_MemFd;
    first->flags = SPA_DATA_FLAG_READABLE;
    first->fd = own->fd;
    first->mapoffset = 0;
    first->maxsize = (uint32_t)own->size;
    first->data = own->data;
    buffer->user_data = own;
}

static void on_remove(void *data, struct pw_buffer *buffer)
{
    (void)data;
    picture_t *own = buffer->user_data;
    if (!own) return;
    munmap(own->data, own->size);
    close(own->fd);
    free(own);
}

static const struct pw_stream_events events = {
    PW_VERSION_STREAM_EVENTS,
    .state_changed = on_state,
    .param_changed = on_param,
    .add_buffer = on_add,
    .remove_buffer = on_remove,
};

static void on_tick(void *data, uint64_t expirations)
{
    (void)data;
    (void)expirations;
    if (!streaming || paused) return;
    struct pw_buffer *buffer = pw_stream_dequeue_buffer(stream);
    if (!buffer) return;
    picture_t *own = buffer->user_data;
    if (++count == smaller_after) {
        width = (width * 3 / 4) & ~1u;
        height = (height * 3 / 4) & ~1u;
        fprintf(stderr, "gamescope-stream: new size %ux%u\n", width, height);
        uint8_t room[4096];
        struct spa_pod_builder b = SPA_POD_BUILDER_INIT(room, sizeof(room));
        const struct spa_pod *params[4];
        pw_stream_update_params(stream, params, formats(&b, params));
    }
    // gamescope marks a picture of the old size until the new format comes.
    bool old = own && (own->width != width || own->height != height);
    struct spa_buffer *spa = buffer->buffer;
    struct spa_meta_header *header =
        spa_buffer_find_meta_data(spa, SPA_META_Header, sizeof(*header));
    if (header) {
        header->pts = -1;
        header->flags = old ? SPA_META_HEADER_FLAG_CORRUPTED : 0;
        header->seq = sequence++;
        header->dts_offset = 0;
    }
    float *scale = spa_buffer_find_meta_data(spa, META_REQUESTED_SIZE_SCALE,
                                             sizeof(*scale));
    if (scale) *scale = 1.0f;
    struct spa_chunk *chunk = spa->datas[0].chunk;
    chunk->flags = old ? SPA_CHUNK_FLAG_CORRUPTED : 0;
    if (own) {
        chunk->offset = 0;
        chunk->size = info.size.height * own->stride;
        chunk->stride = own->stride;
        uint32_t *pixels = own->data;
        for (uint32_t y = 0; !old && y < own->height; y++)
            for (uint32_t x = 0; x < own->width; x++)
                pixels[y * (own->stride / 4) + x] =
                    (x + count * 8) % own->width < own->width / 3 ? 0x00ff2000
                                                                 : 0x000020ff;
    }
    pw_stream_queue_buffer(stream, buffer);
}

static void on_signal(void *data, int number)
{
    (void)data;
    if (number == SIGUSR1) {
        paused = !paused;
        fprintf(stderr, "gamescope-stream: %s\n", paused ? "still" : "moves");
        return;
    }
    pw_main_loop_quit(loop);
}

int main(int argc, char **argv)
{
    width = argc > 1 ? (uint32_t)atoi(argv[1]) : 1280;
    height = argc > 2 ? (uint32_t)atoi(argv[2]) : 800;
    if (argc > 3 && strncmp(argv[3], "reneg-after-", 12) == 0)
        smaller_after = atoi(argv[3] + 12);
    pw_init(&argc, &argv);
    loop = pw_main_loop_new(NULL);
    struct pw_loop *events_loop = pw_main_loop_get_loop(loop);
    pw_loop_add_signal(events_loop, SIGINT, on_signal, NULL);
    pw_loop_add_signal(events_loop, SIGTERM, on_signal, NULL);
    pw_loop_add_signal(events_loop, SIGUSR1, on_signal, NULL);
    struct pw_context *context = pw_context_new(events_loop, NULL, 0);
    struct pw_core *core = pw_context_connect(context, NULL, 0);
    if (!core) {
        fprintf(stderr, "gamescope-stream: no PipeWire\n");
        return 1;
    }
    stream = pw_stream_new(core, "gamescope",
        pw_properties_new(PW_KEY_MEDIA_CLASS, "Video/Source", NULL));
    struct spa_hook hook;
    pw_stream_add_listener(stream, &hook, &events, NULL);
    uint8_t room[4096];
    struct spa_pod_builder b = SPA_POD_BUILDER_INIT(room, sizeof(room));
    const struct spa_pod *params[4];
    int n = formats(&b, params);
    pw_stream_connect(stream, PW_DIRECTION_OUTPUT, PW_ID_ANY,
                      PW_STREAM_FLAG_DRIVER | PW_STREAM_FLAG_ALLOC_BUFFERS,
                      params, (uint32_t)n);
    struct spa_source *tick = pw_loop_add_timer(events_loop, on_tick, NULL);
    struct timespec first = {0, 1}, every = {0, 16666667};
    pw_loop_update_timer(events_loop, tick, &first, &every, false);
    pw_main_loop_run(loop);
    pw_stream_destroy(stream);
    pw_core_disconnect(core);
    pw_context_destroy(context);
    pw_main_loop_destroy(loop);
    return 0;
}
