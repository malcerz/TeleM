#include <windows.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <dxgi.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <mftransform.h>
#include <mferror.h>
#include <vector>
#include <string>
#include <iostream>
#include <fstream>
#include <chrono>
#include <thread>
#include <cstdlib>
#include <cstring>

#include "d3d11_vp_pipeline.h"
#include "d3d11_amf_encoder.h"
#include "telem_amd_build_info.h"

// STB Image Write for dumping checkpoint PNGs
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#define TELEM_EXPORT extern "C" __declspec(dllexport)

// Native success/profiling chatter is opt-in so normal GUI exports remain
// readable.  std::cerr is intentionally untouched: failures and warnings
// remain visible.  The state is configured at export creation, before any
// native initialization diagnostics are emitted.
static bool TelemRenderDebugEnabled() {
    const char* value = std::getenv("TELEM_RENDER_DEBUG");
    return value && (
        std::strcmp(value, "1") == 0 ||
        std::strcmp(value, "true") == 0 ||
        std::strcmp(value, "TRUE") == 0 ||
        std::strcmp(value, "on") == 0 ||
        std::strcmp(value, "ON") == 0
    );
}

static void ConfigureNativeRenderLogging() {
    if (TelemRenderDebugEnabled()) {
        std::cout.clear();
    } else {
        std::cout.setstate(std::ios_base::failbit);
    }
}

struct TelemAMDFrameTimings {
    double mfReadSampleMs = 0.0;
    double mfSurfaceAcquireMs = 0.0;
    double baseGpuCopyMs = 0.0;
    double hudNativeCopyMs = 0.0;
    double hudUploadMs = 0.0;
    double stagingMemcpyMs = 0.0;
    double blendMs = 0.0;
    double copySubmitMs = 0.0;
    double vpCpuSubmitMs = 0.0;
    double vpGpuCompletionMs = 0.0;
    double gpuWaitMs = 0.0;
    double amfSubmitMs = 0.0;
    double amfQueryMs = 0.0;
    double packetWriteMs = 0.0;
};

// ETAP 5R — per-frame native process_frame accounting (opt-in, QPC wall).
struct NativeFrameRec {
    UINT64 frame = 0;
    double surfAcquireMs = 0.0;      // decoder surface acquire / copy before VP
    double vpTotalMs = 0.0;          // whole VP ProcessFrame wall
    double vpSetupMs = 0.0;          // entry -> Blt start
    double vpCreateViewMs = 0.0;
    double vpSetStreamMs = 0.0;      // CreateView -> Blt (SetStream*)
    double vpSetterFmtMs = 0.0;      // ETAP 5S: VideoProcessorSetStreamFrameFormat
    double vpSetterSrcRectMs = 0.0;  // ETAP 5S: VideoProcessorSetStreamSourceRect
    double vpSetterDstRectMs = 0.0;  // ETAP 5S: VideoProcessorSetStreamDestRect
    int firstVpApi = 0;               // ETAP 5V: 1=FMT, 2=SRC, 3=DST, 4=BLT
    double firstVpApiMs = 0.0;
    double vpSequenceTotalMs = 0.0;
    double vpBltMs = 0.0;
    double vpSubmitWindowMs = 0.0;   // Blt end -> HUD end
    double vpRangePassMs = 0.0;
    double clearPrevAboveMs = 0.0;
    double vpChartBlendMs = 0.0;
    double chartFlushMs = 0.0;
    double vpGaugeBlendMs = 0.0;
    double gaugeFlushMs = 0.0;
    double mapResampleMs = 0.0;
    double mapBlendMs = 0.0;
    double mapFlush1Ms = 0.0;
    double mapFlush2Ms = 0.0;
    double aboveBlendMs = 0.0;
    double aboveFlushMs = 0.0;
    double flushTotalMs = 0.0;
    double vpHudComposeMs = 0.0;
    double vpReleaseViewMs = 0.0;
    double amfCreateSurfaceMs = 0.0;
    double amfSubmitInputMs = 0.0;
    double amfQueryMs = 0.0;
    double amfPacketWriteMs = 0.0;
    double processFrameTotalMs = 0.0;
    UINT poolIndex = 0;
    UINT amfQueryCalls = 0;      // ETAP 5U: QueryOutput calls this frame
    UINT amfOutputs = 0;         // ETAP 5U: packets received this frame
    UINT retriesThisFrame = 0;
    UINT64 decoderTexId = 0;         // ETAP 5S: decoder input texture pointer (low bits)
    UINT64 vpOutTexId = 0;           // ETAP 5S: VP output texture pointer (low bits)
    UINT arrayIndex = 0;             // ETAP 5S: decoder subresource
    UINT64 vpProcessorId = 0;
    UINT64 vpEnumeratorId = 0;
    UINT64 vpContextId = 0;
    int settersSkipped = 0;          // ETAP 5S: 1 when STATIC_CACHE skipped setters
    UINT stateSig = 0;               // ETAP 5S: applied stream-state signature
    UINT64 amfSubmitted = 0;
    UINT64 amfReceived = 0;
    int submitResult = 0;
    int queryResult = 0;
    int decoderCopy = 0;
    int prevVpQueryReady = -1;
    int prevLocalQueryReady = -1;
    UINT64 sameSlotPreviousFrame = UINT64_MAX;
    int sameSlotQueryReady = -1;
    UINT inFlightFrames = 0;
    UINT maxInFlight = 0;
    UINT outputNotReadyCount = 0;
    double queueWaitMs = 0.0;
};

struct TelemAMDContext {
    ID3D11Device* pDevice = nullptr;
    ID3D11DeviceContext* pContext = nullptr;

    D3D11VideoProcessorPipeline vpPipeline;
    D3D11AMFEncoder amfEncoder;

    // Media Foundation Decoder
    IMFSourceReader* pSourceReader = nullptr;
    IMFDXGIDeviceManager* pDXGIManager = nullptr;
    UINT dxgiResetToken = 0;

    // HUD Texture
    ID3D11Texture2D* pHUDTexture = nullptr;
    ID3D11VideoProcessorInputView* pHUDInputView = nullptr;
    UINT hudWidth = 0;
    UINT hudHeight = 0;

    // Base Video Texture (NV12 surface)
    ID3D11Texture2D* pBaseP010Tex = nullptr;
    ID3D11Texture2D* pUploadStagingTex = nullptr;
    ID3D11Texture2D* pDecodedCopyTex = nullptr;
    bool hasUpdatedVideoFrame = false;

    // Pending Media Foundation D3D11 sample. ReadSample and processing are
    // deliberately split so Python can generate HUD from the real sample PTS.
    ID3D11Texture2D* pPendingDecodedTex = nullptr;
    UINT pendingSubresource = 0;
    LONGLONG pendingTimestamp100ns = 0;
    LONGLONG pendingDuration100ns = 0;
    DWORD pendingStreamFlags = 0;
    DXGI_FORMAT decoderOutputFormat = DXGI_FORMAT_UNKNOWN;
    UINT decoderWidth = 0;
    UINT decoderHeight = 0;
    UINT sourceRotation = 0;
    bool mfDecoderReady = false;
    bool mfHardwareConfirmed = false;
    bool mfEndOfStream = false;
    int decodeMode = 0; // 0 = CPU_DECODE_REFERENCE, 1 = D3D11VA

    // File Output
    std::string outputPath;
    std::ofstream h265Out;

    // Dimensions & Config
    UINT width = 3840;
    UINT height = 2160;
    UINT fpsNum = 30000;
    UINT fpsDen = 1001;

    // Frame counters
    UINT64 framesDecoded = 0;
    UINT64 framesVPProcessed = 0;
    UINT64 framesSubmitted = 0;
    UINT64 framesReceived = 0;
    UINT64 hudUpdates = 0;
    UINT64 videoUpdates = 0;
    UINT64 amfInputFullCount = 0;
    UINT64 amfRetryCount = 0;
    UINT64 amfDroppedSubmissions = 0;
    UINT64 amfIgnoredSubmissions = 0;
    UINT64 blendCalls = 0;
    UINT64 gpuProfiledFrames = 0;
    UINT64 gpuHUDFrames = 0;
    UINT64 hudTextureCreates = 0;
    UINT64 hudTextureUploads = 0;
    UINT64 hudUploadedBytes = 0;
    UINT64 hudUploadedRects = 0;
    UINT64 mfReadSampleCalls = 0;
    UINT64 mfVideoSamples = 0;
    UINT64 mfStreamTicks = 0;
    UINT64 mfNullSamples = 0;
    UINT64 mfD3D11Surfaces = 0;
    UINT64 mfFormatChanges = 0;
    UINT64 mfEndOfStreamEvents = 0;
    UINT64 directDecoderSurfaceFrames = 0;
    UINT64 decoderGpuCopyFrames = 0;

    bool diagnosticsEnabled = false;
    bool profilingEnabled = false;
    bool hudEnabled = true;
    // 0 = CPU_REFERENCE, 1 = GPU_HUD.
    int hudMode = 0;
    // ETAP 5G: 0 = CPU_REFERENCE (map stays in Pillow HUD), 1 = GPU (separate
    // persistent map texture + GPU resample/composite).
    int mapCompositeMode = 0;
    UINT64 mapUploads = 0;
    UINT64 mapUploadedBytes = 0;
    UINT64 mapResampleFrames = 0;
    // ETAP 5J: 0 = CPU_REFERENCE (charts stay in Pillow HUD), 1 = GPU (charts
    // uploaded to persistent textures + GPU blend into the HUD canvas).
    int chartCompositeMode = 0;
    UINT64 chartUploads[2] = { 0, 0 };
    UINT64 chartUploadedBytes[2] = { 0, 0 };
    UINT64 chartGpuFramesCadence = 0;
    UINT64 chartGpuFramesHR = 0;
    // ETAP 1B: GPU AFTER-MAP chart compositing (HR/Cadence)
    int afterMapChartCompositeMode = 0;
    UINT64 afterMapChartUploads[2] = { 0, 0 };
    UINT64 afterMapChartUploadedBytes[2] = { 0, 0 };
    UINT64 afterMapChartGpuFramesCadence = 0;
    UINT64 afterMapChartGpuFramesHR = 0;
    // ETAP 5O diagnostic: 0 = ENCODE (default), 1 = BYPASS (run the whole
    // frontend to the AMF input point but never submit/encode), 2 = reserved.
    int amfMode = 0;
    // ETAP 5U: 0=REFERENCE (one QueryOutput/frame), 1=DRAIN_READY (drain all
    // immediately-ready packets, stop at first AMF_REPEAT, zero wait).
    int amfQueryMode = 0;
    UINT amfQueryCalls = 0;   // QueryOutput calls in the current frame
    UINT amfOutputsThisFrame = 0;  // packets received in the current frame
    int queueDepth = 1;
    UINT64 inFlightFrames = 0;
    UINT64 maxInFlight = 0;
    UINT64 outputNotReadyCount = 0;
    double consumerWaitMs = 0.0;
    TelemAMDFrameTimings lastTimings;

    // ETAP 5R — native process_frame accounting (AMD_NATIVE_FRAME_ACCOUNTING).
    bool frameAccountEnabled = false;
    std::vector<NativeFrameRec> nativeTrace;

    // Last processed VP output NV12 texture
    ID3D11Texture2D* pLastOutNV12Tex = nullptr;

    // Persistent CPU HUD RGBA buffer
    std::vector<uint8_t> currentHUDRGBA;
};

static bool RefreshDecoderMediaType(TelemAMDContext* ctx);

static bool OpenSourceReader(TelemAMDContext* ctx, const wchar_t* input_path) {
    if (!ctx || !ctx->pDXGIManager || !input_path || !*input_path) return false;
    IMFAttributes* attrs = nullptr;
    HRESULT hr = MFCreateAttributes(&attrs, 5);
    if (FAILED(hr)) return false;
    attrs->SetUnknown(MF_SOURCE_READER_D3D_MANAGER, ctx->pDXGIManager);
    attrs->SetUINT32(MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, TRUE);
    attrs->SetUINT32(MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, TRUE);
    hr = MFCreateSourceReaderFromURL(input_path, attrs, &ctx->pSourceReader);
    attrs->Release();
    if (FAILED(hr) || !ctx->pSourceReader) return false;
    ctx->pSourceReader->SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS, FALSE);
    ctx->pSourceReader->SetStreamSelection(MF_SOURCE_READER_FIRST_VIDEO_STREAM, TRUE);
    IMFMediaType* type = nullptr;
    MFCreateMediaType(&type);
    if (!type) {
        ctx->pSourceReader->Release();
        ctx->pSourceReader = nullptr;
        return false;
    }
    type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
    type->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_P010);
    hr = ctx->pSourceReader->SetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, nullptr, type);
    if (FAILED(hr)) {
        type->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12);
        hr = ctx->pSourceReader->SetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, nullptr, type);
    }
    type->Release();
    ctx->mfDecoderReady = SUCCEEDED(hr) && RefreshDecoderMediaType(ctx);
    ctx->mfEndOfStream = false;
    ctx->pendingTimestamp100ns = 0;
    ctx->pendingDuration100ns = 0;
    if (!ctx->mfDecoderReady) {
        if (ctx->pSourceReader) { ctx->pSourceReader->Release(); ctx->pSourceReader = nullptr; }
        return false;
    }
    std::cout << "[MF DECODER] Source opened for native multi-file path." << std::endl;
    return true;
}

TELEM_EXPORT UINT telem_amd_get_abi_version() {
    return TELEM_AMD_ABI_VERSION;
}

TELEM_EXPORT const char* telem_amd_get_build_info() {
    static const char buildInfo[] =
        "version=" TELEM_AMD_VERSION
        "; build_id=" TELEM_AMD_BUILD_ID
        "; build_timestamp=" TELEM_AMD_BUILD_TIMESTAMP
        "; git_commit=" TELEM_AMD_GIT_COMMIT
        "; source_hash=" TELEM_AMD_SOURCE_HASH;
    return buildInfo;
}

TELEM_EXPORT int telem_amd_set_diagnostics(void* handle, int enabled) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->diagnosticsEnabled = (enabled != 0);
    return 1;
}

TELEM_EXPORT int telem_amd_set_profiling(void* handle, int enabled) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->profilingEnabled = (enabled != 0);
    return 1;
}

TELEM_EXPORT int telem_amd_set_hud_enabled(void* handle, int enabled) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->hudEnabled = (enabled != 0);
    if (!ctx->hudEnabled) {
        ctx->currentHUDRGBA.clear();
    }
    return 1;
}

TELEM_EXPORT int telem_amd_set_hud_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->hudMode = mode;
    return 1;
}

// ── ETAP 5G: GPU-resident final map resize + composite ───────────────

TELEM_EXPORT int telem_amd_set_map_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->mapCompositeMode = mode;
    ctx->vpPipeline.SetMapGpuEnabled(mode == 1);
    return 1;
}

TELEM_EXPORT int telem_amd_set_map_filter(void* handle, int filter) {
    if (!handle || (filter < 0 || filter > 2)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetMapFilter(filter);
    return 1;
}

// ── ETAP 8U-B: Map GPU Path ──────────────────────────────────────────
// 0 = DIRECT_AUTO (default: 1:1 uses DirectBlend, mismatch uses Reference),
// 1 = REFERENCE (force two-pass resample + blend),
// 2 = DIRECT_1TO1 (force direct blend).
TELEM_EXPORT int telem_amd_set_map_gpu_path(void* handle, int path) {
    if (!handle || (path < 0 || path > 2)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetMapGpuPath(path);
    return 1;
}

TELEM_EXPORT int telem_amd_get_map_gpu_path_used(void* handle) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.IsMapDirectUsed() ? 1 : 0;
}

// ── ETAP 5O: AMF mode (diagnostic only) ──────────────────────────────
// 0 = ENCODE (default production), 1 = BYPASS (frontend only, no AMF).
TELEM_EXPORT int telem_amd_set_amf_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->amfMode = mode;
    return 1;
}

TELEM_EXPORT int telem_amd_set_map_geometry(
    void* handle, UINT dstX, UINT dstY, UINT srcW, UINT srcH, UINT outW, UINT outH) {
    if (!handle || srcW == 0 || srcH == 0 || outW == 0 || outH == 0) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetMapGeometry(dstX, dstY, srcW, srcH, outW, outH);
    return 1;
}

TELEM_EXPORT int telem_amd_update_map(
    void* handle, const uint8_t* pRGBA, UINT width, UINT height, UINT stride,
    UINT64* outUploadedBytes, int* outTextureCreated) {
    if (!handle || !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (ctx->mapCompositeMode != 1) return 0;
    size_t uploadedBytes = 0;
    bool textureCreated = false;
    if (!ctx->vpPipeline.UpdateMapTexture(
            width, height, pRGBA, stride, &uploadedBytes, &textureCreated)) {
        std::cerr << "[TELEM AMD DLL] GPU map upload failed." << std::endl;
        return 0;
    }
    if (outUploadedBytes) *outUploadedBytes = uploadedBytes;
    if (outTextureCreated) *outTextureCreated = textureCreated ? 1 : 0;
    ctx->mapUploads++;
    ctx->mapUploadedBytes += uploadedBytes;
    return 1;
}

TELEM_EXPORT int telem_amd_set_map_rotate_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetMapRotateMode(mode == 1);
    return 1;
}

TELEM_EXPORT int telem_amd_set_map_heading(void* handle, float headingDeg) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetMapHeading(headingDeg);
    return 1;
}

TELEM_EXPORT int telem_amd_update_map_marker(
    void* handle, const uint8_t* pRGBA, UINT width, UINT height, UINT stride,
    UINT dstX, UINT dstY) {
    if (!handle || !pRGBA || stride < width * 4 || width == 0 || height == 0) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.UpdateMapMarkerTexture(width, height, pRGBA, stride, dstX, dstY) ? 1 : 0;
}

// ETAP 7B: compact CPU_ABOVE_MAP layer.  It is intentionally a single
// ordered layer, not a generalized compositor or a second map path.
TELEM_EXPORT int telem_amd_set_above_map_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetAboveMapGpuEnabled(mode == 1);
    return 1;
}

TELEM_EXPORT int telem_amd_update_above_regions_count(void* handle, UINT count) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.UpdateAboveRegionsCount(count) ? 1 : 0;
}

TELEM_EXPORT int telem_amd_update_above_region(
    void* handle, UINT index, const uint8_t* pRGBA, UINT width, UINT height, UINT stride,
    UINT dstX, UINT dstY) {
    if (!handle || !pRGBA || stride < width * 4 || width == 0 || height == 0) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.UpdateAboveRegion(index, width, height, pRGBA, stride, dstX, dstY) ? 1 : 0;
}

TELEM_EXPORT int telem_amd_update_above_regions_batch(
    void* handle, const uint8_t* const* pRowPointers, UINT canvasStride,
    const HUDDirtyRect* pRects, UINT rectCount) {
    if (!handle || !pRowPointers || !pRects || canvasStride == 0) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.UpdateAboveRegionsBatch(pRowPointers, canvasStride, pRects, rectCount) ? 1 : 0;
}

TELEM_EXPORT void telem_amd_get_above_region_timings(
    void* handle, double* outNativeMs, double* outSubresourceMs, UINT* outSubresourceCalls) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (outNativeMs) *outNativeMs = ctx->vpPipeline.GetLastAboveRegionNativeMs();
    if (outSubresourceMs) *outSubresourceMs = ctx->vpPipeline.GetLastAboveRegionSubresourceMs();
    if (outSubresourceCalls) *outSubresourceCalls = ctx->vpPipeline.GetLastAboveRegionSubresourceCalls();
}

TELEM_EXPORT int telem_amd_update_above_map(
    void* handle, const uint8_t* pRGBA, UINT width, UINT height, UINT stride,
    UINT dstX, UINT dstY, int active) {
    if (!handle || !pRGBA || stride < width * 4 || width == 0 || height == 0) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.UpdateAboveMapTexture(
        width, height, pRGBA, stride, dstX, dstY, active != 0) ? 1 : 0;
}

// Diagnostic A/B readback of the GPU-resampled 691x691 RGBA map.  Not used by
// the production export path.
TELEM_EXPORT int telem_amd_get_map_resample(
    void* handle, uint8_t* outRGBA, UINT stride) {
    if (!handle || !outRGBA) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.GetMapResampleReadback(outRGBA, stride) ? 1 : 0;
}

// Diagnostic: dump the GPU-resampled map texture to a PNG right after the
// resample dispatch (inside ProcessFrame).  Never used on production.
TELEM_EXPORT void telem_amd_set_map_dump_path(void* handle, const char* path) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetMapDumpPath(path);
}

TELEM_EXPORT void telem_amd_get_map_stats(
    void* handle,
    UINT64* outUploads, UINT64* outUploadedBytes, UINT64* outResampleFrames,
    double* outUploadMs, double* outResampleMs, double* outBlendMs) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (outUploads) *outUploads = ctx->mapUploads;
    if (outUploadedBytes) *outUploadedBytes = ctx->mapUploadedBytes;
    if (outResampleFrames) *outResampleFrames = ctx->mapResampleFrames;
    if (outUploadMs) *outUploadMs = ctx->vpPipeline.GetMapUploadMs();
    if (outResampleMs) *outResampleMs = ctx->vpPipeline.GetMapResampleMs();
    if (outBlendMs) *outBlendMs = ctx->vpPipeline.GetMapBlendMs();
}

// ── ETAP 5J: GPU final compositing for the cadence/HR charts ──────────
// mode: 0 = CPU_REFERENCE (charts stay in the Pillow HUD), 1 = GPU (5J:
// full chart texture blended per frame), 2 = GPU_SPLIT (5K: static layer
// uploaded once + small dynamic cursor/value tiles replaced per frame).

TELEM_EXPORT int telem_amd_set_chart_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1 && mode != 2)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->chartCompositeMode = mode;
    ctx->vpPipeline.SetChartGpuEnabled(mode != 0);
    ctx->vpPipeline.SetChartSplitMode(mode == 2);
    return 1;
}

// slot: 0 = cadence, 1 = heart-rate.  The CPU still renders the exact same
// chart RGBA widget (final size, 1:1 texel); the GPU holds a persistent
// texture per slot and blends it into the HUD canvas inside ProcessFrame.
TELEM_EXPORT int telem_amd_update_chart(
    void* handle, int slot, const uint8_t* pRGBA, UINT width, UINT height,
    UINT stride, UINT dstX, UINT dstY,
    UINT64* outUploadedBytes, int* outTextureCreated) {
    if (!handle || slot < 0 || slot > 1 || !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (ctx->chartCompositeMode != 1) return 0;
    size_t uploadedBytes = 0;
    bool textureCreated = false;
    if (!ctx->vpPipeline.UpdateChartTexture(
            (UINT)slot, width, height, pRGBA, stride, dstX, dstY,
            &uploadedBytes, &textureCreated)) {
        std::cerr << "[TELEM AMD DLL] GPU chart upload failed (slot " << slot << ")." << std::endl;
        return 0;
    }
    if (outUploadedBytes) *outUploadedBytes = uploadedBytes;
    if (outTextureCreated) *outTextureCreated = textureCreated ? 1 : 0;
    ctx->chartUploads[slot]++;
    ctx->chartUploadedBytes[slot] += uploadedBytes;
    if (slot == 0) ctx->chartGpuFramesCadence++;
    else ctx->chartGpuFramesHR++;
    return 1;
}

// ETAP 5K — static layer upload.  Called once per cache invalidation/export.
TELEM_EXPORT int telem_amd_update_chart_static(
    void* handle, int slot, const uint8_t* pRGBA, UINT width, UINT height,
    UINT stride, UINT dstX, UINT dstY,
    UINT64* outUploadedBytes, int* outTextureCreated) {
    if (!handle || slot < 0 || slot > 1 || !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (ctx->chartCompositeMode != 2) return 0;
    size_t uploadedBytes = 0;
    bool textureCreated = false;
    if (!ctx->vpPipeline.UpdateChartStaticTexture(
            (UINT)slot, width, height, pRGBA, stride, dstX, dstY,
            &uploadedBytes, &textureCreated)) {
        std::cerr << "[TELEM AMD DLL] GPU chart static upload failed (slot " << slot << ")." << std::endl;
        return 0;
    }
    if (outUploadedBytes) *outUploadedBytes = uploadedBytes;
    if (outTextureCreated) *outTextureCreated = textureCreated ? 1 : 0;
    return 1;
}

// ETAP 5K — dynamic tile upload.  region: 0 = cursor, 1 = current value.
// localX/localY are the tile offset inside the chart image.
TELEM_EXPORT int telem_amd_update_chart_dynamic(
    void* handle, int slot, int region, const uint8_t* pRGBA, UINT width,
    UINT height, UINT stride, UINT localX, UINT localY,
    UINT64* outUploadedBytes) {
    if (!handle || slot < 0 || slot > 1 || region < 0 || region > 1 ||
        !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (ctx->chartCompositeMode != 2) return 0;
    size_t uploadedBytes = 0;
    if (!ctx->vpPipeline.UpdateChartDynamicTile(
            (UINT)slot, (UINT)region, width, height, pRGBA, stride, localX, localY,
            &uploadedBytes)) {
        std::cerr << "[TELEM AMD DLL] GPU chart dynamic upload failed (slot " << slot << ")." << std::endl;
        return 0;
    }
    if (outUploadedBytes) *outUploadedBytes = uploadedBytes;
    if (slot == 0) ctx->chartGpuFramesCadence++;
    else ctx->chartGpuFramesHR++;
    return 1;
}

// Diagnostic/per-frame stats.  blendMs/clearMs are the last processed frame's
// GPU chart blend/clear submit times.  Never used on the production path.
TELEM_EXPORT void telem_amd_get_chart_stats(
    void* handle,
    UINT64* outUploads, UINT64* outUploadedBytes, UINT64* outFrames,
    double* outBlendMs, double* outClearMs, UINT64* outTextureCreates,
    UINT64* outStaticBytes, UINT64* outDynamicBytes, UINT64* outStaticUploads,
    UINT64* outDynamicUploads) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (outUploads) *outUploads = ctx->chartUploads[0] + ctx->chartUploads[1];
    if (outUploadedBytes) *outUploadedBytes = ctx->chartUploadedBytes[0] + ctx->chartUploadedBytes[1];
    if (outFrames) *outFrames = ctx->chartGpuFramesCadence + ctx->chartGpuFramesHR;
    if (outBlendMs) *outBlendMs = ctx->vpPipeline.GetChartBlendMs();
    if (outClearMs) *outClearMs = ctx->vpPipeline.GetChartClearMs();
    if (outTextureCreates) *outTextureCreates = ctx->vpPipeline.GetChartTextureCreates();
    if (outStaticBytes) *outStaticBytes = ctx->vpPipeline.GetChartStaticUploadedBytes();
    if (outDynamicBytes) *outDynamicBytes = ctx->vpPipeline.GetChartDynamicUploadedBytes();
    if (outStaticUploads) *outStaticUploads = ctx->vpPipeline.GetChartStaticUploads();
    if (outDynamicUploads) *outDynamicUploads = ctx->vpPipeline.GetChartDynamicUploads();
}

// Diagnostic: read back a region of the persistent HUD canvas (the exact
// composited pixels the video consumes).  Used only by the 5J A/B harness to
// validate the GPU chart blend; never on the production path.
TELEM_EXPORT int telem_amd_get_hud_region_readback(
    void* handle, UINT x, UINT y, UINT w, UINT h, uint8_t* outRGBA, UINT stride) {
    if (!handle || !outRGBA) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.GetHUDCanvasRegionReadback(x, y, w, h, outRGBA, stride) ? 1 : 0;
}

// ETAP 5K diagnostic: read back the persistent static chart texture (the exact
// bytes uploaded once per cache invalidation).  Used by the 5K raw static
// A/B harness; never on the production path.
TELEM_EXPORT int telem_amd_get_chart_static_readback(
    void* handle, int slot, uint8_t* outRGBA, UINT stride) {
    if (!handle || slot < 0 || slot > 1 || !outRGBA) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.GetChartStaticReadback((UINT)slot, outRGBA, stride) ? 1 : 0;
}

// ── ETAP 1B: GPU AFTER-MAP chart compositing (HR/Cadence) ──────────────
// mode: 0 = CPU_REFERENCE (charts stay in CPU_ABOVE_MAP),
//       2 = GPU_SPLIT (static layer uploaded once + small dynamic cursor/value tiles replaced per frame).

TELEM_EXPORT int telem_amd_set_after_map_chart_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1 && mode != 2)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->afterMapChartCompositeMode = mode;
    ctx->vpPipeline.SetAfterMapChartGpuEnabled(mode != 0);
    ctx->vpPipeline.SetAfterMapChartSplitMode(mode == 2);
    return 1;
}

TELEM_EXPORT int telem_amd_update_after_map_chart_static(
    void* handle, int slot, const uint8_t* pRGBA, UINT width, UINT height,
    UINT stride, UINT dstX, UINT dstY,
    UINT64* outUploadedBytes, int* outTextureCreated) {
    if (!handle || slot < 0 || slot > 1 || !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (ctx->afterMapChartCompositeMode != 2) return 0;
    size_t uploadedBytes = 0;
    bool textureCreated = false;
    if (!ctx->vpPipeline.UpdateAfterMapChartStaticTexture(
            (UINT)slot, width, height, pRGBA, stride, dstX, dstY,
            &uploadedBytes, &textureCreated)) {
        std::cerr << "[TELEM AMD DLL] GPU after-map chart static upload failed (slot " << slot << ")." << std::endl;
        return 0;
    }
    if (outUploadedBytes) *outUploadedBytes = uploadedBytes;
    if (outTextureCreated) *outTextureCreated = textureCreated ? 1 : 0;
    return 1;
}

TELEM_EXPORT int telem_amd_update_after_map_chart_dynamic(
    void* handle, int slot, int region, const uint8_t* pRGBA, UINT width,
    UINT height, UINT stride, UINT localX, UINT localY,
    UINT64* outUploadedBytes) {
    if (!handle || slot < 0 || slot > 1 || region < 0 || region > 1 ||
        !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (ctx->afterMapChartCompositeMode != 2) return 0;
    size_t uploadedBytes = 0;
    if (!ctx->vpPipeline.UpdateAfterMapChartDynamicTile(
            (UINT)slot, (UINT)region, width, height, pRGBA, stride, localX, localY,
            &uploadedBytes)) {
        std::cerr << "[TELEM AMD DLL] GPU after-map chart dynamic upload failed (slot " << slot << ")." << std::endl;
        return 0;
    }
    if (outUploadedBytes) *outUploadedBytes = uploadedBytes;
    ctx->afterMapChartUploads[slot]++;
    ctx->afterMapChartUploadedBytes[slot] += uploadedBytes;
    if (slot == 0) ctx->afterMapChartGpuFramesCadence++;
    else ctx->afterMapChartGpuFramesHR++;
    return 1;
}

TELEM_EXPORT void telem_amd_get_after_map_chart_stats(
    void* handle,
    UINT64* outUploads, UINT64* outUploadedBytes, UINT64* outFrames,
    double* outBlendMs, UINT64* outStaticBytes, UINT64* outDynamicBytes,
    UINT64* outStaticUploads, UINT64* outDynamicUploads) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (outUploads) *outUploads = ctx->afterMapChartUploads[0] + ctx->afterMapChartUploads[1];
    if (outUploadedBytes) *outUploadedBytes = ctx->afterMapChartUploadedBytes[0] + ctx->afterMapChartUploadedBytes[1];
    if (outFrames) *outFrames = ctx->afterMapChartGpuFramesCadence + ctx->afterMapChartGpuFramesHR;
    if (outBlendMs) *outBlendMs = ctx->vpPipeline.GetAfterMapChartBlendMs();
    if (outStaticBytes) *outStaticBytes = ctx->vpPipeline.GetAfterMapChartStaticUploadedBytes();
    if (outDynamicBytes) *outDynamicBytes = ctx->vpPipeline.GetAfterMapChartDynamicUploadedBytes();
    if (outStaticUploads) *outStaticUploads = ctx->vpPipeline.GetAfterMapChartStaticUploads();
    if (outDynamicUploads) *outDynamicUploads = ctx->vpPipeline.GetAfterMapChartDynamicUploads();
}

// ── ETAP 5L: GPU final compositing for the speed gauge ──────────────
// mode: 0 = CPU_REFERENCE (gauge stays in the Pillow HUD), 1 = GPU (the CPU
// still renders the exact same gauge RGBA but the GPU blends it into the HUD).

TELEM_EXPORT int telem_amd_set_gauge_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetGaugeGpuEnabled(mode == 1);
    return 1;
}

// ── ETAP 2A: gauge pass placement ─────────────────────────────────────
// afterMap: 0 = legacy BEFORE-MAP position (ETAP 5L semantics preserved),
//           1 = AFTER-MAP position (after BlendAboveMap, before
//           BlendAfterMapCharts) with early previous-region clearing.
TELEM_EXPORT int telem_amd_set_gauge_after_map(void* handle, int afterMap) {
    if (!handle || (afterMap != 0 && afterMap != 1)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetGaugeAfterMapPlacement(afterMap == 1);
    return 1;
}

// ── ETAP 2A FIX: start-of-frame clears on demand ──────────────────────
// Runs ClearPreviousAboveMap() (previous ABOVE regions + previous AFTER-MAP
// gauge tile erase) outside of telem_amd_process_frame so the exporter can
// order it BEFORE telem_amd_update_hud_regions.  Without this, the early
// erase of the full previous gauge tile bbox destroys freshly-uploaded
// BELOW-canvas pixels inside that bbox (e.g. the dist_visual ruler track)
// because static widgets are not re-uploaded every frame.  The clears are
// consuming (their state resets), so the internal call inside ProcessFrame
// becomes a no-op on frames where this export ran — no double clearing.
TELEM_EXPORT int telem_amd_run_early_clears(void* handle) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.RunEarlyClears() ? 1 : 0;
}

TELEM_EXPORT int telem_amd_update_gauge(
    void* handle, const uint8_t* pRGBA, UINT width, UINT height,
    UINT stride, UINT dstX, UINT dstY,
    UINT64* outUploadedBytes, int* outTextureCreated) {
    if (!handle || !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    size_t uploadedBytes = 0;
    bool textureCreated = false;
    if (!ctx->vpPipeline.UpdateGaugeTexture(
            width, height, pRGBA, stride, dstX, dstY,
            &uploadedBytes, &textureCreated)) {
        std::cerr << "[TELEM AMD DLL] GPU gauge upload failed." << std::endl;
        return 0;
    }
    if (outUploadedBytes) *outUploadedBytes = uploadedBytes;
    if (outTextureCreated) *outTextureCreated = textureCreated ? 1 : 0;
    return 1;
}

// ── ETAP 2B: partial gauge texture update (dynamic sub-region) ────────
// Uploads only one dynamic sub-rectangle of the persistent gauge tile.
// Static dial pixels stay from earlier uploads; BlendGauge is untouched.
TELEM_EXPORT int telem_amd_update_gauge_region(
    void* handle, const uint8_t* pRGBA,
    UINT boxX, UINT boxY, UINT boxW, UINT boxH, UINT srcRowPitch,
    UINT tileW, UINT tileH, UINT dstX, UINT dstY,
    UINT64* outUploadedBytes, int* outTextureCreated) {
    if (!handle || !pRGBA) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    size_t uploadedBytes = 0;
    bool textureCreated = false;
    if (!ctx->vpPipeline.UpdateGaugeRegionTexture(
            boxX, boxY, boxW, boxH, pRGBA, srcRowPitch,
            tileW, tileH, dstX, dstY, &uploadedBytes, &textureCreated)) {
        std::cerr << "[TELEM AMD DLL] GPU gauge region upload failed." << std::endl;
        return 0;
    }
    if (outUploadedBytes) *outUploadedBytes = uploadedBytes;
    if (outTextureCreated) *outTextureCreated = textureCreated ? 1 : 0;
    return 1;
}

// Diagnostic/per-frame stats.  blendMs/clearMs are the last processed frame's
// GPU gauge blend/clear submit times.  Never used on the production path.
TELEM_EXPORT void telem_amd_get_gauge_stats(
    void* handle,
    UINT64* outUploads, UINT64* outUploadedBytes, double* outBlendMs,
    double* outClearMs, UINT64* outTextureCreates) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (outUploads) *outUploads = ctx->vpPipeline.GetGaugeUploads();
    if (outUploadedBytes) *outUploadedBytes = ctx->vpPipeline.GetGaugeUploadedBytes();
    if (outBlendMs) *outBlendMs = ctx->vpPipeline.GetGaugeBlendMs();
    if (outClearMs) *outClearMs = ctx->vpPipeline.GetGaugeClearMs();
    if (outTextureCreates) *outTextureCreates = ctx->vpPipeline.GetGaugeTextureCreates();
}

// ── ETAP 2G: GPU lean indicator sprite affine transform compositor ──
TELEM_EXPORT int telem_amd_set_lean_gpu_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.SetLeanGpuEnabled(mode == 1);
    return 1;
}

TELEM_EXPORT int telem_amd_update_lean_static_texture(
    void* handle, const uint8_t* pRGBA, UINT width, UINT height, UINT stride,
    UINT64* outUploadedBytes, int* outTextureCreated) {
    if (!handle || !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    size_t uploadedBytes = 0;
    bool textureCreated = false;
    if (!ctx->vpPipeline.UpdateLeanStaticTexture(
            width, height, pRGBA, stride, &uploadedBytes, &textureCreated)) {
        std::cerr << "[TELEM AMD DLL] GPU lean static texture upload failed." << std::endl;
        return 0;
    }
    if (outUploadedBytes) *outUploadedBytes = uploadedBytes;
    if (outTextureCreated) *outTextureCreated = textureCreated ? 1 : 0;
    return 1;
}

TELEM_EXPORT int telem_amd_set_lean_transform(
    void* handle, float angleDeg, float pivotPx, float pivotPy,
    float screenPivotX, float screenPivotY,
    UINT dstX, UINT dstY, UINT tightW, UINT tightH) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.SetLeanTransform(
        angleDeg, pivotPx, pivotPy, screenPivotX, screenPivotY,
        dstX, dstY, tightW, tightH) ? 1 : 0;
}

TELEM_EXPORT void telem_amd_get_lean_stats(
    void* handle, UINT64* outStaticUploads, UINT64* outStaticUploadedBytes, double* outBlendMs) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (outStaticUploads) *outStaticUploads = ctx->vpPipeline.GetLeanStaticUploads();
    if (outStaticUploadedBytes) *outStaticUploadedBytes = ctx->vpPipeline.GetLeanStaticUploadedBytes();
    if (outBlendMs) *outBlendMs = ctx->vpPipeline.GetLeanBlendMs();
}

TELEM_EXPORT int telem_amd_blend_lean_diagnostic(void* handle, double* outBlendMs, double* outFlushMs) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.BlendLean(outBlendMs, outFlushMs) ? 1 : 0;
}

TELEM_EXPORT int telem_amd_clear_previous_above_map(void* handle, double* outClearMs) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    return ctx->vpPipeline.RunEarlyClears(outClearMs) ? 1 : 0;
}

TELEM_EXPORT int telem_amd_reset_previous_above_regions(void* handle) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->vpPipeline.ResetPreviousAboveRegions();
    return 1;
}

TELEM_EXPORT int telem_amd_set_source_rotation(void* handle, UINT degrees) {
    if (!handle) return 0;
    degrees %= 360;
    if (degrees != 0 && degrees != 90 && degrees != 180 && degrees != 270) return 0;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    ctx->sourceRotation = degrees;
    return ctx->vpPipeline.SetStreamRotation(degrees) ? 1 : 0;
}

TELEM_EXPORT int telem_amd_set_decode_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    if (mode == 1) {
        if (!ctx->mfDecoderReady || !ctx->pSourceReader) {
            std::cerr << "[MF DECODER] D3D11VA mode rejected: decoder is not ready."
                      << std::endl;
            return 0;
        }
        if (!ctx->vpPipeline.SetStreamRotation(ctx->sourceRotation)) {
            std::cerr << "[MF DECODER] Failed to configure VP rotation="
                      << ctx->sourceRotation << std::endl;
            return 0;
        }
    }
    ctx->decodeMode = mode;
    std::cout << "[MF DECODER] Active mode="
              << (mode == 1 ? "GPU_HUD_D3D11VA" : "GPU_HUD_CPU_DECODE_REFERENCE")
              << " rotation=" << ctx->sourceRotation << std::endl;
    return 1;
}

// Replace only the source reader; device, VP compositor, HUD textures and AMF
// encoder remain alive. The caller must switch at a VideoTimeline boundary.
TELEM_EXPORT int telem_amd_switch_source(void* handle, const wchar_t* input_path) {
    if (!handle || !input_path || !*input_path) return 0;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    const UINT oldWidth = ctx->decoderWidth;
    const UINT oldHeight = ctx->decoderHeight;
    const DXGI_FORMAT oldFormat = ctx->decoderOutputFormat;
    if (ctx->pPendingDecodedTex) {
        ctx->pPendingDecodedTex->Release();
        ctx->pPendingDecodedTex = nullptr;
    }
    if (ctx->pSourceReader) {
        ctx->pSourceReader->Release();
        ctx->pSourceReader = nullptr;
    }
    ctx->mfDecoderReady = false;
    if (!OpenSourceReader(ctx, input_path)) return 0;
    if (ctx->decoderWidth != oldWidth || ctx->decoderHeight != oldHeight ||
        ctx->decoderOutputFormat != oldFormat) {
        std::cerr << "[MF DECODER] Source switch rejected: incompatible format "
                  << ctx->decoderWidth << "x" << ctx->decoderHeight << " format="
                  << static_cast<unsigned>(ctx->decoderOutputFormat) << std::endl;
        ctx->mfDecoderReady = false;
        ctx->pSourceReader->Release();
        ctx->pSourceReader = nullptr;
        return 0;
    }
    if (ctx->decodeMode == 1 && !ctx->vpPipeline.SetStreamRotation(ctx->sourceRotation)) {
        ctx->mfDecoderReady = false;
        ctx->pSourceReader->Release();
        ctx->pSourceReader = nullptr;
        return 0;
    }
    std::cout << "[MF DECODER] Native source switch complete." << std::endl;
    return 1;
}

// Seek the active source reader to a source-local timestamp.  This is used by
// production range exports; it does not change the global AMF output clock.
TELEM_EXPORT int telem_amd_seek_source(void* handle, INT64 timestamp100ns) {
    if (!handle || timestamp100ns < 0) return 0;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    if (!ctx->pSourceReader || ctx->decodeMode != 1) return 0;
    if (ctx->pPendingDecodedTex) {
        ctx->pPendingDecodedTex->Release();
        ctx->pPendingDecodedTex = nullptr;
    }
    PROPVARIANT position;
    PropVariantInit(&position);
    position.vt = VT_I8;
    position.hVal.QuadPart = timestamp100ns;
    const HRESULT hr = ctx->pSourceReader->SetCurrentPosition(GUID_NULL, position);
    PropVariantClear(&position);
    if (FAILED(hr)) {
        std::cerr << "[MF DECODER] Source seek failed: 0x" << std::hex << hr
                  << std::dec << std::endl;
        return 0;
    }
    ctx->mfEndOfStream = false;
    ctx->pendingTimestamp100ns = 0;
    ctx->pendingDuration100ns = 0;
    return 1;
}

// Return: 1 = D3D11 video sample ready, 2 = non-sample event/tick,
// 0 = clean EOS, -1 = fatal decode/acquisition error.
TELEM_EXPORT int telem_amd_read_video_sample(
    void* handle,
    UINT64* outFrameIndex,
    INT64* outTimestamp100ns,
    INT64* outDuration100ns,
    UINT* outStreamFlags,
    UINT* outDXGIFormat,
    UINT* outWidth,
    UINT* outHeight,
    UINT* outSubresource,
    UINT64* outTexturePointer
) {
    if (!handle) return -1;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    if (ctx->decodeMode != 1 || !ctx->pSourceReader || ctx->mfEndOfStream) return 0;
    if (ctx->pPendingDecodedTex) {
        std::cerr << "[MF DECODER] Read requested before pending sample was processed." << std::endl;
        return -1;
    }

    ctx->lastTimings = {};
    DWORD actualStream = 0;
    DWORD streamFlags = 0;
    LONGLONG timestamp = 0;
    IMFSample* sample = nullptr;
    const auto readStart = std::chrono::high_resolution_clock::now();
    const HRESULT readHR = ctx->pSourceReader->ReadSample(
        static_cast<DWORD>(MF_SOURCE_READER_FIRST_VIDEO_STREAM), 0,
        &actualStream, &streamFlags, &timestamp, &sample);
    const auto readEnd = std::chrono::high_resolution_clock::now();
    ctx->lastTimings.mfReadSampleMs = std::chrono::duration<double, std::milli>(
        readEnd - readStart).count();
    ctx->mfReadSampleCalls++;

    if (FAILED(readHR) || (streamFlags & MF_SOURCE_READERF_ERROR)) {
        if (sample) sample->Release();
        std::cerr << "[MF DECODER] ReadSample failed: 0x" << std::hex << readHR
                  << " flags=0x" << streamFlags << std::dec << std::endl;
        return -1;
    }
    if (streamFlags & (MF_SOURCE_READERF_NATIVEMEDIATYPECHANGED |
                       MF_SOURCE_READERF_CURRENTMEDIATYPECHANGED)) {
        ctx->mfFormatChanges++;
        if (!RefreshDecoderMediaType(ctx)) {
            if (sample) sample->Release();
            return -1;
        }
    }
    if (streamFlags & MF_SOURCE_READERF_STREAMTICK) {
        ctx->mfStreamTicks++;
    }
    if (streamFlags & MF_SOURCE_READERF_ENDOFSTREAM) {
        if (sample) sample->Release();
        ctx->mfEndOfStream = true;
        ctx->mfEndOfStreamEvents++;
        if (outStreamFlags) *outStreamFlags = streamFlags;
        return 0;
    }
    if (!sample) {
        ctx->mfNullSamples++;
        if (outStreamFlags) *outStreamFlags = streamFlags;
        return 2;
    }

    const auto acquireStart = std::chrono::high_resolution_clock::now();
    LONGLONG duration = 0;
    sample->GetSampleDuration(&duration);
    IMFMediaBuffer* mediaBuffer = nullptr;
    HRESULT hr = sample->GetBufferByIndex(0, &mediaBuffer);
    IMFDXGIBuffer* dxgiBuffer = nullptr;
    if (SUCCEEDED(hr) && mediaBuffer) {
        hr = mediaBuffer->QueryInterface(
            __uuidof(IMFDXGIBuffer), reinterpret_cast<void**>(&dxgiBuffer));
    }
    ID3D11Texture2D* texture = nullptr;
    UINT subresource = 0;
    if (SUCCEEDED(hr) && dxgiBuffer) {
        hr = dxgiBuffer->GetResource(
            __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&texture));
        if (SUCCEEDED(hr)) dxgiBuffer->GetSubresourceIndex(&subresource);
    }
    if (dxgiBuffer) dxgiBuffer->Release();
    if (mediaBuffer) mediaBuffer->Release();
    sample->Release();
    const auto acquireEnd = std::chrono::high_resolution_clock::now();
    ctx->lastTimings.mfSurfaceAcquireMs = std::chrono::duration<double, std::milli>(
        acquireEnd - acquireStart).count();

    if (FAILED(hr) || !texture) {
        if (texture) texture->Release();
        std::cerr << "[MF DECODER] Sample is not an IMFDXGIBuffer D3D11 texture: 0x"
                  << std::hex << hr << std::dec << std::endl;
        return -1;
    }

    D3D11_TEXTURE2D_DESC desc = {};
    texture->GetDesc(&desc);
    if ((desc.Format != DXGI_FORMAT_P010 && desc.Format != DXGI_FORMAT_NV12) ||
        desc.Width == 0 || desc.Height == 0 ||
        subresource >= desc.ArraySize) {
        std::cerr << "[MF DECODER] Unsupported decoder surface: format=" << desc.Format
                  << " size=" << desc.Width << "x" << desc.Height
                  << " array=" << desc.ArraySize << " subresource=" << subresource << std::endl;
        texture->Release();
        return -1;
    }

    const UINT64 frameIndex = ctx->mfVideoSamples;
    ctx->pPendingDecodedTex = texture;
    ctx->pendingSubresource = subresource;
    ctx->pendingTimestamp100ns = timestamp;
    ctx->pendingDuration100ns = duration;
    ctx->pendingStreamFlags = streamFlags;
    ctx->mfVideoSamples++;
    ctx->mfD3D11Surfaces++;
    if ((desc.BindFlags & D3D11_BIND_DECODER) != 0 && desc.ArraySize > 1) {
        ctx->mfHardwareConfirmed = true;
    }

    if (frameIndex < 3 || frameIndex == 30 || frameIndex == 300 ||
        frameIndex == 600 || frameIndex == 900) {
        std::cout << "[MF SAMPLE] frame=" << frameIndex
                  << " pts100ns=" << timestamp
                  << " duration100ns=" << duration
                  << " format=" << desc.Format
                  << " size=" << desc.Width << "x" << desc.Height
                  << " array=" << desc.ArraySize
                  << " subresource=" << subresource
                  << " bind=0x" << std::hex << desc.BindFlags << std::dec
                  << " texture=" << texture << std::endl;
    }

    if (outFrameIndex) *outFrameIndex = frameIndex;
    if (outTimestamp100ns) *outTimestamp100ns = timestamp;
    if (outDuration100ns) *outDuration100ns = duration;
    if (outStreamFlags) *outStreamFlags = streamFlags;
    if (outDXGIFormat) *outDXGIFormat = static_cast<UINT>(desc.Format);
    if (outWidth) *outWidth = desc.Width;
    if (outHeight) *outHeight = desc.Height;
    if (outSubresource) *outSubresource = subresource;
    if (outTexturePointer) {
        *outTexturePointer = static_cast<UINT64>(reinterpret_cast<uintptr_t>(texture));
    }
    return 1;
}

// Release a decoded sample without compositing or encoding it. SourceReader
// seeks may land on an earlier keyframe, so range exports use this entry point
// to advance to the requested source-local timestamp while leaving the global
// output frame clock untouched.
TELEM_EXPORT int telem_amd_discard_video_sample(void* handle) {
    if (!handle) return 0;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    if (!ctx->pPendingDecodedTex) return 0;
    ctx->pPendingDecodedTex->Release();
    ctx->pPendingDecodedTex = nullptr;
    ctx->pendingSubresource = 0;
    ctx->pendingTimestamp100ns = 0;
    ctx->pendingDuration100ns = 0;
    ctx->pendingStreamFlags = 0;
    return 1;
}

// Helper: Convert NV12 to RGBA in CPU memory for diagnostic checkpoint PNGs
static std::vector<uint8_t> ConvertNV12ToRGBA(const uint8_t* yData, const uint8_t* uvData, UINT w, UINT h, UINT yPitch, UINT uvPitch) {
    std::vector<uint8_t> rgba(w * h * 4, 255);
    for (UINT y = 0; y < h; ++y) {
        for (UINT x = 0; x < w; ++x) {
            int Y = yData[y * yPitch + x];
            size_t uvIndex = (y / 2) * uvPitch + (x / 2) * 2;
            int U = uvData[uvIndex] - 128;
            int V = uvData[uvIndex + 1] - 128;

            int R = (int)(Y + 1.402 * V);
            int G = (int)(Y - 0.344136 * U - 0.714136 * V);
            int B = (int)(Y + 1.772 * U);

            size_t idx = (y * w + x) * 4;
            rgba[idx + 0] = (uint8_t)(R < 0 ? 0 : (R > 255 ? 255 : R));
            rgba[idx + 1] = (uint8_t)(G < 0 ? 0 : (G > 255 ? 255 : G));
            rgba[idx + 2] = (uint8_t)(B < 0 ? 0 : (B > 255 ? 255 : B));
            rgba[idx + 3] = 255;
        }
    }
    return rgba;
}

// Fast CPU Alpha Blend: RGBA HUD over NV12 Base Video
static void BlendRGBAToNV12(
    uint8_t* pNV12,
    UINT width,
    UINT height,
    UINT stride,
    const uint8_t* pRGBA
) {
    if (!pNV12 || !pRGBA) return;

    uint8_t* pY = pNV12;
    uint8_t* pUV = pNV12 + (height * stride);

    for (UINT y = 0; y < height; ++y) {
        for (UINT x = 0; x < width; ++x) {
            size_t rgbaIdx = (y * width + x) * 4;
            uint8_t a = pRGBA[rgbaIdx + 3];
            if (a == 0) continue;

            uint8_t r = pRGBA[rgbaIdx + 0];
            uint8_t g = pRGBA[rgbaIdx + 1];
            uint8_t b = pRGBA[rgbaIdx + 2];

            int Y_hud = ((66 * r + 129 * g + 25 * b + 128) >> 8) + 16;
            if (Y_hud < 0) Y_hud = 0;
            if (Y_hud > 255) Y_hud = 255;

            size_t yIdx = y * stride + x;
            if (a == 255) {
                pY[yIdx] = (uint8_t)Y_hud;
            } else {
                int yOrig = pY[yIdx];
                pY[yIdx] = (uint8_t)((Y_hud * a + yOrig * (255 - a)) / 255);
            }

            if ((y % 2 == 0) && (x % 2 == 0)) {
                int U_hud = ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128;
                int V_hud = ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128;
                if (U_hud < 0) U_hud = 0; if (U_hud > 255) U_hud = 255;
                if (V_hud < 0) V_hud = 0; if (V_hud > 255) V_hud = 255;

                size_t uvIdx = (y / 2) * stride + x;
                if (a == 255) {
                    pUV[uvIdx + 0] = (uint8_t)U_hud;
                    pUV[uvIdx + 1] = (uint8_t)V_hud;
                } else {
                    int uOrig = pUV[uvIdx + 0];
                    int vOrig = pUV[uvIdx + 1];
                    pUV[uvIdx + 0] = (uint8_t)((U_hud * a + uOrig * (255 - a)) / 255);
                    pUV[uvIdx + 1] = (uint8_t)((V_hud * a + vOrig * (255 - a)) / 255);
                }
            }
        }
    }
}

static DXGI_FORMAT DXGIFormatFromMFSubtype(const GUID& subtype) {
    if (IsEqualGUID(subtype, MFVideoFormat_P010)) return DXGI_FORMAT_P010;
    if (IsEqualGUID(subtype, MFVideoFormat_NV12)) return DXGI_FORMAT_NV12;
    return DXGI_FORMAT_UNKNOWN;
}

static bool RefreshDecoderMediaType(TelemAMDContext* ctx) {
    if (!ctx || !ctx->pSourceReader) return false;
    IMFMediaType* mediaType = nullptr;
    HRESULT hr = ctx->pSourceReader->GetCurrentMediaType(
        static_cast<DWORD>(MF_SOURCE_READER_FIRST_VIDEO_STREAM), &mediaType);
    if (FAILED(hr) || !mediaType) return false;

    GUID subtype = GUID_NULL;
    UINT32 width = 0;
    UINT32 height = 0;
    UINT32 primaries = 0;
    UINT32 transfer = 0;
    UINT32 matrix = 0;
    UINT32 range = 0;
    UINT32 rotation = 0;
    mediaType->GetGUID(MF_MT_SUBTYPE, &subtype);
    MFGetAttributeSize(mediaType, MF_MT_FRAME_SIZE, &width, &height);
    mediaType->GetUINT32(MF_MT_VIDEO_PRIMARIES, &primaries);
    mediaType->GetUINT32(MF_MT_TRANSFER_FUNCTION, &transfer);
    mediaType->GetUINT32(MF_MT_YUV_MATRIX, &matrix);
    mediaType->GetUINT32(MF_MT_VIDEO_NOMINAL_RANGE, &range);
    // Container rotation is supplied by the production probe because the
    // MinGW Media Foundation headers do not expose it consistently here.

    ctx->decoderOutputFormat = DXGIFormatFromMFSubtype(subtype);
    ctx->decoderWidth = width;
    ctx->decoderHeight = height;
    if (rotation == 90 || rotation == 180 || rotation == 270) {
        ctx->sourceRotation = rotation;
    }
    std::cout << "[MF DECODER TYPE] DXGI format=" << static_cast<UINT>(ctx->decoderOutputFormat)
              << " size=" << width << "x" << height
              << " primaries=" << primaries
              << " transfer=" << transfer
              << " matrix=" << matrix
              << " range=" << range
              << " rotation=" << rotation << std::endl;
    mediaType->Release();
    return ctx->decoderOutputFormat == DXGI_FORMAT_P010 ||
           ctx->decoderOutputFormat == DXGI_FORMAT_NV12;
}

TELEM_EXPORT void* telem_amd_create(
    const wchar_t* input_path,
    const wchar_t* output_path,
    UINT width,
    UINT height,
    UINT fps_num,
    UINT fps_den
) {
    ConfigureNativeRenderLogging();
    MFStartup(MF_VERSION);

    TelemAMDContext* ctx = new TelemAMDContext();
    ctx->width = width;
    ctx->height = height;
    ctx->fpsNum = fps_num;
    ctx->fpsDen = fps_den;

    char mbsOut[512] = {};
    wcstombs(mbsOut, output_path, 512);
    ctx->outputPath = std::string(mbsOut);
    std::string h265Path = ctx->outputPath + ".h265";
    ctx->h265Out.open(h265Path, std::ios::binary);

    // ETAP 5R — opt-in native process_frame accounting.
    const char* faEnv = getenv("AMD_NATIVE_FRAME_ACCOUNTING");
    ctx->frameAccountEnabled = (faEnv && faEnv[0] == '1');
    ctx->vpPipeline.SetFrameAccount(ctx->frameAccountEnabled);
    if (ctx->frameAccountEnabled) {
        std::cout << "[TELEM AMD DLL] AMD_NATIVE_FRAME_ACCOUNTING=1: native "
                     "per-frame process_frame substage trace enabled." << std::endl;
    }
    // ETAP 5S — VP stream-state mode (REFERENCE | STATIC_CACHE | REORDER).
    const char* vpModeEnv = getenv("AMD_VP_STATE_MODE");
    int vpMode = 0;
    if (vpModeEnv) {
        std::string m(vpModeEnv);
        if (m == "STATIC_CACHE") vpMode = 1;
        else if (m == "REORDER") vpMode = 2;
    }
    ctx->vpPipeline.SetVpStateMode(vpMode);
    std::cout << "[TELEM AMD DLL] AMD_VP_STATE_MODE="
              << (vpMode == 1 ? "STATIC_CACHE" : (vpMode == 2 ? "REORDER" : "REFERENCE"))
              << std::endl;
    // ETAP 5V: setter ordering diagnostic.  Default is the production order;
    // only the three known same-semantics permutations are accepted.
    const char* orderEnv = getenv("AMD_VP_SETTER_ORDER");
    int setterOrder = 0;
    if (orderEnv) {
        std::string order(orderEnv);
        if (order == "SRC_FORMAT_DST") setterOrder = 1;
        else if (order == "DST_SRC_FORMAT") setterOrder = 2;
    }
    ctx->vpPipeline.SetVpSetterOrder(setterOrder);
    // ETAP 5U - individual VP setter-cache candidates.  Opt-in only; these
    // are intentionally independent of STATIC_CACHE and remain disabled by
    // the canonical production resolver.
    const auto vpCacheEnabled = [](const char* name) {
        const char* value = getenv(name);
        return value && (value[0] == '1' || value[0] == 'y' || value[0] == 'Y');
    };
    ctx->vpPipeline.SetVpIndividualCaches(
        vpCacheEnabled("AMD_VP_CACHE_FRAME_FORMAT"),
        vpCacheEnabled("AMD_VP_CACHE_SOURCE_RECT"),
        vpCacheEnabled("AMD_VP_CACHE_DEST_RECT"));
    // ETAP 5U/5V — runtime VP output surface pool size (4..8).  Must be set
    // before vpPipeline.Initialize().  Production default is 8 (ETAP 5V);
    // AMD_VP_POOL_SIZE override honored.  Safe fallback 8->6->4 inside
    // SetupVideoProcessor on allocation/resource-creation failure only.
    const char* poolEnv = getenv("AMD_VP_POOL_SIZE");
    UINT poolSize = 8;
    if (poolEnv) {
        const UINT requested = static_cast<UINT>(atoi(poolEnv));
        if (requested == 6 || requested == 8 || requested == 10 || requested == 12) {
            poolSize = requested;
        }
    }
    ctx->vpPipeline.SetPoolSize(poolSize);
    std::cout << "[TELEM AMD DLL] AMD_VP_POOL_SIZE=" << poolSize << std::endl;
    // ETAP 5W: diagnostic-only persistent VideoProcessor object ring.
    // This is independent from the NV12 output-surface pool.
    const char* processorRingEnv = getenv("AMD_VP_PROCESSOR_RING_SIZE");
    UINT processorRingSize = 1;
    if (processorRingEnv) {
        const UINT requested = static_cast<UINT>(atoi(processorRingEnv));
        if (requested >= 1 && requested <= 3) processorRingSize = requested;
    }
    ctx->vpPipeline.SetProcessorRingSize(processorRingSize);
    std::cout << "[TELEM AMD DLL] AMD_VP_PROCESSOR_RING_SIZE="
              << processorRingSize << std::endl;
    const char* baseConvertEnv = getenv("AMD_BASE_CONVERT_MODE");
    const bool baseConvertCompute = baseConvertEnv &&
        _stricmp(baseConvertEnv, "COMPUTE_P010_NV12") == 0;
    ctx->vpPipeline.SetBaseConvertMode(baseConvertCompute);
    std::cout << "[TELEM AMD DLL] AMD_BASE_CONVERT_MODE="
              << (baseConvertCompute ? "COMPUTE_P010_NV12" : "VP_REFERENCE") << std::endl;
    // ETAP 5V — debug-only pool lifecycle stats (AMD_POOL_LIFECYCLE_STATS=1).
    const char* plsEnv = getenv("AMD_POOL_LIFECYCLE_STATS");
    const bool poolLs = (plsEnv && plsEnv[0] == '1');
    ctx->vpPipeline.SetPoolLifecycleStats(poolLs);
    if (poolLs) std::cout << "[TELEM AMD DLL] AMD_POOL_LIFECYCLE_STATS=1" << std::endl;
    // ETAP 5U — AMF QueryOutput policy (REFERENCE | DRAIN_READY).
    const char* qmEnv = getenv("AMD_AMF_QUERY_MODE");
    int qm = 0;
    if (qmEnv) {
        std::string m(qmEnv);
        if (m == "DRAIN_READY") qm = 1;
    }
    ctx->amfQueryMode = qm;
    std::cout << "[TELEM AMD DLL] AMD_AMF_QUERY_MODE="
              << (qm == 1 ? "DRAIN_READY" : "REFERENCE") << std::endl;
    // AMD_QUEUE_DEPTH & AMD_CPU_GPU_PIPELINE
    const char* pipeEnv = getenv("AMD_CPU_GPU_PIPELINE");
    const bool isAsync = !pipeEnv || (_stricmp(pipeEnv, "SYNC") != 0);
    const char* qdEnv = getenv("AMD_QUEUE_DEPTH");
    int qd = isAsync ? 2 : 1;
    if (qdEnv) {
        int parsed = atoi(qdEnv);
        if (parsed >= 1 && parsed <= 8) qd = parsed;
    }
    ctx->queueDepth = qd;
    std::cout << "[TELEM AMD DLL] AMD_QUEUE_DEPTH=" << qd
              << " (pipeline=" << (isAsync ? "ASYNC" : "SYNC") << ")" << std::endl;
    // ETAP 5T — async GPU timestamp timeline (enabled after VP init below).
    const char* gpuTsEnv = getenv("AMD_GPU_TIMESTAMP_PROFILE");
    const bool gpuTsEnabled = (gpuTsEnv && gpuTsEnv[0] == '1');
    std::cout << "[TELEM AMD DLL] AMD_GPU_TIMESTAMP_PROFILE="
              << (gpuTsEnabled ? "ON" : "OFF") << std::endl;
    // ETAP 5V: persistent non-blocking D3D11_QUERY_EVENT evidence.
    const char* completionEnv = getenv("AMD_VP_COMPLETION_PROBE");
    const bool completionProbe = (completionEnv && completionEnv[0] == '1');
    // ETAP 8K: Unified Fused NV12 Compositor production mode
    const char* fusedEnv = getenv("AMD_FUSED_COMPOSITOR");
    const int fusedMode = fusedEnv ? atoi(fusedEnv) : 1;
    std::cout << "[TELEM AMD DLL] AMD_NV12_COMPOSITOR="
              << (fusedMode == 1 ? "FUSED (production single-range)" : "LEGACY_SEPARATE (diagnostic)")
              << std::endl;
    std::cout << "[TELEM AMD DLL] AMD_RANGE_NORMALIZE="
              << (fusedMode == 1 ? "FUSED_SINGLE" : "SEPARATE_PASS")
              << std::endl;
    std::cout << "[TELEM AMD DLL] AMD_NORMALIZE_PASSES="
              << (fusedMode == 1 ? 0 : (getenv("AMD_NORMALIZE_PASSES") ? atoi(getenv("AMD_NORMALIZE_PASSES")) : 1))
              << std::endl;
    // ETAP 5T diagnostic: HUD GPU compositor OFF.
    const char* hudOffEnv = getenv("AMD_GPU_HUD_OFF");
    const bool gpuHudOff = (hudOffEnv && hudOffEnv[0] == '1');
    ctx->vpPipeline.SetGpuHudOff(gpuHudOff);
    if (gpuHudOff) std::cout << "[TELEM AMD DLL] AMD_GPU_HUD_OFF=1 (diagnostic)" << std::endl;

    // 1. Initialize D3D11 Device
    UINT createDeviceFlags = D3D11_CREATE_DEVICE_VIDEO_SUPPORT;
    D3D_FEATURE_LEVEL featureLevels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
    D3D_FEATURE_LEVEL featureLevel;

    HRESULT hr = D3D11CreateDevice(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        createDeviceFlags, featureLevels, 2,
        D3D11_SDK_VERSION, &ctx->pDevice, &featureLevel, &ctx->pContext
    );
    if (FAILED(hr)) {
        std::cerr << "[TELEM AMD DLL] D3D11CreateDevice failed: 0x" << std::hex << hr << std::dec << std::endl;
        delete ctx;
        return nullptr;
    }

    // 2. Initialize VideoProcessor Pipeline
    // ETAP 5W debug: AMD_DEBUG_NO_VP=1 skips the VP pipeline (device-ref leak
    // isolation).  For create/close refcount tests only (no frames).
    const bool skipVp = (getenv("AMD_DEBUG_NO_VP") != nullptr);
    if (skipVp) {
        std::cout << "[TELEM AMD DLL] AMD_DEBUG_NO_VP=1 (diagnostic skip)" << std::endl;
    }
    if (!skipVp) {
        if (!ctx->vpPipeline.Initialize(ctx->pDevice, ctx->pContext, width, height)) {
            std::cerr << "[TELEM AMD DLL] VP Pipeline Initialize failed!" << std::endl;
            delete ctx;
            return nullptr;
        }
        if (!ctx->vpPipeline.SetupVideoProcessor(DXGI_FORMAT_P010, DXGI_FORMAT_NV12)) {
            std::cerr << "[TELEM AMD DLL] VP Setup failed!" << std::endl;
            delete ctx;
            return nullptr;
        }
        // ETAP 5V — report the effective pool size (fallback may have reduced it).
        if (ctx->vpPipeline.GetPoolSize() != poolSize) {
            std::cout << "[TELEM AMD DLL] VP pool effective size = "
                      << ctx->vpPipeline.GetPoolSize() << " (requested " << poolSize
                      << ")" << std::endl;
        }
        // ETAP 5T: enable the GPU timestamp ring now that the device is ready.
        ctx->vpPipeline.SetGpuTimestampProfile(gpuTsEnabled);
        ctx->vpPipeline.SetVpCompletionProbe(completionProbe);
    }

    // 3. Initialize AMF HEVC Encoder on shared D3D11 device
    // ETAP 5W debug: AMD_DEBUG_NO_AMF=1 skips AMF init (device-ref leak isolation).
    const bool skipAmf = (getenv("AMD_DEBUG_NO_AMF") != nullptr);
    if (!skipAmf) {
        if (!ctx->amfEncoder.Initialize(ctx->pDevice, width, height, fps_num, fps_den)) {
            std::cerr << "[TELEM AMD DLL] AMF Encoder Initialize failed!" << std::endl;
            delete ctx;
            return nullptr;
        }
    } else {
        std::cout << "[TELEM AMD DLL] AMD_DEBUG_NO_AMF=1 (diagnostic skip)" << std::endl;
    }

    // 4. Initialize Media Foundation Decoder for Input Video File
    // ETAP 5W debug: AMD_DEBUG_NO_MF=1 skips the MF source reader.
    // AMD_DECODE_MODE=CPU disables MF decoder completely.
    const char* decEnv = getenv("AMD_DECODE_MODE");
    const bool isCpuDecodeEnv = decEnv && (_stricmp(decEnv, "CPU") == 0 || strcmp(decEnv, "0") == 0);
    const bool skipMf = (getenv("AMD_DEBUG_NO_MF") != nullptr) || isCpuDecodeEnv;
    if (isCpuDecodeEnv) {
        ctx->decodeMode = 0;
        std::cout << "[TELEM AMD DLL] AMD_DECODE_MODE=CPU -> D3D11VA MF decoder disabled." << std::endl;
    }
    if (skipMf && !isCpuDecodeEnv) {
        std::cout << "[TELEM AMD DLL] AMD_DEBUG_NO_MF=1 (diagnostic skip)" << std::endl;
    }
    if (input_path && wcslen(input_path) > 0 && !skipMf) {
        hr = MFCreateDXGIDeviceManager(&ctx->dxgiResetToken, &ctx->pDXGIManager);
        if (SUCCEEDED(hr)) {
            ctx->pDXGIManager->ResetDevice(ctx->pDevice, ctx->dxgiResetToken);
            if (!OpenSourceReader(ctx, input_path))
                std::cerr << "[TELEM AMD DLL] MediaFoundation decoder initialization failed." << std::endl;
            else
                std::cout << "[TELEM AMD DLL] MediaFoundation D3D11VA decoder configured." << std::endl;
        }
    }

    // 5. Create Standby Base P010 (10-bit) Texture & Upload Staging Texture
    D3D11_TEXTURE2D_DESC p010Desc = {};
    p010Desc.Width = width;
    p010Desc.Height = height;
    p010Desc.MipLevels = 1;
    p010Desc.ArraySize = 1;
    p010Desc.Format = DXGI_FORMAT_P010;
    p010Desc.SampleDesc.Count = 1;
    p010Desc.Usage = D3D11_USAGE_DEFAULT;
    p010Desc.BindFlags = D3D11_BIND_DECODER | D3D11_BIND_SHADER_RESOURCE;
    ctx->pDevice->CreateTexture2D(&p010Desc, nullptr, &ctx->pBaseP010Tex);

    D3D11_TEXTURE2D_DESC stagingDesc = p010Desc;
    stagingDesc.Usage = D3D11_USAGE_STAGING;
    stagingDesc.BindFlags = 0;
    stagingDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    stagingDesc.MiscFlags = 0;
    ctx->pDevice->CreateTexture2D(&stagingDesc, nullptr, &ctx->pUploadStagingTex);

    std::cout << "[TELEM AMD DLL] telem_amd_create SUCCESS. Width: " << width << " Height: " << height << std::endl;
    return (void*)ctx;
}

TELEM_EXPORT int telem_amd_update_hud(
    void* handle,
    const uint8_t* pRGBA,
    UINT width,
    UINT height,
    UINT stride
) {
    if (!handle || !pRGBA) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    const auto copyStart = std::chrono::high_resolution_clock::now();
    size_t sz = (size_t)height * stride;
    if (ctx->currentHUDRGBA.size() != sz) {
        ctx->currentHUDRGBA.resize(sz);
    }
    memcpy(ctx->currentHUDRGBA.data(), pRGBA, sz);
    const auto copyEnd = std::chrono::high_resolution_clock::now();
    ctx->lastTimings.hudNativeCopyMs = std::chrono::duration<double, std::milli>(
        copyEnd - copyStart).count();
    if (ctx->hudMode == 1) {
        const auto uploadStart = std::chrono::high_resolution_clock::now();
        size_t uploadedBytes = 0;
        bool textureCreated = false;
        if (!ctx->vpPipeline.UpdateHUDTexture(
                width, height, ctx->currentHUDRGBA.data(), stride,
                nullptr, 0, true, &uploadedBytes, &textureCreated)) {
            std::cerr << "[TELEM AMD DLL] GPU HUD texture upload failed." << std::endl;
            return 0;
        }
        const auto uploadEnd = std::chrono::high_resolution_clock::now();
        ctx->lastTimings.hudUploadMs = std::chrono::duration<double, std::milli>(
            uploadEnd - uploadStart).count();
        if (textureCreated) ctx->hudTextureCreates++;
        ctx->hudTextureUploads++;
        ctx->hudUploadedBytes += uploadedBytes;
        ctx->hudUploadedRects++;
    }
    ctx->hudUpdates++;
    return 1;
}

struct TelemAMDHUDRect {
    UINT x;
    UINT y;
    UINT width;
    UINT height;
};

TELEM_EXPORT int telem_amd_update_hud_regions(
    void* handle,
    const uint8_t* pRGBA,
    UINT width,
    UINT height,
    UINT stride,
    const TelemAMDHUDRect* rects,
    UINT rectCount,
    int fullUpload
) {
    if (!handle || !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (ctx->hudMode != 1) return 0;

    static_assert(sizeof(TelemAMDHUDRect) == sizeof(HUDDirtyRect), "HUD rect ABI mismatch");
    ctx->lastTimings.hudNativeCopyMs = 0.0;
    const auto uploadStart = std::chrono::high_resolution_clock::now();
    size_t uploadedBytes = 0;
    bool textureCreated = false;
    if (!ctx->vpPipeline.UpdateHUDTexture(
            width, height, pRGBA, stride,
            reinterpret_cast<const HUDDirtyRect*>(rects), rectCount,
            fullUpload != 0, &uploadedBytes, &textureCreated)) {
        std::cerr << "[TELEM AMD DLL] GPU HUD region upload failed." << std::endl;
        return 0;
    }
    const auto uploadEnd = std::chrono::high_resolution_clock::now();
    ctx->lastTimings.hudUploadMs = std::chrono::duration<double, std::milli>(
        uploadEnd - uploadStart).count();
    if (textureCreated) ctx->hudTextureCreates++;
    if (uploadedBytes > 0) ctx->hudTextureUploads++;
    ctx->hudUploadedBytes += uploadedBytes;
    ctx->hudUploadedRects += (fullUpload != 0 || textureCreated) ? 1 : rectCount;
    ctx->hudUpdates++;
    return 1;
}

TELEM_EXPORT int telem_amd_update_video_frame(
    void* handle,
    const uint8_t* pNV12,
    UINT width,
    UINT height,
    UINT stride
) {
    if (!handle || !pNV12) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    if (!ctx->pBaseP010Tex || !ctx->pUploadStagingTex) return 0;

    D3D11_MAPPED_SUBRESOURCE map = {};
    HRESULT hr = ctx->pContext->Map(ctx->pUploadStagingTex, 0, D3D11_MAP_WRITE, 0, &map);
    if (SUCCEEDED(hr) && map.pData) {
        const double hudNativeCopyMs = ctx->lastTimings.hudNativeCopyMs;
        const double hudUploadMs = ctx->lastTimings.hudUploadMs;
        ctx->lastTimings = {};
        ctx->lastTimings.hudNativeCopyMs = hudNativeCopyMs;
        ctx->lastTimings.hudUploadMs = hudUploadMs;
        uint8_t* pDstY = (uint8_t*)map.pData;
        const uint8_t* pSrcY = pNV12;
        UINT dstPitch = map.RowPitch;

        const auto memcpyStart = std::chrono::high_resolution_clock::now();
        // Copy Y plane (height rows)
        if (dstPitch == stride && dstPitch == width) {
            memcpy(pDstY, pSrcY, width * height);
        } else {
            for (UINT y = 0; y < height; ++y) {
                memcpy(pDstY + y * dstPitch, pSrcY + y * stride, width);
            }
        }

        // Copy UV plane (height / 2 rows)
        uint8_t* pDstUV = pDstY + (height * dstPitch);
        const uint8_t* pSrcUV = pNV12 + (height * stride);
        if (dstPitch == stride && dstPitch == width) {
            memcpy(pDstUV, pSrcUV, width * (height / 2));
        } else {
            for (UINT y = 0; y < height / 2; ++y) {
                memcpy(pDstUV + y * dstPitch, pSrcUV + y * stride, width);
            }
        }
        const auto memcpyEnd = std::chrono::high_resolution_clock::now();
        ctx->lastTimings.stagingMemcpyMs = std::chrono::duration<double, std::milli>(
            memcpyEnd - memcpyStart).count();

        // If HUD overlay buffer is present, blend HUD directly onto mapped NV12 before unmapping
        const auto blendStart = std::chrono::high_resolution_clock::now();
        if (ctx->hudEnabled && ctx->hudMode == 0 && !ctx->currentHUDRGBA.empty()) {
            BlendRGBAToNV12(pDstY, width, height, dstPitch, ctx->currentHUDRGBA.data());
            ctx->blendCalls++;
        }
        const auto blendEnd = std::chrono::high_resolution_clock::now();
        ctx->lastTimings.blendMs = std::chrono::duration<double, std::milli>(
            blendEnd - blendStart).count();

        const auto copyStart = std::chrono::high_resolution_clock::now();
        ctx->pContext->Unmap(ctx->pUploadStagingTex, 0);

        // Fast GPU Copy to Default Base Texture
        ctx->pContext->CopyResource(ctx->pBaseP010Tex, ctx->pUploadStagingTex);
        const auto copyEnd = std::chrono::high_resolution_clock::now();
        ctx->lastTimings.copySubmitMs = std::chrono::duration<double, std::milli>(
            copyEnd - copyStart).count();
        ctx->hasUpdatedVideoFrame = true;
        ctx->videoUpdates++;
        return 1;
    }
    return 0;
}

TELEM_EXPORT int telem_amd_update_video_frame_p010(
    void* handle,
    const uint8_t* pP010,
    UINT width,
    UINT height,
    UINT stride,
    double* out_upload_ms
) {
    if (!handle || !pP010) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (!ctx->pBaseP010Tex || !ctx->pUploadStagingTex) return 0;

    const auto uploadStart = std::chrono::high_resolution_clock::now();
    D3D11_MAPPED_SUBRESOURCE map = {};
    HRESULT hr = ctx->pContext->Map(ctx->pUploadStagingTex, 0, D3D11_MAP_WRITE, 0, &map);
    if (FAILED(hr) || !map.pData) return 0;

    uint8_t* pDstY = (uint8_t*)map.pData;
    const uint8_t* pSrcY = pP010;
    const UINT dstPitch = map.RowPitch;
    const UINT srcPitch = (stride > 0) ? stride : (width * 2);
    const size_t yBytes = (size_t)height * srcPitch;
    const size_t uvBytes = (size_t)(height / 2) * srcPitch;

    if (dstPitch == srcPitch) {
        memcpy(pDstY, pSrcY, yBytes);
        uint8_t* pDstUV = pDstY + ((size_t)height * dstPitch);
        const uint8_t* pSrcUV = pSrcY + yBytes;
        memcpy(pDstUV, pSrcUV, uvBytes);
    } else {
        for (UINT y = 0; y < height; ++y) {
            memcpy(pDstY + y * dstPitch, pSrcY + y * srcPitch, width * 2);
        }
        uint8_t* pDstUV = pDstY + ((size_t)height * dstPitch);
        const uint8_t* pSrcUV = pSrcY + yBytes;
        for (UINT y = 0; y < height / 2; ++y) {
            memcpy(pDstUV + y * dstPitch, pSrcUV + y * srcPitch, width * 2);
        }
    }

    ctx->pContext->Unmap(ctx->pUploadStagingTex, 0);
    ctx->pContext->CopyResource(ctx->pBaseP010Tex, ctx->pUploadStagingTex);
    ctx->hasUpdatedVideoFrame = true;
    ctx->videoUpdates++;

    const auto uploadEnd = std::chrono::high_resolution_clock::now();
    const double upMs = std::chrono::duration<double, std::milli>(uploadEnd - uploadStart).count();
    if (out_upload_ms) *out_upload_ms = upMs;
    ctx->lastTimings.stagingMemcpyMs = upMs;
    return 1;
}

static bool EnsureDecoderCopyTexture(
    TelemAMDContext* ctx,
    const D3D11_TEXTURE2D_DESC& sourceDesc
) {
    if (!ctx || !ctx->pDevice) return false;
    if (ctx->pDecodedCopyTex) {
        D3D11_TEXTURE2D_DESC existing = {};
        ctx->pDecodedCopyTex->GetDesc(&existing);
        if (existing.Width == sourceDesc.Width && existing.Height == sourceDesc.Height &&
            existing.Format == sourceDesc.Format) {
            return true;
        }
        ctx->pDecodedCopyTex->Release();
        ctx->pDecodedCopyTex = nullptr;
    }

    D3D11_TEXTURE2D_DESC copyDesc = {};
    copyDesc.Width = sourceDesc.Width;
    copyDesc.Height = sourceDesc.Height;
    copyDesc.MipLevels = 1;
    copyDesc.ArraySize = 1;
    copyDesc.Format = sourceDesc.Format;
    copyDesc.SampleDesc.Count = 1;
    copyDesc.Usage = D3D11_USAGE_DEFAULT;
    copyDesc.BindFlags = D3D11_BIND_DECODER | D3D11_BIND_SHADER_RESOURCE;
    const HRESULT hr = ctx->pDevice->CreateTexture2D(
        &copyDesc, nullptr, &ctx->pDecodedCopyTex);
    if (FAILED(hr)) {
        std::cerr << "[MF DECODER] Compatible GPU copy texture creation failed: 0x"
                  << std::hex << hr << std::dec << std::endl;
        return false;
    }
    return true;
}

TELEM_EXPORT int telem_amd_process_frame(
    void* handle,
    UINT frame_index,
    int enable_hud
) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    ID3D11Texture2D* pDecodedTex = ctx->pBaseP010Tex;
    UINT sampleSlice = 0;
    const bool d3d11Decode = ctx->decodeMode == 1;
    // ETAP 5R — opt-in per-frame native accounting.
    const bool fa = ctx->frameAccountEnabled;
    const auto pfStart = std::chrono::steady_clock::now();
    NativeFrameRec rec;
    rec.frame = frame_index;
    bool decoderCopyHappened = false;
    const auto tSurfAcq = std::chrono::steady_clock::now();
    if (d3d11Decode) {
        if (!ctx->pPendingDecodedTex) {
            std::cerr << "[MF DECODER] Process requested without a pending D3D11 sample." << std::endl;
            return 0;
        }
        pDecodedTex = ctx->pPendingDecodedTex;
        sampleSlice = ctx->pendingSubresource;

        if (ctx->vpPipeline.CanUseInputSurface(pDecodedTex, sampleSlice)) {
            ctx->directDecoderSurfaceFrames++;
        } else {
            D3D11_TEXTURE2D_DESC sourceDesc = {};
            pDecodedTex->GetDesc(&sourceDesc);
            if (!EnsureDecoderCopyTexture(ctx, sourceDesc)) return 0;
            const auto copyStart = std::chrono::high_resolution_clock::now();
            ctx->pContext->CopySubresourceRegion(
                ctx->pDecodedCopyTex, 0, 0, 0, 0,
                pDecodedTex, sampleSlice, nullptr);
            const auto copyEnd = std::chrono::high_resolution_clock::now();
            decoderCopyHappened = true;
            ctx->lastTimings.baseGpuCopyMs = std::chrono::duration<double, std::milli>(
                copyEnd - copyStart).count();
            pDecodedTex = ctx->pDecodedCopyTex;
            sampleSlice = 0;
            ctx->decoderGpuCopyFrames++;
        }
    } else {
        if (!ctx->hasUpdatedVideoFrame) {
            std::cerr << "[CPU DECODE REFERENCE] Process requested without uploaded P010." << std::endl;
            return 0;
        }
        ctx->hasUpdatedVideoFrame = false;
    }
    if (fa) {
        rec.surfAcquireMs = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - tSurfAcq).count();
    }
    rec.decoderCopy = decoderCopyHappened ? 1 : 0;

    // Step 1: ID3D11VideoProcessor Hardware Stream 0 (Base Video) + Stream 1 (HUD) Composition
    ID3D11Texture2D* pOutNV12Tex = nullptr;
    VPPipelineStats vpStats = {};
    bool doHUD = ctx->hudEnabled && ctx->hudMode == 1 && (enable_hud != 0);
    const auto tVpStart = std::chrono::steady_clock::now();
    if (!ctx->vpPipeline.ProcessFrame(
            pDecodedTex, sampleSlice, &pOutNV12Tex, doHUD, d3d11Decode, &vpStats,
            frame_index, ctx->diagnosticsEnabled, ctx->profilingEnabled)) {
        std::cerr << "[TELEM AMD DLL] VP ProcessFrame failed on frame " << frame_index << std::endl;
        if (d3d11Decode && ctx->pPendingDecodedTex) {
            ctx->pPendingDecodedTex->Release();
            ctx->pPendingDecodedTex = nullptr;
        }
        return 0;
    }
    const auto tVpEnd = std::chrono::steady_clock::now();
    if (fa) {
        rec.vpTotalMs = std::chrono::duration<double, std::milli>(tVpEnd - tVpStart).count();
        rec.vpSetupMs = vpStats.setup_ms;
        rec.vpCreateViewMs = vpStats.create_view_ms;
        rec.vpSetStreamMs = vpStats.set_stream_ms;
        rec.vpSetterFmtMs = vpStats.setter_fmt_ms;
        rec.vpSetterSrcRectMs = vpStats.setter_src_rect_ms;
        rec.vpSetterDstRectMs = vpStats.setter_dst_rect_ms;
        rec.firstVpApi = vpStats.first_vp_api;
        rec.firstVpApiMs = vpStats.first_vp_api_ms;
        rec.vpSequenceTotalMs = vpStats.vp_sequence_total_ms;
        rec.vpBltMs = vpStats.blt_ms;
        rec.vpSubmitWindowMs = vpStats.submit_window_ms;
        rec.vpRangePassMs = vpStats.range_pass_ms;
        rec.clearPrevAboveMs = vpStats.clear_prev_above_ms;
        rec.vpChartBlendMs = vpStats.chart_blend_ms;
        rec.chartFlushMs = vpStats.chart_flush_ms;
        rec.vpGaugeBlendMs = vpStats.gauge_blend_ms;
        rec.gaugeFlushMs = vpStats.gauge_flush_ms;
        rec.mapResampleMs = vpStats.map_resample_ms;
        rec.mapBlendMs = vpStats.map_blend_ms;
        rec.mapFlush1Ms = vpStats.map_flush1_ms;
        rec.mapFlush2Ms = vpStats.map_flush2_ms;
        rec.aboveBlendMs = vpStats.above_blend_ms;
        rec.aboveFlushMs = vpStats.above_flush_ms;
        rec.flushTotalMs = vpStats.flush_total_ms;
        rec.vpHudComposeMs = vpStats.hud_compute_ms;
        rec.vpReleaseViewMs = vpStats.release_view_ms;
        rec.poolIndex = vpStats.pool_index;
        rec.decoderTexId = vpStats.decoder_tex_id;
        rec.vpOutTexId = (UINT64)((uintptr_t)pOutNV12Tex & 0xFFFFFFFFu);
        rec.arrayIndex = vpStats.array_index;
        rec.settersSkipped = vpStats.setters_skipped;
        rec.stateSig = vpStats.state_sig;
        rec.vpProcessorId = vpStats.vp_processor_id;
        rec.vpEnumeratorId = vpStats.vp_enumerator_id;
        rec.vpContextId = vpStats.vp_context_id;
        rec.prevVpQueryReady = vpStats.prev_vp_query_ready;
        rec.prevLocalQueryReady = vpStats.prev_local_query_ready;
        rec.sameSlotPreviousFrame = vpStats.same_slot_previous_frame;
        rec.sameSlotQueryReady = vpStats.same_slot_query_ready;
    }
    if (d3d11Decode && ctx->pPendingDecodedTex) {
        ctx->pPendingDecodedTex->Release();
        ctx->pPendingDecodedTex = nullptr;
    }
    ctx->framesDecoded++;
    ctx->framesVPProcessed++;
    if (doHUD) ctx->gpuHUDFrames++;
    if (ctx->mapCompositeMode == 1) ctx->mapResampleFrames++;
    ctx->pLastOutNV12Tex = pOutNV12Tex;
    ctx->lastTimings.vpCpuSubmitMs = vpStats.cpu_submit_ms;
    ctx->lastTimings.vpGpuCompletionMs = vpStats.gpu_completion_ms;
    ctx->lastTimings.gpuWaitMs = vpStats.gpu_wait_ms;
    if (ctx->profilingEnabled) {
        ctx->gpuProfiledFrames++;
    }

    if (ctx->diagnosticsEnabled && frame_index == 30) {
        std::cout << "\n--- FRAME 30 POINTER IDENTITIES ---" << std::endl;
        std::cout << "  Base Stream0 texture pointer: " << pDecodedTex << std::endl;
        std::cout << "  VP output texture pointer:    " << pOutNV12Tex << std::endl;
        std::cout << "  Texture passed to AMF:        " << pOutNV12Tex << std::endl;
        std::cout << "  VP_OUTPUT_POINTER == AMF_INPUT_POINTER: YES" << std::endl;
        std::cout << "  Output pool index:            " << ctx->vpPipeline.GetLastPoolIndex() << std::endl;
        std::cout << "  Frame number:                 " << frame_index << std::endl;
    }

    // Step 2: Direct GPU handoff to AMD AMF HEVC Hardware Encoder
    // ETAP 5R build gate: the 5O BYPASS goto must not cross the submit/query
    // initializations, so that whole section is wrapped in a scope block.  The
    // default path (amfMode==0) runs the identical code; BYPASS (amfMode==1)
    // skips the encoder handoff entirely and returns success.
    if (ctx->amfMode == 1) { goto amf_bypassed; }  // ETAP 5O BYPASS
    {
    AMFEncoderStats amfStats = {};
    ctx->amfQueryCalls = 0;
    ctx->amfOutputsThisFrame = 0;
    double amfCreateSurfaceMs = 0.0;
    double amfSubmitInputMs = 0.0;
    double amfQueryMsTot = 0.0;
    double amfPacketWriteMsTot = 0.0;
    int submitResult = AMF_OK;
    int queryResult = (int)AMF_REPEAT;
    UINT retriesThisFrame = 0;
    double queueWaitMs = 0.0;

    const int64_t pts = static_cast<int64_t>(
        (static_cast<uint64_t>(frame_index) * 10000000ULL * ctx->fpsDen
         + ctx->fpsNum / 2) / ctx->fpsNum);

    constexpr auto kMaxWait = std::chrono::seconds(60);

    // Helper lambda to drain any packets that are immediately ready
    auto drainReadyPackets = [&]() {
        while (true) {
            std::vector<uint8_t> pktData;
            int64_t outPts = 0;
            bool isKeyframe = false;
            AMF_RESULT qRes = AMF_REPEAT;
            double qMs = 0.0;
            ctx->amfQueryCalls++;
            if (!ctx->amfEncoder.QueryPacket(pktData, outPts, isKeyframe, &qRes, &qMs)) {
                ctx->lastTimings.amfQueryMs += qMs;
                amfQueryMsTot += qMs;
                ctx->outputNotReadyCount++;
                break; // No more packets ready right now
            }
            ctx->lastTimings.amfQueryMs += qMs;
            amfQueryMsTot += qMs;
            ctx->framesReceived++;
            ctx->amfOutputsThisFrame++;
            queryResult = (int)qRes;

            const auto writeStart = std::chrono::high_resolution_clock::now();
            if (ctx->h265Out.is_open() && !pktData.empty()) {
                ctx->h265Out.write(reinterpret_cast<const char*>(pktData.data()), pktData.size());
            }
            const auto writeEnd = std::chrono::high_resolution_clock::now();
            const double writeMs = std::chrono::duration<double, std::milli>(
                writeEnd - writeStart).count();
            ctx->lastTimings.packetWriteMs += writeMs;
            amfPacketWriteMsTot += writeMs;
        }
    };

    // Substage A: Pre-drain packets completed during decode / HUD / VideoProcessor
    drainReadyPackets();

    // Substage B: If in-flight frames reached queueDepth limit, wait for at least one packet
    // to complete before submitting.
    const int maxInFlight = ctx->queueDepth;
    const auto waitStart = std::chrono::steady_clock::now();
    while (static_cast<int>(ctx->framesSubmitted - ctx->framesReceived) >= maxInFlight) {
        std::vector<uint8_t> pktData;
        int64_t outPts = 0;
        bool isKeyframe = false;
        AMF_RESULT qRes = AMF_REPEAT;
        double qMs = 0.0;
        ctx->amfQueryCalls++;
        if (ctx->amfEncoder.QueryPacket(pktData, outPts, isKeyframe, &qRes, &qMs)) {
            ctx->lastTimings.amfQueryMs += qMs;
            amfQueryMsTot += qMs;
            ctx->framesReceived++;
            ctx->amfOutputsThisFrame++;
            queryResult = (int)qRes;

            const auto writeStart = std::chrono::high_resolution_clock::now();
            if (ctx->h265Out.is_open() && !pktData.empty()) {
                ctx->h265Out.write(reinterpret_cast<const char*>(pktData.data()), pktData.size());
            }
            const auto writeEnd = std::chrono::high_resolution_clock::now();
            const double writeMs = std::chrono::duration<double, std::milli>(
                writeEnd - writeStart).count();
            ctx->lastTimings.packetWriteMs += writeMs;
            amfPacketWriteMsTot += writeMs;
            break; // slot freed!
        } else {
            ctx->lastTimings.amfQueryMs += qMs;
            amfQueryMsTot += qMs;
            ctx->outputNotReadyCount++;
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        }
        if (std::chrono::steady_clock::now() - waitStart >= kMaxWait) {
            std::cerr << "[TELEM AMD DLL] In-flight wait timed out after 60s on frame " << frame_index << std::endl;
            return 0;
        }
    }
    queueWaitMs = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - waitStart).count();
    ctx->consumerWaitMs += queueWaitMs;

    // Substage C: Create AMFSurface EXACTLY ONCE for this frame
    amf::AMFSurfacePtr pSurface;
    double createMs = 0.0;
    if (!ctx->amfEncoder.CreateSurface(pOutNV12Tex, pts, pSurface, &createMs)) {
        std::cerr << "[AMF] CreateSurface failed on frame " << frame_index << std::endl;
        return 0;
    }
    amfCreateSurfaceMs = createMs;

    // Substage D: Submit surface to AMF encoder
    const auto submitStart = std::chrono::steady_clock::now();
    bool submitted = false;
    while (!submitted) {
        AMF_RESULT sRes = ctx->amfEncoder.SubmitSurface(pSurface, &amfStats);
        amfSubmitInputMs += amfStats.submit_input_ms;
        submitResult = sRes;
        if (sRes == AMF_OK) {
            submitted = true;
            ctx->framesSubmitted++;
            break;
        }
        if (sRes != AMF_INPUT_FULL) {
            ctx->amfDroppedSubmissions++;
            std::cerr << "[TELEM AMD DLL] SubmitSurface failed on frame " << frame_index << ": " << sRes << std::endl;
            return 0;
        }

        // AMF_INPUT_FULL backpressure handling (rare): drain 1 packet and retry submission
        ctx->amfInputFullCount++;
        ctx->amfRetryCount++;
        retriesThisFrame++;

        std::vector<uint8_t> bpPacket;
        int64_t bpPts = 0;
        bool bpKey = false;
        AMF_RESULT bpRes = AMF_REPEAT;
        double bpMs = 0.0;
        ctx->amfQueryCalls++;
        if (ctx->amfEncoder.QueryPacket(bpPacket, bpPts, bpKey, &bpRes, &bpMs)) {
            ctx->lastTimings.amfQueryMs += bpMs;
            amfQueryMsTot += bpMs;
            ctx->framesReceived++;
            ctx->amfOutputsThisFrame++;
            queryResult = (int)bpRes;
            const auto writeStart = std::chrono::high_resolution_clock::now();
            if (ctx->h265Out.is_open() && !bpPacket.empty()) {
                ctx->h265Out.write(reinterpret_cast<const char*>(bpPacket.data()), bpPacket.size());
            }
            const auto writeEnd = std::chrono::high_resolution_clock::now();
            const double writeMs = std::chrono::duration<double, std::milli>(
                writeEnd - writeStart).count();
            ctx->lastTimings.packetWriteMs += writeMs;
            amfPacketWriteMsTot += writeMs;
        } else {
            ctx->lastTimings.amfQueryMs += bpMs;
            amfQueryMsTot += bpMs;
            ctx->outputNotReadyCount++;
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        }

        if (std::chrono::steady_clock::now() - submitStart >= kMaxWait) {
            ctx->amfDroppedSubmissions++;
            std::cerr << "[TELEM AMD DLL] AMF_INPUT_FULL timed out on frame " << frame_index << std::endl;
            return 0;
        }
    }
    ctx->lastTimings.amfSubmitMs = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - submitStart).count();

    // Substage E: Non-blocking drain of any packets that finished immediately
    drainReadyPackets();

    ctx->inFlightFrames = ctx->framesSubmitted - ctx->framesReceived;
    if (ctx->inFlightFrames > ctx->maxInFlight) {
        ctx->maxInFlight = ctx->inFlightFrames;
    }

    if (fa) {
        rec.amfCreateSurfaceMs = amfCreateSurfaceMs;
        rec.amfSubmitInputMs = amfSubmitInputMs;
        rec.amfQueryMs = amfQueryMsTot;
        rec.amfPacketWriteMs = amfPacketWriteMsTot;
        rec.submitResult = submitResult;
        rec.queryResult = queryResult;
        rec.amfSubmitted = ctx->framesSubmitted;
        rec.amfReceived = ctx->framesReceived;
        rec.amfQueryCalls = ctx->amfQueryCalls;
        rec.amfOutputs = ctx->amfOutputsThisFrame;
        rec.retriesThisFrame = retriesThisFrame;
        rec.inFlightFrames = static_cast<UINT>(ctx->inFlightFrames);
        rec.maxInFlight = static_cast<UINT>(ctx->maxInFlight);
        rec.outputNotReadyCount = static_cast<UINT>(ctx->outputNotReadyCount);
        rec.queueWaitMs = queueWaitMs;
    }
    }

amf_bypassed:
    if (fa) {
        rec.processFrameTotalMs = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - pfStart).count();
        if (ctx->nativeTrace.size() < 100000) {
            ctx->nativeTrace.push_back(rec);
        }
    }
    return 1;
}

TELEM_EXPORT int telem_amd_dump_checkpoint(
    void* handle,
    UINT frame_index,
    const char* stage_name,
    const wchar_t* out_png_path
) {
    if (!handle || !stage_name || !out_png_path) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    char mbsPng[512] = {};
    wcstombs(mbsPng, out_png_path, 512);

    std::string stage(stage_name);

    if (stage == "01_base_input" || stage == "B_base_d3d11") {
        ID3D11Texture2D* pTex = ctx->pBaseP010Tex;
        if (!pTex) return 0;
        D3D11_TEXTURE2D_DESC desc = {};
        pTex->GetDesc(&desc);

        D3D11_TEXTURE2D_DESC readDesc = desc;
        readDesc.Usage = D3D11_USAGE_STAGING;
        readDesc.BindFlags = 0;
        readDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        readDesc.MiscFlags = 0;

        ID3D11Texture2D* pStaging = nullptr;
        HRESULT hr = ctx->pDevice->CreateTexture2D(&readDesc, nullptr, &pStaging);
        if (SUCCEEDED(hr) && pStaging) {
            ctx->pContext->CopyResource(pStaging, pTex);

            D3D11_MAPPED_SUBRESOURCE mapY = {}, mapUV = {};
            HRESULT hrY = ctx->pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &mapY);
            HRESULT hrUV = ctx->pContext->Map(pStaging, 1, D3D11_MAP_READ, 0, &mapUV);

            if (SUCCEEDED(hrY)) {
                const uint8_t* yPlane = (const uint8_t*)mapY.pData;
                const uint8_t* uvPlane = SUCCEEDED(hrUV) ? (const uint8_t*)mapUV.pData : (yPlane + (mapY.RowPitch * desc.Height));
                UINT yPitch = mapY.RowPitch;
                UINT uvPitch = SUCCEEDED(hrUV) ? mapUV.RowPitch : mapY.RowPitch;

                std::cout << "[DUMP STATS] stage: " << stage 
                          << " hrY: 0x" << std::hex << hrY << " hrUV: 0x" << hrUV << std::dec
                          << " yPitch: " << yPitch << " uvPitch: " << uvPitch 
                          << " yData[0]: " << (int)yPlane[0] << " uvData[0]: " << (int)uvPlane[0] << " uvData[1]: " << (int)uvPlane[1]
                          << " uvData[yPitch]: " << (int)uvPlane[uvPitch] << " uvData[yPitch+1]: " << (int)uvPlane[uvPitch+1] << std::endl;

                std::vector<uint8_t> rgba = ConvertNV12ToRGBA(yPlane, uvPlane, desc.Width, desc.Height, yPitch, uvPitch);
                stbi_write_png(mbsPng, desc.Width, desc.Height, 4, rgba.data(), desc.Width * 4);

                ctx->pContext->Unmap(pStaging, 0);
                if (SUCCEEDED(hrUV)) ctx->pContext->Unmap(pStaging, 1);
            }
            pStaging->Release();
            std::cout << "[TELEM AMD DLL] Checkpoint " << stage << " saved to: " << mbsPng << std::endl;
            return 1;
        }
    } else if (stage == "03_d3d11_hud_texture") {
        ID3D11Texture2D* pTex = ctx->vpPipeline.GetHUDTexture();
        if (!pTex) return 0;

        D3D11_TEXTURE2D_DESC desc = {};
        pTex->GetDesc(&desc);

        D3D11_TEXTURE2D_DESC readDesc = desc;
        readDesc.Usage = D3D11_USAGE_STAGING;
        readDesc.BindFlags = 0;
        readDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        readDesc.MiscFlags = 0;

        ID3D11Texture2D* pStaging = nullptr;
        HRESULT hr = ctx->pDevice->CreateTexture2D(&readDesc, nullptr, &pStaging);
        if (SUCCEEDED(hr) && pStaging) {
            ctx->pContext->CopyResource(pStaging, pTex);

            D3D11_MAPPED_SUBRESOURCE map = {};
            if (SUCCEEDED(ctx->pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &map))) {
                stbi_write_png(mbsPng, desc.Width, desc.Height, 4, map.pData, map.RowPitch);
                ctx->pContext->Unmap(pStaging, 0);
            }
            pStaging->Release();
            std::cout << "[TELEM AMD DLL] Checkpoint 03 saved to: " << mbsPng << std::endl;
            return 1;
        }
    } else if (stage == "04_videoprocessor_output" || stage == "02_vp_stream0_output" || stage == "03_amf_input" || stage == "E_amf_input") {
        ID3D11Texture2D* pTex = ctx->pLastOutNV12Tex;
        if (!pTex) return 0;

        D3D11_TEXTURE2D_DESC desc = {};
        pTex->GetDesc(&desc);

        D3D11_TEXTURE2D_DESC readDesc = desc;
        readDesc.Usage = D3D11_USAGE_STAGING;
        readDesc.BindFlags = 0;
        readDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        readDesc.MiscFlags = 0;

        ID3D11Texture2D* pStaging = nullptr;
        HRESULT hr = ctx->pDevice->CreateTexture2D(&readDesc, nullptr, &pStaging);
        if (SUCCEEDED(hr) && pStaging) {
            ctx->pContext->CopyResource(pStaging, pTex);

            D3D11_MAPPED_SUBRESOURCE mapY = {}, mapUV = {};
            HRESULT hrY = ctx->pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &mapY);
            HRESULT hrUV = ctx->pContext->Map(pStaging, 1, D3D11_MAP_READ, 0, &mapUV);

            if (SUCCEEDED(hrY)) {
                const uint8_t* yPlane = (const uint8_t*)mapY.pData;
                const uint8_t* uvPlane = SUCCEEDED(hrUV) ? (const uint8_t*)mapUV.pData : (yPlane + (mapY.RowPitch * desc.Height));
                UINT yPitch = mapY.RowPitch;
                UINT uvPitch = SUCCEEDED(hrUV) ? mapUV.RowPitch : mapY.RowPitch;

                std::vector<uint8_t> rgba = ConvertNV12ToRGBA(yPlane, uvPlane, desc.Width, desc.Height, yPitch, uvPitch);
                stbi_write_png(mbsPng, desc.Width, desc.Height, 4, rgba.data(), desc.Width * 4);
                ctx->pContext->Unmap(pStaging, 0);
                if (SUCCEEDED(hrUV)) ctx->pContext->Unmap(pStaging, 1);
            }
            pStaging->Release();
            std::cout << "[TELEM AMD DLL] Checkpoint " << stage << " saved to: " << mbsPng << std::endl;
            return 1;
        }
    }
    return 0;
}

TELEM_EXPORT int telem_amd_flush(void* handle) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    if (ctx->amfMode == 1) {
        // ETAP 5O BYPASS: no encoder, nothing to drain.
        return 1;
    }
    ctx->amfEncoder.Flush();

    // Drain any remaining packets from AMF
    std::vector<uint8_t> pktData;
    int64_t outPts = 0;
    bool isKeyframe = false;
    const auto drainStart = std::chrono::steady_clock::now();
    while (true) {
        AMF_RESULT queryResult = AMF_REPEAT;
        if (ctx->amfEncoder.QueryPacket(pktData, outPts, isKeyframe, &queryResult, nullptr)) {
            if (ctx->h265Out.is_open() && !pktData.empty()) {
                ctx->h265Out.write(reinterpret_cast<const char*>(pktData.data()), pktData.size());
            }
            ctx->framesReceived++;
            continue;
        }
        if (queryResult == AMF_EOF) break;
        if (queryResult != AMF_REPEAT) {
            std::cerr << "[TELEM AMD DLL] AMF drain QueryOutput failed: "
                      << queryResult << std::endl;
            return 0;
        }
        if (std::chrono::duration<double>(
                std::chrono::steady_clock::now() - drainStart).count() > 30.0) {
            std::cerr << "[TELEM AMD DLL] AMF drain timeout before AMF_EOF." << std::endl;
            return 0;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    if (ctx->h265Out.is_open()) {
        ctx->h265Out.close();
    }
    std::cout << "[TELEM AMD DLL] telem_amd_flush completed. Total received: " << ctx->framesReceived << std::endl;
    return 1;
}

TELEM_EXPORT int telem_amd_close(void* handle) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    // ETAP 5R — write the native per-frame process_frame trace (CSV).
    if (ctx->frameAccountEnabled && !ctx->nativeTrace.empty()) {
        std::string tracePath = ctx->outputPath + ".frame_accounting.csv";
        std::ofstream trace(tracePath);
        if (trace.is_open()) {
            trace << "frame,surf_acquire,vp_total,vp_setup,vp_create_view,vp_set_stream,"
                     "vp_setter_fmt,vp_setter_src_rect,vp_setter_dst_rect,vp_blt,"
                     "first_vp_api,first_vp_api_us,vp_sequence_total_us,"
                     "vp_submit_window,vp_range_pass,clear_prev_above,"
                     "vp_chart_blend,chart_flush,vp_gauge_blend,gauge_flush,"
                     "map_resample,vp_map_blend,map_flush1,map_flush2,"
                     "above_blend,above_flush,flush_total,vp_hud_compute,"
                     "vp_release_view,amf_create_surface,amf_submit_input,amf_query,"
                     "amf_packet_write,process_frame_total,pool_index,decoder_tex_id,"
                     "vp_out_tex_id,array_index,setters_skipped,state_sig,vp_processor_id,vp_enumerator_id,vp_context_id,"
                     "prev_vp_query_ready,prev_local_query_ready,same_slot_previous_frame,same_slot_query_ready,"
                     "amf_submitted,"
                     "amf_received,amf_query_calls,amf_outputs,retries,submit_result,query_result,"
                     "decoder_copy,in_flight,max_in_flight,not_ready,queue_wait_ms\n";
            for (const auto& r : ctx->nativeTrace) {
                trace << r.frame << ',' << r.surfAcquireMs << ',' << r.vpTotalMs << ','
                      << r.vpSetupMs << ',' << r.vpCreateViewMs << ',' << r.vpSetStreamMs << ','
                      << r.vpSetterFmtMs << ',' << r.vpSetterSrcRectMs << ','
                      << r.vpSetterDstRectMs << ',' << r.vpBltMs << ','
                      << r.firstVpApi << ',' << r.firstVpApiMs << ',' << r.vpSequenceTotalMs << ','
                      << r.vpSubmitWindowMs << ',' << r.vpRangePassMs << ','
                      << r.clearPrevAboveMs << ','
                      << r.vpChartBlendMs << ',' << r.chartFlushMs << ','
                      << r.vpGaugeBlendMs << ',' << r.gaugeFlushMs << ','
                      << r.mapResampleMs << ',' << r.mapBlendMs << ','
                      << r.mapFlush1Ms << ',' << r.mapFlush2Ms << ','
                      << r.aboveBlendMs << ',' << r.aboveFlushMs << ','
                      << r.flushTotalMs << ','
                      << r.vpHudComposeMs << ',' << r.vpReleaseViewMs << ','
                      << r.amfCreateSurfaceMs << ',' << r.amfSubmitInputMs << ','
                      << r.amfQueryMs << ',' << r.amfPacketWriteMs << ','
                      << r.processFrameTotalMs << ',' << r.poolIndex << ','
                      << r.decoderTexId << ',' << r.vpOutTexId << ','
                      << r.arrayIndex << ',' << r.settersSkipped << ',' << r.stateSig << ','
                      << r.vpProcessorId << ',' << r.vpEnumeratorId << ',' << r.vpContextId << ','
                      << r.prevVpQueryReady << ',' << r.prevLocalQueryReady << ','
                      << r.sameSlotPreviousFrame << ',' << r.sameSlotQueryReady << ','
                      << r.amfSubmitted << ',' << r.amfReceived << ','
                      << r.amfQueryCalls << ',' << r.amfOutputs << ','
                      << r.retriesThisFrame << ','
                      << r.submitResult << ',' << r.queryResult << ',' << r.decoderCopy << ','
                      << r.inFlightFrames << ',' << r.maxInFlight << ',' << r.outputNotReadyCount << ','
                      << r.queueWaitMs << '\n';
            }
            trace.close();
            std::cout << "[TELEM AMD DLL] Native frame trace: " << tracePath
                      << " (" << ctx->nativeTrace.size() << " frames)" << std::endl;
        }
    }

    // ETAP 5T — write the async GPU timestamp timeline (CSV).
    if (ctx->vpPipeline.IsGpuTimestampProfile()) {
        const auto& gtl = ctx->vpPipeline.GetGPUTimeline();
        std::string gpuPath = ctx->outputPath + ".gpu_timeline.csv";
        std::ofstream gpu(gpuPath);
        if (gpu.is_open()) {
            gpu << "frame,ready,disjoint,freq,begin_ts,blt_ts,range_ts,charts_ts,"
                   "gauge_ts,map_ts,hud_ts,end_ts,read_latency,span_ms,vp_ms,range_ms,"
                   "charts_ms,gauge_ms,map_ms,hud_ms\n";
            for (const auto& r : gtl) {
                const double f = r.freq > 0 ? r.freq : 1.0;
                gpu << r.frame << ',' << (r.ready ? 1 : 0) << ',' << (r.disjoint ? 1 : 0)
                    << ',' << r.freq << ',' << r.beginTs << ',' << r.bltTs << ','
                    << r.rangeTs << ',' << r.chartsTs << ',' << r.gaugeTs << ','
                    << r.mapTs << ',' << r.hudTs << ',' << r.endTs << ','
                    << r.readLatency << ','
                    << (double)(r.endTs - r.beginTs) / f * 1000.0 << ','
                    << (double)(r.bltTs - r.beginTs) / f * 1000.0 << ','
                    << (double)(r.rangeTs - r.bltTs) / f * 1000.0 << ','
                    << (double)(r.chartsTs - r.rangeTs) / f * 1000.0 << ','
                    << (double)(r.gaugeTs - r.chartsTs) / f * 1000.0 << ','
                    << (double)(r.mapTs - r.gaugeTs) / f * 1000.0 << ','
                    << (double)(r.hudTs - r.mapTs) / f * 1000.0 << '\n';
            }
            gpu.close();
            UINT64 gdCalls = 0, gdNR = 0;
            ctx->vpPipeline.GetGPUTimelineGetDataStats(&gdCalls, &gdNR);
            std::cout << "[TELEM AMD DLL] GPU timeline: " << gpuPath << " ("
                      << gtl.size() << " frames; GetData " << gdCalls
                      << " not-ready " << gdNR << ")" << std::endl;
        }
    }

    if (ctx->framesReceived < ctx->framesSubmitted) {
        telem_amd_flush(ctx);
    }
    if (ctx->pSourceReader) ctx->pSourceReader->Release();
    if (ctx->pDXGIManager) ctx->pDXGIManager->Release();
    if (ctx->pBaseP010Tex) ctx->pBaseP010Tex->Release();
    if (ctx->pUploadStagingTex) ctx->pUploadStagingTex->Release();
    if (ctx->pDecodedCopyTex) ctx->pDecodedCopyTex->Release();
    if (ctx->pPendingDecodedTex) ctx->pPendingDecodedTex->Release();
    // ETAP 5W — release the D3D11 device/context AFTER the VP/AMF destructors
    // (inside delete ctx) have torn down all GPU resources.  Releasing the
    // device first can strand driver-side kernel objects (events/mutants/
    // sections) when child resources are released against a destroyed device.
    ID3D11Device* dev = ctx->pDevice;
    ID3D11DeviceContext* cctx = ctx->pContext;
    ctx->pDevice = nullptr;
    ctx->pContext = nullptr;
    // ETAP 5W — device/context liveness diagnostic (AMD_POOL_LIFECYCLE_STATS=1).
    const bool poolDbg = ctx->vpPipeline.IsPoolLifecycleStats();

    delete ctx;
    if (cctx) cctx->Release();
    MFShutdown();
    // ETAP 5W — remaining refcount after teardown + MFShutdown.  1 = only ours
    // (device destroyed by our Release below); >1 = a leaked reference keeps
    // the device alive and strands driver-side kernel objects.
    if (poolDbg) {
        ULONG devRef = dev ? (dev->AddRef() - 1) : 0;
        if (dev) dev->Release();
        std::cout << "[TELEM AMD DLL] close: D3D11 device refcount=" << devRef
                  << " after teardown+MFShutdown (1=clean)" << std::endl;
    }
    if (dev) dev->Release();
    std::cout << "[TELEM AMD DLL] telem_amd_close completed." << std::endl;
    return 1;
}

TELEM_EXPORT int telem_amd_drain_amf(void* handle) {
    if (!handle) return 0;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    return telem_amd_flush(ctx);
}

TELEM_EXPORT void telem_amd_get_queue_stats(
    void* handle,
    UINT64* out_submitted,
    UINT64* out_received,
    UINT64* out_in_flight,
    UINT64* out_max_in_flight,
    UINT64* out_query_calls,
    UINT64* out_input_full,
    UINT64* out_not_ready,
    UINT64* out_retries,
    double* out_consumer_wait_ms
) {
    if (!handle) return;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    if (out_submitted) *out_submitted = ctx->framesSubmitted;
    if (out_received) *out_received = ctx->framesReceived;
    if (out_in_flight) *out_in_flight = ctx->inFlightFrames;
    if (out_max_in_flight) *out_max_in_flight = ctx->maxInFlight;
    if (out_query_calls) *out_query_calls = ctx->amfQueryCalls;
    if (out_input_full) *out_input_full = ctx->amfInputFullCount;
    if (out_not_ready) *out_not_ready = ctx->outputNotReadyCount;
    if (out_retries) *out_retries = ctx->amfRetryCount;
    if (out_consumer_wait_ms) *out_consumer_wait_ms = ctx->consumerWaitMs;
}

TELEM_EXPORT void telem_amd_get_stats(
    void* handle,
    UINT64* out_decoded,
    UINT64* out_vp,
    UINT64* out_submitted,
    UINT64* out_received
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_decoded) *out_decoded = ctx->framesDecoded;
    if (out_vp) *out_vp = ctx->framesVPProcessed;
    if (out_submitted) *out_submitted = ctx->framesSubmitted;
    if (out_received) *out_received = ctx->framesReceived;
}

TELEM_EXPORT void telem_amd_get_extended_stats(
    void* handle,
    UINT64* out_hud_updates,
    UINT64* out_video_updates,
    UINT64* out_input_full,
    UINT64* out_retries,
    UINT64* out_dropped,
    UINT64* out_ignored
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_hud_updates) *out_hud_updates = ctx->hudUpdates;
    if (out_video_updates) *out_video_updates = ctx->videoUpdates;
    if (out_input_full) *out_input_full = ctx->amfInputFullCount;
    if (out_retries) *out_retries = ctx->amfRetryCount;
    if (out_dropped) *out_dropped = ctx->amfDroppedSubmissions;
    if (out_ignored) *out_ignored = ctx->amfIgnoredSubmissions;
}

TELEM_EXPORT void telem_amd_get_etap1_stats(
    void* handle,
    UINT64* out_blend_calls,
    UINT64* out_gpu_profiled_frames
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_blend_calls) *out_blend_calls = ctx->blendCalls;
    if (out_gpu_profiled_frames) *out_gpu_profiled_frames = ctx->gpuProfiledFrames;
}

TELEM_EXPORT void telem_amd_get_etap2_stats(
    void* handle,
    UINT64* out_gpu_hud_frames,
    UINT64* out_hud_texture_creates,
    UINT64* out_hud_texture_uploads,
    int* out_hud_mode
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_gpu_hud_frames) *out_gpu_hud_frames = ctx->gpuHUDFrames;
    if (out_hud_texture_creates) *out_hud_texture_creates = ctx->hudTextureCreates;
    if (out_hud_texture_uploads) *out_hud_texture_uploads = ctx->hudTextureUploads;
    if (out_hud_mode) *out_hud_mode = ctx->hudMode;
}

TELEM_EXPORT void telem_amd_get_etap3_stats(
    void* handle,
    UINT64* out_hud_uploaded_bytes,
    UINT64* out_hud_uploaded_rects
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_hud_uploaded_bytes) *out_hud_uploaded_bytes = ctx->hudUploadedBytes;
    if (out_hud_uploaded_rects) *out_hud_uploaded_rects = ctx->hudUploadedRects;
}

TELEM_EXPORT void telem_amd_get_etap4_stats(
    void* handle,
    UINT64* out_read_calls,
    UINT64* out_video_samples,
    UINT64* out_stream_ticks,
    UINT64* out_null_samples,
    UINT64* out_d3d11_surfaces,
    UINT64* out_format_changes,
    UINT64* out_eos_events,
    UINT64* out_direct_surface_frames,
    UINT64* out_gpu_copy_frames,
    int* out_decode_mode,
    int* out_hardware_confirmed,
    UINT* out_decoder_format
) {
    if (!handle) return;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    if (out_read_calls) *out_read_calls = ctx->mfReadSampleCalls;
    if (out_video_samples) *out_video_samples = ctx->mfVideoSamples;
    if (out_stream_ticks) *out_stream_ticks = ctx->mfStreamTicks;
    if (out_null_samples) *out_null_samples = ctx->mfNullSamples;
    if (out_d3d11_surfaces) *out_d3d11_surfaces = ctx->mfD3D11Surfaces;
    if (out_format_changes) *out_format_changes = ctx->mfFormatChanges;
    if (out_eos_events) *out_eos_events = ctx->mfEndOfStreamEvents;
    if (out_direct_surface_frames) *out_direct_surface_frames = ctx->directDecoderSurfaceFrames;
    if (out_gpu_copy_frames) *out_gpu_copy_frames = ctx->decoderGpuCopyFrames;
    if (out_decode_mode) *out_decode_mode = ctx->decodeMode;
    if (out_hardware_confirmed) *out_hardware_confirmed = ctx->mfHardwareConfirmed ? 1 : 0;
    if (out_decoder_format) *out_decoder_format = static_cast<UINT>(ctx->decoderOutputFormat);
}

TELEM_EXPORT void telem_amd_get_last_frame_timings(
    void* handle,
    double* out_mf_read_sample_ms,
    double* out_mf_surface_acquire_ms,
    double* out_base_gpu_copy_ms,
    double* out_hud_native_copy_ms,
    double* out_hud_upload_ms,
    double* out_staging_memcpy_ms,
    double* out_blend_ms,
    double* out_copy_submit_ms,
    double* out_vp_cpu_submit_ms,
    double* out_vp_gpu_completion_ms,
    double* out_gpu_wait_ms,
    double* out_amf_submit_ms,
    double* out_amf_query_ms,
    double* out_packet_write_ms
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    const TelemAMDFrameTimings& t = ctx->lastTimings;
    if (out_mf_read_sample_ms) *out_mf_read_sample_ms = t.mfReadSampleMs;
    if (out_mf_surface_acquire_ms) *out_mf_surface_acquire_ms = t.mfSurfaceAcquireMs;
    if (out_base_gpu_copy_ms) *out_base_gpu_copy_ms = t.baseGpuCopyMs;
    if (out_hud_native_copy_ms) *out_hud_native_copy_ms = t.hudNativeCopyMs;
    if (out_hud_upload_ms) *out_hud_upload_ms = t.hudUploadMs;
    if (out_staging_memcpy_ms) *out_staging_memcpy_ms = t.stagingMemcpyMs;
    if (out_blend_ms) *out_blend_ms = t.blendMs;
    if (out_copy_submit_ms) *out_copy_submit_ms = t.copySubmitMs;
    if (out_vp_cpu_submit_ms) *out_vp_cpu_submit_ms = t.vpCpuSubmitMs;
    if (out_vp_gpu_completion_ms) *out_vp_gpu_completion_ms = t.vpGpuCompletionMs;
    if (out_gpu_wait_ms) *out_gpu_wait_ms = t.gpuWaitMs;
    if (out_amf_submit_ms) *out_amf_submit_ms = t.amfSubmitMs;
    if (out_amf_query_ms) *out_amf_query_ms = t.amfQueryMs;
    if (out_packet_write_ms) *out_packet_write_ms = t.packetWriteMs;
}
