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
#include <thread>

#include "d3d11_vp_pipeline.h"
#include "d3d11_amf_encoder.h"
#include "telem_amd_build_info.h"

// STB Image Write for dumping checkpoint PNGs
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#define TELEM_EXPORT extern "C" __declspec(dllexport)

struct TelemAMDFrameTimings {
    double mfReadSampleMs = 0.0;
    double mfSurfaceAcquireMs = 0.0;
    double baseGpuCopyMs = 0.0;
    double hudNativeCopyMs = 0.0;
    double hudUploadMs = 0.0;
    double stagingMemcpyMs = 0.0;
    double blendMs = 0.0;
    double copySubmitMs = 0.0;
    double vpCpuSubmitMs = 0.0;
    double vpGpuCompletionMs = 0.0;
    double gpuWaitMs = 0.0;
    double amfSubmitMs = 0.0;
    double amfQueryMs = 0.0;
    double packetWriteMs = 0.0;
};

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
    ID3D11Texture2D* pDecodedCopyTex = nullptr;
    bool hasUpdatedVideoFrame = false;

    // Pending Media Foundation D3D11 sample. ReadSample and processing are
    // deliberately split so Python can generate HUD from the real sample PTS.
    ID3D11Texture2D* pPendingDecodedTex = nullptr;
    UINT pendingSubresource = 0;
    LONGLONG pendingTimestamp100ns = 0;
    LONGLONG pendingDuration100ns = 0;
    DWORD pendingStreamFlags = 0;
    DXGI_FORMAT decoderOutputFormat = DXGI_FORMAT_UNKNOWN;
    UINT decoderWidth = 0;
    UINT decoderHeight = 0;
    UINT sourceRotation = 0;
    bool mfDecoderReady = false;
    bool mfHardwareConfirmed = false;
    bool mfEndOfStream = false;
    int decodeMode = 0; // 0 = CPU_DECODE_REFERENCE, 1 = D3D11VA

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
    UINT64 hudUpdates = 0;
    UINT64 videoUpdates = 0;
    UINT64 amfInputFullCount = 0;
    UINT64 amfRetryCount = 0;
    UINT64 amfDroppedSubmissions = 0;
    UINT64 amfIgnoredSubmissions = 0;
    UINT64 blendCalls = 0;
    UINT64 gpuProfiledFrames = 0;
    UINT64 gpuHUDFrames = 0;
    UINT64 hudTextureCreates = 0;
    UINT64 hudTextureUploads = 0;
    UINT64 hudUploadedBytes = 0;
    UINT64 hudUploadedRects = 0;
    UINT64 mfReadSampleCalls = 0;
    UINT64 mfVideoSamples = 0;
    UINT64 mfStreamTicks = 0;
    UINT64 mfNullSamples = 0;
    UINT64 mfD3D11Surfaces = 0;
    UINT64 mfFormatChanges = 0;
    UINT64 mfEndOfStreamEvents = 0;
    UINT64 directDecoderSurfaceFrames = 0;
    UINT64 decoderGpuCopyFrames = 0;

    bool diagnosticsEnabled = false;
    bool profilingEnabled = false;
    bool hudEnabled = true;
    // 0 = CPU_REFERENCE, 1 = GPU_HUD.
    int hudMode = 0;
    TelemAMDFrameTimings lastTimings;

    // Last processed VP output NV12 texture
    ID3D11Texture2D* pLastOutNV12Tex = nullptr;

    // Persistent CPU HUD RGBA buffer
    std::vector<uint8_t> currentHUDRGBA;
};

static bool RefreshDecoderMediaType(TelemAMDContext* ctx);

TELEM_EXPORT UINT telem_amd_get_abi_version() {
    return TELEM_AMD_ABI_VERSION;
}

TELEM_EXPORT const char* telem_amd_get_build_info() {
    static const char buildInfo[] =
        "version=" TELEM_AMD_VERSION
        "; build_id=" TELEM_AMD_BUILD_ID
        "; build_timestamp=" TELEM_AMD_BUILD_TIMESTAMP
        "; git_commit=" TELEM_AMD_GIT_COMMIT
        "; source_hash=" TELEM_AMD_SOURCE_HASH;
    return buildInfo;
}

TELEM_EXPORT int telem_amd_set_diagnostics(void* handle, int enabled) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->diagnosticsEnabled = (enabled != 0);
    return 1;
}

TELEM_EXPORT int telem_amd_set_profiling(void* handle, int enabled) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->profilingEnabled = (enabled != 0);
    return 1;
}

TELEM_EXPORT int telem_amd_set_hud_enabled(void* handle, int enabled) {
    if (!handle) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->hudEnabled = (enabled != 0);
    if (!ctx->hudEnabled) {
        ctx->currentHUDRGBA.clear();
    }
    return 1;
}

TELEM_EXPORT int telem_amd_set_hud_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    ctx->hudMode = mode;
    return 1;
}

TELEM_EXPORT int telem_amd_set_source_rotation(void* handle, UINT degrees) {
    if (!handle) return 0;
    degrees %= 360;
    if (degrees != 0 && degrees != 90 && degrees != 180 && degrees != 270) return 0;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    ctx->sourceRotation = degrees;
    if (ctx->decodeMode == 1) {
        return ctx->vpPipeline.SetStreamRotation(degrees) ? 1 : 0;
    }
    return 1;
}

TELEM_EXPORT int telem_amd_set_decode_mode(void* handle, int mode) {
    if (!handle || (mode != 0 && mode != 1)) return 0;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    if (mode == 1) {
        if (!ctx->mfDecoderReady || !ctx->pSourceReader ||
            ctx->decoderWidth != ctx->width || ctx->decoderHeight != ctx->height) {
            std::cerr << "[MF DECODER] D3D11VA mode rejected: decoder is not ready or dimensions differ."
                      << std::endl;
            return 0;
        }
        if (!ctx->vpPipeline.SetStreamRotation(ctx->sourceRotation)) {
            std::cerr << "[MF DECODER] Failed to configure VP rotation="
                      << ctx->sourceRotation << std::endl;
            return 0;
        }
    }
    ctx->decodeMode = mode;
    std::cout << "[MF DECODER] Active mode="
              << (mode == 1 ? "GPU_HUD_D3D11VA" : "GPU_HUD_CPU_DECODE_REFERENCE")
              << " rotation=" << ctx->sourceRotation << std::endl;
    return 1;
}

// Return: 1 = D3D11 video sample ready, 2 = non-sample event/tick,
// 0 = clean EOS, -1 = fatal decode/acquisition error.
TELEM_EXPORT int telem_amd_read_video_sample(
    void* handle,
    UINT64* outFrameIndex,
    INT64* outTimestamp100ns,
    INT64* outDuration100ns,
    UINT* outStreamFlags,
    UINT* outDXGIFormat,
    UINT* outWidth,
    UINT* outHeight,
    UINT* outSubresource,
    UINT64* outTexturePointer
) {
    if (!handle) return -1;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    if (ctx->decodeMode != 1 || !ctx->pSourceReader || ctx->mfEndOfStream) return 0;
    if (ctx->pPendingDecodedTex) {
        std::cerr << "[MF DECODER] Read requested before pending sample was processed." << std::endl;
        return -1;
    }

    ctx->lastTimings = {};
    DWORD actualStream = 0;
    DWORD streamFlags = 0;
    LONGLONG timestamp = 0;
    IMFSample* sample = nullptr;
    const auto readStart = std::chrono::high_resolution_clock::now();
    const HRESULT readHR = ctx->pSourceReader->ReadSample(
        static_cast<DWORD>(MF_SOURCE_READER_FIRST_VIDEO_STREAM), 0,
        &actualStream, &streamFlags, &timestamp, &sample);
    const auto readEnd = std::chrono::high_resolution_clock::now();
    ctx->lastTimings.mfReadSampleMs = std::chrono::duration<double, std::milli>(
        readEnd - readStart).count();
    ctx->mfReadSampleCalls++;

    if (FAILED(readHR) || (streamFlags & MF_SOURCE_READERF_ERROR)) {
        if (sample) sample->Release();
        std::cerr << "[MF DECODER] ReadSample failed: 0x" << std::hex << readHR
                  << " flags=0x" << streamFlags << std::dec << std::endl;
        return -1;
    }
    if (streamFlags & (MF_SOURCE_READERF_NATIVEMEDIATYPECHANGED |
                       MF_SOURCE_READERF_CURRENTMEDIATYPECHANGED)) {
        ctx->mfFormatChanges++;
        if (!RefreshDecoderMediaType(ctx)) {
            if (sample) sample->Release();
            return -1;
        }
    }
    if (streamFlags & MF_SOURCE_READERF_STREAMTICK) {
        ctx->mfStreamTicks++;
    }
    if (streamFlags & MF_SOURCE_READERF_ENDOFSTREAM) {
        if (sample) sample->Release();
        ctx->mfEndOfStream = true;
        ctx->mfEndOfStreamEvents++;
        if (outStreamFlags) *outStreamFlags = streamFlags;
        return 0;
    }
    if (!sample) {
        ctx->mfNullSamples++;
        if (outStreamFlags) *outStreamFlags = streamFlags;
        return 2;
    }

    const auto acquireStart = std::chrono::high_resolution_clock::now();
    LONGLONG duration = 0;
    sample->GetSampleDuration(&duration);
    IMFMediaBuffer* mediaBuffer = nullptr;
    HRESULT hr = sample->GetBufferByIndex(0, &mediaBuffer);
    IMFDXGIBuffer* dxgiBuffer = nullptr;
    if (SUCCEEDED(hr) && mediaBuffer) {
        hr = mediaBuffer->QueryInterface(
            __uuidof(IMFDXGIBuffer), reinterpret_cast<void**>(&dxgiBuffer));
    }
    ID3D11Texture2D* texture = nullptr;
    UINT subresource = 0;
    if (SUCCEEDED(hr) && dxgiBuffer) {
        hr = dxgiBuffer->GetResource(
            __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&texture));
        if (SUCCEEDED(hr)) dxgiBuffer->GetSubresourceIndex(&subresource);
    }
    if (dxgiBuffer) dxgiBuffer->Release();
    if (mediaBuffer) mediaBuffer->Release();
    sample->Release();
    const auto acquireEnd = std::chrono::high_resolution_clock::now();
    ctx->lastTimings.mfSurfaceAcquireMs = std::chrono::duration<double, std::milli>(
        acquireEnd - acquireStart).count();

    if (FAILED(hr) || !texture) {
        if (texture) texture->Release();
        std::cerr << "[MF DECODER] Sample is not an IMFDXGIBuffer D3D11 texture: 0x"
                  << std::hex << hr << std::dec << std::endl;
        return -1;
    }

    D3D11_TEXTURE2D_DESC desc = {};
    texture->GetDesc(&desc);
    if ((desc.Format != DXGI_FORMAT_P010 && desc.Format != DXGI_FORMAT_NV12) ||
        desc.Width != ctx->width || desc.Height != ctx->height ||
        subresource >= desc.ArraySize) {
        std::cerr << "[MF DECODER] Unsupported decoder surface: format=" << desc.Format
                  << " size=" << desc.Width << "x" << desc.Height
                  << " array=" << desc.ArraySize << " subresource=" << subresource << std::endl;
        texture->Release();
        return -1;
    }

    const UINT64 frameIndex = ctx->mfVideoSamples;
    ctx->pPendingDecodedTex = texture;
    ctx->pendingSubresource = subresource;
    ctx->pendingTimestamp100ns = timestamp;
    ctx->pendingDuration100ns = duration;
    ctx->pendingStreamFlags = streamFlags;
    ctx->mfVideoSamples++;
    ctx->mfD3D11Surfaces++;
    if ((desc.BindFlags & D3D11_BIND_DECODER) != 0 && desc.ArraySize > 1) {
        ctx->mfHardwareConfirmed = true;
    }

    if (frameIndex < 3 || frameIndex == 30 || frameIndex == 300 ||
        frameIndex == 600 || frameIndex == 900) {
        std::cout << "[MF SAMPLE] frame=" << frameIndex
                  << " pts100ns=" << timestamp
                  << " duration100ns=" << duration
                  << " format=" << desc.Format
                  << " size=" << desc.Width << "x" << desc.Height
                  << " array=" << desc.ArraySize
                  << " subresource=" << subresource
                  << " bind=0x" << std::hex << desc.BindFlags << std::dec
                  << " texture=" << texture << std::endl;
    }

    if (outFrameIndex) *outFrameIndex = frameIndex;
    if (outTimestamp100ns) *outTimestamp100ns = timestamp;
    if (outDuration100ns) *outDuration100ns = duration;
    if (outStreamFlags) *outStreamFlags = streamFlags;
    if (outDXGIFormat) *outDXGIFormat = static_cast<UINT>(desc.Format);
    if (outWidth) *outWidth = desc.Width;
    if (outHeight) *outHeight = desc.Height;
    if (outSubresource) *outSubresource = subresource;
    if (outTexturePointer) {
        *outTexturePointer = static_cast<UINT64>(reinterpret_cast<uintptr_t>(texture));
    }
    return 1;
}

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

static DXGI_FORMAT DXGIFormatFromMFSubtype(const GUID& subtype) {
    if (IsEqualGUID(subtype, MFVideoFormat_P010)) return DXGI_FORMAT_P010;
    if (IsEqualGUID(subtype, MFVideoFormat_NV12)) return DXGI_FORMAT_NV12;
    return DXGI_FORMAT_UNKNOWN;
}

static bool RefreshDecoderMediaType(TelemAMDContext* ctx) {
    if (!ctx || !ctx->pSourceReader) return false;
    IMFMediaType* mediaType = nullptr;
    HRESULT hr = ctx->pSourceReader->GetCurrentMediaType(
        static_cast<DWORD>(MF_SOURCE_READER_FIRST_VIDEO_STREAM), &mediaType);
    if (FAILED(hr) || !mediaType) return false;

    GUID subtype = GUID_NULL;
    UINT32 width = 0;
    UINT32 height = 0;
    UINT32 primaries = 0;
    UINT32 transfer = 0;
    UINT32 matrix = 0;
    UINT32 range = 0;
    UINT32 rotation = 0;
    mediaType->GetGUID(MF_MT_SUBTYPE, &subtype);
    MFGetAttributeSize(mediaType, MF_MT_FRAME_SIZE, &width, &height);
    mediaType->GetUINT32(MF_MT_VIDEO_PRIMARIES, &primaries);
    mediaType->GetUINT32(MF_MT_TRANSFER_FUNCTION, &transfer);
    mediaType->GetUINT32(MF_MT_YUV_MATRIX, &matrix);
    mediaType->GetUINT32(MF_MT_VIDEO_NOMINAL_RANGE, &range);
    // Container rotation is supplied by the production probe because the
    // MinGW Media Foundation headers do not expose it consistently here.

    ctx->decoderOutputFormat = DXGIFormatFromMFSubtype(subtype);
    ctx->decoderWidth = width;
    ctx->decoderHeight = height;
    if (rotation == 90 || rotation == 180 || rotation == 270) {
        ctx->sourceRotation = rotation;
    }
    std::cout << "[MF DECODER TYPE] DXGI format=" << static_cast<UINT>(ctx->decoderOutputFormat)
              << " size=" << width << "x" << height
              << " primaries=" << primaries
              << " transfer=" << transfer
              << " matrix=" << matrix
              << " range=" << range
              << " rotation=" << rotation << std::endl;
    mediaType->Release();
    return ctx->decoderOutputFormat == DXGI_FORMAT_P010 ||
           ctx->decoderOutputFormat == DXGI_FORMAT_NV12;
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
            MFCreateAttributes(&pAttributes, 5);
            pAttributes->SetUnknown(MF_SOURCE_READER_D3D_MANAGER, ctx->pDXGIManager);
            pAttributes->SetUINT32(MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, TRUE);
            pAttributes->SetUINT32(MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, TRUE);

            hr = MFCreateSourceReaderFromURL(input_path, pAttributes, &ctx->pSourceReader);
            pAttributes->Release();

            if (SUCCEEDED(hr) && ctx->pSourceReader) {
                ctx->pSourceReader->SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS, FALSE);
                ctx->pSourceReader->SetStreamSelection(
                    static_cast<DWORD>(MF_SOURCE_READER_FIRST_VIDEO_STREAM), TRUE);
                IMFMediaType* pType = nullptr;
                MFCreateMediaType(&pType);
                pType->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
                pType->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_P010);
                MFSetAttributeSize(pType, MF_MT_FRAME_SIZE, width, height);
                hr = ctx->pSourceReader->SetCurrentMediaType((DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM, nullptr, pType);
                if (FAILED(hr)) {
                    pType->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12);
                    hr = ctx->pSourceReader->SetCurrentMediaType((DWORD)MF_SOURCE_READER_FIRST_VIDEO_STREAM, nullptr, pType);
                }
                pType->Release();
                ctx->mfDecoderReady = SUCCEEDED(hr) && RefreshDecoderMediaType(ctx);
                if (ctx->mfDecoderReady) {
                    std::cout << "[TELEM AMD DLL] MediaFoundation D3D11VA decoder configured." << std::endl;
                } else {
                    std::cerr << "[TELEM AMD DLL] MediaFoundation decoder format negotiation failed: 0x"
                              << std::hex << hr << std::dec << std::endl;
                }
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

    const auto copyStart = std::chrono::high_resolution_clock::now();
    size_t sz = (size_t)height * stride;
    if (ctx->currentHUDRGBA.size() != sz) {
        ctx->currentHUDRGBA.resize(sz);
    }
    memcpy(ctx->currentHUDRGBA.data(), pRGBA, sz);
    const auto copyEnd = std::chrono::high_resolution_clock::now();
    ctx->lastTimings.hudNativeCopyMs = std::chrono::duration<double, std::milli>(
        copyEnd - copyStart).count();
    if (ctx->hudMode == 1) {
        const auto uploadStart = std::chrono::high_resolution_clock::now();
        size_t uploadedBytes = 0;
        bool textureCreated = false;
        if (!ctx->vpPipeline.UpdateHUDTexture(
                width, height, ctx->currentHUDRGBA.data(), stride,
                nullptr, 0, true, &uploadedBytes, &textureCreated)) {
            std::cerr << "[TELEM AMD DLL] GPU HUD texture upload failed." << std::endl;
            return 0;
        }
        const auto uploadEnd = std::chrono::high_resolution_clock::now();
        ctx->lastTimings.hudUploadMs = std::chrono::duration<double, std::milli>(
            uploadEnd - uploadStart).count();
        if (textureCreated) ctx->hudTextureCreates++;
        ctx->hudTextureUploads++;
        ctx->hudUploadedBytes += uploadedBytes;
        ctx->hudUploadedRects++;
    }
    ctx->hudUpdates++;
    return 1;
}

struct TelemAMDHUDRect {
    UINT x;
    UINT y;
    UINT width;
    UINT height;
};

TELEM_EXPORT int telem_amd_update_hud_regions(
    void* handle,
    const uint8_t* pRGBA,
    UINT width,
    UINT height,
    UINT stride,
    const TelemAMDHUDRect* rects,
    UINT rectCount,
    int fullUpload
) {
    if (!handle || !pRGBA || stride < width * 4) return 0;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (ctx->hudMode != 1) return 0;

    static_assert(sizeof(TelemAMDHUDRect) == sizeof(HUDDirtyRect), "HUD rect ABI mismatch");
    ctx->lastTimings.hudNativeCopyMs = 0.0;
    const auto uploadStart = std::chrono::high_resolution_clock::now();
    size_t uploadedBytes = 0;
    bool textureCreated = false;
    if (!ctx->vpPipeline.UpdateHUDTexture(
            width, height, pRGBA, stride,
            reinterpret_cast<const HUDDirtyRect*>(rects), rectCount,
            fullUpload != 0, &uploadedBytes, &textureCreated)) {
        std::cerr << "[TELEM AMD DLL] GPU HUD region upload failed." << std::endl;
        return 0;
    }
    const auto uploadEnd = std::chrono::high_resolution_clock::now();
    ctx->lastTimings.hudUploadMs = std::chrono::duration<double, std::milli>(
        uploadEnd - uploadStart).count();
    if (textureCreated) ctx->hudTextureCreates++;
    if (uploadedBytes > 0) ctx->hudTextureUploads++;
    ctx->hudUploadedBytes += uploadedBytes;
    ctx->hudUploadedRects += (fullUpload != 0 || textureCreated) ? 1 : rectCount;
    ctx->hudUpdates++;
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
        const double hudNativeCopyMs = ctx->lastTimings.hudNativeCopyMs;
        const double hudUploadMs = ctx->lastTimings.hudUploadMs;
        ctx->lastTimings = {};
        ctx->lastTimings.hudNativeCopyMs = hudNativeCopyMs;
        ctx->lastTimings.hudUploadMs = hudUploadMs;
        uint8_t* pDstY = (uint8_t*)map.pData;
        const uint8_t* pSrcY = pNV12;
        UINT dstPitch = map.RowPitch;

        const auto memcpyStart = std::chrono::high_resolution_clock::now();
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
        const auto memcpyEnd = std::chrono::high_resolution_clock::now();
        ctx->lastTimings.stagingMemcpyMs = std::chrono::duration<double, std::milli>(
            memcpyEnd - memcpyStart).count();

        // If HUD overlay buffer is present, blend HUD directly onto mapped NV12 before unmapping
        const auto blendStart = std::chrono::high_resolution_clock::now();
        if (ctx->hudEnabled && ctx->hudMode == 0 && !ctx->currentHUDRGBA.empty()) {
            BlendRGBAToNV12(pDstY, width, height, dstPitch, ctx->currentHUDRGBA.data());
            ctx->blendCalls++;
        }
        const auto blendEnd = std::chrono::high_resolution_clock::now();
        ctx->lastTimings.blendMs = std::chrono::duration<double, std::milli>(
            blendEnd - blendStart).count();

        const auto copyStart = std::chrono::high_resolution_clock::now();
        ctx->pContext->Unmap(ctx->pUploadStagingTex, 0);

        // Fast GPU Copy to Default Base Texture
        ctx->pContext->CopyResource(ctx->pBaseP010Tex, ctx->pUploadStagingTex);
        const auto copyEnd = std::chrono::high_resolution_clock::now();
        ctx->lastTimings.copySubmitMs = std::chrono::duration<double, std::milli>(
            copyEnd - copyStart).count();
        ctx->hasUpdatedVideoFrame = true;
        ctx->videoUpdates++;
        return 1;
    }
    return 0;
}

static bool EnsureDecoderCopyTexture(
    TelemAMDContext* ctx,
    const D3D11_TEXTURE2D_DESC& sourceDesc
) {
    if (!ctx || !ctx->pDevice) return false;
    if (ctx->pDecodedCopyTex) {
        D3D11_TEXTURE2D_DESC existing = {};
        ctx->pDecodedCopyTex->GetDesc(&existing);
        if (existing.Width == sourceDesc.Width && existing.Height == sourceDesc.Height &&
            existing.Format == sourceDesc.Format) {
            return true;
        }
        ctx->pDecodedCopyTex->Release();
        ctx->pDecodedCopyTex = nullptr;
    }

    D3D11_TEXTURE2D_DESC copyDesc = {};
    copyDesc.Width = sourceDesc.Width;
    copyDesc.Height = sourceDesc.Height;
    copyDesc.MipLevels = 1;
    copyDesc.ArraySize = 1;
    copyDesc.Format = sourceDesc.Format;
    copyDesc.SampleDesc.Count = 1;
    copyDesc.Usage = D3D11_USAGE_DEFAULT;
    copyDesc.BindFlags = D3D11_BIND_DECODER | D3D11_BIND_SHADER_RESOURCE;
    const HRESULT hr = ctx->pDevice->CreateTexture2D(
        &copyDesc, nullptr, &ctx->pDecodedCopyTex);
    if (FAILED(hr)) {
        std::cerr << "[MF DECODER] Compatible GPU copy texture creation failed: 0x"
                  << std::hex << hr << std::dec << std::endl;
        return false;
    }
    return true;
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
    const bool d3d11Decode = ctx->decodeMode == 1;
    const LONGLONG sourceTimestamp100ns = ctx->pendingTimestamp100ns;
    if (d3d11Decode) {
        if (!ctx->pPendingDecodedTex) {
            std::cerr << "[MF DECODER] Process requested without a pending D3D11 sample." << std::endl;
            return 0;
        }
        pDecodedTex = ctx->pPendingDecodedTex;
        sampleSlice = ctx->pendingSubresource;

        if (ctx->vpPipeline.CanUseInputSurface(pDecodedTex, sampleSlice)) {
            ctx->directDecoderSurfaceFrames++;
        } else {
            D3D11_TEXTURE2D_DESC sourceDesc = {};
            pDecodedTex->GetDesc(&sourceDesc);
            if (!EnsureDecoderCopyTexture(ctx, sourceDesc)) return 0;
            const auto copyStart = std::chrono::high_resolution_clock::now();
            ctx->pContext->CopySubresourceRegion(
                ctx->pDecodedCopyTex, 0, 0, 0, 0,
                pDecodedTex, sampleSlice, nullptr);
            const auto copyEnd = std::chrono::high_resolution_clock::now();
            ctx->lastTimings.baseGpuCopyMs = std::chrono::duration<double, std::milli>(
                copyEnd - copyStart).count();
            pDecodedTex = ctx->pDecodedCopyTex;
            sampleSlice = 0;
            ctx->decoderGpuCopyFrames++;
        }
    } else {
        if (!ctx->hasUpdatedVideoFrame) {
            std::cerr << "[CPU DECODE REFERENCE] Process requested without uploaded NV12." << std::endl;
            return 0;
        }
        ctx->hasUpdatedVideoFrame = false;
    }

    // Step 1: ID3D11VideoProcessor Hardware Stream 0 (Base Video) + Stream 1 (HUD) Composition
    ID3D11Texture2D* pOutNV12Tex = nullptr;
    VPPipelineStats vpStats = {};
    bool doHUD = ctx->hudEnabled && ctx->hudMode == 1 && (enable_hud != 0);
    if (!ctx->vpPipeline.ProcessFrame(
            pDecodedTex, sampleSlice, &pOutNV12Tex, doHUD, d3d11Decode, &vpStats,
            frame_index, ctx->diagnosticsEnabled, ctx->profilingEnabled)) {
        std::cerr << "[TELEM AMD DLL] VP ProcessFrame failed on frame " << frame_index << std::endl;
        if (d3d11Decode && ctx->pPendingDecodedTex) {
            ctx->pPendingDecodedTex->Release();
            ctx->pPendingDecodedTex = nullptr;
        }
        return 0;
    }
    if (d3d11Decode && ctx->pPendingDecodedTex) {
        ctx->pPendingDecodedTex->Release();
        ctx->pPendingDecodedTex = nullptr;
    }
    ctx->framesDecoded++;
    ctx->framesVPProcessed++;
    if (doHUD) ctx->gpuHUDFrames++;
    ctx->pLastOutNV12Tex = pOutNV12Tex;
    ctx->lastTimings.vpCpuSubmitMs = vpStats.cpu_submit_ms;
    ctx->lastTimings.vpGpuCompletionMs = vpStats.gpu_completion_ms;
    ctx->lastTimings.gpuWaitMs = vpStats.gpu_wait_ms;
    if (ctx->profilingEnabled) {
        ctx->gpuProfiledFrames++;
    }

    if (ctx->diagnosticsEnabled && frame_index == 30) {
        std::cout << "\n--- FRAME 30 POINTER IDENTITIES ---" << std::endl;
        std::cout << "  Base Stream0 texture pointer: " << pDecodedTex << std::endl;
        std::cout << "  VP output texture pointer:    " << pOutNV12Tex << std::endl;
        std::cout << "  Texture passed to AMF:        " << pOutNV12Tex << std::endl;
        std::cout << "  VP_OUTPUT_POINTER == AMF_INPUT_POINTER: YES" << std::endl;
        std::cout << "  Output pool index:            " << ctx->vpPipeline.GetLastPoolIndex() << std::endl;
        std::cout << "  Frame number:                 " << frame_index << std::endl;
    }

    // Step 2: Direct GPU handoff to AMD AMF HEVC Hardware Encoder
    AMFEncoderStats amfStats = {};
    int64_t pts = d3d11Decode ? sourceTimestamp100ns : (int64_t)frame_index * 3000;
    const auto submitLoopStart = std::chrono::steady_clock::now();
    constexpr auto kMaxInputFullWait = std::chrono::seconds(60);
    UINT retriesThisFrame = 0;
    bool submitted = false;
    while (!submitted) {
        amfStats = {};
        const bool submitOk = ctx->amfEncoder.SubmitTexture(pOutNV12Tex, pts, &amfStats);
        if (submitOk) {
            submitted = true;
            break;
        }
        if (!amfStats.input_full) {
            ctx->amfDroppedSubmissions++;
            std::cerr << "[TELEM AMD DLL] AMF SubmitTexture failed on frame " << frame_index << std::endl;
            return 0;
        }

        ctx->amfInputFullCount++;
        ctx->amfRetryCount++;
        retriesThisFrame++;

        // Correctness-only backpressure handling: drain one ready packet and
        // retry the exact same surface.  Queue depth and encoder settings stay
        // unchanged.
        std::vector<uint8_t> backpressurePacket;
        int64_t backpressurePts = 0;
        bool backpressureKeyframe = false;
        AMF_RESULT queryResult = AMF_REPEAT;
        double queryMs = 0.0;
        if (ctx->amfEncoder.QueryPacket(
                backpressurePacket, backpressurePts, backpressureKeyframe,
                &queryResult, &queryMs)) {
            ctx->lastTimings.amfQueryMs += queryMs;
            const auto writeStart = std::chrono::high_resolution_clock::now();
            if (ctx->h265Out.is_open() && !backpressurePacket.empty()) {
                ctx->h265Out.write(
                    reinterpret_cast<const char*>(backpressurePacket.data()),
                    backpressurePacket.size());
            }
            const auto writeEnd = std::chrono::high_resolution_clock::now();
            ctx->lastTimings.packetWriteMs += std::chrono::duration<double, std::milli>(
                writeEnd - writeStart).count();
            ctx->framesReceived++;
        } else {
            ctx->lastTimings.amfQueryMs += queryMs;
            std::this_thread::yield();
        }

        if (std::chrono::steady_clock::now() - submitLoopStart >= kMaxInputFullWait) {
            ctx->amfDroppedSubmissions++;
            std::cerr << "[TELEM AMD DLL] AMF_INPUT_FULL timed out after 60 seconds on frame "
                      << frame_index << " retries=" << retriesThisFrame << std::endl;
            return 0;
        }
    }
    ctx->lastTimings.amfSubmitMs = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - submitLoopStart).count();
    ctx->framesSubmitted++;

    // Step 3: Query Encoded Packets
    std::vector<uint8_t> pktData;
    int64_t outPts = 0;
    bool isKeyframe = false;
    AMF_RESULT queryResult = AMF_REPEAT;
    double queryMs = 0.0;
    if (ctx->amfEncoder.QueryPacket(pktData, outPts, isKeyframe, &queryResult, &queryMs)) {
        ctx->lastTimings.amfQueryMs += queryMs;
        const auto writeStart = std::chrono::high_resolution_clock::now();
        if (ctx->h265Out.is_open() && !pktData.empty()) {
            ctx->h265Out.write(reinterpret_cast<const char*>(pktData.data()), pktData.size());
        }
        const auto writeEnd = std::chrono::high_resolution_clock::now();
        ctx->lastTimings.packetWriteMs += std::chrono::duration<double, std::milli>(
            writeEnd - writeStart).count();
        ctx->framesReceived++;
    } else {
        ctx->lastTimings.amfQueryMs += queryMs;
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
    const auto drainStart = std::chrono::steady_clock::now();
    while (true) {
        AMF_RESULT queryResult = AMF_REPEAT;
        if (ctx->amfEncoder.QueryPacket(pktData, outPts, isKeyframe, &queryResult, nullptr)) {
            if (ctx->h265Out.is_open() && !pktData.empty()) {
                ctx->h265Out.write(reinterpret_cast<const char*>(pktData.data()), pktData.size());
            }
            ctx->framesReceived++;
            continue;
        }
        if (queryResult == AMF_EOF) break;
        if (queryResult != AMF_REPEAT) {
            std::cerr << "[TELEM AMD DLL] AMF drain QueryOutput failed: "
                      << queryResult << std::endl;
            return 0;
        }
        if (std::chrono::duration<double>(
                std::chrono::steady_clock::now() - drainStart).count() > 30.0) {
            std::cerr << "[TELEM AMD DLL] AMF drain timeout before AMF_EOF." << std::endl;
            return 0;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
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
    if (ctx->pDecodedCopyTex) ctx->pDecodedCopyTex->Release();
    if (ctx->pPendingDecodedTex) ctx->pPendingDecodedTex->Release();
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

TELEM_EXPORT void telem_amd_get_extended_stats(
    void* handle,
    UINT64* out_hud_updates,
    UINT64* out_video_updates,
    UINT64* out_input_full,
    UINT64* out_retries,
    UINT64* out_dropped,
    UINT64* out_ignored
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_hud_updates) *out_hud_updates = ctx->hudUpdates;
    if (out_video_updates) *out_video_updates = ctx->videoUpdates;
    if (out_input_full) *out_input_full = ctx->amfInputFullCount;
    if (out_retries) *out_retries = ctx->amfRetryCount;
    if (out_dropped) *out_dropped = ctx->amfDroppedSubmissions;
    if (out_ignored) *out_ignored = ctx->amfIgnoredSubmissions;
}

TELEM_EXPORT void telem_amd_get_etap1_stats(
    void* handle,
    UINT64* out_blend_calls,
    UINT64* out_gpu_profiled_frames
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_blend_calls) *out_blend_calls = ctx->blendCalls;
    if (out_gpu_profiled_frames) *out_gpu_profiled_frames = ctx->gpuProfiledFrames;
}

TELEM_EXPORT void telem_amd_get_etap2_stats(
    void* handle,
    UINT64* out_gpu_hud_frames,
    UINT64* out_hud_texture_creates,
    UINT64* out_hud_texture_uploads,
    int* out_hud_mode
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_gpu_hud_frames) *out_gpu_hud_frames = ctx->gpuHUDFrames;
    if (out_hud_texture_creates) *out_hud_texture_creates = ctx->hudTextureCreates;
    if (out_hud_texture_uploads) *out_hud_texture_uploads = ctx->hudTextureUploads;
    if (out_hud_mode) *out_hud_mode = ctx->hudMode;
}

TELEM_EXPORT void telem_amd_get_etap3_stats(
    void* handle,
    UINT64* out_hud_uploaded_bytes,
    UINT64* out_hud_uploaded_rects
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    if (out_hud_uploaded_bytes) *out_hud_uploaded_bytes = ctx->hudUploadedBytes;
    if (out_hud_uploaded_rects) *out_hud_uploaded_rects = ctx->hudUploadedRects;
}

TELEM_EXPORT void telem_amd_get_etap4_stats(
    void* handle,
    UINT64* out_read_calls,
    UINT64* out_video_samples,
    UINT64* out_stream_ticks,
    UINT64* out_null_samples,
    UINT64* out_d3d11_surfaces,
    UINT64* out_format_changes,
    UINT64* out_eos_events,
    UINT64* out_direct_surface_frames,
    UINT64* out_gpu_copy_frames,
    int* out_decode_mode,
    int* out_hardware_confirmed,
    UINT* out_decoder_format
) {
    if (!handle) return;
    TelemAMDContext* ctx = static_cast<TelemAMDContext*>(handle);
    if (out_read_calls) *out_read_calls = ctx->mfReadSampleCalls;
    if (out_video_samples) *out_video_samples = ctx->mfVideoSamples;
    if (out_stream_ticks) *out_stream_ticks = ctx->mfStreamTicks;
    if (out_null_samples) *out_null_samples = ctx->mfNullSamples;
    if (out_d3d11_surfaces) *out_d3d11_surfaces = ctx->mfD3D11Surfaces;
    if (out_format_changes) *out_format_changes = ctx->mfFormatChanges;
    if (out_eos_events) *out_eos_events = ctx->mfEndOfStreamEvents;
    if (out_direct_surface_frames) *out_direct_surface_frames = ctx->directDecoderSurfaceFrames;
    if (out_gpu_copy_frames) *out_gpu_copy_frames = ctx->decoderGpuCopyFrames;
    if (out_decode_mode) *out_decode_mode = ctx->decodeMode;
    if (out_hardware_confirmed) *out_hardware_confirmed = ctx->mfHardwareConfirmed ? 1 : 0;
    if (out_decoder_format) *out_decoder_format = static_cast<UINT>(ctx->decoderOutputFormat);
}

TELEM_EXPORT void telem_amd_get_last_frame_timings(
    void* handle,
    double* out_mf_read_sample_ms,
    double* out_mf_surface_acquire_ms,
    double* out_base_gpu_copy_ms,
    double* out_hud_native_copy_ms,
    double* out_hud_upload_ms,
    double* out_staging_memcpy_ms,
    double* out_blend_ms,
    double* out_copy_submit_ms,
    double* out_vp_cpu_submit_ms,
    double* out_vp_gpu_completion_ms,
    double* out_gpu_wait_ms,
    double* out_amf_submit_ms,
    double* out_amf_query_ms,
    double* out_packet_write_ms
) {
    if (!handle) return;
    TelemAMDContext* ctx = (TelemAMDContext*)handle;
    const TelemAMDFrameTimings& t = ctx->lastTimings;
    if (out_mf_read_sample_ms) *out_mf_read_sample_ms = t.mfReadSampleMs;
    if (out_mf_surface_acquire_ms) *out_mf_surface_acquire_ms = t.mfSurfaceAcquireMs;
    if (out_base_gpu_copy_ms) *out_base_gpu_copy_ms = t.baseGpuCopyMs;
    if (out_hud_native_copy_ms) *out_hud_native_copy_ms = t.hudNativeCopyMs;
    if (out_hud_upload_ms) *out_hud_upload_ms = t.hudUploadMs;
    if (out_staging_memcpy_ms) *out_staging_memcpy_ms = t.stagingMemcpyMs;
    if (out_blend_ms) *out_blend_ms = t.blendMs;
    if (out_copy_submit_ms) *out_copy_submit_ms = t.copySubmitMs;
    if (out_vp_cpu_submit_ms) *out_vp_cpu_submit_ms = t.vpCpuSubmitMs;
    if (out_vp_gpu_completion_ms) *out_vp_gpu_completion_ms = t.vpGpuCompletionMs;
    if (out_gpu_wait_ms) *out_gpu_wait_ms = t.gpuWaitMs;
    if (out_amf_submit_ms) *out_amf_submit_ms = t.amfSubmitMs;
    if (out_amf_query_ms) *out_amf_query_ms = t.amfQueryMs;
    if (out_packet_write_ms) *out_packet_write_ms = t.packetWriteMs;
}
