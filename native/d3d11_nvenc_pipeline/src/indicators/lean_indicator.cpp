#include "lean_indicator.h"
#include <algorithm>
#include <cmath>
#include <cwctype>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static D2D1_COLOR_F LeanColor(uint32_t c, uint32_t fallback) {
    return ColorFromHex(c ? c : fallback);
}

LeanIndicator::LeanIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache)
    : m_key(desc.key), m_style(desc.style.lean), m_cx(desc.x), m_cy(desc.y),
      m_width(desc.width), m_height(desc.height), m_rotation(desc.rotation),
      m_alpha(desc.alpha), m_z_order(desc.z_order), m_pFontCache(pFontCache),
      m_pMarkerBrush(nullptr), m_pTrackBrush(nullptr), m_pTickBrush(nullptr),
      m_pTextBrush(nullptr), m_pOutlineBrush(nullptr), m_pFmtTitle(nullptr),
      m_pFmtValue(nullptr) {}

LeanIndicator::~LeanIndicator() { DiscardDeviceResources(); }

bool LeanIndicator::CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) {
    DiscardDeviceResources();
    if (!pD2D || !pDWrite || !m_pFontCache) return false;

    pD2D->CreateSolidColorBrush(LeanColor(m_style.marker_color, 0xFFFFFFFF), &m_pMarkerBrush);
    pD2D->CreateSolidColorBrush(LeanColor(m_style.track_color, 0x8CFFFFFF), &m_pTrackBrush);
    pD2D->CreateSolidColorBrush(LeanColor(m_style.tick_color, 0x59FFFFFF), &m_pTickBrush);
    pD2D->CreateSolidColorBrush(LeanColor(m_style.text_color, 0xFFFFFFFF), &m_pTextBrush);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0, 0, 0, 0.90f), &m_pOutlineBrush);

    const wchar_t* family = m_style.font_family[0] ? m_style.font_family : L"Arial";
    m_pFmtTitle = m_pFontCache->GetFormat(family,
        m_style.title_font_size > 0 ? m_style.title_font_size : 54.0f);
    m_pFmtValue = m_pFontCache->GetFormat(family,
        m_style.value_font_size > 0 ? m_style.value_font_size : 48.0f,
        DWRITE_FONT_WEIGHT_NORMAL);
    return m_pMarkerBrush && m_pTrackBrush && m_pTickBrush && m_pTextBrush &&
           m_pOutlineBrush && m_pFmtTitle && m_pFmtValue;
}

void LeanIndicator::DiscardDeviceResources() {
    if (m_pMarkerBrush) { m_pMarkerBrush->Release(); m_pMarkerBrush = nullptr; }
    if (m_pTrackBrush) { m_pTrackBrush->Release(); m_pTrackBrush = nullptr; }
    if (m_pTickBrush) { m_pTickBrush->Release(); m_pTickBrush = nullptr; }
    if (m_pTextBrush) { m_pTextBrush->Release(); m_pTextBrush = nullptr; }
    if (m_pOutlineBrush) { m_pOutlineBrush->Release(); m_pOutlineBrush = nullptr; }
    m_pFmtTitle = nullptr;
    m_pFmtValue = nullptr;
}

void LeanIndicator::Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    if (!pD2D || !m_pMarkerBrush || !m_pTextBrush) return;
    const float g = std::max(32.0f, m_style.size_px > 0 ? m_style.size_px : 302.0f);
    const float pad = 8.0f;
    const bool showLabel = m_style.show_label != 0;
    const bool showValue = m_style.show_value != 0;
    const float titleH = (showLabel && m_style.title[0]) ? m_style.title_font_size * 1.25f : 0.0f;
    const float titleGap = titleH > 0 ? 5.0f : 0.0f;
    const float valueH = showValue ? m_style.value_font_size * 1.25f : 0.0f;
    const float valueGap = valueH > 0 ? 4.0f : 0.0f;
    const float top = m_cy - m_height * 0.5f + pad;
    const float centerY = top + titleH + titleGap + g * 0.5f;
    const float pivotX = m_cx + (m_style.pivot_x - 0.5f) * (g + 4.0f);
    const float pivotY = centerY + (m_style.pivot_y - 0.5f) * (g * 0.35f + 4.0f);
    const float angle = state.lean_visual_angle_deg;

    // Draw the rotated marker first.  On this D2D driver, a transformed
    // primitive issued after DirectWrite commands can invalidate the open
    // command stream; text is still horizontal because it follows the reset.
    pD2D->SetTransform(D2D1::Matrix3x2F::Rotation(-angle, D2D1::Point2F(pivotX, pivotY)));
    const float gw = g + 4.0f;
    const float gh = g * 0.35f + 4.0f;
    const float r = std::max(3.0f, g * 0.12f);
    const float wheelY = pivotY - gh * 0.5f;
    const float leftX = pivotX - gw * 0.5f + r;
    const float rightX = pivotX + gw * 0.5f - r;
    D2D1_ELLIPSE leftWheel = D2D1::Ellipse(D2D1::Point2F(leftX, wheelY), r, r);
    D2D1_ELLIPSE rightWheel = D2D1::Ellipse(D2D1::Point2F(rightX, wheelY), r, r);
    pD2D->FillEllipse(&leftWheel, m_pMarkerBrush);
    pD2D->FillEllipse(&rightWheel, m_pMarkerBrush);
    pD2D->DrawLine(D2D1::Point2F(leftX + r, wheelY),
                   D2D1::Point2F(rightX - r, wheelY), m_pMarkerBrush, 4.0f);
    pD2D->FillEllipse(D2D1::Ellipse(D2D1::Point2F(pivotX, pivotY),
                                   std::max(2.0f, g * 0.05f), std::max(2.0f, g * 0.05f)),
                      m_pTextBrush);
    pD2D->SetTransform(D2D1::Matrix3x2F::Identity());

    if (showLabel && m_style.title[0] && m_pFmtTitle) {
        std::wstring title(m_style.title);
        if (m_style.uppercase_title) {
            for (auto& ch : title) ch = (wchar_t)std::towupper(ch);
        }
        D2D1_RECT_F r = D2D1::RectF(m_cx - m_width * 0.5f, top,
                                    m_cx + m_width * 0.5f, top + titleH);
        FontCache::DrawTextOutlined(pD2D, title.c_str(), m_pFmtTitle, r,
                                    m_pTextBrush, m_pOutlineBrush,
                                    m_style.outline_width > 0 ? m_style.outline_width : 6.0f,
                                    DWRITE_TEXT_ALIGNMENT_CENTER);
    }

    if (m_style.show_reference && m_pTrackBrush) {
        pD2D->DrawLine(D2D1::Point2F(m_cx - g * 0.5f, centerY),
                       D2D1::Point2F(m_cx + g * 0.5f, centerY),
                       m_pTrackBrush, 1.4f);
    }
    if (m_style.show_ticks && m_pTickBrush) {
        const float maxAngle = std::max(1.0f, std::min(90.0f, m_style.max_angle));
        for (float tick = -maxAngle; tick <= maxAngle + 0.01f; tick += 10.0f) {
            const float x = m_cx + (tick / maxAngle) * (g * 0.5f - 4.0f);
            const float len = (std::fabs(std::fabs(tick) - maxAngle) < 0.01f) ? 4.0f : 3.0f;
            pD2D->DrawLine(D2D1::Point2F(x, centerY - len),
                           D2D1::Point2F(x, centerY + len), m_pTickBrush, 1.0f);
        }
    }

    // All DirectWrite calls are kept in the identity-transform portion after
    // the marker. This avoids the NVIDIA D2D command-stream hazard observed
    // when transformed geometry followed two DirectWrite blocks.
    if (showValue && m_pFmtValue) {
        wchar_t value[64] = {};
        const int decimals = std::max(0, m_style.decimals);
        swprintf_s(value, L"%+.*f", decimals, angle);
        std::wstring text(value);
        if (m_style.unit[0]) text += m_style.unit;
        D2D1_RECT_F rText = D2D1::RectF(m_cx - m_width * 0.5f,
                                        top + titleH + titleGap + g + valueGap,
                                        m_cx + m_width * 0.5f,
                                        top + titleH + titleGap + g + valueGap + valueH);
        FontCache::DrawTextOutlined(pD2D, text.c_str(), m_pFmtValue, rText,
                                    m_pTextBrush, m_pOutlineBrush,
                                    m_style.outline_width > 0 ? m_style.outline_width : 6.0f,
                                    DWRITE_TEXT_ALIGNMENT_CENTER);
    }

}
