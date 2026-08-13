#include "d3d11_vp_pipeline.h"

int main() {
    std::cout << "=================================================================" << std::endl;
    std::cout << " TeleM — AMD C++ ETAP 2B: Real P010 Surface → VideoProcessor NV12 " << std::endl;
    std::cout << "=================================================================" << std::endl;

    D3D11VideoProcessorPipeline pipeline;
    if (!pipeline.Initialize(3840, 2160)) {
        std::cerr << "Initialization failed!" << std::endl;
        return 1;
    }

    if (!pipeline.SetupVideoProcessor(DXGI_FORMAT_P010, DXGI_FORMAT_NV12)) {
        std::cerr << "VideoProcessor setup failed!" << std::endl;
        return 1;
    }

    std::cout << "\n[PASS] ETAP 2B Pipeline initialized successfully." << std::endl;
    return 0;
}
