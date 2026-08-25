#include "d3d11_compositor.h"

int main() {
    std::cout << "=========================================================" << std::endl;
    std::cout << " TeleM — AMD C++ ETAP 1: PoC Natywnego D3D11 Compositora " << std::endl;
    std::cout << "=========================================================" << std::endl;

    D3D11CompositorPoC poc;
    if (!poc.Initialize()) {
        std::cerr << "Initialization failed!" << std::endl;
        return 1;
    }

    if (!poc.CreateTextures(3840, 2160, 1920, 1264)) {
        std::cerr << "Texture creation failed!" << std::endl;
        return 1;
    }

    poc.VerifyAMFCompatibility();
    std::cout << "\n[PoC Success] Module initialized properly." << std::endl;
    return 0;
}
