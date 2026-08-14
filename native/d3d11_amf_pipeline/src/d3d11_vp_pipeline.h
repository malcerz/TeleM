#pragma once

#include <d3d11.h>
#include <d3d11_1.h>
#include <d3d11_3.h>
#include <dxgi.h>
#include <vector>
#include <iostream>
#include <chrono>

struct VPPipelineStats {
    double p010_to_nv12_ms = 0.0;
    double hud_compose_ms = 0.0;
    double total_vp_ms = 0.0;
    double cpu_submit_ms = 0.0;
    double gpu_completion_ms = 0.0;
    double gpu_wait_ms = 0.0;
};

struct HUDDirtyRect {
    UINT x = 0;
    UINT y = 0;
    UINT width = 0;
    UINT height = 0;
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

private:
    static const UINT POOL_SIZE = 4;
    bool InitializeNV12ComputeCompositor();
    bool ComposeHUDDirectNV12(ID3D11Texture2D* outputTexture, UINT poolIndex);
    bool NormalizeD3D11VARangeNV12(UINT poolIndex);

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

    ID3D11Device3* m_device3 = nullptr;
    ID3D11ComputeShader* m_nv12HUDComputeShader = nullptr;
    ID3D11ComputeShader* m_nv12RangeComputeShader = nullptr;
    ID3D11UnorderedAccessView* m_outputYViews[POOL_SIZE] = { nullptr };
    ID3D11UnorderedAccessView* m_outputUVViews[POOL_SIZE] = { nullptr };

    ID3D11Texture2D* m_outputPool[POOL_SIZE] = { nullptr };
    ID3D11VideoProcessorOutputView* m_outputViewPool[POOL_SIZE] = { nullptr };
    UINT m_poolIndex = 0;
    UINT m_lastPoolIndex = 0;

    ID3D11Query* m_disjointQuery = nullptr;
    ID3D11Query* m_startQuery = nullptr;
    ID3D11Query* m_endQuery = nullptr;

    UINT m_width = 3840;
    UINT m_height = 2160;
    UINT m_hudWidth = 1920;
    UINT m_hudHeight = 1264;
};
