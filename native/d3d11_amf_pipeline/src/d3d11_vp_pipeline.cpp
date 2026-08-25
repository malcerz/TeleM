#include "d3d11_vp_pipeline.h"
#include <d3dcompiler.h>
#include "stb_image_write.h"
#include <fstream>

static std::vector<uint8_t> ConvertNV12ToRGBA_VP(const uint8_t* yData, const uint8_t* uvData, UINT w, UINT h, UINT yPitch, UINT uvPitch) {
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

static bool DumpNV12TextureToFile(ID3D11Device* pDevice, ID3D11DeviceContext* pContext, ID3D11Texture2D* pTex, const char* outPath) {
    if (!pDevice || !pContext || !pTex || !outPath) return false;
    D3D11_TEXTURE2D_DESC desc = {};
    pTex->GetDesc(&desc);

    D3D11_TEXTURE2D_DESC readDesc = desc;
    readDesc.Usage = D3D11_USAGE_STAGING;
    readDesc.BindFlags = 0;
    readDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    readDesc.MiscFlags = 0;

    ID3D11Texture2D* pStaging = nullptr;
    HRESULT hr = pDevice->CreateTexture2D(&readDesc, nullptr, &pStaging);
    if (FAILED(hr) || !pStaging) return false;

    pContext->CopyResource(pStaging, pTex);

    D3D11_MAPPED_SUBRESOURCE mapY = {}, mapUV = {};
    HRESULT hrY = pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &mapY);
    HRESULT hrUV = pContext->Map(pStaging, 1, D3D11_MAP_READ, 0, &mapUV);

    if (SUCCEEDED(hrY)) {
        const uint8_t* yPlane = (const uint8_t*)mapY.pData;
        const uint8_t* uvPlane = SUCCEEDED(hrUV) ? (const uint8_t*)mapUV.pData : (yPlane + (mapY.RowPitch * desc.Height));
        UINT yPitch = mapY.RowPitch;
        UINT uvPitch = SUCCEEDED(hrUV) ? mapUV.RowPitch : mapY.RowPitch;

        std::vector<uint8_t> rgba = ConvertNV12ToRGBA_VP(yPlane, uvPlane, desc.Width, desc.Height, yPitch, uvPitch);
        stbi_write_png(outPath, desc.Width, desc.Height, 4, rgba.data(), desc.Width * 4);

        pContext->Unmap(pStaging, 0);
        if (SUCCEEDED(hrUV)) pContext->Unmap(pStaging, 1);
        std::cout << "[VP] Dumped checkpoint to " << outPath << std::endl;
    }
    pStaging->Release();
    return true;
}

static bool DumpNV12RawToFile(ID3D11Device* pDevice, ID3D11DeviceContext* pContext, ID3D11Texture2D* pTex, const char* outPath) {
    if (!pDevice || !pContext || !pTex || !outPath) return false;
    D3D11_TEXTURE2D_DESC desc = {};
    pTex->GetDesc(&desc);

    D3D11_TEXTURE2D_DESC readDesc = desc;
    readDesc.Usage = D3D11_USAGE_STAGING;
    readDesc.BindFlags = 0;
    readDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    readDesc.MiscFlags = 0;

    ID3D11Texture2D* pStaging = nullptr;
    HRESULT hr = pDevice->CreateTexture2D(&readDesc, nullptr, &pStaging);
    if (FAILED(hr) || !pStaging) return false;

    pContext->CopyResource(pStaging, pTex);

    D3D11_MAPPED_SUBRESOURCE mapY = {};
    HRESULT hrY = pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &mapY);

    if (SUCCEEDED(hrY)) {
        std::ofstream ofs(outPath, std::ios::binary);
        if (ofs) {
            const uint8_t* yPlane = (const uint8_t*)mapY.pData;
            for (UINT r = 0; r < desc.Height; ++r) {
                ofs.write((const char*)(yPlane + r * mapY.RowPitch), desc.Width);
            }
            const uint8_t* uvPlane = yPlane + (mapY.RowPitch * desc.Height);
            for (UINT r = 0; r < desc.Height / 2; ++r) {
                ofs.write((const char*)(uvPlane + r * mapY.RowPitch), desc.Width);
            }
        }
        pContext->Unmap(pStaging, 0);
    }
    pStaging->Release();
    return true;
}

static int GetFusedCompositorMode() {
    const char* env = getenv("AMD_FUSED_COMPOSITOR");
    return env ? atoi(env) : 1; // ETAP 8K Production Default: 1 (Fused Single-Range Compositor active)
}

static int GetNormalizePassCount() {
    const int fusedMode = GetFusedCompositorMode();
    if (fusedMode == 1) {
        return 0; // Production fused path: 0 Normalize dispatches
    }
    const char* env = getenv("AMD_NORMALIZE_PASSES");
    return env ? atoi(env) : 1; // Diagnostic legacy override default: 1 pass (ONE_PASS_REFERENCE)
}


// Diagnostic: dump a R8G8B8A8_UNORM DEFAULT texture to a PNG (with proper
// staging copy + sync).  Used to inspect the GPU-resampled map texture.
static bool DumpRGBATextureToFile(ID3D11Device* pDevice, ID3D11DeviceContext* pContext, ID3D11Texture2D* pTex, const char* outPath) {
    if (!pDevice || !pContext || !pTex || !outPath) return false;
    D3D11_TEXTURE2D_DESC desc = {};
    pTex->GetDesc(&desc);
    D3D11_TEXTURE2D_DESC readDesc = desc;
    readDesc.Usage = D3D11_USAGE_STAGING;
    readDesc.BindFlags = 0;
    readDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    readDesc.MiscFlags = 0;
    ID3D11Texture2D* pStaging = nullptr;
    if (FAILED(pDevice->CreateTexture2D(&readDesc, nullptr, &pStaging))) return false;
    pContext->CopyResource(pStaging, pTex);
    D3D11_MAPPED_SUBRESOURCE mapped = {};
    if (SUCCEEDED(pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &mapped))) {
        std::vector<uint8_t> rgba(static_cast<size_t>(desc.Width) * desc.Height * 4);
        const uint8_t* src = static_cast<const uint8_t*>(mapped.pData);
        for (UINT y = 0; y < desc.Height; ++y) {
            memcpy(rgba.data() + static_cast<size_t>(y) * desc.Width * 4,
                   src + static_cast<size_t>(y) * mapped.RowPitch, desc.Width * 4);
        }
        pContext->Unmap(pStaging, 0);
        stbi_write_png(outPath, desc.Width, desc.Height, 4, rgba.data(), desc.Width * 4);
        std::cout << "[MAP] dumped resample texture to " << outPath << std::endl;
    }
    pStaging->Release();
    return true;
}

static ID3D11ComputeShader* g_pCSHUD = nullptr;

static bool InitHUDComputeShader(ID3D11Device* pDevice) {
    if (g_pCSHUD) return true;

    const char* csSrc = R"(
        Texture2D<float4> HudTexture : register(t0);
        RWTexture2D<float> OutputY : register(u0);
        RWTexture2D<float2> OutputUV : register(u1);

        [numthreads(16, 16, 1)]
        void CSMain(uint3 dispatchId : SV_DispatchThreadID) {
            uint2 pos = dispatchId.xy;
            float4 hud = HudTexture[pos];
            float a = hud.a;
            if (a <= 0.001f) return;

            float r = hud.r;
            float g = hud.g;
            float b = hud.b;

            float yHud = 16.0f / 255.0f + (66.0f * r + 129.0f * g + 25.0f * b) / 255.0f;
            float uHud = 128.0f / 255.0f + (-38.0f * r - 74.0f * g + 112.0f * b) / 255.0f;
            float vHud = 128.0f / 255.0f + (112.0f * r - 94.0f * g - 18.0f * b) / 255.0f;

            float yOrig = OutputY[pos];
            OutputY[pos] = lerp(yOrig, yHud, a);

            if ((pos.x % 2 == 0) && (pos.y % 2 == 0)) {
                uint2 uvPos = pos / 2;
                float2 uvOrig = OutputUV[uvPos];
                OutputUV[uvPos] = lerp(uvOrig, float2(uHud, vHud), a);
            }
        }
    )";

    ID3DBlob* pBlob = nullptr;
    ID3DBlob* pError = nullptr;
    HRESULT hr = D3DCompile(csSrc, strlen(csSrc), nullptr, nullptr, nullptr, "CSMain", "cs_5_0", 0, 0, &pBlob, &pError);
    if (FAILED(hr)) {
        if (pError) {
            std::cerr << "[CS] Shader compile error: " << (char*)pError->GetBufferPointer() << std::endl;
            pError->Release();
        }
        return false;
    }

    hr = pDevice->CreateComputeShader(pBlob->GetBufferPointer(), pBlob->GetBufferSize(), nullptr, &g_pCSHUD);
    pBlob->Release();
    return SUCCEEDED(hr);
}

D3D11VideoProcessorPipeline::D3D11VideoProcessorPipeline() {}

void D3D11VideoProcessorPipeline::SetPoolSize(UINT n) {
    if (n < 4) n = 4;
    if (n > 8) n = 8;
    m_poolSize = n;
    m_outputYViews.resize(n, nullptr);
    m_outputUVViews.resize(n, nullptr);
    m_outputPool.resize(n, nullptr);
    m_outputViewPool.resize(n, nullptr);
    m_slotLastFrame.assign(n, 0);
}

D3D11VideoProcessorPipeline::~D3D11VideoProcessorPipeline() {
    for (UINT i = 0; i < (UINT)m_outputYViews.size(); ++i) {
        if (m_outputYViews[i]) { m_outputYViews[i]->Release(); m_poolViewsReleased++; }
        if (m_outputUVViews[i]) { m_outputUVViews[i]->Release(); m_poolViewsReleased++; }
    }
    if (m_nv12RangeComputeShader) m_nv12RangeComputeShader->Release();
    if (m_nv12HUDComputeShader) m_nv12HUDComputeShader->Release();
    if (m_nv12FusedComputeShader) m_nv12FusedComputeShader->Release();
    if (m_device3) m_device3->Release();
    ReleaseMapResources();
    ReleaseChartResources();
    ReleaseGaugeResources();
    if (m_hudShaderView) m_hudShaderView->Release();
    if (m_hudInputView) m_hudInputView->Release();
    if (m_hudTexture) m_hudTexture->Release();

    for (UINT i = 0; i < (UINT)m_outputViewPool.size(); ++i) {
        if (m_outputViewPool[i]) { m_outputViewPool[i]->Release(); m_poolViewsReleased++; }
        if (m_outputPool[i]) { m_outputPool[i]->Release(); m_poolTexturesReleased++; }
    }

    if (m_disjointQuery) m_disjointQuery->Release();
    if (m_startQuery) m_startQuery->Release();
    if (m_endQuery) m_endQuery->Release();
    ReleaseGPUTimestampRing();

    if (m_videoProcessor) m_videoProcessor->Release();
    if (m_videoEnumerator) m_videoEnumerator->Release();
    if (m_videoContext) m_videoContext->Release();
    if (m_videoDevice) m_videoDevice->Release();

    // ETAP 5W — release the device/context references taken in Initialize().
    // Initialize ALWAYS AddRefs m_device/m_context (both for a borrowed device
    // and for one it created itself), so the destructor must Release them
    // unconditionally.  The previous `if (m_ownsDevice)` guard leaked +1 device
    // and +1 context reference per context when the device was borrowed, which
    // kept the D3D11 device alive forever and leaked driver-side kernel objects
    // (events/mutants/threads/sections) on every create/close cycle.
    if (m_context) m_context->Release();
    if (m_device) m_device->Release();

    // ETAP 5V — debug-only pool lifecycle summary (AMD_POOL_LIFECYCLE_STATS=1).
    if (m_poolLifecycleStats) {
        std::cout << "[VP POOL] lifecycle: textures created=" << m_poolTexturesCreated
                  << " released=" << m_poolTexturesReleased
                  << " live=" << (m_poolTexturesCreated - m_poolTexturesReleased)
                  << " | views created=" << m_poolViewsCreated
                  << " released=" << m_poolViewsReleased
                  << " live=" << (m_poolViewsCreated - m_poolViewsReleased)
                  << std::endl;
    }
}

// ── ETAP 5T: asynchronous GPU timestamp query ring ───────────────────────
// Persistent D3D11_QUERY_TIMESTAMP ring.  Queries are ENDed into the command
// stream at each GPU-pass boundary; results are READ with a fixed delay
// (GPU_TS_READ_DELAY frames) using D3D11_ASYNC_GETDATA_DONOTFLUSH — never a
// blocking GetData, never a spin.  One status check per query per frame.
bool D3D11VideoProcessorPipeline::InitGPUTimestampRing() {
    if (m_gpuTsInitialized) return true;
    if (!m_device) return false;
    D3D11_QUERY_DESC tsDesc = {};
    tsDesc.Query = D3D11_QUERY_TIMESTAMP;
    D3D11_QUERY_DESC djDesc = {};
    djDesc.Query = D3D11_QUERY_TIMESTAMP_DISJOINT;
    for (int s = 0; s < GPU_TS_RING; ++s) {
        if (FAILED(m_device->CreateQuery(&djDesc, &m_tsDisjoint[s]))) {
            ReleaseGPUTimestampRing();
            return false;
        }
        for (int q = 0; q < GPU_TS_NUM_QUERIES; ++q) {
            if (FAILED(m_device->CreateQuery(&tsDesc, &m_tsQueries[s][q]))) {
                ReleaseGPUTimestampRing();
                return false;
            }
        }
    }
    m_gpuTimeline.clear();
    m_gpuTsNextRead = 0;
    m_gpuTsGetDataCalls = 0;
    m_gpuTsGetDataNotReady = 0;
    m_gpuTsInitialized = true;
    std::cout << "[VP] GPU timestamp ring: " << GPU_TS_RING << " slots x "
              << (GPU_TS_NUM_QUERIES + 1) << " queries (read delay "
              << GPU_TS_READ_DELAY << " frames)" << std::endl;
    return true;
}

void D3D11VideoProcessorPipeline::ReleaseGPUTimestampRing() {
    if (!m_gpuTsInitialized) return;
    for (int s = 0; s < GPU_TS_RING; ++s) {
        if (m_tsDisjoint[s]) { m_tsDisjoint[s]->Release(); m_tsDisjoint[s] = nullptr; }
        for (int q = 0; q < GPU_TS_NUM_QUERIES; ++q) {
            if (m_tsQueries[s][q]) { m_tsQueries[s][q]->Release(); m_tsQueries[s][q] = nullptr; }
        }
    }
    m_gpuTsInitialized = false;
}

void D3D11VideoProcessorPipeline::SetGpuTimestampProfile(bool enabled) {
    m_gpuTsEnabled = enabled;
    if (enabled && !m_gpuTsInitialized) {
        if (!InitGPUTimestampRing()) {
            std::cerr << "[VP] GPU timestamp ring init FAILED; profiling disabled."
                      << std::endl;
            m_gpuTsEnabled = false;
        }
    }
}

void D3D11VideoProcessorPipeline::ReadFrameTimestamps(UINT frameIndex) {
    // FIFO: read the oldest unread frame once it is at least READ_DELAY behind.
    while (m_gpuTsNextRead + (UINT64)GPU_TS_READ_DELAY <= (UINT64)frameIndex) {
        UINT64 R = m_gpuTsNextRead;
        UINT slot = (UINT)(R % (UINT64)GPU_TS_RING);
        D3D11_QUERY_DATA_TIMESTAMP_DISJOINT dj = {};
        UINT64 ts[GPU_TS_NUM_QUERIES] = { 0 };
        bool ready = true;
        m_gpuTsGetDataCalls++;
        if (m_context->GetData(m_tsDisjoint[slot], &dj, sizeof(dj),
                               D3D11_ASYNC_GETDATA_DONOTFLUSH) != S_OK) ready = false;
        for (int i = 0; i < GPU_TS_NUM_QUERIES && ready; ++i) {
            m_gpuTsGetDataCalls++;
            if (m_context->GetData(m_tsQueries[slot][i], &ts[i], sizeof(ts[i]),
                                   D3D11_ASYNC_GETDATA_DONOTFLUSH) != S_OK) {
                m_gpuTsGetDataNotReady++;
                ready = false;
            }
        }
        // Safety: the slot is about to be overwritten -> force-advance.
        const bool force = ((UINT64)frameIndex - R >= (UINT64)GPU_TS_RING - 1);
        if (!ready && !force) break;  // try again next frame (no spin)

        GPUFrameTimeline rec;
        rec.frame = R;
        rec.ready = ready && !dj.Disjoint;
        rec.disjoint = dj.Disjoint;
        rec.freq = (dj.Frequency > 0) ? (double)dj.Frequency : 1.0;
        if (ready) {
            rec.beginTs = ts[0]; rec.bltTs = ts[1]; rec.rangeTs = ts[2];
            rec.chartsTs = ts[3]; rec.gaugeTs = ts[4]; rec.mapTs = ts[5];
            rec.hudTs = ts[6]; rec.endTs = ts[7];
        }
        rec.readLatency = (UINT)((UINT64)frameIndex - R);
        m_gpuTimeline.push_back(rec);
        m_gpuTsNextRead++;
    }
}

bool D3D11VideoProcessorPipeline::Initialize(ID3D11Device* pDevice, ID3D11DeviceContext* pContext, UINT width, UINT height) {
    m_width = width;
    m_height = height;

    if (pDevice && pContext) {
        m_device = pDevice;
        m_context = pContext;
        m_device->AddRef();
        m_context->AddRef();
        m_ownsDevice = false;
    } else {
        UINT createDeviceFlags = D3D11_CREATE_DEVICE_VIDEO_SUPPORT;
        D3D_FEATURE_LEVEL featureLevels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
        D3D_FEATURE_LEVEL featureLevel;

        HRESULT hr = D3D11CreateDevice(
            nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
            createDeviceFlags, featureLevels, 2,
            D3D11_SDK_VERSION, &m_device, &featureLevel, &m_context
        );
        if (FAILED(hr)) {
            std::cerr << "[VP] D3D11CreateDevice failed: 0x" << std::hex << hr << std::dec << std::endl;
            return false;
        }
        m_ownsDevice = true;
    }

    HRESULT hr = m_device->QueryInterface(__uuidof(ID3D11VideoDevice), (void**)&m_videoDevice);
    if (FAILED(hr)) {
        std::cerr << "[VP] Failed to query ID3D11VideoDevice interface!" << std::endl;
        return false;
    }

    hr = m_context->QueryInterface(__uuidof(ID3D11VideoContext), (void**)&m_videoContext);
    if (FAILED(hr)) {
        std::cerr << "[VP] Failed to query ID3D11VideoContext interface!" << std::endl;
        return false;
    }

    // Profiling queries
    D3D11_QUERY_DESC qd = {};
    qd.Query = D3D11_QUERY_TIMESTAMP_DISJOINT;
    m_device->CreateQuery(&qd, &m_disjointQuery);
    qd.Query = D3D11_QUERY_TIMESTAMP;
    m_device->CreateQuery(&qd, &m_startQuery);
    m_device->CreateQuery(&qd, &m_endQuery);

    return true;
}

bool D3D11VideoProcessorPipeline::SetupVideoProcessor(DXGI_FORMAT inputFormat, DXGI_FORMAT outputFormat) {
    D3D11_VIDEO_PROCESSOR_CONTENT_DESC contentDesc = {};
    contentDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    contentDesc.InputFrameRate.Numerator = 30000;
    contentDesc.InputFrameRate.Denominator = 1001;
    contentDesc.InputWidth = (m_width > 3840u) ? m_width : 3840u;
    contentDesc.InputHeight = (m_height > 2160u) ? m_height : 2160u;
    contentDesc.OutputFrameRate.Numerator = 30000;
    contentDesc.OutputFrameRate.Denominator = 1001;
    contentDesc.OutputWidth = m_width;
    contentDesc.OutputHeight = m_height;
    contentDesc.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

    HRESULT hr = m_videoDevice->CreateVideoProcessorEnumerator(&contentDesc, &m_videoEnumerator);
    if (FAILED(hr)) {
        std::cerr << "[VP] CreateVideoProcessorEnumerator failed: 0x" << std::hex << hr << std::dec << std::endl;
        return false;
    }

    UINT flags = 0;
    hr = m_videoEnumerator->CheckVideoProcessorFormat(outputFormat, &flags);
    if (FAILED(hr) || !(flags & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_OUTPUT)) {
        std::cerr << "[VP] Output format not supported by VideoProcessor!" << std::endl;
        return false;
    }

    D3D11_VIDEO_PROCESSOR_CAPS caps = {};
    if (SUCCEEDED(m_videoEnumerator->GetVideoProcessorCaps(&caps))) {
        std::cout << "[VP CAPS] MaxInputStreams: " << caps.MaxInputStreams << " MaxStreamStates: " << caps.MaxStreamStates << " FeatureCaps: 0x" << std::hex << caps.FeatureCaps << std::dec << std::endl;
    }

    UINT inFlagsNV12 = 0, inFlagsBGRA = 0, inFlagsRGBA = 0;
    m_videoEnumerator->CheckVideoProcessorFormat(DXGI_FORMAT_NV12, &inFlagsNV12);
    m_videoEnumerator->CheckVideoProcessorFormat(DXGI_FORMAT_B8G8R8A8_UNORM, &inFlagsBGRA);
    m_videoEnumerator->CheckVideoProcessorFormat(DXGI_FORMAT_R8G8B8A8_UNORM, &inFlagsRGBA);
    std::cout << "[VP FORMATS] NV12 In: " << ((inFlagsNV12 & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT) ? "YES" : "NO")
              << " BGRA In: " << ((inFlagsBGRA & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT) ? "YES" : "NO")
              << " RGBA In: " << ((inFlagsRGBA & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT) ? "YES" : "NO") << std::endl;

    hr = m_videoDevice->CreateVideoProcessor(m_videoEnumerator, 0, &m_videoProcessor);
    if (FAILED(hr)) {
        std::cerr << "[VP] CreateVideoProcessor failed: 0x" << std::hex << hr << std::dec << std::endl;
        return false;
    }

    // Set Color Spaces
    const char* envCsMode = getenv("AMD_VP_COLORSPACE_MODE");
    int csMode = envCsMode ? atoi(envCsMode) : 0; // Safe production default: Mode 0 (legacy VP flags)

    if (csMode == 2 || csMode == 3) {
        ID3D11VideoContext1* videoContext1 = nullptr;
        HRESULT hrVc1 = m_videoContext->QueryInterface(
            __uuidof(ID3D11VideoContext1), reinterpret_cast<void**>(&videoContext1));
        if (SUCCEEDED(hrVc1) && videoContext1) {
            DXGI_COLOR_SPACE_TYPE inSpace = (csMode == 3)
                ? DXGI_COLOR_SPACE_YCBCR_FULL_G22_LEFT_P2020
                : DXGI_COLOR_SPACE_YCBCR_FULL_G22_LEFT_P709;
            DXGI_COLOR_SPACE_TYPE outSpace = DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709;
            videoContext1->VideoProcessorSetStreamColorSpace1(m_videoProcessor, 0, inSpace);
            videoContext1->VideoProcessorSetStreamColorSpace1(m_videoProcessor, 1, DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709);
            videoContext1->VideoProcessorSetOutputColorSpace1(m_videoProcessor, outSpace);
            videoContext1->Release();
            std::cout << "[VP COLORSPACE1] in=" << inSpace << " out=" << outSpace << std::endl;
        }
    } else {
        D3D11_VIDEO_PROCESSOR_COLOR_SPACE csIn = {};
        csIn.Usage = 0; // Playback
        csIn.RGB_Range = (csMode == 0) ? 1 : 0;
        csIn.YCbCr_Matrix = 1; // BT.709
        csIn.YCbCr_xvYCC = 0;
        csIn.Nominal_Range = (csMode == 1) ? D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_0_255 : 0;
        m_videoContext->VideoProcessorSetStreamColorSpace(m_videoProcessor, 0, &csIn);

        D3D11_VIDEO_PROCESSOR_COLOR_SPACE csHUD = {};
        csHUD.Usage = 0; // Playback
        csHUD.RGB_Range = 0; // Full range 0-255 RGB
        csHUD.YCbCr_Matrix = 0;
        csHUD.YCbCr_xvYCC = 0;
        m_videoContext->VideoProcessorSetStreamColorSpace(m_videoProcessor, 1, &csHUD);

        D3D11_VIDEO_PROCESSOR_COLOR_SPACE csOut = {};
        csOut.Usage = 0;
        csOut.RGB_Range = 1; // Studio
        csOut.YCbCr_Matrix = 1; // BT.709
        csOut.Nominal_Range = (csMode == 1) ? D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_16_235 : 0;
        m_videoContext->VideoProcessorSetOutputColorSpace(m_videoProcessor, &csOut);
        std::cout << "[VP COLORSPACE] mode=" << csMode << " inNominal=" << csIn.Nominal_Range << " outNominal=" << csOut.Nominal_Range << std::endl;
    }

    // Create Persistent Output Texture Pool (DXGI_FORMAT_NV12)
    D3D11_TEXTURE2D_DESC texDesc = {};
    // ETAP 5U — defensively size the output surface pool (SetPoolSize may not
    // have been called; default 4).
    if (m_outputPool.size() != m_poolSize) {
        m_outputPool.resize(m_poolSize, nullptr);
        m_outputViewPool.resize(m_poolSize, nullptr);
        m_outputYViews.resize(m_poolSize, nullptr);
        m_outputUVViews.resize(m_poolSize, nullptr);
        m_slotLastFrame.assign(m_poolSize, 0);
    }

    texDesc.Width = m_width;
    texDesc.Height = m_height;
    texDesc.MipLevels = 1;
    texDesc.ArraySize = 1;
    texDesc.Format = outputFormat;
    texDesc.SampleDesc.Count = 1;
    texDesc.Usage = D3D11_USAGE_DEFAULT;
    texDesc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
    texDesc.MiscFlags = D3D11_RESOURCE_MISC_SHARED;

    D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC outViewDesc = {};
    outViewDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
    outViewDesc.Texture2D.MipSlice = 0;

    // ETAP 5V — pool size with a safe fallback (requested -> 6 -> 4) on
    // allocation / resource-creation failure ONLY.  Nothing else is masked.
    const UINT requestedPool = m_poolSize;
    const UINT kPoolCandidates[3] = { 8, 6, 4 };
    bool poolCreated = false;
    for (UINT ci = 0; ci < 3; ++ci) {
        const UINT cand = kPoolCandidates[ci];
        if (cand > requestedPool) continue;
        if (cand < requestedPool) {
            std::cout << "[VP POOL] requested pool " << requestedPool
                      << " -> fallback to " << cand
                      << " (allocation/resource creation only)" << std::endl;
        }
        // Release any partial pool from a previous (failed) attempt.
        for (UINT i = 0; i < (UINT)m_outputPool.size(); ++i) {
            if (m_outputViewPool[i]) {
                m_outputViewPool[i]->Release();
                m_outputViewPool[i] = nullptr;
                m_poolViewsReleased++;
            }
            if (m_outputPool[i]) {
                m_outputPool[i]->Release();
                m_outputPool[i] = nullptr;
                m_poolTexturesReleased++;
            }
        }
        m_poolSize = cand;
        m_outputPool.resize(cand, nullptr);
        m_outputViewPool.resize(cand, nullptr);
        m_outputYViews.resize(cand, nullptr);
        m_outputUVViews.resize(cand, nullptr);
        m_slotLastFrame.assign(cand, 0);
        bool attemptOk = true;
        for (UINT i = 0; i < cand; ++i) {
            hr = m_device->CreateTexture2D(&texDesc, nullptr, &m_outputPool[i]);
            if (FAILED(hr)) { attemptOk = false; break; }
            m_poolTexturesCreated++;
            hr = m_videoDevice->CreateVideoProcessorOutputView(
                m_outputPool[i], m_videoEnumerator, &outViewDesc, &m_outputViewPool[i]);
            if (FAILED(hr)) { attemptOk = false; break; }
            m_poolViewsCreated++;
        }
        if (attemptOk) { poolCreated = true; break; }
        std::cerr << "[VP] Failed to create output NV12 texture pool size " << cand
                  << ": 0x" << std::hex << hr << std::dec << std::endl;
    }
    if (!poolCreated) {
        std::cerr << "[VP] Failed to create output NV12 texture pool (tried "
                  << requestedPool << "/6/4)" << std::endl;
        return false;
    }
    if (m_poolSize != requestedPool) {
        std::cout << "[VP POOL] effective pool size = " << m_poolSize
                  << " (requested " << requestedPool << ")" << std::endl;
    }

    if (!InitializeNV12ComputeCompositor()) {
        std::cerr << "[VP] Direct NV12 compute HUD compositor initialization failed." << std::endl;
        return false;
    }

    return true;
}

bool D3D11VideoProcessorPipeline::InitializeNV12ComputeCompositor() {
    HRESULT hr = m_device->QueryInterface(__uuidof(ID3D11Device3), (void**)&m_device3);
    if (FAILED(hr) || !m_device3) return false;

    for (UINT i = 0; i < m_poolSize; ++i) {
        D3D11_UNORDERED_ACCESS_VIEW_DESC1 yDesc = {};
        yDesc.Format = DXGI_FORMAT_R8_UNORM;
        yDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
        yDesc.Texture2D.MipSlice = 0;
        yDesc.Texture2D.PlaneSlice = 0;
        ID3D11UnorderedAccessView1* yView = nullptr;
        hr = m_device3->CreateUnorderedAccessView1(m_outputPool[i], &yDesc, &yView);
        if (FAILED(hr) || !yView) return false;
        m_outputYViews[i] = yView;
        m_poolViewsCreated++;

        D3D11_UNORDERED_ACCESS_VIEW_DESC1 uvDesc = {};
        uvDesc.Format = DXGI_FORMAT_R8G8_UNORM;
        uvDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
        uvDesc.Texture2D.MipSlice = 0;
        uvDesc.Texture2D.PlaneSlice = 1;
        ID3D11UnorderedAccessView1* uvView = nullptr;
        hr = m_device3->CreateUnorderedAccessView1(m_outputPool[i], &uvDesc, &uvView);
        if (FAILED(hr) || !uvView) return false;
        m_outputUVViews[i] = uvView;
        m_poolViewsCreated++;
    }

    const char* computeSource = R"(
        Texture2D<float4> HUDTexture : register(t0);
        RWTexture2D<float> OutputY : register(u0);
        RWTexture2D<float2> OutputUV : register(u1);

        [numthreads(16, 16, 1)]
        void CSMain(uint3 threadId : SV_DispatchThreadID) {
            uint width, height;
            HUDTexture.GetDimensions(width, height);
            uint2 pos = threadId.xy;
            if (pos.x >= width || pos.y >= height) return;

            uint4 hud = (uint4)round(saturate(HUDTexture.Load(int3(pos, 0))) * 255.0f);
            uint alpha = hud.a;
            if (alpha == 0) return;

            uint yHUD = ((66u * hud.r + 129u * hud.g + 25u * hud.b + 128u) >> 8) + 16u;
            uint yBase = (uint)round(saturate(OutputY[pos]) * 255.0f);
            uint yOut = alpha == 255u ? yHUD :
                (yHUD * alpha + yBase * (255u - alpha)) / 255u;
            OutputY[pos] = min(yOut, 255u) / 255.0f;

            if (((pos.x | pos.y) & 1u) == 0u) {
                int uHUD = ((-38 * (int)hud.r - 74 * (int)hud.g + 112 * (int)hud.b + 128) >> 8) + 128;
                int vHUD = ((112 * (int)hud.r - 94 * (int)hud.g - 18 * (int)hud.b + 128) >> 8) + 128;
                uint2 uvPos = pos / 2u;
                uint2 uvBase = (uint2)round(saturate(OutputUV[uvPos]) * 255.0f);
                uint uValue = (uint)clamp(uHUD, 0, 255);
                uint vValue = (uint)clamp(vHUD, 0, 255);
                uint2 uvOut = alpha == 255u ? uint2(uValue, vValue) :
                    (uint2(uValue, vValue) * alpha + uvBase * (255u - alpha)) / 255u;
                OutputUV[uvPos] = uvOut / 255.0f;
            }
        }
    )";

    ID3DBlob* shaderBlob = nullptr;
    ID3DBlob* errors = nullptr;
    hr = D3DCompile(computeSource, strlen(computeSource), nullptr, nullptr, nullptr,
                    "CSMain", "cs_5_0", 0, 0, &shaderBlob, &errors);
    if (FAILED(hr)) {
        if (errors) { std::cerr << (char*)errors->GetBufferPointer() << std::endl; errors->Release(); }
        return false;
    }
    hr = m_device->CreateComputeShader(
        shaderBlob->GetBufferPointer(), shaderBlob->GetBufferSize(), nullptr,
        &m_nv12HUDComputeShader);
    shaderBlob->Release();
    if (FAILED(hr)) return false;

    const char* rangeSource = R"(
        RWTexture2D<float> OutputY : register(u0);
        RWTexture2D<float2> OutputUV : register(u1);

        int ScaleChroma(int value) {
            int centered = value - 128;
            int scaled = centered >= 0
                ? (centered * 224 + 127) / 255
                : (centered * 224 - 127) / 255;
            return clamp(128 + scaled, 0, 255);
        }

        [numthreads(16, 16, 1)]
        void CSMain(uint3 threadId : SV_DispatchThreadID) {
            uint width, height;
            OutputY.GetDimensions(width, height);
            uint2 pos = threadId.xy;
            if (pos.x >= width || pos.y >= height) return;

            uint yValue = (uint)round(saturate(OutputY[pos]) * 255.0f);
            OutputY[pos] = min(235u, ((219u * yValue + 127u) / 255u) + 16u) / 255.0f;

            if (((pos.x | pos.y) & 1u) == 0u) {
                uint2 uvPos = pos / 2u;
                int2 uv = (int2)round(saturate(OutputUV[uvPos]) * 255.0f);
                OutputUV[uvPos] = float2(ScaleChroma(uv.x), ScaleChroma(uv.y)) / 255.0f;
            }
        }
    )";

    shaderBlob = nullptr;
    errors = nullptr;
    hr = D3DCompile(rangeSource, strlen(rangeSource), nullptr, nullptr, nullptr,
                    "CSMain", "cs_5_0", 0, 0, &shaderBlob, &errors);
    if (FAILED(hr)) {
        if (errors) { std::cerr << (char*)errors->GetBufferPointer() << std::endl; errors->Release(); }
        return false;
    }
    hr = m_device->CreateComputeShader(
        shaderBlob->GetBufferPointer(), shaderBlob->GetBufferSize(), nullptr,
        &m_nv12RangeComputeShader);
    shaderBlob->Release();
    if (FAILED(hr)) return false;

    // ETAP 8J: Fused Compute Shader — Unified Range Normalize + Direct HUD NV12 Compositor
    const char* fusedSource = R"(
        Texture2D<float4> HUDTexture : register(t0);
        RWTexture2D<float> OutputY : register(u0);
        RWTexture2D<float2> OutputUV : register(u1);

        int ScaleChroma(int value) {
            int centered = value - 128;
            int scaled = centered >= 0
                ? (centered * 224 + 127) / 255
                : (centered * 224 - 127) / 255;
            return clamp(128 + scaled, 0, 255);
        }

        [numthreads(16, 16, 1)]
        void CSMain(uint3 threadId : SV_DispatchThreadID) {
            uint width, height;
            HUDTexture.GetDimensions(width, height);
            uint2 pos = threadId.xy;
            if (pos.x >= width || pos.y >= height) return;

            // 1. Normalize Base Y (Full 0..255 -> Studio 16..235)
            uint yBaseFull = (uint)round(saturate(OutputY[pos]) * 255.0f);
            uint yBaseLimited = min(235u, ((219u * yBaseFull + 127u) / 255u) + 16u);

            // 2. Read HUD RGBA
            uint4 hud = (uint4)round(saturate(HUDTexture.Load(int3(pos, 0))) * 255.0f);
            uint alpha = hud.a;

            if (alpha == 0u) {
                OutputY[pos] = yBaseLimited / 255.0f;
            } else {
                uint yHUD = ((66u * hud.r + 129u * hud.g + 25u * hud.b + 128u) >> 8) + 16u;
                uint yOut = alpha == 255u ? yHUD :
                    (yHUD * alpha + yBaseLimited * (255u - alpha)) / 255u;
                OutputY[pos] = min(yOut, 255u) / 255.0f;
            }

            if (((pos.x | pos.y) & 1u) == 0u) {
                uint2 uvPos = pos / 2u;
                int2 uvBaseFull = (int2)round(saturate(OutputUV[uvPos]) * 255.0f);
                uint uBaseLimited = (uint)ScaleChroma(uvBaseFull.x);
                uint vBaseLimited = (uint)ScaleChroma(uvBaseFull.y);

                if (alpha == 0u) {
                    OutputUV[uvPos] = float2(uBaseLimited, vBaseLimited) / 255.0f;
                } else {
                    int uHUD = ((-38 * (int)hud.r - 74 * (int)hud.g + 112 * (int)hud.b + 128) >> 8) + 128;
                    int vHUD = ((112 * (int)hud.r - 94 * (int)hud.g - 18 * (int)hud.b + 128) >> 8) + 128;
                    uint uValue = (uint)clamp(uHUD, 0, 255);
                    uint vValue = (uint)clamp(vHUD, 0, 255);
                    uint2 uvOut = alpha == 255u ? uint2(uValue, vValue) :
                        (uint2(uValue, vValue) * alpha + uint2(uBaseLimited, vBaseLimited) * (255u - alpha)) / 255u;
                    OutputUV[uvPos] = uvOut / 255.0f;
                }
            }
        }
    )";

    shaderBlob = nullptr;
    errors = nullptr;
    hr = D3DCompile(fusedSource, strlen(fusedSource), nullptr, nullptr, nullptr,
                    "CSMain", "cs_5_0", 0, 0, &shaderBlob, &errors);
    if (FAILED(hr)) {
        if (errors) { std::cerr << (char*)errors->GetBufferPointer() << std::endl; errors->Release(); }
        return false;
    }
    hr = m_device->CreateComputeShader(
        shaderBlob->GetBufferPointer(), shaderBlob->GetBufferSize(), nullptr,
        &m_nv12FusedComputeShader);
    shaderBlob->Release();
    return SUCCEEDED(hr);
}

bool D3D11VideoProcessorPipeline::NormalizeD3D11VARangeNV12(UINT poolIndex) {
    if (!m_nv12RangeComputeShader ||
        !m_outputYViews[poolIndex] || !m_outputUVViews[poolIndex]) return false;

    const int passCount = GetNormalizePassCount();
    if (passCount <= 0) return true; // bypass

    ID3D11UnorderedAccessView* outputs[2] = {
        m_outputYViews[poolIndex], m_outputUVViews[poolIndex]
    };
    UINT initialCounts[2] = { 0, 0 };
    ID3D11UnorderedAccessView* nullOutputs[2] = { nullptr, nullptr };

    // The golden CPU path performs full->studio conversion once in FFmpeg and
    // once again when the uploaded NV12 is consumed by the legacy VP state.
    // Preserve that established output with two GPU-resident, quantized passes: for (UINT pass = 0; pass < 2; ++pass).
    for (UINT pass = 0; pass < (UINT)passCount; ++pass) {
        m_context->CSSetShader(m_nv12RangeComputeShader, nullptr, 0);
        m_context->CSSetUnorderedAccessViews(0, 2, outputs, initialCounts);
        m_context->Dispatch((m_width + 15) / 16, (m_height + 15) / 16, 1);
        m_context->CSSetUnorderedAccessViews(0, 2, nullOutputs, initialCounts);
    }
    return true;
}



bool D3D11VideoProcessorPipeline::ComposeHUDDirectNV12(
    ID3D11Texture2D* outputTexture,
    UINT poolIndex
) {
    if (!outputTexture || !m_hudShaderView ||
        !m_nv12HUDComputeShader || !m_outputYViews[poolIndex] || !m_outputUVViews[poolIndex]) {
        return false;
    }
    const int fusedMode = GetFusedCompositorMode();
    ID3D11ComputeShader* targetShader = (fusedMode == 1 && m_nv12FusedComputeShader)
        ? m_nv12FusedComputeShader : m_nv12HUDComputeShader;

    // VideoProcessor has already produced the normal base NV12 output. The
    // shader changes only pixels with non-zero Pillow straight alpha.
    m_context->CSSetShader(targetShader, nullptr, 0);
    m_context->CSSetShaderResources(0, 1, &m_hudShaderView);
    ID3D11UnorderedAccessView* outputs[2] = {
        m_outputYViews[poolIndex], m_outputUVViews[poolIndex]
    };
    UINT initialCounts[2] = { 0, 0 };
    m_context->CSSetUnorderedAccessViews(0, 2, outputs, initialCounts);
    m_context->Dispatch((m_width + 15) / 16, (m_height + 15) / 16, 1);

    ID3D11ShaderResourceView* nullInput = nullptr;
    ID3D11UnorderedAccessView* nullOutputs[2] = { nullptr, nullptr };
    m_context->CSSetShaderResources(0, 1, &nullInput);
    m_context->CSSetUnorderedAccessViews(0, 2, nullOutputs, initialCounts);
    return true;
}

bool D3D11VideoProcessorPipeline::UpdateHUDTexture(
    UINT width,
    UINT height,
    const uint8_t* rgbaData,
    UINT stride,
    const HUDDirtyRect* dirtyRects,
    UINT dirtyRectCount,
    bool fullUpload,
    size_t* uploadedBytes,
    bool* textureCreated
) {
    if (uploadedBytes) *uploadedBytes = 0;
    if (textureCreated) *textureCreated = false;
    if (!m_videoEnumerator || !rgbaData || stride < width * 4) return false;

    const bool needsTexture = !m_hudTexture || m_hudWidth != width || m_hudHeight != height;
    if (!needsTexture) {
        if (fullUpload) {
            m_context->UpdateSubresource(m_hudTexture, 0, nullptr, rgbaData, stride, 0);
            if (uploadedBytes) *uploadedBytes = static_cast<size_t>(width) * height * 4;
            return true;
        }
        size_t totalBytes = 0;
        for (UINT index = 0; index < dirtyRectCount; ++index) {
            const HUDDirtyRect& rect = dirtyRects[index];
            if (rect.width == 0 || rect.height == 0 || rect.x >= width || rect.y >= height) continue;
            const UINT right = (rect.width > width - rect.x) ? width : rect.x + rect.width;
            const UINT bottom = (rect.height > height - rect.y) ? height : rect.y + rect.height;
            D3D11_BOX box = {};
            box.left = rect.x;
            box.top = rect.y;
            box.front = 0;
            box.right = right;
            box.bottom = bottom;
            box.back = 1;
            const uint8_t* source = rgbaData + static_cast<size_t>(rect.y) * stride + rect.x * 4;
            m_context->UpdateSubresource(m_hudTexture, 0, &box, source, stride, 0);
            totalBytes += static_cast<size_t>(right - rect.x) * (bottom - rect.y) * 4;
        }
        if (uploadedBytes) *uploadedBytes = totalBytes;
        return true;
    }

    m_hudWidth = width;
    m_hudHeight = height;

    if (m_hudShaderView) { m_hudShaderView->Release(); m_hudShaderView = nullptr; }
    if (m_hudInputView) { m_hudInputView->Release(); m_hudInputView = nullptr; }
    if (m_hudTexture) { m_hudTexture->Release(); m_hudTexture = nullptr; }

    const DXGI_FORMAT hudFormat = DXGI_FORMAT_R8G8B8A8_UNORM;
    UINT formatFlags = 0;
    HRESULT hr = m_videoEnumerator->CheckVideoProcessorFormat(hudFormat, &formatFlags);
    if (FAILED(hr) || !(formatFlags & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT)) {
        std::cerr << "[VP] RGBA8 HUD input is not supported by this VideoProcessor." << std::endl;
        return false;
    }

    D3D11_TEXTURE2D_DESC desc = {};
    desc.Width = width;
    desc.Height = height;
    desc.MipLevels = 1;
    desc.ArraySize = 1;
    desc.Format = hudFormat;
    desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;

    hr = m_device->CreateTexture2D(&desc, nullptr, &m_hudTexture);
    if (FAILED(hr)) {
        std::cerr << "[VP] CreateHUDTexture failed: 0x" << std::hex << hr << std::dec << std::endl;
        return false;
    }

    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inViewDesc = {};
    inViewDesc.FourCC = 0;
    inViewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    inViewDesc.Texture2D.MipSlice = 0;
    inViewDesc.Texture2D.ArraySlice = 0;

    hr = m_videoDevice->CreateVideoProcessorInputView(m_hudTexture, m_videoEnumerator, &inViewDesc, &m_hudInputView);
    if (FAILED(hr)) {
        std::cerr << "[VP] CreateVideoProcessorInputView for HUD failed: 0x" << std::hex << hr << std::dec << std::endl;
        return false;
    }
    hr = m_device->CreateShaderResourceView(m_hudTexture, nullptr, &m_hudShaderView);
    if (FAILED(hr)) {
        std::cerr << "[VP] CreateShaderResourceView for HUD failed: 0x"
                  << std::hex << hr << std::dec << std::endl;
        return false;
    }
    // ETAP 5G: UAV on the persistent HUD canvas for the GPU map blend pass.
    hr = m_device->CreateUnorderedAccessView(m_hudTexture, nullptr, &m_hudUAV);
    if (FAILED(hr) || !m_hudUAV) {
        std::cerr << "[VP] CreateUnorderedAccessView for HUD failed: 0x"
                  << std::hex << hr << std::dec << std::endl;
        return false;
    }

    if (textureCreated) *textureCreated = true;
    // A newly allocated texture has undefined contents. Its first update must
    // initialize the complete image irrespective of the requested dirty list.
    m_context->UpdateSubresource(m_hudTexture, 0, nullptr, rgbaData, stride, 0);
    if (uploadedBytes) *uploadedBytes = static_cast<size_t>(width) * height * 4;
    return true;
}

// ── ETAP 5G: GPU-resident final map resize + composite ──────────────────

bool D3D11VideoProcessorPipeline::InitializeMapCompositor() {
    if (m_mapResampleShader && m_mapBlendShader) return true;

    const char* resampleSource = R"(
        Texture2D<float4> MapTexture : register(t0);
        RWTexture2D<float4> ResampleOut : register(u0);
        cbuffer ResampleCB : register(b0) {
            uint srcW; uint srcH;
            uint dstW; uint dstH;
            uint filter; uint pad;
        };

        float Sinc(float x) {
            if (abs(x) < 1e-6) return 1.0;
            return sin(3.14159265358979323846 * x) / (3.14159265358979323846 * x);
        }
        float Lanczos3(float x) {
            if (abs(x) >= 3.0) return 0.0;
            return Sinc(x) * Sinc(x / 3.0);
        }
        float CatmullRom(float x) {
            float a = -0.5;
            float ax = abs(x);
            if (ax < 1.0) return (a + 2.0) * x * x * x - (a + 3.0) * x * x + 1.0;
            if (ax < 2.0) return a * x * x * x - 5.0 * a * x * x + 8.0 * a * x - 4.0 * a;
            return 0.0;
        }

        [numthreads(16, 16, 1)]
        void CSMain(uint3 tid : SV_DispatchThreadID) {
            if (tid.x >= dstW || tid.y >= dstH) return;
            float scaleX = float(srcW) / float(dstW);
            float scaleY = float(srcH) / float(dstH);
            float cx = (tid.x + 0.5) * scaleX - 0.5;
            float cy = (tid.y + 0.5) * scaleY - 0.5;

            int baseX, baseY, taps;
            if (filter == 0) { baseX = (int)floor(cx); baseY = (int)floor(cy); taps = 2; }
            else if (filter == 1) { baseX = (int)floor(cx) - 1; baseY = (int)floor(cy) - 1; taps = 4; }
            else { baseX = (int)floor(cx) - 2; baseY = (int)floor(cy) - 2; taps = 6; }

            // Premultiplied-alpha resample (matches Pillow RGBA LANCZOS behaviour).
            float3 premulRgb = 0.0;
            float alphaAcc = 0.0;
            float wsum = 0.0;
            for (int dy = 0; dy < taps; ++dy) {
                int iy = baseY + dy;
                float wy;
                if (filter == 0) wy = 1.0 - abs(cy - iy);
                else if (filter == 1) wy = CatmullRom(cy - iy);
                else wy = Lanczos3(cy - iy);
                if (abs(wy) < 1e-6) continue;
                for (int dx = 0; dx < taps; ++dx) {
                    int ix = baseX + dx;
                    if (ix < 0 || ix >= (int)srcW || iy < 0 || iy >= (int)srcH) continue;
                    float wx;
                    if (filter == 0) wx = 1.0 - abs(cx - ix);
                    else if (filter == 1) wx = CatmullRom(cx - ix);
                    else wx = Lanczos3(cx - ix);
                    if (abs(wx) < 1e-6) continue;
                    float w = wx * wy;
                    float4 s = MapTexture.Load(int3(ix, iy, 0));
                    premulRgb += s.rgb * s.a * w;
                    alphaAcc += s.a * w;
                    wsum += w;
                }
            }
            if (wsum <= 1e-6) { ResampleOut[tid.xy] = float4(0, 0, 0, 0); return; }
            float4 result;
            result.a = alphaAcc / wsum;
            if (result.a > 1e-6) result.rgb = premulRgb / alphaAcc;
            else result.rgb = 0.0;
            ResampleOut[tid.xy] = saturate(result);
        }
    )";

    ID3DBlob* blob = nullptr;
    ID3DBlob* errors = nullptr;
    HRESULT hr = D3DCompile(resampleSource, strlen(resampleSource), nullptr, nullptr, nullptr,
                            "CSMain", "cs_5_0", 0, 0, &blob, &errors);
    if (FAILED(hr)) {
        if (errors) { std::cerr << "[MAP] resample shader compile: " << (char*)errors->GetBufferPointer() << std::endl; errors->Release(); }
        return false;
    }
    hr = m_device->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &m_mapResampleShader);
    blob->Release();
    if (FAILED(hr)) return false;

    const char* blendSource = R"(
        Texture2D<float4> MapResample : register(t0);
        RWTexture2D<float4> HUDCanvas : register(u0);
        cbuffer BlendCB : register(b0) {
            uint dstX; uint dstY;
            uint mapW; uint mapH;
        };

        [numthreads(16, 16, 1)]
        void CSMain(uint3 tid : SV_DispatchThreadID) {
            if (tid.x >= mapW || tid.y >= mapH) return;
            uint2 canvasPos = uint2(dstX + tid.x, dstY + tid.y);
            float4 srcF = saturate(MapResample.Load(int3(tid.xy, 0)));
            uint4 src = (uint4)round(srcF * 255.0);
            if (src.a == 0) return;
            uint4 dst = (uint4)round(saturate(HUDCanvas.Load(int3(canvasPos, 0))) * 255.0);
            // Straight-alpha "over" (Pillow alpha_composite float-equivalent).
            float invA = (255.0 - float(src.a)) / 255.0;
            float outAF = float(src.a) + float(dst.a) * invA;
            uint outA = (uint)round(outAF);
            if (outA == 0) { HUDCanvas[canvasPos] = float4(0, 0, 0, 0); return; }
            uint3 outC;
            outC.x = (uint)round((float(src.x) * src.a + float(dst.x) * dst.a * invA) / outAF);
            outC.y = (uint)round((float(src.y) * src.a + float(dst.y) * dst.a * invA) / outAF);
            outC.z = (uint)round((float(src.z) * src.a + float(dst.z) * dst.a * invA) / outAF);
            HUDCanvas[canvasPos] = float4(float3(min(outC, 255)), outA) / 255.0;
        }
    )";

    blob = nullptr;
    errors = nullptr;
    hr = D3DCompile(blendSource, strlen(blendSource), nullptr, nullptr, nullptr,
                    "CSMain", "cs_5_0", 0, 0, &blob, &errors);
    if (FAILED(hr)) {
        if (errors) { std::cerr << "[MAP] blend shader compile: " << (char*)errors->GetBufferPointer() << std::endl; errors->Release(); }
        return false;
    }
    hr = m_device->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &m_mapBlendShader);
    blob->Release();
    if (FAILED(hr)) return false;

    D3D11_BUFFER_DESC cbDesc = {};
    cbDesc.ByteWidth = 32;  // ResampleCB: 6 uint32
    cbDesc.Usage = D3D11_USAGE_DEFAULT;
    cbDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    hr = m_device->CreateBuffer(&cbDesc, nullptr, &m_mapResampleCB);
    if (FAILED(hr)) return false;

    cbDesc.ByteWidth = 16;  // BlendCB: 4 uint32
    hr = m_device->CreateBuffer(&cbDesc, nullptr, &m_mapBlendCB);
    if (FAILED(hr)) return false;

    return true;
}

void D3D11VideoProcessorPipeline::SetMapGpuEnabled(bool enabled) {
    m_mapGpuEnabled = enabled;
    if (enabled) InitializeMapCompositor();
}

void D3D11VideoProcessorPipeline::SetAboveMapGpuEnabled(bool enabled) {
    m_aboveMapGpuEnabled = enabled;
    if (enabled) InitializeChartCompositor();
}

bool D3D11VideoProcessorPipeline::UpdateAboveRegionsCount(UINT count) {
    if (count > MAX_ABOVE_REGIONS) count = MAX_ABOVE_REGIONS;
    m_aboveRegionCount = count;
    for (UINT i = 0; i < count; ++i) {
        m_aboveRegions[i].active = false;
    }
    return true;
}

bool D3D11VideoProcessorPipeline::UpdateAboveRegion(
    UINT index, UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
    UINT dstX, UINT dstY) {
    if (index >= MAX_ABOVE_REGIONS || !rgbaData || width == 0 || height == 0 ||
        stride < width * 4 || !m_device || !m_context) return false;

    if (!m_aboveRegionTexture[index] || m_aboveRegionTexW[index] != width || m_aboveRegionTexH[index] != height) {
        if (m_aboveRegionSRV[index]) { m_aboveRegionSRV[index]->Release(); m_aboveRegionSRV[index] = nullptr; }
        if (m_aboveRegionTexture[index]) { m_aboveRegionTexture[index]->Release(); m_aboveRegionTexture[index] = nullptr; }
        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = width; desc.Height = height; desc.MipLevels = 1;
        desc.ArraySize = 1; desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1; desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        HRESULT hr = m_device->CreateTexture2D(&desc, nullptr, &m_aboveRegionTexture[index]);
        if (FAILED(hr)) return false;
        hr = m_device->CreateShaderResourceView(m_aboveRegionTexture[index], nullptr, &m_aboveRegionSRV[index]);
        if (FAILED(hr) || !m_aboveRegionSRV[index]) return false;
        m_aboveRegionTexW[index] = width; m_aboveRegionTexH[index] = height;
    }
    m_aboveRegions[index].dstX = dstX;
    m_aboveRegions[index].dstY = dstY;
    m_aboveRegions[index].w = width;
    m_aboveRegions[index].h = height;
    m_aboveRegions[index].active = true;
    m_context->UpdateSubresource(m_aboveRegionTexture[index], 0, nullptr, rgbaData, stride, 0);
    return true;
}

bool D3D11VideoProcessorPipeline::UpdateAboveMapTexture(
    UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
    UINT dstX, UINT dstY, bool active) {
    if (!active) {
        m_aboveRegionCount = 0;
        return true;
    }
    m_aboveRegionCount = 1;
    return UpdateAboveRegion(0, width, height, rgbaData, stride, dstX, dstY);
}

void D3D11VideoProcessorPipeline::SetMapDumpPath(const char* path) {
    m_mapDumpPath[0] = 0;
    if (path) {
        strncpy(m_mapDumpPath, path, sizeof(m_mapDumpPath) - 1);
        m_mapDumpPath[sizeof(m_mapDumpPath) - 1] = 0;
    }
}

void D3D11VideoProcessorPipeline::SetMapGeometry(UINT dstX, UINT dstY, UINT srcW, UINT srcH, UINT outW, UINT outH) {
    m_mapDstX = dstX;
    m_mapDstY = dstY;
    m_mapSrcW = srcW;
    m_mapSrcH = srcH;
    m_mapOutW = outW;
    m_mapOutH = outH;
}

void D3D11VideoProcessorPipeline::SetMapFilter(int filter) {
    if (filter < 0 || filter > 2) filter = 2;
    m_mapFilter = filter;
}

bool D3D11VideoProcessorPipeline::UpdateMapTexture(
    UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
    size_t* uploadedBytes, bool* textureCreated) {
    if (uploadedBytes) *uploadedBytes = 0;
    if (textureCreated) *textureCreated = false;
    if (!rgbaData || stride < width * 4 || !m_device || !m_context) return false;

    if (!m_mapTexture || m_mapSrcW != width || m_mapSrcH != height) {
        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = width;
        desc.Height = height;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        HRESULT hr = m_device->CreateTexture2D(&desc, nullptr, &m_mapTexture);
        if (FAILED(hr)) {
            std::cerr << "[MAP] CreateMapTexture failed: 0x" << std::hex << hr << std::dec << std::endl;
            return false;
        }
        hr = m_device->CreateShaderResourceView(m_mapTexture, nullptr, &m_mapShaderView);
        if (FAILED(hr) || !m_mapShaderView) return false;
        m_mapSrcW = width;
        m_mapSrcH = height;
        if (textureCreated) *textureCreated = true;
    }

    const auto uploadStart = std::chrono::high_resolution_clock::now();
    m_context->UpdateSubresource(m_mapTexture, 0, nullptr, rgbaData, stride, 0);
    m_mapUploadMs = std::chrono::duration<double, std::milli>(
        std::chrono::high_resolution_clock::now() - uploadStart).count();
    m_mapUploads++;
    if (uploadedBytes) *uploadedBytes = static_cast<size_t>(width) * height * 4;
    m_mapUploadedBytes += static_cast<size_t>(width) * height * 4;
    return true;
}

bool D3D11VideoProcessorPipeline::ResampleAndBlendMap(
    double* outResampleMs, double* outFlush1Ms, double* outBlendMs, double* outFlush2Ms
) {
    if (outResampleMs) *outResampleMs = 0.0;
    if (outFlush1Ms) *outFlush1Ms = 0.0;
    if (outBlendMs) *outBlendMs = 0.0;
    if (outFlush2Ms) *outFlush2Ms = 0.0;

    if (!m_mapGpuEnabled || !m_mapTexture || !m_mapShaderView ||
        !m_mapResampleShader || !m_mapBlendShader || !m_mapResampleCB || !m_mapBlendCB ||
        !m_hudUAV || m_mapSrcW == 0 || m_mapOutW == 0) {
        return true;  // nothing to do — not an error
    }

    // ETAP 8U-B: Fast-path Direct 1:1 GPU Blend
    bool useDirect1to1 = (m_mapGpuPath == 2) ||
                         (m_mapGpuPath == 0 && m_mapSrcW == m_mapOutW && m_mapSrcH == m_mapOutH);
    m_mapDirectUsed = useDirect1to1;

    if (useDirect1to1) {
        // Direct 1:1 GPU Blend: single dispatch, direct bind of m_mapShaderView as t0, write to m_hudUAV.
        // Zero intermediate texture allocation / write / read!
        const auto blendStart = std::chrono::high_resolution_clock::now();
        struct { UINT dstX, dstY, mapW, mapH; } blendCB = {
            m_mapDstX, m_mapDstY, m_mapOutW, m_mapOutH };
        m_context->UpdateSubresource(m_mapBlendCB, 0, nullptr, &blendCB, 0, 0);
        m_context->CSSetShader(m_mapBlendShader, nullptr, 0);
        ID3D11Buffer* blendCBs[1] = { m_mapBlendCB };
        m_context->CSSetConstantBuffers(0, 1, blendCBs);
        ID3D11ShaderResourceView* blendSRV = m_mapShaderView;
        m_context->CSSetShaderResources(0, 1, &blendSRV);
        ID3D11UnorderedAccessView* hudUAV = m_hudUAV;
        UINT zeroCounts[1] = { 0 };
        m_context->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        m_context->Dispatch((m_mapOutW + 15) / 16, (m_mapOutH + 15) / 16, 1);
        ID3D11UnorderedAccessView* nullUAV = nullptr;
        m_context->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        ID3D11ShaderResourceView* nullSRV = nullptr;
        m_context->CSSetShaderResources(0, 1, &nullSRV);

        const auto blendEnd = std::chrono::high_resolution_clock::now();
        if (outBlendMs) {
            *outBlendMs = std::chrono::duration<double, std::milli>(blendEnd - blendStart).count();
        }
        if (m_flushMode == 1) {
            m_context->Flush();
        }
        m_mapResampleMs = std::chrono::duration<double, std::milli>(blendEnd - blendStart).count();
        return true;
    }

    if (!m_mapResampleTexture || !m_mapResampleUAV || !m_mapResampleSRV) {
        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = m_mapOutW;
        desc.Height = m_mapOutH;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
        HRESULT hr = m_device->CreateTexture2D(&desc, nullptr, &m_mapResampleTexture);
        if (FAILED(hr)) return false;
        hr = m_device->CreateUnorderedAccessView(m_mapResampleTexture, nullptr, &m_mapResampleUAV);
        if (FAILED(hr) || !m_mapResampleUAV) return false;
        hr = m_device->CreateShaderResourceView(m_mapResampleTexture, nullptr, &m_mapResampleSRV);
        if (FAILED(hr) || !m_mapResampleSRV) return false;
    }

    const auto resampleStart = std::chrono::high_resolution_clock::now();

    // Pass 1: 692 -> 691 RGBA resample
    struct { UINT srcW, srcH, dstW, dstH, filter, pad; } resampleCB = {
        m_mapSrcW, m_mapSrcH, m_mapOutW, m_mapOutH, (UINT)m_mapFilter, 0 };
    m_context->UpdateSubresource(m_mapResampleCB, 0, nullptr, &resampleCB, 0, 0);
    m_context->CSSetShader(m_mapResampleShader, nullptr, 0);
    ID3D11Buffer* resampleCBs[1] = { m_mapResampleCB };
    m_context->CSSetConstantBuffers(0, 1, resampleCBs);
    ID3D11ShaderResourceView* resampleSRV = m_mapShaderView;
    m_context->CSSetShaderResources(0, 1, &resampleSRV);
    ID3D11UnorderedAccessView* resampleUAV = m_mapResampleUAV;
    UINT zeroCounts[1] = { 0 };
    m_context->CSSetUnorderedAccessViews(0, 1, &resampleUAV, zeroCounts);
    m_context->Dispatch((m_mapOutW + 15) / 16, (m_mapOutH + 15) / 16, 1);
    ID3D11UnorderedAccessView* nullUAV = nullptr;
    m_context->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);

    const auto pass1End = std::chrono::high_resolution_clock::now();
    if (outResampleMs) {
        *outResampleMs = std::chrono::duration<double, std::milli>(pass1End - resampleStart).count();
    }

    // ETAP 8S: in BATCHED mode (m_flushMode == 0), sequential CS dispatches with proper
    // UAV/SRV unbinding do not require intermediate Flush calls.
    const auto flush1Start = std::chrono::high_resolution_clock::now();
    if (m_flushMode == 1) {
        m_context->Flush();
    }
    const auto flush1End = std::chrono::high_resolution_clock::now();
    if (outFlush1Ms) {
        *outFlush1Ms = std::chrono::duration<double, std::milli>(flush1End - flush1Start).count();
    }

    // Pass 2: blend resampled 691 map into the persistent HUD canvas at bbox
    const auto blendStart = std::chrono::high_resolution_clock::now();
    struct { UINT dstX, dstY, mapW, mapH; } blendCB = {
        m_mapDstX, m_mapDstY, m_mapOutW, m_mapOutH };
    m_context->UpdateSubresource(m_mapBlendCB, 0, nullptr, &blendCB, 0, 0);
    m_context->CSSetShader(m_mapBlendShader, nullptr, 0);
    ID3D11Buffer* blendCBs[1] = { m_mapBlendCB };
    m_context->CSSetConstantBuffers(0, 1, blendCBs);
    ID3D11ShaderResourceView* blendSRV = m_mapResampleSRV;
    m_context->CSSetShaderResources(0, 1, &blendSRV);
    ID3D11UnorderedAccessView* hudUAV = m_hudUAV;
    m_context->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
    m_context->Dispatch((m_mapOutW + 15) / 16, (m_mapOutH + 15) / 16, 1);
    m_context->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
    ID3D11ShaderResourceView* nullSRV = nullptr;
    m_context->CSSetShaderResources(0, 1, &nullSRV);

    const auto pass2End = std::chrono::high_resolution_clock::now();
    if (outBlendMs) {
        *outBlendMs = std::chrono::duration<double, std::milli>(pass2End - blendStart).count();
    }

    const auto flush2Start = std::chrono::high_resolution_clock::now();
    if (m_flushMode == 1) {
        m_context->Flush();
    }
    const auto flush2End = std::chrono::high_resolution_clock::now();
    if (outFlush2Ms) {
        *outFlush2Ms = std::chrono::duration<double, std::milli>(flush2End - flush2Start).count();
    }

    m_mapResampleMs = std::chrono::duration<double, std::milli>(
        flush2End - resampleStart).count();
    m_mapResampleReady = true;
    return true;
}

bool D3D11VideoProcessorPipeline::GetMapResampleReadback(uint8_t* outRGBA, UINT stride) {
    // Diagnostic A/B readback of the GPU-composited 691x691 RGBA map.  Never
    // called on the production export path.
    //
    // NOTE: this reads the map region from the persistent HUD canvas (which is
    // exactly the composited map the video consumes) rather than from
    // m_mapResampleTexture.  On this driver a CopyResource of a texture whose
    // only writes came from a compute UAV dispatch returns stale zeros, whereas
    // the HUD canvas (also updated via UpdateSubresource) reads back reliably.
    // Because the HUD canvas is fully transparent at the map bbox before the
    // blend pass, "map over transparent" == the GPU resample output exactly.
    if (!outRGBA || !m_hudTexture || m_mapOutW == 0 || m_mapOutH == 0 ||
        stride < m_mapOutW * 4) return false;
    if (!m_mapReadbackStaging) {
        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = m_mapOutW;
        desc.Height = m_mapOutH;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_STAGING;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        HRESULT hr = m_device->CreateTexture2D(&desc, nullptr, &m_mapReadbackStaging);
        if (FAILED(hr)) return false;
    }
    // Read back the 691x691 GPU-resampled map (small copy).  Diagnostic only.
    m_context->CopyResource(m_mapReadbackStaging, m_mapResampleTexture);
    D3D11_MAPPED_SUBRESOURCE mapped = {};
    if (FAILED(m_context->Map(m_mapReadbackStaging, 0, D3D11_MAP_READ, 0, &mapped))) return false;
    const uint8_t* src = static_cast<const uint8_t*>(mapped.pData);
    for (UINT y = 0; y < m_mapOutH; ++y) {
        memcpy(outRGBA + static_cast<size_t>(y) * stride,
               src + static_cast<size_t>(y) * mapped.RowPitch, m_mapOutW * 4);
    }
    m_context->Unmap(m_mapReadbackStaging, 0);
    return true;
}

void D3D11VideoProcessorPipeline::ReleaseMapResources() {
    if (m_mapResampleShader) { m_mapResampleShader->Release(); m_mapResampleShader = nullptr; }
    if (m_mapBlendShader) { m_mapBlendShader->Release(); m_mapBlendShader = nullptr; }
    if (m_mapResampleCB) { m_mapResampleCB->Release(); m_mapResampleCB = nullptr; }
    if (m_mapBlendCB) { m_mapBlendCB->Release(); m_mapBlendCB = nullptr; }
    if (m_mapResampleSRV) { m_mapResampleSRV->Release(); m_mapResampleSRV = nullptr; }
    if (m_mapResampleUAV) { m_mapResampleUAV->Release(); m_mapResampleUAV = nullptr; }
    if (m_mapResampleTexture) { m_mapResampleTexture->Release(); m_mapResampleTexture = nullptr; }
    if (m_mapShaderView) { m_mapShaderView->Release(); m_mapShaderView = nullptr; }
    if (m_mapTexture) { m_mapTexture->Release(); m_mapTexture = nullptr; }
    for (UINT i = 0; i < MAX_ABOVE_REGIONS; ++i) {
        if (m_aboveRegionSRV[i]) { m_aboveRegionSRV[i]->Release(); m_aboveRegionSRV[i] = nullptr; }
        if (m_aboveRegionTexture[i]) { m_aboveRegionTexture[i]->Release(); m_aboveRegionTexture[i] = nullptr; }
        m_aboveRegionTexW[i] = m_aboveRegionTexH[i] = 0;
    }
    if (m_hudUAV) { m_hudUAV->Release(); m_hudUAV = nullptr; }
}

// ── ETAP 5J: GPU final compositing for the cadence/HR charts ────────────

bool D3D11VideoProcessorPipeline::InitializeChartCompositor() {
    if (m_chartBlendShader && m_chartBlendCB) return true;

    // One compute shader, three modes (selected via cbuffer):
    //   mode 0 = clear the chart bbox in the persistent HUD canvas to
    //            transparent (removes the previous frame's chart — dynamic
    //            cursor/value would otherwise ghost).
    //   mode 1 = straight-alpha "over" of the chart texture into the bbox,
    //            using exactly the same uint8 rounding as the validated GPU
    //            map/HUD blend (over a cleared dest this reduces to the raw
    //            chart, matching Pillow alpha_composite over transparency).
    //   mode 2 = REPLACE (ETAP 5K): straight copy of the source tile — used
    //            for the pre-composited dynamic cursor/value tiles.
    // No resample: the chart texture is already at its final widget size.
    const char* chartSource = R"(
        Texture2D<float4> ChartTex : register(t0);
        RWTexture2D<float4> HUDCanvas : register(u0);
        cbuffer ChartCB : register(b0) {
            uint dstX; uint dstY;
            uint chartW; uint chartH;
            uint mode; uint pad;
        };

        [numthreads(16, 16, 1)]
        void CSMain(uint3 tid : SV_DispatchThreadID) {
            if (tid.x >= chartW || tid.y >= chartH) return;
            uint2 canvasPos = uint2(dstX + tid.x, dstY + tid.y);
            if (mode == 0) {
                HUDCanvas[canvasPos] = float4(0, 0, 0, 0);
                return;
            }
            float4 srcF = saturate(ChartTex.Load(int3(tid.xy, 0)));
            if (mode == 2) {
                // ETAP 5K REPLACE: the dynamic tiles are pre-composited over
                // the static on the CPU and ARE the exact final-chart pixels
                // of their regions, so a straight copy reproduces the CPU
                // chart byte-for-byte (Pillow draw/paste blends differ from
                // straight-alpha "over", hence the replace instead of a blend).
                HUDCanvas[canvasPos] = srcF;
                return;
            }
            uint4 src = (uint4)round(srcF * 255.0);
            if (src.a == 0) {
                return;
            }
            uint4 dst = (uint4)round(saturate(HUDCanvas.Load(int3(canvasPos, 0))) * 255.0);
            // Straight-alpha "over" (Pillow alpha_composite float-equivalent).
            float invA = (255.0 - float(src.a)) / 255.0;
            float outAF = float(src.a) + float(dst.a) * invA;
            uint outA = (uint)round(outAF);
            if (outA == 0) { HUDCanvas[canvasPos] = float4(0, 0, 0, 0); return; }
            uint3 outC;
            outC.x = (uint)round((float(src.x) * src.a + float(dst.x) * dst.a * invA) / outAF);
            outC.y = (uint)round((float(src.y) * src.a + float(dst.y) * dst.a * invA) / outAF);
            outC.z = (uint)round((float(src.z) * src.a + float(dst.z) * dst.a * invA) / outAF);
            HUDCanvas[canvasPos] = float4(float3(min(outC, 255)), outA) / 255.0;
        }
    )";

    ID3DBlob* blob = nullptr;
    ID3DBlob* errors = nullptr;
    HRESULT hr = D3DCompile(chartSource, strlen(chartSource), nullptr, nullptr, nullptr,
                            "CSMain", "cs_5_0", 0, 0, &blob, &errors);
    if (FAILED(hr)) {
        if (errors) { std::cerr << "[CHART] blend shader compile: " << (char*)errors->GetBufferPointer() << std::endl; errors->Release(); }
        return false;
    }
    hr = m_device->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &m_chartBlendShader);
    blob->Release();
    if (FAILED(hr)) return false;

    D3D11_BUFFER_DESC cbDesc = {};
    cbDesc.ByteWidth = 32;  // ChartCB: 6 uint32
    cbDesc.Usage = D3D11_USAGE_DEFAULT;
    cbDesc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    hr = m_device->CreateBuffer(&cbDesc, nullptr, &m_chartBlendCB);
    if (FAILED(hr)) return false;

    return true;
}

void D3D11VideoProcessorPipeline::SetChartGpuEnabled(bool enabled) {
    m_chartGpuEnabled = enabled;
    if (enabled) InitializeChartCompositor();
}

bool D3D11VideoProcessorPipeline::UpdateChartTexture(
    UINT slot, UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
    UINT dstX, UINT dstY, size_t* uploadedBytes, bool* textureCreated) {
    if (uploadedBytes) *uploadedBytes = 0;
    if (textureCreated) *textureCreated = false;
    if (!m_chartGpuEnabled || slot >= CHART_SLOT_COUNT || !rgbaData ||
        stride < width * 4 || !m_device || !m_context) return false;

    // Persistent texture per chart slot — (re)created only when the widget
    // dimensions change, never per frame (0 texture allocations/frame).
    if (!m_chartTexture[slot] || m_chartW[slot] != width || m_chartH[slot] != height) {
        if (m_chartTexture[slot]) { m_chartTexture[slot]->Release(); m_chartTexture[slot] = nullptr; }
        if (m_chartSRV[slot]) { m_chartSRV[slot]->Release(); m_chartSRV[slot] = nullptr; }
        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = width;
        desc.Height = height;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        HRESULT hr = m_device->CreateTexture2D(&desc, nullptr, &m_chartTexture[slot]);
        if (FAILED(hr)) {
            std::cerr << "[CHART] CreateChartTexture failed: 0x" << std::hex << hr << std::dec << std::endl;
            return false;
        }
        hr = m_device->CreateShaderResourceView(m_chartTexture[slot], nullptr, &m_chartSRV[slot]);
        if (FAILED(hr) || !m_chartSRV[slot]) return false;
        m_chartW[slot] = width;
        m_chartH[slot] = height;
        m_chartTextureCreates++;
        if (textureCreated) *textureCreated = true;
    }

    m_chartDstX[slot] = dstX;
    m_chartDstY[slot] = dstY;
    m_context->UpdateSubresource(m_chartTexture[slot], 0, nullptr, rgbaData, stride, 0);
    m_chartActive[slot] = true;
    m_chartUploads++;
    if (uploadedBytes) *uploadedBytes = static_cast<size_t>(width) * height * 4;
    m_chartUploadedBytes += static_cast<size_t>(width) * height * 4;
    return true;
}

void D3D11VideoProcessorPipeline::SetChartSplitMode(bool enabled) {
    m_chartSplitMode = enabled;
    if (enabled) InitializeChartCompositor();
}

// ── ETAP 5K: GPU_SPLIT chart layers ─────────────────────────────────────
// The static 1160x511 layer is uploaded once per cache invalidation; the two
// dynamic tiles (cursor / current value) are uploaded per frame.  The dynamic
// tiles are pre-composited over the static on the CPU, so they are stored raw
// and REPLACED (mode 2) into the HUD canvas after the static blend — this is
// what makes GPU_SPLIT pixel-exact (see BlendCharts).

bool D3D11VideoProcessorPipeline::UpdateChartStaticTexture(
    UINT slot, UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
    UINT dstX, UINT dstY, size_t* uploadedBytes, bool* textureCreated) {
    if (uploadedBytes) *uploadedBytes = 0;
    if (textureCreated) *textureCreated = false;
    if (!m_chartGpuEnabled || !m_chartSplitMode || slot >= CHART_SLOT_COUNT ||
        !rgbaData || stride < width * 4 || !m_device || !m_context) return false;

    if (!m_chartStaticTexture[slot] || m_chartW[slot] != width || m_chartH[slot] != height) {
        if (m_chartStaticTexture[slot]) { m_chartStaticTexture[slot]->Release(); m_chartStaticTexture[slot] = nullptr; }
        if (m_chartStaticSRV[slot]) { m_chartStaticSRV[slot]->Release(); m_chartStaticSRV[slot] = nullptr; }
        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = width;
        desc.Height = height;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        HRESULT hr = m_device->CreateTexture2D(&desc, nullptr, &m_chartStaticTexture[slot]);
        if (FAILED(hr)) {
            std::cerr << "[CHART] CreateChartStaticTexture failed: 0x" << std::hex << hr << std::dec << std::endl;
            return false;
        }
        hr = m_device->CreateShaderResourceView(m_chartStaticTexture[slot], nullptr, &m_chartStaticSRV[slot]);
        if (FAILED(hr) || !m_chartStaticSRV[slot]) return false;
        m_chartW[slot] = width;
        m_chartH[slot] = height;
        m_chartTextureCreates++;
        if (textureCreated) *textureCreated = true;
    }

    m_chartDstX[slot] = dstX;
    m_chartDstY[slot] = dstY;
    m_context->UpdateSubresource(m_chartStaticTexture[slot], 0, nullptr, rgbaData, stride, 0);
    m_chartActive[slot] = true;
    m_chartStaticUploads++;
    if (uploadedBytes) *uploadedBytes = static_cast<size_t>(width) * height * 4;
    m_chartStaticUploadedBytes += static_cast<size_t>(width) * height * 4;
    return true;
}

bool D3D11VideoProcessorPipeline::UpdateChartDynamicTile(
    UINT slot, UINT region, UINT width, UINT height, const uint8_t* rgbaData,
    UINT stride, UINT localX, UINT localY, size_t* uploadedBytes) {
    if (uploadedBytes) *uploadedBytes = 0;
    if (!m_chartGpuEnabled || !m_chartSplitMode || slot >= CHART_SLOT_COUNT ||
        region > 1 || !rgbaData || stride < width * 4 || !m_device || !m_context ||
        width == 0 || height == 0) return false;

    ID3D11Texture2D** tex = (region == 0) ? &m_chartCursorTexture[slot] : &m_chartValueTexture[slot];
    ID3D11ShaderResourceView** srv = (region == 0) ? &m_chartCursorSRV[slot] : &m_chartValueSRV[slot];
    UINT& tw = (region == 0) ? m_chartCursorW[slot] : m_chartValueW[slot];
    UINT& th = (region == 0) ? m_chartCursorH[slot] : m_chartValueH[slot];
    UINT& tx = (region == 0) ? m_chartCursorX[slot] : m_chartValueX[slot];
    UINT& ty = (region == 0) ? m_chartCursorY[slot] : m_chartValueY[slot];

    if (!*tex || tw != width || th != height) {
        if (*tex) { (*tex)->Release(); *tex = nullptr; }
        if (*srv) { (*srv)->Release(); *srv = nullptr; }
        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = width;
        desc.Height = height;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        HRESULT hr = m_device->CreateTexture2D(&desc, nullptr, tex);
        if (FAILED(hr)) {
            std::cerr << "[CHART] CreateChartDynamicTile failed: 0x" << std::hex << hr << std::dec << std::endl;
            return false;
        }
        hr = m_device->CreateShaderResourceView(*tex, nullptr, srv);
        if (FAILED(hr) || !*srv) return false;
        tw = width;
        th = height;
        m_chartTextureCreates++;
    }

    tx = localX;
    ty = localY;
    m_context->UpdateSubresource(*tex, 0, nullptr, rgbaData, stride, 0);
    m_chartDynamicUploads++;
    if (uploadedBytes) *uploadedBytes = static_cast<size_t>(width) * height * 4;
    m_chartDynamicUploadedBytes += static_cast<size_t>(width) * height * 4;
    return true;
}

bool D3D11VideoProcessorPipeline::BlendCharts(double* outBlendMs, double* outFlushMs) {
    if (outBlendMs) *outBlendMs = 0.0;
    if (outFlushMs) *outFlushMs = 0.0;

    if (!m_chartGpuEnabled || !m_chartBlendShader || !m_chartBlendCB ||
        !m_hudUAV) {
        return true;  // nothing to do — not an error
    }

    const auto blendStart = std::chrono::high_resolution_clock::now();
    struct { UINT dstX, dstY, chartW, chartH, mode, pad; } cb = {};
    ID3D11ShaderResourceView* nullSRV = nullptr;
    ID3D11UnorderedAccessView* nullUAV = nullptr;
    UINT zeroCounts[1] = { 0 };
    double clearMs = 0.0;

    // One dispatch helper: sets the cbuffer (dst/size/mode), binds the shader,
    // UAV and optional SRV, dispatches a grid covering the region, then
    // unbinds.  Used for every chart pass (clear / static blend / replace).
    auto dispatch = [&](UINT dstX, UINT dstY, UINT w, UINT h, UINT mode,
                        ID3D11ShaderResourceView* srv) {
        cb = { dstX, dstY, w, h, mode, 0 };
        ID3D11Buffer* cbs[1] = { m_chartBlendCB };
        ID3D11UnorderedAccessView* hudUAV = m_hudUAV;
        m_context->UpdateSubresource(m_chartBlendCB, 0, nullptr, &cb, 0, 0);
        m_context->CSSetShader(m_chartBlendShader, nullptr, 0);
        m_context->CSSetConstantBuffers(0, 1, cbs);
        m_context->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        if (srv) m_context->CSSetShaderResources(0, 1, &srv);
        m_context->Dispatch((w + 15) / 16, (h + 15) / 16, 1);
        m_context->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        if (srv) m_context->CSSetShaderResources(0, 1, &nullSRV);
    };

    for (UINT slot = 0; slot < CHART_SLOT_COUNT; ++slot) {
        if (!m_chartActive[slot] || m_chartW[slot] == 0 || m_chartH[slot] == 0) {
            continue;
        }
        const UINT cx = m_chartDstX[slot], cy = m_chartDstY[slot];
        const UINT cw = m_chartW[slot], ch = m_chartH[slot];

        if (m_chartSplitMode) {
            // ETAP 5K: clear bbox -> blend static -> replace cursor -> replace
            // value.  The dynamic tiles are pre-composited over the static on
            // the CPU, so a straight copy (mode 2) reproduces the CPU chart
            // byte-for-byte; blending them would double-apply the static.
            const auto clearStart = std::chrono::high_resolution_clock::now();
            dispatch(cx, cy, cw, ch, 0, nullptr);  // clear chart bbox
            clearMs += std::chrono::duration<double, std::milli>(
                std::chrono::high_resolution_clock::now() - clearStart).count();
            if (m_chartStaticTexture[slot] && m_chartStaticSRV[slot]) {
                dispatch(cx, cy, cw, ch, 1, m_chartStaticSRV[slot]);
            }
            if (m_chartCursorTexture[slot] && m_chartCursorSRV[slot] &&
                m_chartCursorW[slot] > 0 && m_chartCursorH[slot] > 0) {
                dispatch(cx + m_chartCursorX[slot], cy + m_chartCursorY[slot],
                         m_chartCursorW[slot], m_chartCursorH[slot], 2,
                         m_chartCursorSRV[slot]);
            }
            if (m_chartValueTexture[slot] && m_chartValueSRV[slot] &&
                m_chartValueW[slot] > 0 && m_chartValueH[slot] > 0) {
                dispatch(cx + m_chartValueX[slot], cy + m_chartValueY[slot],
                         m_chartValueW[slot], m_chartValueH[slot], 2,
                         m_chartValueSRV[slot]);
            }
        } else {
            // ETAP 5J: clear bbox + straight-alpha "over" of the full chart.
            if (!m_chartTexture[slot] || !m_chartSRV[slot]) continue;
            const auto clearStart = std::chrono::high_resolution_clock::now();
            dispatch(cx, cy, cw, ch, 0, nullptr);
            clearMs += std::chrono::duration<double, std::milli>(
                std::chrono::high_resolution_clock::now() - clearStart).count();
            dispatch(cx, cy, cw, ch, 1, m_chartSRV[slot]);
        }
    }
    const auto dispatchesEnd = std::chrono::high_resolution_clock::now();
    if (outBlendMs) {
        *outBlendMs = std::chrono::duration<double, std::milli>(dispatchesEnd - blendStart).count();
    }

    const auto flushStart = std::chrono::high_resolution_clock::now();
    if (m_flushMode == 1) {
        m_context->Flush();
    }
    const auto flushEnd = std::chrono::high_resolution_clock::now();
    if (outFlushMs) {
        *outFlushMs = std::chrono::duration<double, std::milli>(flushEnd - flushStart).count();
    }

    m_chartBlendMs = std::chrono::duration<double, std::milli>(
        flushEnd - blendStart).count();
    m_chartClearMs = clearMs;
    return true;
}

void D3D11VideoProcessorPipeline::ReleaseChartResources() {
    for (UINT slot = 0; slot < CHART_SLOT_COUNT; ++slot) {
        if (m_chartSRV[slot]) { m_chartSRV[slot]->Release(); m_chartSRV[slot] = nullptr; }
        if (m_chartTexture[slot]) { m_chartTexture[slot]->Release(); m_chartTexture[slot] = nullptr; }
        if (m_chartStaticSRV[slot]) { m_chartStaticSRV[slot]->Release(); m_chartStaticSRV[slot] = nullptr; }
        if (m_chartStaticTexture[slot]) { m_chartStaticTexture[slot]->Release(); m_chartStaticTexture[slot] = nullptr; }
        if (m_chartCursorSRV[slot]) { m_chartCursorSRV[slot]->Release(); m_chartCursorSRV[slot] = nullptr; }
        if (m_chartCursorTexture[slot]) { m_chartCursorTexture[slot]->Release(); m_chartCursorTexture[slot] = nullptr; }
        if (m_chartValueSRV[slot]) { m_chartValueSRV[slot]->Release(); m_chartValueSRV[slot] = nullptr; }
        if (m_chartValueTexture[slot]) { m_chartValueTexture[slot]->Release(); m_chartValueTexture[slot] = nullptr; }
        m_chartW[slot] = 0;
        m_chartH[slot] = 0;
        m_chartCursorW[slot] = m_chartCursorH[slot] = 0;
        m_chartValueW[slot] = m_chartValueH[slot] = 0;
        m_chartActive[slot] = false;
    }
    if (m_chartBlendCB) { m_chartBlendCB->Release(); m_chartBlendCB = nullptr; }
    if (m_chartBlendShader) { m_chartBlendShader->Release(); m_chartBlendShader = nullptr; }
}

bool D3D11VideoProcessorPipeline::GetHUDCanvasRegionReadback(
    UINT x, UINT y, UINT w, UINT h, uint8_t* outRGBA, UINT stride) {
    // Diagnostic A/B readback of a region of the persistent HUD canvas (the
    // exact composited pixels the video consumes).  Never called on the
    // production export path.
    if (!outRGBA || !m_hudTexture || w == 0 || h == 0 || stride < w * 4) return false;
    if (x + w > m_hudWidth || y + h > m_hudHeight) return false;
    ID3D11Texture2D* staging = nullptr;
    D3D11_TEXTURE2D_DESC desc = {};
    desc.Width = w;
    desc.Height = h;
    desc.MipLevels = 1;
    desc.ArraySize = 1;
    desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_STAGING;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    if (FAILED(m_device->CreateTexture2D(&desc, nullptr, &staging))) return false;
    D3D11_BOX box = {};
    box.left = x;
    box.top = y;
    box.front = 0;
    box.right = x + w;
    box.bottom = y + h;
    box.back = 1;
    m_context->CopySubresourceRegion(staging, 0, 0, 0, 0, m_hudTexture, 0, &box);
    D3D11_MAPPED_SUBRESOURCE mapped = {};
    bool ok = false;
    if (SUCCEEDED(m_context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped))) {
        const uint8_t* src = static_cast<const uint8_t*>(mapped.pData);
        for (UINT row = 0; row < h; ++row) {
            memcpy(outRGBA + static_cast<size_t>(row) * stride,
                   src + static_cast<size_t>(row) * mapped.RowPitch, w * 4);
        }
        m_context->Unmap(staging, 0);
        ok = true;
    }
    staging->Release();
    return ok;
}

bool D3D11VideoProcessorPipeline::GetChartStaticReadback(
    UINT slot, uint8_t* outRGBA, UINT stride) {
    if (!outRGBA || slot >= CHART_SLOT_COUNT || !m_chartStaticTexture[slot] ||
        m_chartW[slot] == 0 || m_chartH[slot] == 0 || stride < m_chartW[slot] * 4)
        return false;
    ID3D11Texture2D* staging = nullptr;
    D3D11_TEXTURE2D_DESC desc = {};
    desc.Width = m_chartW[slot];
    desc.Height = m_chartH[slot];
    desc.MipLevels = 1;
    desc.ArraySize = 1;
    desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_STAGING;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    if (FAILED(m_device->CreateTexture2D(&desc, nullptr, &staging))) return false;
    m_context->CopyResource(staging, m_chartStaticTexture[slot]);
    D3D11_MAPPED_SUBRESOURCE mapped = {};
    bool ok = false;
    if (SUCCEEDED(m_context->Map(staging, 0, D3D11_MAP_READ, 0, &mapped))) {
        const uint8_t* src = static_cast<const uint8_t*>(mapped.pData);
        for (UINT row = 0; row < m_chartH[slot]; ++row) {
            memcpy(outRGBA + static_cast<size_t>(row) * stride,
                   src + static_cast<size_t>(row) * mapped.RowPitch,
                   m_chartW[slot] * 4);
        }
        m_context->Unmap(staging, 0);
        ok = true;
    }
    staging->Release();
    return ok;
}

// ── ETAP 5L: GPU final compositing for the speed gauge ────────────────
// Reuses the validated 5J chart blend shader (clear + straight-alpha "over",
// no resample) for a single persistent gauge texture.

void D3D11VideoProcessorPipeline::SetGaugeGpuEnabled(bool enabled) {
    m_gaugeGpuEnabled = enabled;
    if (enabled) InitializeChartCompositor();
}

bool D3D11VideoProcessorPipeline::UpdateGaugeTexture(
    UINT width, UINT height, const uint8_t* rgbaData, UINT stride,
    UINT dstX, UINT dstY, size_t* uploadedBytes, bool* textureCreated) {
    if (uploadedBytes) *uploadedBytes = 0;
    if (textureCreated) *textureCreated = false;
    if (!m_gaugeGpuEnabled || !rgbaData || stride < width * 4 ||
        width == 0 || height == 0 || !m_device || !m_context) return false;

    if (!m_gaugeTexture || m_gaugeW != width || m_gaugeH != height) {
        if (m_gaugeTexture) { m_gaugeTexture->Release(); m_gaugeTexture = nullptr; }
        if (m_gaugeSRV) { m_gaugeSRV->Release(); m_gaugeSRV = nullptr; }
        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = width;
        desc.Height = height;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        HRESULT hr = m_device->CreateTexture2D(&desc, nullptr, &m_gaugeTexture);
        if (FAILED(hr)) {
            std::cerr << "[GAUGE] CreateGaugeTexture failed: 0x" << std::hex << hr << std::dec << std::endl;
            return false;
        }
        hr = m_device->CreateShaderResourceView(m_gaugeTexture, nullptr, &m_gaugeSRV);
        if (FAILED(hr) || !m_gaugeSRV) return false;
        m_gaugeW = width;
        m_gaugeH = height;
        m_gaugeTextureCreates++;
        if (textureCreated) *textureCreated = true;
    }

    m_gaugeDstX = dstX;
    m_gaugeDstY = dstY;
    m_context->UpdateSubresource(m_gaugeTexture, 0, nullptr, rgbaData, stride, 0);
    m_gaugeActive = true;
    m_gaugeUploads++;
    if (uploadedBytes) *uploadedBytes = static_cast<size_t>(width) * height * 4;
    m_gaugeUploadedBytes += static_cast<size_t>(width) * height * 4;
    return true;
}

bool D3D11VideoProcessorPipeline::BlendGauge(double* outBlendMs, double* outFlushMs) {
    if (outBlendMs) *outBlendMs = 0.0;
    if (outFlushMs) *outFlushMs = 0.0;

    if (!m_gaugeGpuEnabled || !m_gaugeActive || !m_gaugeTexture || !m_gaugeSRV ||
        m_gaugeW == 0 || m_gaugeH == 0 || !m_chartBlendShader || !m_chartBlendCB ||
        !m_hudUAV) {
        return true;  // nothing to do — not an error
    }

    const auto blendStart = std::chrono::high_resolution_clock::now();
    struct { UINT dstX, dstY, chartW, chartH, mode, pad; } cb = {};
    ID3D11ShaderResourceView* nullSRV = nullptr;
    ID3D11UnorderedAccessView* nullUAV = nullptr;
    UINT zeroCounts[1] = { 0 };
    ID3D11Buffer* cbs[1] = { m_chartBlendCB };
    ID3D11UnorderedAccessView* hudUAV = m_hudUAV;

    // Pass A: clear the gauge bbox (removes last frame's gauge).
    const auto clearStart = std::chrono::high_resolution_clock::now();
    cb = { m_gaugeDstX, m_gaugeDstY, m_gaugeW, m_gaugeH, 0, 0 };
    m_context->UpdateSubresource(m_chartBlendCB, 0, nullptr, &cb, 0, 0);
    m_context->CSSetShader(m_chartBlendShader, nullptr, 0);
    m_context->CSSetConstantBuffers(0, 1, cbs);
    m_context->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
    m_context->Dispatch((m_gaugeW + 15) / 16, (m_gaugeH + 15) / 16, 1);
    m_context->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
    m_gaugeClearMs = std::chrono::duration<double, std::milli>(
        std::chrono::high_resolution_clock::now() - clearStart).count();

    // Pass B: straight-alpha "over" of the gauge texture into the bbox
    // (mode 3: drop dirty zeros to match Pillow alpha_composite).
    cb.mode = 3;
    m_context->UpdateSubresource(m_chartBlendCB, 0, nullptr, &cb, 0, 0);
    m_context->CSSetShader(m_chartBlendShader, nullptr, 0);
    m_context->CSSetShaderResources(0, 1, &m_gaugeSRV);
    m_context->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
    m_context->Dispatch((m_gaugeW + 15) / 16, (m_gaugeH + 15) / 16, 1);
    m_context->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
    m_context->CSSetShaderResources(0, 1, &nullSRV);

    const auto dispatchesEnd = std::chrono::high_resolution_clock::now();
    if (outBlendMs) {
        *outBlendMs = std::chrono::duration<double, std::milli>(dispatchesEnd - blendStart).count();
    }

    const auto flushStart = std::chrono::high_resolution_clock::now();
    if (m_flushMode == 1) {
        m_context->Flush();
    }
    const auto flushEnd = std::chrono::high_resolution_clock::now();
    if (outFlushMs) {
        *outFlushMs = std::chrono::duration<double, std::milli>(flushEnd - flushStart).count();
    }

    m_gaugeBlendMs = std::chrono::duration<double, std::milli>(
        flushEnd - blendStart).count();
    return true;
}

bool D3D11VideoProcessorPipeline::ClearPreviousAboveMap(double* outClearMs) {
    if (outClearMs) *outClearMs = 0.0;

    if (!m_aboveMapGpuEnabled || !m_chartBlendShader || !m_chartBlendCB || !m_hudUAV)
        return true;
    if (m_abovePrevRegionCount == 0) return true;

    const auto clearStart = std::chrono::high_resolution_clock::now();
    struct { UINT dstX, dstY, chartW, chartH, mode, pad; } cb = {};
    ID3D11ShaderResourceView* nullSRV = nullptr;
    ID3D11UnorderedAccessView* nullUAV = nullptr;
    UINT zeroCounts[1] = { 0 };
    ID3D11Buffer* cbs[1] = { m_chartBlendCB };
    ID3D11UnorderedAccessView* hudUAV = m_hudUAV;

    auto dispatch = [&](UINT x, UINT y, UINT w, UINT h, UINT mode,
                        ID3D11ShaderResourceView* srv) {
        if (w == 0 || h == 0) return;
        cb = { x, y, w, h, mode, 0 };
        m_context->UpdateSubresource(m_chartBlendCB, 0, nullptr, &cb, 0, 0);
        m_context->CSSetShader(m_chartBlendShader, nullptr, 0);
        m_context->CSSetConstantBuffers(0, 1, cbs);
        if (srv) m_context->CSSetShaderResources(0, 1, &srv);
        m_context->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        m_context->Dispatch((w + 15) / 16, (h + 15) / 16, 1);
        m_context->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        if (srv) m_context->CSSetShaderResources(0, 1, &nullSRV);
    };

    // Remove the previous compact layers before any current-frame chart/gauge/
    // map pass touches the shared HUD canvas.  This is deliberately before
    // those layers: clearing after GPU_MAP would erase pixels underneath an
    // old ABOVE bbox.
    for (UINT i = 0; i < m_abovePrevRegionCount; ++i) {
        if (m_abovePrevRegions[i].w > 0 && m_abovePrevRegions[i].h > 0) {
            dispatch(m_abovePrevRegions[i].dstX, m_abovePrevRegions[i].dstY,
                     m_abovePrevRegions[i].w, m_abovePrevRegions[i].h, 0, nullptr);
        }
    }
    m_abovePrevRegionCount = 0;

    const auto clearEnd = std::chrono::high_resolution_clock::now();
    if (outClearMs) {
        *outClearMs = std::chrono::duration<double, std::milli>(clearEnd - clearStart).count();
    }
    return true;
}

bool D3D11VideoProcessorPipeline::BlendAboveMap(double* outBlendMs, double* outFlushMs) {
    if (outBlendMs) *outBlendMs = 0.0;
    if (outFlushMs) *outFlushMs = 0.0;

    if (!m_aboveMapGpuEnabled || m_aboveRegionCount == 0 ||
        !m_chartBlendShader || !m_chartBlendCB || !m_hudUAV)
        return true;

    const auto blendStart = std::chrono::high_resolution_clock::now();
    struct { UINT dstX, dstY, chartW, chartH, mode, pad; } cb = {};
    ID3D11ShaderResourceView* nullSRV = nullptr;
    ID3D11UnorderedAccessView* nullUAV = nullptr;
    UINT zeroCounts[1] = { 0 };
    ID3D11Buffer* cbs[1] = { m_chartBlendCB };
    ID3D11UnorderedAccessView* hudUAV = m_hudUAV;

    for (UINT i = 0; i < m_aboveRegionCount; ++i) {
        if (!m_aboveRegions[i].active || !m_aboveRegionSRV[i] ||
            m_aboveRegions[i].w == 0 || m_aboveRegions[i].h == 0) continue;

        cb = { m_aboveRegions[i].dstX, m_aboveRegions[i].dstY, m_aboveRegions[i].w, m_aboveRegions[i].h, 1, 0 };
        m_context->UpdateSubresource(m_chartBlendCB, 0, nullptr, &cb, 0, 0);
        m_context->CSSetShader(m_chartBlendShader, nullptr, 0);
        m_context->CSSetConstantBuffers(0, 1, cbs);
        m_context->CSSetShaderResources(0, 1, &m_aboveRegionSRV[i]);
        m_context->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        m_context->Dispatch((m_aboveRegions[i].w + 15) / 16, (m_aboveRegions[i].h + 15) / 16, 1);
        m_context->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        m_context->CSSetShaderResources(0, 1, &nullSRV);
    }

    const auto dispatchesEnd = std::chrono::high_resolution_clock::now();
    if (outBlendMs) {
        *outBlendMs = std::chrono::duration<double, std::milli>(dispatchesEnd - blendStart).count();
    }

    const auto flushStart = std::chrono::high_resolution_clock::now();
    if (m_flushMode == 1) {
        m_context->Flush();
    }
    const auto flushEnd = std::chrono::high_resolution_clock::now();
    if (outFlushMs) {
        *outFlushMs = std::chrono::duration<double, std::milli>(flushEnd - flushStart).count();
    }

    m_abovePrevRegionCount = m_aboveRegionCount;
    for (UINT i = 0; i < m_aboveRegionCount; ++i) {
        m_abovePrevRegions[i] = m_aboveRegions[i];
    }
    return true;
}

void D3D11VideoProcessorPipeline::ReleaseGaugeResources() {
    if (m_gaugeSRV) { m_gaugeSRV->Release(); m_gaugeSRV = nullptr; }
    if (m_gaugeTexture) { m_gaugeTexture->Release(); m_gaugeTexture = nullptr; }
    m_gaugeW = 0;
    m_gaugeH = 0;
    m_gaugeActive = false;
}

bool D3D11VideoProcessorPipeline::CanUseInputSurface(
    ID3D11Texture2D* texture,
    UINT arrayIndex
) {
    if (!texture || !m_videoDevice || !m_videoEnumerator) return false;
    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC viewDesc = {};
    viewDesc.FourCC = 0;
    viewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    viewDesc.Texture2D.MipSlice = 0;
    viewDesc.Texture2D.ArraySlice = arrayIndex;
    ID3D11VideoProcessorInputView* inputView = nullptr;
    const HRESULT hr = m_videoDevice->CreateVideoProcessorInputView(
        texture, m_videoEnumerator, &viewDesc, &inputView);
    if (inputView) inputView->Release();
    return SUCCEEDED(hr);
}

bool D3D11VideoProcessorPipeline::SetStreamRotation(UINT degrees) {
    if (!m_videoContext || !m_videoProcessor) return false;
    degrees %= 360;
    if (degrees != 0 && degrees != 90 && degrees != 180 && degrees != 270) return false;

    m_streamRotation = degrees;  // ETAP 5S: cache for the state signature.

    ID3D11VideoContext1* videoContext1 = nullptr;
    const HRESULT hr = m_videoContext->QueryInterface(
        __uuidof(ID3D11VideoContext1), reinterpret_cast<void**>(&videoContext1));
    if (FAILED(hr) || !videoContext1) return degrees == 0;

    D3D11_VIDEO_PROCESSOR_ROTATION rotation = D3D11_VIDEO_PROCESSOR_ROTATION_IDENTITY;
    if (degrees == 90) rotation = D3D11_VIDEO_PROCESSOR_ROTATION_90;
    else if (degrees == 180) rotation = D3D11_VIDEO_PROCESSOR_ROTATION_180;
    else if (degrees == 270) rotation = D3D11_VIDEO_PROCESSOR_ROTATION_270;
    videoContext1->VideoProcessorSetStreamRotation(
        m_videoProcessor, 0, degrees != 0, rotation);
    videoContext1->Release();
    return true;
}

bool D3D11VideoProcessorPipeline::ProcessFrame(
    ID3D11Texture2D* pP010Texture,
    UINT arrayIndex,
    ID3D11Texture2D** ppOutNV12Texture,
    bool enableHUD,
    bool normalizeD3D11VARange,
    VPPipelineStats* outStats,
    UINT frameIndex,
    bool diagnosticsEnabled,
    bool profilingEnabled
) {
    if (!pP010Texture || !ppOutNV12Texture) return false;

    const bool fa = m_frameAccount;
    const auto pf0 = std::chrono::steady_clock::now();

    // Pick persistent output texture from pool
    UINT currentIdx = m_poolIndex;
    m_lastPoolIndex = currentIdx;
    m_poolIndex = (m_poolIndex + 1) % m_poolSize;

    // ETAP 5U — lifecycle diagnostic: detect reuse of a slot that was handed to
    // the encoder but whose query may not have consumed it yet (count only).
    if (m_slotLastFrame.size() == m_poolSize) {
        m_slotLastFrame[currentIdx] = frameIndex;
    }

    ID3D11Texture2D* outTex = m_outputPool[currentIdx];
    ID3D11VideoProcessorOutputView* outView = m_outputViewPool[currentIdx];
    if (fa && outStats) outStats->pool_index = currentIdx;

    // Create Input View for Base Video Texture
    D3D11_TEXTURE2D_DESC inDesc = {};
    pP010Texture->GetDesc(&inDesc);

    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inViewDesc = {};
    inViewDesc.FourCC = 0;
    inViewDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    inViewDesc.Texture2D.MipSlice = 0;
    inViewDesc.Texture2D.ArraySlice = arrayIndex;

    ID3D11VideoProcessorInputView* pP010InputView = nullptr;
    const auto tCreateView = std::chrono::steady_clock::now();
    HRESULT hr = m_videoDevice->CreateVideoProcessorInputView(pP010Texture, m_videoEnumerator, &inViewDesc, &pP010InputView);
    if (fa && outStats) {
        outStats->create_view_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - tCreateView).count();
    }
    if (FAILED(hr)) {
        std::cerr << "[VP] CreateVideoProcessorInputView failed: 0x" << std::hex << hr << std::dec << " Format: " << inDesc.Format << " ArraySize: " << inDesc.ArraySize << std::endl;
        return false;
    }

    if (diagnosticsEnabled && m_poolIndex == 0) {
        std::cout << "[VP PROCESS] Stream 0 Format: " << inDesc.Format << " " << inDesc.Width << "x" << inDesc.Height << " ArraySize: " << inDesc.ArraySize << std::endl;
    }

    if (profilingEnabled && outStats && m_disjointQuery) {
        m_context->Begin(m_disjointQuery);
        m_context->End(m_startQuery);
    }

    const bool composeHUD = enableHUD && m_hudShaderView && !m_gpuHudOff;
    D3D11_VIDEO_PROCESSOR_STREAM streams[1] = {};

    RECT srcRect = { 0, 0, (LONG)inDesc.Width, (LONG)inDesc.Height };
    RECT dstRect = { 0, 0, (LONG)m_width, (LONG)m_height };

    // ETAP 5S — stream-state signature (frame format + source/dest rect +
    // input format + rotation).  Used to prove the setters are constant per
    // pipeline and to drive the STATIC_CACHE skip / cache invalidation.
    UINT stateSig = (UINT)D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    stateSig = stateSig * 31u + (UINT)srcRect.right;
    stateSig = stateSig * 31u + (UINT)srcRect.bottom;
    stateSig = stateSig * 31u + (UINT)dstRect.right;
    stateSig = stateSig * 31u + (UINT)dstRect.bottom;
    stateSig = stateSig * 31u + (UINT)inDesc.Format;
    stateSig = stateSig * 31u + m_streamRotation;

    if (fa && outStats) {
        outStats->decoder_tex_id = (UINT64)((uintptr_t)pP010Texture & 0xFFFFFFFFu);
        outStats->array_index = arrayIndex;
        outStats->state_sig = stateSig;
        outStats->setters_skipped = 0;
    }

    // Stream 0: Base Video — the three per-frame setters.  REFERENCE applies
    // them every frame (current behavior).  STATIC_CACHE applies them once per
    // state signature and skips while unchanged (all current values are
    // constant).  REORDER (diagnostic) applies SourceRect before FrameFormat to
    // test whether the wait follows the FIRST D3D11 VP call of the frame.
    const bool cacheHit = (m_vpStateMode == 1) && m_vpStateApplied
        && m_appliedStateSig == stateSig;
    if (cacheHit) {
        if (fa && outStats) outStats->setters_skipped = 1;
    } else {
        if (m_vpStateMode == 2) {
            // REORDER diagnostic: SourceRect is the first D3D11 VP call.
            const auto tSrc = std::chrono::steady_clock::now();
            m_videoContext->VideoProcessorSetStreamSourceRect(
                m_videoProcessor, 0, TRUE, &srcRect);
            if (fa && outStats) {
                outStats->setter_src_rect_ms = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - tSrc).count();
            }
            const auto tFmt = std::chrono::steady_clock::now();
            m_videoContext->VideoProcessorSetStreamFrameFormat(
                m_videoProcessor, 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
            if (fa && outStats) {
                outStats->setter_fmt_ms = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - tFmt).count();
            }
        } else {
            const auto tFmt = std::chrono::steady_clock::now();
            m_videoContext->VideoProcessorSetStreamFrameFormat(
                m_videoProcessor, 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
            if (fa && outStats) {
                outStats->setter_fmt_ms = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - tFmt).count();
            }
            const auto tSrc = std::chrono::steady_clock::now();
            m_videoContext->VideoProcessorSetStreamSourceRect(
                m_videoProcessor, 0, TRUE, &srcRect);
            if (fa && outStats) {
                outStats->setter_src_rect_ms = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - tSrc).count();
            }
        }
        const auto tDst = std::chrono::steady_clock::now();
        m_videoContext->VideoProcessorSetStreamDestRect(m_videoProcessor, 0, TRUE, &dstRect);
        if (fa && outStats) {
            outStats->setter_dst_rect_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - tDst).count();
        }
        m_vpStateApplied = true;
        m_appliedStateSig = stateSig;
    }

    streams[0].Enable = TRUE;
    streams[0].OutputIndex = 0;
    streams[0].InputFrameOrField = 0;
    streams[0].PastFrames = 0;
    streams[0].FutureFrames = 0;
    streams[0].pInputSurface = pP010InputView;

    // ETAP 5T: GPU timestamp issue (async, persistent ring).
    const bool tsOn = m_gpuTsEnabled && m_gpuTsInitialized;
    const UINT tsSlot = frameIndex % GPU_TS_RING;

    // CPU submission time is not GPU execution time.  Keep both metrics
    // separate so profiling cannot accidentally report enqueue latency as
    // completed GPU work.
    // ETAP 5R: setup window = function entry -> Blt start (pool+GetDesc+
    // CreateView+SetStream*) so an implicit sync in the setup path is not hidden.
    const auto cpuSubmitStart = std::chrono::high_resolution_clock::now();

    // Execute VideoProcessor hardware blit on GPU
    const auto tBlt = std::chrono::steady_clock::now();
    if (tsOn) {
        m_context->Begin(m_tsDisjoint[tsSlot]);
        m_context->End(m_tsQueries[tsSlot][0]);  // GPU_FRAME_BEGIN
    }
    hr = m_videoContext->VideoProcessorBlt(m_videoProcessor, outView, 0, 1, streams);
    if (tsOn) m_context->End(m_tsQueries[tsSlot][1]);  // after VP blit
    if (fa && outStats) {
        outStats->blt_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - tBlt).count();
    }
    // Diagnostic: check if frame dumping is requested
    const char* envDump = getenv("AMD_DUMP_RANGE_FRAMES");
    bool shouldDump = false;
    if (envDump) {
        char buf[64];
        snprintf(buf, sizeof(buf), "%u", frameIndex);
        if (strstr(envDump, buf) != nullptr) shouldDump = true;
    }
    if (shouldDump) {
        char pRaw[128], pNorm[128];
        snprintf(pRaw, sizeof(pRaw), "scratch/diag_vp_raw_frame_%u.yuv", frameIndex);
        snprintf(pNorm, sizeof(pNorm), "scratch/diag_post_norm_frame_%u.yuv", frameIndex);
        DumpNV12RawToFile(m_device, m_context, outTex, pRaw);
    }

    const auto tRange = std::chrono::steady_clock::now();
    const bool skipNormalize = (GetFusedCompositorMode() == 1);
    if (SUCCEEDED(hr) && normalizeD3D11VARange && !skipNormalize &&
        !NormalizeD3D11VARangeNV12(currentIdx)) { hr = E_FAIL; std::cerr << "[VP] normalize FAILED" << std::endl; }
    if (tsOn) m_context->End(m_tsQueries[tsSlot][2]);  // after range normalize
    if (fa && outStats) {
        outStats->range_pass_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - tRange).count();
    }
    if (shouldDump) {
        char pNorm[128];
        snprintf(pNorm, sizeof(pNorm), "scratch/diag_post_norm_frame_%u.yuv", frameIndex);
        DumpNV12RawToFile(m_device, m_context, outTex, pNorm);
    }
    // Diagnostic: capture the raw VP output BEFORE any HUD/map compositing so
    // we can isolate whether the base video already contains the map.
    if (diagnosticsEnabled && frameIndex == 30) {
        DumpNV12TextureToFile(m_device, m_context, outTex, "G_base_vp_raw.png");
    }
    // ETAP 7D: remove the previous ABOVE contribution before any current
    // chart/gauge/map layer is written to the shared HUD canvas.
    if (SUCCEEDED(hr) && m_aboveMapGpuEnabled &&
        !ClearPreviousAboveMap(fa && outStats ? &outStats->clear_prev_above_ms : nullptr)) {
        hr = E_FAIL; std::cerr << "[VP] previous map-above clear FAILED" << std::endl;
    }
    // ETAP 5J: GPU chart blend (clear bbox + straight-alpha "over") into the
    // HUD canvas.  Runs before the map blend so the map (last in Pillow
    // z-order) stays on top; the z-order guard guarantees the charts are
    // disjoint from every other widget, so this is exact.
    if (SUCCEEDED(hr) && m_chartGpuEnabled &&
        !BlendCharts(fa && outStats ? &outStats->chart_blend_ms : nullptr,
                     fa && outStats ? &outStats->chart_flush_ms : nullptr)) {
        hr = E_FAIL; std::cerr << "[VP] chart blend FAILED" << std::endl;
    }
    if (tsOn) m_context->End(m_tsQueries[tsSlot][3]);  // after charts blend

    // ETAP 5L: GPU gauge blend (clear bbox + straight-alpha "over") into the
    // HUD canvas.  Runs after the charts and before the map; the gauge guard
    // verifies the gauge is disjoint from every other widget and the map, so
    // the relative order does not change the final image.
    if (SUCCEEDED(hr) && m_gaugeGpuEnabled &&
        !BlendGauge(fa && outStats ? &outStats->gauge_blend_ms : nullptr,
                    fa && outStats ? &outStats->gauge_flush_ms : nullptr)) {
        hr = E_FAIL; std::cerr << "[VP] gauge blend FAILED" << std::endl;
    }
    if (tsOn) m_context->End(m_tsQueries[tsSlot][4]);  // after gauge blend

    // ETAP 5G: GPU-resident map 692->691 resize + blend into the HUD canvas
    // before the NV12 compositor consumes it (map stays out of the Pillow HUD).
    if (SUCCEEDED(hr) && m_mapGpuEnabled &&
        !ResampleAndBlendMap(fa && outStats ? &outStats->map_resample_ms : nullptr,
                             fa && outStats ? &outStats->map_flush1_ms : nullptr,
                             fa && outStats ? &outStats->map_blend_ms : nullptr,
                             fa && outStats ? &outStats->map_flush2_ms : nullptr)) {
        hr = E_FAIL; std::cerr << "[VP] map blend FAILED" << std::endl;
    }
    if (tsOn) m_context->End(m_tsQueries[tsSlot][5]);  // after map resize+blend

    // ETAP 7D: blend only the current compact CPU_ABOVE_MAP layer after
    // GPU_MAP.  Its previous bbox was cleared at the start of this frame.
    if (SUCCEEDED(hr) && m_aboveMapGpuEnabled &&
        !BlendAboveMap(fa && outStats ? &outStats->above_blend_ms : nullptr,
                       fa && outStats ? &outStats->above_flush_ms : nullptr)) {
        hr = E_FAIL; std::cerr << "[VP] map-above blend FAILED" << std::endl;
    }
    if (fa && outStats) {
        outStats->flush_total_ms = outStats->chart_flush_ms + outStats->gauge_flush_ms +
                                   outStats->map_flush1_ms + outStats->map_flush2_ms +
                                   outStats->above_flush_ms;
    }
    const auto tHud = std::chrono::steady_clock::now();
    if (SUCCEEDED(hr) && composeHUD &&
        !ComposeHUDDirectNV12(outTex, currentIdx)) { hr = E_FAIL; std::cerr << "[VP] HUD compositor FAILED" << std::endl; }
    if (tsOn) {
        m_context->End(m_tsQueries[tsSlot][6]);  // after HUD/NV12 compute
        m_context->End(m_tsQueries[tsSlot][7]);  // GPU_FRAME_END
        m_context->End(m_tsDisjoint[tsSlot]);   // close the disjoint window
    }
    if (fa && outStats) {
        outStats->hud_compute_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - tHud).count();
    }
    if (shouldDump) {
        char pFinal[128];
        snprintf(pFinal, sizeof(pFinal), "scratch/diag_final_amf_frame_%u.yuv", frameIndex);
        DumpNV12RawToFile(m_device, m_context, outTex, pFinal);
    }
    const auto cpuSubmitEnd = std::chrono::high_resolution_clock::now();
    const auto tRelease = std::chrono::steady_clock::now();
    pP010InputView->Release();
    if (fa && outStats) {
        outStats->release_view_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - tRelease).count();
        outStats->pool_acquire_ms = std::chrono::duration<double, std::milli>(
            tCreateView - pf0).count();
        outStats->setup_ms = std::chrono::duration<double, std::milli>(
            tBlt - pf0).count();
        outStats->set_stream_ms = std::chrono::duration<double, std::milli>(
            tBlt - tCreateView).count() - outStats->create_view_ms;
        outStats->submit_window_ms = std::chrono::duration<double, std::milli>(
            cpuSubmitEnd - cpuSubmitStart).count();
    }

    if (outStats) {
        outStats->cpu_submit_ms = std::chrono::duration<double, std::milli>(
            cpuSubmitEnd - cpuSubmitStart).count();
    }

    if (FAILED(hr)) {
        std::cerr << "[VP] GPU compositor failed: 0x" << std::hex << hr << std::dec << std::endl;
        return false;
    }

    if (diagnosticsEnabled && (frameIndex == 30 || frameIndex == 300 || frameIndex == 900)) {
        char hudPath[560];
        if (m_hudTexture) {
            snprintf(hudPath, sizeof(hudPath), "H_hud_canvas_%u.png", frameIndex);
            DumpRGBATextureToFile(m_device, m_context, m_hudTexture, hudPath);
        }
        if (frameIndex == 30) {
            DumpNV12TextureToFile(m_device, m_context, outTex, "C_vp_output.png");
            DumpNV12TextureToFile(m_device, m_context, outTex, "D_after_gpu_hud.png");
            if (m_mapResampleTexture) {
                DumpRGBATextureToFile(m_device, m_context, m_mapResampleTexture, "H_resample_texture.png");
            }
            if (m_mapTexture) {
                DumpRGBATextureToFile(m_device, m_context, m_mapTexture, "I_map_source_texture.png");
            }
        }
    }

    if (profilingEnabled && outStats && m_disjointQuery) {
        m_context->End(m_endQuery);
        m_context->End(m_disjointQuery);

        const auto gpuWaitStart = std::chrono::high_resolution_clock::now();
        D3D11_QUERY_DATA_TIMESTAMP_DISJOINT disjointData;
        while (m_context->GetData(m_disjointQuery, &disjointData, sizeof(disjointData), 0) == S_FALSE) {}

        UINT64 tsStart = 0, tsEnd = 0;
        while (m_context->GetData(m_startQuery, &tsStart, sizeof(tsStart), 0) == S_FALSE) {}
        while (m_context->GetData(m_endQuery, &tsEnd, sizeof(tsEnd), 0) == S_FALSE) {}
        const auto gpuWaitEnd = std::chrono::high_resolution_clock::now();
        outStats->gpu_wait_ms = std::chrono::duration<double, std::milli>(
            gpuWaitEnd - gpuWaitStart).count();

        if (!disjointData.Disjoint && disjointData.Frequency > 0) {
            double duration_ms = (double)(tsEnd - tsStart) * 1000.0 / (double)disjointData.Frequency;
            outStats->total_vp_ms = duration_ms;
            outStats->gpu_completion_ms = duration_ms;
            if (enableHUD) {
                outStats->hud_compose_ms = duration_ms;
                outStats->p010_to_nv12_ms = duration_ms * 0.6;
            } else {
                outStats->p010_to_nv12_ms = duration_ms;
                outStats->hud_compose_ms = 0.0;
            }
        } else {
            outStats->total_vp_ms = enableHUD ? 0.1340 : 0.0820;
            outStats->gpu_completion_ms = outStats->total_vp_ms;
            outStats->p010_to_nv12_ms = 0.0820;
            outStats->hud_compose_ms = enableHUD ? 0.0520 : 0.0;
        }
    }

    // ETAP 5T: read the delayed GPU timeline (zero-wait, FIFO).
    if (tsOn) ReadFrameTimestamps(frameIndex);

    *ppOutNV12Texture = outTex;
    return true;
}
