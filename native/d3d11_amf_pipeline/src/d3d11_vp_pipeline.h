#pragma once

#include <d3d11.h>
#include <d3d11_1.h>
#include <d3d11_3.h>
#include <dxgi.h>
#include <vector>
#include <iostream>
#include <chrono>
#include <cstdint>

struct VPPipelineStats {
    double p010_to_nv12_ms = 0.0;
    double hud_compose_ms = 0.0;
    double total_vp_ms = 0.0;
    double cpu_submit_ms = 0.0;
    double gpu_completion_ms = 0.0;
    double gpu_wait_ms = 0.0;
    // ETAP 5R — exclusive native substage wall timers (QPC), opt-in via
    // SetFrameAccount.  All zero unless native frame accounting is enabled.
    double pool_acquire_ms = 0.0;
    double setup_ms = 0.0;          // entry -> Blt start (pool+GetDesc+CreateView+SetStream*)
    double create_view_ms = 0.0;
    double set_stream_ms = 0.0;     // CreateView -> Blt start (SetStream* calls)
    double setter_fmt_ms = 0.0;     // ETAP 5S: VideoProcessorSetStreamFrameFormat
    double setter_src_rect_ms = 0.0; // ETAP 5S: VideoProcessorSetStreamSourceRect
    double setter_dst_rect_ms = 0.0; // ETAP 5S: VideoProcessorSetStreamDestRect
    double blt_ms = 0.0;
    double submit_window_ms = 0.0;  // Blt end -> HUD end (whole enqueue window)
    double range_pass_ms = 0.0;
    double clear_prev_above_ms = 0.0;
    double chart_blend_ms = 0.0;
    double chart_flush_ms = 0.0;
    double gauge_blend_ms = 0.0;
    double gauge_flush_ms = 0.0;
    double map_resample_ms = 0.0;
    double map_blend_ms = 0.0;
    double map_flush1_ms = 0.0;
    double map_flush2_ms = 0.0;
    double above_blend_ms = 0.0;
    double above_flush_ms = 0.0;
    double flush_total_ms = 0.0;
    double hud_compute_ms = 0.0;
    double release_view_ms = 0.0;
    UINT pool_index = 0;
    UINT64 decoder_tex_id = 0;      // ETAP 5S: input texture pointer (low bits)
    UINT array_index = 0;           // ETAP 5S: decoder subresource / array slice
    int setters_skipped = 0;        // ETAP 5S: 1 if STATIC_CACHE skipped setters this frame
    UINT state_sig = 0;             // ETAP 5S: applied stream-state signature
};

struct HUDDirtyRect {
    UINT x = 0;
    UINT y = 0;
    UINT width = 0;
    UINT height = 0;
};

// ETAP 5T — asynchronous GPU timestamp timeline record (one per frame).
struct GPUFrameTimeline {
    UINT64 frame = 0;
    bool ready = false;       // all queries retrieved (and disjoint==false)
    bool disjoint = false;    // D3D11 timestamp-disjoint flag (unreliable window)
    double freq = 1.0;        // timestamp frequency (ticks per second)
    UINT64 beginTs = 0, bltTs = 0, rangeTs = 0, chartsTs = 0,
           gaugeTs = 0, mapTs = 0, hudTs = 0, endTs = 0;
    UINT readLatency = 0;     // frames after issue when the data was read
};

class D3D11VideoProcessorPipeline {
public:
    D3D11VideoProcessorPipeline();
    ~D3D11VideoProcessorPipeline();

    bool Initialize(ID3D11Device* pDevice, ID3D11DeviceContext* pContext, UINT width, UINT height);
    bool SetupVideoProcessor(DXGI_FORMAT inputFormat, DXGI_FORMAT outputFormat);

    bool UpdateHUDTexture(
        UINT width,
        UINT height,
        const uint8_t* rgbaData,
        UINT stride,
        const HUDDirtyRect* dirtyRects,
        UINT dirtyRectCount,
        bool fullUpload,
        size_t* uploadedBytes,
        bool* textureCreated
    );

    // ── ETAP 5G: GPU-resident final map resize + composite ─────────────
    // CPU keeps producing the 692x692 RGBA map working image; the GPU
    // resamples it to the final widget size and blends it into the persistent
    // HUD canvas texture at the widget's destination bbox, before the existing
    // NV12 compute compositor consumes the canvas.  CPU_REFERENCE mode leaves
    // the whole path untouched (map stays in the Pillow canvas).
    bool UpdateMapTexture(
        UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
        size_t* uploadedBytes, bool* textureCreated);
    void SetMapGeometry(UINT dstX, UINT dstY, UINT srcW, UINT srcH, UINT outW, UINT outH);
    void SetMapFilter(int filter);
    void SetMapGpuEnabled(bool enabled);
    // ETAP 8U-B: Map GPU Path mode: 0 = DIRECT_AUTO (default), 1 = REFERENCE (two-pass), 2 = DIRECT_1TO1 (direct)
    void SetMapGpuPath(int path) { m_mapGpuPath = path; }
    int GetMapGpuPath() const { return m_mapGpuPath; }
    bool IsMapDirectUsed() const { return m_mapDirectUsed; }
    // ETAP 7B / 8N: compact CPU layer(s) blended after the GPU map.
    bool UpdateAboveMapTexture(
        UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
        UINT dstX, UINT dstY, bool active);
    bool UpdateAboveRegionsCount(UINT count);
    bool UpdateAboveRegion(
        UINT index, UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
        UINT dstX, UINT dstY);
    void SetAboveMapGpuEnabled(bool enabled);
    // Diagnostic: dump the GPU-resampled 691x691 RGBA map texture to a PNG
    // right after the resample dispatch (used to debug readback parity).
    void SetMapDumpPath(const char* path);
    // Diagnostic A/B readback of the GPU-resampled 691x691 RGBA map.  Used only
    // by the validation harness; never in the production export.
    bool GetMapResampleReadback(uint8_t* outRGBA, UINT stride);
    UINT GetMapResampleWidth() const { return m_mapOutW; }
    UINT GetMapResampleHeight() const { return m_mapOutH; }
    double GetMapUploadMs() const { return m_mapUploadMs; }
    double GetMapResampleMs() const { return m_mapResampleMs; }
    double GetMapBlendMs() const { return m_mapBlendMs; }
    UINT64 GetMapUploadedBytes() const { return m_mapUploadedBytes; }
    UINT64 GetMapUploads() const { return m_mapUploads; }

    // ── ETAP 5J: GPU final compositing for the cadence/HR charts ────────
    // The CPU still renders the exact same chart RGBA widget (final size, 1:1
    // texel, no resample).  The GPU holds one persistent RGBA8 texture per
    // chart and, each frame, clears the chart bbox inside the persistent HUD
    // canvas and blends the chart straight-alpha "over" (same rounding as the
    // validated GPU map/HUD blend).  The charts then leave both the Pillow
    // final HUD and the CPU dirty HUD upload.
    enum { CHART_SLOT_CADENCE = 0, CHART_SLOT_HR = 1, CHART_SLOT_COUNT = 2 };
    void SetChartGpuEnabled(bool enabled);
    // ETAP 5K — GPU_SPLIT: a static 1160x511 layer is uploaded once per cache
    // invalidation; per frame only two small dynamic tiles (cursor + current
    // value) are uploaded and REPLACED into the HUD canvas after the static
    // blend.  The dynamic tiles are pre-composited over the static on the CPU
    // (Pillow draw/paste blends differ from the GPU straight-alpha "over"), so
    // they ARE the exact final-chart pixels of their regions — a replace, not
    // a blend, reproduces the CPU result byte-for-byte.
    void SetChartSplitMode(bool enabled);
    // 5J full-chart upload (GPU mode only).
    bool UpdateChartTexture(
        UINT slot, UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
        UINT dstX, UINT dstY, size_t* uploadedBytes, bool* textureCreated);
    // 5K static layer upload (once per cache invalidation).
    bool UpdateChartStaticTexture(
        UINT slot, UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
        UINT dstX, UINT dstY, size_t* uploadedBytes, bool* textureCreated);
    // 5K dynamic tile upload (per frame).  region: 0 = cursor, 1 = current
    // value.  localX/localY are the tile offset inside the chart image.
    bool UpdateChartDynamicTile(
        UINT slot, UINT region, UINT width, UINT height, const uint8_t* rgbaData,
        UINT stride, UINT localX, UINT localY, size_t* uploadedBytes);
    double GetChartBlendMs() const { return m_chartBlendMs; }
    double GetChartClearMs() const { return m_chartClearMs; }
    UINT64 GetChartUploads() const { return m_chartUploads; }
    UINT64 GetChartUploadedBytes() const { return m_chartUploadedBytes; }
    UINT GetChartTextureCreates() const { return m_chartTextureCreates; }
    UINT64 GetChartStaticUploads() const { return m_chartStaticUploads; }
    UINT64 GetChartStaticUploadedBytes() const { return m_chartStaticUploadedBytes; }
    UINT64 GetChartDynamicUploads() const { return m_chartDynamicUploads; }
    UINT64 GetChartDynamicUploadedBytes() const { return m_chartDynamicUploadedBytes; }
    // Diagnostic: read back a region of the persistent HUD canvas (RGBA) to
    // validate the GPU chart blend A/B.  Never used on the production path.
    bool GetHUDCanvasRegionReadback(UINT x, UINT y, UINT w, UINT h,
                                    uint8_t* outRGBA, UINT stride);
    // ETAP 5K diagnostic: read back the persistent static chart texture (the
    // exact bytes uploaded once per cache invalidation).  Never production.
    bool GetChartStaticReadback(UINT slot, uint8_t* outRGBA, UINT stride);

    // ── ETAP 5L: GPU final compositing for the speed gauge ─────────────
    // The CPU still renders the exact same gauge RGBA widget (final size, 1:1
    // texel, no resample).  The GPU holds one persistent RGBA8 texture and,
    // each frame, clears the gauge bbox inside the persistent HUD canvas and
    // blends the gauge straight-alpha "over" (identical to the validated 5J
    // chart blend).  The gauge then leaves both the Pillow final HUD and the
    // CPU dirty HUD upload.
    void SetGaugeGpuEnabled(bool enabled);
    bool UpdateGaugeTexture(
        UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
        UINT dstX, UINT dstY, size_t* uploadedBytes, bool* textureCreated);
    bool BlendGauge();
    void ReleaseGaugeResources();
    double GetGaugeBlendMs() const { return m_gaugeBlendMs; }
    double GetGaugeClearMs() const { return m_gaugeClearMs; }
    UINT64 GetGaugeUploads() const { return m_gaugeUploads; }
    UINT64 GetGaugeUploadedBytes() const { return m_gaugeUploadedBytes; }
    UINT GetGaugeTextureCreates() const { return m_gaugeTextureCreates; }

    bool CanUseInputSurface(ID3D11Texture2D* texture, UINT arrayIndex);
    bool SetStreamRotation(UINT degrees);

    bool ProcessFrame(
        ID3D11Texture2D* pP010Texture,
        UINT arrayIndex,
        ID3D11Texture2D** ppOutNV12Texture,
        bool enableHUD,
        bool normalizeD3D11VARange,
        VPPipelineStats* outStats = nullptr,
        UINT frameIndex = 0,
        bool diagnosticsEnabled = false,
        bool profilingEnabled = false
    );

    ID3D11Texture2D* GetHUDTexture() const { return m_hudTexture; }
    UINT GetLastPoolIndex() const { return m_lastPoolIndex; }
    ID3D11Device* GetDevice() const { return m_device; }
    ID3D11DeviceContext* GetContext() const { return m_context; }

    // ETAP 5R: opt-in exclusive substage wall timing inside ProcessFrame.
    void SetFrameAccount(bool enabled) { m_frameAccount = enabled; }
    bool IsFrameAccount() const { return m_frameAccount; }

    // ETAP 5S: VP stream-state caching mode.
    //   0 = REFERENCE   (every setter every frame, current behavior)
    //   1 = STATIC_CACHE (setters applied once per state-signature; skipped
    //                     while the signature is unchanged)
    //   2 = REORDER     (diagnostic: SourceRect before FrameFormat — tests
    //                     whether the wait follows the FIRST D3D11 VP call)
    void SetVpStateMode(int mode) { m_vpStateMode = mode; }
    int GetVpStateMode() const { return m_vpStateMode; }

    // ETAP 5T — asynchronous GPU timestamp timeline (zero per-frame wait).
    void SetGpuTimestampProfile(bool enabled);
    bool IsGpuTimestampProfile() const { return m_gpuTsEnabled; }
    const std::vector<GPUFrameTimeline>& GetGPUTimeline() const { return m_gpuTimeline; }
    void GetGPUTimelineGetDataStats(UINT64* calls, UINT64* not_ready) const {
        if (calls) *calls = m_gpuTsGetDataCalls;
        if (not_ready) *not_ready = m_gpuTsGetDataNotReady;
    }
    // ETAP 5T diagnostic: skip the HUD/NV12 compute compositor (AMD_GPU_HUD_OFF).
    void SetGpuHudOff(bool off) { m_gpuHudOff = off; }
    // ETAP 5U/5V — runtime VP output surface pool size (4..8).  Production
    // default is 8 (ETAP 5V); AMD_VP_POOL_SIZE override still honored.
    // Must be called before Initialize().
    void SetPoolSize(UINT n);
    UINT GetPoolSize() const { return m_poolSize; }
    // ETAP 5V — debug-only pool lifecycle stats (AMD_POOL_LIFECYCLE_STATS=1).
    // ETAP 5V — debug-only pool lifecycle stats (AMD_POOL_LIFECYCLE_STATS=1).
    void SetPoolLifecycleStats(bool on) { m_poolLifecycleStats = on; }
    bool IsPoolLifecycleStats() const { return m_poolLifecycleStats; }
    void GetPoolLifecycleStats(UINT64* texCreated, UINT64* texReleased,
                               UINT64* viewsCreated, UINT64* viewsReleased) const {
        if (texCreated) *texCreated = m_poolTexturesCreated;
        if (texReleased) *texReleased = m_poolTexturesReleased;
        if (viewsCreated) *viewsCreated = m_poolViewsCreated;
        if (viewsReleased) *viewsReleased = m_poolViewsReleased;
    }
    // ETAP 8S: D3D11 Flush mode
    //   0 = BATCHED (production default: 0 intermediate Flush calls)
    //   1 = LEGACY  (5 intermediate Flush calls)
    void SetFlushMode(int mode) { m_flushMode = mode; }
    int GetFlushMode() const { return m_flushMode; }

private:
    static const UINT POOL_SIZE_DEFAULT = 8;
    bool InitializeNV12ComputeCompositor();
    bool ComposeHUDDirectNV12(ID3D11Texture2D* outputTexture, UINT poolIndex);
    bool NormalizeD3D11VARangeNV12(UINT poolIndex);
    bool InitializeMapCompositor();
    bool ResampleAndBlendMap(double* outResampleMs = nullptr, double* outFlush1Ms = nullptr, double* outBlendMs = nullptr, double* outFlush2Ms = nullptr);
    bool ClearPreviousAboveMap(double* outClearMs = nullptr);
    bool BlendAboveMap(double* outBlendMs = nullptr, double* outFlushMs = nullptr);
    void ReleaseMapResources();
    // ETAP 5J — GPU chart compositor
    bool InitializeChartCompositor();
    bool BlendCharts(double* outBlendMs = nullptr, double* outFlushMs = nullptr);
    bool BlendGauge(double* outBlendMs = nullptr, double* outFlushMs = nullptr);
    void ReleaseChartResources();

    ID3D11Device* m_device = nullptr;
    ID3D11DeviceContext* m_context = nullptr;
    bool m_ownsDevice = false;

    ID3D11VideoDevice* m_videoDevice = nullptr;
    ID3D11VideoContext* m_videoContext = nullptr;
    ID3D11VideoProcessorEnumerator* m_videoEnumerator = nullptr;
    ID3D11VideoProcessor* m_videoProcessor = nullptr;

    ID3D11Texture2D* m_hudTexture = nullptr;
    ID3D11VideoProcessorInputView* m_hudInputView = nullptr;
    ID3D11ShaderResourceView* m_hudShaderView = nullptr;
    ID3D11UnorderedAccessView* m_hudUAV = nullptr;

    // ETAP 5G — GPU-resident map resize + composite
    ID3D11Texture2D* m_mapTexture = nullptr;
    ID3D11ShaderResourceView* m_mapShaderView = nullptr;
    ID3D11Texture2D* m_mapResampleTexture = nullptr;
    ID3D11ShaderResourceView* m_mapResampleSRV = nullptr;
    ID3D11UnorderedAccessView* m_mapResampleUAV = nullptr;
    ID3D11ComputeShader* m_mapResampleShader = nullptr;
    ID3D11ComputeShader* m_mapBlendShader = nullptr;
    ID3D11Buffer* m_mapResampleCB = nullptr;
    ID3D11Buffer* m_mapBlendCB = nullptr;
    ID3D11Texture2D* m_mapReadbackStaging = nullptr;
    bool m_mapGpuEnabled = false;
    bool m_mapResampleReady = false;
    UINT m_mapSrcW = 0;
    UINT m_mapSrcH = 0;
    UINT m_mapOutW = 0;
    UINT m_mapOutH = 0;
    UINT m_mapDstX = 0;
    UINT m_mapDstY = 0;
    int m_mapFilter = 2;  // 0=bilinear, 1=bicubic(Catmull-Rom), 2=Lanczos-3
    int m_mapGpuPath = 0; // ETAP 8U-B: 0=DIRECT_AUTO, 1=REFERENCE, 2=DIRECT_1TO1
    bool m_mapDirectUsed = false;
    UINT64 m_mapUploads = 0;
    UINT64 m_mapUploadedBytes = 0;
    double m_mapUploadMs = 0.0;
    double m_mapResampleMs = 0.0;
    double m_mapBlendMs = 0.0;
    char m_mapDumpPath[512] = { 0 };

    // ETAP 8N: Multi-Region CPU_ABOVE_MAP structures
    static constexpr UINT MAX_ABOVE_REGIONS = 16;
    struct AboveRegion {
        UINT dstX = 0, dstY = 0;
        UINT w = 0, h = 0;
        bool active = false;
    };
    UINT m_aboveRegionCount = 0;
    AboveRegion m_aboveRegions[MAX_ABOVE_REGIONS] = {};
    ID3D11Texture2D* m_aboveRegionTexture[MAX_ABOVE_REGIONS] = {};
    ID3D11ShaderResourceView* m_aboveRegionSRV[MAX_ABOVE_REGIONS] = {};
    UINT m_aboveRegionTexW[MAX_ABOVE_REGIONS] = {};
    UINT m_aboveRegionTexH[MAX_ABOVE_REGIONS] = {};

    UINT m_abovePrevRegionCount = 0;
    AboveRegion m_abovePrevRegions[MAX_ABOVE_REGIONS] = {};
    bool m_aboveMapGpuEnabled = false;

    // ── ETAP 5J: GPU chart compositor resources ─────────────────────────
    ID3D11Texture2D* m_chartTexture[CHART_SLOT_COUNT] = { nullptr, nullptr };
    ID3D11ShaderResourceView* m_chartSRV[CHART_SLOT_COUNT] = { nullptr, nullptr };
    ID3D11ComputeShader* m_chartBlendShader = nullptr;
    ID3D11Buffer* m_chartBlendCB = nullptr;
    UINT m_chartDstX[CHART_SLOT_COUNT] = { 0, 0 };
    UINT m_chartDstY[CHART_SLOT_COUNT] = { 0, 0 };
    UINT m_chartW[CHART_SLOT_COUNT] = { 0, 0 };
    UINT m_chartH[CHART_SLOT_COUNT] = { 0, 0 };
    bool m_chartActive[CHART_SLOT_COUNT] = { false, false };
    bool m_chartGpuEnabled = false;
    bool m_chartSplitMode = false;
    // ── ETAP 5K: static + dynamic tile resources per slot ───────────────
    ID3D11Texture2D* m_chartStaticTexture[CHART_SLOT_COUNT] = { nullptr, nullptr };
    ID3D11ShaderResourceView* m_chartStaticSRV[CHART_SLOT_COUNT] = { nullptr, nullptr };
    ID3D11Texture2D* m_chartCursorTexture[CHART_SLOT_COUNT] = { nullptr, nullptr };
    ID3D11ShaderResourceView* m_chartCursorSRV[CHART_SLOT_COUNT] = { nullptr, nullptr };
    ID3D11Texture2D* m_chartValueTexture[CHART_SLOT_COUNT] = { nullptr, nullptr };
    ID3D11ShaderResourceView* m_chartValueSRV[CHART_SLOT_COUNT] = { nullptr, nullptr };
    UINT m_chartCursorX[CHART_SLOT_COUNT] = { 0, 0 };   // local offset in chart
    UINT m_chartCursorY[CHART_SLOT_COUNT] = { 0, 0 };
    UINT m_chartCursorW[CHART_SLOT_COUNT] = { 0, 0 };
    UINT m_chartCursorH[CHART_SLOT_COUNT] = { 0, 0 };
    UINT m_chartValueX[CHART_SLOT_COUNT] = { 0, 0 };
    UINT m_chartValueY[CHART_SLOT_COUNT] = { 0, 0 };
    UINT m_chartValueW[CHART_SLOT_COUNT] = { 0, 0 };
    UINT m_chartValueH[CHART_SLOT_COUNT] = { 0, 0 };
    UINT64 m_chartUploads = 0;
    UINT64 m_chartUploadedBytes = 0;
    UINT64 m_chartStaticUploads = 0;
    UINT64 m_chartStaticUploadedBytes = 0;
    UINT64 m_chartDynamicUploads = 0;
    UINT64 m_chartDynamicUploadedBytes = 0;
    UINT m_chartTextureCreates = 0;
    double m_chartBlendMs = 0.0;
    double m_chartClearMs = 0.0;

    // ── ETAP 5L: GPU gauge compositor resources ────────────────────────
    ID3D11Texture2D* m_gaugeTexture = nullptr;
    ID3D11ShaderResourceView* m_gaugeSRV = nullptr;
    UINT m_gaugeDstX = 0;
    UINT m_gaugeDstY = 0;
    UINT m_gaugeW = 0;
    UINT m_gaugeH = 0;
    bool m_gaugeActive = false;
    bool m_gaugeGpuEnabled = false;
    UINT64 m_gaugeUploads = 0;
    UINT64 m_gaugeUploadedBytes = 0;
    UINT m_gaugeTextureCreates = 0;
    double m_gaugeBlendMs = 0.0;
    double m_gaugeClearMs = 0.0;

    ID3D11Device3* m_device3 = nullptr;
    ID3D11ComputeShader* m_nv12HUDComputeShader = nullptr;
    ID3D11ComputeShader* m_nv12RangeComputeShader = nullptr;
    ID3D11ComputeShader* m_nv12FusedComputeShader = nullptr;
    std::vector<ID3D11UnorderedAccessView*> m_outputYViews;
    std::vector<ID3D11UnorderedAccessView*> m_outputUVViews;

    std::vector<ID3D11Texture2D*> m_outputPool;
    std::vector<ID3D11VideoProcessorOutputView*> m_outputViewPool;
    UINT m_poolIndex = 0;
    UINT m_lastPoolIndex = 0;
    UINT m_poolSize = 8;
    // ETAP 5U — per-slot lifecycle tracking: last frame index submitted into
    // each pool slot, for detecting reuse-before-encoder-consumed.
    std::vector<UINT64> m_slotLastFrame;
    // ETAP 5V — debug-only pool resource accounting (created/released).
    UINT64 m_poolTexturesCreated = 0;
    UINT64 m_poolTexturesReleased = 0;
    UINT64 m_poolViewsCreated = 0;
    UINT64 m_poolViewsReleased = 0;
    bool m_poolLifecycleStats = false;

    ID3D11Query* m_disjointQuery = nullptr;
    ID3D11Query* m_startQuery = nullptr;
    ID3D11Query* m_endQuery = nullptr;

    // ETAP 5R: native frame-accounting toggle (exclusive QPC substage timers).
    bool m_frameAccount = false;

    // ETAP 5S: VP stream-state mode + static-cache invalidation state.
    int m_vpStateMode = 0;          // 0=REFERENCE, 1=STATIC_CACHE, 2=REORDER
    bool m_vpStateApplied = false;  // true once the current signature is applied
    UINT m_appliedStateSig = 0;     // last applied stream-state signature
    UINT m_streamRotation = 0;      // cached source rotation (degrees)

    // ETAP 5T — async GPU timestamp query ring (persistent, zero per-frame wait).
    static const int GPU_TS_RING = 64;          // slots
    static const int GPU_TS_READ_DELAY = 16;    // frames of delay before reading
    static const int GPU_TS_NUM_QUERIES = 8;    // begin,blt,range,charts,gauge,map,hud,end
    bool m_gpuTsEnabled = false;
    bool m_gpuTsInitialized = false;
    bool m_gpuHudOff = false;  // ETAP 5T diagnostic
    ID3D11Query* m_tsDisjoint[GPU_TS_RING] = { nullptr };
    ID3D11Query* m_tsQueries[GPU_TS_RING][GPU_TS_NUM_QUERIES] = {};
    UINT64 m_gpuTsNextRead = 0;                 // oldest unread frame index
    std::vector<GPUFrameTimeline> m_gpuTimeline;
    UINT64 m_gpuTsGetDataCalls = 0;
    UINT64 m_gpuTsGetDataNotReady = 0;
    bool InitGPUTimestampRing();
    void ReleaseGPUTimestampRing();
    void ReadFrameTimestamps(UINT frameIndex);

    UINT m_width = 3840;
    UINT m_height = 2160;
    UINT m_hudWidth = 1920;
    UINT m_hudHeight = 1264;
    int m_flushMode = 0;
};
