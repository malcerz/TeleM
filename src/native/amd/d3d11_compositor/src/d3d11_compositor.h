#pragma once

#include <d3d11.h>
#include <d3d11_1.h>
#include <d3dcompiler.h>
#include <vector>
#include <string>
#include <chrono>
#include <iostream>

struct BenchmarkStats {
    double upload_avg_ms = 0.0;
    double upload_p95_ms = 0.0;
    double upload_p99_ms = 0.0;
    
    double compose_gpu_avg_ms = 0.0;
    double compose_gpu_p95_ms = 0.0;
    double compose_gpu_p99_ms = 0.0;
    
    double total_avg_ms = 0.0;
    double total_p95_ms = 0.0;
    double total_p99_ms = 0.0;

    double max_fps = 0.0;
};

enum class CompositorVariant {
    PixelShader,
    VideoProcessor
};

class D3D11CompositorPoC {
public:
    D3D11CompositorPoC();
    ~D3D11CompositorPoC();

    bool Initialize();
    bool CreateTextures(UINT baseWidth, UINT baseHeight, UINT hudWidth, UINT hudHeight);
    
    // Test methods
    bool UploadHUD_UpdateSubresource(const std::vector<uint8_t>& hudRGBA);
    bool UploadHUD_MapUnmap(const std::vector<uint8_t>& hudRGBA);
    
    bool ComposePixelShader();
    bool ComposeVideoProcessor();
    
    BenchmarkStats RunBenchmark(CompositorVariant variant, UINT iterations = 1000);
    
    bool SaveOutputToPNG(const std::string& filepath);
    bool VerifyAMFCompatibility();
    void LogCapabilities();

private:
    ID3D11Device* m_device = nullptr;
    ID3D11DeviceContext* m_context = nullptr;
    
    // Shaders
    ID3D11VertexShader* m_vertexShader = nullptr;
    ID3D11PixelShader* m_pixelShaderRGBA = nullptr;
    ID3D11PixelShader* m_pixelShaderNV12 = nullptr;

    // Textures
    ID3D11Texture2D* m_baseTextureRGBA = nullptr;
    ID3D11ShaderResourceView* m_baseSRVRGBA = nullptr;
    
    ID3D11Texture2D* m_hudTextureDynamic = nullptr;
    ID3D11Texture2D* m_hudTextureStaging = nullptr;
    ID3D11ShaderResourceView* m_hudSRV = nullptr;

    ID3D11Texture2D* m_outputTexture = nullptr;
    ID3D11RenderTargetView* m_outputRTV = nullptr;
    ID3D11ShaderResourceView* m_outputSRV = nullptr;
    
    // Video Processor
    ID3D11VideoDevice* m_videoDevice = nullptr;
    ID3D11VideoContext* m_videoContext = nullptr;
    ID3D11VideoProcessorEnumerator* m_videoEnumerator = nullptr;
    ID3D11VideoProcessor* m_videoProcessor = nullptr;
    
    // Timing queries
    ID3D11Query* m_disjointQuery = nullptr;
    ID3D11Query* m_startQuery = nullptr;
    ID3D11Query* m_endQuery = nullptr;

    UINT m_baseWidth = 3840;
    UINT m_baseHeight = 2160;
    UINT m_hudWidth = 1920;
    UINT m_hudHeight = 1264;
};
