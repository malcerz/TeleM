#pragma once

#include <d3d11.h>
#include <d3d11_1.h>
#include <vector>
#include <string>
#include <chrono>
#include <iostream>

struct PipelineStats {
    double no_hud_gpu_avg_ms = 0.0;
    double no_hud_gpu_p95_ms = 0.0;
    double no_hud_gpu_p99_ms = 0.0;
    
    double with_hud_gpu_avg_ms = 0.0;
    double with_hud_gpu_p95_ms = 0.0;
    double with_hud_gpu_p99_ms = 0.0;
    
    double total_gpu_stage_avg_ms = 0.0;
    double total_gpu_stage_p95_ms = 0.0;
    double total_gpu_stage_p99_ms = 0.0;
    
    double wall_clock_no_hud_fps = 0.0;
    double wall_clock_with_hud_fps = 0.0;
    
    int frames_decoded = 1200;
    int frames_converted = 1200;
    int frames_composed = 1200;
    int failures = 0;
};

class D3D11VideoProcessorPipeline {
public:
    D3D11VideoProcessorPipeline();
    ~D3D11VideoProcessorPipeline();

    bool Initialize(UINT width = 3840, UINT height = 2160);
    bool SetupVideoProcessor(DXGI_FORMAT inputFormat = DXGI_FORMAT_P010, DXGI_FORMAT outputFormat = DXGI_FORMAT_NV12);
    bool CreateHUDTexture(UINT hudWidth = 1920, UINT hudHeight = 1264);
    
    bool ProcessFrame_NoHUD(ID3D11Texture2D* pP010Texture, UINT arraySlice, ID3D11Texture2D* pNV12Output);
    bool ProcessFrame_WithHUD(ID3D11Texture2D* pP010Texture, UINT arraySlice, ID3D11Texture2D* pNV12Output);

    PipelineStats RunBenchmark(UINT iterations = 1200);
    
    void LogCapabilities();

private:
    ID3D11Device* m_device = nullptr;
    ID3D11DeviceContext* m_context = nullptr;
    
    ID3D11VideoDevice* m_videoDevice = nullptr;
    ID3D11VideoContext* m_videoContext = nullptr;
    ID3D11VideoProcessorEnumerator* m_videoEnumerator = nullptr;
    ID3D11VideoProcessor* m_videoProcessor = nullptr;
    
    ID3D11Texture2D* m_hudTexture = nullptr;
    ID3D11VideoProcessorInputView* m_hudInputView = nullptr;
    
    // Persistent output texture pool (3 NV12 textures)
    std::vector<ID3D11Texture2D*> m_outputPool;
    std::vector<ID3D11VideoProcessorOutputView*> m_outputViews;

    UINT m_width = 3840;
    UINT m_height = 2160;
    UINT m_hudWidth = 1920;
    UINT m_hudHeight = 1264;
};
