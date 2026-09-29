#include "segment_bar_indicator.h"
#include <algorithm>
#include <cmath>

SegmentBarIndicator::SegmentBarIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache)
    : m_key(desc.key)
    , m_style(desc.style.segment_bar)
    , m_cx(desc.x)
    , m_cy(desc.y)
    , m_width(desc.width)
    , m_height(desc.height)
    , m_rotation(desc.rotation)
    , m_alpha(desc.alpha)
    , m_z_order(desc.z_order)
    , m_pFontCache(pFontCache)
    , m_pActiveBrush(nullptr)
    , m_pInactiveBrush(nullptr)
    , m_numSegBrushes(0)
    , m_pTextBrush(nullptr)
    , m_pDimBrush(nullptr)
    , m_pOutlineBrush(nullptr)
    , m_pFmtLabel(nullptr)
    , m_pFmtValue(nullptr)
    , m_pFmtRange(nullptr)
{
    for (int i = 0; i < 64; ++i) m_pSegBrushes[i] = nullptr;
}

SegmentBarIndicator::~SegmentBarIndicator() {
    DiscardDeviceResources();
}

bool SegmentBarIndicator::CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) {
    DiscardDeviceResources();

    if (!pD2D || !pDWrite || !m_pFontCache) return false;

    // Brushes
    uint32_t actCol = m_style.active_color ? m_style.active_color : 0xFF16A7AF;
    pD2D->CreateSolidColorBrush(ColorFromHex(actCol), &m_pActiveBrush);

    // Inactive brush: 0x5F3E3E3E (Pillow RGBA: (62, 62, 62, 95))
    uint32_t inactCol = m_style.inactive_color ? m_style.inactive_color : 0x5F3E3E3E;
    pD2D->CreateSolidColorBrush(ColorFromHex(inactCol), &m_pInactiveBrush);

    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.text_color ? m_style.text_color : 0xFFFFFFFF), &m_pTextBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.dim_color ? m_style.dim_color : 0xFFE0E0E0), &m_pDimBrush);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.0f, 0.0f, 0.0f, 1.0f), &m_pOutlineBrush);

    // Create 30 segment gradient brushes matching Pillow stops ('#16A7AF', '#FF9A2E')
    int num_segs = m_style.segments > 0 ? m_style.segments : 30;
    if (num_segs > 64) num_segs = 64;
    m_numSegBrushes = num_segs;

    uint32_t colStart = m_style.active_color_start ? m_style.active_color_start : 0xFF16A7AF;
    uint32_t colEnd = m_style.active_color_end ? m_style.active_color_end : 0xFFFF9A2E;

    float r0 = (float)((colStart >> 16) & 0xFF) / 255.0f;
    float g0 = (float)((colStart >> 8) & 0xFF) / 255.0f;
    float b0 = (float)(colStart & 0xFF) / 255.0f;

    float r1 = (float)((colEnd >> 16) & 0xFF) / 255.0f;
    float g1 = (float)((colEnd >> 8) & 0xFF) / 255.0f;
    float b1 = (float)(colEnd & 0xFF) / 255.0f;

    for (int i = 0; i < num_segs; ++i) {
        float p = (num_segs > 1) ? ((float)i / (float)(num_segs - 1)) : 0.0f;
        D2D1_COLOR_F segColor = D2D1::ColorF(
            r0 + p * (r1 - r0),
            g0 + p * (g1 - g0),
            b0 + p * (b1 - b0),
            1.0f
        );
        pD2D->CreateSolidColorBrush(segColor, &m_pSegBrushes[i]);
    }

    const wchar_t* family = m_style.font_family[0] ? m_style.font_family : L"Arial";

    m_pFmtLabel = m_pFontCache->GetFormat(family, m_style.label_font_size > 0 ? m_style.label_font_size : 36.0f);
    m_pFmtValue = m_pFontCache->GetFormat(family, m_style.value_font_size > 0 ? m_style.value_font_size : 54.0f, DWRITE_FONT_WEIGHT_BOLD);
    m_pFmtRange = m_pFontCache->GetFormat(family, m_style.range_font_size > 0 ? m_style.range_font_size : 30.0f);

    return (m_pActiveBrush && m_pInactiveBrush && m_pTextBrush && m_pOutlineBrush);
}

void SegmentBarIndicator::DiscardDeviceResources() {
    if (m_pActiveBrush) { m_pActiveBrush->Release(); m_pActiveBrush = nullptr; }
    if (m_pInactiveBrush) { m_pInactiveBrush->Release(); m_pInactiveBrush = nullptr; }
    for (int i = 0; i < 64; ++i) {
        if (m_pSegBrushes[i]) {
            m_pSegBrushes[i]->Release();
            m_pSegBrushes[i] = nullptr;
        }
    }
    m_numSegBrushes = 0;
    if (m_pTextBrush) { m_pTextBrush->Release(); m_pTextBrush = nullptr; }
    if (m_pDimBrush) { m_pDimBrush->Release(); m_pDimBrush = nullptr; }
    if (m_pOutlineBrush) { m_pOutlineBrush->Release(); m_pOutlineBrush = nullptr; }
    m_pFmtLabel = nullptr;
    m_pFmtValue = nullptr;
    m_pFmtRange = nullptr;
}

void SegmentBarIndicator::Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    if (!pD2D || !m_pActiveBrush || !m_pInactiveBrush) return;

    float raw_val = state.garmin_battery_pct;
    const char* val_str = state.garmin_battery_str;

    float span = m_style.max_val - m_style.min_val;
    if (span <= 0.001f) span = 100.0f;
    float norm_frac = std::max(0.0f, std::min(1.0f, (raw_val - m_style.min_val) / span));

    int num_segs = m_style.segments > 0 ? m_style.segments : 30;
    int active_segs = (int)std::ceil(norm_frac * num_segs);

    float hw = m_width * 0.5f;
    float x1 = (m_style.seg_canvas_x > 0.0f) ? m_style.seg_canvas_x : (m_cx - hw);
    float y1 = (m_style.seg_canvas_y > 0.0f) ? m_style.seg_canvas_y : (m_cy - 10.0f);
    float seg_w_total = (m_style.seg_width > 0.0f) ? m_style.seg_width : m_width;
    float gap = (m_style.gap > 0.0f) ? m_style.gap : 3.0f;
    float total_gap = gap * (num_segs - 1);
    float seg_w = (seg_w_total - total_gap) / (float)num_segs;
    if (seg_w < 2.0f) seg_w = 2.0f;

    float seg_h = (m_style.seg_height > 0.0f) ? m_style.seg_height : 60.0f;
    float radius = (m_style.radius > 0.0f) ? m_style.radius : 4.0f;
    float outline_w = (m_style.outline_width > 0.0f) ? m_style.outline_width : 6.0f;

    // 1. Draw segments
    for (int i = 0; i < num_segs; ++i) {
        float p = (num_segs > 1) ? ((float)i / (float)(num_segs - 1)) : 0.0f;
        float grow_s = m_style.grow_start > 0 ? m_style.grow_start : 0.55f;
        float h_mult = m_style.grow_height ? (grow_s + (1.0f - grow_s) * p) : 1.0f;
        float sh = seg_h * h_mult;
        float sx1 = x1 + i * (seg_w + gap);
        float sx2 = sx1 + seg_w;
        float sy2 = y1 + seg_h;
        float sy1 = sy2 - sh;

        D2D1_ROUNDED_RECT rRect = D2D1::RoundedRect(D2D1::RectF(sx1, sy1, sx2, sy2), radius, radius);

        // Always draw inactive base
        pD2D->FillRoundedRectangle(&rRect, m_pInactiveBrush);

        // If active, draw gradient segment brush on top
        if (i < active_segs && i < m_numSegBrushes && m_pSegBrushes[i]) {
            pD2D->FillRoundedRectangle(&rRect, m_pSegBrushes[i]);
        } else if (i < active_segs) {
            pD2D->FillRoundedRectangle(&rRect, m_pActiveBrush);
        }
    }

    // 2. Value text at top (above segments)
    if (m_pFmtValue && val_str && val_str[0]) {
        std::wstring fullValText;
        wchar_t wVal[64] = { 0 };
        MultiByteToWideChar(CP_UTF8, 0, val_str, -1, wVal, 64);
        fullValText = wVal;
        if (strcmp(val_str, "--") != 0 && m_style.unit[0] && fullValText.find(m_style.unit) == std::wstring::npos) {
            fullValText += L" ";
            fullValText += m_style.unit;
        }

        float val_x = (m_style.value_canvas_x > 0.0f) ? m_style.value_canvas_x : x1;
        float val_y = (m_style.value_canvas_y > 0.0f) ? m_style.value_canvas_y : (y1 - 65.0f);
        D2D1_RECT_F valRect = D2D1::RectF(val_x, val_y, val_x + seg_w_total, val_y + 60.0f);
        FontCache::DrawTextOutlined(pD2D, fullValText.c_str(), m_pFmtValue, valRect, m_pTextBrush, m_pOutlineBrush, outline_w, DWRITE_TEXT_ALIGNMENT_LEADING);
    }

    // 3. Label text and range labels (0 / 100) below segments
    float ly = (m_style.label_canvas_y > 0.0f) ? m_style.label_canvas_y : (y1 + seg_h + 6.0f);
    if (m_pFmtLabel) {
        // Center label in uppercase
        std::wstring upperLabel = m_style.label;
        for (auto& c : upperLabel) c = towupper(c);

        float lx = (m_style.label_canvas_x > 0.0f) ? m_style.label_canvas_x : (x1 + seg_w_total * 0.5f);
        D2D1_RECT_F labelRect = D2D1::RectF(lx - 250.0f, ly, lx + 250.0f, ly + 40.0f);
        FontCache::DrawTextOutlined(pD2D, upperLabel.c_str(), m_pFmtLabel, labelRect, m_pTextBrush, m_pOutlineBrush, outline_w * 0.8f, DWRITE_TEXT_ALIGNMENT_CENTER);

        // "0" at left
        D2D1_RECT_F minRect = D2D1::RectF(x1, ly, x1 + 60.0f, ly + 40.0f);
        FontCache::DrawTextOutlined(pD2D, L"0", m_pFmtLabel, minRect, m_pDimBrush, m_pOutlineBrush, outline_w * 0.8f, DWRITE_TEXT_ALIGNMENT_LEADING);

        // "100" at right
        D2D1_RECT_F maxRect = D2D1::RectF(x1 + seg_w_total - 80.0f, ly, x1 + seg_w_total, ly + 40.0f);
        FontCache::DrawTextOutlined(pD2D, L"100", m_pFmtLabel, maxRect, m_pDimBrush, m_pOutlineBrush, outline_w * 0.8f, DWRITE_TEXT_ALIGNMENT_TRAILING);
    }
}
