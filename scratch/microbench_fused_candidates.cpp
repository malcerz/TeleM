#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <d3d11_1.h>
#include <d3d11_3.h>
#include <d3dcompiler.h>
#include <iostream>
#include <vector>
#include <chrono>
#include <iomanip>
#include <cmath>
#include <algorithm>
#include <fstream>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "d3dcompiler.lib")
#pragma comment(lib, "dxgi.lib")

// 4K resolution
static const UINT W = 3840;
static const UINT H = 2160;

// HLSL Shader Definitions

// 1. Current Baseline Fused Shader (Option A)
static const char* HLSL_CURRENT_FUSED = R"(
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
    uint2 pos = threadId.xy;
    if (pos.x >= 3840 || pos.y >= 2160) return;

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

// 2. Pure Range Normalize (Kernel 1 for Two-Kernel / Sparse Option D & E)
static const char* HLSL_PURE_RANGE_NORMALIZE = R"(
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
    uint2 pos = threadId.xy;
    if (pos.x >= 3840 || pos.y >= 2160) return;

    // Normalize Base Y
    uint yBaseFull = (uint)round(saturate(OutputY[pos]) * 255.0f);
    uint yBaseLimited = min(235u, ((219u * yBaseFull + 127u) / 255u) + 16u);
    OutputY[pos] = yBaseLimited / 255.0f;

    if (((pos.x | pos.y) & 1u) == 0u) {
        uint2 uvPos = pos / 2u;
        int2 uvBaseFull = (int2)round(saturate(OutputUV[uvPos]) * 255.0f);
        uint uBaseLimited = (uint)ScaleChroma(uvBaseFull.x);
        uint vBaseLimited = (uint)ScaleChroma(uvBaseFull.y);
        OutputUV[uvPos] = float2(uBaseLimited, vBaseLimited) / 255.0f;
    }
}
)";

// 3. Pure HUD Overlay Kernel (Kernel 2 for Two-Kernel Option D & E, dispatches only on active tiles/regions)
static const char* HLSL_SPARSE_HUD_OVERLAY = R"(
Texture2D<float4> HUDTexture : register(t0);
RWTexture2D<float> OutputY : register(u0);
RWTexture2D<float2> OutputUV : register(u1);

cbuffer RegionCB : register(b0) {
    uint2 RegionOffset;
    uint2 RegionSize;
};

[numthreads(16, 16, 1)]
void CSMain(uint3 threadId : SV_DispatchThreadID) {
    uint2 pos = RegionOffset + threadId.xy;
    if (threadId.x >= RegionSize.x || threadId.y >= RegionSize.y || pos.x >= 3840 || pos.y >= 2160) return;

    uint4 hud = (uint4)round(saturate(HUDTexture.Load(int3(pos, 0))) * 255.0f);
    uint alpha = hud.a;
    if (alpha == 0u) return; // early exit on empty sub-pixel

    uint yBaseLimited = (uint)round(saturate(OutputY[pos]) * 255.0f);
    uint yHUD = ((66u * hud.r + 129u * hud.g + 25u * hud.b + 128u) >> 8) + 16u;
    uint yOut = alpha == 255u ? yHUD : (yHUD * alpha + yBaseLimited * (255u - alpha)) / 255u;
    OutputY[pos] = min(yOut, 255u) / 255.0f;

    if (((pos.x | pos.y) & 1u) == 0u) {
        uint2 uvPos = pos / 2u;
        float2 uvBaseLimitedF = OutputUV[uvPos] * 255.0f;
        uint2 uvBaseLimited = (uint2)round(saturate(OutputUV[uvPos]) * 255.0f);

        int uHUD = ((-38 * (int)hud.r - 74 * (int)hud.g + 112 * (int)hud.b + 128) >> 8) + 128;
        int vHUD = ((112 * (int)hud.r - 94 * (int)hud.g - 18 * (int)hud.b + 128) >> 8) + 128;
        uint uValue = (uint)clamp(uHUD, 0, 255);
        uint vValue = (uint)clamp(vHUD, 0, 255);
        uint2 uvOut = alpha == 255u ? uint2(uValue, vValue) :
            (uint2(uValue, vValue) * alpha + uvBaseLimited * (255u - alpha)) / 255u;
        OutputUV[uvPos] = uvOut / 255.0f;
    }
}
)";

// 4. Tile-Mask Fused Shader (Option C: checks tile mask buffer per 16x16 tile)
static const char* HLSL_TILE_MASK_FUSED = R"(
Texture2D<float4> HUDTexture : register(t0);
Buffer<uint> TileMask : register(t1); // 1 = Active, 0 = Empty
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
void CSMain(uint3 threadId : SV_DispatchThreadID, uint3 groupID : SV_GroupID) {
    uint2 pos = threadId.xy;
    if (pos.x >= 3840 || pos.y >= 2160) return;

    // 1. Normalize Base Y
    uint yBaseFull = (uint)round(saturate(OutputY[pos]) * 255.0f);
    uint yBaseLimited = min(235u, ((219u * yBaseFull + 127u) / 255u) + 16u);

    // Check Tile Mask for this 16x16 threadgroup (240 tiles wide)
    uint tileIdx = groupID.y * 240 + groupID.x;
    uint isTileActive = TileMask[tileIdx];

    if (isTileActive == 0u) {
        // EMPTY TILE FAST PATH: No HUD Texture Load, No Alpha Branch, No Rec.709 Math!
        OutputY[pos] = yBaseLimited / 255.0f;
        if (((pos.x | pos.y) & 1u) == 0u) {
            uint2 uvPos = pos / 2u;
            int2 uvBaseFull = (int2)round(saturate(OutputUV[uvPos]) * 255.0f);
            uint uBaseLimited = (uint)ScaleChroma(uvBaseFull.x);
            uint vBaseLimited = (uint)ScaleChroma(uvBaseFull.y);
            OutputUV[uvPos] = float2(uBaseLimited, vBaseLimited) / 255.0f;
        }
        return;
    }

    // ACTIVE TILE: Full Fused Composite
    uint4 hud = (uint4)round(saturate(HUDTexture.Load(int3(pos, 0))) * 255.0f);
    uint alpha = hud.a;

    if (alpha == 0u) {
        OutputY[pos] = yBaseLimited / 255.0f;
    } else {
        uint yHUD = ((66u * hud.r + 129u * hud.g + 25u * hud.b + 128u) >> 8) + 16u;
        uint yOut = alpha == 255u ? yHUD : (yHUD * alpha + yBaseLimited * (255u - alpha)) / 255u;
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

// 5. 2x2 Block Fused Shader (Option F: 1 thread per 2x2 luma block + 1 UV pair)
static const char* HLSL_2X2_BLOCK_FUSED = R"(
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

[numthreads(8, 8, 1)]
void CSMain(uint3 threadId : SV_DispatchThreadID) {
    uint2 uvPos = threadId.xy; // 1920 x 1080 grid
    if (uvPos.x >= 1920 || uvPos.y >= 1080) return;

    uint2 pos00 = uvPos * 2u;
    uint2 pos10 = pos00 + uint2(1u, 0u);
    uint2 pos01 = pos00 + uint2(0u, 1u);
    uint2 pos11 = pos00 + uint2(1u, 1u);

    // Read 4 Y samples
    uint y00 = (uint)round(saturate(OutputY[pos00]) * 255.0f);
    uint y10 = (uint)round(saturate(OutputY[pos10]) * 255.0f);
    uint y01 = (uint)round(saturate(OutputY[pos01]) * 255.0f);
    uint y11 = (uint)round(saturate(OutputY[pos11]) * 255.0f);

    uint yLim00 = min(235u, ((219u * y00 + 127u) / 255u) + 16u);
    uint yLim10 = min(235u, ((219u * y10 + 127u) / 255u) + 16u);
    uint yLim01 = min(235u, ((219u * y01 + 127u) / 255u) + 16u);
    uint yLim11 = min(235u, ((219u * y11 + 127u) / 255u) + 16u);

    // Read 1 UV sample (no divergence, no modulus branch!)
    int2 uvFull = (int2)round(saturate(OutputUV[uvPos]) * 255.0f);
    uint uLim = (uint)ScaleChroma(uvFull.x);
    uint vLim = (uint)ScaleChroma(uvFull.y);

    // Read HUD 00
    uint4 h00 = (uint4)round(saturate(HUDTexture.Load(int3(pos00, 0))) * 255.0f);
    uint4 h10 = (uint4)round(saturate(HUDTexture.Load(int3(pos10, 0))) * 255.0f);
    uint4 h01 = (uint4)round(saturate(HUDTexture.Load(int3(pos01, 0))) * 255.0f);
    uint4 h11 = (uint4)round(saturate(HUDTexture.Load(int3(pos11, 0))) * 255.0f);

    // Process Y 00
    if (h00.a == 0u) OutputY[pos00] = yLim00 / 255.0f;
    else {
        uint yh = ((66u * h00.r + 129u * h00.g + 25u * h00.b + 128u) >> 8) + 16u;
        OutputY[pos00] = (h00.a == 255u ? yh : (yh * h00.a + yLim00 * (255u - h00.a)) / 255u) / 255.0f;
    }
    // Process Y 10
    if (h10.a == 0u) OutputY[pos10] = yLim10 / 255.0f;
    else {
        uint yh = ((66u * h10.r + 129u * h10.g + 25u * h10.b + 128u) >> 8) + 16u;
        OutputY[pos10] = (h10.a == 255u ? yh : (yh * h10.a + yLim10 * (255u - h10.a)) / 255u) / 255.0f;
    }
    // Process Y 01
    if (h01.a == 0u) OutputY[pos01] = yLim01 / 255.0f;
    else {
        uint yh = ((66u * h01.r + 129u * h01.g + 25u * h01.b + 128u) >> 8) + 16u;
        OutputY[pos01] = (h01.a == 255u ? yh : (yh * h01.a + yLim01 * (255u - h01.a)) / 255u) / 255.0f;
    }
    // Process Y 11
    if (h11.a == 0u) OutputY[pos11] = yLim11 / 255.0f;
    else {
        uint yh = ((66u * h11.r + 129u * h11.g + 25u * h11.b + 128u) >> 8) + 16u;
        OutputY[pos11] = (h11.a == 255u ? yh : (yh * h11.a + yLim11 * (255u - h11.a)) / 255u) / 255.0f;
    }

    // Process UV (aligned with pos00)
    if (h00.a == 0u) {
        OutputUV[uvPos] = float2(uLim, vLim) / 255.0f;
    } else {
        int uHUD = ((-38 * (int)h00.r - 74 * (int)h00.g + 112 * (int)h00.b + 128) >> 8) + 128;
        int vHUD = ((112 * (int)h00.r - 94 * (int)h00.g - 18 * (int)h00.b + 128) >> 8) + 128;
        uint uValue = (uint)clamp(uHUD, 0, 255);
        uint vValue = (uint)clamp(vHUD, 0, 255);
        uint2 uvOut = h00.a == 255u ? uint2(uValue, vValue) :
            (uint2(uValue, vValue) * h00.a + uint2(uLim, vLim) * (255u - h00.a)) / 255u;
        OutputUV[uvPos] = uvOut / 255.0f;
    }
}
)";

struct BenchmarkResult {
    std::string name;
    double median_ms;
    double min_ms;
    double p95_ms;
};

ID3D11ComputeShader* CompileShader(ID3D11Device* dev, const char* src) {
    ID3DBlob* blob = nullptr;
    ID3DBlob* err = nullptr;
    HRESULT hr = D3DCompile(src, strlen(src), nullptr, nullptr, nullptr, "CSMain", "cs_5_0", 0, 0, &blob, &err);
    if (FAILED(hr)) {
        if (err) { std::cerr << "Compile error: " << (char*)err->GetBufferPointer() << std::endl; err->Release(); }
        return nullptr;
    }
    ID3D11ComputeShader* cs = nullptr;
    dev->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &cs);
    blob->Release();
    return cs;
}

int main() {
    std::cout << "=======================================================\n";
    std::cout << "ETAP 8V-A: Pure GPU Compute Shader Microbenchmark (4K)\n";
    std::cout << "=======================================================\n";

    // 1. Create Device
    ID3D11Device* dev = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    D3D_FEATURE_LEVEL fl;
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                   0, nullptr, 0, D3D11_SDK_VERSION, &dev, &fl, &ctx);
    if (FAILED(hr)) { std::cerr << "Failed D3D11CreateDevice\n"; return 1; }

    // 2. Create 4K NV12 Texture & UAVs
    D3D11_TEXTURE2D_DESC td = {};
    td.Width = W; td.Height = H; td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_NV12;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* nv12Tex = nullptr;
    hr = dev->CreateTexture2D(&td, nullptr, &nv12Tex);
    if (FAILED(hr)) { std::cerr << "Failed CreateTexture2D NV12: 0x" << std::hex << hr << std::endl; return 1; }

    ID3D11Device3* dev3 = nullptr;
    dev->QueryInterface(__uuidof(ID3D11Device3), (void**)&dev3);
    if (!dev3) { std::cerr << "Failed ID3D11Device3 QueryInterface\n"; return 1; }

    D3D11_UNORDERED_ACCESS_VIEW_DESC1 yDesc = {};
    yDesc.Format = DXGI_FORMAT_R8_UNORM;
    yDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
    yDesc.Texture2D.PlaneSlice = 0;
    ID3D11UnorderedAccessView1* yView = nullptr;
    hr = dev3->CreateUnorderedAccessView1(nv12Tex, &yDesc, &yView);
    if (FAILED(hr)) { std::cerr << "Failed CreateUnorderedAccessView1 Y: 0x" << std::hex << hr << std::endl; return 1; }

    D3D11_UNORDERED_ACCESS_VIEW_DESC1 uvDesc = {};
    uvDesc.Format = DXGI_FORMAT_R8G8_UNORM;
    uvDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
    uvDesc.Texture2D.PlaneSlice = 1;
    ID3D11UnorderedAccessView1* uvView = nullptr;
    hr = dev3->CreateUnorderedAccessView1(nv12Tex, &uvDesc, &uvView);
    if (FAILED(hr)) { std::cerr << "Failed CreateUnorderedAccessView1 UV: 0x" << std::hex << hr << std::endl; return 1; }

    // HUD Texture (3840x2160 RGBA)
    D3D11_TEXTURE2D_DESC hudDesc = {};
    hudDesc.Width = W; hudDesc.Height = H; hudDesc.MipLevels = 1; hudDesc.ArraySize = 1;
    hudDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    hudDesc.SampleDesc.Count = 1;
    hudDesc.Usage = D3D11_USAGE_DEFAULT;
    hudDesc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* hudTex = nullptr;
    dev->CreateTexture2D(&hudDesc, nullptr, &hudTex);
    ID3D11ShaderResourceView* hudSRV = nullptr;
    dev->CreateShaderResourceView(hudTex, nullptr, &hudSRV);

    ID3D11UnorderedAccessView* yUAV = yView;
    ID3D11UnorderedAccessView* uvUAV = uvView;

    // TileMask Buffer (240 x 135 = 32400 uints)
    std::vector<UINT> maskData(32400, 0);
    // Set ~6.13% of tiles active (1987 tiles active) in typical clusters (corners/bottom)
    for (UINT ty = 0; ty < 135; ++ty) {
        for (UINT tx = 0; tx < 240; ++tx) {
            // Map top-right: tx in [190..235], ty in [5..50] -> ~2000 tiles
            // Gauge bottom-center: tx in [95..145], ty in [100..130] -> ~1500 tiles
            if ((tx >= 195 && tx <= 235 && ty >= 5 && ty <= 45) ||
                (tx >= 95 && tx <= 145 && ty >= 102 && ty <= 132) ||
                (tx >= 10 && tx <= 60 && ty >= 105 && ty <= 130)) {
                maskData[ty * 240 + tx] = 1;
            }
        }
    }
    D3D11_BUFFER_DESC bd = {};
    bd.ByteWidth = sizeof(UINT) * 32400;
    bd.Usage = D3D11_USAGE_DEFAULT;
    bd.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA sd = { maskData.data(), 0, 0 };
    ID3D11Buffer* maskBuf = nullptr;
    dev->CreateBuffer(&bd, &sd, &maskBuf);

    D3D11_SHADER_RESOURCE_VIEW_DESC srvd = {};
    srvd.Format = DXGI_FORMAT_R32_UINT;
    srvd.ViewDimension = D3D11_SRV_DIMENSION_BUFFER;
    srvd.Buffer.NumElements = 32400;
    ID3D11ShaderResourceView* maskSRV = nullptr;
    dev->CreateShaderResourceView(maskBuf, &srvd, &maskSRV);

    // Constant buffer for region
    D3D11_BUFFER_DESC cbd = {};
    cbd.ByteWidth = 32;
    cbd.Usage = D3D11_USAGE_DYNAMIC;
    cbd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    cbd.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    ID3D11Buffer* regionCB = nullptr;
    dev->CreateBuffer(&cbd, nullptr, &regionCB);

    // Queries
    D3D11_QUERY_DESC qd = {};
    qd.Query = D3D11_QUERY_TIMESTAMP_DISJOINT;
    ID3D11Query* qDisjoint = nullptr;
    dev->CreateQuery(&qd, &qDisjoint);
    qd.Query = D3D11_QUERY_TIMESTAMP;
    ID3D11Query* qStart = nullptr;
    ID3D11Query* qEnd = nullptr;
    dev->CreateQuery(&qd, &qStart);
    dev->CreateQuery(&qd, &qEnd);

    // Compile Candidates
    ID3D11ComputeShader* csCurrent = CompileShader(dev, HLSL_CURRENT_FUSED);
    ID3D11ComputeShader* csPureRange = CompileShader(dev, HLSL_PURE_RANGE_NORMALIZE);
    ID3D11ComputeShader* csSparseHUD = CompileShader(dev, HLSL_SPARSE_HUD_OVERLAY);
    ID3D11ComputeShader* csTileMask = CompileShader(dev, HLSL_TILE_MASK_FUSED);
    ID3D11ComputeShader* cs2x2 = CompileShader(dev, HLSL_2X2_BLOCK_FUSED);

    auto run_bench = [&](const char* name, auto dispatch_fn, int num_iters = 300) -> BenchmarkResult {
        // Warmup
        for (int i = 0; i < 20; ++i) dispatch_fn();
        ctx->Flush();

        std::vector<double> samples;
        samples.reserve(num_iters);

        for (int i = 0; i < num_iters; ++i) {
            ctx->Begin(qDisjoint);
            ctx->End(qStart);

            dispatch_fn();

            ctx->End(qEnd);
            ctx->End(qDisjoint);

            // Wait for query
            D3D11_QUERY_DATA_TIMESTAMP_DISJOINT dj;
            while (ctx->GetData(qDisjoint, &dj, sizeof(dj), 0) == S_FALSE) {}
            UINT64 ts0 = 0, ts1 = 0;
            while (ctx->GetData(qStart, &ts0, sizeof(ts0), 0) == S_FALSE) {}
            while (ctx->GetData(qEnd, &ts1, sizeof(ts1), 0) == S_FALSE) {}

            if (!dj.Disjoint && dj.Frequency > 0) {
                double ms = (double)(ts1 - ts0) * 1000.0 / (double)dj.Frequency;
                samples.push_back(ms);
            }
        }

        std::sort(samples.begin(), samples.end());
        double med = samples[samples.size() / 2];
        double min_val = samples.front();
        double p95 = samples[(size_t)(samples.size() * 0.95)];

        std::cout << std::left << std::setw(38) << name << " : Median = "
                  << std::fixed << std::setprecision(3) << med << " ms | Min = "
                  << min_val << " ms | P95 = " << p95 << " ms\n";

        return { name, med, min_val, p95 };
    };

    ID3D11UnorderedAccessView* uavs[2] = { yUAV, uvUAV };
    UINT initCounts[2] = { 0, 0 };
    ID3D11UnorderedAccessView* nullUAVs[2] = { nullptr, nullptr };
    ID3D11ShaderResourceView* nullSRVs[2] = { nullptr, nullptr };

    std::vector<BenchmarkResult> results;

    // 1. Option A: Current Full-Frame Fused Baseline (16x16)
    results.push_back(run_bench("Option A: Current Fused Baseline", [&]() {
        ctx->CSSetShader(csCurrent, nullptr, 0);
        ctx->CSSetShaderResources(0, 1, &hudSRV);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(240, 135, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 1, nullSRVs);
    }));

    // 2. Option C: Tile-Mask 16x16 (Active Tile Bypass)
    results.push_back(run_bench("Option C: Tile-Mask 16x16", [&]() {
        ID3D11ShaderResourceView* srvs[2] = { hudSRV, maskSRV };
        ctx->CSSetShader(csTileMask, nullptr, 0);
        ctx->CSSetShaderResources(0, 2, srvs);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(240, 135, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 2, nullSRVs);
    }));

    // 3. Option D: Two-Kernel (Pass 1 Full Range Normalize + Pass 2 Sparse Active Tiles ~6%)
    results.push_back(run_bench("Option D: Two-Kernel (Full + Sparse Tiles)", [&]() {
        // Pass 1: Full Frame Range Normalize (no HUD texture bound)
        ctx->CSSetShader(csPureRange, nullptr, 0);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(240, 135, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);

        // Pass 2: Sparse HUD Overlay on 3 active clusters (Map 691x691, Gauge 648x648, Speedo 500x300)
        ctx->CSSetShader(csSparseHUD, nullptr, 0);
        ctx->CSSetShaderResources(0, 1, &hudSRV);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);

        // Map region
        D3D11_MAPPED_SUBRESOURCE mapped;
        ctx->Map(regionCB, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
        UINT* cb = (UINT*)mapped.pData;
        cb[0] = 3120; cb[1] = 80; cb[2] = 691; cb[3] = 691;
        ctx->Unmap(regionCB, 0);
        ctx->CSSetConstantBuffers(0, 1, &regionCB);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);

        // Gauge region
        ctx->Map(regionCB, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
        cb = (UINT*)mapped.pData;
        cb[0] = 1544; cb[1] = 1632; cb[2] = 648; cb[3] = 648;
        ctx->Unmap(regionCB, 0);
        ctx->CSSetConstantBuffers(0, 1, &regionCB);
        ctx->Dispatch((648 + 15) / 16, (648 + 15) / 16, 1);

        // Speedo / Texts region
        ctx->Map(regionCB, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
        cb = (UINT*)mapped.pData;
        cb[0] = 100; cb[1] = 1700; cb[2] = 800; cb[3] = 400;
        ctx->Unmap(regionCB, 0);
        ctx->CSSetConstantBuffers(0, 1, &regionCB);
        ctx->Dispatch((800 + 15) / 16, (400 + 15) / 16, 1);

        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 1, nullSRVs);
    }));

    // 4. Option F: 2x2 Block Fused Shader (8x8 threads per group)
    results.push_back(run_bench("Option F: 2x2 Block Fused (4:2:0 Aligned)", [&]() {
        ctx->CSSetShader(cs2x2, nullptr, 0);
        ctx->CSSetShaderResources(0, 1, &hudSRV);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(240, 135, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 1, nullSRVs);
    }));

    // 5. Option D1: Pure Range Normalize Alone (Pass 1 floor)
    results.push_back(run_bench("Component: Pure Range Normalize Floor", [&]() {
        ctx->CSSetShader(csPureRange, nullptr, 0);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(240, 135, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
    }));

    // Cleanup
    if (csCurrent) csCurrent->Release();
    if (csPureRange) csPureRange->Release();
    if (csSparseHUD) csSparseHUD->Release();
    if (csTileMask) csTileMask->Release();
    if (cs2x2) cs2x2->Release();
    if (hudSRV) hudSRV->Release();
    if (hudTex) hudTex->Release();
    if (yView) yView->Release();
    if (uvView) uvView->Release();
    if (nv12Tex) nv12Tex->Release();
    if (maskSRV) maskSRV->Release();
    if (maskBuf) maskBuf->Release();
    if (regionCB) regionCB->Release();
    if (qDisjoint) qDisjoint->Release();
    if (qStart) qStart->Release();
    if (qEnd) qEnd->Release();
    if (dev3) dev3->Release();
    ctx->Release();
    dev->Release();

    std::cout << "\nMicrobenchmark complete.\n";
    return 0;
}
