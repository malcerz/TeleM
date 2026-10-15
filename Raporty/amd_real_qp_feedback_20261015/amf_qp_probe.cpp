// Encoder-only AMF HEVC QP feedback probe (diagnostic, not part of the product).
// Feeds synthetic 4K NV12 textures through D3D11AMFEncoder (the production
// encoder class) and prints the raw statistics-feedback AMF_RESULT values.
// Build: cl /EHsc /O2 /std:c++17 /I<pipeline>/include /I<pipeline>/src amf_qp_probe.cpp <pipeline>/src/d3d11_amf_encoder.cpp d3d11.lib
#include <cstdio>
#include <cstdlib>
#include <random>
#include <vector>
#include "d3d11_amf_encoder.h"

int main(int argc, char** argv) {
    const UINT W = 3840, H = 2160;
    const int frames = (argc > 1) ? std::atoi(argv[1]) : 120;
    const uint64_t bitrate = (argc > 2) ? std::strtoull(argv[2], nullptr, 10) : 40000000ULL;

    ID3D11Device* dev = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    D3D_FEATURE_LEVEL fl;
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                   D3D11_CREATE_DEVICE_VIDEO_SUPPORT, nullptr, 0,
                                   D3D11_SDK_VERSION, &dev, &fl, &ctx);
    if (FAILED(hr)) { std::printf("D3D11CreateDevice failed 0x%08lx\n", hr); return 2; }

    // Pool of textures with different content so P-frames carry real residuals.
    const int poolSize = 8;
    std::vector<ID3D11Texture2D*> pool;
    std::mt19937 rng(1234);
    std::vector<uint8_t> nv12(W * H * 3 / 2);
    for (int i = 0; i < poolSize; ++i) {
        for (UINT y = 0; y < H; ++y)
            for (UINT x = 0; x < W; ++x)
                nv12[y * W + x] = static_cast<uint8_t>(((x + i * 37) ^ (y * 3)) + (rng() & 31));
        for (size_t j = W * H; j < nv12.size(); ++j) nv12[j] = static_cast<uint8_t>(128 + (rng() & 15));
        D3D11_TEXTURE2D_DESC d = {};
        d.Width = W; d.Height = H; d.MipLevels = 1; d.ArraySize = 1;
        d.Format = DXGI_FORMAT_NV12; d.SampleDesc.Count = 1;
        d.Usage = D3D11_USAGE_DEFAULT; d.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA sd = { nv12.data(), W, 0 };
        ID3D11Texture2D* t = nullptr;
        hr = dev->CreateTexture2D(&d, &sd, &t);
        if (FAILED(hr)) { std::printf("CreateTexture2D failed 0x%08lx\n", hr); return 3; }
        pool.push_back(t);
    }

    D3D11AMFEncoder enc;
    if (!enc.Initialize(dev, W, H, 30000, 1001, AMFCodecType::HEVC, AMFQualityPreset::FAST, bitrate)) {
        std::printf("encoder init failed\n"); return 4;
    }
    uint64_t bytes = 0, packets = 0;
    std::vector<uint8_t> pkt; int64_t pts = 0; bool key = false;
    for (int f = 0; f < frames; ++f) {
        while (!enc.SubmitTexture(pool[f % poolSize], static_cast<int64_t>(f) * 333667)) {
            if (enc.QueryPacket(pkt, pts, key)) { bytes += pkt.size(); packets++; }
            else Sleep(1);
        }
        while (enc.QueryPacket(pkt, pts, key)) { bytes += pkt.size(); packets++; }
    }
    enc.Flush();
    for (int spin = 0; spin < 2000; ++spin) {
        if (enc.QueryPacket(pkt, pts, key)) { bytes += pkt.size(); packets++; spin = 0; }
        else if (packets >= static_cast<uint64_t>(frames)) break;
        else Sleep(1);
    }
    const auto& s = enc.GetQPStats();
    const auto& d = enc.GetQPFeedbackDiag();
    std::printf("[PROBE] frames=%d packets=%llu bytes=%llu bitrate_bps=%.0f\n", frames,
                (unsigned long long)packets, (unsigned long long)bytes,
                packets ? bytes * 8.0 * 30000.0 / 1001.0 / packets : 0.0);
    std::printf("[PROBE] encoder_set=%d surface_flag=%d surface_set=%d ok=%llu fail=%llu outputs=%llu\n",
                d.encoderSetResult, d.surfaceFlagEnabled ? 1 : 0, d.surfaceSetResult,
                (unsigned long long)d.surfaceSetOk, (unsigned long long)d.surfaceSetFail,
                (unsigned long long)d.outputBuffers);
    std::printf("[PROBE] GetProperty last results: frameQP=%d avgQP=%d minQP=%d maxQP=%d\n",
                d.lastFrameQpResult, d.lastAvgQpResult, d.lastMinQpResult, d.lastMaxQpResult);
    std::printf("[PROBE] samples: frameQP=%llu avgQP=%llu minQP=%llu maxQP=%llu intra=%llu inter=%llu\n",
                (unsigned long long)d.frameQpSamples, (unsigned long long)d.avgQpSamples,
                (unsigned long long)d.minQpSamples, (unsigned long long)d.maxQpSamples,
                (unsigned long long)d.intraSamples, (unsigned long long)d.interSamples);
    std::printf("[PROBE] avg-series samples=%llu mean=%.2f min=%lld max=%lld last=%lld\n",
                (unsigned long long)s.samples, s.samples ? s.sum / s.samples : 0.0,
                (long long)s.minQp, (long long)s.maxQp, (long long)s.lastQp);
    enc.Shutdown();
    for (auto* t : pool) t->Release();
    ctx->Release(); dev->Release();
    return 0;
}
