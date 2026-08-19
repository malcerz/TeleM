#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <iostream>
#include <vector>
#include <chrono>
#include <cmath>
#include <iomanip>

// Standalone D3D11 Map Shader Microbenchmark
// Measures pure GPU dispatch execution time across 1000 dispatches on a 692x692 RGBA map texture.

static const char* kResampleShaderSource = R"(
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

static const char* kBlendShaderSource = R"(
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

// Single-Pass Fused Map Resample & Blend Shader Prototype
static const char* kSinglePassFusedSource = R"(
    Texture2D<float4> MapTexture : register(t0);
    RWTexture2D<float4> HUDCanvas : register(u0);
    cbuffer FusedCB : register(b0) {
        uint srcW; uint srcH;
        uint dstX; uint dstY;
        uint mapW; uint mapH;
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
        if (tid.x >= mapW || tid.y >= mapH) return;
        float scaleX = float(srcW) / float(mapW);
        float scaleY = float(srcH) / float(mapH);
        float cx = (tid.x + 0.5) * scaleX - 0.5;
        float cy = (tid.y + 0.5) * scaleY - 0.5;

        int baseX, baseY, taps;
        if (filter == 0) { baseX = (int)floor(cx); baseY = (int)floor(cy); taps = 2; }
        else if (filter == 1) { baseX = (int)floor(cx) - 1; baseY = (int)floor(cy) - 1; taps = 4; }
        else { baseX = (int)floor(cx) - 2; baseY = (int)floor(cy) - 2; taps = 6; }

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
        if (wsum <= 1e-6) return;
        float4 srcF;
        srcF.a = alphaAcc / wsum;
        if (srcF.a > 1e-6) srcF.rgb = premulRgb / alphaAcc;
        else return;
        srcF = saturate(srcF);

        uint4 src = (uint4)round(srcF * 255.0);
        if (src.a == 0) return;

        uint2 canvasPos = uint2(dstX + tid.x, dstY + tid.y);
        uint4 dst = (uint4)round(saturate(HUDCanvas.Load(int3(canvasPos, 0))) * 255.0);
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

// Direct 1:1 Map Blend (zero resample math, direct straight-alpha blend)
static const char* kDirect1to1BlendSource = R"(
    Texture2D<float4> MapTexture : register(t0);
    RWTexture2D<float4> HUDCanvas : register(u0);
    cbuffer DirectCB : register(b0) {
        uint dstX; uint dstY;
        uint mapW; uint mapH;
    };

    [numthreads(16, 16, 1)]
    void CSMain(uint3 tid : SV_DispatchThreadID) {
        if (tid.x >= mapW || tid.y >= mapH) return;
        float4 srcF = saturate(MapTexture.Load(int3(tid.xy, 0)));
        uint4 src = (uint4)round(srcF * 255.0);
        if (src.a == 0) return;

        uint2 canvasPos = uint2(dstX + tid.x, dstY + tid.y);
        uint4 dst = (uint4)round(saturate(HUDCanvas.Load(int3(canvasPos, 0))) * 255.0);
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

int main() {
    std::cout << "=== D3D11 MAP SHADER MICROBENCHMARK ===" << std::endl;

    ID3D11Device* dev = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    D3D_FEATURE_LEVEL fl;
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, &dev, &fl, &ctx);
    if (FAILED(hr)) {
        std::cerr << "Failed to create D3D11 device! hr=" << std::hex << hr << std::endl;
        return 1;
    }
    std::cout << "D3D11 Device created successfully." << std::endl;

    auto compileCS = [&](const char* src, const char* name) -> ID3D11ComputeShader* {
        ID3DBlob* blob = nullptr;
        ID3DBlob* err = nullptr;
        hr = D3DCompile(src, strlen(src), nullptr, nullptr, nullptr, "CSMain", "cs_5_0", 0, 0, &blob, &err);
        if (FAILED(hr)) {
            std::cerr << "Compile error for " << name << ": ";
            if (err) { std::cerr << (char*)err->GetBufferPointer(); err->Release(); }
            std::cerr << std::endl;
            return nullptr;
        }
        ID3D11ComputeShader* cs = nullptr;
        dev->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &cs);
        blob->Release();
        return cs;
    };

    ID3D11ComputeShader* csResample = compileCS(kResampleShaderSource, "kResampleShaderSource");
    ID3D11ComputeShader* csBlend = compileCS(kBlendShaderSource, "kBlendShaderSource");
    ID3D11ComputeShader* csSinglePass = compileCS(kSinglePassFusedSource, "kSinglePassFusedSource");
    ID3D11ComputeShader* csDirect1to1 = compileCS(kDirect1to1BlendSource, "kDirect1to1BlendSource");

    // Create 692x692 Source Texture
    D3D11_TEXTURE2D_DESC td = {};
    td.Width = 692; td.Height = 692; td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_R8G8B8A8_UNORM; td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT; td.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* srcTex = nullptr;
    dev->CreateTexture2D(&td, nullptr, &srcTex);
    ID3D11ShaderResourceView* srcSRV = nullptr;
    dev->CreateShaderResourceView(srcTex, nullptr, &srcSRV);

    // Create 691x691 Intermediate Texture
    td.Width = 691; td.Height = 691;
    td.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
    ID3D11Texture2D* interTex = nullptr;
    dev->CreateTexture2D(&td, nullptr, &interTex);
    ID3D11ShaderResourceView* interSRV = nullptr;
    dev->CreateShaderResourceView(interTex, nullptr, &interSRV);
    ID3D11UnorderedAccessView* interUAV = nullptr;
    dev->CreateUnorderedAccessView(interTex, nullptr, &interUAV);

    // Create 1920x1264 HUD Canvas Texture
    td.Width = 1920; td.Height = 1264;
    td.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
    ID3D11Texture2D* hudTex = nullptr;
    dev->CreateTexture2D(&td, nullptr, &hudTex);
    ID3D11UnorderedAccessView* hudUAV = nullptr;
    dev->CreateUnorderedAccessView(hudTex, nullptr, &hudUAV);

    // Constant Buffers
    D3D11_BUFFER_DESC bd = {};
    bd.ByteWidth = 32; bd.Usage = D3D11_USAGE_DEFAULT; bd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    ID3D11Buffer* cbResample = nullptr; dev->CreateBuffer(&bd, nullptr, &cbResample);
    ID3D11Buffer* cbBlend = nullptr; dev->CreateBuffer(&bd, nullptr, &cbBlend);
    ID3D11Buffer* cbFused = nullptr; dev->CreateBuffer(&bd, nullptr, &cbFused);

    // Disjoint Timestamp Query
    ID3D11Query* qDisjoint = nullptr;
    ID3D11Query* qBegin = nullptr;
    ID3D11Query* qEnd = nullptr;
    D3D11_QUERY_DESC qd = { D3D11_QUERY_TIMESTAMP_DISJOINT, 0 };
    dev->CreateQuery(&qd, &qDisjoint);
    qd.Query = D3D11_QUERY_TIMESTAMP;
    dev->CreateQuery(&qd, &qBegin);
    dev->CreateQuery(&qd, &qEnd);

    auto measureGPU = [&](const char* name, int iterations, auto dispatchFn) {
        // Warmup
        for (int i = 0; i < 20; ++i) dispatchFn();
        ctx->Flush();

        ctx->Begin(qDisjoint);
        ctx->End(qBegin);
        const auto cpuStart = std::chrono::high_resolution_clock::now();
        for (int i = 0; i < iterations; ++i) dispatchFn();
        ctx->End(qEnd);
        ctx->End(qDisjoint);
        ctx->Flush();

        while (ctx->GetData(qDisjoint, nullptr, 0, 0) == S_FALSE) Sleep(1);
        while (ctx->GetData(qBegin, nullptr, 0, 0) == S_FALSE) Sleep(1);
        while (ctx->GetData(qEnd, nullptr, 0, 0) == S_FALSE) Sleep(1);
        const auto cpuEnd = std::chrono::high_resolution_clock::now();

        D3D11_QUERY_DATA_TIMESTAMP_DISJOINT dj = {};
        ctx->GetData(qDisjoint, &dj, sizeof(dj), 0);
        UINT64 t0 = 0, t1 = 0;
        ctx->GetData(qBegin, &t0, sizeof(t0), 0);
        ctx->GetData(qEnd, &t1, sizeof(t1), 0);

        double totalMs = (dj.Frequency > 0) ? (double(t1 - t0) / double(dj.Frequency) * 1000.0) : 0.0;
        double cpuWallMs = std::chrono::duration<double, std::milli>(cpuEnd - cpuStart).count();
        double perDispatchMs = totalMs / double(iterations);
        double perDispatchCpu = cpuWallMs / double(iterations);
        std::cout << std::left << std::setw(38) << name 
                  << ": GPU=" << std::fixed << std::setprecision(4) << perDispatchMs << " ms | CPU_Wall="
                  << perDispatchCpu << " ms (" << totalMs << " ms GPU for " << iterations << " iterations)" << std::endl;
    };

    const int kIterations = 1000;
    UINT zeroCounts[1] = { 0 };
    ID3D11UnorderedAccessView* nullUAV = nullptr;
    ID3D11ShaderResourceView* nullSRV = nullptr;

    // 1. Current Two-Pass Lanczos3 (692 -> 691)
    measureGPU("1. Two-Pass Lanczos3 (692->691)", kIterations, [&]() {
        struct { UINT srcW, srcH, dstW, dstH, filter, pad; } rcb = { 692, 692, 691, 691, 2, 0 };
        ctx->UpdateSubresource(cbResample, 0, nullptr, &rcb, 0, 0);
        ctx->CSSetShader(csResample, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbResample);
        ctx->CSSetShaderResources(0, 1, &srcSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &interUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);

        struct { UINT dstX, dstY, mapW, mapH; } bcb = { 100, 100, 691, 691 };
        ctx->UpdateSubresource(cbBlend, 0, nullptr, &bcb, 0, 0);
        ctx->CSSetShader(csBlend, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbBlend);
        ctx->CSSetShaderResources(0, 1, &interSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        ctx->CSSetShaderResources(0, 1, &nullSRV);
    });

    // 2. Current Two-Pass Bicubic (692 -> 691)
    measureGPU("2. Two-Pass Bicubic CatmullRom", kIterations, [&]() {
        struct { UINT srcW, srcH, dstW, dstH, filter, pad; } rcb = { 692, 692, 691, 691, 1, 0 };
        ctx->UpdateSubresource(cbResample, 0, nullptr, &rcb, 0, 0);
        ctx->CSSetShader(csResample, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbResample);
        ctx->CSSetShaderResources(0, 1, &srcSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &interUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);

        struct { UINT dstX, dstY, mapW, mapH; } bcb = { 100, 100, 691, 691 };
        ctx->UpdateSubresource(cbBlend, 0, nullptr, &bcb, 0, 0);
        ctx->CSSetShader(csBlend, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbBlend);
        ctx->CSSetShaderResources(0, 1, &interSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        ctx->CSSetShaderResources(0, 1, &nullSRV);
    });

    // 3. Current Two-Pass Bilinear (692 -> 691)
    measureGPU("3. Two-Pass Bilinear (692->691)", kIterations, [&]() {
        struct { UINT srcW, srcH, dstW, dstH, filter, pad; } rcb = { 692, 692, 691, 691, 0, 0 };
        ctx->UpdateSubresource(cbResample, 0, nullptr, &rcb, 0, 0);
        ctx->CSSetShader(csResample, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbResample);
        ctx->CSSetShaderResources(0, 1, &srcSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &interUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);

        struct { UINT dstX, dstY, mapW, mapH; } bcb = { 100, 100, 691, 691 };
        ctx->UpdateSubresource(cbBlend, 0, nullptr, &bcb, 0, 0);
        ctx->CSSetShader(csBlend, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbBlend);
        ctx->CSSetShaderResources(0, 1, &interSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        ctx->CSSetShaderResources(0, 1, &nullSRV);
    });

    // 4. Single-Pass Fused Lanczos3 (692 -> 691 direct into HUD)
    measureGPU("4. Single-Pass Fused Lanczos3", kIterations, [&]() {
        struct { UINT srcW, srcH, dstX, dstY, mapW, mapH, filter, pad; } fcb = { 692, 692, 100, 100, 691, 691, 2, 0 };
        ctx->UpdateSubresource(cbFused, 0, nullptr, &fcb, 0, 0);
        ctx->CSSetShader(csSinglePass, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbFused);
        ctx->CSSetShaderResources(0, 1, &srcSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        ctx->CSSetShaderResources(0, 1, &nullSRV);
    });

    // 5. Single-Pass Fused Bicubic (692 -> 691 direct into HUD)
    measureGPU("5. Single-Pass Fused Bicubic", kIterations, [&]() {
        struct { UINT srcW, srcH, dstX, dstY, mapW, mapH, filter, pad; } fcb = { 692, 692, 100, 100, 691, 691, 1, 0 };
        ctx->UpdateSubresource(cbFused, 0, nullptr, &fcb, 0, 0);
        ctx->CSSetShader(csSinglePass, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbFused);
        ctx->CSSetShaderResources(0, 1, &srcSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        ctx->CSSetShaderResources(0, 1, &nullSRV);
    });

    // 6. Single-Pass Fused Bilinear (692 -> 691 direct into HUD)
    measureGPU("6. Single-Pass Fused Bilinear", kIterations, [&]() {
        struct { UINT srcW, srcH, dstX, dstY, mapW, mapH, filter, pad; } fcb = { 692, 692, 100, 100, 691, 691, 0, 0 };
        ctx->UpdateSubresource(cbFused, 0, nullptr, &fcb, 0, 0);
        ctx->CSSetShader(csSinglePass, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbFused);
        ctx->CSSetShaderResources(0, 1, &srcSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        ctx->CSSetShaderResources(0, 1, &nullSRV);
    });

    // 7. Direct 1:1 Map Blend (691 -> 691 zero resample)
    measureGPU("7. Direct 1:1 Map Blend (No Resample)", kIterations, [&]() {
        struct { UINT dstX, dstY, mapW, mapH; } dcb = { 100, 100, 691, 691 };
        ctx->UpdateSubresource(cbBlend, 0, nullptr, &dcb, 0, 0);
        ctx->CSSetShader(csDirect1to1, nullptr, 0);
        ctx->CSSetConstantBuffers(0, 1, &cbBlend);
        ctx->CSSetShaderResources(0, 1, &interSRV);
        ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
        ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
        ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
        ctx->CSSetShaderResources(0, 1, &nullSRV);
    });

    std::cout << "=== MICROBENCHMARK COMPLETE ===" << std::endl;
    return 0;
}
