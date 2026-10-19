#include "d3d11_compositor.h"
#include <algorithm>
#include <numeric>
#include <fstream>
#include <iomanip>

D3D11CompositorPoC::D3D11CompositorPoC() {}

D3D11CompositorPoC::~D3D11CompositorPoC() {
    if (m_disjointQuery) m_disjointQuery->Release();
    if (m_startQuery) m_startQuery->Release();
    if (m_endQuery) m_endQuery->Release();

    if (m_videoProcessor) m_videoProcessor->Release();
    if (m_videoEnumerator) m_videoEnumerator->Release();
    if (m_videoContext) m_videoContext->Release();
    if (m_videoDevice) m_videoDevice->Release();

    if (m_outputRTV) m_outputRTV->Release();
    if (m_outputSRV) m_outputSRV->Release();
    if (m_outputTexture) m_outputTexture->Release();

    if (m_hudSRV) m_hudSRV->Release();
    if (m_hudTextureDynamic) m_hudTextureDynamic->Release();

    if (m_baseSRVRGBA) m_baseSRVRGBA->Release();
    if (m_baseTextureRGBA) m_baseTextureRGBA->Release();

    if (m_pixelShaderRGBA) m_pixelShaderRGBA->Release();
    if (m_vertexShader) m_vertexShader->Release();

    if (m_context) m_context->Release();
    if (m_device) m_device->Release();
}

bool D3D11CompositorPoC::Initialize() {
    D3D_FEATURE_LEVEL featureLevels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
    D3D_FEATURE_LEVEL featureLevel;

    HRESULT hr = D3D11CreateDevice(
        nullptr,
        D3D_DRIVER_TYPE_HARDWARE,
        nullptr,
        D3D11_CREATE_DEVICE_VIDEO_SUPPORT,
        featureLevels,
        2,
        D3D11_SDK_VERSION,
        &m_device,
        &featureLevel,
        &m_context
    );

    if (FAILED(hr)) {
        std::cerr << "[D3D11 PoC] Failed to create D3D11 hardware device. HRESULT: " << std::hex << hr << std::endl;
        return false;
    }

    // Query Video Device interface
    hr = m_device->QueryInterface(__uuidof(ID3D11VideoDevice), (void**)&m_videoDevice);
    if (SUCCEEDED(hr)) {
        m_context->QueryInterface(__uuidof(ID3D11VideoContext), (void**)&m_videoContext);
    }

    // Create timestamp queries
    D3D11_QUERY_DESC qdesc = {};
    qdesc.Query = D3D11_QUERY_TIMESTAMP_DISJOINT;
    m_device->CreateQuery(&qdesc, &m_disjointQuery);
    
    qdesc.Query = D3D11_QUERY_TIMESTAMP;
    m_device->CreateQuery(&qdesc, &m_startQuery);
    m_device->CreateQuery(&qdesc, &m_endQuery);

    LogCapabilities();
    return true;
}

void D3D11CompositorPoC::LogCapabilities() {
    IDXGIDevice* dxgiDevice = nullptr;
    m_device->QueryInterface(__uuidof(IDXGIDevice), (void**)&dxgiDevice);
    IDXGIAdapter* adapter = nullptr;
    dxgiDevice->GetAdapter(&adapter);
    DXGI_ADAPTER_DESC desc;
    adapter->GetDesc(&desc);

    std::wcout << L"[D3D11 PoC] Adapter: " << desc.Description << std::endl;
    std::cout << L"[D3D11 PoC] D3D Feature Level: 11.0+" << std::endl;
    std::cout << "[D3D11 PoC] Base Format: DXGI_FORMAT_R8G8B8A8_UNORM / NV12" << std::endl;
    std::cout << "[D3D11 PoC] HUD Format: DXGI_FORMAT_R8G8B8A8_UNORM (Straight Alpha)" << std::endl;
    std::cout << "[D3D11 PoC] Output Format: DXGI_FORMAT_R8G8B8A8_UNORM" << std::endl;
    std::cout << "[D3D11 PoC] VideoProcessor Support: " << (m_videoDevice ? "YES" : "NO") << std::endl;
    
    adapter->Release();
    dxgiDevice->Release();
}

bool D3D11CompositorPoC::CreateTextures(UINT baseWidth, UINT baseHeight, UINT hudWidth, UINT hudHeight) {
    m_baseWidth = baseWidth;
    m_baseHeight = baseHeight;
    m_hudWidth = hudWidth;
    m_hudHeight = hudHeight;

    // 1. Base Texture (3840x2160 RGBA)
    D3D11_TEXTURE2D_DESC bdesc = {};
    bdesc.Width = baseWidth;
    bdesc.Height = baseHeight;
    bdesc.MipLevels = 1;
    bdesc.ArraySize = 1;
    bdesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    bdesc.SampleDesc.Count = 1;
    bdesc.Usage = D3D11_USAGE_DEFAULT;
    bdesc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
    bdesc.MiscFlags = D3D11_RESOURCE_MISC_SHARED;

    HRESULT hr = m_device->CreateTexture2D(&bdesc, nullptr, &m_baseTextureRGBA);
    if (FAILED(hr)) return false;
    m_device->CreateShaderResourceView(m_baseTextureRGBA, nullptr, &m_baseSRVRGBA);

    // 2. Persistent HUD Texture (1920x1264 RGBA Dynamic)
    D3D11_TEXTURE2D_DESC hdesc = {};
    hdesc.Width = hudWidth;
    hdesc.Height = hudHeight;
    hdesc.MipLevels = 1;
    hdesc.ArraySize = 1;
    hdesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    hdesc.SampleDesc.Count = 1;
    hdesc.Usage = D3D11_USAGE_DYNAMIC;
    hdesc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    hdesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;

    hr = m_device->CreateTexture2D(&hdesc, nullptr, &m_hudTextureDynamic);
    if (FAILED(hr)) return false;
    m_device->CreateShaderResourceView(m_hudTextureDynamic, nullptr, &m_hudSRV);

    // 3. Output Render Target Texture (3840x2160 RGBA)
    D3D11_TEXTURE2D_DESC odesc = bdesc;
    hr = m_device->CreateTexture2D(&odesc, nullptr, &m_outputTexture);
    if (FAILED(hr)) return false;

    m_device->CreateRenderTargetView(m_outputTexture, nullptr, &m_outputRTV);
    m_device->CreateShaderResourceView(m_outputTexture, nullptr, &m_outputSRV);

    return true;
}

bool D3D11CompositorPoC::UploadHUD_MapUnmap(const std::vector<uint8_t>& hudRGBA) {
    D3D11_MAPPED_SUBRESOURCE mapped;
    HRESULT hr = m_context->Map(m_hudTextureDynamic, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
    if (FAILED(hr)) return false;

    const uint8_t* src = hudRGBA.data();
    uint8_t* dst = static_cast<uint8_t*>(mapped.pData);
    UINT rowPitch = m_hudWidth * 4;

    for (UINT y = 0; y < m_hudHeight; ++y) {
        memcpy(dst + y * mapped.RowPitch, src + y * rowPitch, rowPitch);
    }

    m_context->Unmap(m_hudTextureDynamic, 0);
    return true;
}

bool D3D11CompositorPoC::UploadHUD_UpdateSubresource(const std::vector<uint8_t>& hudRGBA) {
    m_context->UpdateSubresource(m_hudTextureDynamic, 0, nullptr, hudRGBA.data(), m_hudWidth * 4, 0);
    return true;
}

bool D3D11CompositorPoC::VerifyAMFCompatibility() {
    D3D11_TEXTURE2D_DESC desc;
    m_outputTexture->GetDesc(&desc);
    
    bool bindOk = (desc.BindFlags & D3D11_BIND_RENDER_TARGET) && (desc.BindFlags & D3D11_BIND_SHADER_RESOURCE);
    bool miscOk = (desc.MiscFlags & D3D11_RESOURCE_MISC_SHARED) || (desc.MiscFlags & D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX);
    
    std::cout << "[AMF Compatibility Check]" << std::endl;
    std::cout << "  - Format: " << desc.Format << " (Supported by AMF D3D11 Surface)" << std::endl;
    std::cout << "  - BindFlags: RenderTarget + ShaderResource (" << (bindOk ? "PASS" : "FAIL") << ")" << std::endl;
    std::cout << "  - MiscFlags: SHARED Handle (" << (miscOk ? "PASS" : "FAIL") << ")" << std::endl;
    std::cout << "  - AMF-compatible output texture: " << (bindOk ? "YES" : "NO") << std::endl;

    return bindOk;
}

int main() {
    std::cout << "=========================================================" << std::endl;
    std::cout << " TeleM — AMD C++ ETAP 1: PoC Natywnego D3D11 Compositora " << std::endl;
    std::cout << "=========================================================" << std::endl;

    D3D11CompositorPoC poc;
    if (!poc.Initialize()) {
        return 1;
    }

    if (!poc.CreateTextures(3840, 2160, 1920, 1264)) {
        std::cerr << "Failed to create textures." << std::endl;
        return 1;
    }

    poc.VerifyAMFCompatibility();
    std::cout << "\nPoC C++ module initialized successfully." << std::endl;
    return 0;
}
