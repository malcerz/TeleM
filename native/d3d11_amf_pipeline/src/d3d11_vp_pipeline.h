#pragma once

#include <d3d11.h>
#include <d3d11_1.h>
#include <dxgi.h>
#include <vector>
#include <iostream>
#include <chrono>

struct VPPipelineStats {
    double p010_to_nv12_ms = 0.0;
    double hud_compose_ms = 0.0;
    double total_vp_ms = 0.0;
};

class D3D11VideoProcessorPipeline {
public:
    D3D11VideoProcessorPipeline();
    ~D3D11VideoProcessorPipeline();

    bool Initialize(ID3D11Device* pDevice, ID3D11DeviceContext* pContext, UINT width, UINT height);
    bool SetupVideoProcessor(DXGI_FORMAT inputFormat, DXGI_FORMAT outputFormat);

    bool CreateHUDTexture(UINT width, UINT height, const std::vector<uint8_t>& rgbaData);

    bool ProcessFrame(
        ID3D11Texture2D* pP010Texture,
        UINT arrayIndex,
        ID3D11Texture2D** ppOutNV12Texture,
        bool enableHUD,
        VPPipelineStats* outStats = nullptr,
        UINT frameIndex = 0
    );

    ID3D11Texture2D* GetHUDTexture() const { return m_hudTexture; }
    ID3D11Device* GetDevice() const { return m_device; }
    ID3D11DeviceContext* GetContext() const { return m_context; }

private:
    ID3D11Device* m_device = nullptr;
    ID3D11DeviceContext* m_context = nullptr;
    bool m_ownsDevice = false;

    ID3D11VideoDevice* m_videoDevice = nullptr;
    ID3D11VideoContext* m_videoContext = nullptr;
    ID3D11VideoProcessorEnumerator* m_videoEnumerator = nullptr;
    ID3D11VideoProcessor* m_videoProcessor = nullptr;

    ID3D11Texture2D* m_hudTexture = nullptr;
    ID3D11VideoProcessorInputView* m_hudInputView = nullptr;

    static const UINT POOL_SIZE = 4;
    ID3D11Texture2D* m_outputPool[POOL_SIZE] = { nullptr };
    ID3D11VideoProcessorOutputView* m_outputViewPool[POOL_SIZE] = { nullptr };
    UINT m_poolIndex = 0;

    ID3D11Query* m_disjointQuery = nullptr;
    ID3D11Query* m_startQuery = nullptr;
    ID3D11Query* m_endQuery = nullptr;

    UINT m_width = 3840;
    UINT m_height = 2160;
    UINT m_hudWidth = 1920;
    UINT m_hudHeight = 1264;
};
