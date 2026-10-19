#include "bar_indicator.h"
#include <algorithm>
#include <cmath>

BarIndicator::BarIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache)
    : m_key(desc.key)
    , m_type(desc.type)
    , m_style(desc.style.bar)
    , m_cx(desc.x)
    , m_cy(desc.y)
    , m_width(desc.width)
    , m_height(desc.height)
    , m_rotation(desc.rotation)
    , m_alpha(desc.alpha)
    , m_z_order(desc.z_order)
    , m_pFontCache(pFontCache)
    , m_pTrackBrush(nullptr)
    , m_pShadowBrush(nullptr)
    , m_pTickBrush(nullptr)
    , m_pTextBrush(nullptr)
    , m_pDimTextBrush(nullptr)
    , m_pMarkerBrush(nullptr)
    , m_pMarkerBorderBrush(nullptr)
    , m_pOutlineBrush(nullptr)
    , m_pFmtTitle(nullptr)
    , m_pFmtRange(nullptr)
    , m_pFmtValue(nullptr)
{
}

BarIndicator::~BarIndicator() {
    DiscardDeviceResources();
}

bool BarIndicator::CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) {
    DiscardDeviceResources();

    if (!pD2D || !pDWrite || !m_pFontCache) return false;

    // Brushes
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.track_color ? m_style.track_color : 0xFFF4F4F4), &m_pTrackBrush);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.0f, 0.0f, 0.0f, 0.5f), &m_pShadowBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.tick_color ? m_style.tick_color : 0xFFF6F6F6), &m_pTickBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.text_color ? m_style.text_color : 0xFFF4F4F4), &m_pTextBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.dim_text_color ? m_style.dim_text_color : 0xFFE0E0E0), &m_pDimTextBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.marker_color ? m_style.marker_color : 0xFFFFFFFF), &m_pMarkerBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.marker_border_color ? m_style.marker_border_color : 0xFFD8D8D8), &m_pMarkerBorderBrush);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.0f, 0.0f, 0.0f, 1.0f), &m_pOutlineBrush);

    const wchar_t* family = m_style.font_family[0] ? m_style.font_family : L"Arial";

    m_pFmtTitle = m_pFontCache->GetFormat(family, m_style.title_font_size > 0 ? m_style.title_font_size : 40.0f, DWRITE_FONT_WEIGHT_SEMI_BOLD);
    m_pFmtRange = m_pFontCache->GetFormat(family, m_style.range_font_size > 0 ? m_style.range_font_size : 32.0f);
    m_pFmtValue = m_pFontCache->GetFormat(family, m_style.value_font_size > 0 ? m_style.value_font_size : 48.0f, DWRITE_FONT_WEIGHT_BOLD);

    return (m_pTrackBrush && m_pShadowBrush && m_pTickBrush && m_pTextBrush && m_pMarkerBrush && m_pOutlineBrush);
}

void BarIndicator::DiscardDeviceResources() {
    if (m_pTrackBrush) { m_pTrackBrush->Release(); m_pTrackBrush = nullptr; }
    if (m_pShadowBrush) { m_pShadowBrush->Release(); m_pShadowBrush = nullptr; }
    if (m_pTickBrush) { m_pTickBrush->Release(); m_pTickBrush = nullptr; }
    if (m_pTextBrush) { m_pTextBrush->Release(); m_pTextBrush = nullptr; }
    if (m_pDimTextBrush) { m_pDimTextBrush->Release(); m_pDimTextBrush = nullptr; }
    if (m_pMarkerBrush) { m_pMarkerBrush->Release(); m_pMarkerBrush = nullptr; }
    if (m_pMarkerBorderBrush) { m_pMarkerBorderBrush->Release(); m_pMarkerBorderBrush = nullptr; }
    if (m_pOutlineBrush) { m_pOutlineBrush->Release(); m_pOutlineBrush = nullptr; }
    m_pFmtTitle = nullptr;
    m_pFmtRange = nullptr;
    m_pFmtValue = nullptr;
}

void BarIndicator::Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    if (!pD2D || !m_pTrackBrush) return;

    if (m_type == TELEM_IND_BAR_RULER_V) {
        RenderVertical(pD2D, state);
    } else {
        RenderHorizontal(pD2D, state);
    }
}

void BarIndicator::RenderHorizontal(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    float x1 = (m_style.track_canvas_x > 0.0f) ? m_style.track_canvas_x : (m_cx - m_width * 0.5f);
    float track_len = (m_style.track_len > 0.0f) ? m_style.track_len : m_width;
    float x2 = x1 + track_len;
    float y = (m_style.track_canvas_y > 0.0f) ? m_style.track_canvas_y : m_cy;

    float track_w = m_style.track_width > 0 ? m_style.track_width : 3.0f;
    float major_l = m_style.major_len > 0 ? m_style.major_len : 34.0f;
    float minor_l = m_style.minor_len > 0 ? m_style.minor_len : 20.0f;
    float outline_w = m_style.outline_width > 0 ? m_style.outline_width : 6.0f;

    // 1. Static: Track shadow & Track line
    pD2D->DrawLine(D2D1::Point2F(x1, y + 2.0f), D2D1::Point2F(x2, y + 2.0f), m_pShadowBrush, track_w + 2.0f);
    pD2D->DrawLine(D2D1::Point2F(x1, y), D2D1::Point2F(x2, y), m_pTrackBrush, track_w);

    // 2. Static: Ticks (extending upwards from track_y)
    int major_divs = m_style.major_divisions > 0 ? m_style.major_divisions : 10;
    int minor_per = m_style.minor_per_major > 0 ? m_style.minor_per_major : 5;
    int total_divs = major_divs * minor_per;

    for (int i = 0; i <= total_divs; ++i) {
        float frac = (float)i / (float)total_divs;
        float tx = x1 + frac * (x2 - x1);
        bool is_major = (i % minor_per == 0);
        float tl = is_major ? major_l : minor_l;
        float tw = is_major ? (track_w * 1.3f) : track_w;

        // Draw tick shadow and tick extending upwards
        pD2D->DrawLine(D2D1::Point2F(tx, y + 2.0f), D2D1::Point2F(tx, y - tl + 2.0f), m_pShadowBrush, tw + 2.0f);
        pD2D->DrawLine(D2D1::Point2F(tx, y), D2D1::Point2F(tx, y - tl), m_pTickBrush, tw);
    }

    // 3. Static: Title at top (centered above track)
    if (m_style.show_label && m_style.title[0] && m_pFmtTitle) {
        std::wstring upperTitle = m_style.title;
        for (auto& c : upperTitle) c = towupper(c);
        float title_y = (m_style.title_canvas_y > 0.0f) ? m_style.title_canvas_y : (y - major_l - 60.0f);
        float title_x = (m_style.title_canvas_x > 0.0f) ? m_style.title_canvas_x : (x1 + track_len * 0.5f);
        D2D1_RECT_F titleRect = D2D1::RectF(title_x - 1000.0f, title_y, title_x + 1000.0f, title_y + 55.0f);
        FontCache::DrawTextOutlined(pD2D, upperTitle.c_str(), m_pFmtTitle, titleRect, m_pTextBrush, m_pOutlineBrush, outline_w, DWRITE_TEXT_ALIGNMENT_CENTER);
    }

    // 4. Static: Range labels (min, mid, max) below track
    if (m_style.show_range && m_pFmtRange) {
        wchar_t wMin[32], wMax[32], wMid[32];
        if (m_style.range_units && m_style.unit[0]) {
            swprintf_s(wMin, L"%.0f %s", m_style.min_val, m_style.unit);
            swprintf_s(wMax, L"%.0f %s", m_style.max_val, m_style.unit);
            swprintf_s(wMid, L"%.0f %s", (m_style.min_val + m_style.max_val) * 0.5f, m_style.unit);
        } else {
            swprintf_s(wMin, L"%.0f", m_style.min_val);
            swprintf_s(wMax, L"%.0f", m_style.max_val);
            swprintf_s(wMid, L"%.0f", (m_style.min_val + m_style.max_val) * 0.5f);
        }

        float range_y = (m_style.range_canvas_y > 0.0f) ? m_style.range_canvas_y : (y + 16.0f);

        // Min label (leading / left-aligned)
        D2D1_RECT_F minRect = D2D1::RectF(x1, range_y, x1 + 250.0f, range_y + 40.0f);
        FontCache::DrawTextOutlined(pD2D, wMin, m_pFmtRange, minRect, m_pDimTextBrush, m_pOutlineBrush, outline_w * 0.8f, DWRITE_TEXT_ALIGNMENT_LEADING);

        // Mid label (centered)
        if (m_style.show_mid) {
            float mid_x = x1 + track_len * 0.5f;
            D2D1_RECT_F midRect = D2D1::RectF(mid_x - 150.0f, range_y, mid_x + 150.0f, range_y + 40.0f);
            FontCache::DrawTextOutlined(pD2D, wMid, m_pFmtRange, midRect, m_pDimTextBrush, m_pOutlineBrush, outline_w * 0.8f, DWRITE_TEXT_ALIGNMENT_CENTER);
        }

        // Max label (trailing / right-aligned)
        D2D1_RECT_F maxRect = D2D1::RectF(x2 - 250.0f, range_y, x2, range_y + 40.0f);
        FontCache::DrawTextOutlined(pD2D, wMax, m_pFmtRange, maxRect, m_pDimTextBrush, m_pOutlineBrush, outline_w * 0.8f, DWRITE_TEXT_ALIGNMENT_TRAILING);
    }

    // 5. Dynamic: Live value marker & value text
    float raw_val = 0.0f;
    const char* val_str = "";

    if (m_key == "fit_distance_text" || m_style.telemetry_field == TELEM_FIELD_DISTANCE) {
        raw_val = state.distance_km;
        val_str = state.distance_str;
    } else if (m_key == "fit_solar_text" || m_style.telemetry_field == TELEM_FIELD_SOLAR) {
        raw_val = state.solar_pct;
        val_str = state.solar_str;
    } else if (m_key == "fit_curVpower_text" || m_style.telemetry_field == TELEM_FIELD_POWER) {
        raw_val = state.power_w;
        val_str = state.power_str;
    }

    float span = m_style.max_val - m_style.min_val;
    if (span <= 0.001f) span = 1.0f;
    float norm_frac = std::max(0.0f, std::min(1.0f, (raw_val - m_style.min_val) / span));

    bool has_valid_val = (val_str && val_str[0] && strcmp(val_str, "--") != 0);
    float marker_x = has_valid_val ? (x1 + norm_frac * track_len) : (x1 + track_len * 0.5f);
    float dot_radius = m_style.marker_size > 0 ? (m_style.marker_size * 1.5f) : 12.0f;

    if (has_valid_val) {
        // Marker shadow & dot
        D2D1_ELLIPSE dotShadow = D2D1::Ellipse(D2D1::Point2F(marker_x, y + 2.0f), dot_radius + 2.0f, dot_radius + 2.0f);
        pD2D->FillEllipse(&dotShadow, m_pShadowBrush);

        D2D1_ELLIPSE dot = D2D1::Ellipse(D2D1::Point2F(marker_x, y), dot_radius, dot_radius);
        pD2D->FillEllipse(&dot, m_pMarkerBrush);
        pD2D->DrawEllipse(&dot, m_pMarkerBorderBrush, 2.5f);
    }

    // Dynamic value text (above track, centered at marker_x)
    if (m_style.show_value && m_pFmtValue && val_str && val_str[0]) {
        std::wstring fullValText;
        wchar_t wVal[64] = { 0 };
        MultiByteToWideChar(CP_UTF8, 0, val_str, -1, wVal, 64);
        fullValText = wVal;
        if (has_valid_val && m_style.unit[0] && fullValText.find(m_style.unit) == std::wstring::npos) {
            fullValText += L" ";
            fullValText += m_style.unit;
        }

        float val_y = (m_style.value_canvas_y > 0.0f) ? (m_style.value_canvas_y + m_style.value_offset_y) : (y - major_l - 48.0f);
        float val_center_x = marker_x + m_style.value_offset_x;
        
        // Clamp value center so text stays within [x1, x2] matching Pillow _draw_text_bounded
        float approx_half_w = 70.0f;
        if (val_center_x - approx_half_w < x1) {
            val_center_x = x1 + approx_half_w;
        } else if (val_center_x + approx_half_w > x2) {
            val_center_x = x2 - approx_half_w;
        }

        D2D1_RECT_F valRect = D2D1::RectF(val_center_x - 200.0f, val_y, val_center_x + 200.0f, val_y + 55.0f);
        FontCache::DrawTextOutlined(pD2D, fullValText.c_str(), m_pFmtValue, valRect, m_pTextBrush, m_pOutlineBrush, outline_w, DWRITE_TEXT_ALIGNMENT_CENTER);
    }
}

void BarIndicator::RenderVertical(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    float x = (m_style.track_canvas_x > 0.0f) ? m_style.track_canvas_x : m_cx;
    float y1 = (m_style.track_canvas_y > 0.0f) ? m_style.track_canvas_y : (m_cy - m_height * 0.5f);
    float track_len = (m_style.track_len > 0.0f) ? m_style.track_len : m_height;
    float y2 = y1 + track_len;

    float track_w = m_style.track_width > 0 ? m_style.track_width : 3.0f;
    float major_l = m_style.major_len > 0 ? m_style.major_len : 44.0f;
    float minor_l = m_style.minor_len > 0 ? m_style.minor_len : 24.0f;
    float outline_w = m_style.outline_width > 0 ? m_style.outline_width : 6.0f;

    // 1. Static: Track shadow & Track line
    pD2D->DrawLine(D2D1::Point2F(x + 2.0f, y1), D2D1::Point2F(x + 2.0f, y2), m_pShadowBrush, track_w + 2.0f);
    pD2D->DrawLine(D2D1::Point2F(x, y1), D2D1::Point2F(x, y2), m_pTrackBrush, track_w);

    // 2. Static: Ticks extending to left
    int major_divs = m_style.major_divisions > 0 ? m_style.major_divisions : 5;
    int minor_per = m_style.minor_per_major > 0 ? m_style.minor_per_major : 5;
    int total_divs = major_divs * minor_per;

    for (int i = 0; i <= total_divs; ++i) {
        float frac = (float)i / (float)total_divs;
        float ty = y2 - frac * (y2 - y1);
        bool is_major = (i % minor_per == 0);
        float tl = is_major ? major_l : minor_l;
        float tw = is_major ? (track_w * 1.3f) : track_w;

        // Draw tick shadow and tick extending left
        pD2D->DrawLine(D2D1::Point2F(x - tl, ty + 2.0f), D2D1::Point2F(x, ty + 2.0f), m_pShadowBrush, tw + 2.0f);
        pD2D->DrawLine(D2D1::Point2F(x - tl, ty), D2D1::Point2F(x, ty), m_pTickBrush, tw);

        if (is_major && m_style.show_tick_labels && m_pFmtRange) {
            float tick_val = m_style.min_val + frac * (m_style.max_val - m_style.min_val);
            wchar_t wTick[32];
            swprintf_s(wTick, L"%.0f", tick_val);
            D2D1_RECT_F tickRect = D2D1::RectF(x - tl - 60.0f, ty - 18.0f, x - tl - 8.0f, ty + 18.0f);
            FontCache::DrawTextOutlined(pD2D, wTick, m_pFmtRange, tickRect, m_pDimTextBrush, m_pOutlineBrush, outline_w * 0.8f, DWRITE_TEXT_ALIGNMENT_TRAILING);
        }
    }

    // 3. Dynamic: Live value marker & value text
    float raw_val = state.altitude_m;
    const char* val_str = state.altitude_str;

    float span = m_style.max_val - m_style.min_val;
    if (span <= 0.001f) span = 1.0f;
    float norm_frac = std::max(0.0f, std::min(1.0f, (raw_val - m_style.min_val) / span));

    float marker_y = y2 - norm_frac * (y2 - y1);
    float dot_radius = m_style.marker_size > 0 ? (m_style.marker_size * 1.5f) : 12.0f;

    // Marker shadow & dot
    D2D1_ELLIPSE dotShadow = D2D1::Ellipse(D2D1::Point2F(x + 2.0f, marker_y + 2.0f), dot_radius + 2.0f, dot_radius + 2.0f);
    pD2D->FillEllipse(&dotShadow, m_pShadowBrush);

    D2D1_ELLIPSE dot = D2D1::Ellipse(D2D1::Point2F(x, marker_y), dot_radius, dot_radius);
    pD2D->FillEllipse(&dot, m_pMarkerBrush);
    pD2D->DrawEllipse(&dot, m_pMarkerBorderBrush, 2.5f);

    // Dynamic value text to the right of the marker
    if (m_style.show_value && val_str[0] && m_pFmtValue) {
        wchar_t wVal[64] = { 0 };
        MultiByteToWideChar(CP_UTF8, 0, val_str, -1, wVal, 64);
        std::wstring fullValText = wVal;
        if (m_style.unit[0]) {
            fullValText += L" ";
            fullValText += m_style.unit;
        }

        float val_x = (m_style.value_canvas_y > 0.0f) ? m_style.value_canvas_y : (x + dot_radius + 12.0f);
        D2D1_RECT_F valRect = D2D1::RectF(val_x, marker_y - 25.0f, val_x + 350.0f, marker_y + 25.0f);
        FontCache::DrawTextOutlined(pD2D, fullValText, m_pFmtValue, valRect, m_pTextBrush, m_pOutlineBrush, outline_w, DWRITE_TEXT_ALIGNMENT_LEADING);
    }
}
