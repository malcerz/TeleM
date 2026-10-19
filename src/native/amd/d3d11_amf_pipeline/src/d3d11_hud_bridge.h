#pragma once

#include <d3d11.h>
#include <vector>
#include <iostream>
#include <chrono>

struct HUDRect {
    INT x = 0;
    INT y = 0;
    INT w = 0;
    INT h = 0;
};

struct HUDUploadStats {
    double upload_time_ms = 0.0;
    size_t bytes_uploaded = 0;
    UINT rects_uploaded = 0;
    bool is_dirty_update = false;
};

class D3D11HUDBridge {
public:
    D3D11HUDBridge();
    ~D3D11HUDBridge();

    bool Initialize(ID3D11Device* pDevice, ID3D11DeviceContext* pContext, UINT width, UINT height);

    // Single Dirty BBox / Full Atlas Upload
    bool UploadHUDFrame(
        const uint8_t* pRGBAPixels,
        UINT width,
        UINT height,
        UINT stride,
        INT dirtyX, INT dirtyY, INT dirtyW, INT dirtyH,
        HUDUploadStats* outStats = nullptr
    );

    // Multi-Dirty Rects Upload (Coalesced Rectangles)
    bool UploadHUDFrameMultiRects(
        const uint8_t* pRGBAPixels,
        UINT width,
        UINT height,
        UINT stride,
        const HUDRect* pRects,
        UINT rectCount,
        HUDUploadStats* outStats = nullptr
    );

    ID3D11Texture2D* GetHUDTexture() const { return m_hudTexture; }

private:
    ID3D11Device* m_device = nullptr;
    ID3D11DeviceContext* m_context = nullptr;

    ID3D11Texture2D* m_hudTexture = nullptr;

    UINT m_width = 1920;
    UINT m_height = 1264;
};
