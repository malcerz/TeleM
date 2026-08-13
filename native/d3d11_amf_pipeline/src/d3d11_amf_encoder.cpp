#include "d3d11_amf_encoder.h"

D3D11AMFEncoder::D3D11AMFEncoder() {}

D3D11AMFEncoder::~D3D11AMFEncoder() {
    if (m_encoder != nullptr) {
        m_encoder->Drain();
        m_encoder->Terminate();
        m_encoder = nullptr;
    }
    if (m_context != nullptr) {
        m_context->Terminate();
        m_context = nullptr;
    }
    if (m_hAMFRT != nullptr) {
        FreeLibrary(m_hAMFRT);
        m_hAMFRT = nullptr;
    }
}

bool D3D11AMFEncoder::Initialize(ID3D11Device* pDevice, UINT width, UINT height, UINT fpsNum, UINT fpsDen) {
    m_device = pDevice;
    m_width = width;
    m_height = height;

    // Load AMD AMF Runtime DLL
    m_hAMFRT = LoadLibraryW(L"amfrt64.dll");
    if (!m_hAMFRT) {
        std::cerr << "[AMF] Failed to load amfrt64.dll from system!" << std::endl;
        return false;
    }

    AMFInit_Fn pAMFInit = (AMFInit_Fn)GetProcAddress(m_hAMFRT, AMF_INIT_FUNCTION_NAME);
    if (!pAMFInit) {
        std::cerr << "[AMF] Failed to get AMFInit proc address!" << std::endl;
        return false;
    }

    AMF_RESULT res = pAMFInit(AMF_FULL_VERSION, &m_factory);
    if (res != AMF_OK || !m_factory) {
        std::cerr << "[AMF] AMFInit failed with result: " << res << std::endl;
        return false;
    }

    res = m_factory->CreateContext(&m_context);
    if (res != AMF_OK || !m_context) {
        std::cerr << "[AMF] CreateContext failed with result: " << res << std::endl;
        return false;
    }

    // Initialize AMF on the EXACT SAME D3D11 DEVICE
    res = m_context->InitDX11(m_device);
    if (res != AMF_OK) {
        std::cerr << "[AMF] InitDX11 on shared D3D11 device failed: " << res << std::endl;
        return false;
    }
    m_sameDeviceUsed = true;
    std::cout << "[AMF] InitDX11 SUCCESS: Connected to SAME ID3D11Device." << std::endl;

    // Create AMF HEVC Encoder Component
    res = m_factory->CreateComponent(m_context, AMFVideoEncoder_HEVC, &m_encoder);
    if (res != AMF_OK || !m_encoder) {
        std::cerr << "[AMF] CreateComponent(AMFVideoEncoder_HEVC) failed: " << res << std::endl;
        return false;
    }

    // Configure Encoder Properties matching prompt requirements:
    // HEVC, quality = speed, rate control = CQP, QP P = 28, QP I = 28, 3840x2160 @ 29.97 FPS
    m_encoder->SetProperty(AMF_VIDEO_ENCODER_HEVC_USAGE, AMF_VIDEO_ENCODER_HEVC_USAGE_TRANSCODING);
    m_encoder->SetProperty(AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET, AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED);
    m_encoder->SetProperty(AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD, AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_CONSTANT_QP);
    m_encoder->SetProperty(AMF_VIDEO_ENCODER_HEVC_QP_I, 28);
    m_encoder->SetProperty(AMF_VIDEO_ENCODER_HEVC_QP_P, 28);
    m_encoder->SetProperty(AMF_VIDEO_ENCODER_HEVC_FRAMESIZE, AMFConstructSize(width, height));
    m_encoder->SetProperty(AMF_VIDEO_ENCODER_HEVC_FRAMERATE, AMFConstructRate(fpsNum, fpsDen));

    res = m_encoder->Init(amf::AMF_SURFACE_NV12, width, height);
    if (res != AMF_OK) {
        std::cerr << "[AMF] Encoder Init(AMF_SURFACE_NV12) failed: " << res << std::endl;
        return false;
    }

    std::cout << "[AMF] HEVC Hardware Encoder initialized successfully (3840x2160 CQP 28/28 Speed)." << std::endl;
    return true;
}

bool D3D11AMFEncoder::SubmitTexture(ID3D11Texture2D* pNV12Texture, int64_t pts, AMFEncoderStats* outStats) {
    if (!m_encoder || !pNV12Texture) return false;

    auto tStart = std::chrono::high_resolution_clock::now();

    amf::AMFSurfacePtr pSurface;
    // DIRECT GPU HANDOFF: Wraps ID3D11Texture2D directly into AMFSurface without CPU intermediate!
    AMF_RESULT res = m_context->CreateSurfaceFromDX11Native((void*)pNV12Texture, &pSurface, nullptr);
    if (res != AMF_OK || !pSurface) {
        std::cerr << "[AMF] CreateSurfaceFromDX11Native failed: " << res << std::endl;
        return false;
    }

    pSurface->SetPts(pts);

    // Submit input surface to AMD VCE/VCN hardware encoder engine
    res = m_encoder->SubmitInput(pSurface);
    if (res != AMF_OK && res != AMF_INPUT_FULL) {
        std::cerr << "[AMF] SubmitInput failed: " << res << std::endl;
        return false;
    }

    auto tEnd = std::chrono::high_resolution_clock::now();
    if (outStats) {
        outStats->submit_ms = std::chrono::duration<double, std::milli>(tEnd - tStart).count();
    }

    return true;
}

bool D3D11AMFEncoder::QueryPacket(std::vector<uint8_t>& outData, int64_t& outPts, bool& outIsKeyframe) {
    if (!m_encoder) return false;

    amf::AMFDataPtr pData;
    AMF_RESULT res = m_encoder->QueryOutput(&pData);
    if (res == AMF_OK && pData != nullptr) {
        amf::AMFBufferPtr pBuffer(pData);
        if (pBuffer != nullptr) {
            void* pMem = pBuffer->GetNative();
            size_t size = pBuffer->GetSize();

            outData.resize(size);
            memcpy(outData.data(), pMem, size);

            outPts = pBuffer->GetPts();

            int64_t dataType = 0;
            pBuffer->GetProperty(AMF_VIDEO_ENCODER_HEVC_OUTPUT_DATA_TYPE, &dataType);
            outIsKeyframe = (dataType == AMF_VIDEO_ENCODER_HEVC_OUTPUT_DATA_TYPE_IDR);

            return true;
        }
    }
    return false;
}

bool D3D11AMFEncoder::Flush() {
    if (m_encoder) {
        m_encoder->Drain();
    }
    return true;
}
