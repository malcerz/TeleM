#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <dxgi1_2.h>
#include <iostream>
#include <vector>
#include <iomanip>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")

int main() {
    std::cout << "=== D3D11 VideoProcessor Multi-Stream Deep Blt Diagnostics ===" << std::endl;

    ID3D11Device* dev = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    D3D_FEATURE_LEVEL fl;
    UINT flags = D3D11_CREATE_DEVICE_VIDEO_SUPPORT;
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                   flags, nullptr, 0, D3D11_SDK_VERSION, &dev, &fl, &ctx);
    if (FAILED(hr)) {
        std::cerr << "D3D11CreateDevice failed: 0x" << std::hex << hr << std::endl;
        return 1;
    }
    std::cout << "D3D11CreateDevice: S_OK" << std::endl;

    ID3D11VideoDevice* videoDev = nullptr;
    dev->QueryInterface(__uuidof(ID3D11VideoDevice), (void**)&videoDev);
    ID3D11VideoContext* videoCtx = nullptr;
    ctx->QueryInterface(__uuidof(ID3D11VideoContext), (void**)&videoCtx);
    ID3D11VideoContext1* videoCtx1 = nullptr;
    ctx->QueryInterface(__uuidof(ID3D11VideoContext1), (void**)&videoCtx1);

    D3D11_VIDEO_PROCESSOR_CONTENT_DESC contentDesc = {};
    contentDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    contentDesc.InputWidth = 3840;
    contentDesc.InputHeight = 2160;
    contentDesc.OutputWidth = 3840;
    contentDesc.OutputHeight = 2160;
    contentDesc.Usage = D3D11_VIDEO_USAGE_OPTIMAL_QUALITY;

    ID3D11VideoProcessorEnumerator* enumerator = nullptr;
    videoDev->CreateVideoProcessorEnumerator(&contentDesc, &enumerator);

    ID3D11VideoProcessor* vp = nullptr;
    videoDev->CreateVideoProcessor(enumerator, 0, &vp);

    // Create 4K Textures
    D3D11_TEXTURE2D_DESC td = {};
    td.Width = 3840; td.Height = 2160; td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_NV12;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* vidTex = nullptr;
    hr = dev->CreateTexture2D(&td, nullptr, &vidTex);
    std::cout << "CreateTexture2D vidTex (NV12): " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << std::endl;

    td.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* hudTex = nullptr;
    hr = dev->CreateTexture2D(&td, nullptr, &hudTex);
    std::cout << "CreateTexture2D hudTex (BGRA): " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << std::endl;

    td.Format = DXGI_FORMAT_NV12;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* outTex = nullptr;
    hr = dev->CreateTexture2D(&td, nullptr, &outTex);
    std::cout << "CreateTexture2D outTex (NV12): " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << std::endl;

    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inViewDesc = {};
    inViewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    inViewDesc.Texture2D.MipSlice = 0;
    inViewDesc.Texture2D.ArraySlice = 0;
    ID3D11VideoProcessorInputView* vidView = nullptr;
    hr = videoDev->CreateVideoProcessorInputView(vidTex, enumerator, &inViewDesc, &vidView);
    std::cout << "CreateVideoProcessorInputView vidView: " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << std::endl;

    ID3D11VideoProcessorInputView* hudView = nullptr;
    hr = videoDev->CreateVideoProcessorInputView(hudTex, enumerator, &inViewDesc, &hudView);
    std::cout << "CreateVideoProcessorInputView hudView: " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << std::endl;

    D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC outViewDesc = {};
    outViewDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
    outViewDesc.Texture2D.MipSlice = 0;
    ID3D11VideoProcessorOutputView* outView = nullptr;
    hr = videoDev->CreateVideoProcessorOutputView(outTex, enumerator, &outViewDesc, &outView);
    std::cout << "CreateVideoProcessorOutputView outView: " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << std::endl;

    RECT rFull = { 0, 0, 3840, 2160 };

    // Test 1: Single Stream 0 (Video NV12 -> Output NV12)
    {
        videoCtx->VideoProcessorSetStreamFrameFormat(vp, 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
        videoCtx->VideoProcessorSetStreamSourceRect(vp, 0, TRUE, &rFull);
        videoCtx->VideoProcessorSetStreamDestRect(vp, 0, TRUE, &rFull);
        videoCtx->VideoProcessorSetOutputTargetRect(vp, TRUE, &rFull);

        D3D11_VIDEO_PROCESSOR_STREAM s[1] = {};
        s[0].Enable = TRUE;
        s[0].pInputSurface = vidView;
        hr = videoCtx->VideoProcessorBlt(vp, outView, 0, 1, s);
        std::cout << "Test 1 [Stream 0 Alone (NV12 -> NV12)]:          " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << " (hr=0x" << std::hex << hr << std::dec << ")\n";
    }

    // Test 2: Single Stream 0 (HUD BGRA -> Output NV12)
    {
        videoCtx->VideoProcessorSetStreamFrameFormat(vp, 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
        videoCtx->VideoProcessorSetStreamSourceRect(vp, 0, TRUE, &rFull);
        videoCtx->VideoProcessorSetStreamDestRect(vp, 0, TRUE, &rFull);
        videoCtx->VideoProcessorSetOutputTargetRect(vp, TRUE, &rFull);

        D3D11_VIDEO_PROCESSOR_STREAM s[1] = {};
        s[0].Enable = TRUE;
        s[0].pInputSurface = hudView;
        hr = videoCtx->VideoProcessorBlt(vp, outView, 0, 1, s);
        std::cout << "Test 2 [Stream 0 Alone (BGRA -> NV12)]:          " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << " (hr=0x" << std::hex << hr << std::dec << ")\n";
    }

    // Test 3: Two Streams (Stream 0 NV12 + Stream 1 BGRA -> Output NV12) without Alpha
    {
        videoCtx->VideoProcessorSetStreamFrameFormat(vp, 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
        videoCtx->VideoProcessorSetStreamSourceRect(vp, 0, TRUE, &rFull);
        videoCtx->VideoProcessorSetStreamDestRect(vp, 0, TRUE, &rFull);

        videoCtx->VideoProcessorSetStreamFrameFormat(vp, 1, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
        videoCtx->VideoProcessorSetStreamSourceRect(vp, 1, TRUE, &rFull);
        videoCtx->VideoProcessorSetStreamDestRect(vp, 1, TRUE, &rFull);

        videoCtx->VideoProcessorSetOutputTargetRect(vp, TRUE, &rFull);

        D3D11_VIDEO_PROCESSOR_STREAM s[2] = {};
        s[0].Enable = TRUE;
        s[0].pInputSurface = vidView;
        s[1].Enable = TRUE;
        s[1].pInputSurface = hudView;
        hr = videoCtx->VideoProcessorBlt(vp, outView, 0, 2, s);
        std::cout << "Test 3 [2 Streams (NV12 + BGRA, no alpha)]:      " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << " (hr=0x" << std::hex << hr << std::dec << ")\n";
    }

    // Test 4: Two Streams with Stream 1 Planar Alpha / Stream Alpha
    {
        videoCtx->VideoProcessorSetStreamAlpha(vp, 1, TRUE, 0.5f);
        D3D11_VIDEO_PROCESSOR_STREAM s[2] = {};
        s[0].Enable = TRUE;
        s[0].pInputSurface = vidView;
        s[1].Enable = TRUE;
        s[1].pInputSurface = hudView;
        hr = videoCtx->VideoProcessorBlt(vp, outView, 0, 2, s);
        std::cout << "Test 4 [2 Streams with StreamAlpha(0.5)]:        " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << " (hr=0x" << std::hex << hr << std::dec << ")\n";
    }

    // Test 5: Two Streams with ColorSpace1 if VideoContext1 available
    if (videoCtx1) {
        videoCtx1->VideoProcessorSetStreamColorSpace1(vp, 0, DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709);
        videoCtx1->VideoProcessorSetStreamColorSpace1(vp, 1, DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709);
        videoCtx1->VideoProcessorSetOutputColorSpace1(vp, DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709);

        D3D11_VIDEO_PROCESSOR_STREAM s[2] = {};
        s[0].Enable = TRUE;
        s[0].pInputSurface = vidView;
        s[1].Enable = TRUE;
        s[1].pInputSurface = hudView;
        hr = videoCtx->VideoProcessorBlt(vp, outView, 0, 2, s);
        std::cout << "Test 5 [2 Streams with explicit ColorSpace1]:    " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << " (hr=0x" << std::hex << hr << std::dec << ")\n";
    }

    // Test 6: Two Streams with NV12 + NV12 (Video + Video)
    {
        D3D11_VIDEO_PROCESSOR_STREAM s[2] = {};
        s[0].Enable = TRUE;
        s[0].pInputSurface = vidView;
        s[1].Enable = TRUE;
        s[1].pInputSurface = vidView;
        hr = videoCtx->VideoProcessorBlt(vp, outView, 0, 2, s);
        std::cout << "Test 6 [2 Streams (NV12 + NV12)]:                " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << " (hr=0x" << std::hex << hr << std::dec << ")\n";
    }

    // Cleanup
    if (vidView) vidView->Release();
    if (hudView) hudView->Release();
    if (outView) outView->Release();
    if (vidTex) vidTex->Release();
    if (hudTex) hudTex->Release();
    if (outTex) outTex->Release();
    if (vp) vp->Release();
    if (enumerator) enumerator->Release();
    if (videoCtx1) videoCtx1->Release();
    if (videoCtx) videoCtx->Release();
    if (videoDev) videoDev->Release();
    ctx->Release();
    dev->Release();

    return 0;
}
