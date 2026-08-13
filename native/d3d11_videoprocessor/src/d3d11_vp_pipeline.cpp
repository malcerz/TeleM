#include "d3d11_vp_pipeline.h"
#include <algorithm>
#include <numeric>

D3D11VideoProcessorPipeline::D3D11VideoProcessorPipeline() {}

D3D11VideoProcessorPipeline::~D3D11VideoProcessorPipeline() {
    if (m_hudInputView) m_hudInputView->Release();
    if (m_hudTexture) m_hudTexture->Release();

    for (auto* view : m_outputViews) {
        if (view) view->Release();
    }
    for (auto* tex : m_outputPool) {
        if (tex) tex->Release();
    }

    if (m_videoProcessor) m_videoProcessor->Release();
    if (m_videoEnumerator) m_videoEnumerator->Release();
    if (m_videoContext) m_videoContext->Release();
    if (m_videoDevice) m_videoDevice->Release();

    if (m_context) m_context->Release();
    if (m_device) m_device->Release();
}

bool D3D11VideoProcessorPipeline::Initialize(UINT width, UINT height) {
    m_width = width;
    m_height = height;

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

    if (FAILED(hr)) return false;

    hr = m_device->QueryInterface(__uuidof(ID3D11VideoDevice), (void**)&m_videoDevice);
    if (FAILED(hr)) return false;

    m_context->QueryInterface(__uuidof(ID3D11VideoContext), (void**)&m_videoContext);
    
    LogCapabilities();
    return true;
}

void D3D11VideoProcessorPipeline::LogCapabilities() {
    std::cout << "[D3D11 VP Pipeline] ID3D11VideoDevice initialized." << std::endl;
    std::cout << "[D3D11 VP Pipeline] Input Format: DXGI_FORMAT_P010 (10-bit YUV)" << std::endl;
    std::cout << "[D3D11 VP Pipeline] HUD Format:   DXGI_FORMAT_R8G8B8A8_UNORM / B8G8R8A8_UNORM (Straight Alpha)" << std::endl;
    std::cout << "[D3D11 VP Pipeline] Output Format: DXGI_FORMAT_NV12 (8-bit YUV)" << std::endl;
}

bool D3D11VideoProcessorPipeline::SetupVideoProcessor(DXGI_FORMAT inputFormat, DXGI_FORMAT outputFormat) {
    D3D11_VIDEO_PROCESSOR_CONTENT_DESC contentDesc = {};
    contentDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    contentDesc.InputWidth = m_width;
    contentDesc.InputHeight = m_height;
    contentDesc.OutputWidth = m_width;
    contentDesc.OutputHeight = m_height;
    contentDesc.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

    HRESULT hr = m_videoDevice->CreateVideoProcessorEnumerator(&contentDesc, &m_videoEnumerator);
    if (FAILED(hr)) return false;

    hr = m_videoDevice->CreateVideoProcessor(m_videoEnumerator, 0, &m_videoProcessor);
    if (FAILED(hr)) return false;

    // Create 3 persistent NV12 output textures in pool
    m_outputPool.resize(3);
    m_outputViews.resize(3);

    D3D11_TEXTURE2D_DESC odesc = {};
    odesc.Width = m_width;
    odesc.Height = m_height;
    odesc.MipLevels = 1;
    odesc.ArraySize = 1;
    odesc.Format = outputFormat;
    odesc.SampleDesc.Count = 1;
    odesc.Usage = D3D11_USAGE_DEFAULT;
    odesc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    odesc.MiscFlags = D3D11_RESOURCE_MISC_SHARED;

    for (size_t i = 0; i < 3; ++i) {
        hr = m_device->CreateTexture2D(&odesc, nullptr, &m_outputPool[i]);
        if (FAILED(hr)) return false;

        D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC ovDesc = {};
        ovDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
        ovDesc.Texture2D.MipSlice = 0;

        hr = m_videoDevice->CreateVideoProcessorOutputView(m_outputPool[i], m_videoEnumerator, &ovDesc, &m_outputViews[i]);
        if (FAILED(hr)) return false;
    }

    return true;
}

bool D3D11VideoProcessorPipeline::CreateHUDTexture(UINT hudWidth, UINT hudHeight) {
    m_hudWidth = hudWidth;
    m_hudHeight = hudHeight;

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

    HRESULT hr = m_device->CreateTexture2D(&hdesc, nullptr, &m_hudTexture);
    if (FAILED(hr)) return false;

    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC ivDesc = {};
    ivDesc.FourCC = 0;
    ivDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    ivDesc.Texture2D.MipSlice = 0;
    ivDesc.Texture2D.ArraySlice = 0;

    hr = m_videoDevice->CreateVideoProcessorInputView(m_hudTexture, m_videoEnumerator, &ivDesc, &m_hudInputView);
    return SUCCEEDED(hr);
}

int main() {
    std::cout << "=================================================================" << std::endl;
    std::cout << " TeleM — AMD C++ ETAP 2B: Real P010 Surface → VideoProcessor NV12 " << std::endl;
    std::cout << "=================================================================" << std::endl;

    D3D11VideoProcessorPipeline pipeline;
    if (!pipeline.Initialize(3840, 2160)) {
        std::cerr << "[ERROR] Pipeline initialization failed!" << std::endl;
        return 1;
    }

    if (!pipeline.SetupVideoProcessor(DXGI_FORMAT_P010, DXGI_FORMAT_NV12)) {
        std::cerr << "[ERROR] VideoProcessor setup failed!" << std::endl;
        return 1;
    }

    if (!pipeline.CreateHUDTexture(1920, 1264)) {
        std::cerr << "[ERROR] HUD Texture creation failed!" << std::endl;
        return 1;
    }

    std::cout << "\n[PASS] ETAP 2B VideoProcessor Pipeline Initialized Successfully." << std::endl;
    return 0;
}
