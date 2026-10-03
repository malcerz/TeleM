#include "d3d11_amf_encoder.h"

D3D11AMFEncoder::D3D11AMFEncoder() {}

void D3D11AMFEncoder::Shutdown() {
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

D3D11AMFEncoder::~D3D11AMFEncoder() {
    Shutdown();
}

bool D3D11AMFEncoder::Initialize(
    ID3D11Device* pDevice,
    UINT width,
    UINT height,
    UINT fpsNum,
    UINT fpsDen,
    AMFCodecType codecType,
    AMFQualityPreset qualityPreset,
    uint64_t bitrateBps
) {
    m_device = pDevice;
    m_width = width;
    m_height = height;
    m_codecType = codecType;
    m_qualityPreset = qualityPreset;
    m_bitrateBps = bitrateBps;

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

    if (m_codecType == AMFCodecType::AVC) {
        // Create AMF AVC/H.264 Encoder Component
        res = m_factory->CreateComponent(m_context, AMFVideoEncoderVCE_AVC, &m_encoder);
        if (res != AMF_OK || !m_encoder) {
            std::cerr << "[AMF] CreateComponent(AMFVideoEncoderVCE_AVC) failed: " << res << std::endl;
            return false;
        }

        m_encoder->SetProperty(AMF_VIDEO_ENCODER_USAGE, AMF_VIDEO_ENCODER_USAGE_TRANSCODING);

        // Quality presets for AVC from AMF_VIDEO_ENCODER_QUALITY_PRESET_ENUM:
        // BALANCED = 0, SPEED = 1, QUALITY = 2
        amf_int64 avcPreset = AMF_VIDEO_ENCODER_QUALITY_PRESET_SPEED;
        const char* presetName = "SPEED";
        if (m_qualityPreset == AMFQualityPreset::BALANCED) {
            avcPreset = AMF_VIDEO_ENCODER_QUALITY_PRESET_BALANCED;
            presetName = "BALANCED";
        } else if (m_qualityPreset == AMFQualityPreset::QUALITY) {
            avcPreset = AMF_VIDEO_ENCODER_QUALITY_PRESET_QUALITY;
            presetName = "QUALITY";
        }
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_QUALITY_PRESET, avcPreset);

        // Profile: High, Level 5.2
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_PROFILE, AMF_VIDEO_ENCODER_PROFILE_HIGH);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_PROFILE_LEVEL, AMF_H264_LEVEL__5_2);

        // Rate control & Bitrate
        if (m_bitrateBps > 0) {
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_RATE_CONTROL_METHOD, AMF_VIDEO_ENCODER_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_TARGET_BITRATE, (amf_int64)m_bitrateBps);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_PEAK_BITRATE, (amf_int64)(m_bitrateBps * 1.25));
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_VBV_BUFFER_SIZE, (amf_int64)m_bitrateBps);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_INITIAL_VBV_BUFFER_FULLNESS, (amf_int64)64);
        } else {
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_RATE_CONTROL_METHOD, AMF_VIDEO_ENCODER_RATE_CONTROL_METHOD_CONSTANT_QP);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_QP_I, (amf_int64)26);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_QP_P, (amf_int64)26);
        }

        m_encoder->SetProperty(AMF_VIDEO_ENCODER_FRAMESIZE, AMFConstructSize(width, height));
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_FRAMERATE, AMFConstructRate(fpsNum, fpsDen));

        // Color metadata: BT.709 8-bit SDR
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_OUTPUT_COLOR_PROFILE, AMF_VIDEO_CONVERTER_COLOR_PROFILE_709);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_OUTPUT_COLOR_PRIMARIES, AMF_COLOR_PRIMARIES_BT709);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_OUTPUT_TRANSFER_CHARACTERISTIC, AMF_COLOR_TRANSFER_CHARACTERISTIC_BT709);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_OUTPUT_MATRIX_COEFF, AMF_COLOR_MATRIX_COEFF_BT_709);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_OUTPUT_FULL_RANGE_COLOR, false);

        res = m_encoder->Init(amf::AMF_SURFACE_NV12, width, height);
        if (res != AMF_OK) {
            std::cerr << "[AMF] AVC Encoder Init(AMF_SURFACE_NV12) failed: " << res << std::endl;
            return false;
        }

        std::cout << "[AMF] H.264/AVC Hardware Encoder initialized successfully (" 
                  << width << "x" << height << " preset=" << presetName 
                  << " raw_amf_preset=" << avcPreset << ")." << std::endl;
    } else if (m_codecType == AMFCodecType::AV1) {
        // Create AMF AV1 Encoder Component
        res = m_factory->CreateComponent(m_context, AMFVideoEncoder_AV1, &m_encoder);
        if (res != AMF_OK || !m_encoder) {
            std::cerr << "[AMF] CreateComponent(AMFVideoEncoder_AV1) failed: " << res << std::endl;
            return false;
        }

        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_USAGE, AMF_VIDEO_ENCODER_AV1_USAGE_TRANSCODING);

        // Quality presets for AV1 from AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_ENUM:
        // HIGH_QUALITY = 0, QUALITY = 30, BALANCED = 70, SPEED = 100
        amf_int64 av1Preset = AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_SPEED;
        const char* presetName = "SPEED";
        if (m_qualityPreset == AMFQualityPreset::BALANCED) {
            av1Preset = AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_BALANCED;
            presetName = "BALANCED";
        } else if (m_qualityPreset == AMFQualityPreset::QUALITY) {
            av1Preset = AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_QUALITY;
            presetName = "QUALITY";
        }

        // Developer override for AV1 quality preset:
        // TELEM_AMD_AV1_QUALITY_PRESET=HIGH_QUALITY (or 0)
        const char* av1Override = std::getenv("TELEM_AMD_AV1_QUALITY_PRESET");
        if (av1Override && m_qualityPreset == AMFQualityPreset::QUALITY) {
            if (_stricmp(av1Override, "HIGH_QUALITY") == 0 || std::strcmp(av1Override, "0") == 0) {
                av1Preset = AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET_HIGH_QUALITY;
                presetName = "HIGH_QUALITY (override)";
            }
        }

        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_QUALITY_PRESET, av1Preset);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_PROFILE, AMF_VIDEO_ENCODER_AV1_PROFILE_MAIN);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_ALIGNMENT_MODE, AMF_VIDEO_ENCODER_AV1_ALIGNMENT_MODE_NO_RESTRICTIONS);

        // Rate control & Bitrate
        if (m_bitrateBps > 0) {
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_RATE_CONTROL_METHOD, AMF_VIDEO_ENCODER_AV1_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_TARGET_BITRATE, (amf_int64)m_bitrateBps);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_PEAK_BITRATE, (amf_int64)(m_bitrateBps * 1.25));
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_VBV_BUFFER_SIZE, (amf_int64)m_bitrateBps);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_INITIAL_VBV_BUFFER_FULLNESS, (amf_int64)64);
        } else {
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_RATE_CONTROL_METHOD, AMF_VIDEO_ENCODER_AV1_RATE_CONTROL_METHOD_CONSTANT_QP);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_Q_INDEX_INTRA, (amf_int64)112);
            m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_Q_INDEX_INTER, (amf_int64)112);
        }

        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_FRAMESIZE, AMFConstructSize(width, height));
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_FRAMERATE, AMFConstructRate(fpsNum, fpsDen));

        // Color metadata: BT.709 8-bit SDR (NV12 production pipeline)
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_COLOR_BIT_DEPTH, AMF_COLOR_BIT_DEPTH_8);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_OUTPUT_COLOR_PROFILE, AMF_VIDEO_CONVERTER_COLOR_PROFILE_709);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_OUTPUT_COLOR_PRIMARIES, AMF_COLOR_PRIMARIES_BT709);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_OUTPUT_TRANSFER_CHARACTERISTIC, AMF_COLOR_TRANSFER_CHARACTERISTIC_BT709);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_OUTPUT_MATRIX_COEFF, AMF_COLOR_MATRIX_COEFF_BT_709);
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_AV1_OUTPUT_FULL_RANGE_COLOR, false);

        res = m_encoder->Init(amf::AMF_SURFACE_NV12, width, height);
        if (res != AMF_OK) {
            std::cerr << "[AMF] AV1 Encoder Init(AMF_SURFACE_NV12) failed: " << res << std::endl;
            return false;
        }

        std::cout << "[AMF] AV1 Hardware Encoder initialized successfully (" 
                  << width << "x" << height << " preset=" << presetName 
                  << " raw_amf_preset=" << av1Preset << ")." << std::endl;
    } else {
        // Create AMF HEVC Encoder Component
        res = m_factory->CreateComponent(m_context, AMFVideoEncoder_HEVC, &m_encoder);
        if (res != AMF_OK || !m_encoder) {
            std::cerr << "[AMF] CreateComponent(AMFVideoEncoder_HEVC) failed: " << res << std::endl;
            return false;
        }

        m_encoder->SetProperty(AMF_VIDEO_ENCODER_HEVC_USAGE, AMF_VIDEO_ENCODER_HEVC_USAGE_TRANSCODING);

        // Quality presets for HEVC from AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_ENUM:
        // QUALITY = 0, BALANCED = 5, SPEED = 10
        amf_int64 hevcPreset = AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED;
        const char* presetName = "SPEED";
        if (m_qualityPreset == AMFQualityPreset::BALANCED) {
            hevcPreset = AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_BALANCED;
            presetName = "BALANCED";
        } else if (m_qualityPreset == AMFQualityPreset::QUALITY) {
            hevcPreset = AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_QUALITY;
            presetName = "QUALITY";
        }
        m_encoder->SetProperty(AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET, hevcPreset);

        // Preserve exact existing HEVC rate control behavior
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

        std::cout << "[AMF] HEVC Hardware Encoder initialized successfully (" 
                  << width << "x" << height << " preset=" << presetName 
                  << " raw_amf_preset=" << hevcPreset << ")." << std::endl;
    }
    return true;
}

bool D3D11AMFEncoder::CreateSurface(ID3D11Texture2D* pNV12Texture, int64_t pts, amf::AMFSurfacePtr& outSurface, double* outCreateMs) {
    if (!m_context || !pNV12Texture) return false;
    const auto tCreate = std::chrono::steady_clock::now();
    AMF_RESULT res = m_context->CreateSurfaceFromDX11Native((void*)pNV12Texture, &outSurface, nullptr);
    if (outCreateMs) {
        *outCreateMs = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - tCreate).count();
    }
    if (res != AMF_OK || !outSurface) {
        std::cerr << "[AMF] CreateSurfaceFromDX11Native failed: " << res << std::endl;
        return false;
    }
    outSurface->SetPts(pts);
    return true;
}

AMF_RESULT D3D11AMFEncoder::SubmitSurface(amf::AMFSurface* pSurface, AMFEncoderStats* outStats) {
    if (!m_encoder || !pSurface) return AMF_NOT_INITIALIZED;
    const auto tSubmit = std::chrono::steady_clock::now();
    AMF_RESULT res = m_encoder->SubmitInput(pSurface);
    if (outStats) {
        outStats->submit_input_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - tSubmit).count();
        outStats->result = res;
        outStats->input_full = (res == AMF_INPUT_FULL);
    }
    return res;
}

bool D3D11AMFEncoder::SubmitTexture(ID3D11Texture2D* pNV12Texture, int64_t pts, AMFEncoderStats* outStats) {
    if (!m_encoder || !pNV12Texture) return false;
    auto tStart = std::chrono::high_resolution_clock::now();

    amf::AMFSurfacePtr pSurface;
    double createMs = 0.0;
    if (!CreateSurface(pNV12Texture, pts, pSurface, &createMs)) return false;
    if (outStats) outStats->create_surface_ms = createMs;

    AMF_RESULT res = SubmitSurface(pSurface, outStats);
    if (outStats) {
        auto tEnd = std::chrono::high_resolution_clock::now();
        outStats->submit_ms = std::chrono::duration<double, std::milli>(tEnd - tStart).count();
    }
    if (res == AMF_INPUT_FULL) {
        return false;
    }
    if (res != AMF_OK) {
        std::cerr << "[AMF] SubmitInput failed: " << res << std::endl;
        return false;
    }
    return true;
}

bool D3D11AMFEncoder::QueryPacket(
    std::vector<uint8_t>& outData,
    int64_t& outPts,
    bool& outIsKeyframe,
    AMF_RESULT* outResult,
    double* outQueryMs
) {
    if (!m_encoder) return false;

    const auto tStart = std::chrono::high_resolution_clock::now();
    amf::AMFDataPtr pData;
    AMF_RESULT res = m_encoder->QueryOutput(&pData);
    const auto tEnd = std::chrono::high_resolution_clock::now();
    if (outResult) *outResult = res;
    if (outQueryMs) {
        *outQueryMs = std::chrono::duration<double, std::milli>(tEnd - tStart).count();
    }
    if (res == AMF_OK && pData != nullptr) {
        amf::AMFBufferPtr pBuffer(pData);
        if (pBuffer != nullptr) {
            void* pMem = pBuffer->GetNative();
            size_t size = pBuffer->GetSize();

            outData.resize(size);
            memcpy(outData.data(), pMem, size);

            outPts = pBuffer->GetPts();

            int64_t dataType = 0;
            if (m_codecType == AMFCodecType::AVC) {
                pBuffer->GetProperty(AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE, &dataType);
                outIsKeyframe = (dataType == AMF_VIDEO_ENCODER_OUTPUT_DATA_TYPE_IDR);
            } else if (m_codecType == AMFCodecType::AV1) {
                pBuffer->GetProperty(AMF_VIDEO_ENCODER_AV1_OUTPUT_FRAME_TYPE, &dataType);
                outIsKeyframe = (dataType == AMF_VIDEO_ENCODER_AV1_OUTPUT_FRAME_TYPE_KEY);
            } else {
                pBuffer->GetProperty(AMF_VIDEO_ENCODER_HEVC_OUTPUT_DATA_TYPE, &dataType);
                outIsKeyframe = (dataType == AMF_VIDEO_ENCODER_HEVC_OUTPUT_DATA_TYPE_IDR);
            }

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
