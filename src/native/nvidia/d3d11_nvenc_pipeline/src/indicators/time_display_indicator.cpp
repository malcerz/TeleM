#include "time_display_indicator.h"
#include <vector>

TimeDisplayIndicator::TimeDisplayIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache, IconCache* pIconCache)
    : m_key(desc.key)
    , m_style(desc.style.time_display)
    , m_x(desc.x)
    , m_y(desc.y)
    , m_width(desc.width)
    , m_height(desc.height)
    , m_rotation(desc.rotation)
    , m_alpha(desc.alpha)
    , m_z_order(desc.z_order)
    , m_pFontCache(pFontCache)
    , m_pIconCache(pIconCache)
    , m_pBrushDate(nullptr)
    , m_pBrushTime(nullptr)
    , m_pBrushElapsed(nullptr)
    , m_pBrushAvgSpeed(nullptr)
    , m_pBrushOutline(nullptr)
    , m_pFmtDate(nullptr)
    , m_pFmtTime(nullptr)
    , m_pFmtElapsed(nullptr)
    , m_pFmtAvgSpeed(nullptr)
{
}

TimeDisplayIndicator::~TimeDisplayIndicator() {
    DiscardDeviceResources();
}

bool TimeDisplayIndicator::CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) {
    DiscardDeviceResources();

    if (!pD2D || !pDWrite || !m_pFontCache) return false;

    // Brushes
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.date_color ? m_style.date_color : 0xFFD2D2D2), &m_pBrushDate);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.time_color ? m_style.time_color : 0xFFFFFFFF), &m_pBrushTime);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.elapsed_color ? m_style.elapsed_color : 0xFFFFFFFF), &m_pBrushElapsed);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.avg_speed_color ? m_style.avg_speed_color : 0xFFFFFFFF), &m_pBrushAvgSpeed);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.0f, 0.0f, 0.0f, 1.0f), &m_pBrushOutline);

    const wchar_t* family = m_style.font_family[0] ? m_style.font_family : L"Arial";

    m_pFmtDate = m_pFontCache->GetFormat(family, m_style.date_font_size > 0 ? m_style.date_font_size : 46.0f);
    m_pFmtTime = m_pFontCache->GetFormat(family, m_style.time_font_size > 0 ? m_style.time_font_size : 46.0f);
    m_pFmtElapsed = m_pFontCache->GetFormat(family, m_style.elapsed_font_size > 0 ? m_style.elapsed_font_size : 46.0f);
    m_pFmtAvgSpeed = m_pFontCache->GetFormat(family, m_style.avg_speed_font_size > 0 ? m_style.avg_speed_font_size : 34.0f);

    return (m_pBrushDate && m_pBrushTime && m_pBrushElapsed && m_pBrushAvgSpeed && m_pBrushOutline);
}

void TimeDisplayIndicator::DiscardDeviceResources() {
    if (m_pBrushDate) { m_pBrushDate->Release(); m_pBrushDate = nullptr; }
    if (m_pBrushTime) { m_pBrushTime->Release(); m_pBrushTime = nullptr; }
    if (m_pBrushElapsed) { m_pBrushElapsed->Release(); m_pBrushElapsed = nullptr; }
    if (m_pBrushAvgSpeed) { m_pBrushAvgSpeed->Release(); m_pBrushAvgSpeed = nullptr; }
    if (m_pBrushOutline) { m_pBrushOutline->Release(); m_pBrushOutline = nullptr; }
    m_pFmtDate = nullptr;
    m_pFmtTime = nullptr;
    m_pFmtElapsed = nullptr;
    m_pFmtAvgSpeed = nullptr;
}

void TimeDisplayIndicator::Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    if (!pD2D || !m_pBrushOutline) return;

    // Convert strings
    wchar_t wDate[64] = { 0 };
    wchar_t wTime[64] = { 0 };
    wchar_t wElapsed[64] = { 0 };
    wchar_t wAvgSpeed[64] = { 0 };

    if (state.time_display_date[0]) MultiByteToWideChar(CP_UTF8, 0, state.time_display_date, -1, wDate, 64);
    if (state.time_display_time[0]) MultiByteToWideChar(CP_UTF8, 0, state.time_display_time, -1, wTime, 64);
    if (state.time_display_elapsed[0]) MultiByteToWideChar(CP_UTF8, 0, state.time_display_elapsed, -1, wElapsed, 64);
    if (state.time_display_avg_speed[0]) MultiByteToWideChar(CP_UTF8, 0, state.time_display_avg_speed, -1, wAvgSpeed, 64);

    struct LineItem {
        std::wstring        text;
        IDWriteTextFormat*  format;
        ID2D1Brush*         brush;
        float               lh;
    };

    std::vector<LineItem> lines;
    float default_lh = (m_style.line_spacing > 0.0f) ? m_style.line_spacing : 58.0f;

    if (m_style.show_date && wDate[0]) {
        std::wstring t = m_style.date_label[0] ? (std::wstring(m_style.date_label) + L": " + wDate) : wDate;
        lines.push_back({ t, m_pFmtDate, m_pBrushDate, default_lh });
    }
    if (m_style.show_time && wTime[0]) {
        std::wstring t = m_style.time_label[0] ? (std::wstring(m_style.time_label) + L": " + wTime) : wTime;
        lines.push_back({ t, m_pFmtTime, m_pBrushTime, default_lh });
    }
    if (m_style.show_elapsed && wElapsed[0]) {
        std::wstring t = m_style.elapsed_label[0] ? (std::wstring(m_style.elapsed_label) + L": " + wElapsed) : wElapsed;
        lines.push_back({ t, m_pFmtElapsed, m_pBrushElapsed, default_lh });
    }
    if (m_style.show_avg_speed && wAvgSpeed[0]) {
        std::wstring t = m_style.avg_speed_label[0] ? (std::wstring(m_style.avg_speed_label) + L": " + wAvgSpeed) : wAvgSpeed;
        float fs_avg = m_style.avg_speed_font_size > 0 ? m_style.avg_speed_font_size : 34.0f;
        lines.push_back({ t, m_pFmtAvgSpeed, m_pBrushAvgSpeed, fs_avg * 1.35f });
    }

    if (lines.empty()) return;

    // Total text block height
    float total_text_h = 0.0f;
    for (const auto& l : lines) {
        total_text_h += l.lh;
    }

    float start_x = (m_style.canvas_x > 0.0f) ? m_style.canvas_x : m_x;
    float start_y = (m_style.canvas_y > 0.0f) ? m_style.canvas_y : m_y;

    // Icon handling
    float current_x = start_x;
    float icon_dim = m_style.icon_size > 0 ? m_style.icon_size : 51.0f;
    float icon_gap = 10.0f;

    ID2D1Bitmap* pIconBitmap = nullptr;
    if (m_pIconCache && m_style.icon_name[0] && strcmp(m_style.icon_name, "none") != 0) {
        pIconBitmap = m_pIconCache->GetIcon(pD2D, m_style.icon_name);
    }

    if (pIconBitmap) {
        D2D1_SIZE_F bitmapSize = pIconBitmap->GetSize();
        float aspect = bitmapSize.width / (bitmapSize.height > 0.1f ? bitmapSize.height : 1.0f);
        float icon_w = icon_dim * aspect;
        float icon_h = icon_dim;

        // Vertically centered with total rendered lines
        float icon_y = start_y + (total_text_h - icon_h) * 0.5f;
        D2D1_RECT_F iconRect = D2D1::RectF(current_x, icon_y, current_x + icon_w, icon_y + icon_h);
        pD2D->DrawBitmap(pIconBitmap, &iconRect);

        current_x += icon_w + icon_gap;
    }

    // Render each line
    float current_y = start_y;
    float outline_w = m_style.outline_width > 0 ? m_style.outline_width : 6.0f;

    for (const auto& l : lines) {
        D2D1_RECT_F lineRect = D2D1::RectF(current_x, current_y, current_x + 1200.0f, current_y + l.lh);
        FontCache::DrawTextOutlined(
            pD2D,
            l.text,
            l.format,
            lineRect,
            l.brush,
            m_pBrushOutline,
            outline_w,
            DWRITE_TEXT_ALIGNMENT_LEADING
        );
        current_y += l.lh;
    }
}
