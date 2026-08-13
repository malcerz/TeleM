#include <windows.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <dxgi.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <mftransform.h>
#include <mferror.h>
#include <vector>
#include <string>
#include <iostream>
#include <fstream>
#include <chrono>

#include "d3d11_vp_pipeline.h"
#include "d3d11_amf_encoder.h"

// STB Image Write for dumping checkpoint PNGs
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#define TELEM_EXPORT extern "C" __declspec(dllexport)

struct TelemAMDContext {
    ID3D11Device* pDevice = nullptr;
    ID3D11DeviceContext* pContext = nullptr;

    D3D11VideoProcessorPipeline vpPipeline;
    D3D11AMFEncoder amfEncoder;

    // Media Foundation Decoder
    IMFSourceReader* pSourceReader = nullptr;
    IMFDXGIDeviceManager* pDXGIManager = nullptr;
    UINT dxgiResetToken = 0;

    // HUD Texture
    ID3D11Texture2D* pHUDTexture = nullptr;
    ID3D11VideoProcessorInputView* pHUDInputView = nullptr;
    UINT hudWidth = 0;
    UINT hudHeight = 0;

    // Base Video Texture (in case of manual / decoded P010 surface)
    ID3D11Texture2D* pBaseP010Tex = nullptr;

    // File Output
    std::string outputPath;
    std::ofstream h265Out;

    // Dimensions & Config
    UINT width = 3840;
    UINT height = 2160;
    UINT fpsNum = 30000;
    UINT fpsDen = 1001;

    // Frame counters
    UINT64 framesDecoded = 0;
    UINT64 framesVPProcessed = 0;
    UINT64 framesSubmitted = 0;
    UINT64 framesReceived = 0;

    // Last processed VP output NV12 texture
    ID3D11Texture2D* pLastOutNV12Tex = nullptr;
};

// Helper: Convert NV12 to RGBA in CPU memory for diagnostic checkpoint PNGs
static std::vector<uint8_t> ConvertNV12ToRGBA(const uint8_t* yData, const uint8_t* uvData, UINT w, UINT h, UINT yPitch, UINT uvPitch) {
    std::vector<uint8_t> rgba(w * h * 4, 255);
    for (UINT y = 0; y < h; ++y) {
        for (UINT x = 0; x < w; ++x) {
            int Y = yData[y * yPitch + x];
            size_t uvIndex = (y / 2) * uvPitch + (x / 2) * 2;
            int U = uvData[uvIndex] - 128;
            int V = uvData[uvIndex + 1] - 128;

            int R = (int)(Y + 1.402 * V);
            int G = (int)(Y - 0.344136 * U - 0.714136 * V);
            int B = (int)(Y + 1.772 * U);

            size_t idx = (y * w + x) * 4;
            rgba[idx + 0] = (uint8_t)(R < 0 ? 0 : (R > 255 ? 255 : R));
            rgba[idx + 1] = (uint8_t)(G < 0 ? 0 : (G > 255 ? 255 : G));
            rgba[idx + 2] = (uint8_t)(B < 0 ? 0 : (B > 255 ? 255 : B));
            rgba[idx + 3] = 255;
        }
    }
    return rgba;
}

TELEM_EXPORT void* telem_amd_create(
    const wchar_t* input_path,
    const wchar_t* output_path,
    UINT width,
    UINT height,
    UINT fps_num,
    UINT fps_den
) {
    MFStartup(MF_VERSION);

    TelemAMDContext* ctx = new TelemAMDContext();
    ctx->width = width;
    ctx->height = height;
    ctx->fpsNum = fps_num;
    ctx->fpsDen = fps_den;

    char mbsOut[512] = {};
    wcstombs(mbsOut, output_path, 512);
    ctx->outputPath = std::string(mbsOut);
    std::string h265Path = ctx->outputPath + ".h265";
    ctx->h265Out.open(h265Path, std::ios::binary);

    // 1. Initialize D3D11 Device
    UINT createDeviceFlags = D3D11_CREATE_DEVICE_VIDEO_SUPPORT;
    D3D_FEATURE_LEVEL featureLevels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
    D3D_FEATURE_LEVEL featureLevel;

    HRESULT hr = D3D11CreateDevice(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        createDeviceFlags, featureLevels, 2,
        D3D11_SDK_VERSION, &ctx->pDevice, &featureLevel, &ctx->pContext
    );
    if (FAILED(hr)) {
        std::cerr << "[TELEM AMD DLL] D3D11CreateDevice failed: 0x" << std::hex << hr << std::dec << std::endl;
        delete ctx;
        return nullptr;
    }

    // D3D11 Device initialized successfully

    // 2. Initialize VideoProcessor Pipeline
    if (!ctx->vpPipeline.Initialize(ctx->pDevice, ctx->pContext, width, height)) {
        std::cerr << "[TELEM AMD DLL] VP Pipeline Initialize failed!" << std::endl;
        delete ctx;
        return nullptr;
    }
    if (!ctx->vpPipeline.SetupVideoProcessor(DXGI_FORMAT_P010, DXGI_FORMAT_NV12)) {
        std::cerr << "[TELEM AMD DLL] VP Setup failed!" << std::endl;
        delete ctx;
        return nullptr;
    }

    // 3. Initialize AMF HEVC Encoder on shared D3D11 device
    if (!ctx->amfEncoder.Initialize(ctx->pDevice, width, height, fps_num, fps_den)) {
        std::cerr << "[TELEM AMD DLL] AMF Encoder Initialize failed!" << std::endl;
        delete ctx;
        return nullptr;
    }

    // 4. Initialize Media Foundation Decoder for Input Video File
    if (input_path && wcslen(input_path) > 0) {
        hr = MFCreateDXGIDeviceManager(&ctx->dxgiResetToken, &ctx->pDXGIManager);
        if (SUCCEEDED(hr)) {
            ctx->pDXGIManager->ResetDevice(ctx->pDevice, ctx->dxgiResetToken);

            IMFAttributes* pAttributes = nullptr;
            MFCreateAttributes(&pAttributes, 4);
            pAttributes->SetUnknown(MF_SOURCE_READER_D3D_MANAGER, ctx->pDXGIManager);
            pAttributes->SetUINT32(MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, TRUE);
            pAttributes->SetUINT32(MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, TRUE);

            hr = MFCreateSourceReaderFromURL(input_path, pAttributes, &ctx->pSourceReader);
            pAttributes->Release();

            if (SUCCEEDED(hr) && ctx->pSourceReader) {
                IMFMediaType* pType = nullptr;
                MFCreateMediaType(&pType);
                pType->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
                pType->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_P010);
                hr = ctx->pSourceReader->SetCurrentMediaType((DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM, nullptr, pType);
                if (FAILED(hr)) {
                    pType->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12);
                    ctx->pSourceReader->SetCurrentMediaType((DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM, nullptr, pType);
                }
                pType->Release();
                std::cout << "[TELEM AMD DLL] MediaFoundation D3D11VA decoder initialized successfully." << std::endl;
            }
        }
    }

    // 5. Create Standby Base P010 Texture (in case manual frame feed is used)
    D3D11_TEXTURE2D_DESC p010Desc = {};
    p010Desc.Width = width;
    p010Desc.Height = height;
    p010Desc.MipLevels = 1;
    p010Desc.ArraySize = 1;
    p010Desc.Format = DXGI_FORMAT_P010;
    p010Desc.SampleDesc.Count = 1;
    p010Desc.Usage = D3D11_USAGE_DEFAULT;
    p010Desc.BindFlags = D3D11_BIND_DECODER | D3D11_BIND_SHADER_RESOURCE;
    ctx->pDevice->CreateTexture2D(&p010Desc, nullptr, &ctx->pBaseP010Tex);

    std::cout << "[TELEM AMD DLL] telem_amd_create SUCCESS. Width: " << width << " Height: " << height << std::endl;
    return (void*)ctx;
}

TELEM_EXPORT int telem_amd_update_hud(
    void* handle,
    const uint8_t* pRGBA,
    UINT width,
    UINT height,
    UINT stride
) {
    if (!handle || !pRGBA) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    std::vector<uint8_t> rgbaVec(pRGBA, pRGBA + (height * stride));
    if (!ctx->vpPipeline.CreateHUDTexture(width, height, rgbaVec)) {
        std::cerr << "[TELEM AMD DLL] Update HUD failed!" << std::endl;
        return 0;
    }
    return 1;
}

TELEM_EXPORT int telem_amd_process_frame(
    void* handle,
    UINT frame_index
) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    ID3D11Texture2D* pDecodedTex = ctx->pBaseP010Tex;

    // Read frame from Media Foundation Decoder if available
    if (ctx->pSourceReader) {
        DWORD streamFlags = 0;
        LONGLONG timeStamp = 0;
        IMFSample* pSample = nullptr;

        HRESULT hr = ctx->pSourceReader->ReadSample(
            (DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM,
            0, nullptr, &streamFlags, &timeStamp, &pSample
        );

        if (SUCCEEDED(hr) && pSample) {
            IMFMediaBuffer* pBuffer = nullptr;
            hr = pSample->GetBufferByIndex(0, &pBuffer);
            if (SUCCEEDED(hr) && pBuffer) {
                IMFDXGIBuffer* pDXGIBuffer = nullptr;
                hr = pBuffer->QueryInterface(__uuidof(IMFDXGIBuffer), (void**)&pDXGIBuffer);
                if (SUCCEEDED(hr) && pDXGIBuffer) {
                    ID3D11Texture2D* pSampleTex = nullptr;
                    pDXGIBuffer->GetResource(__uuidof(ID3D11Texture2D), (void**)&pSampleTex);
                    if (pSampleTex) {
                        D3D11_TEXTURE2D_DESC sDesc = {};
                        pSampleTex->GetDesc(&sDesc);

                        D3D11_TEXTURE2D_DESC bDesc = {};
                        ctx->pBaseP010Tex->GetDesc(&bDesc);
                        if (bDesc.Format != sDesc.Format) {
                            ctx->pBaseP010Tex->Release();
                            ctx->pBaseP010Tex = nullptr;
                            bDesc.Format = sDesc.Format;
                            bDesc.Width = ctx->width;
                            bDesc.Height = ctx->height;
                            bDesc.MipLevels = 1;
                            bDesc.ArraySize = 1;
                            bDesc.Usage = D3D11_USAGE_DEFAULT;
                            bDesc.BindFlags = D3D11_BIND_DECODER | D3D11_BIND_SHADER_RESOURCE;
                            ctx->pDevice->CreateTexture2D(&bDesc, nullptr, &ctx->pBaseP010Tex);
                        }

                        UINT subIdx = 0;
                        pDXGIBuffer->GetSubresourceIndex(&subIdx);
                        ctx->pContext->CopySubresourceRegion(ctx->pBaseP010Tex, 0, 0, 0, 0, pSampleTex, subIdx, nullptr);
                        pDecodedTex = ctx->pBaseP010Tex;
                        pSampleTex->Release();
                    }
                    pDXGIBuffer->Release();
                }
                pBuffer->Release();
            }
            pSample->Release();
            ctx->framesDecoded++;
        }
    } else {
        ctx->framesDecoded++;
    }

    // Step 1: ID3D11VideoProcessor Hardware Blending (Base P010 + RGBA HUD -> NV12)
    ID3D11Texture2D* pOutNV12Tex = nullptr;
    VPPipelineStats vpStats = {};
    if (!ctx->vpPipeline.ProcessFrame(pDecodedTex, 0, &pOutNV12Tex, true, &vpStats)) {
        std::cerr << "[TELEM AMD DLL] VP ProcessFrame failed on frame " << frame_index << std::endl;
        return 0;
    }
    ctx->framesVPProcessed++;
    ctx->pLastOutNV12Tex = pOutNV12Tex;

    // Step 2: Direct GPU handoff to AMD AMF HEVC Hardware Encoder
    AMFEncoderStats amfStats = {};
    int64_t pts = (int64_t)frame_index * 3000;
    if (!ctx->amfEncoder.SubmitTexture(pOutNV12Tex, pts, &amfStats)) {
        std::cerr << "[TELEM AMD DLL] AMF SubmitTexture failed on frame " << frame_index << std::endl;
        return 0;
    }
    ctx->framesSubmitted++;

    // Step 3: Query Encoded Packets
    std::vector<uint8_t> pktData;
    int64_t outPts = 0;
    bool isKeyframe = false;
    if (ctx->amfEncoder.QueryPacket(pktData, outPts, isKeyframe)) {
        if (ctx->h265Out.is_open() && !pktData.empty()) {
            ctx->h265Out.write(reinterpret_cast<const char*>(pktData.data()), pktData.size());
        }
        ctx->framesReceived++;
    }

    return 1;
}

TELEM_EXPORT int telem_amd_dump_checkpoint(
    void* handle,
    UINT frame_index,
    const char* stage_name,
    const wchar_t* out_png_path
) {
    if (!handle || !stage_name || !out_png_path) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    char mbsPng[512] = {};
    wcstombs(mbsPng, out_png_path, 512);

    std::string stage(stage_name);

    if (stage == "03_d3d11_hud_texture") {
        ID3D11Texture2D* pTex = ctx->vpPipeline.GetHUDTexture();
        if (!pTex) return 0;

        D3D11_TEXTURE2D_DESC desc = {};
        pTex->GetDesc(&desc);

        D3D11_TEXTURE2D_DESC readDesc = desc;
        readDesc.Usage = D3D11_USAGE_STAGING;
        readDesc.BindFlags = 0;
        readDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        readDesc.MiscFlags = 0;

        ID3D11Texture2D* pStaging = nullptr;
        HRESULT hr = ctx->pDevice->CreateTexture2D(&readDesc, nullptr, &pStaging);
        if (SUCCEEDED(hr) && pStaging) {
            ctx->pContext->CopyResource(pStaging, pTex);

            D3D11_MAPPED_SUBRESOURCE map = {};
            if (SUCCEEDED(ctx->pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &map))) {
                stbi_write_png(mbsPng, desc.Width, desc.Height, 4, map.pData, map.RowPitch);
                ctx->pContext->Unmap(pStaging, 0);
            }
            pStaging->Release();
            std::cout << "[TELEM AMD DLL] Checkpoint 03 saved to: " << mbsPng << std::endl;
            return 1;
        }
    } else if (stage == "04_videoprocessor_output") {
        ID3D11Texture2D* pTex = ctx->pLastOutNV12Tex;
        if (!pTex) return 0;

        D3D11_TEXTURE2D_DESC desc = {};
        pTex->GetDesc(&desc);

        D3D11_TEXTURE2D_DESC readDesc = desc;
        readDesc.Usage = D3D11_USAGE_STAGING;
        readDesc.BindFlags = 0;
        readDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        readDesc.MiscFlags = 0;

        ID3D11Texture2D* pStaging = nullptr;
        HRESULT hr = ctx->pDevice->CreateTexture2D(&readDesc, nullptr, &pStaging);
        if (SUCCEEDED(hr) && pStaging) {
            ctx->pContext->CopyResource(pStaging, pTex);

            D3D11_MAPPED_SUBRESOURCE map = {};
            if (SUCCEEDED(ctx->pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &map))) {
                const uint8_t* yPlane = (const uint8_t*)map.pData;
                const uint8_t* uvPlane = yPlane + (map.RowPitch * desc.Height);
                std::vector<uint8_t> rgba = ConvertNV12ToRGBA(yPlane, uvPlane, desc.Width, desc.Height, map.RowPitch, map.RowPitch);
                stbi_write_png(mbsPng, desc.Width, desc.Height, 4, rgba.data(), desc.Width * 4);
                ctx->pContext->Unmap(pStaging, 0);
            }
            pStaging->Release();
            std::cout << "[TELEM AMD DLL] Checkpoint 04 (VP NV12 -> RGBA) saved to: " << mbsPng << std::endl;
            return 1;
        }
    }
    return 0;
}

TELEM_EXPORT int telem_amd_flush(void* handle) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    ctx->amfEncoder.Flush();

    // Drain any remaining packets from AMF
    std::vector<uint8_t> pktData;
    int64_t outPts = 0;
    bool isKeyframe = false;
    while (ctx->amfEncoder.QueryPacket(pktData, outPts, isKeyframe)) {
        if (ctx->h265Out.is_open() && !pktData.empty()) {
            ctx->h265Out.write(reinterpret_cast<const char*>(pktData.data()), pktData.size());
        }
        ctx->framesReceived++;
    }

    if (ctx->h265Out.is_open()) {
        ctx->h265Out.close();
    }
    std::cout << "[TELEM AMD DLL] telem_amd_flush completed. Total received: " << ctx->framesReceived << std::endl;
    return 1;
}

TELEM_EXPORT int telem_amd_close(void* handle) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    if (ctx->pSourceReader) ctx->pSourceReader->Release();
    if (ctx->pDXGIManager) ctx->pDXGIManager->Release();
    if (ctx->pBaseP010Tex) ctx->pBaseP010Tex->Release();
    if (ctx->pContext) ctx->pContext->Release();
    if (ctx->pDevice) ctx->pDevice->Release();

    delete ctx;
    MFShutdown();
    std::cout << "[TELEM AMD DLL] telem_amd_close completed." << std::endl;
    return 1;
}

TELEM_EXPORT void telem_amd_get_stats(
    void* handle,
    UINT64* out_decoded,
    UINT64* out_vp,
    UINT64* out_submitted,
    UINT64* out_received
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_decoded) *out_decoded = ctx->framesDecoded;
    if (out_vp) *out_vp = ctx->framesVPProcessed;
    if (out_submitted) *out_submitted = ctx->framesSubmitted;
    if (out_received) *out_received = ctx->framesReceived;
}
