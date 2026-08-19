#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <dxgi1_2.h>
#include <iostream>
#include <vector>
#include <iomanip>
#include <cmath>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")

static const char* FormatName(DXGI_FORMAT fmt) {
    switch (fmt) {
        case DXGI_FORMAT_NV12: return "DXGI_FORMAT_NV12";
        case DXGI_FORMAT_P010: return "DXGI_FORMAT_P010";
        case DXGI_FORMAT_R8G8B8A8_UNORM: return "DXGI_FORMAT_R8G8B8A8_UNORM";
        case DXGI_FORMAT_B8G8R8A8_UNORM: return "DXGI_FORMAT_B8G8R8A8_UNORM";
        case DXGI_FORMAT_R16G16B16A16_FLOAT: return "DXGI_FORMAT_R16G16B16A16_FLOAT";
        case DXGI_FORMAT_AYUV: return "DXGI_FORMAT_AYUV";
        case DXGI_FORMAT_YUY2: return "DXGI_FORMAT_YUY2";
        default: return "OTHER";
    }
}

int main() {
    std::cout << "===============================================================================\n";
    std::cout << "ETAP 8V-PROBE: D3D11 VideoProcessor Multi-Stream & Format Capability Probe\n";
    std::cout << "===============================================================================\n";

    // 1. Create D3D11 Device with Video Support
    ID3D11Device* dev = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    D3D_FEATURE_LEVEL fl;
    UINT flags = D3D11_CREATE_DEVICE_VIDEO_SUPPORT;
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                   flags, nullptr, 0, D3D11_SDK_VERSION, &dev, &fl, &ctx);
    if (FAILED(hr)) {
        std::cerr << "Failed D3D11CreateDevice with VIDEO_SUPPORT: 0x" << std::hex << hr << std::endl;
        return 1;
    }

    // 2. Query ID3D11VideoDevice and ID3D11VideoContext
    ID3D11VideoDevice* videoDev = nullptr;
    hr = dev->QueryInterface(__uuidof(ID3D11VideoDevice), (void**)&videoDev);
    if (FAILED(hr) || !videoDev) {
        std::cerr << "Failed QueryInterface ID3D11VideoDevice: 0x" << std::hex << hr << std::endl;
        return 1;
    }

    ID3D11VideoContext* videoCtx = nullptr;
    hr = ctx->QueryInterface(__uuidof(ID3D11VideoContext), (void**)&videoCtx);
    if (FAILED(hr) || !videoCtx) {
        std::cerr << "Failed QueryInterface ID3D11VideoContext: 0x" << std::hex << hr << std::endl;
        return 1;
    }

    ID3D11VideoContext1* videoCtx1 = nullptr;
    ctx->QueryInterface(__uuidof(ID3D11VideoContext1), (void**)&videoCtx1);

    // 3. Create Video Processor Enumerator
    D3D11_VIDEO_PROCESSOR_CONTENT_DESC contentDesc = {};
    contentDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    contentDesc.InputWidth = 3840;
    contentDesc.InputHeight = 2160;
    contentDesc.OutputWidth = 3840;
    contentDesc.OutputHeight = 2160;
    contentDesc.Usage = D3D11_VIDEO_USAGE_OPTIMAL_QUALITY;

    ID3D11VideoProcessorEnumerator* enumerator = nullptr;
    hr = videoDev->CreateVideoProcessorEnumerator(&contentDesc, &enumerator);
    if (FAILED(hr) || !enumerator) {
        std::cerr << "Failed CreateVideoProcessorEnumerator: 0x" << std::hex << hr << std::endl;
        return 1;
    }

    ID3D11VideoProcessorEnumerator1* enumerator1 = nullptr;
    enumerator->QueryInterface(__uuidof(ID3D11VideoProcessorEnumerator1), (void**)&enumerator1);

    // 4. Inspect GetVideoProcessorCaps
    D3D11_VIDEO_PROCESSOR_CAPS caps = {};
    hr = enumerator->GetVideoProcessorCaps(&caps);
    if (FAILED(hr)) {
        std::cerr << "Failed GetVideoProcessorCaps: 0x" << std::hex << hr << std::endl;
        return 1;
    }

    std::cout << "\n[1. VIDEO PROCESSOR CAPS]\n";
    std::cout << "  DeviceCaps:            0x" << std::hex << caps.DeviceCaps << std::dec << "\n";
    std::cout << "  FeatureCaps:           0x" << std::hex << caps.FeatureCaps << std::dec << "\n";
    std::cout << "    - ALPHA_FILL:        " << ((caps.FeatureCaps & D3D11_VIDEO_PROCESSOR_FEATURE_CAPS_ALPHA_FILL) ? "YES" : "NO") << "\n";
    std::cout << "    - CONST_METADATA:    " << ((caps.FeatureCaps & D3D11_VIDEO_PROCESSOR_FEATURE_CAPS_METADATA_HDR10) ? "YES" : "NO") << "\n";
    std::cout << "    - ALPHA_PALETTE:     " << ((caps.FeatureCaps & D3D11_VIDEO_PROCESSOR_FEATURE_CAPS_ALPHA_PALETTE) ? "YES" : "NO") << "\n";
    std::cout << "    - LEGACY:            " << ((caps.FeatureCaps & D3D11_VIDEO_PROCESSOR_FEATURE_CAPS_LEGACY) ? "YES" : "NO") << "\n";
    std::cout << "  InputFormatCaps:       0x" << std::hex << caps.InputFormatCaps << std::dec << "\n";
    std::cout << "    - RGB_INTERLACED:    " << ((caps.InputFormatCaps & D3D11_VIDEO_PROCESSOR_FORMAT_CAPS_RGB_INTERLACED) ? "YES" : "NO") << "\n";
    std::cout << "    - RGB_PROCAMP:       " << ((caps.InputFormatCaps & D3D11_VIDEO_PROCESSOR_FORMAT_CAPS_RGB_PROCAMP) ? "YES" : "NO") << "\n";
    std::cout << "    - RGB_LUMA_KEY:      " << ((caps.InputFormatCaps & D3D11_VIDEO_PROCESSOR_FORMAT_CAPS_RGB_LUMA_KEY) ? "YES" : "NO") << "\n";
    std::cout << "    - PALETTE_INTERLACED:" << ((caps.InputFormatCaps & D3D11_VIDEO_PROCESSOR_FORMAT_CAPS_PALETTE_INTERLACED) ? "YES" : "NO") << "\n";
    std::cout << "  AutoStreamCaps:        0x" << std::hex << caps.AutoStreamCaps << std::dec << "\n";
    std::cout << "  StereoCaps:            0x" << std::hex << caps.StereoCaps << std::dec << "\n";
    std::cout << "  MaxInputStreams:       " << caps.MaxInputStreams << "\n";
    std::cout << "  MaxStreamStates:       " << caps.MaxStreamStates << "\n";

    // 5. Inspect CheckVideoProcessorFormat for required formats
    std::cout << "\n[2. FORMAT SUPPORT (CheckVideoProcessorFormat)]\n";
    DXGI_FORMAT testFormats[] = {
        DXGI_FORMAT_P010,
        DXGI_FORMAT_NV12,
        DXGI_FORMAT_R8G8B8A8_UNORM,
        DXGI_FORMAT_B8G8R8A8_UNORM,
        DXGI_FORMAT_AYUV,
        DXGI_FORMAT_YUY2,
        DXGI_FORMAT_R16G16B16A16_FLOAT
    };

    bool p010In = false, nv12In = false, nv12Out = false, rgbaIn = false, bgraIn = false;

    for (DXGI_FORMAT f : testFormats) {
        UINT supportFlags = 0;
        hr = enumerator->CheckVideoProcessorFormat(f, &supportFlags);
        bool inSupport = (supportFlags & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT) != 0;
        bool outSupport = (supportFlags & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_OUTPUT) != 0;
        std::cout << "  " << std::left << std::setw(30) << FormatName(f)
                  << " : INPUT=" << (inSupport ? "YES" : "NO ")
                  << " | OUTPUT=" << (outSupport ? "YES" : "NO ")
                  << " (raw=0x" << std::hex << supportFlags << std::dec << ")\n";

        if (f == DXGI_FORMAT_P010 && inSupport) p010In = true;
        if (f == DXGI_FORMAT_NV12 && inSupport) nv12In = true;
        if (f == DXGI_FORMAT_NV12 && outSupport) nv12Out = true;
        if (f == DXGI_FORMAT_R8G8B8A8_UNORM && inSupport) rgbaIn = true;
        if (f == DXGI_FORMAT_B8G8R8A8_UNORM && inSupport) bgraIn = true;
    }

    // 6. Check Format Conversions (ID3D11VideoProcessorEnumerator1)
    std::cout << "\n[3. FORMAT CONVERSIONS (CheckVideoProcessorFormatConversion)]\n";
    bool convP010ToNV12 = false;
    bool convRGBAToNV12 = false;
    bool convBGRAToNV12 = false;

    if (enumerator1) {
        BOOL sup = FALSE;
        // P010 (Rec.709 Studio) -> NV12 (Rec.709 Studio)
        hr = enumerator1->CheckVideoProcessorFormatConversion(
            DXGI_FORMAT_P010, DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709,
            DXGI_FORMAT_NV12, DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709, &sup);
        convP010ToNV12 = (SUCCEEDED(hr) && sup);
        std::cout << "  P010 (Rec.709) -> NV12 (Rec.709) Conversion:          " << (convP010ToNV12 ? "YES" : "NO") << "\n";

        // RGBA (sRGB Full) -> NV12 (Rec.709 Studio)
        sup = FALSE;
        hr = enumerator1->CheckVideoProcessorFormatConversion(
            DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709,
            DXGI_FORMAT_NV12, DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709, &sup);
        convRGBAToNV12 = (SUCCEEDED(hr) && sup);
        std::cout << "  R8G8B8A8_UNORM (sRGB) -> NV12 (Rec.709) Conversion:  " << (convRGBAToNV12 ? "YES" : "NO") << "\n";

        // BGRA (sRGB Full) -> NV12 (Rec.709 Studio)
        sup = FALSE;
        hr = enumerator1->CheckVideoProcessorFormatConversion(
            DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709,
            DXGI_FORMAT_NV12, DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709, &sup);
        convBGRAToNV12 = (SUCCEEDED(hr) && sup);
        std::cout << "  B8G8R8A8_UNORM (sRGB) -> NV12 (Rec.709) Conversion:  " << (convBGRAToNV12 ? "YES" : "NO") << "\n";
    } else {
        std::cout << "  ID3D11VideoProcessorEnumerator1 NOT AVAILABLE on driver\n";
    }

    // 7. Check if VideoProcessor can be created
    ID3D11VideoProcessor* vp = nullptr;
    hr = videoDev->CreateVideoProcessor(enumerator, 0, &vp);
    if (FAILED(hr) || !vp) {
        std::cerr << "Failed CreateVideoProcessor: 0x" << std::hex << hr << std::endl;
        return 1;
    }

    std::cout << "\n[4. 2-STREAM CAPABILITY EVALUATION]\n";
    bool multiStreamPossible = (caps.MaxInputStreams >= 2) && (rgbaIn || bgraIn) && nv12Out;
    std::cout << "  MaxInputStreams >= 2:    " << (caps.MaxInputStreams >= 2 ? "YES" : "NO") << " (" << caps.MaxInputStreams << ")\n";
    std::cout << "  RGBA/BGRA Input Support: " << ((rgbaIn || bgraIn) ? "YES" : "NO") << "\n";
    std::cout << "  NV12 Output Support:     " << (nv12Out ? "YES" : "NO") << "\n";
    std::cout << "  MultiStream Possible:    " << (multiStreamPossible ? "YES" : "NO") << "\n";

    // 8. If multi-stream is supported on hardware, run 1-frame prototype
    if (multiStreamPossible) {
        std::cout << "\n[5. 1-FRAME 2-STREAM VIDEOPROCESSOR PROTOTYPE RUN]\n";

        // Create Stream 0: Video texture (P010 or NV12) 3840x2160
        D3D11_TEXTURE2D_DESC td = {};
        td.Width = 3840; td.Height = 2160; td.MipLevels = 1; td.ArraySize = 1;
        td.Format = DXGI_FORMAT_NV12;
        td.SampleDesc.Count = 1;
        td.Usage = D3D11_USAGE_DEFAULT;
        td.BindFlags = D3D11_BIND_DECODER | D3D11_BIND_SHADER_RESOURCE;
        ID3D11Texture2D* vidTex = nullptr;
        dev->CreateTexture2D(&td, nullptr, &vidTex);

        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inViewDesc = {};
        inViewDesc.FourCC = 0;
        inViewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
        inViewDesc.Texture2D.MipSlice = 0;
        inViewDesc.Texture2D.ArraySlice = 0;
        ID3D11VideoProcessorInputView* vidView = nullptr;
        hr = videoDev->CreateVideoProcessorInputView(vidTex, enumerator, &inViewDesc, &vidView);
        std::cout << "  CreateVideoProcessorInputView (Stream 0 Video): " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << "\n";

        // Create Stream 1: HUD texture (RGBA or BGRA) 3840x2160
        DXGI_FORMAT hudFmt = rgbaIn ? DXGI_FORMAT_R8G8B8A8_UNORM : DXGI_FORMAT_B8G8R8A8_UNORM;
        td.Format = hudFmt;
        td.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
        ID3D11Texture2D* hudTex = nullptr;
        dev->CreateTexture2D(&td, nullptr, &hudTex);

        ID3D11VideoProcessorInputView* hudView = nullptr;
        hr = videoDev->CreateVideoProcessorInputView(hudTex, enumerator, &inViewDesc, &hudView);
        std::cout << "  CreateVideoProcessorInputView (Stream 1 HUD):   " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << "\n";

        // Create Output: NV12 3840x2160
        td.Format = DXGI_FORMAT_NV12;
        td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_SHADER_RESOURCE;
        ID3D11Texture2D* outTex = nullptr;
        dev->CreateTexture2D(&td, nullptr, &outTex);

        D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC outViewDesc = {};
        outViewDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
        outViewDesc.Texture2D.MipSlice = 0;
        ID3D11VideoProcessorOutputView* outView = nullptr;
        hr = videoDev->CreateVideoProcessorOutputView(outTex, enumerator, &outViewDesc, &outView);
        std::cout << "  CreateVideoProcessorOutputView (Output NV12):  " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << "\n";

        if (vidView && hudView && outView) {
            // Setup Stream 0 (Video)
            videoCtx->VideoProcessorSetStreamFrameFormat(vp, 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
            videoCtx->VideoProcessorSetStreamAutoProcessingMode(vp, 0, FALSE);
            videoCtx->VideoProcessorSetStreamAlpha(vp, 0, FALSE, 1.0f);

            // Setup Stream 1 (HUD)
            videoCtx->VideoProcessorSetStreamFrameFormat(vp, 1, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
            videoCtx->VideoProcessorSetStreamAutoProcessingMode(vp, 1, FALSE);
            // Enable per-pixel alpha / stream alpha
            videoCtx->VideoProcessorSetStreamAlpha(vp, 1, TRUE, 1.0f);

            D3D11_VIDEO_PROCESSOR_STREAM streams[2] = {};
            streams[0].Enable = TRUE;
            streams[0].pInputSurface = vidView;
            streams[1].Enable = TRUE;
            streams[1].pInputSurface = hudView;

            // Execute 2-Stream Blt
            hr = videoCtx->VideoProcessorBlt(vp, outView, 0, 2, streams);
            std::cout << "  VideoProcessorBlt (2-Stream Video+HUD -> NV12): "
                      << (SUCCEEDED(hr) ? "S_OK" : "FAILED (0x" + std::to_string(hr) + ")") << "\n";
        }

        // Cleanup test resources
        if (vidView) vidView->Release();
        if (hudView) hudView->Release();
        if (outView) outView->Release();
        if (vidTex) vidTex->Release();
        if (hudTex) hudTex->Release();
        if (outTex) outTex->Release();
    }

    // Cleanup
    if (vp) vp->Release();
    if (enumerator1) enumerator1->Release();
    if (enumerator) enumerator->Release();
    if (videoCtx1) videoCtx1->Release();
    if (videoCtx) videoCtx->Release();
    if (videoDev) videoDev->Release();
    ctx->Release();
    dev->Release();

    std::cout << "\n===============================================================================\n";
    return 0;
}
