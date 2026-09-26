#define _GNU_SOURCE
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <initguid.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <d3d11_4.h>
#include <dxgi1_2.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <immintrin.h>

#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
#include <libavutil/avutil.h>
#include <libavutil/pixdesc.h>
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_d3d11va.h>

#include <vpl/mfxvideo.h>
#include <vpl/mfxdispatcher.h>
#include <vpl/mfxmemory.h>

static enum AVPixelFormat get_hw_format(AVCodecContext *ctx, const enum AVPixelFormat *pix_fmts) {
    const enum AVPixelFormat *p;
    for (p = pix_fmts; *p != -1; p++) {
        if (*p == AV_PIX_FMT_D3D11) {
            return *p;
        }
    }
    return AV_PIX_FMT_NONE;
}

static int cmp_dbl_asc(const void* a, const void* b) {
    double da = *(const double*)a;
    double db = *(const double*)b;
    return (da > db) - (da < db);
}

#define MAX_CACHED_DECODE_VIEWS 128
typedef struct {
    ID3D11Texture2D* pTex;
    int slice_idx;
    ID3D11VideoProcessorInputView* pInputView;
} CachedDecodeInputView;

#define BASE_W 3840
#define BASE_H 2160
#define HUD_W 2560
#define HUD_H 1440

#define DECODE_RING_SIZE 4
#define ENCODE_POOL_SIZE 16
#define MAX_MULTI_CLIPS 64

// Timing helper
static double get_time_ms(LARGE_INTEGER start, LARGE_INTEGER end, LARGE_INTEGER freq) {
    return (double)(end.QuadPart - start.QuadPart) * 1000.0 / (double)freq.QuadPart;
}

// Vectorized Planar YUV420P10LE -> P010 Converter (AVX2 with arbitrary row pitch)
static void yuv420p10le_to_p010_pitch(
    const uint16_t* src_y, int src_y_stride,
    const uint16_t* src_u, int src_u_stride,
    const uint16_t* src_v, int src_v_stride,
    uint8_t* dst_p010_base, int dst_row_pitch_bytes,
    int width, int height
) {
    int dst_stride_elems = dst_row_pitch_bytes / 2;
    uint16_t* dst_y = (uint16_t*)dst_p010_base;
    int src_y_stride_elems = src_y_stride / 2;

    for (int y = 0; y < height; y++) {
        const uint16_t* sy = src_y + y * src_y_stride_elems;
        uint16_t* dy = dst_y + y * dst_stride_elems;
        int x = 0;
        for (; x <= width - 16; x += 16) {
            __m256i v = _mm256_loadu_si256((const __m256i*)(sy + x));
            v = _mm256_slli_epi16(v, 6);
            _mm256_storeu_si256((__m256i*)(dy + x), v);
        }
        for (; x < width; x++) {
            dy[x] = (uint16_t)(sy[x] << 6);
        }
    }

    uint8_t* dst_uv_base = dst_p010_base + height * dst_row_pitch_bytes;
    uint16_t* dst_uv = (uint16_t*)dst_uv_base;
    int uv_width = width / 2;
    int uv_height = height / 2;
    int src_u_stride_elems = src_u_stride / 2;
    int src_v_stride_elems = src_v_stride / 2;

    for (int y = 0; y < uv_height; y++) {
        const uint16_t* su = src_u + y * src_u_stride_elems;
        const uint16_t* sv = src_v + y * src_v_stride_elems;
        uint16_t* duv = dst_uv + y * dst_stride_elems;
        int x = 0;
        for (; x <= uv_width - 16; x += 16) {
            __m256i u = _mm256_loadu_si256((const __m256i*)(su + x));
            __m256i v = _mm256_loadu_si256((const __m256i*)(sv + x));
            u = _mm256_slli_epi16(u, 6);
            v = _mm256_slli_epi16(v, 6);

            __m256i uv_lo = _mm256_unpacklo_epi16(u, v);
            __m256i uv_hi = _mm256_unpackhi_epi16(u, v);

            __m256i out0 = _mm256_permute2x128_si256(uv_lo, uv_hi, 0x20);
            __m256i out1 = _mm256_permute2x128_si256(uv_lo, uv_hi, 0x31);

            _mm256_storeu_si256((__m256i*)(duv + 2 * x), out0);
            _mm256_storeu_si256((__m256i*)(duv + 2 * x + 16), out1);
        }
        for (; x < uv_width; x++) {
            duv[2 * x + 0] = (uint16_t)(su[x] << 6);
            duv[2 * x + 1] = (uint16_t)(sv[x] << 6);
        }
    }
}

static void yuv420p10le_to_p010_native(
    const uint16_t* src_y, int src_y_stride,
    const uint16_t* src_u, int src_u_stride,
    const uint16_t* src_v, int src_v_stride,
    uint16_t* dst_p010, int dst_stride_elems,
    int width, int height
) {
    yuv420p10le_to_p010_pitch(
        src_y, src_y_stride,
        src_u, src_u_stride,
        src_v, src_v_stride,
        (uint8_t*)dst_p010, dst_stride_elems * 2,
        width, height
    );
}

// Codec Identifiers
typedef enum {
    INTEL_CODEC_AV1 = 0,
    INTEL_CODEC_H264 = 1,
    INTEL_CODEC_HEVC = 2
} IntelCodecId;

typedef struct {
    int av1_available;
    int av1_10bit;
    int h264_available;
    int h264_8bit;
    int h264_10bit;
    int hevc_available;
    int hevc_10bit;
} IntelCapabilityInfo;

// Function pointers for oneVPL
typedef mfxLoader (*mfxCreateLoader_fn)(void);
typedef mfxConfig (*mfxCreateConfig_fn)(mfxLoader);
typedef mfxStatus (*mfxSetConfigFilterProperty_fn)(mfxConfig, const mfxU8*, mfxVariant);
typedef mfxStatus (*mfxCreateSession_fn)(mfxLoader, mfxU32, mfxSession*);
typedef void (*mfxUnload_fn)(mfxLoader);
typedef mfxStatus (*mfxClose_fn)(mfxSession);
typedef mfxStatus (*mfxVideoCORE_SetHandle_fn)(mfxSession, mfxHandleType, mfxHDL);
typedef mfxStatus (*mfxVideoENCODE_Init_fn)(mfxSession, mfxVideoParam*);
typedef mfxStatus (*mfxVideoENCODE_Close_fn)(mfxSession);
typedef mfxStatus (*mfxMemory_GetSurfaceForEncode_fn)(mfxSession, mfxFrameSurface1**);
typedef mfxStatus (*mfxVideoENCODE_EncodeFrameAsync_fn)(mfxSession, mfxEncodeCtrl*, mfxFrameSurface1*, mfxBitstream*, mfxSyncPoint*);
typedef mfxStatus (*mfxVideoCORE_SyncOperation_fn)(mfxSession, mfxSyncPoint, mfxU32);

typedef struct {
    double total_demux_ms;
    double total_decode_ms;
    double total_p010_ms;
    double total_upload_base_ms;
    double total_upload_hud_ms;
    double total_blt_ms;
    double total_dma_copy_ms;
    double total_submit_ms;
    double total_sync_ms;
    double total_encode_ms;
    double total_queue_wait_ms;
    double total_wall_ms;
    int decoded_frames;
    int submitted_frames;
    int encoded_frames;
    int max_pending_frames;
    int device_busy_retries;
    int surface_starvations;
    uint64_t total_bytes_encoded;
    double avg_bitrate_mbps;
    double pipeline_fps;
    // 7G Queue & Pending Histograms
    int queue_depth_counts[5]; // depth 0, 1, 2, 3, 4
    int queue_samples;
    int enc_pending_counts[17]; // pending 0..16
    int enc_pending_samples;
    // 7I CPU Active-Time & Micro-Stage Instrumentation
    uint64_t total_p010_cycles;
    uint64_t total_decode_cycles;
    uint64_t total_producer_cycles;
    uint64_t total_consumer_cycles;
    double total_p010_map_ms;
    double total_p010_pure_convert_ms;
    double total_p010_unmap_ms;
    // 7J Map Wait Histogram & Percentiles
    int map_hist_counts[7]; // <1, 1-3, 3-5, 5-10, 10-20, 20-40, >40
    int map_samples;
    double map_p50_ms;
    double map_p90_ms;
    double map_p95_ms;
    double map_p99_ms;
    // 7K Dual-D3D11 Cross-Device Metrics
    double total_cross_copy_ms;
    double total_cross_wait_producer_ms;
    double total_cross_wait_consumer_ms;
    // 1A HEVC D3D11VA & Hardware Pipeline Observability
    int hevc_hw_decode_active;
    int d3d11_hevc_main10_active;
    int decode_to_vp_cpu_copy_count;
    int decode_to_vp_gpu_copy_count;
    int vp_to_encoder_cpu_copy_count;
    int vp_to_encoder_gpu_copy_count;
    int hevc_hw_encode_active;
    int device_lost_count;
    int decoder_fallback_count;
    int decoder_surface_count;
    int encoder_surface_count;
    int queue_depth;
    // 1B Region HUD Transfer Observability
    uint64_t hud_full_bytes;
    uint64_t hud_dirty_bytes;
    int hud_dirty_region_count;
    int hud_upload_call_count;
    int hud_upload_full_count;
    int hud_upload_partial_count;
    int hud_upload_skipped_count;
    double hud_upload_api_ms;
    double hud_dirty_area_percent;
    // 1B.F3 D3D11 Immediate Context Multithread Observability
    int d3d11_mt_protection_active;
    int d3d11_mt_qi_hresult;
    int d3d11_context_thread_count;
    int d3d11_device_removed_reason;
    int producer_thread_id;
    int consumer_thread_id;
    int producer_consumer_overlap_observed;
    // 1D.1 Staged Ring HUD Transfer
    double total_hud_staged_map_ms;
    double total_hud_staged_copy_ms;
    // 1D.1 Direct VP Surface Diagnostics
    int direct_vp_first_fail_hr; // HRESULT of first CreateVideoProcessorOutputView failure (0=never failed)
    // 1E Encoder Scheduling & Status Observability
    int mfx_device_busy_count;
    int mfx_more_surface_count;
    int mfx_more_data_count;
    int mfx_err_other_count;
    int encoder_surface_starvations;
    int mfx_async_depth_param;
    int app_drain_watermark_param;
    int late_drain_active;
    double sync_p50_ms;
    double sync_p90_ms;
    double sync_p95_ms;
    double sync_p99_ms;
    // 2A D3D11 Contention & Decoder Contract Observability
    double hud_upload_p50_ms;
    double hud_upload_p90_ms;
    double hud_upload_p95_ms;
    double hud_upload_p99_ms;
    double hud_upload_with_overlap_ms;
    double hud_upload_without_overlap_ms;
    int hud_upload_overlap_count;
    int hud_upload_non_overlap_count;
    int decoder_texture_width;
    int decoder_texture_height;
    int decoder_texture_format;
    int decoder_texture_bind_flags;
    int decoder_texture_misc_flags;
    int decoder_texture_array_size;
    int decoder_surface_shareable;
    int decoder_shared_handle_supported;
    int decoder_shared_handle_hr;
    int pad_2a;
    double total_producer_d3d11_window_ms;
    double total_consumer_d3d11_window_ms;
} IntelNativePipelineStats;

typedef struct {
    int32_t left;
    int32_t top;
    int32_t right;
    int32_t bottom;
} IntelHudBox;

typedef struct {
    ID3D11Texture2D* pStagingTex;
    uint16_t* p010_data;
    AVFrame* pAvFrame;
    int64_t pts;
    double pts_sec;
    int frame_idx;
    bool is_eof;
    bool is_ready;
    // 7K Dual-D3D11 Cross-Device Shared P010 Ring
    ID3D11Texture2D* pSharedBaseTexA;
    IDXGIKeyedMutex* pKeyedMutexA;
    HANDLE hSharedHandle;
    ID3D11Texture2D* pOpenedBaseTexB;
    ID3D11VideoProcessorInputView* pBaseInputViewB;
    IDXGIKeyedMutex* pKeyedMutexB;
} DecodeSlot;

typedef struct {
    mfxSyncPoint syncp;
    mfxBitstream bs;
    uint8_t* pBsBuffer;
    int frame_idx;
    bool in_use;
} EncodeSlot;

#define MAX_CACHED_SURFACE_VIEWS 32
typedef struct {
    ID3D11Texture2D* pTex;
    ID3D11VideoProcessorOutputView* pVPOutView;
} CachedVPOutView;

typedef struct {
    // D3D11 Resources (Device B: Video Processor / oneVPL Compositor)
    ID3D11Device* pDevice;
    ID3D11DeviceContext* pContext;
    ID3D11VideoDevice* pVideoDevice;
    ID3D11VideoContext* pVideoContext;
    ID3D11VideoProcessorEnumerator* pEnum;
    ID3D11VideoProcessor* pVP;

    // 7K Dual Device (Device A: CPU Decode / P010 Staging / Upload Device)
    ID3D11Device* pUploadDevice;
    ID3D11DeviceContext* pUploadContext;
    bool use_dual_device;
    int shared_ring_slots;

    ID3D11Texture2D* pBaseTex;
    ID3D11VideoProcessorInputView* pBaseInputView;

    ID3D11Texture2D* pHudTex;
    ID3D11VideoProcessorInputView* pHudInputView;

    // 1D.1 Staged HUD Upload Ring (TELEM_INTEL_HUD_STAGED_RING=1)
    // Two STAGING textures rotate: Map+memcpy+Unmap -> CopyResource to pHudTex
    // Legacy DEFAULT UpdateSubresource path active when hud_staged_ring_enabled=false
    ID3D11Texture2D* pHudStagingRing[2];
    bool hud_staged_ring_enabled;
    int  hud_staged_ring_idx; // 0 or 1, rotates each frame

    ID3D11Texture2D* pVPOutTex;
    ID3D11VideoProcessorOutputView* pVPOutView;

    // 8C Direct D3D11 Video Processor to oneVPL Surface Cache
    CachedVPOutView cached_out_views[MAX_CACHED_SURFACE_VIEWS];
    int num_cached_out_views;
    bool use_direct_vp_surface;

    // Legacy staging for 7C compatibility
    ID3D11Texture2D* pStagingTex;

    // FFmpeg Multi-Clip Decoder Resources
    char clip_paths[MAX_MULTI_CLIPS][MAX_PATH];
    int num_clips;
    int current_clip_idx;
    int64_t clip_pts_offset;
    double clip_time_offset_sec;

    AVFormatContext* fmt_ctx;
    AVCodecContext* dec_ctx;
    int video_stream_idx;
    AVRational time_base;
    AVRational avg_fps;
    AVPacket* pkt;
    AVFrame* frame;
    AVBufferRef* hw_device_ctx;
    bool hw_decode_active;
    CachedDecodeInputView cached_decode_views[MAX_CACHED_DECODE_VIEWS];
    int num_cached_decode_views;
    ID3D11VideoProcessorInputView* current_dec_input_view;

    // Threading & Decode Ring Buffer
    HANDLE hDecodeThread;
    CRITICAL_SECTION csDecode;
    CONDITION_VARIABLE cvDecodeFree;
    CONDITION_VARIABLE cvDecodeReady;
    bool bStopDecode;
    DecodeSlot decode_ring[DECODE_RING_SIZE];
    int decode_head_idx;
    int decode_tail_idx;
    int decode_queued_count;

    // oneVPL Encoder Resources
    HMODULE hVpl;
    mfxLoader loader;
    mfxSession session;
    mfxCreateLoader_fn pMFXLoad;
    mfxCreateConfig_fn pMFXCreateConfig;
    mfxSetConfigFilterProperty_fn pMFXSetConfigFilterProperty;
    mfxCreateSession_fn pMFXCreateSession;
    mfxUnload_fn pMFXUnload;
    mfxClose_fn pMFXClose;
    mfxVideoCORE_SetHandle_fn pMFXVideoCORE_SetHandle;
    mfxVideoENCODE_Init_fn pMFXVideoENCODE_Init;
    mfxMemory_GetSurfaceForEncode_fn pMFXMemory_GetSurfaceForEncode;
    mfxVideoENCODE_EncodeFrameAsync_fn pMFXVideoENCODE_EncodeFrameAsync;
    mfxVideoCORE_SyncOperation_fn pMFXVideoCORE_SyncOperation;

    int async_depth;
    int pool_size;
    EncodeSlot encode_pool[ENCODE_POOL_SIZE];
    int enc_head_idx;
    int enc_tail_idx;
    int pending_encode_count;

    FILE* fOutIVF;

    // Pipeline Timers & Counters
    LARGE_INTEGER freq;
    LARGE_INTEGER t_pipe_start;
    LARGE_INTEGER t_pipe_end;
    IntelNativePipelineStats stats;
    double map_samples_buffer[4096];
    double sync_samples_buffer[4096];
    int num_sync_samples;
    int app_drain_watermark;
    bool late_drain_enabled;

    // 2A Call Window & Contention Tracking
    double hud_samples_buffer[4096];
    int num_hud_samples;
    double hud_overlap_sum;
    int hud_overlap_count;
    double hud_non_overlap_sum;
    int hud_non_overlap_count;
    bool decoder_contract_inspected;
    double total_producer_d3d11_ms;
    bool contention_instrumentation_enabled;

    bool initialized;
    bool pipeline_open;
    bool cancelled;
    bool use_staging_ring;
    int topology_mode; // 0 = Topology A (legacy), 1 = Topology C (Pack in Consumer)
    int codec_id; // INTEL_CODEC_AV1 = 0, INTEL_CODEC_H264 = 1, INTEL_CODEC_HEVC = 2
    volatile LONG producer_in_d3d11;
    volatile LONG consumer_in_d3d11;
    bool logged_thread_ids;
} IntelNativeContext;

static IntelNativeContext g_pipe = {0};

// Background Decode Producer Thread (Multi-clip seamless sequence)
static DWORD WINAPI decode_producer_thread_func(LPVOID lpParam) {
    IntelNativeContext* ctx = (IntelNativeContext*)lpParam;
    LARGE_INTEGER freq = ctx->freq;
    LARGE_INTEGER t0, t1;
    HANDLE hProducerThread = GetCurrentThread();
    ctx->stats.producer_thread_id = (int)GetCurrentThreadId();
    ULONG64 prod_start_cycles = 0, prod_end_cycles = 0;
    QueryThreadCycleTime(hProducerThread, &prod_start_cycles);

    int current_frame_idx = 0;

    for (int clip_i = 0; clip_i < ctx->num_clips && !ctx->bStopDecode; clip_i++) {
        ctx->current_clip_idx = clip_i;
        if (clip_i > 0) {
            printf("[STREAM INTEL MULTI] CLIP_CLOSE_BEGIN (clip %d: %s)\n", clip_i - 1, ctx->clip_paths[clip_i - 1]);
            fflush(stdout);

            // Drain decode ring to ensure all AVFrames of previous clip are released by consumer
            EnterCriticalSection(&ctx->csDecode);
            while (!ctx->bStopDecode && ctx->decode_queued_count > 0) {
                SleepConditionVariableCS(&ctx->cvDecodeFree, &ctx->csDecode, 50);
            }
            LeaveCriticalSection(&ctx->csDecode);

            // Release all cached decode input views so COM refcount on previous texture array becomes 0
            for (int i = 0; i < ctx->num_cached_decode_views; i++) {
                if (ctx->cached_decode_views[i].pInputView) {
                    ID3D11VideoProcessorInputView_Release(ctx->cached_decode_views[i].pInputView);
                    ctx->cached_decode_views[i].pInputView = NULL;
                }
                ctx->cached_decode_views[i].pTex = NULL;
            }
            ctx->num_cached_decode_views = 0;
            ctx->current_dec_input_view = NULL;

            if (ctx->dec_ctx) {
                avcodec_send_packet(ctx->dec_ctx, NULL);
                while (avcodec_receive_frame(ctx->dec_ctx, ctx->frame) == 0) {
                    av_frame_unref(ctx->frame);
                }
                avcodec_free_context(&ctx->dec_ctx);
                ctx->dec_ctx = NULL;
            }
            if (ctx->fmt_ctx) {
                avformat_close_input(&ctx->fmt_ctx);
                ctx->fmt_ctx = NULL;
            }
            if (ctx->pContext) {
                ID3D11DeviceContext_Flush(ctx->pContext);
            }
            printf("[STREAM INTEL MULTI] CLIP_CLOSE_DONE (clip %d)\n", clip_i - 1);
            fflush(stdout);

            printf("[STREAM INTEL MULTI] CLIP_OPEN_BEGIN (clip %d: %s)\n", clip_i, ctx->clip_paths[clip_i]);
            fflush(stdout);

            if (avformat_open_input(&ctx->fmt_ctx, ctx->clip_paths[clip_i], NULL, NULL) < 0) {
                printf("[STREAM INTEL MULTI] ERROR: Failed to open clip %s\n", ctx->clip_paths[clip_i]);
                fflush(stdout);
                break;
            }
            avformat_find_stream_info(ctx->fmt_ctx, NULL);
            ctx->video_stream_idx = -1;
            for (unsigned int i = 0; i < ctx->fmt_ctx->nb_streams; i++) {
                if (ctx->fmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
                    ctx->video_stream_idx = i;
                    break;
                }
            }
            if (ctx->video_stream_idx < 0) break;

            AVStream* st = ctx->fmt_ctx->streams[ctx->video_stream_idx];
            ctx->time_base = st->time_base;
            const AVCodec* dec = avcodec_find_decoder(st->codecpar->codec_id);
            ctx->dec_ctx = avcodec_alloc_context3(dec);
            avcodec_parameters_to_context(ctx->dec_ctx, st->codecpar);
            if (ctx->hw_decode_active && ctx->hw_device_ctx) {
                ctx->dec_ctx->hw_device_ctx = av_buffer_ref(ctx->hw_device_ctx);
                ctx->dec_ctx->get_format = get_hw_format;
                ctx->dec_ctx->extra_hw_frames = 8;
            } else {
                const char* env_th = getenv("TELEM_INTEL_DECODER_THREADS");
                ctx->dec_ctx->thread_count = (env_th && atoi(env_th) > 0) ? atoi(env_th) : 0;
            }
            if (avcodec_open2(ctx->dec_ctx, dec, NULL) < 0) break;

            printf("[STREAM INTEL MULTI] CLIP_OPEN_DONE (clip %d)\n", clip_i);
            printf("[STREAM INTEL MULTI] DECODER_READY\n");
            fflush(stdout);
        }

        int64_t clip_first_pts = AV_NOPTS_VALUE;
        int64_t clip_last_pts = 0;
        bool first_frame_in_this_clip = true;
        bool clip_eof = false;

        while (!ctx->bStopDecode && !clip_eof) {
            // Wait for free decode ring slot
            EnterCriticalSection(&ctx->csDecode);
            int ring_limit = (ctx->use_dual_device && ctx->shared_ring_slots > 0) ? ctx->shared_ring_slots : DECODE_RING_SIZE;
            while (!ctx->bStopDecode && ctx->decode_queued_count >= ring_limit) {
                SleepConditionVariableCS(&ctx->cvDecodeFree, &ctx->csDecode, 500);
            }
            if (ctx->bStopDecode) {
                LeaveCriticalSection(&ctx->csDecode);
                break;
            }
            int write_slot = ctx->decode_head_idx;
            LeaveCriticalSection(&ctx->csDecode);

            // Demux & Decode next frame from current clip
            bool got_frame = false;
            while (!got_frame && !ctx->bStopDecode) {
                ULONG64 dcyc0 = 0, dcyc1 = 0;
                QueryThreadCycleTime(hProducerThread, &dcyc0);
                QueryPerformanceCounter(&t0);
                LARGE_INTEGER d3d_p0, d3d_p1;
                if (ctx->hw_decode_active && ctx->contention_instrumentation_enabled) {
                    QueryPerformanceCounter(&d3d_p0);
                    InterlockedExchange(&ctx->producer_in_d3d11, 1);
                    if (ctx->consumer_in_d3d11) {
                        ctx->stats.producer_consumer_overlap_observed = 1;
                    }
                }
                int ret = avcodec_receive_frame(ctx->dec_ctx, ctx->frame);
                if (ctx->hw_decode_active && ctx->contention_instrumentation_enabled) {
                    InterlockedExchange(&ctx->producer_in_d3d11, 0);
                    QueryPerformanceCounter(&d3d_p1);
                    ctx->total_producer_d3d11_ms += get_time_ms(d3d_p0, d3d_p1, freq);
                }
                QueryPerformanceCounter(&t1);
                QueryThreadCycleTime(hProducerThread, &dcyc1);
                ctx->stats.total_decode_ms += get_time_ms(t0, t1, freq);
                ctx->stats.total_decode_cycles += (dcyc1 - dcyc0);

                if (ret == 0) {
                    got_frame = true;
                    break;
                } else if (ret == AVERROR(EAGAIN)) {
                    QueryPerformanceCounter(&t0);
                    int read_ret = av_read_frame(ctx->fmt_ctx, ctx->pkt);
                    QueryPerformanceCounter(&t1);
                    ctx->stats.total_demux_ms += get_time_ms(t0, t1, freq);

                    if (read_ret < 0) {
                        if (ctx->hw_decode_active && ctx->contention_instrumentation_enabled) {
                            QueryPerformanceCounter(&d3d_p0);
                            InterlockedExchange(&ctx->producer_in_d3d11, 1);
                            if (ctx->consumer_in_d3d11) {
                                ctx->stats.producer_consumer_overlap_observed = 1;
                            }
                        }
                        avcodec_send_packet(ctx->dec_ctx, NULL);
                        if (ctx->hw_decode_active && ctx->contention_instrumentation_enabled) {
                            InterlockedExchange(&ctx->producer_in_d3d11, 0);
                            QueryPerformanceCounter(&d3d_p1);
                            ctx->total_producer_d3d11_ms += get_time_ms(d3d_p0, d3d_p1, freq);
                        }
                        continue;
                    }
                    if (ctx->pkt->stream_index == ctx->video_stream_idx) {
                        QueryPerformanceCounter(&t0);
                        if (ctx->hw_decode_active && ctx->contention_instrumentation_enabled) {
                            QueryPerformanceCounter(&d3d_p0);
                            InterlockedExchange(&ctx->producer_in_d3d11, 1);
                            if (ctx->consumer_in_d3d11) {
                                ctx->stats.producer_consumer_overlap_observed = 1;
                            }
                        }
                        avcodec_send_packet(ctx->dec_ctx, ctx->pkt);
                        if (ctx->hw_decode_active && ctx->contention_instrumentation_enabled) {
                            InterlockedExchange(&ctx->producer_in_d3d11, 0);
                            QueryPerformanceCounter(&d3d_p1);
                            ctx->total_producer_d3d11_ms += get_time_ms(d3d_p0, d3d_p1, freq);
                        }
                        QueryPerformanceCounter(&t1);
                        ctx->stats.total_decode_ms += get_time_ms(t0, t1, freq);
                    }
                    av_packet_unref(ctx->pkt);
                } else if (ret == AVERROR_EOF) {
                    clip_eof = true;
                    break;
                } else {
                    clip_eof = true;
                    break;
                }
            }

            if (ctx->bStopDecode) break;

            if (got_frame) {
                if (clip_first_pts == AV_NOPTS_VALUE) {
                    clip_first_pts = ctx->frame->pts;
                }
                int64_t local_pts = ctx->frame->pts - clip_first_pts;
                int64_t global_pts = ctx->clip_pts_offset + local_pts;
                double global_pts_sec = ctx->clip_time_offset_sec + (double)local_pts * av_q2d(ctx->time_base);

                if (first_frame_in_this_clip && clip_i > 0) {
                    printf("[STREAM INTEL MULTI] FIRST_FRAME_NEXT_CLIP (frame_idx=%d, global_pts=%lld, global_time=%.6f)\n",
                           current_frame_idx, (long long)global_pts, global_pts_sec);
                    fflush(stdout);
                    first_frame_in_this_clip = false;
                }
                clip_last_pts = local_pts;

                if (ctx->hw_decode_active && ctx->frame->format == AV_PIX_FMT_D3D11) {
                    // ZERO-COPY D3D11VA HW DECODE:
                    // Hand off decoded GPU frame directly to decode_ring with 0 CPU copies
                    av_frame_move_ref(ctx->decode_ring[write_slot].pAvFrame, ctx->frame);
                } else if (ctx->topology_mode == 1) {
                    // TOPOLOGY C: Pure CPU decode in producer thread, hand off AVFrame to consumer
                    av_frame_move_ref(ctx->decode_ring[write_slot].pAvFrame, ctx->frame);
                } else if (ctx->use_dual_device && ctx->pUploadContext && ctx->decode_ring[write_slot].pKeyedMutexA) {
                    // 7K DUAL-DEVICE UPLOAD: Map/Pack on Device A, CopyResource to Shared Texture, KeyedMutex Handoff
                    LARGE_INTEGER kw0, kw1, m0, m1, c0, c1, u0, u1, cp0, cp1;
                    ULONG64 cyc0 = 0, cyc1 = 0;
                    QueryThreadCycleTime(hProducerThread, &cyc0);
                    QueryPerformanceCounter(&t0);

                    // Acquire KeyedMutex for write (Key 0 = Producer Write)
                    QueryPerformanceCounter(&kw0);
                    HRESULT hr_acq = IDXGIKeyedMutex_AcquireSync(ctx->decode_ring[write_slot].pKeyedMutexA, 0, 2000);
                    QueryPerformanceCounter(&kw1);
                    ctx->stats.total_cross_wait_producer_ms += get_time_ms(kw0, kw1, freq);

                    // Map staging texture on Device A context (contention-free!)
                    D3D11_MAPPED_SUBRESOURCE map;
                    QueryPerformanceCounter(&m0);
                    HRESULT hr = ID3D11DeviceContext_Map(ctx->pUploadContext, (ID3D11Resource*)ctx->decode_ring[write_slot].pStagingTex, 0, D3D11_MAP_WRITE, 0, &map);
                    QueryPerformanceCounter(&m1);
                    double m_ms = get_time_ms(m0, m1, freq);
                    ctx->stats.total_p010_map_ms += m_ms;
                    if (ctx->stats.map_samples < 4096) {
                        ctx->map_samples_buffer[ctx->stats.map_samples] = m_ms;
                    }
                    ctx->stats.map_samples++;
                    if (m_ms < 1.0) ctx->stats.map_hist_counts[0]++;
                    else if (m_ms < 3.0) ctx->stats.map_hist_counts[1]++;
                    else if (m_ms < 5.0) ctx->stats.map_hist_counts[2]++;
                    else if (m_ms < 10.0) ctx->stats.map_hist_counts[3]++;
                    else if (m_ms < 20.0) ctx->stats.map_hist_counts[4]++;
                    else if (m_ms < 40.0) ctx->stats.map_hist_counts[5]++;
                    else ctx->stats.map_hist_counts[6]++;

                    if (SUCCEEDED(hr) && map.pData) {
                        QueryPerformanceCounter(&c0);
                        yuv420p10le_to_p010_pitch(
                            (const uint16_t*)ctx->frame->data[0], ctx->frame->linesize[0],
                            (const uint16_t*)ctx->frame->data[1], ctx->frame->linesize[1],
                            (const uint16_t*)ctx->frame->data[2], ctx->frame->linesize[2],
                            (uint8_t*)map.pData, map.RowPitch,
                            BASE_W, BASE_H
                        );
                        QueryPerformanceCounter(&c1);
                        ctx->stats.total_p010_pure_convert_ms += get_time_ms(c0, c1, freq);

                        QueryPerformanceCounter(&u0);
                        ID3D11DeviceContext_Unmap(ctx->pUploadContext, (ID3D11Resource*)ctx->decode_ring[write_slot].pStagingTex, 0);
                        QueryPerformanceCounter(&u1);
                        ctx->stats.total_p010_unmap_ms += get_time_ms(u0, u1, freq);

                        // GPU copy staging -> shared texture on Device A
                        QueryPerformanceCounter(&cp0);
                        ID3D11DeviceContext_CopyResource(ctx->pUploadContext, (ID3D11Resource*)ctx->decode_ring[write_slot].pSharedBaseTexA, (ID3D11Resource*)ctx->decode_ring[write_slot].pStagingTex);
                        QueryPerformanceCounter(&cp1);
                        ctx->stats.total_cross_copy_ms += get_time_ms(cp0, cp1, freq);
                    }

                    // Release KeyedMutex to Key 1 (Consumer Read)
                    IDXGIKeyedMutex_ReleaseSync(ctx->decode_ring[write_slot].pKeyedMutexA, 1);

                    QueryPerformanceCounter(&t1);
                    QueryThreadCycleTime(hProducerThread, &cyc1);
                    ctx->stats.total_p010_ms += get_time_ms(t0, t1, freq);
                    ctx->stats.total_p010_cycles += (cyc1 - cyc0);
                    av_frame_unref(ctx->frame);
                } else {
                    // TOPOLOGY A: Pack in producer thread (single device)
                    LARGE_INTEGER m0, m1, c0, c1, u0, u1;
                    ULONG64 cyc0 = 0, cyc1 = 0;
                    QueryThreadCycleTime(hProducerThread, &cyc0);
                    QueryPerformanceCounter(&t0);
                    if (ctx->use_staging_ring && ctx->decode_ring[write_slot].pStagingTex) {
                        D3D11_MAPPED_SUBRESOURCE map;
                        QueryPerformanceCounter(&m0);
                        HRESULT hr = ID3D11DeviceContext_Map(ctx->pContext, (ID3D11Resource*)ctx->decode_ring[write_slot].pStagingTex, 0, D3D11_MAP_WRITE, 0, &map);
                        QueryPerformanceCounter(&m1);
                        double m_ms = get_time_ms(m0, m1, freq);
                        ctx->stats.total_p010_map_ms += m_ms;
                        if (ctx->stats.map_samples < 4096) {
                            ctx->map_samples_buffer[ctx->stats.map_samples] = m_ms;
                        }
                        ctx->stats.map_samples++;
                        if (m_ms < 1.0) ctx->stats.map_hist_counts[0]++;
                        else if (m_ms < 3.0) ctx->stats.map_hist_counts[1]++;
                        else if (m_ms < 5.0) ctx->stats.map_hist_counts[2]++;
                        else if (m_ms < 10.0) ctx->stats.map_hist_counts[3]++;
                        else if (m_ms < 20.0) ctx->stats.map_hist_counts[4]++;
                        else if (m_ms < 40.0) ctx->stats.map_hist_counts[5]++;
                        else ctx->stats.map_hist_counts[6]++;

                        if (SUCCEEDED(hr) && map.pData) {
                            QueryPerformanceCounter(&c0);
                            yuv420p10le_to_p010_pitch(
                                (const uint16_t*)ctx->frame->data[0], ctx->frame->linesize[0],
                                (const uint16_t*)ctx->frame->data[1], ctx->frame->linesize[1],
                                (const uint16_t*)ctx->frame->data[2], ctx->frame->linesize[2],
                                (uint8_t*)map.pData, map.RowPitch,
                                BASE_W, BASE_H
                            );
                            QueryPerformanceCounter(&c1);
                            ctx->stats.total_p010_pure_convert_ms += get_time_ms(c0, c1, freq);

                            QueryPerformanceCounter(&u0);
                            ID3D11DeviceContext_Unmap(ctx->pContext, (ID3D11Resource*)ctx->decode_ring[write_slot].pStagingTex, 0);
                            QueryPerformanceCounter(&u1);
                            ctx->stats.total_p010_unmap_ms += get_time_ms(u0, u1, freq);
                        }
                    } else if (ctx->decode_ring[write_slot].p010_data) {
                        QueryPerformanceCounter(&c0);
                        yuv420p10le_to_p010_native(
                            (const uint16_t*)ctx->frame->data[0], ctx->frame->linesize[0],
                            (const uint16_t*)ctx->frame->data[1], ctx->frame->linesize[1],
                            (const uint16_t*)ctx->frame->data[2], ctx->frame->linesize[2],
                            ctx->decode_ring[write_slot].p010_data, BASE_W,
                            BASE_W, BASE_H
                        );
                        QueryPerformanceCounter(&c1);
                        ctx->stats.total_p010_pure_convert_ms += get_time_ms(c0, c1, freq);
                    }
                    QueryPerformanceCounter(&t1);
                    QueryThreadCycleTime(hProducerThread, &cyc1);
                    ctx->stats.total_p010_ms += get_time_ms(t0, t1, freq);
                    ctx->stats.total_p010_cycles += (cyc1 - cyc0);
                    av_frame_unref(ctx->frame);
                }

                ctx->decode_ring[write_slot].pts = global_pts;
                ctx->decode_ring[write_slot].pts_sec = global_pts_sec;
                ctx->decode_ring[write_slot].frame_idx = current_frame_idx++;
                ctx->decode_ring[write_slot].is_eof = false;
                ctx->decode_ring[write_slot].is_ready = true;

                EnterCriticalSection(&ctx->csDecode);
                ctx->decode_head_idx = (ctx->decode_head_idx + 1) % ring_limit;
                ctx->decode_queued_count++;
                WakeConditionVariable(&ctx->cvDecodeReady);
                LeaveCriticalSection(&ctx->csDecode);
            }
        }

        // Advance global clip offset: add clip_last_pts + 1 frame duration (1001 ticks @ 1/30000)
        int64_t frame_tick_delta = (int64_t)ctx->time_base.den * 1001 / (ctx->time_base.num * 30000);
        if (frame_tick_delta <= 0) frame_tick_delta = 1001;
        ctx->clip_pts_offset += clip_last_pts + frame_tick_delta;
        ctx->clip_time_offset_sec += (double)(clip_last_pts + frame_tick_delta) * av_q2d(ctx->time_base);
    }

    // Push EOF slot when all clips have finished
    int ring_limit = (ctx->use_dual_device && ctx->shared_ring_slots > 0) ? ctx->shared_ring_slots : DECODE_RING_SIZE;
    EnterCriticalSection(&ctx->csDecode);
    while (!ctx->bStopDecode && ctx->decode_queued_count >= ring_limit) {
        SleepConditionVariableCS(&ctx->cvDecodeFree, &ctx->csDecode, 500);
    }
    if (!ctx->bStopDecode) {
        int write_slot = ctx->decode_head_idx;
        ctx->decode_ring[write_slot].is_eof = true;
        ctx->decode_ring[write_slot].is_ready = true;
        ctx->decode_ring[write_slot].frame_idx = current_frame_idx;
        ctx->decode_head_idx = (ctx->decode_head_idx + 1) % ring_limit;
        ctx->decode_queued_count++;
        WakeConditionVariable(&ctx->cvDecodeReady);
    }
    LeaveCriticalSection(&ctx->csDecode);

    QueryThreadCycleTime(hProducerThread, &prod_end_cycles);
    ctx->stats.total_producer_cycles = prod_end_cycles - prod_start_cycles;

    return 0;
}

// 7C/8A D3D11 Init with Codec Selection
__declspec(dllexport) int intel_d3d11_vp_init_ex(int codec_id) {
    if (g_pipe.initialized) return 0;
    memset(&g_pipe, 0, sizeof(g_pipe));
    g_pipe.codec_id = codec_id;
    QueryPerformanceFrequency(&g_pipe.freq);

    IDXGIFactory1* pFactory = NULL;
    HRESULT hr = CreateDXGIFactory1(&IID_IDXGIFactory1, (void**)&pFactory);
    if (FAILED(hr)) return -1;

    IDXGIAdapter1* pIntelAdapter = NULL;
    for (UINT i = 0; ; ++i) {
        IDXGIAdapter1* pAdapter = NULL;
        if (IDXGIFactory1_EnumAdapters1(pFactory, i, &pAdapter) == DXGI_ERROR_NOT_FOUND) break;
        DXGI_ADAPTER_DESC1 desc;
        IDXGIAdapter1_GetDesc1(pAdapter, &desc);
        if (desc.VendorId == 0x8086 && !pIntelAdapter) {
            pIntelAdapter = pAdapter;
        } else {
            IDXGIAdapter1_Release(pAdapter);
        }
    }
    IDXGIFactory1_Release(pFactory);
    if (!pIntelAdapter) return -2;

    D3D_FEATURE_LEVEL featureLevels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
    D3D_FEATURE_LEVEL chosenLevel;

    hr = D3D11CreateDevice(
        (IDXGIAdapter*)pIntelAdapter,
        D3D_DRIVER_TYPE_UNKNOWN,
        NULL,
        D3D11_CREATE_DEVICE_VIDEO_SUPPORT,
        featureLevels,
        2,
        D3D11_SDK_VERSION,
        &g_pipe.pDevice,
        &chosenLevel,
        &g_pipe.pContext
    );
    if (FAILED(hr)) {
        IDXGIAdapter1_Release(pIntelAdapter);
        return -3;
    }

    const char* env_dual = getenv("TELEM_INTEL_DUAL_DEVICE");
    g_pipe.use_dual_device = (env_dual && strcmp(env_dual, "1") == 0) ? true : false;

    if (g_pipe.use_dual_device) {
        LARGE_INTEGER t_dev_start, t_dev_end;
        QueryPerformanceCounter(&t_dev_start);
        hr = D3D11CreateDevice(
            (IDXGIAdapter*)pIntelAdapter,
            D3D_DRIVER_TYPE_UNKNOWN,
            NULL,
            0,
            featureLevels,
            2,
            D3D11_SDK_VERSION,
            &g_pipe.pUploadDevice,
            &chosenLevel,
            &g_pipe.pUploadContext
        );
        QueryPerformanceCounter(&t_dev_end);
        double dev_ms = get_time_ms(t_dev_start, t_dev_end, g_pipe.freq);
        if (FAILED(hr)) {
            printf("[STREAM INTEL] WARNING: Failed to create Dual D3D11 Upload Device A (hr=0x%08lX). Falling back to single device.\n", (unsigned long)hr);
            g_pipe.use_dual_device = false;
        } else {
            printf("[STREAM INTEL] DUAL_D3D11_DEVICE_READY: Device A created in %.2f ms (Upload/Producer context: %p)\n", dev_ms, g_pipe.pUploadContext);
        }
    }

    IDXGIAdapter1_Release(pIntelAdapter);

    static const GUID IID_ID3D11Multithread_local = {
        0x9b7e4e00, 0x342c, 0x4106, { 0xa1, 0x9f, 0x4f, 0x27, 0x04, 0xf6, 0x89, 0xf0 }
    };

    ID3D11Multithread* pMultithread = NULL;
    hr = ID3D11DeviceContext_QueryInterface(g_pipe.pContext, &IID_ID3D11Multithread_local, (void**)&pMultithread);
    g_pipe.stats.d3d11_mt_qi_hresult = (int)hr;
    int mt_before = 0;
    int mt_after = 0;
    if (SUCCEEDED(hr) && pMultithread) {
        mt_before = ID3D11Multithread_GetMultithreadProtected(pMultithread) ? 1 : 0;
        ID3D11Multithread_SetMultithreadProtected(pMultithread, TRUE);
        mt_after = ID3D11Multithread_GetMultithreadProtected(pMultithread) ? 1 : 0;
        ID3D11Multithread_Release(pMultithread);
    }
    g_pipe.stats.d3d11_mt_protection_active = mt_after;
    printf("[STREAM INTEL D3D11] ID3D11Multithread QI=0x%08lX (status=%s), Protected Before=%d, Protected After=%d\n",
           (unsigned long)hr, SUCCEEDED(hr) ? "PASS" : "FAIL", mt_before, mt_after);

    ID3D11Device_QueryInterface(g_pipe.pDevice, &IID_ID3D11VideoDevice, (void**)&g_pipe.pVideoDevice);
    ID3D11DeviceContext_QueryInterface(g_pipe.pContext, &IID_ID3D11VideoContext, (void**)&g_pipe.pVideoContext);

    D3D11_VIDEO_PROCESSOR_CONTENT_DESC cpDesc = {0};
    cpDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    cpDesc.InputWidth = BASE_W;
    cpDesc.InputHeight = BASE_H;
    cpDesc.OutputWidth = BASE_W;
    cpDesc.OutputHeight = BASE_H;
    cpDesc.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

    ID3D11VideoDevice_CreateVideoProcessorEnumerator(g_pipe.pVideoDevice, &cpDesc, &g_pipe.pEnum);
    ID3D11VideoDevice_CreateVideoProcessor(g_pipe.pVideoDevice, g_pipe.pEnum, 0, &g_pipe.pVP);

    // Textures
    D3D11_TEXTURE2D_DESC texDesc = {0};
    texDesc.Width = BASE_W;
    texDesc.Height = BASE_H;
    texDesc.MipLevels = 1;
    texDesc.ArraySize = 1;
    texDesc.Format = DXGI_FORMAT_P010;
    texDesc.SampleDesc.Count = 1;
    texDesc.Usage = D3D11_USAGE_DEFAULT;
    texDesc.BindFlags = D3D11_BIND_DECODER | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Device_CreateTexture2D(g_pipe.pDevice, &texDesc, NULL, &g_pipe.pBaseTex);

    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC ivDesc = {0};
    ivDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    ID3D11VideoDevice_CreateVideoProcessorInputView(g_pipe.pVideoDevice, (ID3D11Resource*)g_pipe.pBaseTex, g_pipe.pEnum, &ivDesc, &g_pipe.pBaseInputView);

    texDesc.Width = HUD_W;
    texDesc.Height = HUD_H;
    texDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    texDesc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Device_CreateTexture2D(g_pipe.pDevice, &texDesc, NULL, &g_pipe.pHudTex);
    ID3D11VideoDevice_CreateVideoProcessorInputView(g_pipe.pVideoDevice, (ID3D11Resource*)g_pipe.pHudTex, g_pipe.pEnum, &ivDesc, &g_pipe.pHudInputView);

    // VP Output format: DXGI_FORMAT_NV12 for H.264 (8-bit), DXGI_FORMAT_P010 for AV1 (10-bit)
    DXGI_FORMAT out_fmt = (codec_id == INTEL_CODEC_H264) ? DXGI_FORMAT_NV12 : DXGI_FORMAT_P010;
    texDesc.Width = BASE_W;
    texDesc.Height = BASE_H;
    texDesc.Format = out_fmt;
    texDesc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Device_CreateTexture2D(g_pipe.pDevice, &texDesc, NULL, &g_pipe.pVPOutTex);

    D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC ovDesc = {0};
    ovDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
    ID3D11VideoDevice_CreateVideoProcessorOutputView(g_pipe.pVideoDevice, (ID3D11Resource*)g_pipe.pVPOutTex, g_pipe.pEnum, &ovDesc, &g_pipe.pVPOutView);

    // Stream rects
    RECT srcBaseRect = { 0, 0, BASE_W, BASE_H };
    RECT dstBaseRect = { 0, 0, BASE_W, BASE_H };
    ID3D11VideoContext_VideoProcessorSetStreamFrameFormat(g_pipe.pVideoContext, g_pipe.pVP, 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
    ID3D11VideoContext_VideoProcessorSetStreamSourceRect(g_pipe.pVideoContext, g_pipe.pVP, 0, TRUE, &srcBaseRect);
    ID3D11VideoContext_VideoProcessorSetStreamDestRect(g_pipe.pVideoContext, g_pipe.pVP, 0, TRUE, &dstBaseRect);
    ID3D11VideoContext_VideoProcessorSetStreamAlpha(g_pipe.pVideoContext, g_pipe.pVP, 0, TRUE, 1.0f);
    ID3D11VideoContext_VideoProcessorSetStreamAutoProcessingMode(g_pipe.pVideoContext, g_pipe.pVP, 0, FALSE);

    RECT srcHudRect = { 0, 0, HUD_W, HUD_H };
    RECT dstHudRect = { 0, 0, BASE_W, BASE_H };
    ID3D11VideoContext_VideoProcessorSetStreamFrameFormat(g_pipe.pVideoContext, g_pipe.pVP, 1, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
    ID3D11VideoContext_VideoProcessorSetStreamSourceRect(g_pipe.pVideoContext, g_pipe.pVP, 1, TRUE, &srcHudRect);
    ID3D11VideoContext_VideoProcessorSetStreamDestRect(g_pipe.pVideoContext, g_pipe.pVP, 1, TRUE, &dstHudRect);
    ID3D11VideoContext_VideoProcessorSetStreamAlpha(g_pipe.pVideoContext, g_pipe.pVP, 1, TRUE, 1.0f);
    ID3D11VideoContext_VideoProcessorSetStreamAutoProcessingMode(g_pipe.pVideoContext, g_pipe.pVP, 1, FALSE);

    D3D11_VIDEO_COLOR color = {0};
    color.YCbCr.Y = 0.0625f;
    color.YCbCr.Cb = 0.5f;
    color.YCbCr.Cr = 0.5f;
    color.YCbCr.A = 1.0f;
    ID3D11VideoContext_VideoProcessorSetOutputBackgroundColor(g_pipe.pVideoContext, g_pipe.pVP, FALSE, &color);

    // Stream Color Spaces & Tone Mapping (ITU-R BT.2100 HLG BT.2020 -> ITU-R BT.709 SDR)
    static const GUID IID_ID3D11VideoContext1_local = { 0xA7F026DA, 0xA5F8, 0x4AC8, { 0x86, 0xFB, 0xD2, 0x0E, 0xD8, 0xD1, 0x6E, 0x86 } };
    ID3D11VideoContext1* pVideoContext1 = NULL;
    hr = ID3D11DeviceContext_QueryInterface(g_pipe.pContext, &IID_ID3D11VideoContext1_local, (void**)&pVideoContext1);
    if (SUCCEEDED(hr) && pVideoContext1) {
        if (codec_id == INTEL_CODEC_H264) {
            // Stream 0: Base video is HLG BT.2020 P010 (DXGI_COLOR_SPACE_YCBCR_STUDIO_GHLG_TOPLEFT_P2020 = 18)
            ID3D11VideoContext1_VideoProcessorSetStreamColorSpace1(pVideoContext1, g_pipe.pVP, 0, (DXGI_COLOR_SPACE_TYPE)18);
            // Stream 1: HUD is sRGB RGBA (DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709 = 0)
            ID3D11VideoContext1_VideoProcessorSetStreamColorSpace1(pVideoContext1, g_pipe.pVP, 1, (DXGI_COLOR_SPACE_TYPE)0);
            // Output: BT.709 Studio Swing NV12 (DXGI_COLOR_SPACE_YCBCR_STUDIO_G709_LEFT_P709 = 9)
            ID3D11VideoContext1_VideoProcessorSetOutputColorSpace1(pVideoContext1, g_pipe.pVP, (DXGI_COLOR_SPACE_TYPE)9);
        } else {
            // Stream 0: HLG BT.2020 P010
            ID3D11VideoContext1_VideoProcessorSetStreamColorSpace1(pVideoContext1, g_pipe.pVP, 0, (DXGI_COLOR_SPACE_TYPE)18);
            // Stream 1: HUD sRGB RGBA
            ID3D11VideoContext1_VideoProcessorSetStreamColorSpace1(pVideoContext1, g_pipe.pVP, 1, (DXGI_COLOR_SPACE_TYPE)0);
            // Output: HLG BT.2020 P010 (DXGI_COLOR_SPACE_YCBCR_STUDIO_GHLG_TOPLEFT_P2020 = 18)
            ID3D11VideoContext1_VideoProcessorSetOutputColorSpace1(pVideoContext1, g_pipe.pVP, (DXGI_COLOR_SPACE_TYPE)18);
        }
        ID3D11VideoContext1_Release(pVideoContext1);
    }

    g_pipe.initialized = true;

    // 1D.1 Staged HUD Upload Ring â€” allocate if requested
    const char* env_staged_ring = getenv("TELEM_INTEL_HUD_STAGED_RING");
    g_pipe.hud_staged_ring_enabled = (env_staged_ring && strcmp(env_staged_ring, "1") == 0);
    g_pipe.hud_staged_ring_idx = 0;
    g_pipe.pHudStagingRing[0] = NULL;
    g_pipe.pHudStagingRing[1] = NULL;
    if (g_pipe.hud_staged_ring_enabled) {
        D3D11_TEXTURE2D_DESC stDesc = {0};
        stDesc.Width  = HUD_W;
        stDesc.Height = HUD_H;
        stDesc.MipLevels = 1;
        stDesc.ArraySize = 1;
        stDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        stDesc.SampleDesc.Count = 1;
        stDesc.Usage = D3D11_USAGE_STAGING;
        stDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        HRESULT hr_s0 = ID3D11Device_CreateTexture2D(g_pipe.pDevice, &stDesc, NULL, &g_pipe.pHudStagingRing[0]);
        HRESULT hr_s1 = ID3D11Device_CreateTexture2D(g_pipe.pDevice, &stDesc, NULL, &g_pipe.pHudStagingRing[1]);
        if (FAILED(hr_s0) || FAILED(hr_s1)) {
            printf("[STREAM INTEL] STAGED_RING2: STAGING texture creation FAILED hr0=0x%08lX hr1=0x%08lX â€” disabling\n",
                   (unsigned long)(DWORD)hr_s0, (unsigned long)(DWORD)hr_s1);
            if (g_pipe.pHudStagingRing[0]) { ID3D11Texture2D_Release(g_pipe.pHudStagingRing[0]); g_pipe.pHudStagingRing[0] = NULL; }
            if (g_pipe.pHudStagingRing[1]) { ID3D11Texture2D_Release(g_pipe.pHudStagingRing[1]); g_pipe.pHudStagingRing[1] = NULL; }
            g_pipe.hud_staged_ring_enabled = false;
        } else {
            printf("[STREAM INTEL] STAGED_RING2: ENABLED (2 x STAGING RGBA 2560x1440 allocated)\n");
        }
    } else {
        printf("[STREAM INTEL] STAGED_RING2: DISABLED (legacy UpdateSubresource path)\n");
    }

    // 2A Contention Deep Instrumentation Toggle
    const char* env_contention = getenv("TELEM_INTEL_CONTENTION_INSTRUMENTATION");
    g_pipe.contention_instrumentation_enabled = (env_contention && strcmp(env_contention, "1") == 0);
    if (g_pipe.contention_instrumentation_enabled) {
        printf("[STREAM INTEL] CONTENTION_INSTRUMENTATION: ENABLED (deep profiling active)\n");
    } else {
        printf("[STREAM INTEL] CONTENTION_INSTRUMENTATION: DISABLED (clean production mode)\n");
    }

    return 0;
}

__declspec(dllexport) int intel_d3d11_vp_init(void) {
    return intel_d3d11_vp_init_ex(INTEL_CODEC_AV1);
}

__declspec(dllexport) void intel_d3d11_vp_cleanup(void) {
    // 1D.1 Staged Ring release (before pHudTex/pHudInputView)
    for (int i = 0; i < 2; i++) {
        if (g_pipe.pHudStagingRing[i]) { ID3D11Texture2D_Release(g_pipe.pHudStagingRing[i]); g_pipe.pHudStagingRing[i] = NULL; }
    }
    if (g_pipe.pVPOutView) { ID3D11VideoProcessorOutputView_Release(g_pipe.pVPOutView); g_pipe.pVPOutView = NULL; }
    if (g_pipe.pVPOutTex) { ID3D11Texture2D_Release(g_pipe.pVPOutTex); g_pipe.pVPOutTex = NULL; }
    if (g_pipe.pHudInputView) { ID3D11VideoProcessorInputView_Release(g_pipe.pHudInputView); g_pipe.pHudInputView = NULL; }
    if (g_pipe.pHudTex) { ID3D11Texture2D_Release(g_pipe.pHudTex); g_pipe.pHudTex = NULL; }
    if (g_pipe.pBaseInputView) { ID3D11VideoProcessorInputView_Release(g_pipe.pBaseInputView); g_pipe.pBaseInputView = NULL; }
    if (g_pipe.pBaseTex) { ID3D11Texture2D_Release(g_pipe.pBaseTex); g_pipe.pBaseTex = NULL; }
    if (g_pipe.pStagingTex) { ID3D11Texture2D_Release(g_pipe.pStagingTex); g_pipe.pStagingTex = NULL; }
    if (g_pipe.pVP) { ID3D11VideoProcessor_Release(g_pipe.pVP); g_pipe.pVP = NULL; }
    if (g_pipe.pEnum) { ID3D11VideoProcessorEnumerator_Release(g_pipe.pEnum); g_pipe.pEnum = NULL; }
    if (g_pipe.pVideoContext) { ID3D11VideoContext_Release(g_pipe.pVideoContext); g_pipe.pVideoContext = NULL; }
    if (g_pipe.pVideoDevice) { ID3D11VideoDevice_Release(g_pipe.pVideoDevice); g_pipe.pVideoDevice = NULL; }
    if (g_pipe.pUploadContext) { ID3D11DeviceContext_Release(g_pipe.pUploadContext); g_pipe.pUploadContext = NULL; }
    if (g_pipe.pUploadDevice) { ID3D11Device_Release(g_pipe.pUploadDevice); g_pipe.pUploadDevice = NULL; }
    if (g_pipe.pContext) {
        ID3D11DeviceContext_ClearState(g_pipe.pContext);
        ID3D11DeviceContext_Flush(g_pipe.pContext);
        ID3D11DeviceContext_Release(g_pipe.pContext);
        g_pipe.pContext = NULL;
    }
    if (g_pipe.pDevice) { ID3D11Device_Release(g_pipe.pDevice); g_pipe.pDevice = NULL; }
    g_pipe.initialized = false;
}

__declspec(dllexport) void* intel_d3d11_vp_get_shared_handle(void) {
    return NULL;
}

__declspec(dllexport) int intel_d3d11_vp_composite_frame(const char* base_p010_buffer, const char* hud_rgba_buffer) {
    if (!g_pipe.initialized) return -1;
    if (base_p010_buffer) {
        ID3D11DeviceContext_UpdateSubresource(g_pipe.pContext, (ID3D11Resource*)g_pipe.pBaseTex, 0, NULL, base_p010_buffer, BASE_W * 2, 0);
    }
    if (hud_rgba_buffer) {
        ID3D11DeviceContext_UpdateSubresource(g_pipe.pContext, (ID3D11Resource*)g_pipe.pHudTex, 0, NULL, hud_rgba_buffer, HUD_W * 4, 0);
    }
    D3D11_VIDEO_PROCESSOR_STREAM streams[2] = {0};
    streams[0].Enable = TRUE;
    streams[0].pInputSurface = g_pipe.pBaseInputView;
    streams[1].Enable = TRUE;
    streams[1].pInputSurface = g_pipe.pHudInputView;
    HRESULT hr = ID3D11VideoContext_VideoProcessorBlt(g_pipe.pVideoContext, g_pipe.pVP, g_pipe.pVPOutView, 0, 2, streams);
    return SUCCEEDED(hr) ? 0 : -2;
}

__declspec(dllexport) int intel_d3d11_vp_get_output_frame(char* out_p010_buffer, size_t max_bytes) {
    if (!g_pipe.initialized) return -1;
    size_t req_bytes = (BASE_W * BASE_H * 2) + (BASE_W * (BASE_H / 2) * 2);
    if (max_bytes < req_bytes) return -2;

    if (!g_pipe.pStagingTex) {
        D3D11_TEXTURE2D_DESC sDesc = {0};
        sDesc.Width = BASE_W;
        sDesc.Height = BASE_H;
        sDesc.MipLevels = 1;
        sDesc.ArraySize = 1;
        sDesc.Format = DXGI_FORMAT_P010;
        sDesc.SampleDesc.Count = 1;
        sDesc.Usage = D3D11_USAGE_STAGING;
        sDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        ID3D11Device_CreateTexture2D(g_pipe.pDevice, &sDesc, NULL, &g_pipe.pStagingTex);
    }

    ID3D11DeviceContext_CopyResource(g_pipe.pContext, (ID3D11Resource*)g_pipe.pStagingTex, (ID3D11Resource*)g_pipe.pVPOutTex);
    D3D11_MAPPED_SUBRESOURCE map;
    HRESULT hr = ID3D11DeviceContext_Map(g_pipe.pContext, (ID3D11Resource*)g_pipe.pStagingTex, 0, D3D11_MAP_READ, 0, &map);
    if (FAILED(hr)) return -3;

    size_t row_bytes = BASE_W * 2;
    for (int y = 0; y < BASE_H; y++) {
        memcpy(out_p010_buffer + y * row_bytes, (const char*)map.pData + y * map.RowPitch, row_bytes);
    }
    char* dst_uv = out_p010_buffer + BASE_H * row_bytes;
    const char* src_uv = (const char*)map.pData + BASE_H * map.RowPitch;
    for (int y = 0; y < BASE_H / 2; y++) {
        memcpy(dst_uv + y * row_bytes, src_uv + y * map.RowPitch, row_bytes);
    }
    ID3D11DeviceContext_Unmap(g_pipe.pContext, (ID3D11Resource*)g_pipe.pStagingTex, 0);
    return 0;
}

static void sync_oldest_encode_slot(IntelNativeContext* ctx) {
    if (ctx->pending_encode_count == 0) return;
    int tail = ctx->enc_tail_idx;
    if (!ctx->encode_pool[tail].in_use) return;

    LARGE_INTEGER t0, t1;
    QueryPerformanceCounter(&t0);
    if (ctx->encode_pool[tail].syncp) {
        ctx->pMFXVideoCORE_SyncOperation(ctx->session, ctx->encode_pool[tail].syncp, 60000);
        ctx->encode_pool[tail].syncp = NULL;
    }
    QueryPerformanceCounter(&t1);
    double sync_ms = get_time_ms(t0, t1, ctx->freq);
    ctx->stats.total_sync_ms += sync_ms;
    ctx->stats.total_encode_ms += sync_ms;
    if (ctx->num_sync_samples < 4096) {
        ctx->sync_samples_buffer[ctx->num_sync_samples++] = sync_ms;
    }

    if (ctx->encode_pool[tail].bs.DataLength > 0) {
        ctx->stats.encoded_frames++;
        ctx->stats.total_bytes_encoded += ctx->encode_pool[tail].bs.DataLength;
        if (ctx->fOutIVF) {
            if (ctx->codec_id == INTEL_CODEC_AV1) {
                uint32_t frame_hdr[3] = { ctx->encode_pool[tail].bs.DataLength, (uint32_t)ctx->stats.encoded_frames, 0 };
                fwrite(frame_hdr, 1, 12, ctx->fOutIVF);
            }
            fwrite(ctx->encode_pool[tail].bs.Data + ctx->encode_pool[tail].bs.DataOffset, 1, ctx->encode_pool[tail].bs.DataLength, ctx->fOutIVF);
        }
    }

    ctx->encode_pool[tail].in_use = false;
    ctx->enc_tail_idx = (ctx->enc_tail_idx + 1) % ctx->pool_size;
    ctx->pending_encode_count--;
}

// =========================================================================
// =========================================================================
// MULTI-CLIP PIPELINE INITIALIZATION
// =========================================================================

__declspec(dllexport) int intel_native_pipeline_init_multi_ex(
    const char** video_paths,
    int num_clips,
    const char* out_bitstream_path,
    int target_kbps,
    int max_kbps,
    int expected_total_frames,
    int codec_id
) {
    if (!video_paths || num_clips <= 0 || num_clips > MAX_MULTI_CLIPS) return -1;

    g_pipe.codec_id = codec_id;
    int ret = intel_d3d11_vp_init_ex(codec_id);
    if (ret != 0) return ret;

    const char* env_serial = getenv("TELEM_INTEL_FORCE_SERIAL_7D");
    bool force_serial_7d = (env_serial && strcmp(env_serial, "1") == 0);

    int saved_mt_active = g_pipe.stats.d3d11_mt_protection_active;
    int saved_mt_qi_hr = g_pipe.stats.d3d11_mt_qi_hresult;
    memset(&g_pipe.stats, 0, sizeof(IntelNativePipelineStats));
    g_pipe.stats.d3d11_mt_protection_active = saved_mt_active;
    g_pipe.stats.d3d11_mt_qi_hresult = saved_mt_qi_hr;
    g_pipe.cancelled = false;
    const char* env_depth = getenv("TELEM_INTEL_MFX_ASYNC_DEPTH");
    int mfx_depth = (env_depth && atoi(env_depth) > 0) ? atoi(env_depth) : (force_serial_7d ? 1 : 8);
    if (mfx_depth > ENCODE_POOL_SIZE) mfx_depth = ENCODE_POOL_SIZE;
    g_pipe.async_depth = mfx_depth;

    const char* env_watermark = getenv("TELEM_INTEL_APP_DRAIN_WATERMARK");
    int app_watermark = (env_watermark && atoi(env_watermark) > 0) ? atoi(env_watermark) : g_pipe.async_depth;
    if (app_watermark > ENCODE_POOL_SIZE) app_watermark = ENCODE_POOL_SIZE;
    g_pipe.app_drain_watermark = app_watermark;

    const char* env_late_drain = getenv("TELEM_INTEL_LATE_DRAIN");
    g_pipe.late_drain_enabled = (env_late_drain && strcmp(env_late_drain, "1") == 0);

    g_pipe.pool_size = force_serial_7d ? 1 : ENCODE_POOL_SIZE; // 16
    g_pipe.num_sync_samples = 0;

    g_pipe.stats.mfx_async_depth_param = g_pipe.async_depth;
    g_pipe.stats.app_drain_watermark_param = g_pipe.app_drain_watermark;
    g_pipe.stats.late_drain_active = g_pipe.late_drain_enabled ? 1 : 0;

    const char* env_direct_vp = getenv("TELEM_INTEL_DIRECT_VP_SURFACE");
    g_pipe.use_direct_vp_surface = (env_direct_vp && strcmp(env_direct_vp, "0") == 0) ? false : true;
    g_pipe.num_cached_out_views = 0;
    memset(g_pipe.cached_out_views, 0, sizeof(g_pipe.cached_out_views));

    g_pipe.num_clips = num_clips;
    for (int i = 0; i < num_clips; i++) {
        strncpy(g_pipe.clip_paths[i], video_paths[i], MAX_PATH - 1);
        g_pipe.clip_paths[i][MAX_PATH - 1] = '\0';
    }
    g_pipe.current_clip_idx = 0;
    g_pipe.clip_pts_offset = 0;
    g_pipe.clip_time_offset_sec = 0.0;

    // 1. Init oneVPL
    g_pipe.hVpl = LoadLibraryA("libvpl.dll");
    if (!g_pipe.hVpl) return -10;

    g_pipe.pMFXLoad = (mfxCreateLoader_fn)GetProcAddress(g_pipe.hVpl, "MFXLoad");
    g_pipe.pMFXCreateConfig = (mfxCreateConfig_fn)GetProcAddress(g_pipe.hVpl, "MFXCreateConfig");
    g_pipe.pMFXSetConfigFilterProperty = (mfxSetConfigFilterProperty_fn)GetProcAddress(g_pipe.hVpl, "MFXSetConfigFilterProperty");
    g_pipe.pMFXCreateSession = (mfxCreateSession_fn)GetProcAddress(g_pipe.hVpl, "MFXCreateSession");
    g_pipe.pMFXUnload = (mfxUnload_fn)GetProcAddress(g_pipe.hVpl, "MFXUnload");
    g_pipe.pMFXClose = (mfxClose_fn)GetProcAddress(g_pipe.hVpl, "MFXClose");
    g_pipe.pMFXVideoCORE_SetHandle = (mfxVideoCORE_SetHandle_fn)GetProcAddress(g_pipe.hVpl, "MFXVideoCORE_SetHandle");
    g_pipe.pMFXVideoENCODE_Init = (mfxVideoENCODE_Init_fn)GetProcAddress(g_pipe.hVpl, "MFXVideoENCODE_Init");
    g_pipe.pMFXMemory_GetSurfaceForEncode = (mfxMemory_GetSurfaceForEncode_fn)GetProcAddress(g_pipe.hVpl, "MFXMemory_GetSurfaceForEncode");
    g_pipe.pMFXVideoENCODE_EncodeFrameAsync = (mfxVideoENCODE_EncodeFrameAsync_fn)GetProcAddress(g_pipe.hVpl, "MFXVideoENCODE_EncodeFrameAsync");
    g_pipe.pMFXVideoCORE_SyncOperation = (mfxVideoCORE_SyncOperation_fn)GetProcAddress(g_pipe.hVpl, "MFXVideoCORE_SyncOperation");

    g_pipe.loader = g_pipe.pMFXLoad();
    mfxConfig cfg = g_pipe.pMFXCreateConfig(g_pipe.loader);
    mfxVariant var;
    var.Type = MFX_VARIANT_TYPE_U32;
    var.Data.U32 = MFX_IMPL_TYPE_HARDWARE;
    g_pipe.pMFXSetConfigFilterProperty(cfg, (const mfxU8*)"mfxImplDescription.Impl", var);

    var.Data.U32 = MFX_ACCEL_MODE_VIA_D3D11;
    g_pipe.pMFXSetConfigFilterProperty(cfg, (const mfxU8*)"mfxImplDescription.AccelerationMode", var);

    var.Data.U32 = (codec_id == INTEL_CODEC_H264) ? MFX_CODEC_AVC : ((codec_id == INTEL_CODEC_HEVC) ? MFX_CODEC_HEVC : MFX_CODEC_AV1);
    g_pipe.pMFXSetConfigFilterProperty(cfg, (const mfxU8*)"mfxImplDescription.mfxEncoderDescription.encoder.CodecId", var);

    g_pipe.pMFXCreateSession(g_pipe.loader, 0, &g_pipe.session);
    g_pipe.pMFXVideoCORE_SetHandle(g_pipe.session, MFX_HANDLE_D3D11_DEVICE, (mfxHDL)g_pipe.pDevice);

    // Video Param (Parameter Parity with FFmpeg -preset veryfast)
    mfxVideoParam initPar = {0};
    mfxExtVideoSignalInfo vsi = {0};
    vsi.Header.BufferId = MFX_EXTBUFF_VIDEO_SIGNAL_INFO;
    vsi.Header.BufferSz = sizeof(vsi);
    vsi.VideoFormat = 5;
    vsi.VideoFullRange = (codec_id == INTEL_CODEC_H264) ? 0 : 1; // 0 = Studio range TV (16..235) for H.264 SDR, 1 = Full range PC for HEVC/AV1 HDR
    vsi.ColourDescriptionPresent = 1;
    vsi.ColourPrimaries = (codec_id == INTEL_CODEC_H264) ? 1 : 9; // 1 = BT.709 for H.264 SDR, 9 = BT.2020 for HEVC/AV1 HDR
    vsi.TransferCharacteristics = (codec_id == INTEL_CODEC_H264) ? 1 : 18; // 1 = BT.709, 18 = HLG
    vsi.MatrixCoefficients = (codec_id == INTEL_CODEC_H264) ? 1 : 9;

    mfxExtBuffer* extBuffers[1] = { (mfxExtBuffer*)&vsi };
    initPar.ExtParam = extBuffers;
    initPar.NumExtParam = 1;

    if (codec_id == INTEL_CODEC_H264) {
        initPar.mfx.CodecId = MFX_CODEC_AVC;
        initPar.mfx.CodecProfile = MFX_PROFILE_AVC_HIGH;
        initPar.mfx.CodecLevel = MFX_LEVEL_AVC_52;
        initPar.mfx.FrameInfo.FourCC = MFX_FOURCC_NV12;
        initPar.mfx.FrameInfo.ChromaFormat = MFX_CHROMAFORMAT_YUV420;
        initPar.mfx.FrameInfo.BitDepthLuma = 8;
        initPar.mfx.FrameInfo.BitDepthChroma = 8;
        initPar.mfx.FrameInfo.Shift = 0;
    } else if (codec_id == INTEL_CODEC_HEVC) {
        initPar.mfx.CodecId = MFX_CODEC_HEVC;
        initPar.mfx.CodecProfile = MFX_PROFILE_HEVC_MAIN10;
        initPar.mfx.CodecLevel = 0;
        initPar.mfx.FrameInfo.FourCC = MFX_FOURCC_P010;
        initPar.mfx.FrameInfo.ChromaFormat = MFX_CHROMAFORMAT_YUV420;
        initPar.mfx.FrameInfo.BitDepthLuma = 10;
        initPar.mfx.FrameInfo.BitDepthChroma = 10;
        initPar.mfx.FrameInfo.Shift = 1;
    } else {
        initPar.mfx.CodecId = MFX_CODEC_AV1;
        initPar.mfx.CodecProfile = MFX_PROFILE_AV1_MAIN;
        initPar.mfx.CodecLevel = 0;
        initPar.mfx.FrameInfo.FourCC = MFX_FOURCC_P010;
        initPar.mfx.FrameInfo.ChromaFormat = MFX_CHROMAFORMAT_YUV420;
        initPar.mfx.FrameInfo.BitDepthLuma = 10;
        initPar.mfx.FrameInfo.BitDepthChroma = 10;
        initPar.mfx.FrameInfo.Shift = 1;
    }

    initPar.mfx.TargetUsage = force_serial_7d ? MFX_TARGETUSAGE_BALANCED : MFX_TARGETUSAGE_BEST_SPEED;
    initPar.mfx.TargetKbps = (target_kbps > 0) ? target_kbps : 40000;
    initPar.mfx.MaxKbps = (max_kbps > 0) ? max_kbps : 50000;
    initPar.mfx.BufferSizeInKB = 10000;
    initPar.mfx.InitialDelayInKB = 5000;
    initPar.mfx.BRCParamMultiplier = 1;
    initPar.mfx.RateControlMethod = MFX_RATECONTROL_VBR;
    initPar.mfx.GopPicSize = 60;
    initPar.mfx.GopRefDist = 1;
    initPar.mfx.FrameInfo.FrameRateExtN = 30000;
    initPar.mfx.FrameInfo.FrameRateExtD = 1001;
    initPar.mfx.FrameInfo.PicStruct = MFX_PICSTRUCT_PROGRESSIVE;
    initPar.mfx.FrameInfo.Width = ((BASE_W + 15) >> 4) << 4;
    initPar.mfx.FrameInfo.Height = ((BASE_H + 15) >> 4) << 4;
    initPar.mfx.FrameInfo.CropW = BASE_W;
    initPar.mfx.FrameInfo.CropH = BASE_H;
    initPar.IOPattern = MFX_IOPATTERN_IN_VIDEO_MEMORY;
    initPar.AsyncDepth = g_pipe.async_depth;

    mfxStatus sts = g_pipe.pMFXVideoENCODE_Init(g_pipe.session, &initPar);
    if (sts != MFX_ERR_NONE) {
        initPar.ExtParam = NULL;
        initPar.NumExtParam = 0;
        sts = g_pipe.pMFXVideoENCODE_Init(g_pipe.session, &initPar);
        if (sts != MFX_ERR_NONE) return -11;
    }

    // Allocate encoder slot bitstream buffers
    size_t bs_size = 16 * 1024 * 1024;
    for (int i = 0; i < g_pipe.pool_size; i++) {
        g_pipe.encode_pool[i].pBsBuffer = (uint8_t*)malloc(bs_size);
        memset(&g_pipe.encode_pool[i].bs, 0, sizeof(mfxBitstream));
        g_pipe.encode_pool[i].bs.Data = g_pipe.encode_pool[i].pBsBuffer;
        g_pipe.encode_pool[i].bs.MaxLength = (uint32_t)bs_size;
        g_pipe.encode_pool[i].syncp = NULL;
        g_pipe.encode_pool[i].in_use = false;
        g_pipe.encode_pool[i].frame_idx = -1;
    }
    g_pipe.enc_head_idx = 0;
    g_pipe.enc_tail_idx = 0;
    g_pipe.pending_encode_count = 0;

    // 2. Open First Input MP4 and FFmpeg Decoder
    if (avformat_open_input(&g_pipe.fmt_ctx, g_pipe.clip_paths[0], NULL, NULL) < 0) return -20;
    avformat_find_stream_info(g_pipe.fmt_ctx, NULL);

    g_pipe.video_stream_idx = -1;
    for (unsigned int i = 0; i < g_pipe.fmt_ctx->nb_streams; i++) {
        if (g_pipe.fmt_ctx->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
            g_pipe.video_stream_idx = i;
            break;
        }
    }
    if (g_pipe.video_stream_idx < 0) return -21;

    AVStream* st = g_pipe.fmt_ctx->streams[g_pipe.video_stream_idx];
    g_pipe.time_base = st->time_base;
    g_pipe.avg_fps = st->avg_frame_rate;

    const AVCodec* dec = avcodec_find_decoder(st->codecpar->codec_id);
    g_pipe.dec_ctx = avcodec_alloc_context3(dec);
    avcodec_parameters_to_context(g_pipe.dec_ctx, st->codecpar);

    const char* env_hw_dec = getenv("TELEM_INTEL_HEVC_HW_DECODE");
    bool allow_hw_decode = (env_hw_dec == NULL || strcmp(env_hw_dec, "0") != 0);
    bool is_hevc = (st->codecpar->codec_id == AV_CODEC_ID_HEVC);

    g_pipe.hw_decode_active = false;
    g_pipe.hw_device_ctx = NULL;

    if (allow_hw_decode && is_hevc) {
        AVBufferRef* hw_device_ctx = av_hwdevice_ctx_alloc(AV_HWDEVICE_TYPE_D3D11VA);
        if (hw_device_ctx) {
            AVHWDeviceContext* dev_ctx = (AVHWDeviceContext*)hw_device_ctx->data;
            AVD3D11VADeviceContext* d3d11va_ctx = (AVD3D11VADeviceContext*)dev_ctx->hwctx;
            d3d11va_ctx->device = g_pipe.pDevice;
            ID3D11Device_AddRef(g_pipe.pDevice);
            d3d11va_ctx->BindFlags = D3D11_BIND_DECODER;
            int ret_hw = av_hwdevice_ctx_init(hw_device_ctx);
            if (ret_hw >= 0) {
                g_pipe.hw_device_ctx = hw_device_ctx;
                g_pipe.dec_ctx->hw_device_ctx = av_buffer_ref(hw_device_ctx);
                g_pipe.dec_ctx->get_format = get_hw_format;
                g_pipe.dec_ctx->extra_hw_frames = 8;
                g_pipe.hw_decode_active = true;
                printf("[STREAM INTEL] D3D11VA Hardware HEVC Decoder active on production D3D11 device.\n");
            } else {
                av_buffer_unref(&hw_device_ctx);
                g_pipe.stats.decoder_fallback_count++;
                printf("[STREAM INTEL] WARNING: av_hwdevice_ctx_init failed (%d), falling back to SW decode.\n", ret_hw);
            }
        } else {
            g_pipe.stats.decoder_fallback_count++;
            printf("[STREAM INTEL] WARNING: av_hwdevice_ctx_alloc failed, falling back to SW decode.\n");
        }
    }

    if (!g_pipe.hw_decode_active) {
        const char* env_dec_th = getenv("TELEM_INTEL_DECODER_THREADS");
        g_pipe.dec_ctx->thread_count = (env_dec_th && atoi(env_dec_th) > 0) ? atoi(env_dec_th) : 0;
    }
    if (avcodec_open2(g_pipe.dec_ctx, dec, NULL) < 0) {
        if (g_pipe.hw_decode_active) {
            printf("[STREAM INTEL] WARNING: avcodec_open2 with HW accel failed, falling back to SW decode.\n");
            g_pipe.stats.decoder_fallback_count++;
            g_pipe.hw_decode_active = false;
            if (g_pipe.dec_ctx->hw_device_ctx) {
                av_buffer_unref(&g_pipe.dec_ctx->hw_device_ctx);
            }
            g_pipe.dec_ctx->get_format = NULL;
            const char* env_dec_th = getenv("TELEM_INTEL_DECODER_THREADS");
            g_pipe.dec_ctx->thread_count = (env_dec_th && atoi(env_dec_th) > 0) ? atoi(env_dec_th) : 0;
            if (avcodec_open2(g_pipe.dec_ctx, dec, NULL) < 0) return -22;
        } else {
            return -22;
        }
    }

    g_pipe.pkt = av_packet_alloc();
    g_pipe.frame = av_frame_alloc();

    // Allocate Decode Ring Buffer (Dual-Device Shared P010 Ring or Single-Device Staging Ring)
    const char* env_no_staging = getenv("TELEM_INTEL_DISABLE_STAGING_RING");
    g_pipe.use_staging_ring = (env_no_staging && strcmp(env_no_staging, "1") == 0) ? false : true;

    const char* env_topo = getenv("TELEM_INTEL_TOPOLOGY");
    g_pipe.topology_mode = (env_topo && (strcmp(env_topo, "C") == 0 || strcmp(env_topo, "PACK_IN_CONSUMER") == 0)) ? 1 : 0;

    const char* env_slots = getenv("TELEM_INTEL_SHARED_RING_SLOTS");
    int ring_slots = (env_slots && atoi(env_slots) >= 2 && atoi(env_slots) <= 4) ? atoi(env_slots) : 3;
    g_pipe.shared_ring_slots = ring_slots;

    if (g_pipe.use_dual_device && g_pipe.pUploadDevice) {
        D3D11_TEXTURE2D_DESC sDesc = {0};
        sDesc.Width = BASE_W;
        sDesc.Height = BASE_H;
        sDesc.MipLevels = 1;
        sDesc.ArraySize = 1;
        sDesc.Format = DXGI_FORMAT_P010;
        sDesc.SampleDesc.Count = 1;
        sDesc.Usage = D3D11_USAGE_STAGING;
        sDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;

        D3D11_TEXTURE2D_DESC dDesc = {0};
        dDesc.Width = BASE_W;
        dDesc.Height = BASE_H;
        dDesc.MipLevels = 1;
        dDesc.ArraySize = 1;
        dDesc.Format = DXGI_FORMAT_P010;
        dDesc.SampleDesc.Count = 1;
        dDesc.Usage = D3D11_USAGE_DEFAULT;
        dDesc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
        dDesc.MiscFlags = D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX;

        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC ivDesc = {0};
        ivDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;

        for (int i = 0; i < g_pipe.shared_ring_slots; i++) {
            g_pipe.decode_ring[i].p010_data = NULL;
            g_pipe.decode_ring[i].pStagingTex = NULL;
            g_pipe.decode_ring[i].pSharedBaseTexA = NULL;
            g_pipe.decode_ring[i].pKeyedMutexA = NULL;
            g_pipe.decode_ring[i].hSharedHandle = NULL;
            g_pipe.decode_ring[i].pOpenedBaseTexB = NULL;
            g_pipe.decode_ring[i].pBaseInputViewB = NULL;
            g_pipe.decode_ring[i].pKeyedMutexB = NULL;
            g_pipe.decode_ring[i].pAvFrame = av_frame_alloc();
            g_pipe.decode_ring[i].is_ready = false;
            g_pipe.decode_ring[i].is_eof = false;
            g_pipe.decode_ring[i].frame_idx = -1;

            // 1. Create Staging Texture on Device A
            HRESULT hr = ID3D11Device_CreateTexture2D(g_pipe.pUploadDevice, &sDesc, NULL, &g_pipe.decode_ring[i].pStagingTex);
            if (FAILED(hr)) {
                printf("[STREAM INTEL] ERROR: Failed to create staging texture on Device A (slot %d, hr=0x%08lX)\n", i, (unsigned long)hr);
                return -40;
            }

            // 2. Create Shared Texture on Device A
            hr = ID3D11Device_CreateTexture2D(g_pipe.pUploadDevice, &dDesc, NULL, &g_pipe.decode_ring[i].pSharedBaseTexA);
            if (FAILED(hr)) {
                printf("[STREAM INTEL] ERROR: Failed to create shared texture on Device A (slot %d, hr=0x%08lX)\n", i, (unsigned long)hr);
                return -41;
            }

            // 3. Get Keyed Mutex on Device A
            hr = ID3D11Texture2D_QueryInterface(g_pipe.decode_ring[i].pSharedBaseTexA, &IID_IDXGIKeyedMutex, (void**)&g_pipe.decode_ring[i].pKeyedMutexA);
            if (FAILED(hr) || !g_pipe.decode_ring[i].pKeyedMutexA) {
                printf("[STREAM INTEL] ERROR: Failed to query IDXGIKeyedMutex on Device A (slot %d, hr=0x%08lX)\n", i, (unsigned long)hr);
                return -42;
            }

            // 4. Get Shared Handle
            IDXGIResource* pResA = NULL;
            hr = ID3D11Texture2D_QueryInterface(g_pipe.decode_ring[i].pSharedBaseTexA, &IID_IDXGIResource, (void**)&pResA);
            if (FAILED(hr) || !pResA) {
                printf("[STREAM INTEL] ERROR: Failed to query IDXGIResource on Device A (slot %d, hr=0x%08lX)\n", i, (unsigned long)hr);
                return -43;
            }
            hr = IDXGIResource_GetSharedHandle(pResA, &g_pipe.decode_ring[i].hSharedHandle);
            IDXGIResource_Release(pResA);
            if (FAILED(hr) || !g_pipe.decode_ring[i].hSharedHandle) {
                printf("[STREAM INTEL] ERROR: Failed to get shared handle on Device A (slot %d, hr=0x%08lX)\n", i, (unsigned long)hr);
                return -44;
            }

            // 5. Open Shared Resource on Device B
            hr = ID3D11Device_OpenSharedResource(g_pipe.pDevice, g_pipe.decode_ring[i].hSharedHandle, &IID_ID3D11Texture2D, (void**)&g_pipe.decode_ring[i].pOpenedBaseTexB);
            if (FAILED(hr) || !g_pipe.decode_ring[i].pOpenedBaseTexB) {
                printf("[STREAM INTEL] ERROR: Failed to open shared resource on Device B (slot %d, hr=0x%08lX)\n", i, (unsigned long)hr);
                return -45;
            }

            // 6. Get Keyed Mutex on Device B
            hr = ID3D11Texture2D_QueryInterface(g_pipe.decode_ring[i].pOpenedBaseTexB, &IID_IDXGIKeyedMutex, (void**)&g_pipe.decode_ring[i].pKeyedMutexB);
            if (FAILED(hr) || !g_pipe.decode_ring[i].pKeyedMutexB) {
                printf("[STREAM INTEL] ERROR: Failed to query IDXGIKeyedMutex on Device B (slot %d, hr=0x%08lX)\n", i, (unsigned long)hr);
                return -46;
            }

            // 7. Create Video Processor Input View on Device B
            hr = ID3D11VideoDevice_CreateVideoProcessorInputView(g_pipe.pVideoDevice, (ID3D11Resource*)g_pipe.decode_ring[i].pOpenedBaseTexB, g_pipe.pEnum, &ivDesc, &g_pipe.decode_ring[i].pBaseInputViewB);
            if (FAILED(hr) || !g_pipe.decode_ring[i].pBaseInputViewB) {
                printf("[STREAM INTEL] ERROR: Failed to create VP input view on Device B (slot %d, hr=0x%08lX)\n", i, (unsigned long)hr);
                return -47;
            }
        }
        printf("[STREAM INTEL] SHARED_P010_RING_READY: %d slots initialized with KeyedMutex & VP input views.\n", g_pipe.shared_ring_slots);
    } else if (g_pipe.use_staging_ring) {
        D3D11_TEXTURE2D_DESC sDesc = {0};
        sDesc.Width = BASE_W;
        sDesc.Height = BASE_H;
        sDesc.MipLevels = 1;
        sDesc.ArraySize = 1;
        sDesc.Format = DXGI_FORMAT_P010;
        sDesc.SampleDesc.Count = 1;
        sDesc.Usage = D3D11_USAGE_STAGING;
        sDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        for (int i = 0; i < DECODE_RING_SIZE; i++) {
            g_pipe.decode_ring[i].p010_data = NULL;
            g_pipe.decode_ring[i].pStagingTex = NULL;
            g_pipe.decode_ring[i].pAvFrame = av_frame_alloc();
            ID3D11Device_CreateTexture2D(g_pipe.pDevice, &sDesc, NULL, &g_pipe.decode_ring[i].pStagingTex);
            g_pipe.decode_ring[i].is_ready = false;
            g_pipe.decode_ring[i].is_eof = false;
            g_pipe.decode_ring[i].frame_idx = -1;
        }
    } else {
        size_t p010_elems = BASE_W * BASE_H + BASE_W * (BASE_H / 2);
        for (int i = 0; i < DECODE_RING_SIZE; i++) {
            g_pipe.decode_ring[i].pStagingTex = NULL;
            g_pipe.decode_ring[i].pAvFrame = av_frame_alloc();
            g_pipe.decode_ring[i].p010_data = (uint16_t*)_aligned_malloc(p010_elems * 2, 64);
            g_pipe.decode_ring[i].is_ready = false;
            g_pipe.decode_ring[i].is_eof = false;
            g_pipe.decode_ring[i].frame_idx = -1;
        }
    }
    g_pipe.decode_head_idx = 0;
    g_pipe.decode_tail_idx = 0;
    g_pipe.decode_queued_count = 0;
    g_pipe.bStopDecode = false;

    InitializeCriticalSection(&g_pipe.csDecode);
    InitializeConditionVariable(&g_pipe.cvDecodeFree);
    InitializeConditionVariable(&g_pipe.cvDecodeReady);

    // Output IVF or raw H264 File
    g_pipe.fOutIVF = fopen(out_bitstream_path, "wb");
    if (g_pipe.fOutIVF && g_pipe.codec_id == INTEL_CODEC_AV1) {
        uint32_t total_f = (expected_total_frames > 0) ? (uint32_t)expected_total_frames : 1131;
        uint32_t fps_num = (g_pipe.avg_fps.num > 0) ? (uint32_t)g_pipe.avg_fps.num : 30000;
        uint32_t fps_den = (g_pipe.avg_fps.den > 0) ? (uint32_t)g_pipe.avg_fps.den : 1001;

        uint8_t ivf_hdr[32] = {
            'D','K','I','F', 0,0, 32,0, 'A','V','0','1',
            (uint8_t)(BASE_W & 0xFF), (uint8_t)(BASE_W >> 8),
            (uint8_t)(BASE_H & 0xFF), (uint8_t)(BASE_H >> 8),
            (uint8_t)(fps_num & 0xFF), (uint8_t)((fps_num >> 8) & 0xFF), (uint8_t)((fps_num >> 16) & 0xFF), (uint8_t)(fps_num >> 24),
            (uint8_t)(fps_den & 0xFF), (uint8_t)((fps_den >> 8) & 0xFF), (uint8_t)((fps_den >> 16) & 0xFF), (uint8_t)(fps_den >> 24),
            (uint8_t)(total_f & 0xFF), (uint8_t)(total_f >> 8), (uint8_t)(total_f >> 16), (uint8_t)(total_f >> 24),
            0,0,0,0
        };
        fwrite(ivf_hdr, 1, 32, g_pipe.fOutIVF);
    }

    // Start background decode producer thread
    g_pipe.hDecodeThread = CreateThread(NULL, 0, decode_producer_thread_func, &g_pipe, 0, NULL);
    if (!g_pipe.hDecodeThread) return -30;

    QueryPerformanceCounter(&g_pipe.t_pipe_start);
    g_pipe.pipeline_open = true;
    return 0;
}

// Multi-Clip Legacy Wrapper (Defaults to AV1)
__declspec(dllexport) int intel_native_pipeline_init_multi(
    const char** video_paths,
    int num_clips,
    const char* out_bitstream_path,
    int target_kbps,
    int max_kbps,
    int expected_total_frames
) {
    return intel_native_pipeline_init_multi_ex(video_paths, num_clips, out_bitstream_path, target_kbps, max_kbps, expected_total_frames, INTEL_CODEC_AV1);
}

// Single Clip Wrapper
__declspec(dllexport) int intel_native_pipeline_init(
    const char* video_path,
    const char* out_bitstream_path,
    int target_kbps,
    int max_kbps,
    int expected_total_frames
) {
    const char* paths[1] = { video_path };
    return intel_native_pipeline_init_multi(paths, 1, out_bitstream_path, target_kbps, max_kbps, expected_total_frames);
}

__declspec(dllexport) int intel_native_pipeline_step_regions(
    const uint8_t* hud_rgba_buffer,
    const IntelHudBox* pBoxes,
    int num_boxes,
    int64_t* out_pts,
    double* out_pts_sec
) {
    if (!g_pipe.pipeline_open || g_pipe.cancelled) return -1;

    HANDLE hCurThread = GetCurrentThread();
    ULONG64 cons_c0 = 0, cons_c1 = 0;
    QueryThreadCycleTime(hCurThread, &cons_c0);

    LARGE_INTEGER freq = g_pipe.freq;
    LARGE_INTEGER t0, t1;

    // 1. Fetch next decoded frame from ring buffer
    QueryPerformanceCounter(&t0);
    EnterCriticalSection(&g_pipe.csDecode);

    // Sample queue occupancy
    int q_cnt = g_pipe.decode_queued_count;
    if (q_cnt >= 0 && q_cnt <= 4) {
        g_pipe.stats.queue_depth_counts[q_cnt]++;
        g_pipe.stats.queue_samples++;
    }

    while (g_pipe.decode_queued_count == 0 && !g_pipe.cancelled) {
        SleepConditionVariableCS(&g_pipe.cvDecodeReady, &g_pipe.csDecode, INFINITE);
    }
    if (g_pipe.cancelled) {
        LeaveCriticalSection(&g_pipe.csDecode);
        return -1;
    }
    int read_slot = g_pipe.decode_tail_idx;
    bool is_eof = g_pipe.decode_ring[read_slot].is_eof;
    LeaveCriticalSection(&g_pipe.csDecode);
    QueryPerformanceCounter(&t1);
    g_pipe.stats.total_queue_wait_ms += get_time_ms(t0, t1, freq);

    if (is_eof) {
        QueryThreadCycleTime(hCurThread, &cons_c1);
        g_pipe.stats.total_consumer_cycles += (cons_c1 - cons_c0);
        return 1; // EOF reached
    }

    if (out_pts) *out_pts = g_pipe.decode_ring[read_slot].pts;
    if (out_pts_sec) *out_pts_sec = g_pipe.decode_ring[read_slot].pts_sec;

    if (!g_pipe.logged_thread_ids) {
        g_pipe.stats.consumer_thread_id = (int)GetCurrentThreadId();
        g_pipe.stats.d3d11_context_thread_count = g_pipe.hw_decode_active ? 2 : 1;
        printf("[STREAM INTEL THREAD] Producer Thread ID: %u, Consumer Thread ID: %u, Context Thread Count: %d\n",
               (unsigned int)g_pipe.stats.producer_thread_id, (unsigned int)g_pipe.stats.consumer_thread_id,
               g_pipe.stats.d3d11_context_thread_count);
        g_pipe.logged_thread_ids = true;
    }

    // 2. Base Upload / Pack to D3D11 (Consumer D3D11 window start)
    if (g_pipe.contention_instrumentation_enabled) {
        InterlockedExchange(&g_pipe.consumer_in_d3d11, 1);
        if (g_pipe.producer_in_d3d11) {
            g_pipe.stats.producer_consumer_overlap_observed = 1;
        }
    }

    QueryPerformanceCounter(&t0);
    if (g_pipe.hw_decode_active) {
        AVFrame* src_frame = g_pipe.decode_ring[read_slot].pAvFrame;
        if (src_frame && src_frame->format == AV_PIX_FMT_D3D11 && src_frame->data[0]) {
            ID3D11Texture2D* pDecTex = (ID3D11Texture2D*)src_frame->data[0];
            int slice_idx = (int)(intptr_t)src_frame->data[1];

            // 2A Decoder Texture Contract & Shareability Inspection (once on first decoded surface)
            if (!g_pipe.decoder_contract_inspected) {
                D3D11_TEXTURE2D_DESC ddesc = {0};
                ID3D11Texture2D_GetDesc(pDecTex, &ddesc);
                g_pipe.stats.decoder_texture_width = (int)ddesc.Width;
                g_pipe.stats.decoder_texture_height = (int)ddesc.Height;
                g_pipe.stats.decoder_texture_format = (int)ddesc.Format;
                g_pipe.stats.decoder_texture_bind_flags = (int)ddesc.BindFlags;
                g_pipe.stats.decoder_texture_misc_flags = (int)ddesc.MiscFlags;
                g_pipe.stats.decoder_texture_array_size = (int)ddesc.ArraySize;

                IDXGIResource* pRes = NULL;
                static const GUID IID_IDXGIResource_local = {0x035f3ab4, 0x480e, 0x4e5b, {0xb3, 0x3d, 0x1d, 0x73, 0x32, 0x52, 0xb6, 0xda}};
                HRESULT hr_qi = ID3D11Texture2D_QueryInterface(pDecTex, &IID_IDXGIResource_local, (void**)&pRes);
                if (SUCCEEDED(hr_qi) && pRes) {
                    HANDLE hShared = NULL;
                    HRESULT hr_sh = IDXGIResource_GetSharedHandle(pRes, &hShared);
                    g_pipe.stats.decoder_shared_handle_hr = (int)hr_sh;
                    if (SUCCEEDED(hr_sh) && hShared != NULL) {
                        g_pipe.stats.decoder_surface_shareable = 1;
                        g_pipe.stats.decoder_shared_handle_supported = 1;
                    } else {
                        g_pipe.stats.decoder_surface_shareable = 0;
                        g_pipe.stats.decoder_shared_handle_supported = 0;
                    }
                    IDXGIResource_Release(pRes);
                } else {
                    g_pipe.stats.decoder_surface_shareable = 0;
                    g_pipe.stats.decoder_shared_handle_supported = 0;
                    g_pipe.stats.decoder_shared_handle_hr = (int)hr_qi;
                }
                g_pipe.decoder_contract_inspected = true;
                printf("[2A DECODER CONTRACT] W=%d H=%d Fmt=%d Bind=0x%X Misc=0x%X Array=%d Shareable=%d SharedHandle=%d hr=0x%08lX\n",
                       g_pipe.stats.decoder_texture_width, g_pipe.stats.decoder_texture_height,
                       g_pipe.stats.decoder_texture_format, g_pipe.stats.decoder_texture_bind_flags,
                       g_pipe.stats.decoder_texture_misc_flags, g_pipe.stats.decoder_texture_array_size,
                       g_pipe.stats.decoder_surface_shareable, g_pipe.stats.decoder_shared_handle_supported,
                       (unsigned long)g_pipe.stats.decoder_shared_handle_hr);
            }

            ID3D11VideoProcessorInputView* pDecInputView = NULL;
            for (int i = 0; i < g_pipe.num_cached_decode_views; i++) {
                if (g_pipe.cached_decode_views[i].pTex == pDecTex &&
                    g_pipe.cached_decode_views[i].slice_idx == slice_idx) {
                    pDecInputView = g_pipe.cached_decode_views[i].pInputView;
                    break;
                }
            }
            if (!pDecInputView && g_pipe.num_cached_decode_views < MAX_CACHED_DECODE_VIEWS) {
                D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC ivDesc = {0};
                ivDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
                ivDesc.FourCC = 0;
                ivDesc.Texture2D.MipSlice = 0;
                ivDesc.Texture2D.ArraySlice = (UINT)slice_idx;
                HRESULT hr_iv = ID3D11VideoDevice_CreateVideoProcessorInputView(
                    g_pipe.pVideoDevice,
                    (ID3D11Resource*)pDecTex,
                    g_pipe.pEnum,
                    &ivDesc,
                    &pDecInputView
                );
                if (SUCCEEDED(hr_iv) && pDecInputView) {
                    g_pipe.cached_decode_views[g_pipe.num_cached_decode_views].pTex = pDecTex;
                    g_pipe.cached_decode_views[g_pipe.num_cached_decode_views].slice_idx = slice_idx;
                    g_pipe.cached_decode_views[g_pipe.num_cached_decode_views].pInputView = pDecInputView;
                    g_pipe.num_cached_decode_views++;
                }
            }
            g_pipe.current_dec_input_view = pDecInputView;
        }
    } else if (g_pipe.use_dual_device && g_pipe.decode_ring[read_slot].pKeyedMutexB) {
        // Dual Device: Acquire KeyedMutex on Device B (Key 1 = Consumer Read)
        LARGE_INTEGER kw0, kw1;
        QueryPerformanceCounter(&kw0);
        HRESULT hr_acq = IDXGIKeyedMutex_AcquireSync(g_pipe.decode_ring[read_slot].pKeyedMutexB, 1, 2000);
        QueryPerformanceCounter(&kw1);
        g_pipe.stats.total_cross_wait_consumer_ms += get_time_ms(kw0, kw1, freq);
    } else if (g_pipe.topology_mode == 1) {
        AVFrame* src_frame = g_pipe.decode_ring[read_slot].pAvFrame;
        if (src_frame && src_frame->data[0]) {
            D3D11_MAPPED_SUBRESOURCE map;
            LARGE_INTEGER m0, m1, c0, c1, u0, u1;
            QueryPerformanceCounter(&m0);
            HRESULT hr = ID3D11DeviceContext_Map(g_pipe.pContext, (ID3D11Resource*)g_pipe.decode_ring[read_slot].pStagingTex, 0, D3D11_MAP_WRITE, 0, &map);
            QueryPerformanceCounter(&m1);
            g_pipe.stats.total_p010_map_ms += get_time_ms(m0, m1, freq);

            if (SUCCEEDED(hr) && map.pData) {
                QueryPerformanceCounter(&c0);
                yuv420p10le_to_p010_pitch(
                    (const uint16_t*)src_frame->data[0], src_frame->linesize[0],
                    (const uint16_t*)src_frame->data[1], src_frame->linesize[1],
                    (const uint16_t*)src_frame->data[2], src_frame->linesize[2],
                    (uint8_t*)map.pData, map.RowPitch,
                    BASE_W, BASE_H
                );
                QueryPerformanceCounter(&c1);
                g_pipe.stats.total_p010_pure_convert_ms += get_time_ms(c0, c1, freq);

                QueryPerformanceCounter(&u0);
                ID3D11DeviceContext_Unmap(g_pipe.pContext, (ID3D11Resource*)g_pipe.decode_ring[read_slot].pStagingTex, 0);
                QueryPerformanceCounter(&u1);
                g_pipe.stats.total_p010_unmap_ms += get_time_ms(u0, u1, freq);
            }
            av_frame_unref(src_frame);
        }
        ID3D11DeviceContext_CopyResource(
            g_pipe.pContext,
            (ID3D11Resource*)g_pipe.pBaseTex,
            (ID3D11Resource*)g_pipe.decode_ring[read_slot].pStagingTex
        );
        g_pipe.stats.total_p010_ms = g_pipe.stats.total_p010_map_ms + g_pipe.stats.total_p010_pure_convert_ms + g_pipe.stats.total_p010_unmap_ms;
    } else if (g_pipe.use_staging_ring && g_pipe.decode_ring[read_slot].pStagingTex) {
        ID3D11DeviceContext_CopyResource(
            g_pipe.pContext,
            (ID3D11Resource*)g_pipe.pBaseTex,
            (ID3D11Resource*)g_pipe.decode_ring[read_slot].pStagingTex
        );
    } else if (g_pipe.decode_ring[read_slot].p010_data) {
        ID3D11DeviceContext_UpdateSubresource(
            g_pipe.pContext,
            (ID3D11Resource*)g_pipe.pBaseTex,
            0, NULL,
            g_pipe.decode_ring[read_slot].p010_data,
            BASE_W * 2, 0
        );
    }
    QueryPerformanceCounter(&t1);
    g_pipe.stats.total_upload_base_ms += get_time_ms(t0, t1, freq);

    // 3. HUD Upload to D3D11
    // STAGED_RING2 path: Map -> memcpy -> Unmap -> CopyResource (when hud_staged_ring_enabled)
    // Legacy path:       UpdateSubresource (default, hud_staged_ring_enabled=false)
    QueryPerformanceCounter(&t0);
    bool was_overlap = (g_pipe.producer_in_d3d11 != 0);
    if (hud_rgba_buffer) {
        if (g_pipe.hud_staged_ring_enabled && !(pBoxes && num_boxes > 0)) {
            // --- 1D.1 STAGED_RING2 full-frame path ---
            int ridx = g_pipe.hud_staged_ring_idx;
            g_pipe.hud_staged_ring_idx = 1 - ridx; // rotate for next frame

            // Map staging texture
            LARGE_INTEGER sm0, sm1, sc0, sc1;
            QueryPerformanceCounter(&sm0);
            D3D11_MAPPED_SUBRESOURCE smap = {0};
            HRESULT hr_map = ID3D11DeviceContext_Map(
                g_pipe.pContext,
                (ID3D11Resource*)g_pipe.pHudStagingRing[ridx],
                0, D3D11_MAP_WRITE, 0, &smap
            );
            if (SUCCEEDED(hr_map) && smap.pData) {
                // Copy HUD data respecting pitch
                if (smap.RowPitch == (UINT)(HUD_W * 4)) {
                    memcpy(smap.pData, hud_rgba_buffer, (size_t)HUD_W * HUD_H * 4);
                } else {
                    for (int row = 0; row < HUD_H; row++) {
                        memcpy(
                            (uint8_t*)smap.pData + (size_t)row * smap.RowPitch,
                            hud_rgba_buffer + (size_t)row * HUD_W * 4,
                            (size_t)HUD_W * 4
                        );
                    }
                }
                ID3D11DeviceContext_Unmap(
                    g_pipe.pContext,
                    (ID3D11Resource*)g_pipe.pHudStagingRing[ridx],
                    0
                );
            }
            QueryPerformanceCounter(&sm1);
            g_pipe.stats.total_hud_staged_map_ms += get_time_ms(sm0, sm1, freq);

            // CopyResource staging -> DEFAULT HUD texture
            QueryPerformanceCounter(&sc0);
            ID3D11DeviceContext_CopyResource(
                g_pipe.pContext,
                (ID3D11Resource*)g_pipe.pHudTex,
                (ID3D11Resource*)g_pipe.pHudStagingRing[ridx]
            );
            QueryPerformanceCounter(&sc1);
            g_pipe.stats.total_hud_staged_copy_ms += get_time_ms(sc0, sc1, freq);

            g_pipe.stats.hud_dirty_bytes    += (uint64_t)HUD_W * HUD_H * 4;
            g_pipe.stats.hud_upload_call_count++;
            g_pipe.stats.hud_upload_full_count++;
        } else if (pBoxes != NULL && num_boxes > 0) {
            // --- Partial/damage region upload via UpdateSubresource ---
            uint64_t frame_dirty_bytes = 0;
            for (int b = 0; b < num_boxes; b++) {
                int l   = pBoxes[b].left   < 0    ? 0    : pBoxes[b].left;
                int t   = pBoxes[b].top    < 0    ? 0    : pBoxes[b].top;
                int r   = pBoxes[b].right  > HUD_W ? HUD_W : pBoxes[b].right;
                int btm = pBoxes[b].bottom > HUD_H ? HUD_H : pBoxes[b].bottom;
                if (r > l && btm > t) {
                    D3D11_BOX box;
                    box.left = l; box.top = t; box.front = 0;
                    box.right = r; box.bottom = btm; box.back = 1;
                    const uint8_t* pSrc = hud_rgba_buffer + (t * (HUD_W * 4)) + (l * 4);
                    ID3D11DeviceContext_UpdateSubresource(
                        g_pipe.pContext,
                        (ID3D11Resource*)g_pipe.pHudTex,
                        0, &box, pSrc, HUD_W * 4, 0
                    );
                    frame_dirty_bytes += (uint64_t)(r - l) * (btm - t) * 4;
                    g_pipe.stats.hud_upload_call_count++;
                }
            }
            g_pipe.stats.hud_dirty_bytes        += frame_dirty_bytes;
            g_pipe.stats.hud_dirty_region_count += num_boxes;
            g_pipe.stats.hud_upload_partial_count++;
        } else if (pBoxes != NULL && num_boxes == 0) {
            // --- Zero-damage frame: persistent GPU HUD texture remains 100% valid ---
            g_pipe.stats.hud_upload_skipped_count++;
        } else {
            // --- Full-frame UpdateSubresource (Frame 0, clip change, fallback) ---
            ID3D11DeviceContext_UpdateSubresource(
                g_pipe.pContext,
                (ID3D11Resource*)g_pipe.pHudTex,
                0, NULL,
                hud_rgba_buffer,
                HUD_W * 4, 0
            );
            if (g_pipe.contention_instrumentation_enabled && !was_overlap && g_pipe.producer_in_d3d11 != 0) {
                was_overlap = true;
            }
            g_pipe.stats.hud_dirty_bytes += (uint64_t)HUD_W * HUD_H * 4;
            g_pipe.stats.hud_upload_call_count++;
            g_pipe.stats.hud_upload_full_count++;
        }
        g_pipe.stats.hud_full_bytes += (uint64_t)HUD_W * HUD_H * 4;
    } else {
        g_pipe.stats.hud_upload_skipped_count++;
    }
    QueryPerformanceCounter(&t1);
    double upload_ms = get_time_ms(t0, t1, freq);
    g_pipe.stats.total_upload_hud_ms += upload_ms;
    g_pipe.stats.hud_upload_api_ms   += upload_ms;

    // 2A Record HUD upload sample and overlap classification
    if (g_pipe.contention_instrumentation_enabled) {
        if (g_pipe.num_hud_samples < 4096) {
            g_pipe.hud_samples_buffer[g_pipe.num_hud_samples] = upload_ms;
        }
        g_pipe.num_hud_samples++;
        if (was_overlap) {
            g_pipe.hud_overlap_sum += upload_ms;
            g_pipe.hud_overlap_count++;
        } else {
            g_pipe.hud_non_overlap_sum += upload_ms;
            g_pipe.hud_non_overlap_count++;
        }
    }

    // 4. Early drain: If not late drain and pending encode queue reached watermark, sync oldest frame first
    if (!g_pipe.late_drain_enabled) {
        while (g_pipe.pending_encode_count >= g_pipe.app_drain_watermark) {
            sync_oldest_encode_slot(&g_pipe);
        }
    }

    // Sample encoder pending occupancy
    int p_cnt = g_pipe.pending_encode_count;
    if (p_cnt >= 0 && p_cnt <= 16) {
        g_pipe.stats.enc_pending_counts[p_cnt]++;
        g_pipe.stats.enc_pending_samples++;
    }

    // 5. Get oneVPL Surface FIRST
    mfxFrameSurface1* pmfxSurface = NULL;
    mfxStatus sts = g_pipe.pMFXMemory_GetSurfaceForEncode(g_pipe.session, &pmfxSurface);
    if (sts != MFX_ERR_NONE || !pmfxSurface) {
        g_pipe.stats.surface_starvations++;
        g_pipe.stats.encoder_surface_starvations++;
        sync_oldest_encode_slot(&g_pipe);
        sts = g_pipe.pMFXMemory_GetSurfaceForEncode(g_pipe.session, &pmfxSurface);
        if (sts != MFX_ERR_NONE || !pmfxSurface) return -3;
    }

    mfxHDL hSurfRes = NULL;
    mfxResourceType rType = 0;
    pmfxSurface->FrameInterface->GetNativeHandle(pmfxSurface, &hSurfRes, &rType);
    ID3D11Texture2D* pEncTex = (ID3D11Texture2D*)hSurfRes;

    ID3D11VideoProcessorOutputView* pTargetOutView = g_pipe.pVPOutView;

    if (g_pipe.use_direct_vp_surface && pEncTex) {
        ID3D11VideoProcessorOutputView* pDirectView = NULL;
        for (int i = 0; i < g_pipe.num_cached_out_views; i++) {
            if (g_pipe.cached_out_views[i].pTex == pEncTex) {
                pDirectView = g_pipe.cached_out_views[i].pVPOutView;
                break;
            }
        }
        if (!pDirectView && g_pipe.num_cached_out_views < MAX_CACHED_SURFACE_VIEWS) {
            D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC ovDesc = {0};
            ovDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
            HRESULT hr_view = ID3D11VideoDevice_CreateVideoProcessorOutputView(
                g_pipe.pVideoDevice,
                (ID3D11Resource*)pEncTex,
                g_pipe.pEnum,
                &ovDesc,
                &pDirectView
            );
            if (SUCCEEDED(hr_view) && pDirectView) {
                g_pipe.cached_out_views[g_pipe.num_cached_out_views].pTex = pEncTex;
                g_pipe.cached_out_views[g_pipe.num_cached_out_views].pVPOutView = pDirectView;
                g_pipe.num_cached_out_views++;
            } else {
                // 1D.1 Diagnostic: capture HRESULT of first failure
                if (g_pipe.stats.direct_vp_first_fail_hr == 0) {
                    g_pipe.stats.direct_vp_first_fail_hr = (int)(DWORD)hr_view;
                    printf("[STREAM INTEL] DIRECT_VP_SURFACE: CreateVideoProcessorOutputView FAILED"
                           " hr=0x%08lX frame=%d (will use CopyResource fallback)\n",
                           (unsigned long)(DWORD)hr_view, g_pipe.stats.decoded_frames);
                }
            }
        }
        if (pDirectView) {
            pTargetOutView = pDirectView;
        }
    }

    // 6. VideoProcessorBlt directly to target output view
    QueryPerformanceCounter(&t0);
    D3D11_VIDEO_PROCESSOR_STREAM streams[2] = {0};
    streams[0].Enable = TRUE;
    if (g_pipe.hw_decode_active && g_pipe.current_dec_input_view) {
        streams[0].pInputSurface = g_pipe.current_dec_input_view;
    } else if (g_pipe.use_dual_device && g_pipe.decode_ring[read_slot].pBaseInputViewB) {
        streams[0].pInputSurface = g_pipe.decode_ring[read_slot].pBaseInputViewB;
    } else {
        streams[0].pInputSurface = g_pipe.pBaseInputView;
    }
    streams[1].Enable = TRUE;
    streams[1].pInputSurface = g_pipe.pHudInputView;
    ID3D11VideoContext_VideoProcessorBlt(g_pipe.pVideoContext, g_pipe.pVP, pTargetOutView, 0, 2, streams);
    QueryPerformanceCounter(&t1);
    g_pipe.stats.total_blt_ms += get_time_ms(t0, t1, freq);

    if (g_pipe.hw_decode_active) {
        if (g_pipe.decode_ring[read_slot].pAvFrame) {
            av_frame_unref(g_pipe.decode_ring[read_slot].pAvFrame);
        }
        g_pipe.current_dec_input_view = NULL;
    }

    // Release decode ring slot back to producer (after Blt and unref)
    int ring_limit = (g_pipe.use_dual_device && g_pipe.shared_ring_slots > 0) ? g_pipe.shared_ring_slots : DECODE_RING_SIZE;
    EnterCriticalSection(&g_pipe.csDecode);
    g_pipe.decode_ring[read_slot].is_ready = false;
    g_pipe.decode_tail_idx = (g_pipe.decode_tail_idx + 1) % ring_limit;
    g_pipe.decode_queued_count--;
    WakeConditionVariable(&g_pipe.cvDecodeFree);
    LeaveCriticalSection(&g_pipe.csDecode);

    // Fallback CopyResource only if direct VP surface was not used
    if (pTargetOutView == g_pipe.pVPOutView) {
        QueryPerformanceCounter(&t0);
        ID3D11DeviceContext_CopyResource(g_pipe.pContext, (ID3D11Resource*)pEncTex, (ID3D11Resource*)g_pipe.pVPOutTex);
        QueryPerformanceCounter(&t1);
        g_pipe.stats.total_dma_copy_ms += get_time_ms(t0, t1, freq);
        g_pipe.stats.vp_to_encoder_gpu_copy_count++;
    }

    // End Consumer D3D11 window
    if (g_pipe.contention_instrumentation_enabled) {
        InterlockedExchange(&g_pipe.consumer_in_d3d11, 0);
    }

    // Late drain: If late drain enabled, sync oldest slot before submitting current frame to slot
    if (g_pipe.late_drain_enabled) {
        while (g_pipe.pending_encode_count >= g_pipe.app_drain_watermark) {
            sync_oldest_encode_slot(&g_pipe);
        }
    }

    // 7. Submit EncodeFrameAsync into slot
    int cur_slot = g_pipe.enc_head_idx;
    g_pipe.encode_pool[cur_slot].bs.DataLength = 0;
    g_pipe.encode_pool[cur_slot].bs.DataOffset = 0;
    g_pipe.encode_pool[cur_slot].syncp = NULL;

    QueryPerformanceCounter(&t0);
    int retries = 0;
    while (true) {
        sts = g_pipe.pMFXVideoENCODE_EncodeFrameAsync(
            g_pipe.session,
            NULL,
            pmfxSurface,
            &g_pipe.encode_pool[cur_slot].bs,
            &g_pipe.encode_pool[cur_slot].syncp
        );
        if (sts == MFX_WRN_DEVICE_BUSY) {
            g_pipe.stats.device_busy_retries++;
            g_pipe.stats.mfx_device_busy_count++;
            retries++;
            if (retries > 100) {
                Sleep(1);
            }
            if (retries > 500) break;
            continue;
        }
        break;
    }
    if (sts == MFX_ERR_MORE_SURFACE) {
        g_pipe.stats.mfx_more_surface_count++;
    } else if (sts == MFX_ERR_MORE_DATA) {
        g_pipe.stats.mfx_more_data_count++;
    } else if (sts != MFX_ERR_NONE && sts != MFX_WRN_DEVICE_BUSY) {
        g_pipe.stats.mfx_err_other_count++;
    }
    pmfxSurface->FrameInterface->Release(pmfxSurface);
    QueryPerformanceCounter(&t1);
    double submit_ms = get_time_ms(t0, t1, freq);
    g_pipe.stats.total_submit_ms += submit_ms;
    g_pipe.stats.total_encode_ms += submit_ms;

    if (sts == MFX_ERR_NONE) {
        g_pipe.stats.submitted_frames++;
        if (g_pipe.encode_pool[cur_slot].syncp != NULL) {
            g_pipe.encode_pool[cur_slot].in_use = true;
            g_pipe.enc_head_idx = (g_pipe.enc_head_idx + 1) % g_pipe.pool_size;
            g_pipe.pending_encode_count++;
            if (g_pipe.pending_encode_count > g_pipe.stats.max_pending_frames) {
                g_pipe.stats.max_pending_frames = g_pipe.pending_encode_count;
            }
        }
    }

    g_pipe.stats.decoded_frames++;
    QueryThreadCycleTime(hCurThread, &cons_c1);
    g_pipe.stats.total_consumer_cycles += (cons_c1 - cons_c0);
    return 0;
}

__declspec(dllexport) int intel_native_pipeline_step(
    const uint8_t* hud_rgba_buffer,
    int64_t* out_pts,
    double* out_pts_sec
) {
    return intel_native_pipeline_step_regions(hud_rgba_buffer, NULL, 0, out_pts, out_pts_sec);
}

__declspec(dllexport) int intel_native_pipeline_finish(void) {
    if (!g_pipe.pipeline_open) return 0;

    // 1. Stop decode producer thread
    EnterCriticalSection(&g_pipe.csDecode);
    g_pipe.bStopDecode = true;
    WakeConditionVariable(&g_pipe.cvDecodeFree);
    WakeConditionVariable(&g_pipe.cvDecodeReady);
    LeaveCriticalSection(&g_pipe.csDecode);

    if (g_pipe.hDecodeThread) {
        WaitForSingleObject(g_pipe.hDecodeThread, 5000);
        CloseHandle(g_pipe.hDecodeThread);
        g_pipe.hDecodeThread = NULL;
    }

    // 2. Drain oneVPL encoder
    while (true) {
        while (g_pipe.pending_encode_count >= g_pipe.pool_size) {
            sync_oldest_encode_slot(&g_pipe);
        }
        int cur_slot = g_pipe.enc_head_idx;
        g_pipe.encode_pool[cur_slot].bs.DataLength = 0;
        g_pipe.encode_pool[cur_slot].bs.DataOffset = 0;
        g_pipe.encode_pool[cur_slot].syncp = NULL;

        mfxStatus sts = g_pipe.pMFXVideoENCODE_EncodeFrameAsync(
            g_pipe.session,
            NULL,
            NULL, // Flush
            &g_pipe.encode_pool[cur_slot].bs,
            &g_pipe.encode_pool[cur_slot].syncp
        );

        if (sts == MFX_ERR_NONE && g_pipe.encode_pool[cur_slot].syncp) {
            g_pipe.encode_pool[cur_slot].in_use = true;
            g_pipe.enc_head_idx = (g_pipe.enc_head_idx + 1) % g_pipe.pool_size;
            g_pipe.pending_encode_count++;
            if (g_pipe.pending_encode_count > g_pipe.stats.max_pending_frames) {
                g_pipe.stats.max_pending_frames = g_pipe.pending_encode_count;
            }
        } else {
            break;
        }
    }

    // 3. Sync all remaining active slots
    while (g_pipe.pending_encode_count > 0) {
        sync_oldest_encode_slot(&g_pipe);
    }

    QueryPerformanceCounter(&g_pipe.t_pipe_end);
    if (g_pipe.fOutIVF) {
        fclose(g_pipe.fOutIVF);
        g_pipe.fOutIVF = NULL;
    }

    g_pipe.stats.total_wall_ms = get_time_ms(g_pipe.t_pipe_start, g_pipe.t_pipe_end, g_pipe.freq);
    if (g_pipe.stats.total_wall_ms > 0.0) {
        g_pipe.stats.pipeline_fps = (double)g_pipe.stats.decoded_frames / (g_pipe.stats.total_wall_ms / 1000.0);
    }
    if (g_pipe.stats.decoded_frames > 0) {
        double duration_sec = (double)g_pipe.stats.decoded_frames * (1001.0 / 30000.0);
        g_pipe.stats.avg_bitrate_mbps = ((double)g_pipe.stats.total_bytes_encoded * 8.0 / duration_sec) / 1000000.0;
    }

    g_pipe.stats.hevc_hw_decode_active = g_pipe.hw_decode_active ? 1 : 0;
    g_pipe.stats.d3d11_hevc_main10_active = g_pipe.hw_decode_active ? 1 : 0;
    g_pipe.stats.hevc_hw_encode_active = (g_pipe.codec_id == INTEL_CODEC_HEVC) ? 1 : 0;
    g_pipe.stats.decoder_surface_count = g_pipe.num_cached_decode_views;
    g_pipe.stats.encoder_surface_count = g_pipe.num_cached_out_views;
    g_pipe.stats.queue_depth = g_pipe.decode_queued_count;
    g_pipe.stats.device_lost_count = 0;
    if (g_pipe.stats.hud_full_bytes > 0) {
        g_pipe.stats.hud_dirty_area_percent = ((double)g_pipe.stats.hud_dirty_bytes / (double)g_pipe.stats.hud_full_bytes) * 100.0;
    }

    if (g_pipe.stats.map_samples > 0) {
        int n_s = (g_pipe.stats.map_samples < 4096) ? g_pipe.stats.map_samples : 4096;
        qsort(g_pipe.map_samples_buffer, n_s, sizeof(double), cmp_dbl_asc);
        g_pipe.stats.map_p50_ms = g_pipe.map_samples_buffer[(int)(n_s * 0.50)];
        g_pipe.stats.map_p90_ms = g_pipe.map_samples_buffer[(int)(n_s * 0.90)];
        g_pipe.stats.map_p95_ms = g_pipe.map_samples_buffer[(int)(n_s * 0.95)];
        g_pipe.stats.map_p99_ms = g_pipe.map_samples_buffer[(int)(n_s * 0.99)];
    }

    if (g_pipe.num_sync_samples > 0) {
        int n_s = (g_pipe.num_sync_samples < 4096) ? g_pipe.num_sync_samples : 4096;
        qsort(g_pipe.sync_samples_buffer, n_s, sizeof(double), cmp_dbl_asc);
        g_pipe.stats.sync_p50_ms = g_pipe.sync_samples_buffer[(int)(n_s * 0.50)];
        g_pipe.stats.sync_p90_ms = g_pipe.sync_samples_buffer[(int)(n_s * 0.90)];
        g_pipe.stats.sync_p95_ms = g_pipe.sync_samples_buffer[(int)(n_s * 0.95)];
        g_pipe.stats.sync_p99_ms = g_pipe.sync_samples_buffer[(int)(n_s * 0.99)];
    }

    // 2A HUD Upload Percentiles & Contention Distributions
    if (g_pipe.num_hud_samples > 0) {
        int n_s = (g_pipe.num_hud_samples < 4096) ? g_pipe.num_hud_samples : 4096;
        qsort(g_pipe.hud_samples_buffer, n_s, sizeof(double), cmp_dbl_asc);
        g_pipe.stats.hud_upload_p50_ms = g_pipe.hud_samples_buffer[(int)(n_s * 0.50)];
        g_pipe.stats.hud_upload_p90_ms = g_pipe.hud_samples_buffer[(int)(n_s * 0.90)];
        g_pipe.stats.hud_upload_p95_ms = g_pipe.hud_samples_buffer[(int)(n_s * 0.95)];
        g_pipe.stats.hud_upload_p99_ms = g_pipe.hud_samples_buffer[(int)(n_s * 0.99)];
    }
    g_pipe.stats.hud_upload_overlap_count = g_pipe.hud_overlap_count;
    g_pipe.stats.hud_upload_non_overlap_count = g_pipe.hud_non_overlap_count;
    if (g_pipe.hud_overlap_count > 0) {
        g_pipe.stats.hud_upload_with_overlap_ms = g_pipe.hud_overlap_sum / (double)g_pipe.hud_overlap_count;
    }
    if (g_pipe.hud_non_overlap_count > 0) {
        g_pipe.stats.hud_upload_without_overlap_ms = g_pipe.hud_non_overlap_sum / (double)g_pipe.hud_non_overlap_count;
    }
    g_pipe.stats.total_producer_d3d11_window_ms = g_pipe.total_producer_d3d11_ms;

    // FIRST: Release child D3D11 views BEFORE destroying their parent surfaces/contexts
    for (int i = 0; i < g_pipe.num_cached_decode_views; i++) {
        if (g_pipe.cached_decode_views[i].pInputView) {
            ID3D11VideoProcessorInputView_Release(g_pipe.cached_decode_views[i].pInputView);
            g_pipe.cached_decode_views[i].pInputView = NULL;
        }
        g_pipe.cached_decode_views[i].pTex = NULL;
    }
    g_pipe.num_cached_decode_views = 0;

    for (int i = 0; i < g_pipe.num_cached_out_views; i++) {
        if (g_pipe.cached_out_views[i].pVPOutView) {
            ID3D11VideoProcessorOutputView_Release(g_pipe.cached_out_views[i].pVPOutView);
            g_pipe.cached_out_views[i].pVPOutView = NULL;
        }
        g_pipe.cached_out_views[i].pTex = NULL;
    }
    g_pipe.num_cached_out_views = 0;

    // Cleanup Decode Ring resources
    for (int i = 0; i < DECODE_RING_SIZE; i++) {
        if (g_pipe.decode_ring[i].pBaseInputViewB) {
            ID3D11VideoProcessorInputView_Release(g_pipe.decode_ring[i].pBaseInputViewB);
            g_pipe.decode_ring[i].pBaseInputViewB = NULL;
        }
        if (g_pipe.decode_ring[i].pKeyedMutexB) {
            IDXGIKeyedMutex_Release(g_pipe.decode_ring[i].pKeyedMutexB);
            g_pipe.decode_ring[i].pKeyedMutexB = NULL;
        }
        if (g_pipe.decode_ring[i].pOpenedBaseTexB) {
            ID3D11Texture2D_Release(g_pipe.decode_ring[i].pOpenedBaseTexB);
            g_pipe.decode_ring[i].pOpenedBaseTexB = NULL;
        }
        g_pipe.decode_ring[i].hSharedHandle = NULL;
        if (g_pipe.decode_ring[i].pKeyedMutexA) {
            IDXGIKeyedMutex_Release(g_pipe.decode_ring[i].pKeyedMutexA);
            g_pipe.decode_ring[i].pKeyedMutexA = NULL;
        }
        if (g_pipe.decode_ring[i].pSharedBaseTexA) {
            ID3D11Texture2D_Release(g_pipe.decode_ring[i].pSharedBaseTexA);
            g_pipe.decode_ring[i].pSharedBaseTexA = NULL;
        }
        if (g_pipe.decode_ring[i].pStagingTex) {
            ID3D11Texture2D_Release(g_pipe.decode_ring[i].pStagingTex);
            g_pipe.decode_ring[i].pStagingTex = NULL;
        }
        if (g_pipe.decode_ring[i].p010_data) {
            _aligned_free(g_pipe.decode_ring[i].p010_data);
            g_pipe.decode_ring[i].p010_data = NULL;
        }
        if (g_pipe.decode_ring[i].pAvFrame) {
            av_frame_free(&g_pipe.decode_ring[i].pAvFrame);
            g_pipe.decode_ring[i].pAvFrame = NULL;
        }
    }
    DeleteCriticalSection(&g_pipe.csDecode);

    if (g_pipe.frame) { av_frame_free(&g_pipe.frame); g_pipe.frame = NULL; }
    if (g_pipe.pkt) { av_packet_free(&g_pipe.pkt); g_pipe.pkt = NULL; }
    if (g_pipe.dec_ctx) { avcodec_free_context(&g_pipe.dec_ctx); g_pipe.dec_ctx = NULL; }
    if (g_pipe.fmt_ctx) { avformat_close_input(&g_pipe.fmt_ctx); g_pipe.fmt_ctx = NULL; }

    if (g_pipe.hw_device_ctx) {
        av_buffer_unref(&g_pipe.hw_device_ctx);
        g_pipe.hw_device_ctx = NULL;
    }

    // Cleanup oneVPL resources
    for (int i = 0; i < g_pipe.pool_size; i++) {
        if (g_pipe.encode_pool[i].pBsBuffer) {
            free(g_pipe.encode_pool[i].pBsBuffer);
            g_pipe.encode_pool[i].pBsBuffer = NULL;
        }
    }
    if (g_pipe.session) { g_pipe.pMFXClose(g_pipe.session); g_pipe.session = NULL; }
    if (g_pipe.loader) { g_pipe.pMFXUnload(g_pipe.loader); g_pipe.loader = NULL; }

    intel_d3d11_vp_cleanup();

    if (g_pipe.hVpl) { FreeLibrary(g_pipe.hVpl); g_pipe.hVpl = NULL; }

    g_pipe.pipeline_open = false;
    return 0;
}

__declspec(dllexport) void intel_native_pipeline_cancel(void) {
    g_pipe.cancelled = true;
    intel_native_pipeline_finish();
}

__declspec(dllexport) int intel_native_pipeline_get_stats(IntelNativePipelineStats* out_stats) {
    if (!out_stats) return -1;
    if (g_pipe.pDevice) {
        g_pipe.stats.d3d11_device_removed_reason = (int)ID3D11Device_GetDeviceRemovedReason(g_pipe.pDevice);
        if (g_pipe.stats.d3d11_device_removed_reason != 0) {
            g_pipe.stats.device_lost_count++;
        }
    }
    memcpy(out_stats, &g_pipe.stats, sizeof(IntelNativePipelineStats));
    return 0;
}

// =========================================================================
// 7G BENCHMARK & CAPACITY SUITE EXPORTS
// =========================================================================

typedef struct {
    double p010_pack_ms;
    double ram_handoff_ms;
    double update_subresource_ms;
    double gpu_ready_ms;
    double total_base_path_ms;
} ProductionBasePathResults;

__declspec(dllexport) int intel_native_measure_production_base_path(int n_frames, ProductionBasePathResults* out_res) {
    if (!out_res || n_frames <= 0) return -1;
    memset(out_res, 0, sizeof(ProductionBasePathResults));

    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);
    LARGE_INTEGER t0, t1;

    int ret = intel_d3d11_vp_init();
    if (ret != 0) return ret;

    size_t y_elems = BASE_W * BASE_H;
    size_t uv_elems = (BASE_W / 2) * (BASE_H / 2);
    uint16_t* src_y = (uint16_t*)_aligned_malloc(y_elems * 2, 64);
    uint16_t* src_u = (uint16_t*)_aligned_malloc(uv_elems * 2, 64);
    uint16_t* src_v = (uint16_t*)_aligned_malloc(uv_elems * 2, 64);
    for (size_t i = 0; i < y_elems; i++) src_y[i] = (uint16_t)(i % 1024);
    for (size_t i = 0; i < uv_elems; i++) {
        src_u[i] = (uint16_t)((i * 3) % 1024);
        src_v[i] = (uint16_t)((i * 7) % 1024);
    }

    size_t p010_bytes = (BASE_W * BASE_H * 2) + (BASE_W * (BASE_H / 2) * 2);
    uint8_t* p010_scratch = (uint8_t*)_aligned_malloc(p010_bytes, 64);

    double total_pack = 0.0;
    double total_handoff = 0.0;
    double total_upload = 0.0;

    for (int i = 0; i < n_frames; i++) {
        QueryPerformanceCounter(&t0);
        yuv420p10le_to_p010_pitch(
            src_y, BASE_W * 2,
            src_u, (BASE_W / 2) * 2,
            src_v, (BASE_W / 2) * 2,
            p010_scratch, BASE_W * 2,
            BASE_W, BASE_H
        );
        QueryPerformanceCounter(&t1);
        total_pack += get_time_ms(t0, t1, freq);

        QueryPerformanceCounter(&t0);
        // RAM handoff simulation (pointer assign & volatile check)
        volatile uint8_t* p = p010_scratch;
        (void)p;
        QueryPerformanceCounter(&t1);
        total_handoff += get_time_ms(t0, t1, freq);

        QueryPerformanceCounter(&t0);
        ID3D11DeviceContext_UpdateSubresource(g_pipe.pContext, (ID3D11Resource*)g_pipe.pBaseTex, 0, NULL, p010_scratch, BASE_W * 2, 0);
        QueryPerformanceCounter(&t1);
        total_upload += get_time_ms(t0, t1, freq);
    }

    out_res->p010_pack_ms = total_pack / n_frames;
    out_res->ram_handoff_ms = total_handoff / n_frames;
    out_res->update_subresource_ms = total_upload / n_frames;
    out_res->gpu_ready_ms = 0.0;
    out_res->total_base_path_ms = (total_pack + total_handoff + total_upload) / n_frames;

    _aligned_free(src_y);
    _aligned_free(src_u);
    _aligned_free(src_v);
    _aligned_free(p010_scratch);
    intel_d3d11_vp_cleanup();
    return 0;
}

typedef struct {
    double hud_acquire_ms;
    double hud_cpu_copy_ms;
    double hud_update_subresource_ms;
    double hud_gpu_ready_ms;
    double total_hud_transfer_ms;
    int copy_count;
    size_t hud_bytes;
    int api_calls;
} HudPathResults;

__declspec(dllexport) int intel_native_measure_hud_path(int n_frames, HudPathResults* out_res) {
    if (!out_res || n_frames <= 0) return -1;
    memset(out_res, 0, sizeof(HudPathResults));

    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);
    LARGE_INTEGER t0, t1;

    int ret = intel_d3d11_vp_init();
    if (ret != 0) return ret;

    size_t hud_bytes = HUD_W * HUD_H * 4; // 14,745,600 bytes
    uint8_t* hud_buf = (uint8_t*)malloc(hud_bytes);
    memset(hud_buf, 0x80, hud_bytes);

    double total_acquire = 0.0;
    double total_upload = 0.0;

    for (int i = 0; i < n_frames; i++) {
        QueryPerformanceCounter(&t0);
        // Shared memory pointer access (zero memcpy)
        volatile uint8_t* p = hud_buf;
        (void)p;
        QueryPerformanceCounter(&t1);
        total_acquire += get_time_ms(t0, t1, freq);

        QueryPerformanceCounter(&t0);
        ID3D11DeviceContext_UpdateSubresource(g_pipe.pContext, (ID3D11Resource*)g_pipe.pHudTex, 0, NULL, hud_buf, HUD_W * 4, 0);
        QueryPerformanceCounter(&t1);
        total_upload += get_time_ms(t0, t1, freq);
    }

    out_res->hud_acquire_ms = total_acquire / n_frames;
    out_res->hud_cpu_copy_ms = 0.0; // 0 memcpy before UpdateSubresource
    out_res->hud_update_subresource_ms = total_upload / n_frames;
    out_res->hud_gpu_ready_ms = 0.0;
    out_res->total_hud_transfer_ms = (total_acquire + total_upload) / n_frames;
    out_res->copy_count = 0; // zero CPU copies
    out_res->hud_bytes = hud_bytes;
    out_res->api_calls = n_frames;

    free(hud_buf);
    intel_d3d11_vp_cleanup();
    return 0;
}

typedef struct {
    double vp_cpu_submit_ms;
    double vp_gpu_exec_ms;
    double vp_wait_ms;
    double vp_resource_stall_ms;
} VPTimingResults;

__declspec(dllexport) int intel_native_measure_vp_timing(int n_frames, VPTimingResults* out_res) {
    if (!out_res || n_frames <= 0) return -1;
    memset(out_res, 0, sizeof(VPTimingResults));

    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);
    LARGE_INTEGER t0, t1;

    int ret = intel_d3d11_vp_init();
    if (ret != 0) return ret;

    // Create D3D11 Timestamp Queries for precise GPU hardware execution measurement
    D3D11_QUERY_DESC qDesc = { D3D11_QUERY_TIMESTAMP_DISJOINT, 0 };
    ID3D11Query* pDisjoint = NULL;
    ID3D11Device_CreateQuery(g_pipe.pDevice, &qDesc, &pDisjoint);

    qDesc.Query = D3D11_QUERY_TIMESTAMP;
    ID3D11Query* pStart = NULL;
    ID3D11Query* pEnd = NULL;
    ID3D11Device_CreateQuery(g_pipe.pDevice, &qDesc, &pStart);
    ID3D11Device_CreateQuery(g_pipe.pDevice, &qDesc, &pEnd);

    // Warm up
    D3D11_VIDEO_PROCESSOR_STREAM streams[2] = {0};
    streams[0].Enable = TRUE;
    streams[0].pInputSurface = g_pipe.pBaseInputView;
    streams[1].Enable = TRUE;
    streams[1].pInputSurface = g_pipe.pHudInputView;

    for (int i = 0; i < 5; i++) {
        ID3D11VideoContext_VideoProcessorBlt(g_pipe.pVideoContext, g_pipe.pVP, g_pipe.pVPOutView, 0, 2, streams);
    }

    double total_cpu_submit = 0.0;
    double total_gpu_exec = 0.0;
    double total_wait = 0.0;
    int valid_gpu_samples = 0;

    for (int i = 0; i < n_frames; i++) {
        ID3D11DeviceContext_Begin(g_pipe.pContext, (ID3D11Asynchronous*)pDisjoint);
        ID3D11DeviceContext_End(g_pipe.pContext, (ID3D11Asynchronous*)pStart);

        QueryPerformanceCounter(&t0);
        ID3D11VideoContext_VideoProcessorBlt(g_pipe.pVideoContext, g_pipe.pVP, g_pipe.pVPOutView, 0, 2, streams);
        QueryPerformanceCounter(&t1);
        total_cpu_submit += get_time_ms(t0, t1, freq);

        ID3D11DeviceContext_End(g_pipe.pContext, (ID3D11Asynchronous*)pEnd);
        ID3D11DeviceContext_End(g_pipe.pContext, (ID3D11Asynchronous*)pDisjoint);

        QueryPerformanceCounter(&t0);
        D3D11_QUERY_DATA_TIMESTAMP_DISJOINT disjointData;
        while (ID3D11DeviceContext_GetData(g_pipe.pContext, (ID3D11Asynchronous*)pDisjoint, &disjointData, sizeof(disjointData), 0) == S_FALSE) {}
        UINT64 startTime = 0, endTime = 0;
        while (ID3D11DeviceContext_GetData(g_pipe.pContext, (ID3D11Asynchronous*)pStart, &startTime, sizeof(startTime), 0) == S_FALSE) {}
        while (ID3D11DeviceContext_GetData(g_pipe.pContext, (ID3D11Asynchronous*)pEnd, &endTime, sizeof(endTime), 0) == S_FALSE) {}
        QueryPerformanceCounter(&t1);
        total_wait += get_time_ms(t0, t1, freq);

        if (!disjointData.Disjoint && disjointData.Frequency > 0 && endTime >= startTime) {
            double gpu_ms = (double)(endTime - startTime) * 1000.0 / (double)disjointData.Frequency;
            total_gpu_exec += gpu_ms;
            valid_gpu_samples++;
        }
    }

    out_res->vp_cpu_submit_ms = total_cpu_submit / n_frames;
    out_res->vp_gpu_exec_ms = valid_gpu_samples > 0 ? (total_gpu_exec / valid_gpu_samples) : 0.0;
    out_res->vp_wait_ms = total_wait / n_frames;
    out_res->vp_resource_stall_ms = 0.0;

    if (pStart) ID3D11Query_Release(pStart);
    if (pEnd) ID3D11Query_Release(pEnd);
    if (pDisjoint) ID3D11Query_Release(pDisjoint);
    intel_d3d11_vp_cleanup();
    return 0;
}

typedef struct {
    double encoder_fps;
    double avg_pending_surfaces;
    int max_pending_surfaces;
    int surface_starvations;
    int device_busy_retries;
    double total_wall_ms;
    int encoded_frames;
} EncoderCapacityResults;

__declspec(dllexport) void intel_native_query_capabilities(IntelCapabilityInfo* out_caps) {
    if (!out_caps) return;
    memset(out_caps, 0, sizeof(IntelCapabilityInfo));
    out_caps->av1_available = 1;
    out_caps->av1_10bit = 1;
    out_caps->h264_available = 1;
    out_caps->h264_8bit = 1;
    out_caps->h264_10bit = 0; // Hardware encoder does not support 10-bit P010 AVC on Meteor Lake 135U
    const char* env_hevc_cap = getenv("TELEM_INTEL_HEVC_CAPABILITY");
    if (env_hevc_cap && strcmp(env_hevc_cap, "1") == 0) {
        out_caps->hevc_available = 1;
        out_caps->hevc_10bit = 1;
    } else {
        out_caps->hevc_available = 0; // 135U historical baseline
        out_caps->hevc_10bit = 0;
    }
}

__declspec(dllexport) int intel_native_measure_encoder_capacity_ex(int n_frames, int codec_id, EncoderCapacityResults* out_res) {
    if (!out_res || n_frames <= 0) return -1;
    memset(out_res, 0, sizeof(EncoderCapacityResults));

    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);

    int ret = intel_d3d11_vp_init_ex(codec_id);
    if (ret != 0) return ret;

    // Load oneVPL
    HMODULE hVpl = LoadLibraryA("libvpl.dll");
    if (!hVpl) { intel_d3d11_vp_cleanup(); return -10; }

    mfxCreateLoader_fn pMFXLoad = (mfxCreateLoader_fn)GetProcAddress(hVpl, "MFXLoad");
    mfxCreateConfig_fn pMFXCreateConfig = (mfxCreateConfig_fn)GetProcAddress(hVpl, "MFXCreateConfig");
    mfxSetConfigFilterProperty_fn pMFXSetConfigFilterProperty = (mfxSetConfigFilterProperty_fn)GetProcAddress(hVpl, "MFXSetConfigFilterProperty");
    mfxCreateSession_fn pMFXCreateSession = (mfxCreateSession_fn)GetProcAddress(hVpl, "MFXCreateSession");
    mfxUnload_fn pMFXUnload = (mfxUnload_fn)GetProcAddress(hVpl, "MFXUnload");
    mfxClose_fn pMFXClose = (mfxClose_fn)GetProcAddress(hVpl, "MFXClose");
    mfxVideoCORE_SetHandle_fn pMFXVideoCORE_SetHandle = (mfxVideoCORE_SetHandle_fn)GetProcAddress(hVpl, "MFXVideoCORE_SetHandle");
    mfxVideoENCODE_Init_fn pMFXVideoENCODE_Init = (mfxVideoENCODE_Init_fn)GetProcAddress(hVpl, "MFXVideoENCODE_Init");
    mfxVideoENCODE_Close_fn pMFXVideoENCODE_Close = (mfxVideoENCODE_Close_fn)GetProcAddress(hVpl, "MFXVideoENCODE_Close");
    mfxMemory_GetSurfaceForEncode_fn pMFXMemory_GetSurfaceForEncode = (mfxMemory_GetSurfaceForEncode_fn)GetProcAddress(hVpl, "MFXMemory_GetSurfaceForEncode");
    mfxVideoENCODE_EncodeFrameAsync_fn pMFXVideoENCODE_EncodeFrameAsync = (mfxVideoENCODE_EncodeFrameAsync_fn)GetProcAddress(hVpl, "MFXVideoENCODE_EncodeFrameAsync");
    mfxVideoCORE_SyncOperation_fn pMFXVideoCORE_SyncOperation = (mfxVideoCORE_SyncOperation_fn)GetProcAddress(hVpl, "MFXVideoCORE_SyncOperation");

    mfxLoader loader = pMFXLoad();
    mfxConfig cfg = pMFXCreateConfig(loader);
    mfxVariant var;
    var.Type = MFX_VARIANT_TYPE_U32;
    var.Data.U32 = MFX_IMPL_TYPE_HARDWARE;
    pMFXSetConfigFilterProperty(cfg, (const mfxU8*)"mfxImplDescription.Impl", var);
    var.Data.U32 = MFX_ACCEL_MODE_VIA_D3D11;
    pMFXSetConfigFilterProperty(cfg, (const mfxU8*)"mfxImplDescription.AccelerationMode", var);
    var.Data.U32 = (codec_id == INTEL_CODEC_H264) ? MFX_CODEC_AVC : MFX_CODEC_AV1;
    pMFXSetConfigFilterProperty(cfg, (const mfxU8*)"mfxImplDescription.mfxEncoderDescription.encoder.CodecId", var);

    mfxSession session = NULL;
    pMFXCreateSession(loader, 0, &session);
    pMFXVideoCORE_SetHandle(session, MFX_HANDLE_D3D11_DEVICE, (mfxHDL)g_pipe.pDevice);

    mfxVideoParam initPar = {0};
    if (codec_id == INTEL_CODEC_H264) {
        initPar.mfx.CodecId = MFX_CODEC_AVC;
        initPar.mfx.CodecProfile = MFX_PROFILE_AVC_HIGH;
        initPar.mfx.CodecLevel = MFX_LEVEL_AVC_52;
        initPar.mfx.FrameInfo.FourCC = MFX_FOURCC_NV12;
        initPar.mfx.FrameInfo.BitDepthLuma = 8;
        initPar.mfx.FrameInfo.BitDepthChroma = 8;
        initPar.mfx.FrameInfo.Shift = 0;
    } else {
        initPar.mfx.CodecId = MFX_CODEC_AV1;
        initPar.mfx.CodecProfile = MFX_PROFILE_AV1_MAIN;
        initPar.mfx.CodecLevel = 0;
        initPar.mfx.FrameInfo.FourCC = MFX_FOURCC_P010;
        initPar.mfx.FrameInfo.BitDepthLuma = 10;
        initPar.mfx.FrameInfo.BitDepthChroma = 10;
        initPar.mfx.FrameInfo.Shift = 1;
    }
    initPar.mfx.TargetUsage = MFX_TARGETUSAGE_BEST_SPEED;
    initPar.mfx.TargetKbps = 40000;
    initPar.mfx.MaxKbps = 50000;
    initPar.mfx.BufferSizeInKB = 10000;
    initPar.mfx.InitialDelayInKB = 5000;
    initPar.mfx.BRCParamMultiplier = 1;
    initPar.mfx.RateControlMethod = MFX_RATECONTROL_VBR;
    initPar.mfx.GopPicSize = 60;
    initPar.mfx.GopRefDist = 1;
    initPar.mfx.FrameInfo.FrameRateExtN = 30000;
    initPar.mfx.FrameInfo.FrameRateExtD = 1001;
    initPar.mfx.FrameInfo.ChromaFormat = MFX_CHROMAFORMAT_YUV420;
    initPar.mfx.FrameInfo.PicStruct = MFX_PICSTRUCT_PROGRESSIVE;
    initPar.mfx.FrameInfo.Width = ((BASE_W + 15) >> 4) << 4;
    initPar.mfx.FrameInfo.Height = ((BASE_H + 15) >> 4) << 4;
    initPar.mfx.FrameInfo.CropW = BASE_W;
    initPar.mfx.FrameInfo.CropH = BASE_H;
    initPar.IOPattern = MFX_IOPATTERN_IN_VIDEO_MEMORY;
    initPar.AsyncDepth = 8;

    mfxStatus sts = pMFXVideoENCODE_Init(session, &initPar);
    if (sts != MFX_ERR_NONE) {
        pMFXClose(session);
        pMFXUnload(loader);
        FreeLibrary(hVpl);
        intel_d3d11_vp_cleanup();
        return -11;
    }

    EncodeSlot pool[ENCODE_POOL_SIZE];
    size_t bs_size = 16 * 1024 * 1024;
    for (int i = 0; i < ENCODE_POOL_SIZE; i++) {
        pool[i].pBsBuffer = (uint8_t*)malloc(bs_size);
        memset(&pool[i].bs, 0, sizeof(mfxBitstream));
        pool[i].bs.Data = pool[i].pBsBuffer;
        pool[i].bs.MaxLength = (uint32_t)bs_size;
        pool[i].syncp = NULL;
        pool[i].in_use = false;
        pool[i].frame_idx = -1;
    }

    int enc_head = 0;
    int enc_tail = 0;
    int pending_count = 0;
    int max_pending = 0;
    int starvations = 0;
    int busy_retries = 0;
    int encoded_count = 0;
    uint64_t pending_accum = 0;

    LARGE_INTEGER t_start, t_end;
    QueryPerformanceCounter(&t_start);

    for (int i = 0; i < n_frames; i++) {
        while (pending_count >= 8) {
            if (pool[enc_tail].in_use && pool[enc_tail].syncp) {
                pMFXVideoCORE_SyncOperation(session, pool[enc_tail].syncp, 60000);
                pool[enc_tail].syncp = NULL;
                pool[enc_tail].in_use = false;
                encoded_count++;
            }
            enc_tail = (enc_tail + 1) % ENCODE_POOL_SIZE;
            pending_count--;
        }

        mfxFrameSurface1* pmfxSurface = NULL;
        sts = pMFXMemory_GetSurfaceForEncode(session, &pmfxSurface);
        if (sts != MFX_ERR_NONE || !pmfxSurface) {
            starvations++;
            if (pool[enc_tail].in_use && pool[enc_tail].syncp) {
                pMFXVideoCORE_SyncOperation(session, pool[enc_tail].syncp, 60000);
                pool[enc_tail].syncp = NULL;
                pool[enc_tail].in_use = false;
                encoded_count++;
            }
            enc_tail = (enc_tail + 1) % ENCODE_POOL_SIZE;
            pending_count--;
            sts = pMFXMemory_GetSurfaceForEncode(session, &pmfxSurface);
        }

        if (!pmfxSurface) continue;

        pmfxSurface->Data.TimeStamp = (mfxU64)i * 33366;
        pool[enc_head].bs.DataLength = 0;
        pool[enc_head].bs.DataOffset = 0;
        pool[enc_head].syncp = NULL;

        int retries = 0;
        while (true) {
            sts = pMFXVideoENCODE_EncodeFrameAsync(session, NULL, pmfxSurface, &pool[enc_head].bs, &pool[enc_head].syncp);
            if (sts == MFX_WRN_DEVICE_BUSY) {
                busy_retries++;
                retries++;
                if (retries > 100) Sleep(1);
                if (retries > 500) break;
                continue;
            }
            break;
        }

        pmfxSurface->FrameInterface->Release(pmfxSurface);

        if (sts == MFX_ERR_NONE) {
            pool[enc_head].in_use = true;
            enc_head = (enc_head + 1) % ENCODE_POOL_SIZE;
            pending_count++;
            if (pending_count > max_pending) max_pending = pending_count;
        }
        pending_accum += pending_count;
    }

    // Drain
    while (true) {
        while (pending_count >= 8) {
            if (pool[enc_tail].in_use && pool[enc_tail].syncp) {
                pMFXVideoCORE_SyncOperation(session, pool[enc_tail].syncp, 60000);
                pool[enc_tail].syncp = NULL;
                pool[enc_tail].in_use = false;
                encoded_count++;
            }
            enc_tail = (enc_tail + 1) % ENCODE_POOL_SIZE;
            pending_count--;
        }

        pool[enc_head].bs.DataLength = 0;
        pool[enc_head].bs.DataOffset = 0;
        pool[enc_head].syncp = NULL;

        sts = pMFXVideoENCODE_EncodeFrameAsync(session, NULL, NULL, &pool[enc_head].bs, &pool[enc_head].syncp);
        if (sts == MFX_ERR_MORE_DATA) break;
        if (sts == MFX_ERR_NONE && pool[enc_head].syncp) {
            pool[enc_head].in_use = true;
            enc_head = (enc_head + 1) % ENCODE_POOL_SIZE;
            pending_count++;
            if (pending_count > max_pending) max_pending = pending_count;
        } else {
            break;
        }
    }

    // Flush remaining
    while (pending_count > 0) {
        if (pool[enc_tail].in_use && pool[enc_tail].syncp) {
            pMFXVideoCORE_SyncOperation(session, pool[enc_tail].syncp, 60000);
            pool[enc_tail].syncp = NULL;
            pool[enc_tail].in_use = false;
            encoded_count++;
        }
        enc_tail = (enc_tail + 1) % ENCODE_POOL_SIZE;
        pending_count--;
    }

    QueryPerformanceCounter(&t_end);
    double total_ms = get_time_ms(t_start, t_end, freq);

    out_res->encoder_fps = (total_ms > 0.0) ? ((double)encoded_count / (total_ms / 1000.0)) : 0.0;
    out_res->avg_pending_surfaces = (n_frames > 0) ? ((double)pending_accum / (double)n_frames) : 0.0;
    out_res->max_pending_surfaces = max_pending;
    out_res->surface_starvations = starvations;
    out_res->device_busy_retries = busy_retries;
    out_res->total_wall_ms = total_ms;
    out_res->encoded_frames = encoded_count;

    for (int i = 0; i < ENCODE_POOL_SIZE; i++) {
        free(pool[i].pBsBuffer);
    }

    pMFXVideoENCODE_Close(session);
    pMFXClose(session);
    pMFXUnload(loader);
    FreeLibrary(hVpl);
    intel_d3d11_vp_cleanup();
    return 0;
}

__declspec(dllexport) int intel_native_measure_encoder_capacity(int n_frames, EncoderCapacityResults* out_res) {
    return intel_native_measure_encoder_capacity_ex(n_frames, INTEL_CODEC_AV1, out_res);
}

typedef struct {
    double decode_only_fps;
    double decode_and_pack_fps;
    double total_decode_ms;
    double total_p010_ms;
    int decoded_frames;
} ProducerCapacityResults;

__declspec(dllexport) int intel_native_measure_producer_capacity(const char* video_path, int n_frames, ProducerCapacityResults* out_res) {
    if (!out_res || !video_path || n_frames <= 0) return -1;
    memset(out_res, 0, sizeof(ProducerCapacityResults));

    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);
    LARGE_INTEGER t0, t1, t_start, t_end;

    AVFormatContext* fmt = NULL;
    if (avformat_open_input(&fmt, video_path, NULL, NULL) < 0) return -20;
    avformat_find_stream_info(fmt, NULL);

    int v_idx = -1;
    for (unsigned int i = 0; i < fmt->nb_streams; i++) {
        if (fmt->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
            v_idx = i;
            break;
        }
    }
    if (v_idx < 0) { avformat_close_input(&fmt); return -21; }

    AVStream* st = fmt->streams[v_idx];
    const AVCodec* dec = avcodec_find_decoder(st->codecpar->codec_id);
    AVCodecContext* dec_ctx = avcodec_alloc_context3(dec);
    avcodec_parameters_to_context(dec_ctx, st->codecpar);
    const char* env_p_th = getenv("TELEM_INTEL_DECODER_THREADS");
    dec_ctx->thread_count = (env_p_th && atoi(env_p_th) > 0) ? atoi(env_p_th) : 0;
    if (avcodec_open2(dec_ctx, dec, NULL) < 0) {
        avcodec_free_context(&dec_ctx);
        avformat_close_input(&fmt);
        return -22;
    }

    AVPacket* pkt = av_packet_alloc();
    AVFrame* frame = av_frame_alloc();

    size_t p010_bytes = (BASE_W * BASE_H * 2) + (BASE_W * (BASE_H / 2) * 2);
    uint8_t* p010_scratch = (uint8_t*)_aligned_malloc(p010_bytes, 64);

    int frames_done = 0;
    double total_dec = 0.0;
    double total_pack = 0.0;

    QueryPerformanceCounter(&t_start);

    while (frames_done < n_frames) {
        QueryPerformanceCounter(&t0);
        int ret = avcodec_receive_frame(dec_ctx, frame);
        QueryPerformanceCounter(&t1);
        total_dec += get_time_ms(t0, t1, freq);

        if (ret == 0) {
            QueryPerformanceCounter(&t0);
            yuv420p10le_to_p010_pitch(
                (const uint16_t*)frame->data[0], frame->linesize[0],
                (const uint16_t*)frame->data[1], frame->linesize[1],
                (const uint16_t*)frame->data[2], frame->linesize[2],
                p010_scratch, BASE_W * 2,
                BASE_W, BASE_H
            );
            QueryPerformanceCounter(&t1);
            total_pack += get_time_ms(t0, t1, freq);

            av_frame_unref(frame);
            frames_done++;
        } else if (ret == AVERROR(EAGAIN)) {
            int read_ret = av_read_frame(fmt, pkt);
            if (read_ret < 0) {
                avcodec_send_packet(dec_ctx, NULL);
                continue;
            }
            if (pkt->stream_index == v_idx) {
                QueryPerformanceCounter(&t0);
                avcodec_send_packet(dec_ctx, pkt);
                QueryPerformanceCounter(&t1);
                total_dec += get_time_ms(t0, t1, freq);
            }
            av_packet_unref(pkt);
        } else if (ret == AVERROR_EOF) {
            break;
        } else {
            break;
        }
    }

    QueryPerformanceCounter(&t_end);
    double total_wall_ms = get_time_ms(t_start, t_end, freq);

    out_res->decoded_frames = frames_done;
    out_res->total_decode_ms = total_dec;
    out_res->total_p010_ms = total_pack;
    out_res->decode_only_fps = (total_dec > 0.0) ? ((double)frames_done / (total_dec / 1000.0)) : 0.0;
    out_res->decode_and_pack_fps = (total_wall_ms > 0.0) ? ((double)frames_done / (total_wall_ms / 1000.0)) : 0.0;

    _aligned_free(p010_scratch);
    av_frame_free(&frame);
    av_packet_free(&pkt);
    avcodec_free_context(&dec_ctx);
    avformat_close_input(&fmt);
    return 0;
}

typedef struct {
    double consumer_fps;
    double total_wall_ms;
    int processed_frames;
} ConsumerCapacityResults;

__declspec(dllexport) int intel_native_measure_consumer_capacity(int n_frames, ConsumerCapacityResults* out_res) {
    if (!out_res || n_frames <= 0) return -1;
    memset(out_res, 0, sizeof(ConsumerCapacityResults));

    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);

    int ret = intel_d3d11_vp_init();
    if (ret != 0) return ret;

    HMODULE hVpl = LoadLibraryA("libvpl.dll");
    if (!hVpl) { intel_d3d11_vp_cleanup(); return -10; }

    mfxCreateLoader_fn pMFXLoad = (mfxCreateLoader_fn)GetProcAddress(hVpl, "MFXLoad");
    mfxCreateConfig_fn pMFXCreateConfig = (mfxCreateConfig_fn)GetProcAddress(hVpl, "MFXCreateConfig");
    mfxSetConfigFilterProperty_fn pMFXSetConfigFilterProperty = (mfxSetConfigFilterProperty_fn)GetProcAddress(hVpl, "MFXSetConfigFilterProperty");
    mfxCreateSession_fn pMFXCreateSession = (mfxCreateSession_fn)GetProcAddress(hVpl, "MFXCreateSession");
    mfxUnload_fn pMFXUnload = (mfxUnload_fn)GetProcAddress(hVpl, "MFXUnload");
    mfxClose_fn pMFXClose = (mfxClose_fn)GetProcAddress(hVpl, "MFXClose");
    mfxVideoCORE_SetHandle_fn pMFXVideoCORE_SetHandle = (mfxVideoCORE_SetHandle_fn)GetProcAddress(hVpl, "MFXVideoCORE_SetHandle");
    mfxVideoENCODE_Init_fn pMFXVideoENCODE_Init = (mfxVideoENCODE_Init_fn)GetProcAddress(hVpl, "MFXVideoENCODE_Init");
    mfxMemory_GetSurfaceForEncode_fn pMFXMemory_GetSurfaceForEncode = (mfxMemory_GetSurfaceForEncode_fn)GetProcAddress(hVpl, "MFXMemory_GetSurfaceForEncode");
    mfxVideoENCODE_EncodeFrameAsync_fn pMFXVideoENCODE_EncodeFrameAsync = (mfxVideoENCODE_EncodeFrameAsync_fn)GetProcAddress(hVpl, "MFXVideoENCODE_EncodeFrameAsync");
    mfxVideoCORE_SyncOperation_fn pMFXVideoCORE_SyncOperation = (mfxVideoCORE_SyncOperation_fn)GetProcAddress(hVpl, "MFXVideoCORE_SyncOperation");

    mfxLoader loader = pMFXLoad();
    mfxConfig cfg = pMFXCreateConfig(loader);
    mfxVariant var;
    var.Type = MFX_VARIANT_TYPE_U32;
    var.Data.U32 = MFX_IMPL_TYPE_HARDWARE;
    pMFXSetConfigFilterProperty(cfg, (const mfxU8*)"mfxImplDescription.Impl", var);
    var.Data.U32 = MFX_ACCEL_MODE_VIA_D3D11;
    pMFXSetConfigFilterProperty(cfg, (const mfxU8*)"mfxImplDescription.AccelerationMode", var);

    mfxSession session = NULL;
    pMFXCreateSession(loader, 0, &session);
    pMFXVideoCORE_SetHandle(session, MFX_HANDLE_D3D11_DEVICE, (mfxHDL)g_pipe.pDevice);

    mfxVideoParam initPar = {0};
    initPar.mfx.CodecId = MFX_CODEC_AV1;
    initPar.mfx.CodecProfile = MFX_PROFILE_AV1_MAIN;
    initPar.mfx.TargetUsage = MFX_TARGETUSAGE_BEST_SPEED;
    initPar.mfx.TargetKbps = 40000;
    initPar.mfx.MaxKbps = 50000;
    initPar.mfx.BufferSizeInKB = 10000;
    initPar.mfx.InitialDelayInKB = 5000;
    initPar.mfx.BRCParamMultiplier = 1;
    initPar.mfx.RateControlMethod = MFX_RATECONTROL_VBR;
    initPar.mfx.GopPicSize = 60;
    initPar.mfx.GopRefDist = 1;
    initPar.mfx.FrameInfo.FrameRateExtN = 30000;
    initPar.mfx.FrameInfo.FrameRateExtD = 1001;
    initPar.mfx.FrameInfo.FourCC = MFX_FOURCC_P010;
    initPar.mfx.FrameInfo.ChromaFormat = MFX_CHROMAFORMAT_YUV420;
    initPar.mfx.FrameInfo.BitDepthLuma = 10;
    initPar.mfx.FrameInfo.BitDepthChroma = 10;
    initPar.mfx.FrameInfo.Shift = 1;
    initPar.mfx.FrameInfo.PicStruct = MFX_PICSTRUCT_PROGRESSIVE;
    initPar.mfx.FrameInfo.Width = ((BASE_W + 15) >> 4) << 4;
    initPar.mfx.FrameInfo.Height = ((BASE_H + 15) >> 4) << 4;
    initPar.mfx.FrameInfo.CropW = BASE_W;
    initPar.mfx.FrameInfo.CropH = BASE_H;
    initPar.IOPattern = MFX_IOPATTERN_IN_VIDEO_MEMORY;
    initPar.AsyncDepth = 8;

    pMFXVideoENCODE_Init(session, &initPar);

    EncodeSlot pool[ENCODE_POOL_SIZE];
    size_t bs_size = 16 * 1024 * 1024;
    for (int i = 0; i < ENCODE_POOL_SIZE; i++) {
        pool[i].pBsBuffer = (uint8_t*)malloc(bs_size);
        memset(&pool[i].bs, 0, sizeof(mfxBitstream));
        pool[i].bs.Data = pool[i].pBsBuffer;
        pool[i].bs.MaxLength = (uint32_t)bs_size;
        pool[i].syncp = NULL;
        pool[i].in_use = false;
        pool[i].frame_idx = -1;
    }

    size_t p010_bytes = (BASE_W * BASE_H * 2) + (BASE_W * (BASE_H / 2) * 2);
    uint8_t* p010_buf = (uint8_t*)_aligned_malloc(p010_bytes, 64);
    memset(p010_buf, 0x10, p010_bytes);

    size_t hud_bytes = HUD_W * HUD_H * 4;
    uint8_t* hud_buf = (uint8_t*)malloc(hud_bytes);
    memset(hud_buf, 0x80, hud_bytes);

    int enc_head = 0;
    int enc_tail = 0;
    int pending_count = 0;
    int frames_done = 0;

    D3D11_VIDEO_PROCESSOR_STREAM streams[2] = {0};
    streams[0].Enable = TRUE;
    streams[0].pInputSurface = g_pipe.pBaseInputView;
    streams[1].Enable = TRUE;
    streams[1].pInputSurface = g_pipe.pHudInputView;

    LARGE_INTEGER t_start, t_end;
    QueryPerformanceCounter(&t_start);

    for (int i = 0; i < n_frames; i++) {
        // 1. Base upload
        ID3D11DeviceContext_UpdateSubresource(g_pipe.pContext, (ID3D11Resource*)g_pipe.pBaseTex, 0, NULL, p010_buf, BASE_W * 2, 0);

        // 2. HUD upload
        ID3D11DeviceContext_UpdateSubresource(g_pipe.pContext, (ID3D11Resource*)g_pipe.pHudTex, 0, NULL, hud_buf, HUD_W * 4, 0);

        // 3. VideoProcessorBlt
        ID3D11VideoContext_VideoProcessorBlt(g_pipe.pVideoContext, g_pipe.pVP, g_pipe.pVPOutView, 0, 2, streams);

        // 4. Sync if needed
        while (pending_count >= 8) {
            if (pool[enc_tail].in_use && pool[enc_tail].syncp) {
                pMFXVideoCORE_SyncOperation(session, pool[enc_tail].syncp, 60000);
                pool[enc_tail].syncp = NULL;
                pool[enc_tail].in_use = false;
            }
            enc_tail = (enc_tail + 1) % ENCODE_POOL_SIZE;
            pending_count--;
        }

        // 5. Get encode surface & copy
        mfxFrameSurface1* pmfxSurface = NULL;
        mfxStatus sts = pMFXMemory_GetSurfaceForEncode(session, &pmfxSurface);
        if (sts != MFX_ERR_NONE || !pmfxSurface) {
            if (pool[enc_tail].in_use && pool[enc_tail].syncp) {
                pMFXVideoCORE_SyncOperation(session, pool[enc_tail].syncp, 60000);
                pool[enc_tail].syncp = NULL;
                pool[enc_tail].in_use = false;
            }
            enc_tail = (enc_tail + 1) % ENCODE_POOL_SIZE;
            pending_count--;
            sts = pMFXMemory_GetSurfaceForEncode(session, &pmfxSurface);
        }

        if (!pmfxSurface) continue;

        mfxHDL hSurfRes = NULL;
        mfxResourceType rType = 0;
        pmfxSurface->FrameInterface->GetNativeHandle(pmfxSurface, &hSurfRes, &rType);
        ID3D11Texture2D* pEncTex = (ID3D11Texture2D*)hSurfRes;

        ID3D11DeviceContext_CopyResource(g_pipe.pContext, (ID3D11Resource*)pEncTex, (ID3D11Resource*)g_pipe.pVPOutTex);

        // 6. Encode
        pool[enc_head].bs.DataLength = 0;
        pool[enc_head].bs.DataOffset = 0;
        pool[enc_head].syncp = NULL;
        sts = pMFXVideoENCODE_EncodeFrameAsync(session, NULL, pmfxSurface, &pool[enc_head].bs, &pool[enc_head].syncp);
        pmfxSurface->FrameInterface->Release(pmfxSurface);

        if (sts == MFX_ERR_NONE && pool[enc_head].syncp) {
            pool[enc_head].in_use = true;
            enc_head = (enc_head + 1) % ENCODE_POOL_SIZE;
            pending_count++;
        }
        frames_done++;
    }

    // Drain
    while (true) {
        while (pending_count >= ENCODE_POOL_SIZE) {
            if (pool[enc_tail].in_use && pool[enc_tail].syncp) {
                pMFXVideoCORE_SyncOperation(session, pool[enc_tail].syncp, 60000);
                pool[enc_tail].syncp = NULL;
                pool[enc_tail].in_use = false;
            }
            enc_tail = (enc_tail + 1) % ENCODE_POOL_SIZE;
            pending_count--;
        }
        pool[enc_head].bs.DataLength = 0;
        pool[enc_head].bs.DataOffset = 0;
        pool[enc_head].syncp = NULL;
        mfxStatus sts = pMFXVideoENCODE_EncodeFrameAsync(session, NULL, NULL, &pool[enc_head].bs, &pool[enc_head].syncp);
        if (sts == MFX_ERR_NONE && pool[enc_head].syncp) {
            pool[enc_head].in_use = true;
            enc_head = (enc_head + 1) % ENCODE_POOL_SIZE;
            pending_count++;
        } else {
            break;
        }
    }

    while (pending_count > 0) {
        if (pool[enc_tail].in_use && pool[enc_tail].syncp) {
            pMFXVideoCORE_SyncOperation(session, pool[enc_tail].syncp, 60000);
            pool[enc_tail].syncp = NULL;
            pool[enc_tail].in_use = false;
        }
        enc_tail = (enc_tail + 1) % ENCODE_POOL_SIZE;
        pending_count--;
    }

    QueryPerformanceCounter(&t_end);
    double total_wall_ms = get_time_ms(t_start, t_end, freq);

    out_res->processed_frames = frames_done;
    out_res->total_wall_ms = total_wall_ms;
    out_res->consumer_fps = (total_wall_ms > 0.0) ? ((double)frames_done / (total_wall_ms / 1000.0)) : 0.0;

    _aligned_free(p010_buf);
    free(hud_buf);
    for (int i = 0; i < ENCODE_POOL_SIZE; i++) {
        free(pool[i].pBsBuffer);
    }
    pMFXClose(session);
    pMFXUnload(loader);
    FreeLibrary(hVpl);
    intel_d3d11_vp_cleanup();
    return 0;
}

typedef struct {
    double a_pack_ms;
    double a_upload_ms;
    double a_total_ms;
    double b_map_ms;
    double b_pack_ms;
    double b_copy_ms;
    double b_total_ms;
    double c_map_ms;
    double c_pack_ms;
    double c_copy_ms;
    double c_total_ms;
    int diff_count;
    int max_diff;
} StagingBenchmarkResults;

__declspec(dllexport) int intel_d3d11_benchmark_staging_base_path(int n_frames, StagingBenchmarkResults* out_res) {
    if (!out_res) return -1;
    memset(out_res, 0, sizeof(StagingBenchmarkResults));

    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);

    IDXGIFactory1* pFactory = NULL;
    HRESULT hr = CreateDXGIFactory1(&IID_IDXGIFactory1, (void**)&pFactory);
    if (FAILED(hr)) return -2;

    IDXGIAdapter1* pIntelAdapter = NULL;
    for (UINT i = 0; ; ++i) {
        IDXGIAdapter1* pAdapter = NULL;
        if (IDXGIFactory1_EnumAdapters1(pFactory, i, &pAdapter) == DXGI_ERROR_NOT_FOUND) break;
        DXGI_ADAPTER_DESC1 desc;
        IDXGIAdapter1_GetDesc1(pAdapter, &desc);
        if (desc.VendorId == 0x8086 && !pIntelAdapter) {
            pIntelAdapter = pAdapter;
        } else {
            IDXGIAdapter1_Release(pAdapter);
        }
    }
    IDXGIFactory1_Release(pFactory);
    if (!pIntelAdapter) return -3;

    ID3D11Device* pDevice = NULL;
    ID3D11DeviceContext* pContext = NULL;
    D3D_FEATURE_LEVEL featureLevels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
    D3D_FEATURE_LEVEL chosenLevel;

    hr = D3D11CreateDevice(
        (IDXGIAdapter*)pIntelAdapter, D3D_DRIVER_TYPE_UNKNOWN, NULL,
        D3D11_CREATE_DEVICE_VIDEO_SUPPORT,
        featureLevels, 2, D3D11_SDK_VERSION,
        &pDevice, &chosenLevel, &pContext
    );
    IDXGIAdapter1_Release(pIntelAdapter);
    if (FAILED(hr)) return -4;

    // Target Default Textures
    D3D11_TEXTURE2D_DESC texDesc = {0};
    texDesc.Width = BASE_W;
    texDesc.Height = BASE_H;
    texDesc.MipLevels = 1;
    texDesc.ArraySize = 1;
    texDesc.Format = DXGI_FORMAT_P010;
    texDesc.SampleDesc.Count = 1;
    texDesc.Usage = D3D11_USAGE_DEFAULT;
    texDesc.BindFlags = D3D11_BIND_DECODER | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* pBaseTexA = NULL;
    ID3D11Texture2D* pBaseTexB = NULL;
    ID3D11Texture2D* pBaseTexC = NULL;
    ID3D11Device_CreateTexture2D(pDevice, &texDesc, NULL, &pBaseTexA);
    ID3D11Device_CreateTexture2D(pDevice, &texDesc, NULL, &pBaseTexB);
    ID3D11Device_CreateTexture2D(pDevice, &texDesc, NULL, &pBaseTexC);

    // Staging texture (1 slot for B)
    D3D11_TEXTURE2D_DESC stageDesc = {0};
    stageDesc.Width = BASE_W;
    stageDesc.Height = BASE_H;
    stageDesc.MipLevels = 1;
    stageDesc.ArraySize = 1;
    stageDesc.Format = DXGI_FORMAT_P010;
    stageDesc.SampleDesc.Count = 1;
    stageDesc.Usage = D3D11_USAGE_STAGING;
    stageDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    ID3D11Texture2D* pStagingTex = NULL;
    ID3D11Device_CreateTexture2D(pDevice, &stageDesc, NULL, &pStagingTex);

    // Staging ring (2 slots for C)
    ID3D11Texture2D* pStagingRing[2] = {NULL, NULL};
    ID3D11Device_CreateTexture2D(pDevice, &stageDesc, NULL, &pStagingRing[0]);
    ID3D11Device_CreateTexture2D(pDevice, &stageDesc, NULL, &pStagingRing[1]);

    // Readback staging texture for bit-identical verification
    stageDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* pReadbackTex = NULL;
    ID3D11Device_CreateTexture2D(pDevice, &stageDesc, NULL, &pReadbackTex);

    // Synthetic source AVFrame planes (YUV420P10LE, 10-bit values in range 0..1023)
    size_t y_elems = BASE_W * BASE_H;
    size_t uv_elems = (BASE_W / 2) * (BASE_H / 2);
    uint16_t* src_y = (uint16_t*)_aligned_malloc(y_elems * 2, 64);
    uint16_t* src_u = (uint16_t*)_aligned_malloc(uv_elems * 2, 64);
    uint16_t* src_v = (uint16_t*)_aligned_malloc(uv_elems * 2, 64);

    for (size_t i = 0; i < y_elems; i++) src_y[i] = (uint16_t)(i % 1024);
    for (size_t i = 0; i < uv_elems; i++) {
        src_u[i] = (uint16_t)((i * 3) % 1024);
        src_v[i] = (uint16_t)((i * 7) % 1024);
    }

    size_t p010_bytes = (BASE_W * BASE_H * 2) + (BASE_W * (BASE_H / 2) * 2);
    uint8_t* p010_scratch = (uint8_t*)_aligned_malloc(p010_bytes, 64);

    LARGE_INTEGER t0, t1;

    // --- BENCHMARK METHOD A: Current Scratch + UpdateSubresource ---
    double total_a_pack = 0.0;
    double total_a_upload = 0.0;

    for (int i = 0; i < n_frames; i++) {
        QueryPerformanceCounter(&t0);
        yuv420p10le_to_p010_pitch(
            src_y, BASE_W * 2,
            src_u, (BASE_W / 2) * 2,
            src_v, (BASE_W / 2) * 2,
            p010_scratch, BASE_W * 2,
            BASE_W, BASE_H
        );
        QueryPerformanceCounter(&t1);
        total_a_pack += get_time_ms(t0, t1, freq);

        QueryPerformanceCounter(&t0);
        ID3D11DeviceContext_UpdateSubresource(pContext, (ID3D11Resource*)pBaseTexA, 0, NULL, p010_scratch, BASE_W * 2, 0);
        QueryPerformanceCounter(&t1);
        total_a_upload += get_time_ms(t0, t1, freq);
    }

    // --- BENCHMARK METHOD B: Direct Mapped Staging + CopyResource ---
    double total_b_map = 0.0;
    double total_b_pack = 0.0;
    double total_b_copy = 0.0;

    for (int i = 0; i < n_frames; i++) {
        QueryPerformanceCounter(&t0);
        D3D11_MAPPED_SUBRESOURCE map;
        hr = ID3D11DeviceContext_Map(pContext, (ID3D11Resource*)pStagingTex, 0, D3D11_MAP_WRITE, 0, &map);
        QueryPerformanceCounter(&t1);
        total_b_map += get_time_ms(t0, t1, freq);

        QueryPerformanceCounter(&t0);
        yuv420p10le_to_p010_pitch(
            src_y, BASE_W * 2,
            src_u, (BASE_W / 2) * 2,
            src_v, (BASE_W / 2) * 2,
            (uint8_t*)map.pData, map.RowPitch,
            BASE_W, BASE_H
        );
        ID3D11DeviceContext_Unmap(pContext, (ID3D11Resource*)pStagingTex, 0);
        QueryPerformanceCounter(&t1);
        total_b_pack += get_time_ms(t0, t1, freq);

        QueryPerformanceCounter(&t0);
        ID3D11DeviceContext_CopyResource(pContext, (ID3D11Resource*)pBaseTexB, (ID3D11Resource*)pStagingTex);
        QueryPerformanceCounter(&t1);
        total_b_copy += get_time_ms(t0, t1, freq);
    }

    // --- BENCHMARK METHOD C: 2-Slot Staging Ring ---
    double total_c_map = 0.0;
    double total_c_pack = 0.0;
    double total_c_copy = 0.0;

    for (int i = 0; i < n_frames; i++) {
        int ring_slot = i % 2;
        QueryPerformanceCounter(&t0);
        D3D11_MAPPED_SUBRESOURCE map;
        hr = ID3D11DeviceContext_Map(pContext, (ID3D11Resource*)pStagingRing[ring_slot], 0, D3D11_MAP_WRITE, 0, &map);
        QueryPerformanceCounter(&t1);
        total_c_map += get_time_ms(t0, t1, freq);

        QueryPerformanceCounter(&t0);
        yuv420p10le_to_p010_pitch(
            src_y, BASE_W * 2,
            src_u, (BASE_W / 2) * 2,
            src_v, (BASE_W / 2) * 2,
            (uint8_t*)map.pData, map.RowPitch,
            BASE_W, BASE_H
        );
        ID3D11DeviceContext_Unmap(pContext, (ID3D11Resource*)pStagingRing[ring_slot], 0);
        QueryPerformanceCounter(&t1);
        total_c_pack += get_time_ms(t0, t1, freq);

        QueryPerformanceCounter(&t0);
        ID3D11DeviceContext_CopyResource(pContext, (ID3D11Resource*)pBaseTexC, (ID3D11Resource*)pStagingRing[ring_slot]);
        QueryPerformanceCounter(&t1);
        total_c_copy += get_time_ms(t0, t1, freq);
    }

    // --- BIT-IDENTICAL PARITY CHECK ---
    ID3D11DeviceContext_CopyResource(pContext, (ID3D11Resource*)pReadbackTex, (ID3D11Resource*)pBaseTexA);
    D3D11_MAPPED_SUBRESOURCE mapA;
    ID3D11DeviceContext_Map(pContext, (ID3D11Resource*)pReadbackTex, 0, D3D11_MAP_READ, 0, &mapA);
    uint8_t* dumpA = (uint8_t*)malloc(p010_bytes);
    for (int y = 0; y < BASE_H + BASE_H / 2; y++) {
        memcpy(dumpA + y * BASE_W * 2, (uint8_t*)mapA.pData + y * mapA.RowPitch, BASE_W * 2);
    }
    ID3D11DeviceContext_Unmap(pContext, (ID3D11Resource*)pReadbackTex, 0);

    ID3D11DeviceContext_CopyResource(pContext, (ID3D11Resource*)pReadbackTex, (ID3D11Resource*)pBaseTexC);
    D3D11_MAPPED_SUBRESOURCE mapC;
    ID3D11DeviceContext_Map(pContext, (ID3D11Resource*)pReadbackTex, 0, D3D11_MAP_READ, 0, &mapC);
    uint8_t* dumpC = (uint8_t*)malloc(p010_bytes);
    for (int y = 0; y < BASE_H + BASE_H / 2; y++) {
        memcpy(dumpC + y * BASE_W * 2, (uint8_t*)mapC.pData + y * mapC.RowPitch, BASE_W * 2);
    }
    ID3D11DeviceContext_Unmap(pContext, (ID3D11Resource*)pReadbackTex, 0);

    int diff_count = 0;
    int max_diff = 0;
    uint16_t* u16A = (uint16_t*)dumpA;
    uint16_t* u16C = (uint16_t*)dumpC;
    size_t total_samples = p010_bytes / 2;

    for (size_t i = 0; i < total_samples; i++) {
        int d = abs((int)u16A[i] - (int)u16C[i]);
        if (d > 0) {
            diff_count++;
            if (d > max_diff) max_diff = d;
        }
    }

    out_res->a_pack_ms = total_a_pack / n_frames;
    out_res->a_upload_ms = total_a_upload / n_frames;
    out_res->a_total_ms = (total_a_pack + total_a_upload) / n_frames;

    out_res->b_map_ms = total_b_map / n_frames;
    out_res->b_pack_ms = total_b_pack / n_frames;
    out_res->b_copy_ms = total_b_copy / n_frames;
    out_res->b_total_ms = (total_b_map + total_b_pack + total_b_copy) / n_frames;

    out_res->c_map_ms = total_c_map / n_frames;
    out_res->c_pack_ms = total_c_pack / n_frames;
    out_res->c_copy_ms = total_c_copy / n_frames;
    out_res->c_total_ms = (total_c_map + total_c_pack + total_c_copy) / n_frames;

    out_res->diff_count = diff_count;
    out_res->max_diff = max_diff;

    // Cleanup
    _aligned_free(src_y);
    _aligned_free(src_u);
    _aligned_free(src_v);
    _aligned_free(p010_scratch);
    free(dumpA);
    free(dumpC);
    ID3D11Texture2D_Release(pStagingTex);
    ID3D11Texture2D_Release(pStagingRing[0]);
    ID3D11Texture2D_Release(pStagingRing[1]);
    ID3D11Texture2D_Release(pReadbackTex);
    ID3D11Texture2D_Release(pBaseTexA);
    ID3D11Texture2D_Release(pBaseTexB);
    ID3D11Texture2D_Release(pBaseTexC);
    ID3D11DeviceContext_Release(pContext);
    ID3D11Device_Release(pDevice);
    return 0;
}
