#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <iostream>
#include <vector>
#include <iomanip>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")

int main() {
    std::cout << "=== Testing D3D11 VideoProcessor Per-Pixel Alpha Blend Behavior ===\n";

    ID3D11Device* dev = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    D3D_FEATURE_LEVEL fl;
    UINT flags = D3D11_CREATE_DEVICE_VIDEO_SUPPORT;
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                   flags, nullptr, 0, D3D11_SDK_VERSION, &dev, &fl, &ctx);
    if (FAILED(hr)) return 1;

    ID3D11VideoDevice* videoDev = nullptr;
    dev->QueryInterface(__uuidof(ID3D11VideoDevice), (void**)&videoDev);
    ID3D11VideoContext* videoCtx = nullptr;
    ctx->QueryInterface(__uuidof(ID3D11VideoContext), (void**)&videoCtx);

    const UINT W = 3840, H = 2160;

    D3D11_VIDEO_PROCESSOR_CONTENT_DESC contentDesc = {};
    contentDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    contentDesc.InputWidth = W;
    contentDesc.InputHeight = H;
    contentDesc.OutputWidth = W;
    contentDesc.OutputHeight = H;
    contentDesc.Usage = D3D11_VIDEO_USAGE_OPTIMAL_QUALITY;

    ID3D11VideoProcessorEnumerator* enumerator = nullptr;
    videoDev->CreateVideoProcessorEnumerator(&contentDesc, &enumerator);

    ID3D11VideoProcessor* vp = nullptr;
    videoDev->CreateVideoProcessor(enumerator, 0, &vp);

    // 1. Fill Video Surface (Stream 0): Y = 128 (Gray), UV = 128 (Neutral)
    std::vector<BYTE> vidY(W * H, 128);
    std::vector<BYTE> vidUV(W * (H / 2), 128);
    std::vector<BYTE> vidNV12(W * H + W * (H / 2));
    memcpy(vidNV12.data(), vidY.data(), vidY.size());
    memcpy(vidNV12.data() + W * H, vidUV.data(), vidUV.size());

    D3D11_TEXTURE2D_DESC td = {};
    td.Width = W; td.Height = H; td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_NV12;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA sub0 = { vidNV12.data(), W, 0 };
    ID3D11Texture2D* vidTex = nullptr;
    dev->CreateTexture2D(&td, &sub0, &vidTex);

    // 2. Fill HUD Surface (Stream 1):
    // Left half (x < 1920): A = 0 (Transparent)
    // Right half (x >= 1920): A = 255, RGB = (255, 255, 255) (White)
    std::vector<UINT32> hudRGBA(W * H, 0);
    for (UINT y = 0; y < H; ++y) {
        for (UINT x = 0; x < W; ++x) {
            if (x < W / 2) {
                hudRGBA[y * W + x] = 0x00000000; // A=0 (Transparent)
            } else {
                hudRGBA[y * W + x] = 0xFFFFFFFF; // A=255, R=255, G=255, B=255 (Opaque White)
            }
        }
    }
    td.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA sub1 = { hudRGBA.data(), W * 4, 0 };
    ID3D11Texture2D* hudTex = nullptr;
    dev->CreateTexture2D(&td, &sub1, &hudTex);

    // 3. Output NV12 Surface
    td.Format = DXGI_FORMAT_NV12;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* outTex = nullptr;
    dev->CreateTexture2D(&td, nullptr, &outTex);

    // 4. Staging NV12 Texture for CPU Readback
    td.Usage = D3D11_USAGE_STAGING;
    td.BindFlags = 0;
    td.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* stagingTex = nullptr;
    dev->CreateTexture2D(&td, nullptr, &stagingTex);

    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inViewDesc = {};
    inViewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    inViewDesc.Texture2D.MipSlice = 0;
    inViewDesc.Texture2D.ArraySlice = 0;
    ID3D11VideoProcessorInputView* vidView = nullptr;
    videoDev->CreateVideoProcessorInputView(vidTex, enumerator, &inViewDesc, &vidView);

    ID3D11VideoProcessorInputView* hudView = nullptr;
    videoDev->CreateVideoProcessorInputView(hudTex, enumerator, &inViewDesc, &hudView);

    D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC outViewDesc = {};
    outViewDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
    outViewDesc.Texture2D.MipSlice = 0;
    ID3D11VideoProcessorOutputView* outView = nullptr;
    videoDev->CreateVideoProcessorOutputView(outTex, enumerator, &outViewDesc, &outView);

    RECT rFull = { 0, 0, (LONG)W, (LONG)H };
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

    // Run 2-Stream Blt
    hr = videoCtx->VideoProcessorBlt(vp, outView, 0, 2, s);
    std::cout << "VideoProcessorBlt (2-Stream): " << (SUCCEEDED(hr) ? "S_OK" : "FAILED") << std::endl;

    if (SUCCEEDED(hr)) {
        ctx->CopyResource(stagingTex, outTex);

        D3D11_MAPPED_SUBRESOURCE mapped;
        hr = ctx->Map(stagingTex, 0, D3D11_MAP_READ, 0, &mapped);
        if (SUCCEEDED(hr)) {
            BYTE* pY = (BYTE*)mapped.pData;
            UINT pitch = mapped.RowPitch;

            // Sample pixel on left side (x=500, y=1080) -> HUD A=0 (Expected Y=128 if alpha blended, Y=16 if opaque overwrite)
            BYTE leftY = pY[1080 * pitch + 500];

            // Sample pixel on right side (x=3000, y=1080) -> HUD A=255, White (Expected Y=235)
            BYTE rightY = pY[1080 * pitch + 3000];

            ctx->Unmap(stagingTex, 0);

            std::cout << "\n=== READBACK RESULTS ===\n";
            std::cout << "  Left Half (HUD Alpha = 0, Expected Video Y=128):\n";
            std::cout << "    Actual Y Output = " << (int)leftY << "\n";
            if (leftY == 128) {
                std::cout << "    -> PER-PIXEL ALPHA BLENDING: WORKING (Video Preserved through Alpha=0!)\n";
            } else if (leftY <= 20) {
                std::cout << "    -> OPAQUE OVERWRITE: FAILED (Alpha ignored! Solid black overwrite Y=" << (int)leftY << ")\n";
            } else {
                std::cout << "    -> UNEXPECTED VALUE Y=" << (int)leftY << "\n";
            }

            std::cout << "  Right Half (HUD Alpha = 255, White):\n";
            std::cout << "    Actual Y Output = " << (int)rightY << "\n";
        }
    }

    // Cleanup
    if (vidView) vidView->Release();
    if (hudView) hudView->Release();
    if (outView) outView->Release();
    if (vidTex) vidTex->Release();
    if (hudTex) hudTex->Release();
    if (outTex) outTex->Release();
    if (stagingTex) stagingTex->Release();
    if (vp) vp->Release();
    if (enumerator) enumerator->Release();
    if (videoCtx) videoCtx->Release();
    if (videoDev) videoDev->Release();
    ctx->Release();
    dev->Release();

    return 0;
}
