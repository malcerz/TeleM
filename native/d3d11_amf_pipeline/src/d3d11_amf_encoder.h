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

struct AMFEncoderStats {
    double submit_ms = 0.0;
    double create_surface_ms = 0.0;   // ETAP 5R
    double submit_input_ms = 0.0;     // ETAP 5R
    double query_ms = 0.0;
    size_t output_bytes = 0;
    bool input_full = false;
    AMF_RESULT result = AMF_OK;
};

class D3D11AMFEncoder {
public:
    D3D11AMFEncoder();
    ~D3D11AMFEncoder();

    bool Initialize(ID3D11Device* pDevice, UINT width, UINT height, UINT fpsNum = 30000, UINT fpsDen = 1001);
    bool SubmitTexture(ID3D11Texture2D* pNV12Texture, int64_t pts, AMFEncoderStats* outStats = nullptr);
    bool QueryPacket(
        std::vector<uint8_t>& outData,
        int64_t& outPts,
        bool& outIsKeyframe,
        AMF_RESULT* outResult = nullptr,
        double* outQueryMs = nullptr
    );
    bool Flush();

    bool IsSameDeviceUsed() const { return m_sameDeviceUsed; }

private:
    HMODULE m_hAMFRT = nullptr;
    amf::AMFFactory* m_factory = nullptr;
    amf::AMFContextPtr m_context;
    amf::AMFComponentPtr m_encoder;

    ID3D11Device* m_device = nullptr;
    bool m_sameDeviceUsed = false;

    UINT m_width = 3840;
    UINT m_height = 2160;
};
