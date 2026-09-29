#include "icon_cache.h"
#include <iostream>
#include <vector>

IconCache::IconCache() : m_pWicFactory(nullptr) {}

IconCache::~IconCache() {
    Clear();
}

bool IconCache::Init() {
    if (m_pWicFactory) return true;

    HRESULT hr = CoCreateInstance(
        CLSID_WICImagingFactory,
        NULL,
        CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(&m_pWicFactory)
    );

    // Candidate base directories for icon assets
    std::vector<std::wstring> candidates = {
        L"src/assets/icons/png/",
        L"../src/assets/icons/png/",
        L"../../src/assets/icons/png/",
        L"H:/_Dev/BikeRideHUD/src/assets/icons/png/"
    };

    for (const auto& dir : candidates) {
        std::wstring test_file = dir + L"camera.png";
        DWORD attr = GetFileAttributesW(test_file.c_str());
        if (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY)) {
            m_base_dir = dir;
            break;
        }
    }

    if (m_base_dir.empty()) {
        m_base_dir = L"src/assets/icons/png/";
    }

    return SUCCEEDED(hr) && m_pWicFactory != nullptr;
}

void IconCache::Clear() {
    for (auto& pair : m_bitmaps) {
        if (pair.second) {
            pair.second->Release();
        }
    }
    m_bitmaps.clear();

    if (m_pWicFactory) {
        m_pWicFactory->Release();
        m_pWicFactory = nullptr;
    }
}

ID2D1Bitmap* IconCache::GetIcon(ID2D1DeviceContext* pD2D, const std::string& icon_name) {
    if (!pD2D || icon_name.empty() || icon_name == "none") return nullptr;

    auto it = m_bitmaps.find(icon_name);
    if (it != m_bitmaps.end()) {
        return it->second;
    }

    if (!m_pWicFactory) {
        if (!Init()) return nullptr;
    }

    // Convert icon name to wide string path
    std::wstring wName(icon_name.begin(), icon_name.end());
    std::wstring full_path = m_base_dir + wName + L".png";

    IWICBitmapDecoder* pDecoder = nullptr;
    HRESULT hr = m_pWicFactory->CreateDecoderFromFilename(
        full_path.c_str(),
        NULL,
        GENERIC_READ,
        WICDecodeMetadataCacheOnDemand,
        &pDecoder
    );

    if (FAILED(hr) || !pDecoder) {
        // Cache as nullptr to avoid repeating failed disk hits
        m_bitmaps[icon_name] = nullptr;
        return nullptr;
    }

    IWICBitmapFrameDecode* pFrame = nullptr;
    hr = pDecoder->GetFrame(0, &pFrame);
    if (FAILED(hr) || !pFrame) {
        pDecoder->Release();
        m_bitmaps[icon_name] = nullptr;
        return nullptr;
    }

    IWICFormatConverter* pConverter = nullptr;
    hr = m_pWicFactory->CreateFormatConverter(&pConverter);
    if (FAILED(hr) || !pConverter) {
        pFrame->Release();
        pDecoder->Release();
        m_bitmaps[icon_name] = nullptr;
        return nullptr;
    }

    hr = pConverter->Initialize(
        pFrame,
        GUID_WICPixelFormat32bppPBGRA,
        WICBitmapDitherTypeNone,
        NULL,
        0.0,
        WICBitmapPaletteTypeCustom
    );

    ID2D1Bitmap* pBitmap = nullptr;
    if (SUCCEEDED(hr)) {
        hr = pD2D->CreateBitmapFromWicBitmap(pConverter, NULL, &pBitmap);
    }

    pConverter->Release();
    pFrame->Release();
    pDecoder->Release();

    if (SUCCEEDED(hr) && pBitmap) {
        m_bitmaps[icon_name] = pBitmap;
        return pBitmap;
    }

    m_bitmaps[icon_name] = nullptr;
    return nullptr;
}
