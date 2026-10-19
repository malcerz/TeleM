#ifndef TELEM_NVENC_API_H
#define TELEM_NVENC_API_H

#include <stdint.h>
#include <wchar.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifdef TELEM_NVENC_BUILD_DLL
    #define TELEM_NVENC_API __declspec(dllexport)
#else
    #define TELEM_NVENC_API __declspec(dllimport)
#endif

#pragma pack(push, 1)

// Expanded per-frame telemetry state for all production indicators
typedef struct TelemFrameState {
    uint32_t frame_index;
    double   timestamp_sec;
    
    // Raw numeric values for dynamic positioning (marker, needle, fill, cursor)
    float    speed_kmh;
    float    heart_rate_bpm;
    float    cadence_rpm;
    float    power_w;
    float    distance_km;
    float    altitude_m;
    float    solar_pct;
    float    garmin_battery_pct;
    float    gopro_battery_pct;
    float    temperature_c;
    float    iso;
    float    exposure_denom;
    float    avg_speed_kmh;
    double   elapsed_sec;
    float    activity_progress; // 0.0 to 1.0 for chart cursor

    // Exact pre-formatted display strings (guarantees 100% telemetry text parity with Python)
    char     time_display_date[32];      // e.g. "2026-07-28"
    char     time_display_time[32];      // e.g. "14:32:15"
    char     time_display_elapsed[32];   // e.g. "00:03" or "01:23:45"
    char     time_display_avg_speed[32]; // e.g. "14.2 km/h"
    
    char     speed_str[32];              // e.g. "22.4"
    char     hr_str[32];                 // e.g. "90"
    char     cad_str[32];                // e.g. "75"
    char     power_str[32];              // e.g. "185"
    char     distance_str[32];           // e.g. "0.00"
    char     altitude_str[32];           // e.g. "35.20"
    char     solar_str[32];              // e.g. "0"
    char     garmin_battery_str[32];     // e.g. "98.0"
    char     gopro_battery_str[32];      // e.g. "100.0%"
    char     temp_str[32];               // e.g. "27.0°C"
    char     iso_str[32];                // e.g. "100"
    char     exposure_str[32];           // e.g. "1/590"

    // Map telemetry
    double   map_latitude;
    double   map_longitude;
    float    map_heading_deg;
    int32_t  has_map_heading;
} TelemFrameState;

// Telemetry field mapping enum
typedef enum TelemFieldId {
    TELEM_FIELD_NONE = 0,
    TELEM_FIELD_TIME_DISPLAY = 1,
    TELEM_FIELD_SPEED = 2,
    TELEM_FIELD_HEART_RATE = 3,
    TELEM_FIELD_CADENCE = 4,
    TELEM_FIELD_POWER = 5,
    TELEM_FIELD_DISTANCE = 6,
    TELEM_FIELD_ALTITUDE = 7,
    TELEM_FIELD_SOLAR = 8,
    TELEM_FIELD_GARMIN_BATTERY = 9,
    TELEM_FIELD_GOPRO_BATTERY = 10,
    TELEM_FIELD_TEMPERATURE = 11,
    TELEM_FIELD_ISO = 12,
    TELEM_FIELD_EXPOSURE = 13
} TelemFieldId;

// Indicator Types
typedef enum TelemIndicatorType {
    TELEM_IND_TEXT = 0,
    TELEM_IND_TIME_DISPLAY = 1,
    TELEM_IND_BAR_RULER_H = 2,
    TELEM_IND_BAR_RULER_V = 3,
    TELEM_IND_BAR_SEGMENTS = 4,
    TELEM_IND_GAUGE = 5,
    TELEM_IND_CHART = 6,
    TELEM_IND_MAP = 7
} TelemIndicatorType;

// Styles for individual indicator types
typedef struct TelemTextStyle {
    wchar_t  font_family[64];
    float    font_size;
    uint32_t text_color;     // 0xAARRGGBB
    uint32_t outline_color;  // 0xAARRGGBB
    float    outline_width;
    wchar_t  label[64];
    wchar_t  unit[32];
    char     icon_name[32];
    float    icon_size;
    int32_t  telemetry_field;
    float    canvas_x;       // exact top-left canvas X
    float    canvas_y;       // exact top-left canvas Y
    float    icon_offset_y;  // optical Y offset for icon
    float    text_offset_y;  // optical Y offset for text
} TelemTextStyle;

typedef struct TelemTimeDisplayStyle {
    wchar_t  font_family[64];
    float    global_font_size;
    float    outline_width;
    int32_t  show_date;
    int32_t  show_time;
    int32_t  show_elapsed;
    int32_t  show_avg_speed;
    wchar_t  date_label[32];
    wchar_t  time_label[32];
    wchar_t  elapsed_label[32];
    wchar_t  avg_speed_label[32];
    uint32_t date_color;
    uint32_t time_color;
    uint32_t elapsed_color;
    uint32_t avg_speed_color;
    float    date_font_size;
    float    time_font_size;
    float    elapsed_font_size;
    float    avg_speed_font_size;
    char     icon_name[32];
    float    icon_size;
    float    canvas_x;
    float    canvas_y;
    float    line_spacing;
} TelemTimeDisplayStyle;

typedef struct TelemBarStyle {
    wchar_t  font_family[64];
    float    title_font_size;
    float    range_font_size;
    float    value_font_size;
    float    outline_width;
    wchar_t  title[64];
    wchar_t  unit[32];
    int32_t  show_label;
    int32_t  show_range;
    int32_t  show_value;
    int32_t  show_mid;
    int32_t  show_tick_labels;
    int32_t  range_units;
    int32_t  major_divisions;
    int32_t  minor_per_major;
    float    major_step;
    float    min_val;
    float    max_val;
    uint32_t track_color;
    uint32_t tick_color;
    uint32_t text_color;
    uint32_t dim_text_color;
    uint32_t marker_color;
    uint32_t marker_border_color;
    float    track_width;
    float    major_len;
    float    minor_len;
    float    marker_size;
    int32_t  marker_style;   // 0 = dot, 1 = line
    int32_t  telemetry_field;
    float    track_canvas_x;
    float    track_canvas_y;
    float    track_len;
    float    title_canvas_x;
    float    title_canvas_y;
    float    range_canvas_y;
    float    value_canvas_y;
    float    value_offset_x;
    float    value_offset_y;
} TelemBarStyle;

typedef struct TelemSegmentBarStyle {
    wchar_t  font_family[64];
    float    label_font_size;
    float    value_font_size;
    float    range_font_size;
    float    outline_width;
    wchar_t  label[64];
    wchar_t  unit[32];
    int32_t  segments;
    float    gap;
    float    radius;
    float    min_val;
    float    max_val;
    uint32_t active_color;
    uint32_t inactive_color;
    uint32_t text_color;
    uint32_t dim_color;
    int32_t  grow_height;
    float    grow_start;
    int32_t  telemetry_field;
    uint32_t active_color_start;
    uint32_t active_color_end;
    float    seg_canvas_x;
    float    seg_canvas_y;
    float    seg_width;
    float    seg_height;
    float    value_canvas_x;
    float    value_canvas_y;
    float    label_canvas_x;
    float    label_canvas_y;
} TelemSegmentBarStyle;

typedef struct TelemGaugeStyle {
    wchar_t  font_family[64];
    float    gauge_font_size;
    float    value_font_size;
    float    unit_font_size;
    float    outline_width;
    wchar_t  unit[32];
    float    min_val;
    float    max_val;
    float    start_deg;
    float    sweep_deg;
    int32_t  ticks;
    float    step_val;
    int32_t  major_intervals;
    int32_t  sub_ticks_count;
    uint32_t needle_color;
    float    needle_length;
    float    needle_width;
    uint32_t tick_color;
    uint32_t text_color;
    int32_t  telemetry_field;
} TelemGaugeStyle;

typedef struct TelemChartStyle {
    wchar_t  font_family[64];
    float    header_font_size;
    float    axis_font_size;
    float    value_font_size;
    float    outline_width;
    wchar_t  label[64];
    wchar_t  unit[32];
    float    min_val;
    float    max_val;
    uint32_t line_color;
    uint32_t fill_color;
    float    fill_alpha;
    uint32_t grid_color;
    uint32_t text_color;
    int32_t  show_grid;
    int32_t  show_x_axis;
    int32_t  show_y_axis;
    int32_t  label_count;
    int32_t  telemetry_field;
    float    plot_canvas_x1;
    float    plot_canvas_y1;
    float    plot_canvas_x2;
    float    plot_canvas_y2;
    float    header_canvas_x;
    float    header_canvas_y;
    float    value_canvas_x;
    float    value_canvas_y;
} TelemChartStyle;

typedef struct TelemMapStyle {
    wchar_t  font_family[64];
    float    canvas_x;       // center X in pixels
    float    canvas_y;       // center Y in pixels
    float    width;          // pixel width
    float    height;         // pixel height
    int32_t  zoom;           // effective zoom level
    int32_t  rotate_map;     // 1 = track_up, 0 = north_up
    float    alpha;          // 0.0 .. 255.0
    float    track_width;    // rendered track line width in pixels
    uint32_t track_color;    // 0xAARRGGBB
    float    marker_radius;  // marker radius in pixels
    uint32_t marker_color;   // 0xAARRGGBB
    uint32_t marker_border_color; // 0xAARRGGBB
    uint32_t border_color;   // 0xAARRGGBB
    float    border_width;   // border stroke width in pixels
    float    corner_radius;  // corner radius in pixels
    int32_t  marker_style;   // 0 = dot, 1 = directional
} TelemMapStyle;

// Unified descriptor for an active indicator
typedef struct TelemIndicatorDesc {
    TelemIndicatorType type;
    char               key[64];
    float              x;        // pixel position
    float              y;        // pixel position
    float              width;    // pixel width
    float              height;   // pixel height
    float              rotation; // 0, 90, 180, 270
    float              alpha;
    int32_t            z_order;
    
    union {
        TelemTextStyle         text;
        TelemTimeDisplayStyle  time_display;
        TelemBarStyle          bar;
        TelemSegmentBarStyle   segment_bar;
        TelemGaugeStyle        gauge;
        TelemChartStyle        chart;
        TelemMapStyle          map;
    } style;
} TelemIndicatorDesc;

// Multi-clip video sequence descriptor
typedef struct TelemVideoClipDesc {
    wchar_t  path[512];
    uint32_t frame_count;
    double   duration_sec;
    uint32_t fps_num;
    uint32_t fps_den;
    uint32_t global_start_frame;
    double   global_start_time;
} TelemVideoClipDesc;

// Codec & Quality Modes (Stage 8K.4)
typedef enum TelemCodec {
    TELEM_CODEC_HEVC = 0,
    TELEM_CODEC_AV1  = 1
} TelemCodec;

typedef enum TelemQualityMode {
    TELEM_QUALITY_FAST    = 0,
    TELEM_QUALITY_QUALITY = 1,
    TELEM_QUALITY_MAX     = 2
} TelemQualityMode;

typedef struct TelemEncoderConfig {
    uint32_t codec;              // 0 = HEVC, 1 = AV1
    uint32_t quality_mode;       // 0 = FAST, 1 = QUALITY, 2 = MAX
    uint32_t bit_depth;          // 8 or 10 (default 10)
    uint32_t bitrate_bps;        // e.g. 20000000 (20 Mbps baseline)
    uint32_t max_bitrate_bps;    // e.g. 25000000 (25 Mbps)
    uint32_t vbv_size_bits;      // e.g. 20000000 (20 Mb)
    uint32_t gop_length;         // e.g. 250 (0 = default 250)
    uint32_t b_frames;           // 0 = auto from profile, or explicit count
    uint32_t multipass;          // 0 = disabled, 1 = quarter-res, 2 = full-res
    uint32_t enable_lookahead;   // 0 or 1
    uint32_t lookahead_depth;    // e.g. 16 or 25
    uint32_t enable_aq;          // 0 or 1
    uint32_t aq_strength;        // 0 = auto, 1-15
    uint32_t enable_temporal_aq; // 0 or 1
    uint32_t enable_compression_analysis; // 0 = disabled, 1 = live compression analysis enabled
    wchar_t  compression_csv_path[512];   // Optional path to write per-frame time series CSV directly
} TelemEncoderConfig;

// Pipeline configuration
typedef struct TelemNvencConfig {
    uint32_t width;              // e.g. 3840
    uint32_t height;             // e.g. 2160
    uint32_t fps_num;            // e.g. 30000
    uint32_t fps_den;            // e.g. 1001
    uint32_t ring_size;          // e.g. 4 (or auto-sized by profile)
    uint32_t bit_depth;          // 8 (NV12) or 10 (P010 readiness)
    uint32_t preset_p1_to_p7;    // 1 = P1 Fastest, ..., 7 = P7 Slowest
    uint32_t tuning_info;        // 1 = HIGH_QUALITY, 5 = ULTRA_HIGH_QUALITY
    int      async_nvenc;        // 0 = sync lock bitstream, 1 = async event-driven
    int      enable_debug_layer; // 0 = off, 1 = D3D11 Debug Layer

    TelemEncoderConfig encoder_config;
} TelemNvencConfig;

// Thread-safe progress reporting
typedef struct TelemProgressInfo {
    uint32_t completed_frames;
    uint32_t total_frames;
    double   elapsed_sec;
    double   current_fps;
    int      is_active;
    int      is_cancelled;
    int      is_finished;
    int      error_code;
    char     error_message[256];
} TelemProgressInfo;

// Full pipeline benchmark and profiling statistics
typedef struct TelemPipelineStats {
    uint32_t completed_frames;
    double   wall_time_sec;
    double   throughput_fps;
    uint64_t total_bitstream_bytes;
    double   bitrate_mbps;
    
    // Latency metrics (ms)
    double   avg_latency_ms;
    double   median_latency_ms;
    double   p95_latency_ms;
    double   p99_latency_ms;
    double   max_latency_ms;

    // Timing breakdown per frame (ms)
    double   decode_acquire_ms;
    double   telemetry_lookup_ms;
    double   hud_d2d_ms;
    double   vp_composite_ms;
    double   nvenc_submit_ms;
    double   bitstream_handling_ms;

    // Memory metrics (bytes)
    uint64_t ram_start_bytes;
    uint64_t ram_peak_bytes;
    uint64_t ram_end_bytes;
    uint64_t vram_budget_bytes;
    uint64_t vram_usage_bytes;

    // Multi-clip transition metric (ms)
    double   clip_switch_ms;
} TelemPipelineStats;

// Map tile cache statistics
typedef struct TelemMapCacheStats {
    uint32_t total_tiles;
    uint32_t decoded_tiles;
    uint32_t cache_hits;
    uint32_t cache_misses;
    uint64_t vram_bytes;
    uint64_t peak_vram_bytes;
} TelemMapCacheStats;

// Live Compression Analysis Statistics (Stage 8K.5)
typedef struct TelemCompressionStats {
    uint32_t is_active;              // 1 if compression analysis is enabled, 0 if disabled
    uint32_t is_av1;                 // 1 for AV1 (Quantizer/QIndex), 0 for HEVC (QP)
    uint32_t frames_analyzed;        // Total frames analyzed so far
    
    // Live / instantaneous metrics
    uint32_t current_qp;             // QP / quantizer of the most recently encoded frame
    char     current_frame_type;     // 'I', 'P', 'B'
    double   current_bitrate_mbps;   // Instantaneous bitrate of last frame
    
    // Aggregated Quantizer / QP statistics
    double   mean_qp;
    double   median_qp;
    double   p10_qp;
    double   p50_qp;
    double   p90_qp;
    double   p95_qp;
    uint32_t min_qp;
    uint32_t max_qp;
    
    // Per-picture type breakdown
    uint32_t i_frame_count;
    uint32_t p_frame_count;
    uint32_t b_frame_count;
    double   i_frame_mean_qp;
    double   p_frame_mean_qp;
    double   b_frame_mean_qp;
    
    // Bitrate & byte statistics
    uint64_t total_encoded_bytes;
    double   mean_bytes_per_frame;
    double   peak_bitrate_mbps;
    double   average_bitrate_mbps;
    
    // Histogram: counts for QP/quantizer values 0..255 (256 bins)
    // HEVC uses range 0..51, AV1 uses base_q_idx / quantizer range 0..255
    uint32_t qp_histogram[256];
} TelemCompressionStats;

#pragma pack(pop)

typedef void* HTelemNvenc;

// Lifecycle & Configuration
TELEM_NVENC_API HTelemNvenc telem_nvenc_create(void);
TELEM_NVENC_API int         telem_nvenc_configure(HTelemNvenc handle, const TelemNvencConfig* config);
TELEM_NVENC_API int         telem_nvenc_open_video(HTelemNvenc handle, const wchar_t* video_path);
TELEM_NVENC_API int         telem_nvenc_set_video_sequence(HTelemNvenc handle, const TelemVideoClipDesc* clips, uint32_t count);
TELEM_NVENC_API int         telem_nvenc_set_telemetry(HTelemNvenc handle, const TelemFrameState* states, uint32_t count);
TELEM_NVENC_API int         telem_nvenc_set_indicators(HTelemNvenc handle, const TelemIndicatorDesc* indicators, uint32_t count);
TELEM_NVENC_API int         telem_nvenc_set_chart_samples(HTelemNvenc handle, const char* indicator_key, const float* samples, uint32_t sample_count);
TELEM_NVENC_API int         telem_nvenc_set_map_route(HTelemNvenc handle, const double* lats, const double* lons, uint32_t count);
TELEM_NVENC_API int         telem_nvenc_preload_map_tile(HTelemNvenc handle, int32_t z, int32_t x, int32_t y, const void* data, uint32_t size_bytes);

// Visual Parity / Transparent HUD Extraction
TELEM_NVENC_API int         telem_nvenc_render_hud_frame_to_file(HTelemNvenc handle, uint32_t frame_index, const wchar_t* output_png_path);
TELEM_NVENC_API int         telem_nvenc_render_hud_frame_to_buffer(HTelemNvenc handle, uint32_t frame_index, void* out_bgra_buffer, uint32_t buffer_size, uint32_t* out_width, uint32_t* out_height, uint32_t* out_pitch);

// Execution
TELEM_NVENC_API int         telem_nvenc_start_export(HTelemNvenc handle, const wchar_t* output_hevc_path, uint32_t start_frame, uint32_t frame_count, int include_hud);
TELEM_NVENC_API void        telem_nvenc_cancel(HTelemNvenc handle);
TELEM_NVENC_API int         telem_nvenc_wait_completion(HTelemNvenc handle, uint32_t timeout_ms);

// Monitoring & Statistics
TELEM_NVENC_API void        telem_nvenc_get_progress(HTelemNvenc handle, TelemProgressInfo* out_progress);
TELEM_NVENC_API void        telem_nvenc_get_stats(HTelemNvenc handle, TelemPipelineStats* out_stats);
TELEM_NVENC_API void        telem_nvenc_get_map_cache_stats(HTelemNvenc handle, TelemMapCacheStats* out_stats);
TELEM_NVENC_API void        telem_nvenc_get_compression_stats(HTelemNvenc handle, TelemCompressionStats* out_stats);
TELEM_NVENC_API int         telem_nvenc_export_compression_csv(HTelemNvenc handle, const wchar_t* csv_path);

// Cleanup
TELEM_NVENC_API void        telem_nvenc_close_video(HTelemNvenc handle);
TELEM_NVENC_API void        telem_nvenc_destroy(HTelemNvenc handle);

// Live Render Preview Tap (Stage 8L.4)
TELEM_NVENC_API int         telem_nvenc_set_preview_tap(HTelemNvenc handle, int enabled, uint32_t width, uint32_t height, double target_fps);
TELEM_NVENC_API int         telem_nvenc_poll_preview_frame(HTelemNvenc handle, uint8_t* out_bgra, uint32_t buffer_size, uint32_t* out_width, uint32_t* out_height, uint32_t* out_frame_idx, double* out_pts);

#ifdef __cplusplus
}
#endif

#endif // TELEM_NVENC_API_H
