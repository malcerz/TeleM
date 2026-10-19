#include "d3d11_hud_bridge.h"

D3D11HUDBridge::D3D11HUDBridge() {}

D3D11HUDBridge::~D3D11HUDBridge() {
    if (m_hudTexture) {
        m_hudTexture->Release();
        m_hudTexture = nullptr;
    }
}

bool D3D11HUDBridge::Initialize(ID3D11Device* pDevice, ID3D11DeviceContext* pContext, UINT width, UINT height) {
    if (!pDevice || !pContext) return false;

    m_device = pDevice;
    m_context = pContext;
    m_width = width;
    m_height = height;

    if (m_hudTexture) {
        m_hudTexture->Release();
        m_hudTexture = nullptr;
    }

    // Allocate Persistent D3D11 RGBA Texture ONCE on shared ID3D11Device
    D3D11_TEXTURE2D_DESC desc = {};
    desc.Width = width;
    desc.Height = height;
    desc.MipLevels = 1;
    desc.ArraySize = 1;
    desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;

    HRESULT hr = m_device->CreateTexture2D(&desc, nullptr, &m_hudTexture);
    if (FAILED(hr)) {
        std::cerr << "[HUD BRIDGE] CreateTexture2D for persistent HUD failed: 0x" << std::hex << hr << std::dec << std::endl;
        return false;
    }

    std::cout << "[HUD BRIDGE] Persistent D3D11 RGBA Texture (" << width << "x" << height << ") initialized." << std::endl;
    return true;
}

bool D3D11HUDBridge::UploadHUDFrame(
    const uint8_t* pRGBAPixels,
    UINT width,
    UINT height,
    UINT stride,
    INT dirtyX, INT dirtyY, INT dirtyW, INT dirtyH,
    HUDUploadStats* outStats
) {
    if (!m_context || !m_hudTexture || !pRGBAPixels) return false;

    auto tStart = std::chrono::high_resolution_clock::now();

    D3D11_BOX box = {};
    const uint8_t* pSrcData = pRGBAPixels;
    size_t uploadedBytes = 0;
    bool isDirty = false;

    if (dirtyW > 0 && dirtyH > 0 && (dirtyX > 0 || dirtyY > 0 || (UINT)dirtyW < width || (UINT)dirtyH < height)) {
        box.left = (UINT)dirtyX;
        box.top = (UINT)dirtyY;
        box.front = 0;
        box.right = (UINT)(dirtyX + dirtyW);
        box.bottom = (UINT)(dirtyY + dirtyH);
        box.back = 1;

        pSrcData = pRGBAPixels + (dirtyY * stride + dirtyX * 4);
        uploadedBytes = (size_t)dirtyW * 4 * dirtyH;
        isDirty = true;
    } else {
        box.left = 0;
        box.top = 0;
        box.front = 0;
        box.right = width;
        box.bottom = height;
        box.back = 1;

        pSrcData = pRGBAPixels;
        uploadedBytes = (size_t)stride * height;
        isDirty = false;
    }

    m_context->UpdateSubresource(m_hudTexture, 0, &box, pSrcData, stride, 0);

    auto tEnd = std::chrono::high_resolution_clock::now();

    if (outStats) {
        outStats->upload_time_ms = std::chrono::duration<double, std::milli>(tEnd - tStart).count();
        outStats->bytes_uploaded = uploadedBytes;
        outStats->rects_uploaded = 1;
        outStats->is_dirty_update = isDirty;
    }

    return true;
}

bool D3D11HUDBridge::UploadHUDFrameMultiRects(
    const uint8_t* pRGBAPixels,
    UINT width,
    UINT height,
    UINT stride,
    const HUDRect* pRects,
    UINT rectCount,
    HUDUploadStats* outStats
) {
    if (!m_context || !m_hudTexture || !pRGBAPixels) return false;

    if (!pRects || rectCount == 0) {
        return UploadHUDFrame(pRGBAPixels, width, height, stride, 0, 0, width, height, outStats);
    }

    auto tStart = std::chrono::high_resolution_clock::now();

    size_t totalBytesUploaded = 0;

    for (UINT i = 0; i < rectCount; ++i) {
        const HUDRect& r = pRects[i];
        if (r.w <= 0 || r.h <= 0) continue;

        D3D11_BOX box = {};
        box.left = (UINT)r.x;
        box.top = (UINT)r.y;
        box.front = 0;
        box.right = (UINT)(r.x + r.w);
        box.bottom = (UINT)(r.y + r.h);
        box.back = 1;

        const uint8_t* pSrcData = pRGBAPixels + (r.y * stride + r.x * 4);
        m_context->UpdateSubresource(m_hudTexture, 0, &box, pSrcData, stride, 0);

        totalBytesUploaded += (size_t)r.w * 4 * r.h;
    }

    auto tEnd = std::chrono::high_resolution_clock::now();

    if (outStats) {
        outStats->upload_time_ms = std::chrono::duration<double, std::milli>(tEnd - tStart).count();
        outStats->bytes_uploaded = totalBytesUploaded;
        outStats->rects_uploaded = rectCount;
        outStats->is_dirty_update = true;
    }

    return true;
}
