#include "gauge_indicator.h"
#include <algorithm>
#include <cmath>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

GaugeIndicator::GaugeIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache)
    : m_key(desc.key)
    , m_style(desc.style.gauge)
    , m_cx(desc.x)
    , m_cy(desc.y)
    , m_width(desc.width)
    , m_height(desc.height)
    , m_rotation(desc.rotation)
    , m_alpha(desc.alpha)
    , m_z_order(desc.z_order)
    , m_pFontCache(pFontCache)
    , m_pDialBrush(nullptr)
    , m_pShadowBrush(nullptr)
    , m_pTickBrush(nullptr)
    , m_pTextBrush(nullptr)
    , m_pNeedleBrush(nullptr)
    , m_pOutlineBrush(nullptr)
    , m_pFmtGauge(nullptr)
    , m_pFmtValue(nullptr)
    , m_pFmtUnit(nullptr)
{
}

GaugeIndicator::~GaugeIndicator() {
    DiscardDeviceResources();
}

bool GaugeIndicator::CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) {
    DiscardDeviceResources();

    if (!pD2D || !pDWrite || !m_pFontCache) return false;

    // Brushes
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.85f, 0.85f, 0.85f, 1.0f), &m_pDialBrush);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.0f, 0.0f, 0.0f, 0.4f), &m_pShadowBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.tick_color ? m_style.tick_color : 0xFFF0F0F0), &m_pTickBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.text_color ? m_style.text_color : 0xFFFFFFFF), &m_pTextBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.needle_color ? m_style.needle_color : 0xFFFF0004), &m_pNeedleBrush);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.0f, 0.0f, 0.0f, 1.0f), &m_pOutlineBrush);

    const wchar_t* family = m_style.font_family[0] ? m_style.font_family : L"Arial";

    m_pFmtGauge = m_pFontCache->GetFormat(family, m_style.gauge_font_size > 0 ? m_style.gauge_font_size : 36.0f);
    m_pFmtValue = m_pFontCache->GetFormat(family, m_style.value_font_size > 0 ? m_style.value_font_size : 68.0f, DWRITE_FONT_WEIGHT_BOLD);
    m_pFmtUnit = m_pFontCache->GetFormat(family, m_style.unit_font_size > 0 ? m_style.unit_font_size : 32.0f, DWRITE_FONT_WEIGHT_SEMI_BOLD);

    return (m_pDialBrush && m_pTickBrush && m_pTextBrush && m_pNeedleBrush && m_pOutlineBrush);
}

void GaugeIndicator::DiscardDeviceResources() {
    if (m_pDialBrush) { m_pDialBrush->Release(); m_pDialBrush = nullptr; }
    if (m_pShadowBrush) { m_pShadowBrush->Release(); m_pShadowBrush = nullptr; }
    if (m_pTickBrush) { m_pTickBrush->Release(); m_pTickBrush = nullptr; }
    if (m_pTextBrush) { m_pTextBrush->Release(); m_pTextBrush = nullptr; }
    if (m_pNeedleBrush) { m_pNeedleBrush->Release(); m_pNeedleBrush = nullptr; }
    if (m_pOutlineBrush) { m_pOutlineBrush->Release(); m_pOutlineBrush = nullptr; }
    m_pFmtGauge = nullptr;
    m_pFmtValue = nullptr;
    m_pFmtUnit = nullptr;
}

void GaugeIndicator::Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    if (!pD2D || !m_pTickBrush || !m_pNeedleBrush) return;

    // Legacy gauge rasters are 2.4 * radius wide.  Native descriptors now
    // carry that exact outer side, so derive the dial radius from the same
    // contract instead of the old 0.42 approximation (which was several
    // pixels too large at 4K).
    float radius = m_width > 0 ? (m_width / 2.4f) : 320.0f;
    float cx = m_cx;
    float cy = m_cy;

    float start_deg = m_style.start_deg > 0 ? m_style.start_deg : 180.0f;
    float sweep_deg = m_style.sweep_deg > 0 ? m_style.sweep_deg : 180.0f;
    float end_deg = start_deg + sweep_deg;

    int major_intervals = m_style.major_intervals > 0 ? m_style.major_intervals : 3;
    int sub_ticks = m_style.sub_ticks_count > 0 ? m_style.sub_ticks_count : 10;
    int total_ticks = major_intervals * sub_ticks;
    if (total_ticks <= 0) total_ticks = 30;

    float min_val = m_style.min_val;
    float max_val = m_style.max_val > min_val ? m_style.max_val : 30.0f;
    float outline_w = m_style.outline_width > 0 ? m_style.outline_width : 5.0f;

    // 1. Static: Ticks & Tick Numbers
    for (int i = 0; i <= total_ticks; ++i) {
        float deg = start_deg + (end_deg - start_deg) * ((float)i / (float)total_ticks);
        float rad = (float)(deg * M_PI / 180.0);
        float cos_a = std::cos(rad);
        float sin_a = std::sin(rad);

        bool is_major = (i % sub_ticks == 0);
        bool is_mid = (!is_major && sub_ticks % 2 == 0 && (i % (sub_ticks / 2) == 0));

        float tick_len = is_major ? (radius * 0.12f) : (is_mid ? (radius * 0.075f) : (radius * 0.035f));
        float tick_width = is_major ? 4.5f : (is_mid ? 3.0f : 1.8f);

        float r_in = radius - tick_len;
        float r_out = radius;

        D2D1_POINT_2F p1 = D2D1::Point2F(cx + cos_a * r_in, cy + sin_a * r_in);
        D2D1_POINT_2F p2 = D2D1::Point2F(cx + cos_a * r_out, cy + sin_a * r_out);

        // Shadow & tick line
        pD2D->DrawLine(D2D1::Point2F(p1.x, p1.y + 2.0f), D2D1::Point2F(p2.x, p2.y + 2.0f), m_pShadowBrush, tick_width + 1.5f);
        pD2D->DrawLine(p1, p2, m_pTickBrush, tick_width);

        if (is_major && m_pFmtGauge) {
            float tick_val = min_val + (max_val - min_val) * ((float)i / (float)total_ticks);
            wchar_t wTick[32];
            swprintf_s(wTick, L"%.0f", tick_val);

            float text_r = radius - tick_len - (radius * 0.14f);
            float tx = cx + cos_a * text_r;
            float ty = cy + sin_a * text_r;

            D2D1_RECT_F textRect = D2D1::RectF(tx - 40.0f, ty - 20.0f, tx + 40.0f, ty + 20.0f);
            FontCache::DrawTextOutlined(pD2D, wTick, m_pFmtGauge, textRect, m_pTextBrush, m_pOutlineBrush, outline_w * 0.7f, DWRITE_TEXT_ALIGNMENT_CENTER);
        }
    }

    // 2. Dynamic: Needle (only if value is valid numeric, not "--")
    const char* val_str = state.speed_str[0] ? state.speed_str : "--";
    bool has_valid_val = (val_str[0] && strcmp(val_str, "--") != 0);

    if (has_valid_val) {
        float raw_speed = state.speed_kmh;
        float span = max_val - min_val;
        if (span <= 0.001f) span = 1.0f;
        float norm_frac = std::max(0.0f, std::min(1.0f, (raw_speed - min_val) / span));

        float needle_deg = start_deg + (end_deg - start_deg) * norm_frac;
        float needle_rad = (float)(needle_deg * M_PI / 180.0);
        float cos_n = std::cos(needle_rad);
        float sin_n = std::sin(needle_rad);

        float needle_len = radius * (m_style.needle_length > 0 ? m_style.needle_length : 0.88f);
        float needle_w = m_style.needle_width > 0 ? m_style.needle_width : 8.0f;

        D2D1_POINT_2F tip = D2D1::Point2F(cx + cos_n * needle_len, cy + sin_n * needle_len);

        // Draw needle shadow
        pD2D->DrawLine(D2D1::Point2F(cx, cy + 3.0f), D2D1::Point2F(tip.x, tip.y + 3.0f), m_pShadowBrush, needle_w + 2.0f);

        // Draw needle line with thickness tapering to tip
        pD2D->DrawLine(D2D1::Point2F(cx, cy), tip, m_pNeedleBrush, needle_w);
    }

    // Center white dot marker (always visible)
    D2D1_ELLIPSE hub = D2D1::Ellipse(D2D1::Point2F(cx, cy), 8.0f, 8.0f);
    pD2D->FillEllipse(&hub, m_pTextBrush);

    // 3. Dynamic: Center speed value & Unit on single line: "-- km/h" or "25.4 km/h"
    wchar_t wSpeed[64] = { 0 };
    MultiByteToWideChar(CP_UTF8, 0, val_str, -1, wSpeed, 64);

    std::wstring fullDigitalText = wSpeed;
    const wchar_t* unit_str = m_style.unit[0] ? m_style.unit : L"km/h";
    if (unit_str[0]) {
        fullDigitalText += L" ";
        fullDigitalText += unit_str;
    }

    if (m_pFmtValue) {
        // Pillow's Legacy value anchor is 15% of the dial radius below the
        // centre (the surrounding 2.4R raster already provides the lower
        // margin).  Keep the semantic baseline; glyph rasterisation is
        // intentionally allowed to differ between Pillow and DirectWrite.
        D2D1_RECT_F valRect = D2D1::RectF(cx - 200.0f, cy + radius * 0.15f, cx + 200.0f, cy + radius * 0.15f + 75.0f);
        FontCache::DrawTextOutlined(pD2D, fullDigitalText.c_str(), m_pFmtValue, valRect, m_pTextBrush, m_pOutlineBrush, outline_w, DWRITE_TEXT_ALIGNMENT_CENTER);
    }
}
