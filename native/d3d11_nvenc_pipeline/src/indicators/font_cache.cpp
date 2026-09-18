#include "font_cache.h"
#include "../hud_profile.h"
#include <cmath>

FontCache::FontCache() : m_pDWriteFactory(nullptr) {}

FontCache::~FontCache() {
    Clear();
}

void FontCache::Init(IDWriteFactory* pDWriteFactory) {
    Clear();
    m_pDWriteFactory = pDWriteFactory;
    if (m_pDWriteFactory) {
        m_pDWriteFactory->AddRef();
    }
}

void FontCache::Clear() {
    for (auto& pair : m_formats) {
        if (pair.second) {
            pair.second->Release();
        }
    }
    m_formats.clear();

    if (m_pDWriteFactory) {
        m_pDWriteFactory->Release();
        m_pDWriteFactory = nullptr;
    }
}

IDWriteTextFormat* FontCache::GetFormat(const std::wstring& family, float size, DWRITE_FONT_WEIGHT weight, DWRITE_FONT_STYLE style) {
    if (!m_pDWriteFactory) return nullptr;

    int size_key = (int)std::round(size * 10.0f);
    auto key = std::make_tuple(family, size_key, (int)weight, (int)style);
    auto it = m_formats.find(key);
    if (it != m_formats.end()) {
        return it->second;
    }

    const wchar_t* font_fam = family.empty() ? L"Arial" : family.c_str();
    IDWriteTextFormat* pFormat = nullptr;
    HRESULT hr = m_pDWriteFactory->CreateTextFormat(
        font_fam,
        NULL,
        weight,
        style,
        DWRITE_FONT_STRETCH_NORMAL,
        size,
        L"en-us",
        &pFormat
    );

    if (FAILED(hr) || !pFormat) {
        // Fallback to Arial
        hr = m_pDWriteFactory->CreateTextFormat(
            L"Arial",
            NULL,
            weight,
            style,
            DWRITE_FONT_STRETCH_NORMAL,
            size,
            L"en-us",
            &pFormat
        );
    }

    if (SUCCEEDED(hr) && pFormat) {
        TelemHudProfile::Count("resource", "CreateTextFormat");
        m_formats[key] = pFormat;
        return pFormat;
    }

    return nullptr;
}

void FontCache::DrawTextOutlined(
    ID2D1DeviceContext* pD2D,
    const std::wstring& text,
    IDWriteTextFormat* pFormat,
    const D2D1_RECT_F& layoutRect,
    ID2D1Brush* pTextBrush,
    ID2D1Brush* pOutlineBrush,
    float outlineWidth,
    DWRITE_TEXT_ALIGNMENT align
) {
    if (!pD2D || !pFormat || text.empty()) return;
    const double text_t0 = TelemHudProfile::NowSeconds();

    pFormat->SetTextAlignment(align);

    if (outlineWidth > 0.5f && pOutlineBrush) {
        // 8-directional shadow passes for crisp, uniform outline matching Pillow stroke_width
        float d = outlineWidth * 0.85f;
        float d_diag = d * 0.7071f;

        const float offsets[8][2] = {
            { -d, 0.0f },
            {  d, 0.0f },
            { 0.0f, -d },
            { 0.0f,  d },
            { -d_diag, -d_diag },
            {  d_diag, -d_diag },
            { -d_diag,  d_diag },
            {  d_diag,  d_diag }
        };

        for (int i = 0; i < 8; ++i) {
            D2D1_RECT_F r = layoutRect;
            r.left   += offsets[i][0];
            r.right  += offsets[i][0];
            r.top    += offsets[i][1];
            r.bottom += offsets[i][1];
            pD2D->DrawText(text.c_str(), (UINT32)text.length(), pFormat, &r, pOutlineBrush);
            TelemHudProfile::Count("d2d", "DrawText");
        }
    }

    // Fill at exact origin
    pD2D->DrawText(text.c_str(), (UINT32)text.length(), pFormat, &layoutRect, pTextBrush);
    TelemHudProfile::Count("d2d", "DrawText");
    TelemHudProfile::Record("text", "dynamic", "DrawTextOutlined", (TelemHudProfile::NowSeconds() - text_t0) * 1000.0);
}
