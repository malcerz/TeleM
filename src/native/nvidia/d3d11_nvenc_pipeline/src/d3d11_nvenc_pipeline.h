#ifndef D3D11_NVENC_PIPELINE_H
#define D3D11_NVENC_PIPELINE_H

#include <windows.h>
#include <d3d10.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <dxgi1_4.h>
#include <d2d1_1.h>
#include <dwrite.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <mferror.h>
#include <psapi.h>

#include <vector>
#include <queue>
#include <string>
#include <map>
#include <memory>
#include <chrono>
#include <thread>
#include <atomic>
#include <mutex>
#include <fstream>
#include <cmath>

#include "nvEncodeAPI.h"
#include "telem_nvenc_api.h"
#include "indicators/indicator_base.h"
#include "indicators/font_cache.h"
#include "indicators/icon_cache.h"
#include "indicators/text_indicator.h"
#include "indicators/time_display_indicator.h"
#include "indicators/bar_indicator.h"
#include "indicators/segment_bar_indicator.h"
#include "indicators/gauge_indicator.h"
#include "indicators/chart_indicator.h"
#include "indicators/map_indicator.h"

// RAII helper to safely release COM interfaces
template <typename T>
inline void SafeRelease(T*& ptr) {
    if (ptr) {
        ptr->Release();
        ptr = nullptr;
    }
}

struct FrameLifecycleLog {
    uint32_t frame_index;
    uint64_t qpc_timestamp;

    int ring_slot;
    int wrap_count;

    int slot_owner_before;
    int slot_owner_after;
    int slot_in_flight;

    uint32_t submitted_input_frame;
    int submitted_slot;

    size_t ownership_queue_depth;

    void* hud_texture_ptr;
    void* d2d_target_ptr;
    void* vp_hud_input_view_ptr;

    int hud_query_status_before_reuse;
    int vp_query_status_before_reuse;

    int begin_draw_status;
    uint32_t end_draw_hresult;
    uint32_t d2d_flush_hresult;
    uint64_t d2d_tag1;
    uint64_t d2d_tag2;
    bool composite_result;
    uint32_t vp_blt_hresult;

    int encoded_frame;
    int released_input_frame;
    int released_slot;

    uint32_t active_indicators;
    uint32_t device_removed_reason;
};

class D3D11NvencPipeline {
public:
    D3D11NvencPipeline();
    ~D3D11NvencPipeline();

    bool Configure(const TelemNvencConfig& config);
    bool OpenVideo(const std::wstring& video_path);
    bool SetVideoSequence(const TelemVideoClipDesc* clips, uint32_t count);
    bool SetTelemetry(const TelemFrameState* states, uint32_t count);
    bool SetIndicators(const TelemIndicatorDesc* indicators, uint32_t count);
    bool SetChartSamples(const char* indicator_key, const float* samples, uint32_t sample_count);
    bool SetMapRoute(const double* lats, const double* lons, uint32_t count);
    bool PreloadMapTile(int32_t z, int32_t x, int32_t y, const void* data, uint32_t size_bytes);
    void GetMapCacheStats(TelemMapCacheStats& out_stats);
    bool RenderHudFrameToFile(uint32_t frame_index, const std::wstring& output_png_path);
    bool RenderHudFrameToBuffer(uint32_t frame_index, void* out_bgra_buffer, uint32_t buffer_size, uint32_t* out_width, uint32_t* out_height, uint32_t* out_pitch);

    bool StartExport(const std::wstring& output_hevc_path, uint32_t start_frame, uint32_t frame_count, bool include_hud);
    void Cancel();
    bool WaitCompletion(uint32_t timeout_ms);

    void GetProgress(TelemProgressInfo& out_progress);
    void GetStats(TelemPipelineStats& out_stats);
    void GetCompressionStats(TelemCompressionStats& out_stats);
    bool ExportCompressionCsv(const wchar_t* csv_path);

    void CloseVideo();
    void Destroy();

    // Live Render Preview Tap (Stage 8L.4)
    bool ConfigurePreviewTap(uint32_t width, uint32_t height, double target_fps);
    void ReleasePreviewTap();
    bool PollPreviewFrame(uint8_t* out_bgra, uint32_t buffer_size, uint32_t* out_width, uint32_t* out_height, uint32_t* out_frame_idx, double* out_pts);

private:
    // Core Subsystems
    bool SelectAdapter();
    bool CreateDevice();
    bool CreateHudResources();
    bool CreateDWrite();
    bool CreateBrushes();
    bool CreateVideoProcessor();
    bool CreateRingResources();

    // Decoder & Multi-Clip Chaining
    bool InitDecoder();
    bool OpenClip(uint32_t clip_idx);
    bool SwitchToNextClip();
    bool SeekToGlobalFrame(uint32_t target_global_frame);
    void CloseDecoder();
    ID3D11VideoProcessorInputView* AcquireDecoderFrame(int64_t& out_pts, uint32_t& out_flags);

    // Direct2D HUD
    HRESULT RenderHud(const TelemFrameState& state, int slot);
    bool SaveTextureToPng(ID3D11Texture2D* pTex, const wchar_t* output_png_path);

    // Compositing
    bool Composite(ID3D11VideoProcessorInputView* pVideoInView, int ring_slot, bool include_hud);

struct TelemEncodeDiagInfo {
    uint32_t encode_status = 0;
    uint32_t pending_count = 0;
    bool bitstream_ready = false;
    int bitstream_slot = -1;
    uint32_t bitstream_frame_index = 0;
    uint32_t bitstream_picture_type = 0;
    bool is_first_bitstream = false;
    int released_slot = -1;
    bool slot_reused = false;
    void* mapped_input_handle = nullptr;
};

    // NVENC Encoder
    bool StartNvencSession();
    void EndNvencSession();
    bool ProcessBitstreamQueue(HANDLE hOutputFile, bool blocking, TelemEncodeDiagInfo* pDiag = nullptr);
    bool EncodeFrame(int ring_slot, uint32_t session_frame_idx, uint32_t global_frame_idx, HANDLE hOutputFile, double& out_submit_time, double& out_bs_time, TelemEncodeDiagInfo* pDiag = nullptr);
    bool DrainNvenc(HANDLE hOutputFile);

    // Worker thread loop
    void FrameLoopThread(std::wstring output_path, uint32_t start_frame, uint32_t frame_count, bool include_hud);

    // Memory & Profiling
    void QueryVram(uint64_t& out_budget, uint64_t& out_usage);
    uint64_t QueryRam();

    // Live Compression Analysis (Stage 8K.5)
    void RecordCompressionSample(uint32_t frame_idx, uint64_t pts, NV_ENC_PIC_TYPE pic_type, uint32_t qp, uint32_t bytes);

private:
    TelemNvencConfig                m_config;
    bool                            m_configured;
    bool                            m_video_opened;
    std::vector<TelemVideoClipDesc> m_clips;
    uint32_t                        m_current_clip_idx;
    uint32_t                        m_clip_frames_decoded;
    double                          m_clip_switch_ms;
    IMFSample*                      m_pPendingSample;

    // DXGI & D3D11
    IDXGIFactory1*        m_pFactory;
    IDXGIAdapter1*        m_pAdapter;
    IDXGIAdapter3*        m_pAdapter3;
    DXGI_ADAPTER_DESC     m_adapter_desc;
    ID3D11Device*         m_pDevice;
    ID3D11DeviceContext*  m_pContext;

    // Direct2D & DirectWrite
    ID3D11Texture2D*      m_pHudTexture; // points to m_ring_hud_textures[0]
    ID3D11Texture2D*      m_pStagingHudTex;
    ID2D1Device*          m_pD2DDevice;
    ID2D1DeviceContext*   m_pD2DContext;
    IDWriteFactory*       m_pDWriteFactory;

    // Text Formats & Brushes
    IDWriteTextFormat*    m_fmt_time;
    IDWriteTextFormat*    m_fmt_speed_val;
    IDWriteTextFormat*    m_fmt_speed_unit;
    IDWriteTextFormat*    m_fmt_hr_val;
    IDWriteTextFormat*    m_fmt_hr_unit;
    IDWriteTextFormat*    m_fmt_label;

    ID2D1SolidColorBrush* m_brush_white;
    ID2D1SolidColorBrush* m_brush_text_muted;
    ID2D1SolidColorBrush* m_brush_cyan;
    ID2D1SolidColorBrush* m_brush_coral;
    ID2D1SolidColorBrush* m_brush_card_bg;
    ID2D1SolidColorBrush* m_brush_card_border;

    // D3D11 Video Processor
    ID3D11VideoDevice*                  m_pVideoDevice;
    ID3D11VideoContext*                 m_pVideoContext;
    ID3D11VideoProcessorEnumerator*     m_pVPEnum;
    ID3D11VideoProcessor*               m_pVP;

    // Ring Resources (Persistent D3D11 Textures, VP Views & D2D Targets)
    std::vector<ID3D11Texture2D*>                m_ring_nv12_textures;
    std::vector<ID3D11VideoProcessorOutputView*>  m_ring_vp_out_views;
    std::vector<ID3D11Texture2D*>                m_ring_hud_textures;
    std::vector<ID3D11Texture2D*>                m_ring_hud_resolved_textures;
    std::vector<ID2D1Bitmap1*>                   m_ring_d2d_bitmap_targets;
    std::vector<ID3D11VideoProcessorInputView*>  m_ring_vp_in_view_huds;
    std::vector<ID3D11Query*>                    m_ring_hud_queries;
    std::vector<ID3D11Query*>                    m_ring_vp_queries;
    ID3D11Texture2D*                             m_pHudSyncStagingTex;

    // Media Foundation Decoder
    IMFDXGIDeviceManager* m_pDevMgr;
    IMFAttributes*        m_pReaderAttributes;
    IMFSourceReader*      m_pSourceReader;
    bool                  m_decoder_eof;
    std::map<std::pair<ID3D11Texture2D*, UINT>, ID3D11VideoProcessorInputView*> m_view_cache;

    // NVENC
    HMODULE                       m_hNvencDll;
    NV_ENCODE_API_FUNCTION_LIST   m_nvenc;
    void*                         m_hEncoder;
    NV_ENC_PRESET_CONFIG          m_preset_cfg;
    std::vector<void*>            m_ring_registered_handles;
    std::vector<void*>            m_all_bitstream_buffers;
    std::queue<void*>             m_free_bitstream_buffers;
    std::queue<void*>             m_in_flight_bitstream_buffers;
    struct InFlightBitstreamOwnership {
        void* bitstream;
        uint32_t input_frame;
        int ring_slot;
    };
    std::queue<InFlightBitstreamOwnership> m_in_flight_bitstream_ownership;
    std::vector<HANDLE>           m_ring_completion_events;
    uint32_t                      m_consumer_index{0};
    bool                          m_first_bs_seen{false};
    std::vector<int>              m_slot_in_flight;
    struct RingReleaseDiag {
        uint32_t submitted_input_frame;
        uint32_t lock_frame_idx;
        int owned_ring_slot;
        int released_slot;
        int released_slot_previous_owner;
        bool lock_frame_matches_owner;
    };
    std::vector<RingReleaseDiag>  m_ring_release_diags;
    FILE*                         m_pSlot0File{nullptr};
    int                           m_slot0_last_input{-1};
    int                           m_slot0_last_encoded{-1};
    void*                         m_slot0_mapped_handle{nullptr};
    const char*                   m_slot0_map_state{"UNMAPPED"};
    void LogSlot0State(const char* event_name);

    bool ResolveEncoderProfile(GUID& outCodecGuid, GUID& outProfileGuid, GUID& outPresetGuid, NV_ENC_TUNING_INFO& outTuningInfo, NV_ENC_CONFIG& outConfig, uint32_t& outRequiredRingSize);

    // Telemetry storage
    std::vector<TelemFrameState>  m_telemetry_table;

    // Production Indicators & Direct2D Resources
    FontCache                                    m_font_cache;
    IconCache                                    m_icon_cache;
    std::vector<std::unique_ptr<IndicatorBase>>  m_indicators;
    std::map<std::string, std::vector<float>>    m_chart_samples;
    std::vector<std::pair<double, double>>       m_map_route;
    std::map<std::tuple<int, int, int>, std::vector<uint8_t>> m_preloaded_tiles;

    // Threading & Progress
    std::thread                   m_worker_thread;
    std::atomic<bool>             m_is_active;
    std::atomic<bool>             m_cancel_requested;
    std::atomic<bool>             m_is_finished;
    std::mutex                    m_progress_mutex;
    TelemProgressInfo             m_progress;
    TelemPipelineStats            m_stats;

    // Live Compression Analysis (Stage 8K.5)
    struct FrameCompressionSample {
        uint32_t frame_index;
        double   timestamp_sec;
        char     frame_type; // 'I', 'P', 'B'
        uint8_t  qp;         // 0..255
        uint32_t encoded_bytes;
    };

    bool                                m_enable_compression_analysis;
    std::wstring                        m_compression_csv_path;
    FILE*                               m_compression_csv_file;
    std::vector<FrameCompressionSample> m_compression_samples;
    std::mutex                          m_compression_mutex;
    TelemCompressionStats               m_live_compression_stats;
    uint64_t                            m_i_frame_qp_sum;
    uint64_t                            m_p_frame_qp_sum;
    uint64_t                            m_b_frame_qp_sum;
    uint64_t                            m_total_qp_sum;

    // Live Render Preview Tap (Stage 8L.4)
    bool                                m_preview_tap_enabled{false};
    uint32_t                            m_preview_tap_width{960};
    uint32_t                            m_preview_tap_height{540};
    double                              m_preview_interval_sec{0.125};
    double                              m_preview_last_submit_time{0.0};
    ID3D11VideoProcessorEnumerator*     m_pPreviewVPEnum{nullptr};
    ID3D11VideoProcessor*               m_pPreviewVP{nullptr};
    std::vector<ID3D11VideoProcessorInputView*> m_ring_preview_in_views;
    ID3D11Texture2D*                    m_preview_output_tex[2]{nullptr, nullptr};
    ID3D11VideoProcessorOutputView*     m_preview_output_view[2]{nullptr, nullptr};
    ID3D11Texture2D*                    m_preview_staging_tex[2]{nullptr, nullptr};
    ID3D11Query*                        m_preview_query[2]{nullptr, nullptr};
    bool                                m_preview_capture_in_flight{false};
    uint32_t                            m_preview_in_flight_slot{0};
    uint32_t                            m_preview_in_flight_frame{0};
    double                              m_preview_in_flight_pts{0.0};
    uint32_t                            m_preview_next_slot{0};
    std::mutex                          m_preview_mutex;
    std::vector<uint8_t>                m_preview_ram_buffer;
    bool                                m_preview_has_new_frame{false};
    uint32_t                            m_preview_ready_frame_idx{0};
    double                              m_preview_ready_pts{0.0};

    // Forensic In-Memory Lifecycle Diagnostics (Low Overhead)
    std::vector<FrameLifecycleLog>      m_lifecycle_logs;
    void DumpLifecycleLogs();
    HRESULT                             m_last_vp_blt_hr{S_OK};
    HRESULT                             m_last_end_draw_hr{S_OK};
    HRESULT                             m_last_d2d_flush_hr{S_OK};
    uint64_t                            m_last_d2d_tag1{0};
    uint64_t                            m_last_d2d_tag2{0};
};

#endif // D3D11_NVENC_PIPELINE_H
