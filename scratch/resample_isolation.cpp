// Standalone isolation test for the ETAP 5G GPU map resample shader.
// Creates a D3D11 device, a small gradient input, runs the resample dispatch
// and reads the output back to verify the shader + dispatch mechanism works.
#include <d3d11.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <vector>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "d3dcompiler.lib")

static const char* g_resampleSource = R"(
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

int main() {
    HRESULT hr;
    D3D_FEATURE_LEVEL levels[] = { D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_1, D3D_FEATURE_LEVEL_10_0 };
    ID3D11Device* device = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    D3D_FEATURE_LEVEL got;
    hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, levels, 3,
                           D3D11_SDK_VERSION, &device, &got, &ctx);
    if (FAILED(hr) || !device || !ctx) {
        printf("FAILED to create device: 0x%08X\n", hr);
        return 1;
    }
    printf("Device feature level: 0x%X\n", got);

    // Input 692x692, red-green gradient, opaque
    const UINT srcW = 692, srcH = 692;
    std::vector<uint8_t> src(srcW * srcH * 4);
    for (UINT y = 0; y < srcH; ++y)
        for (UINT x = 0; x < srcW; ++x) {
            size_t o = ((size_t)y * srcW + x) * 4;
            src[o+0] = (uint8_t)(x * 255 / srcW);   // R: gradient
            src[o+1] = (uint8_t)(y * 255 / srcH);   // G: gradient
            src[o+2] = 0;
            src[o+3] = 255;
        }
    D3D11_TEXTURE2D_DESC td = {};
    td.Width = srcW; td.Height = srcH; td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_R8G8B8A8_UNORM; td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT; td.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* srcTex = nullptr;
    hr = device->CreateTexture2D(&td, nullptr, &srcTex);
    if (FAILED(hr)) { printf("create src tex failed 0x%08X\n", hr); return 1; }
    ctx->UpdateSubresource(srcTex, 0, nullptr, src.data(), srcW * 4, 0);
    ID3D11ShaderResourceView* srcSRV = nullptr;
    device->CreateShaderResourceView(srcTex, nullptr, &srcSRV);

    // Output 691x691 UAV+SRV
    const UINT dstW = 691, dstH = 691;
    D3D11_TEXTURE2D_DESC od = td;
    od.Width = dstW; od.Height = dstH; od.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_UNORDERED_ACCESS;
    ID3D11Texture2D* outTex = nullptr;
    hr = device->CreateTexture2D(&od, nullptr, &outTex);
    if (FAILED(hr)) { printf("create out tex failed 0x%08X\n", hr); return 1; }
    ID3D11UnorderedAccessView* outUAV = nullptr;
    device->CreateUnorderedAccessView(outTex, nullptr, &outUAV);
    ID3D11ShaderResourceView* outSRV = nullptr;
    device->CreateShaderResourceView(outTex, nullptr, &outSRV);

    // Compile the resample shader
    ID3DBlob* blob = nullptr; ID3DBlob* errors = nullptr;
    hr = D3DCompile(g_resampleSource, strlen(g_resampleSource), nullptr, nullptr, nullptr,
                    "CSMain", "cs_5_0", 0, 0, &blob, &errors);
    if (FAILED(hr)) {
        printf("D3DCompile FAILED: 0x%08X\n", hr);
        if (errors) { printf("%s\n", (char*)errors->GetBufferPointer()); errors->Release(); }
        return 1;
    }
    printf("Resample shader compiled OK (%zu bytes)\n", blob->GetBufferSize());
    ID3D11ComputeShader* cs = nullptr;
    hr = device->CreateComputeShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &cs);
    blob->Release();
    if (FAILED(hr) || !cs) { printf("CreateComputeShader failed 0x%08X\n", hr); return 1; }

    // CB
    struct { UINT srcW_, srcH_, dstW_, dstH_, filter, pad; } cb = { srcW, srcH, dstW, dstH, 2, 0 };
    D3D11_BUFFER_DESC bd = {};
    bd.ByteWidth = 32; bd.Usage = D3D11_USAGE_DEFAULT; bd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    ID3D11Buffer* cbuf = nullptr;
    hr = device->CreateBuffer(&bd, nullptr, &cbuf);
    if (FAILED(hr)) { printf("create cb failed 0x%08X\n", hr); return 1; }
    ctx->UpdateSubresource(cbuf, 0, nullptr, &cb, 0, 0);

    // Dispatch
    ctx->CSSetShader(cs, nullptr, 0);
    ctx->CSSetShaderResources(0, 1, &srcSRV);
    UINT zero[1] = { 0 };
    ctx->CSSetUnorderedAccessViews(0, 1, &outUAV, zero);
    ctx->Dispatch((dstW + 15) / 16, (dstH + 15) / 16, 1);
    ID3D11UnorderedAccessView* nullUAV = nullptr;
    ctx->CSSetUnorderedAccessViews(0, 1, &nullUAV, zero);

    // Read back
    D3D11_TEXTURE2D_DESC rd = od;
    rd.Usage = D3D11_USAGE_STAGING; rd.BindFlags = 0; rd.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ID3D11Texture2D* staging = nullptr;
    device->CreateTexture2D(&rd, nullptr, &staging);
    ctx->CopyResource(staging, outTex);
    D3D11_MAPPED_SUBRESOURCE mapped = {};
    hr = ctx->Map(staging, 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) { printf("Map failed 0x%08X\n", hr); return 1; }
    const uint8_t* p = (const uint8_t*)mapped.pData;
    printf("Output px[0]: %d,%d,%d,%d\n", p[0], p[1], p[2], p[3]);
    printf("Output px[345,345] (offset %d): %d,%d,%d,%d\n", (345 * (int)mapped.RowPitch + 345*4),
           p[345 * (int)mapped.RowPitch + 345*4], p[345*(int)mapped.RowPitch+345*4+1],
           p[345*(int)mapped.RowPitch+345*4+2], p[345*(int)mapped.RowPitch+345*4+3]);
    printf("Output px[690,690] (offset %d): %d,%d,%d,%d\n", (690*(int)mapped.RowPitch+690*4),
           p[690*(int)mapped.RowPitch+690*4], p[690*(int)mapped.RowPitch+690*4+1],
           p[690*(int)mapped.RowPitch+690*4+2], p[690*(int)mapped.RowPitch+690*4+3]);
    // sample some more pixels to check it's not all zero
    int nonzero = 0;
    for (int y = 0; y < (int)dstH; y += 32)
        for (int x = 0; x < (int)dstW; x += 32) {
            const uint8_t* q = p + (size_t)y * mapped.RowPitch + (size_t)x * 4;
            if (q[0] + q[1] + q[2] + q[3] > 0) nonzero++;
        }
    printf("Nonzero sampled pixels: %d\n", nonzero);
    ctx->Unmap(staging, 0);

    printf("RESULT: %s\n", nonzero > 0 ? "PASS - dispatch writes output" : "FAIL - output is all zeros");
    return nonzero > 0 ? 0 : 1;
}
