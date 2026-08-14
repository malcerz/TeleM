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

    // Base Video Texture (NV12 surface)
    ID3D11Texture2D* pBaseP010Tex = nullptr;
    ID3D11Texture2D* pUploadStagingTex = nullptr;
    bool hasUpdatedVideoFrame = false;

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

    // Persistent CPU HUD RGBA buffer
    std::vector<uint8_t> currentHUDRGBA;
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

// Fast CPU Alpha Blend: RGBA HUD over NV12 Base Video
static void BlendRGBAToNV12(
    uint8_t* pNV12,
    UINT width,
    UINT height,
    UINT stride,
    const uint8_t* pRGBA
) {
    if (!pNV12 || !pRGBA) return;

    uint8_t* pY = pNV12;
    uint8_t* pUV = pNV12 + (height * stride);

    for (UINT y = 0; y < height; ++y) {
        for (UINT x = 0; x < width; ++x) {
            size_t rgbaIdx = (y * width + x) * 4;
            uint8_t a = pRGBA[rgbaIdx + 3];
            if (a == 0) continue;

            uint8_t r = pRGBA[rgbaIdx + 0];
            uint8_t g = pRGBA[rgbaIdx + 1];
            uint8_t b = pRGBA[rgbaIdx + 2];

            int Y_hud = ((66 * r + 129 * g + 25 * b + 128) >> 8) + 16;
            if (Y_hud < 0) Y_hud = 0;
            if (Y_hud > 255) Y_hud = 255;

            size_t yIdx = y * stride + x;
            if (a == 255) {
                pY[yIdx] = (uint8_t)Y_hud;
            } else {
                int yOrig = pY[yIdx];
                pY[yIdx] = (uint8_t)((Y_hud * a + yOrig * (255 - a)) / 255);
            }

            if ((y % 2 == 0) && (x % 2 == 0)) {
                int U_hud = ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128;
                int V_hud = ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128;
                if (U_hud < 0) U_hud = 0; if (U_hud > 255) U_hud = 255;
                if (V_hud < 0) V_hud = 0; if (V_hud > 255) V_hud = 255;

                size_t uvIdx = (y / 2) * stride + x;
                if (a == 255) {
                    pUV[uvIdx + 0] = (uint8_t)U_hud;
                    pUV[uvIdx + 1] = (uint8_t)V_hud;
                } else {
                    int uOrig = pUV[uvIdx + 0];
                    int vOrig = pUV[uvIdx + 1];
                    pUV[uvIdx + 0] = (uint8_t)((U_hud * a + uOrig * (255 - a)) / 255);
                    pUV[uvIdx + 1] = (uint8_t)((V_hud * a + vOrig * (255 - a)) / 255);
                }
            }
        }
    }
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

    // 5. Create Standby Base NV12 Texture & Upload Staging Texture
    D3D11_TEXTURE2D_DESC nv12Desc = {};
    nv12Desc.Width = width;
    nv12Desc.Height = height;
    nv12Desc.MipLevels = 1;
    nv12Desc.ArraySize = 1;
    nv12Desc.Format = DXGI_FORMAT_NV12;
    nv12Desc.SampleDesc.Count = 1;
    nv12Desc.Usage = D3D11_USAGE_DEFAULT;
    nv12Desc.BindFlags = D3D11_BIND_DECODER | D3D11_BIND_SHADER_RESOURCE;
    ctx->pDevice->CreateTexture2D(&nv12Desc, nullptr, &ctx->pBaseP010Tex);

    D3D11_TEXTURE2D_DESC stagingDesc = nv12Desc;
    stagingDesc.Usage = D3D11_USAGE_STAGING;
    stagingDesc.BindFlags = 0;
    stagingDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    stagingDesc.MiscFlags = 0;
    ctx->pDevice->CreateTexture2D(&stagingDesc, nullptr, &ctx->pUploadStagingTex);

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

    size_t sz = (size_t)height * stride;
    if (ctx->currentHUDRGBA.size() != sz) {
        ctx->currentHUDRGBA.resize(sz);
    }
    memcpy(ctx->currentHUDRGBA.data(), pRGBA, sz);
    return 1;
}

TELEM_EXPORT int telem_amd_update_video_frame(
    void* handle,
    const uint8_t* pNV12,
    UINT width,
    UINT height,
    UINT stride
) {
    if (!handle || !pNV12) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    if (!ctx->pBaseP010Tex || !ctx->pUploadStagingTex) return 0;

    D3D11_MAPPED_SUBRESOURCE map = {};
    HRESULT hr = ctx->pContext->Map(ctx->pUploadStagingTex, 0, D3D11_MAP_WRITE, 0, &map);
    if (SUCCEEDED(hr) && map.pData) {
        uint8_t* pDstY = (uint8_t*)map.pData;
        const uint8_t* pSrcY = pNV12;
        UINT dstPitch = map.RowPitch;

        // Copy Y plane (height rows)
        if (dstPitch == stride && dstPitch == width) {
            memcpy(pDstY, pSrcY, width * height);
        } else {
            for (UINT y = 0; y < height; ++y) {
                memcpy(pDstY + y * dstPitch, pSrcY + y * stride, width);
            }
        }

        // Copy UV plane (height / 2 rows)
        uint8_t* pDstUV = pDstY + (height * dstPitch);
        const uint8_t* pSrcUV = pNV12 + (height * stride);
        if (dstPitch == stride && dstPitch == width) {
            memcpy(pDstUV, pSrcUV, width * (height / 2));
        } else {
            for (UINT y = 0; y < height / 2; ++y) {
                memcpy(pDstUV + y * dstPitch, pSrcUV + y * stride, width);
            }
        }

        // If HUD overlay buffer is present, blend HUD directly onto mapped NV12 before unmapping
        if (!ctx->currentHUDRGBA.empty()) {
            BlendRGBAToNV12(pDstY, width, height, dstPitch, ctx->currentHUDRGBA.data());
        }

        ctx->pContext->Unmap(ctx->pUploadStagingTex, 0);

        // Fast GPU Copy to Default Base Texture
        ctx->pContext->CopyResource(ctx->pBaseP010Tex, ctx->pUploadStagingTex);
        ctx->hasUpdatedVideoFrame = true;
        return 1;
    }
    return 0;
}

TELEM_EXPORT int telem_amd_process_frame(
    void* handle,
    UINT frame_index,
    int enable_hud
) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;

    ID3D11Texture2D* pDecodedTex = ctx->pBaseP010Tex;
    UINT sampleSlice = 0;

    bool useBaseTex = true;
    if (ctx->pSourceReader && !ctx->hasUpdatedVideoFrame) {
        DWORD streamFlags = 0;
        LONGLONG timeStamp = 0;
        IMFSample* pSample = nullptr;

        HRESULT hr = ctx->pSourceReader->ReadSample(
            (DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM,
            0, nullptr, &streamFlags, &timeStamp, &pSample
        );

        if (SUCCEEDED(hr) && pSample && !(streamFlags & MF_SOURCE_READERF_STREAMTICK) && !(streamFlags & MF_SOURCE_READERF_ENDOFSTREAM)) {
            IMFMediaBuffer* pBuffer = nullptr;
            hr = pSample->GetBufferByIndex(0, &pBuffer);
            if (SUCCEEDED(hr) && pBuffer) {
                IMFDXGIBuffer* pDXGIBuffer = nullptr;
                hr = pBuffer->QueryInterface(__uuidof(IMFDXGIBuffer), (void**)&pDXGIBuffer);
                if (SUCCEEDED(hr) && pDXGIBuffer) {
                    ID3D11Texture2D* pSampleTex = nullptr;
                    pDXGIBuffer->GetResource(__uuidof(ID3D11Texture2D), (void**)&pSampleTex);
                    if (pSampleTex) {
                        UINT subIdx = 0;
                        pDXGIBuffer->GetSubresourceIndex(&subIdx);
                        pDecodedTex = pSampleTex;
                        sampleSlice = subIdx;
                        useBaseTex = false;
                    }
                    pDXGIBuffer->Release();
                }
                pBuffer->Release();
            }
            pSample->Release();
            ctx->framesDecoded++;
        }
    }
    if (useBaseTex) {
        ctx->framesDecoded++;
        ctx->hasUpdatedVideoFrame = false;
    }

    // Step 1: ID3D11VideoProcessor Hardware Stream 0 (Base Video) + Stream 1 (HUD) Composition
    ID3D11Texture2D* pOutNV12Tex = nullptr;
    VPPipelineStats vpStats = {};
    bool doHUD = (enable_hud != 0);
    if (!ctx->vpPipeline.ProcessFrame(pDecodedTex, sampleSlice, &pOutNV12Tex, doHUD, &vpStats, frame_index)) {
        std::cerr << "[TELEM AMD DLL] VP ProcessFrame failed on frame " << frame_index << std::endl;
        return 0;
    }
    if (pDecodedTex != ctx->pBaseP010Tex) {
        pDecodedTex->Release();
    }
    ctx->framesVPProcessed++;
    ctx->pLastOutNV12Tex = pOutNV12Tex;

    if (frame_index == 30) {
        std::cout << "\n--- FRAME 30 POINTER IDENTITIES ---" << std::endl;
        std::cout << "  Base Stream0 texture pointer: " << pDecodedTex << std::endl;
        std::cout << "  VP output texture pointer:    " << pOutNV12Tex << std::endl;
        std::cout << "  Texture passed to AMF:        " << pOutNV12Tex << std::endl;
        std::cout << "  VP_OUTPUT_POINTER == AMF_INPUT_POINTER: YES" << std::endl;
    }

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

    if (stage == "01_base_input" || stage == "B_base_d3d11") {
        ID3D11Texture2D* pTex = ctx->pBaseP010Tex;
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

            D3D11_MAPPED_SUBRESOURCE mapY = {}, mapUV = {};
            HRESULT hrY = ctx->pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &mapY);
            HRESULT hrUV = ctx->pContext->Map(pStaging, 1, D3D11_MAP_READ, 0, &mapUV);

            if (SUCCEEDED(hrY)) {
                const uint8_t* yPlane = (const uint8_t*)mapY.pData;
                const uint8_t* uvPlane = SUCCEEDED(hrUV) ? (const uint8_t*)mapUV.pData : (yPlane + (mapY.RowPitch * desc.Height));
                UINT yPitch = mapY.RowPitch;
                UINT uvPitch = SUCCEEDED(hrUV) ? mapUV.RowPitch : mapY.RowPitch;

                std::cout << "[DUMP STATS] stage: " << stage 
                          << " hrY: 0x" << std::hex << hrY << " hrUV: 0x" << hrUV << std::dec
                          << " yPitch: " << yPitch << " uvPitch: " << uvPitch 
                          << " yData[0]: " << (int)yPlane[0] << " uvData[0]: " << (int)uvPlane[0] << " uvData[1]: " << (int)uvPlane[1]
                          << " uvData[yPitch]: " << (int)uvPlane[uvPitch] << " uvData[yPitch+1]: " << (int)uvPlane[uvPitch+1] << std::endl;

                std::vector<uint8_t> rgba = ConvertNV12ToRGBA(yPlane, uvPlane, desc.Width, desc.Height, yPitch, uvPitch);
                stbi_write_png(mbsPng, desc.Width, desc.Height, 4, rgba.data(), desc.Width * 4);

                ctx->pContext->Unmap(pStaging, 0);
                if (SUCCEEDED(hrUV)) ctx->pContext->Unmap(pStaging, 1);
            }
            pStaging->Release();
            std::cout << "[TELEM AMD DLL] Checkpoint " << stage << " saved to: " << mbsPng << std::endl;
            return 1;
        }
    } else if (stage == "03_d3d11_hud_texture") {
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
    } else if (stage == "04_videoprocessor_output" || stage == "02_vp_stream0_output" || stage == "03_amf_input" || stage == "E_amf_input") {
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

            D3D11_MAPPED_SUBRESOURCE mapY = {}, mapUV = {};
            HRESULT hrY = ctx->pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &mapY);
            HRESULT hrUV = ctx->pContext->Map(pStaging, 1, D3D11_MAP_READ, 0, &mapUV);

            if (SUCCEEDED(hrY)) {
                const uint8_t* yPlane = (const uint8_t*)mapY.pData;
                const uint8_t* uvPlane = SUCCEEDED(hrUV) ? (const uint8_t*)mapUV.pData : (yPlane + (mapY.RowPitch * desc.Height));
                UINT yPitch = mapY.RowPitch;
                UINT uvPitch = SUCCEEDED(hrUV) ? mapUV.RowPitch : mapY.RowPitch;

                std::vector<uint8_t> rgba = ConvertNV12ToRGBA(yPlane, uvPlane, desc.Width, desc.Height, yPitch, uvPitch);
                stbi_write_png(mbsPng, desc.Width, desc.Height, 4, rgba.data(), desc.Width * 4);
                ctx->pContext->Unmap(pStaging, 0);
                if (SUCCEEDED(hrUV)) ctx->pContext->Unmap(pStaging, 1);
            }
            pStaging->Release();
            std::cout << "[TELEM AMD DLL] Checkpoint " << stage << " saved to: " << mbsPng << std::endl;
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
    if (ctx->pUploadStagingTex) ctx->pUploadStagingTex->Release();
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
