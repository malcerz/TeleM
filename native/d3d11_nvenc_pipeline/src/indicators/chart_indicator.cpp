#include "chart_indicator.h"
#include <algorithm>
#include <cmath>

ChartIndicator::ChartIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache)
    : m_key(desc.key)
    , m_style(desc.style.chart)
    , m_cx(desc.x)
    , m_cy(desc.y)
    , m_width(desc.width)
    , m_height(desc.height)
    , m_rotation(desc.rotation)
    , m_alpha(desc.alpha)
    , m_z_order(desc.z_order)
    , m_pFontCache(pFontCache)
    , m_pD2DFactory(nullptr)
    , m_pLineBrush(nullptr)
    , m_pFillBrush(nullptr)
    , m_pGridBrush(nullptr)
    , m_pTextBrush(nullptr)
    , m_pDimTextBrush(nullptr)
    , m_pCursorBrush(nullptr)
    , m_pOutlineBrush(nullptr)
    , m_pFmtHeader(nullptr)
    , m_pFmtAxis(nullptr)
    , m_pFmtValue(nullptr)
{
}

ChartIndicator::~ChartIndicator() {
    DiscardDeviceResources();
}

void ChartIndicator::SetSamples(const float* samples, uint32_t count) {
    if (samples && count > 0) {
        m_samples.assign(samples, samples + count);
    } else {
        m_samples.clear();
    }
}

bool ChartIndicator::CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) {
    DiscardDeviceResources();

    if (!pD2D || !pDWrite || !m_pFontCache) return false;

    pD2D->GetFactory(&m_pD2DFactory);

    // Brushes
    uint32_t lineCol = m_style.line_color ? m_style.line_color : 0xFFFF0000;
    pD2D->CreateSolidColorBrush(ColorFromHex(lineCol), &m_pLineBrush);

    uint32_t fillCol = m_style.fill_color ? m_style.fill_color : lineCol;
    D2D1_COLOR_F fc = ColorFromHex(fillCol);
    fc.a = m_style.fill_alpha > 0 ? (m_style.fill_alpha / 255.0f) : 0.40f;
    pD2D->CreateSolidColorBrush(fc, &m_pFillBrush);

    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.35f, 0.35f, 0.35f, 0.45f), &m_pGridBrush);
    pD2D->CreateSolidColorBrush(ColorFromHex(m_style.text_color ? m_style.text_color : 0xFFFFFFFF), &m_pTextBrush);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.85f, 0.85f, 0.85f, 0.80f), &m_pDimTextBrush);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(1.0f, 1.0f, 1.0f, 0.90f), &m_pCursorBrush);
    pD2D->CreateSolidColorBrush(D2D1::ColorF(0.0f, 0.0f, 0.0f, 1.0f), &m_pOutlineBrush);

    const wchar_t* family = m_style.font_family[0] ? m_style.font_family : L"Arial";

    m_pFmtHeader = m_pFontCache->GetFormat(family, m_style.header_font_size > 0 ? m_style.header_font_size : 46.0f, DWRITE_FONT_WEIGHT_SEMI_BOLD);
    m_pFmtAxis = m_pFontCache->GetFormat(family, m_style.axis_font_size > 0 ? m_style.axis_font_size : 32.0f);
    m_pFmtValue = m_pFontCache->GetFormat(family, m_style.value_font_size > 0 ? m_style.value_font_size : 50.0f, DWRITE_FONT_WEIGHT_BOLD);

    return (m_pLineBrush && m_pFillBrush && m_pGridBrush && m_pTextBrush && m_pOutlineBrush);
}

void ChartIndicator::DiscardDeviceResources() {
    if (m_pD2DFactory) { m_pD2DFactory->Release(); m_pD2DFactory = nullptr; }
    if (m_pLineBrush) { m_pLineBrush->Release(); m_pLineBrush = nullptr; }
    if (m_pFillBrush) { m_pFillBrush->Release(); m_pFillBrush = nullptr; }
    if (m_pGridBrush) { m_pGridBrush->Release(); m_pGridBrush = nullptr; }
    if (m_pTextBrush) { m_pTextBrush->Release(); m_pTextBrush = nullptr; }
    if (m_pDimTextBrush) { m_pDimTextBrush->Release(); m_pDimTextBrush = nullptr; }
    if (m_pCursorBrush) { m_pCursorBrush->Release(); m_pCursorBrush = nullptr; }
    if (m_pOutlineBrush) { m_pOutlineBrush->Release(); m_pOutlineBrush = nullptr; }
    m_pFmtHeader = nullptr;
    m_pFmtAxis = nullptr;
    m_pFmtValue = nullptr;
}

void ChartIndicator::Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    if (!pD2D || !m_pLineBrush || !m_pFillBrush) return;

    float hw = m_width * 0.5f;
    float hh = m_height * 0.5f;

    float x1 = m_cx - hw;
    float x2 = m_cx + hw;
    float y1 = m_cy - hh;

    float header_h = 55.0f;
    float plot_x1 = (m_style.plot_canvas_x1 > 0.0f) ? m_style.plot_canvas_x1 : (x1 + 75.0f);
    float plot_x2 = (m_style.plot_canvas_x2 > 0.0f) ? m_style.plot_canvas_x2 : (x2 - 25.0f);
    float plot_y1 = (m_style.plot_canvas_y1 > 0.0f) ? m_style.plot_canvas_y1 : (y1 + header_h);
    float plot_y2 = (m_style.plot_canvas_y2 > 0.0f) ? m_style.plot_canvas_y2 : (plot_y1 + 350.0f);

    float outline_w = m_style.outline_width > 0 ? m_style.outline_width : 6.0f;

    // 1. Static: Grid lines & Axis labels
    if (m_style.show_grid) {
        int lines = m_style.label_count > 0 ? m_style.label_count : 4;
        for (int i = 0; i <= lines; ++i) {
            float frac = (float)i / (float)lines;
            float gy = plot_y2 - frac * (plot_y2 - plot_y1);
            pD2D->DrawLine(D2D1::Point2F(plot_x1, gy), D2D1::Point2F(plot_x2, gy), m_pGridBrush, 1.5f);

            if (m_pFmtAxis) {
                float y_val = m_style.min_val + frac * (m_style.max_val - m_style.min_val);
                wchar_t wAxis[32];
                swprintf_s(wAxis, L"%.0f", (float)std::round(y_val));
                D2D1_RECT_F axisRect = D2D1::RectF(plot_x1 - 120.0f, gy - 16.0f, plot_x1 - 10.0f, gy + 16.0f);
                FontCache::DrawTextOutlined(pD2D, wAxis, m_pFmtAxis, axisRect, m_pDimTextBrush, m_pOutlineBrush, outline_w * 0.7f, DWRITE_TEXT_ALIGNMENT_TRAILING);
            }
        }
    }

    // Time axis labels along bottom (5 ticks)
    if (m_pFmtAxis) {
        const wchar_t* time_ticks[5] = { L"0:00", L"0:15", L"0:30", L"0:45", L"1:00" };
        for (int i = 0; i < 5; ++i) {
            float frac_x = (float)i / 4.0f;
            float tx = plot_x1 + frac_x * (plot_x2 - plot_x1);
            D2D1_RECT_F tRect = D2D1::RectF(tx - 40.0f, plot_y2 + 6.0f, tx + 40.0f, plot_y2 + 32.0f);
            FontCache::DrawTextOutlined(pD2D, time_ticks[i], m_pFmtAxis, tRect, m_pDimTextBrush, m_pOutlineBrush, outline_w * 0.7f, DWRITE_TEXT_ALIGNMENT_CENTER);
        }
    }

    // 2. Static/Header: Title & Live Value Text
    float hdr_x = (m_style.header_canvas_x > 0.0f) ? m_style.header_canvas_x : plot_x1;
    float hdr_y = (m_style.header_canvas_y > 0.0f) ? m_style.header_canvas_y : (plot_y1 - 65.0f);

    if (m_style.label[0] && m_pFmtHeader) {
        D2D1_RECT_F titleRect = D2D1::RectF(hdr_x, hdr_y, hdr_x + 500.0f, hdr_y + header_h);
        FontCache::DrawTextOutlined(pD2D, m_style.label, m_pFmtHeader, titleRect, m_pTextBrush, m_pOutlineBrush, outline_w, DWRITE_TEXT_ALIGNMENT_LEADING);
    }

    const char* val_str = "";
    if (m_key == "fit_heart_rate_text" || m_style.telemetry_field == TELEM_FIELD_HEART_RATE) {
        val_str = state.hr_str;
    } else if (m_key == "fit_cadence_text" || m_style.telemetry_field == TELEM_FIELD_CADENCE) {
        val_str = state.cad_str;
    }

    float val_x = (m_style.value_canvas_x > 0.0f) ? m_style.value_canvas_x : plot_x2;
    float val_y = (m_style.value_canvas_y > 0.0f) ? m_style.value_canvas_y : hdr_y;

    if (m_pFmtValue) {
        std::wstring fullValText;
        if (val_str && val_str[0]) {
            wchar_t wVal[64] = { 0 };
            MultiByteToWideChar(CP_UTF8, 0, val_str, -1, wVal, 64);
            fullValText = wVal;
        } else {
            fullValText = L"--";
        }
        if (m_style.unit[0]) {
            fullValText += L" ";
            fullValText += m_style.unit;
        }

        D2D1_RECT_F valRect = D2D1::RectF(val_x - 350.0f, val_y, val_x, val_y + header_h);
        FontCache::DrawTextOutlined(pD2D, fullValText.c_str(), m_pFmtValue, valRect, m_pTextBrush, m_pOutlineBrush, outline_w, DWRITE_TEXT_ALIGNMENT_TRAILING);
    }

    // 3. Static/Dynamic: Full History curve & Cursor
    if (m_samples.size() >= 2 && m_pD2DFactory) {
        ID2D1PathGeometry* pPath = nullptr;
        HRESULT hr = m_pD2DFactory->CreatePathGeometry(&pPath);
        if (SUCCEEDED(hr) && pPath) {
            ID2D1GeometrySink* pSink = nullptr;
            hr = pPath->Open(&pSink);
            if (SUCCEEDED(hr) && pSink) {
                float span_y = m_style.max_val - m_style.min_val;
                if (span_y <= 0.001f) span_y = 1.0f;

                float first_val = m_samples[0];
                float first_frac_y = std::max(0.0f, std::min(1.0f, (first_val - m_style.min_val) / span_y));
                float first_y = plot_y2 - first_frac_y * (plot_y2 - plot_y1);

                pSink->BeginFigure(D2D1::Point2F(plot_x1, plot_y2), D2D1_FIGURE_BEGIN_FILLED);
                pSink->AddLine(D2D1::Point2F(plot_x1, first_y));

                float last_x = plot_x1;
                float last_y = first_y;

                for (size_t s = 1; s < m_samples.size(); ++s) {
                    float frac_x = (float)s / (float)(m_samples.size() - 1);
                    float sx = plot_x1 + frac_x * (plot_x2 - plot_x1);

                    float val = m_samples[s];
                    float frac_y = std::max(0.0f, std::min(1.0f, (val - m_style.min_val) / span_y));
                    float sy = plot_y2 - frac_y * (plot_y2 - plot_y1);

                    pSink->AddLine(D2D1::Point2F(sx, sy));
                    last_x = sx;
                    last_y = sy;
                }

                pSink->AddLine(D2D1::Point2F(last_x, plot_y2));
                pSink->EndFigure(D2D1_FIGURE_END_CLOSED);
                pSink->Close();

                // Draw filled polygon and stroke
                pD2D->FillGeometry(pPath, m_pFillBrush);
                pD2D->DrawGeometry(pPath, m_pLineBrush, 2.5f);

                pSink->Release();
            }
            pPath->Release();
        }

        // Dynamic Cursor vertical line & dot
        float progress = std::max(0.0f, std::min(1.0f, state.activity_progress));
        float cur_x = plot_x1 + progress * (plot_x2 - plot_x1);
        size_t s_idx = (size_t)std::round(progress * (m_samples.size() - 1));
        if (s_idx >= m_samples.size()) s_idx = m_samples.size() - 1;

        float span_y = m_style.max_val - m_style.min_val;
        if (span_y <= 0.001f) span_y = 1.0f;
        float cur_frac_y = std::max(0.0f, std::min(1.0f, (m_samples[s_idx] - m_style.min_val) / span_y));
        float cur_y = plot_y2 - cur_frac_y * (plot_y2 - plot_y1);

        if (!m_pCursorBrush) {
            pD2D->CreateSolidColorBrush(D2D1::ColorF(1.0f, 1.0f, 1.0f, 0.85f), &m_pCursorBrush);
        }

        if (m_pCursorBrush) {
            pD2D->DrawLine(D2D1::Point2F(cur_x, plot_y1), D2D1::Point2F(cur_x, plot_y2), m_pCursorBrush, 2.0f);

            D2D1_ELLIPSE dot = D2D1::Ellipse(D2D1::Point2F(cur_x, cur_y), 5.0f, 5.0f);
            pD2D->FillEllipse(&dot, m_pCursorBrush);
            pD2D->DrawEllipse(&dot, m_pLineBrush, 1.5f);
        }
    }
}
