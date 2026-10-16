#pragma once

#include <d3d11.h>
#include <vector>
#include <string>
#include <iostream>
#include <chrono>
#include <windows.h>

#include "AMF/core/Factory.h"
#include "AMF/core/Context.h"
#include "AMF/components/VideoEncoderHEVC.h"
#include "AMF/components/VideoEncoderVCE.h"
#include "AMF/components/VideoEncoderAV1.h"

enum class AMFCodecType {
    HEVC = 0,
    AVC = 1,
    AV1 = 2
};

enum class AMFQualityPreset {
    FAST = 0,
    BALANCED = 1,
    QUALITY = 2
};

struct AMFEncoderStats {
    double submit_ms = 0.0;
    double create_surface_ms = 0.0;   // ETAP 5R
    double submit_input_ms = 0.0;     // ETAP 5R
    double query_ms = 0.0;
    size_t output_bytes = 0;
    bool input_full = false;
    AMF_RESULT result = AMF_OK;
};

// Series of per-frame AMF_VIDEO_ENCODER_HEVC_STATISTIC_AVERAGE_QP (average QP
// of encoded CTBs in one picture); samples are real encoder outputs only.
struct AMFEncoderQPStats {
    uint64_t samples = 0;
    double sum = 0.0;
    int64_t minQp = -1;
    int64_t maxQp = -1;
    int64_t lastQp = -1;
    bool supported = false;
};

// Raw HEVC statistics-feedback diagnostics (AMF_RESULT of every step).
struct AMFEncoderQPFeedbackDiag {
    int encoderSetResult = -1;        // SetProperty(STATISTICS_FEEDBACK) on encoder
    int surfaceSetResult = -1;        // last SetProperty(STATISTICS_FEEDBACK) on input surface
    uint64_t surfaceSetOk = 0;
    uint64_t surfaceSetFail = 0;
    uint64_t outputBuffers = 0;       // HEVC output buffers seen by QueryPacket
    int lastFrameQpResult = -1;       // last GetProperty AMF_RESULT per statistic
    int lastAvgQpResult = -1;
    int lastMinQpResult = -1;
    int lastMaxQpResult = -1;
    uint64_t frameQpSamples = 0;
    uint64_t avgQpSamples = 0;
    uint64_t minQpSamples = 0;
    uint64_t maxQpSamples = 0;
    uint64_t intraSamples = 0;        // AVERAGE_QP samples on IDR/I outputs
    uint64_t interSamples = 0;        // AVERAGE_QP samples on P/B outputs
    int64_t lastFrameQp = -1;         // base (rate-control) QP of the last frame
    int64_t lastAvgQp = -1;           // CTB average QP of the last frame
    int64_t lastMinQp = -1;
    int64_t lastMaxQp = -1;
    int64_t lastPts = -1;
    bool surfaceFlagEnabled = true;   // TELEM_AMD_QP_FEEDBACK_SURFACE=0 disables (A/B diagnosis)
};

class D3D11AMFEncoder {
public:
    D3D11AMFEncoder();
    ~D3D11AMFEncoder();

    // Idempotent lifecycle boundary for partial native initialization.
    void Shutdown();

    bool Initialize(
        ID3D11Device* pDevice,
        UINT width,
        UINT height,
        UINT fpsNum = 30000,
        UINT fpsDen = 1001,
        AMFCodecType codecType = AMFCodecType::HEVC,
        AMFQualityPreset qualityPreset = AMFQualityPreset::FAST,
        uint64_t bitrateBps = 0
    );
    bool CreateSurface(ID3D11Texture2D* pNV12Texture, int64_t pts, amf::AMFSurfacePtr& outSurface, double* outCreateMs = nullptr);
    AMF_RESULT SubmitSurface(amf::AMFSurface* pSurface, AMFEncoderStats* outStats = nullptr);
    bool SubmitTexture(ID3D11Texture2D* pNV12Texture, int64_t pts, AMFEncoderStats* outStats = nullptr);
    bool QueryPacket(
        std::vector<uint8_t>& outData,
        int64_t& outPts,
        bool& outIsKeyframe,
        AMF_RESULT* outResult = nullptr,
        double* outQueryMs = nullptr
    );
    bool Flush();

    // Diagnostic-only raw identities; ownership remains with AMF smart
    // pointers and callers must never Release these values.
    const void* ContextIdentity() const { return static_cast<const void*>(m_context.GetPtr()); }
    const void* EncoderIdentity() const { return static_cast<const void*>(m_encoder.GetPtr()); }

    bool IsSameDeviceUsed() const { return m_sameDeviceUsed; }
    amf::AMFContextPtr GetContext() const { return m_context; }
    AMFCodecType GetCodecType() const { return m_codecType; }
    void SetCodecType(AMFCodecType type) { m_codecType = type; }
    // ETAP 5Z.2: colour pipeline (0 = SDR unchanged, 1 = HLG->SDR BT.709 tags,
    // 2 = HLG preserve: HEVC Main10, P010 input, BT.2020/HLG VUI).  Set before Initialize().
    void SetColorConfig(int pipeline, bool sourceFullRange) {
        m_colorPipeline = pipeline;
        m_colorFullRange = sourceFullRange;
    }
    int GetColorPipeline() const { return m_colorPipeline; }
    AMFQualityPreset GetQualityPreset() const { return m_qualityPreset; }
    void SetQualityPreset(AMFQualityPreset preset) { m_qualityPreset = preset; }
    bool IsAVC() const { return m_codecType == AMFCodecType::AVC; }
    bool IsAV1() const { return m_codecType == AMFCodecType::AV1; }
    const AMFEncoderQPStats& GetQPStats() const { return m_qpStats; }
    const AMFEncoderQPFeedbackDiag& GetQPFeedbackDiag() const { return m_qpDiag; }

private:
    HMODULE m_hAMFRT = nullptr;
    amf::AMFFactory* m_factory = nullptr;
    amf::AMFContextPtr m_context;
    amf::AMFComponentPtr m_encoder;

    ID3D11Device* m_device = nullptr;
    bool m_sameDeviceUsed = false;

    UINT m_width = 3840;
    UINT m_height = 2160;
    AMFCodecType m_codecType = AMFCodecType::HEVC;
    int m_colorPipeline = 0;
    bool m_colorFullRange = true;
    AMFQualityPreset m_qualityPreset = AMFQualityPreset::FAST;
    uint64_t m_bitrateBps = 0;
    AMFEncoderQPStats m_qpStats;
    AMFEncoderQPFeedbackDiag m_qpDiag;
};
