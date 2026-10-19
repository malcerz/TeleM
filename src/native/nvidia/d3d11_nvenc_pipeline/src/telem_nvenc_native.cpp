#include "telem_nvenc_api.h"
#include "d3d11_nvenc_pipeline.h"

extern "C" {

TELEM_NVENC_API HTelemNvenc telem_nvenc_create(void) {
    D3D11NvencPipeline* pipeline = new D3D11NvencPipeline();
    return static_cast<HTelemNvenc>(pipeline);
}

TELEM_NVENC_API int telem_nvenc_configure(HTelemNvenc handle, const TelemNvencConfig* config) {
    if (!handle || !config) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->Configure(*config) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_open_video(HTelemNvenc handle, const wchar_t* video_path) {
    if (!handle || !video_path) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->OpenVideo(std::wstring(video_path)) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_set_video_sequence(HTelemNvenc handle, const TelemVideoClipDesc* clips, uint32_t count) {
    if (!handle || !clips || count == 0) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->SetVideoSequence(clips, count) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_set_telemetry(HTelemNvenc handle, const TelemFrameState* states, uint32_t count) {
    if (!handle) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->SetTelemetry(states, count) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_set_indicators(HTelemNvenc handle, const TelemIndicatorDesc* indicators, uint32_t count) {
    if (!handle) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->SetIndicators(indicators, count) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_set_chart_samples(HTelemNvenc handle, const char* indicator_key, const float* samples, uint32_t sample_count) {
    if (!handle || !indicator_key) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->SetChartSamples(indicator_key, samples, sample_count) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_set_map_route(HTelemNvenc handle, const double* lats, const double* lons, uint32_t count) {
    if (!handle) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->SetMapRoute(lats, lons, count) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_preload_map_tile(HTelemNvenc handle, int32_t z, int32_t x, int32_t y, const void* data, uint32_t size_bytes) {
    if (!handle) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->PreloadMapTile(z, x, y, data, size_bytes) ? 1 : 0;
}

TELEM_NVENC_API void telem_nvenc_get_map_cache_stats(HTelemNvenc handle, TelemMapCacheStats* out_stats) {
    if (!handle || !out_stats) return;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    pipeline->GetMapCacheStats(*out_stats);
}

TELEM_NVENC_API int telem_nvenc_render_hud_frame_to_file(HTelemNvenc handle, uint32_t frame_index, const wchar_t* output_png_path) {
    if (!handle || !output_png_path) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->RenderHudFrameToFile(frame_index, std::wstring(output_png_path)) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_render_hud_frame_to_buffer(HTelemNvenc handle, uint32_t frame_index, void* out_bgra_buffer, uint32_t buffer_size, uint32_t* out_width, uint32_t* out_height, uint32_t* out_pitch) {
    if (!handle || !out_bgra_buffer) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->RenderHudFrameToBuffer(frame_index, out_bgra_buffer, buffer_size, out_width, out_height, out_pitch) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_start_export(HTelemNvenc handle, const wchar_t* output_hevc_path, uint32_t start_frame, uint32_t frame_count, int include_hud) {
    if (!handle || !output_hevc_path) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->StartExport(std::wstring(output_hevc_path), start_frame, frame_count, include_hud != 0) ? 1 : 0;
}

TELEM_NVENC_API void telem_nvenc_cancel(HTelemNvenc handle) {
    if (!handle) return;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    pipeline->Cancel();
}

TELEM_NVENC_API int telem_nvenc_wait_completion(HTelemNvenc handle, uint32_t timeout_ms) {
    if (!handle) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->WaitCompletion(timeout_ms) ? 1 : 0;
}

TELEM_NVENC_API void telem_nvenc_get_progress(HTelemNvenc handle, TelemProgressInfo* out_progress) {
    if (!handle || !out_progress) return;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    pipeline->GetProgress(*out_progress);
}

TELEM_NVENC_API void telem_nvenc_get_stats(HTelemNvenc handle, TelemPipelineStats* out_stats) {
    if (!handle || !out_stats) return;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    pipeline->GetStats(*out_stats);
}

TELEM_NVENC_API void telem_nvenc_get_compression_stats(HTelemNvenc handle, TelemCompressionStats* out_stats) {
    if (!handle || !out_stats) return;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    pipeline->GetCompressionStats(*out_stats);
}

TELEM_NVENC_API int telem_nvenc_export_compression_csv(HTelemNvenc handle, const wchar_t* csv_path) {
    if (!handle || !csv_path) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->ExportCompressionCsv(csv_path) ? 1 : 0;
}

TELEM_NVENC_API void telem_nvenc_close_video(HTelemNvenc handle) {
    if (!handle) return;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    pipeline->CloseVideo();
}

TELEM_NVENC_API void telem_nvenc_destroy(HTelemNvenc handle) {
    if (!handle) return;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    pipeline->Destroy();
    delete pipeline;
}

TELEM_NVENC_API int telem_nvenc_set_preview_tap(HTelemNvenc handle, int enabled, uint32_t width, uint32_t height, double target_fps) {
    if (!handle) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    if (!enabled) {
        pipeline->ReleasePreviewTap();
        return 1;
    }
    return pipeline->ConfigurePreviewTap(width, height, target_fps) ? 1 : 0;
}

TELEM_NVENC_API int telem_nvenc_poll_preview_frame(HTelemNvenc handle, uint8_t* out_bgra, uint32_t buffer_size, uint32_t* out_width, uint32_t* out_height, uint32_t* out_frame_idx, double* out_pts) {
    if (!handle || !out_bgra) return 0;
    D3D11NvencPipeline* pipeline = static_cast<D3D11NvencPipeline*>(handle);
    return pipeline->PollPreviewFrame(out_bgra, buffer_size, out_width, out_height, out_frame_idx, out_pts) ? 1 : 0;
}

} // extern "C"
