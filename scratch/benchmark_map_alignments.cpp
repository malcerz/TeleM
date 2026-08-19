#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <iostream>
#include <vector>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <algorithm>

// Standalone D3D11 Map Alignment GPU Microbenchmark
// Measures GPU execution time using D3D11 Timestamp Queries across 1000 iterations for various sizes.

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

    [numthreads(16, 16, 1)]
    void CSMain(uint3 tid : SV_DispatchThreadID) {
        if (tid.x >= dstW || tid.y >= dstH) return;
        float scaleX = float(srcW) / float(dstW);
        float scaleY = float(srcH) / float(dstH);
        float cx = (tid.x + 0.5) * scaleX - 0.5;
        float cy = (tid.y + 0.5) * scaleY - 0.5;

        int baseX = (int)floor(cx) - 2;
        int baseY = (int)floor(cy) - 2;
        int taps = 6;

        float3 premulRgb = 0.0;
        float alphaAcc = 0.0;
        float wsum = 0.0;
        for (int dy = 0; dy < taps; ++dy) {
            int iy = baseY + dy;
            float wy = Lanczos3(cy - iy);
            if (abs(wy) < 1e-6) continue;
            for (int dx = 0; dx < taps; ++dx) {
                int ix = baseX + dx;
                if (ix < 0 || ix >= (int)srcW || iy < 0 || iy >= (int)srcH) continue;
                float wx = Lanczos3(cx - ix);
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

int main() {
    std::cout << "================================================================" << std::endl;
    std::cout << "TeleM ETAP 8U-B-R: GPU Map Exact vs Quantized Alignment Benchmark" << std::endl;
    std::cout << "================================================================" << std::endl;

    D3D_FEATURE_LEVEL featLevel;
    ID3D11Device* dev = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    UINT createFlags = 0;
    HRESULT hr = D3D11CreateDevice(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, createFlags,
        nullptr, 0, D3D11_SDK_VERSION, &dev, &featLevel, &ctx);
    if (FAILED(hr)) {
        std::cerr << "Failed to create D3D11 hardware device: " << hr << std::endl;
        return 1;
    }

    IDXGIDevice* dxgiDev = nullptr;
    dev->QueryInterface(__uuidof(IDXGIDevice), (void**)&dxgiDev);
    IDXGIAdapter* adapter = nullptr;
    dxgiDev->GetAdapter(&adapter);
    DXGI_ADAPTER_DESC desc;
    adapter->GetDesc(&desc);
    std::wcout << L"GPU Adapter: " << desc.Description << L" (VRAM: " << desc.DedicatedVideoMemory / (1024*1024) << L" MiB)" << std::endl;
    adapter->Release();
    dxgiDev->Release();

    // Compile Compute Shaders
    ID3DBlob* blob = nullptr;
    ID3DBlob* err = nullptr;
    hr = D3DCompile(kResampleShaderSource, strlen(kResampleShaderSource), nullptr, nullptr, nullptr, "CSMain", "cs_5_0", 0, 0, &blob, &err);
    if (FAILED(hr)) {
        if (err) { std::cerr << (char*)err->GetBufferPointer() << std::endl; err->Release(); }
        return 1;
    }
    ID3D11ComputeShader* csResample = nullptr;
    dev->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &csResample);
    blob->Release();

    blob = nullptr; err = nullptr;
    hr = D3DCompile(kBlendShaderSource, strlen(kBlendShaderSource), nullptr, nullptr, nullptr, "CSMain", "cs_5_0", 0, 0, &blob, &err);
    if (FAILED(hr)) {
        if (err) { std::cerr << (char*)err->GetBufferPointer() << std::endl; err->Release(); }
        return 1;
    }
    ID3D11ComputeShader* csBlend = nullptr;
    dev->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &csBlend);
    blob->Release();

    // Constant Buffers
    D3D11_BUFFER_DESC cbd = {};
    cbd.Usage = D3D11_USAGE_DEFAULT;
    cbd.ByteWidth = sizeof(UINT) * 8;
    cbd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    ID3D11Buffer* cbResample = nullptr;
    dev->CreateBuffer(&cbd, nullptr, &cbResample);
    ID3D11Buffer* cbBlend = nullptr;
    dev->CreateBuffer(&cbd, nullptr, &cbBlend);

    // Create 4K HUD canvas UAV (1920x1264 for HUD texture)
    D3D11_TEXTURE2D_DESC td = {};
    td.Width = 1920;
    td.Height = 1264;
    td.MipLevels = 1;
    td.ArraySize = 1;
    td.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
    ID3D11Texture2D* hudTex = nullptr;
    dev->CreateTexture2D(&td, nullptr, &hudTex);
    ID3D11UnorderedAccessView* hudUAV = nullptr;
    dev->CreateUnorderedAccessView(hudTex, nullptr, &hudUAV);

    // Timestamp query objects
    D3D11_QUERY_DESC qd = {};
    qd.Query = D3D11_QUERY_TIMESTAMP_DISJOINT;
    ID3D11Query* qDisjoint = nullptr;
    dev->CreateQuery(&qd, &qDisjoint);
    qd.Query = D3D11_QUERY_TIMESTAMP;
    ID3D11Query* qBegin = nullptr;
    dev->CreateQuery(&qd, &qBegin);
    ID3D11Query* qEnd = nullptr;
    dev->CreateQuery(&qd, &qEnd);

    auto measureDirect = [&](UINT size, const char* alignmentName, int iters = 1000) {
        // Create source texture of exact size
        D3D11_TEXTURE2D_DESC srcDesc = {};
        srcDesc.Width = size;
        srcDesc.Height = size;
        srcDesc.MipLevels = 1;
        srcDesc.ArraySize = 1;
        srcDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        srcDesc.SampleDesc.Count = 1;
        srcDesc.Usage = D3D11_USAGE_DEFAULT;
        srcDesc.BindFlags = D3D11_BIND_SHADER_RESOURCE;

        std::vector<uint32_t> initData(size * size, 0xFF00FF00); // opaque green
        D3D11_SUBRESOURCE_DATA subData = {};
        subData.pSysMem = initData.data();
        subData.SysMemPitch = size * 4;

        ID3D11Texture2D* srcTex = nullptr;
        dev->CreateTexture2D(&srcDesc, &subData, &srcTex);
        ID3D11ShaderResourceView* srcSRV = nullptr;
        dev->CreateShaderResourceView(srcTex, nullptr, &srcSRV);

        UINT gx = (size + 15) / 16;
        UINT gy = (size + 15) / 16;
        UINT totalGroups = gx * gy;

        // Warmup
        for (int i = 0; i < 50; ++i) {
            struct { UINT dstX, dstY, mapW, mapH; } bcb = { 100, 100, size, size };
            ctx->UpdateSubresource(cbBlend, 0, nullptr, &bcb, 0, 0);
            ctx->CSSetShader(csBlend, nullptr, 0);
            ctx->CSSetConstantBuffers(0, 1, &cbBlend);
            ctx->CSSetShaderResources(0, 1, &srcSRV);
            UINT zeroCounts[1] = { 0 };
            ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
            ctx->Dispatch(gx, gy, 1);
            ID3D11UnorderedAccessView* nullUAV = nullptr;
            ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
            ID3D11ShaderResourceView* nullSRV = nullptr;
            ctx->CSSetShaderResources(0, 1, &nullSRV);
        }
        ctx->Flush();

        std::vector<double> timings;
        timings.reserve(iters);

        for (int i = 0; i < iters; ++i) {
            ctx->Begin(qDisjoint);
            ctx->End(qBegin);

            struct { UINT dstX, dstY, mapW, mapH; } bcb = { 100, 100, size, size };
            ctx->UpdateSubresource(cbBlend, 0, nullptr, &bcb, 0, 0);
            ctx->CSSetShader(csBlend, nullptr, 0);
            ctx->CSSetConstantBuffers(0, 1, &cbBlend);
            ctx->CSSetShaderResources(0, 1, &srcSRV);
            UINT zeroCounts[1] = { 0 };
            ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
            ctx->Dispatch(gx, gy, 1);
            ID3D11UnorderedAccessView* nullUAV = nullptr;
            ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
            ID3D11ShaderResourceView* nullSRV = nullptr;
            ctx->CSSetShaderResources(0, 1, &nullSRV);

            ctx->End(qEnd);
            ctx->End(qDisjoint);

            UINT64 tsBegin = 0, tsEnd = 0;
            D3D11_QUERY_DATA_TIMESTAMP_DISJOINT dj = {};
            while (ctx->GetData(qDisjoint, &dj, sizeof(dj), 0) == S_FALSE) {}
            while (ctx->GetData(qBegin, &tsBegin, sizeof(tsBegin), 0) == S_FALSE) {}
            while (ctx->GetData(qEnd, &tsEnd, sizeof(tsEnd), 0) == S_FALSE) {}

            if (!dj.Disjoint && dj.Frequency > 0 && tsEnd >= tsBegin) {
                double ms = double(tsEnd - tsBegin) / double(dj.Frequency) * 1000.0;
                timings.push_back(ms);
            }
        }

        std::sort(timings.begin(), timings.end());
        double med = timings.empty() ? 0.0 : timings[timings.size() / 2];
        double p95 = timings.empty() ? 0.0 : timings[size_t(timings.size() * 0.95)];
        double minT = timings.empty() ? 0.0 : timings.front();
        double maxT = timings.empty() ? 0.0 : timings.back();

        std::cout << std::left << std::setw(6) << size
                  << " | " << std::setw(15) << alignmentName
                  << " | " << std::setw(4) << gx << "x" << std::setw(4) << gy << " (" << std::setw(4) << totalGroups << " tg)"
                  << " | Med: " << std::fixed << std::setprecision(4) << med << " ms"
                  << " | P95: " << std::fixed << std::setprecision(4) << p95 << " ms"
                  << " | Min: " << std::fixed << std::setprecision(4) << minT << " ms"
                  << " | Max: " << std::fixed << std::setprecision(4) << maxT << " ms"
                  << std::endl;

        srcSRV->Release();
        srcTex->Release();
    };

    // Also measure Two-Pass Reference (692 -> 691 Lanczos3 + Blend)
    auto measureReference = [&](int iters = 1000) {
        D3D11_TEXTURE2D_DESC srcDesc = {};
        srcDesc.Width = 692; srcDesc.Height = 692; srcDesc.MipLevels = 1; srcDesc.ArraySize = 1;
        srcDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM; srcDesc.SampleDesc.Count = 1;
        srcDesc.Usage = D3D11_USAGE_DEFAULT; srcDesc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        ID3D11Texture2D* srcTex = nullptr; dev->CreateTexture2D(&srcDesc, nullptr, &srcTex);
        ID3D11ShaderResourceView* srcSRV = nullptr; dev->CreateShaderResourceView(srcTex, nullptr, &srcSRV);

        D3D11_TEXTURE2D_DESC interDesc = {};
        interDesc.Width = 691; interDesc.Height = 691; interDesc.MipLevels = 1; interDesc.ArraySize = 1;
        interDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM; interDesc.SampleDesc.Count = 1;
        interDesc.Usage = D3D11_USAGE_DEFAULT; interDesc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
        ID3D11Texture2D* interTex = nullptr; dev->CreateTexture2D(&interDesc, nullptr, &interTex);
        ID3D11UnorderedAccessView* interUAV = nullptr; dev->CreateUnorderedAccessView(interTex, nullptr, &interUAV);
        ID3D11ShaderResourceView* interSRV = nullptr; dev->CreateShaderResourceView(interTex, nullptr, &interSRV);

        std::vector<double> timings;
        timings.reserve(iters);

        for (int i = 0; i < iters; ++i) {
            ctx->Begin(qDisjoint);
            ctx->End(qBegin);

            // Pass 1: Resample
            struct { UINT srcW, srcH, dstW, dstH, filter, pad; } rcb = { 692, 692, 691, 691, 2, 0 };
            ctx->UpdateSubresource(cbResample, 0, nullptr, &rcb, 0, 0);
            ctx->CSSetShader(csResample, nullptr, 0);
            ctx->CSSetConstantBuffers(0, 1, &cbResample);
            ctx->CSSetShaderResources(0, 1, &srcSRV);
            UINT zeroCounts[1] = { 0 };
            ctx->CSSetUnorderedAccessViews(0, 1, &interUAV, zeroCounts);
            ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
            ID3D11UnorderedAccessView* nullUAV = nullptr;
            ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
            ID3D11ShaderResourceView* nullSRV = nullptr;
            ctx->CSSetShaderResources(0, 1, &nullSRV);

            // Pass 2: Blend
            struct { UINT dstX, dstY, mapW, mapH; } bcb = { 100, 100, 691, 691 };
            ctx->UpdateSubresource(cbBlend, 0, nullptr, &bcb, 0, 0);
            ctx->CSSetShader(csBlend, nullptr, 0);
            ctx->CSSetConstantBuffers(0, 1, &cbBlend);
            ctx->CSSetShaderResources(0, 1, &interSRV);
            ctx->CSSetUnorderedAccessViews(0, 1, &hudUAV, zeroCounts);
            ctx->Dispatch((691 + 15) / 16, (691 + 15) / 16, 1);
            ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zeroCounts);
            ctx->CSSetShaderResources(0, 1, &nullSRV);

            ctx->End(qEnd);
            ctx->End(qDisjoint);

            UINT64 tsBegin = 0, tsEnd = 0;
            D3D11_QUERY_DATA_TIMESTAMP_DISJOINT dj = {};
            while (ctx->GetData(qDisjoint, &dj, sizeof(dj), 0) == S_FALSE) {}
            while (ctx->GetData(qBegin, &tsBegin, sizeof(tsBegin), 0) == S_FALSE) {}
            while (ctx->GetData(qEnd, &tsEnd, sizeof(tsEnd), 0) == S_FALSE) {}

            if (!dj.Disjoint && dj.Frequency > 0 && tsEnd >= tsBegin) {
                timings.push_back(double(tsEnd - tsBegin) / double(dj.Frequency) * 1000.0);
            }
        }
        std::sort(timings.begin(), timings.end());
        double med = timings[timings.size() / 2];
        double p95 = timings[size_t(timings.size() * 0.95)];
        std::cout << std::left << std::setw(6) << 691
                  << " | " << std::setw(15) << "REFERENCE 2-PASS"
                  << " | " << std::setw(4) << 44 << "x" << std::setw(4) << 44 << " (1936x2 tg)"
                  << " | Med: " << std::fixed << std::setprecision(4) << med << " ms"
                  << " | P95: " << std::fixed << std::setprecision(4) << p95 << " ms"
                  << std::endl;

        interSRV->Release(); interUAV->Release(); interTex->Release();
        srcSRV->Release(); srcTex->Release();
    };

    std::cout << "\n--- REFERENCE 2-PASS LANCZOS3 (692 -> 691) ---" << std::endl;
    measureReference(1000);

    std::cout << "\n--- DIRECT 1:1 BLEND ACROSS ALIGNMENTS (1000 iterations each) ---" << std::endl;
    std::cout << "Size   | Alignment Type  | Thread Groups           | Median Time | P95 Time    | Min Time    | Max Time" << std::endl;
    std::cout << "-------+-----------------+-------------------------+-------------+-------------+-------------+------------" << std::endl;

    measureDirect(672, "32-px aligned", 1000);
    measureDirect(688, "16-px aligned", 1000);
    measureDirect(691, "EXACT (Odd)",   1000);
    measureDirect(696, "8-px aligned",  1000);
    measureDirect(704, "32-px aligned", 1000);
    measureDirect(720, "16-px aligned", 1000);

    std::cout << "\n================================================================" << std::endl;

    qEnd->Release();
    qBegin->Release();
    qDisjoint->Release();
    hudUAV->Release();
    hudTex->Release();
    cbBlend->Release();
    cbResample->Release();
    csBlend->Release();
    csResample->Release();
    ctx->Release();
    dev->Release();
    return 0;
}
