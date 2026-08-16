// ETAP 5W — minimal D3D11 device create/release refcount probe.
// Answers: is device refcount==3 after teardown a runtime baseline or a leak
// introduced by the TeleM VP pipeline?
#include <windows.h>
#include <d3d11.h>
#include <cstdio>
#include <cstdlib>

int main(int argc, char** argv) {
    int n = argc > 1 ? atoi(argv[1]) : 1;
    UINT flags = D3D11_CREATE_DEVICE_VIDEO_SUPPORT;
    for (int i = 0; i < n; ++i) {
        ID3D11Device* dev = nullptr;
        ID3D11DeviceContext* ctx = nullptr;
        D3D_FEATURE_LEVEL fl;
        HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                       flags, nullptr, 0, D3D11_SDK_VERSION, &dev, &fl, &ctx);
        if (FAILED(hr) || !dev) { printf("create failed %08X\n", (unsigned)hr); return 1; }
        if (ctx) ctx->Release();
        ULONG r = dev->AddRef() - 1;
        dev->Release();
        printf("cycle %d: device refcount after ctx release = %lu\n", i, (unsigned long)r);
        dev->Release();
    }
    printf("done\n");
    return 0;
}
