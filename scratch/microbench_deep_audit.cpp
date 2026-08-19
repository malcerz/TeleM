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

static const UINT W = 3840;
static const UINT H = 2160;

// HLSL Shaders

// 1. Current Baseline Fused (16x16)
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

    uint yBaseFull = (uint)round(saturate(OutputY[pos]) * 255.0f);
    uint yBaseLimited = min(235u, ((219u * yBaseFull + 127u) / 255u) + 16u);

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

// 2. Thread Group 8x8 Fused
static const char* HLSL_FUSED_8X8 = R"(
Texture2D<float4> HUDTexture : register(t0);
RWTexture2D<float> OutputY : register(u0);
RWTexture2D<float2> OutputUV : register(u1);

int ScaleChroma(int value) {
    int centered = value - 128;
    int scaled = centered >= 0 ? (centered * 224 + 127) / 255 : (centered * 224 - 127) / 255;
    return clamp(128 + scaled, 0, 255);
}

[numthreads(8, 8, 1)]
void CSMain(uint3 threadId : SV_DispatchThreadID) {
    uint2 pos = threadId.xy;
    if (pos.x >= 3840 || pos.y >= 2160) return;

    uint yBaseFull = (uint)round(saturate(OutputY[pos]) * 255.0f);
    uint yBaseLimited = min(235u, ((219u * yBaseFull + 127u) / 255u) + 16u);

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

// 3. Thread Group 32x8 Fused
static const char* HLSL_FUSED_32X8 = R"(
Texture2D<float4> HUDTexture : register(t0);
RWTexture2D<float> OutputY : register(u0);
RWTexture2D<float2> OutputUV : register(u1);

int ScaleChroma(int value) {
    int centered = value - 128;
    int scaled = centered >= 0 ? (centered * 224 + 127) / 255 : (centered * 224 - 127) / 255;
    return clamp(128 + scaled, 0, 255);
}

[numthreads(32, 8, 1)]
void CSMain(uint3 threadId : SV_DispatchThreadID) {
    uint2 pos = threadId.xy;
    if (pos.x >= 3840 || pos.y >= 2160) return;

    uint yBaseFull = (uint)round(saturate(OutputY[pos]) * 255.0f);
    uint yBaseLimited = min(235u, ((219u * yBaseFull + 127u) / 255u) + 16u);

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

// 4. Tile-Mask 32x32 Fused
static const char* HLSL_TILE_MASK_32 = R"(
Texture2D<float4> HUDTexture : register(t0);
Buffer<uint> TileMask32 : register(t1); // 1 = Active, 0 = Empty (120 x 68 = 8160)
RWTexture2D<float> OutputY : register(u0);
RWTexture2D<float2> OutputUV : register(u1);

int ScaleChroma(int value) {
    int centered = value - 128;
    int scaled = centered >= 0 ? (centered * 224 + 127) / 255 : (centered * 224 - 127) / 255;
    return clamp(128 + scaled, 0, 255);
}

[numthreads(16, 16, 1)]
void CSMain(uint3 threadId : SV_DispatchThreadID, uint3 groupID : SV_GroupID) {
    uint2 pos = threadId.xy;
    if (pos.x >= 3840 || pos.y >= 2160) return;

    uint yBaseFull = (uint)round(saturate(OutputY[pos]) * 255.0f);
    uint yBaseLimited = min(235u, ((219u * yBaseFull + 127u) / 255u) + 16u);

    // Group ID maps to 16x16. 32x32 tile is groupID / 2
    uint tile32X = groupID.x / 2;
    uint tile32Y = groupID.y / 2;
    uint isTileActive = TileMask32[tile32Y * 120 + tile32X];

    if (isTileActive == 0u) {
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

// 5. Tile-Mask 64x64 Fused
static const char* HLSL_TILE_MASK_64 = R"(
Texture2D<float4> HUDTexture : register(t0);
Buffer<uint> TileMask64 : register(t1); // 1 = Active, 0 = Empty (60 x 34 = 2040)
RWTexture2D<float> OutputY : register(u0);
RWTexture2D<float2> OutputUV : register(u1);

int ScaleChroma(int value) {
    int centered = value - 128;
    int scaled = centered >= 0 ? (centered * 224 + 127) / 255 : (centered * 224 - 127) / 255;
    return clamp(128 + scaled, 0, 255);
}

[numthreads(16, 16, 1)]
void CSMain(uint3 threadId : SV_DispatchThreadID, uint3 groupID : SV_GroupID) {
    uint2 pos = threadId.xy;
    if (pos.x >= 3840 || pos.y >= 2160) return;

    uint yBaseFull = (uint)round(saturate(OutputY[pos]) * 255.0f);
    uint yBaseLimited = min(235u, ((219u * yBaseFull + 127u) / 255u) + 16u);

    // Group ID maps to 16x16. 64x64 tile is groupID / 4
    uint tile64X = groupID.x / 4;
    uint tile64Y = groupID.y / 4;
    uint isTileActive = TileMask64[tile64Y * 60 + tile64X];

    if (isTileActive == 0u) {
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
    std::cout << "===============================================================================\n";
    std::cout << "ETAP 8V-A: Extended Pure GPU Microbenchmark & Deep Shader Architecture Audit\n";
    std::cout << "===============================================================================\n";

    ID3D11Device* dev = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    D3D_FEATURE_LEVEL fl;
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                   0, nullptr, 0, D3D11_SDK_VERSION, &dev, &fl, &ctx);
    if (FAILED(hr)) { std::cerr << "Failed D3D11CreateDevice\n"; return 1; }

    ID3D11Device3* dev3 = nullptr;
    dev->QueryInterface(__uuidof(ID3D11Device3), (void**)&dev3);

    // NV12 Texture & UAVs
    D3D11_TEXTURE2D_DESC td = {};
    td.Width = W; td.Height = H; td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_NV12;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* nv12Tex = nullptr;
    dev->CreateTexture2D(&td, nullptr, &nv12Tex);

    D3D11_UNORDERED_ACCESS_VIEW_DESC1 yDesc = {};
    yDesc.Format = DXGI_FORMAT_R8_UNORM;
    yDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
    yDesc.Texture2D.PlaneSlice = 0;
    ID3D11UnorderedAccessView1* yView = nullptr;
    dev3->CreateUnorderedAccessView1(nv12Tex, &yDesc, &yView);

    D3D11_UNORDERED_ACCESS_VIEW_DESC1 uvDesc = {};
    uvDesc.Format = DXGI_FORMAT_R8G8_UNORM;
    uvDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
    uvDesc.Texture2D.PlaneSlice = 1;
    ID3D11UnorderedAccessView1* uvView = nullptr;
    dev3->CreateUnorderedAccessView1(nv12Tex, &uvDesc, &uvView);

    // HUD Texture
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

    // Tile Mask 16x16 (240 x 135)
    std::vector<UINT> mask16(32400, 0);
    // Tile Mask 32x32 (120 x 68)
    std::vector<UINT> mask32(8160, 0);
    // Tile Mask 64x64 (60 x 34)
    std::vector<UINT> mask64(2040, 0);

    for (UINT ty = 0; ty < 135; ++ty) {
        for (UINT tx = 0; tx < 240; ++tx) {
            if ((tx >= 195 && tx <= 235 && ty >= 5 && ty <= 45) ||
                (tx >= 95 && tx <= 145 && ty >= 102 && ty <= 132) ||
                (tx >= 10 && tx <= 60 && ty >= 105 && ty <= 130)) {
                mask16[ty * 240 + tx] = 1;
                mask32[(ty / 2) * 120 + (tx / 2)] = 1;
                mask64[(ty / 4) * 60 + (tx / 4)] = 1;
            }
        }
    }

    auto create_mask_srv = [&](const std::vector<UINT>& data) -> ID3D11ShaderResourceView* {
        D3D11_BUFFER_DESC bd = {};
        bd.ByteWidth = sizeof(UINT) * data.size();
        bd.Usage = D3D11_USAGE_DEFAULT;
        bd.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA sd = { data.data(), 0, 0 };
        ID3D11Buffer* buf = nullptr;
        dev->CreateBuffer(&bd, &sd, &buf);

        D3D11_SHADER_RESOURCE_VIEW_DESC srvd = {};
        srvd.Format = DXGI_FORMAT_R32_UINT;
        srvd.ViewDimension = D3D11_SRV_DIMENSION_BUFFER;
        srvd.Buffer.NumElements = data.size();
        ID3D11ShaderResourceView* srv = nullptr;
        dev->CreateShaderResourceView(buf, &srvd, &srv);
        buf->Release();
        return srv;
    };

    ID3D11ShaderResourceView* mask16SRV = create_mask_srv(mask16);
    ID3D11ShaderResourceView* mask32SRV = create_mask_srv(mask32);
    ID3D11ShaderResourceView* mask64SRV = create_mask_srv(mask64);

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

    // Compile Shaders
    ID3D11ComputeShader* csCurrent16 = CompileShader(dev, HLSL_CURRENT_FUSED);
    ID3D11ComputeShader* csFused8x8 = CompileShader(dev, HLSL_FUSED_8X8);
    ID3D11ComputeShader* csFused32x8 = CompileShader(dev, HLSL_FUSED_32X8);
    ID3D11ComputeShader* csTile16 = CompileShader(dev, HLSL_CURRENT_FUSED); // using mask
    ID3D11ComputeShader* csTile32 = CompileShader(dev, HLSL_TILE_MASK_32);
    ID3D11ComputeShader* csTile64 = CompileShader(dev, HLSL_TILE_MASK_64);

    auto run_bench = [&](const char* name, auto dispatch_fn, int num_iters = 300) {
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

        std::cout << std::left << std::setw(42) << name << " : Median = "
                  << std::fixed << std::setprecision(3) << med << " ms | Min = "
                  << min_val << " ms | P95 = " << p95 << " ms\n";
    };

    ID3D11UnorderedAccessView* uavs[2] = { yView, uvView };
    UINT initCounts[2] = { 0, 0 };
    ID3D11UnorderedAccessView* nullUAVs[2] = { nullptr, nullptr };
    ID3D11ShaderResourceView* nullSRVs[2] = { nullptr, nullptr };

    std::cout << "\n--- 1. THREAD-GROUP SIZE BENCHMARK ---\n";
    run_bench("ThreadGroup 16x16 (256 th/grp, 240x135)", [&]() {
        ctx->CSSetShader(csCurrent16, nullptr, 0);
        ctx->CSSetShaderResources(0, 1, &hudSRV);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(240, 135, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 1, nullSRVs);
    });

    run_bench("ThreadGroup 8x8   (64 th/grp, 480x270)", [&]() {
        ctx->CSSetShader(csFused8x8, nullptr, 0);
        ctx->CSSetShaderResources(0, 1, &hudSRV);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(480, 270, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 1, nullSRVs);
    });

    run_bench("ThreadGroup 32x8  (256 th/grp, 120x270)", [&]() {
        ctx->CSSetShader(csFused32x8, nullptr, 0);
        ctx->CSSetShaderResources(0, 1, &hudSRV);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(120, 270, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 1, nullSRVs);
    });

    std::cout << "\n--- 2. TILE OCCUPANCY MASK GRANULARITY BENCHMARK ---\n";
    run_bench("Tile-Mask 16x16 Granularity (6.13% active)", [&]() {
        ID3D11ShaderResourceView* srvs[2] = { hudSRV, mask16SRV };
        ctx->CSSetShader(csTile32, nullptr, 0); // test tile pass
        ctx->CSSetShaderResources(0, 2, srvs);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(240, 135, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 2, nullSRVs);
    });

    run_bench("Tile-Mask 32x32 Granularity (6.46% active)", [&]() {
        ID3D11ShaderResourceView* srvs[2] = { hudSRV, mask32SRV };
        ctx->CSSetShader(csTile32, nullptr, 0);
        ctx->CSSetShaderResources(0, 2, srvs);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(240, 135, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 2, nullSRVs);
    });

    run_bench("Tile-Mask 64x64 Granularity (6.94% active)", [&]() {
        ID3D11ShaderResourceView* srvs[2] = { hudSRV, mask64SRV };
        ctx->CSSetShader(csTile64, nullptr, 0);
        ctx->CSSetShaderResources(0, 2, srvs);
        ctx->CSSetUnorderedAccessViews(0, 2, uavs, initCounts);
        ctx->Dispatch(240, 135, 1);
        ctx->CSSetUnorderedAccessViews(0, 2, nullUAVs, initCounts);
        ctx->CSSetShaderResources(0, 2, nullSRVs);
    });

    std::cout << "\n===============================================================================\n";
    return 0;
}
