#include "chart_indicator.h"
#include "../hud_profile.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace {

bool CadenceTraceFrame(uint32_t frame) {
    return frame == 0 || frame == 1 || frame == 2 || frame == 10 ||
           frame == 50 || frame == 100 || frame == 150 || frame == 250 ||
           frame == 299;
}

std::string CadenceTracePath(const char* name) {
    const char* dir = std::getenv("TELEM_CADENCE_TRACE_DIR");
    if (!dir || !*dir) return {};
    std::string path(dir);
    if (!path.empty() && path.back() != '\\' && path.back() != '/') path += '\\';
    path += name;
    return path;
}

void AppendCadenceCsv(const char* name, const char* header, const char* row) {
    const std::string path = CadenceTracePath(name);
    if (path.empty()) return;
    FILE* f = nullptr;
    if (fopen_s(&f, path.c_str(), "a+") != 0 || !f) return;
    fseek(f, 0, SEEK_END);
    const long end = ftell(f);
    if (end == 0 && header) std::fprintf(f, "%s\n", header);
    if (row) std::fprintf(f, "%s\n", row);
    std::fclose(f);
}

void AppendCadenceText(const char* name, const char* line) {
    const std::string path = CadenceTracePath(name);
    if (path.empty()) return;
    FILE* f = nullptr;
    if (fopen_s(&f, path.c_str(), "a") != 0 || !f) return;
    std::fprintf(f, "%s\n", line);
    std::fclose(f);
}

void TraceAlpha(const char* stage, const char* field, const char* type,
                float raw, float normalized, float expected) {
    char row[512] = {};
    std::snprintf(row, sizeof(row), "%s,%s,%s,%.9g,%.9g,%.9g",
                  stage, field, type, raw, normalized, expected);
    AppendCadenceCsv(
        "fill_alpha_trace.csv",
        "stage,field_name,type,raw_value,normalized_value,expected_value",
        row);
}

} // namespace

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
    , m_pDWriteFactory(nullptr)
    , m_pGridGeometry(nullptr)
    , m_static_cache_ready(false)
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

void ChartIndicator::ClearStaticCache() {
    for (auto& item : m_static_text_cache) {
        if (item.layout) item.layout->Release();
        item.layout = nullptr;
    }
    m_static_text_cache.clear();
    if (m_pGridGeometry) {
        m_pGridGeometry->Release();
        m_pGridGeometry = nullptr;
    }
    m_static_cache_ready = false;
}

void ChartIndicator::BuildStaticTextCache(float plot_x1, float plot_x2, float plot_y1,
                                          float plot_y2, float header_h, float outline_w) {
    if (!m_pDWriteFactory || !m_pD2DFactory || !m_pFmtAxis) return;

    ClearStaticCache();

    if (m_style.show_grid) {
        int lines = m_style.label_count > 0 ? m_style.label_count : 4;
        if (SUCCEEDED(m_pD2DFactory->CreatePathGeometry(&m_pGridGeometry)) && m_pGridGeometry) {
            TelemHudProfile::Count("resource", "CreatePathGeometry");
            ID2D1GeometrySink* sink = nullptr;
            if (SUCCEEDED(m_pGridGeometry->Open(&sink)) && sink) {
                for (int i = 0; i <= lines; ++i) {
                    float frac = (float)i / (float)lines;
                    float gy = plot_y2 - frac * (plot_y2 - plot_y1);
                    sink->BeginFigure(D2D1::Point2F(plot_x1, gy), D2D1_FIGURE_BEGIN_HOLLOW);
                    sink->AddLine(D2D1::Point2F(plot_x2, gy));
                    sink->EndFigure(D2D1_FIGURE_END_OPEN);

                    if (m_pFmtAxis) {
                        float y_val = m_style.min_val + frac * (m_style.max_val - m_style.min_val);
                        wchar_t axis[32] = {};
                        swprintf_s(axis, L"%.0f", (float)std::round(y_val));
                        D2D1_RECT_F rect = D2D1::RectF(plot_x1 - 120.0f, gy - 16.0f,
                                                        plot_x1 - 10.0f, gy + 16.0f);
                        IDWriteTextLayout* layout = nullptr;
                        if (SUCCEEDED(m_pDWriteFactory->CreateTextLayout(
                                axis, (UINT32)wcslen(axis), m_pFmtAxis,
                                rect.right - rect.left, rect.bottom - rect.top, &layout)) && layout) {
                            layout->SetTextAlignment(DWRITE_TEXT_ALIGNMENT_TRAILING);
                            m_static_text_cache.push_back({layout,
                                D2D1::Point2F(rect.left, rect.top), m_pDimTextBrush,
                                m_pOutlineBrush, outline_w * 0.7f});
                            TelemHudProfile::Count("resource", "CreateTextLayout");
                        }
                    }
                }
                sink->Close();
                sink->Release();
            }
        }
    }

    if (m_pFmtAxis) {
        const float duration_s = m_style.time_duration_s > 0.0f ? m_style.time_duration_s : 60.0f;
        const float tick_step = duration_s >= 3600.0f ? 1800.0f : (duration_s >= 600.0f ? 300.0f : 60.0f);
        const int tick_count = (int)std::floor(duration_s / tick_step + 0.0001f);
        const int max_ticks = std::min(6, std::max(2, tick_count + 1));
        for (int i = 0; i < max_ticks; ++i) {
            const int tick_index = std::min(i, max_ticks - 1);
            const float tick_s = std::min(duration_s, tick_index * tick_step);
            const float frac_x = duration_s > 0.0f ? tick_s / duration_s : (float)i / 4.0f;
            const float tx = plot_x1 + frac_x * (plot_x2 - plot_x1);
            D2D1_RECT_F rect = D2D1::RectF(tx - 40.0f, plot_y2 + 6.0f,
                                            tx + 40.0f, plot_y2 + 32.0f);
            wchar_t tick[32] = {};
            const int total_seconds = (int)std::lround(tick_s);
            if (duration_s >= 3600.0f) swprintf_s(tick, L"%d:%02d", total_seconds / 3600, (total_seconds / 60) % 60);
            else swprintf_s(tick, L"%02d:%02d", total_seconds / 60, total_seconds % 60);
            IDWriteTextLayout* layout = nullptr;
            if (SUCCEEDED(m_pDWriteFactory->CreateTextLayout(
                    tick, (UINT32)wcslen(tick), m_pFmtAxis,
                    rect.right - rect.left, rect.bottom - rect.top, &layout)) && layout) {
                layout->SetTextAlignment(DWRITE_TEXT_ALIGNMENT_CENTER);
                m_static_text_cache.push_back({layout,
                    D2D1::Point2F(rect.left, rect.top), m_pDimTextBrush,
                    m_pOutlineBrush, outline_w * 0.7f});
                TelemHudProfile::Count("resource", "CreateTextLayout");
            }
        }
    }

    const float hdr_x = (m_style.header_canvas_x > 0.0f) ? m_style.header_canvas_x : plot_x1;
    const float hdr_y = (m_style.header_canvas_y > 0.0f) ? m_style.header_canvas_y : (plot_y1 - 65.0f);
    if (m_style.label[0] && m_pFmtHeader) {
        const D2D1_RECT_F rect = D2D1::RectF(hdr_x, hdr_y, hdr_x + 500.0f, hdr_y + header_h);
        IDWriteTextLayout* layout = nullptr;
        if (SUCCEEDED(m_pDWriteFactory->CreateTextLayout(
                m_style.label, (UINT32)wcslen(m_style.label), m_pFmtHeader,
                rect.right - rect.left, rect.bottom - rect.top, &layout)) && layout) {
            layout->SetTextAlignment(DWRITE_TEXT_ALIGNMENT_LEADING);
            m_static_text_cache.push_back({layout,
                D2D1::Point2F(rect.left, rect.top), m_pTextBrush,
                m_pOutlineBrush, outline_w});
            TelemHudProfile::Count("resource", "CreateTextLayout");
        }
    }
    m_static_cache_ready = m_pGridGeometry != nullptr || !m_static_text_cache.empty();
}

void ChartIndicator::DrawCachedText(ID2D1DeviceContext* pD2D,
                                    const ChartCachedText& item) const {
    if (!pD2D || !item.layout) return;
    const double text_t0 = TelemHudProfile::NowSeconds();
    if (item.outline_width > 0.5f && item.outline_brush) {
        const float d = item.outline_width * 0.85f;
        const float dd = d * 0.7071f;
        const float offsets[8][2] = {{-d,0.0f},{d,0.0f},{0.0f,-d},{0.0f,d},
                                     {-dd,-dd},{dd,-dd},{-dd,dd},{dd,dd}};
        for (const auto& offset : offsets) {
            pD2D->DrawTextLayout(D2D1::Point2F(item.origin.x + offset[0], item.origin.y + offset[1]),
                                 item.layout, item.outline_brush);
            TelemHudProfile::Count("d2d", "DrawTextLayout");
        }
    }
    if (item.text_brush) {
        pD2D->DrawTextLayout(item.origin, item.layout, item.text_brush);
        TelemHudProfile::Count("d2d", "DrawTextLayout");
    }
    TelemHudProfile::Record("text", "static", "DrawTextLayout",
                            (TelemHudProfile::NowSeconds() - text_t0) * 1000.0);
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
    m_pDWriteFactory = pDWrite;
    if (m_pDWriteFactory) m_pDWriteFactory->AddRef();

    // Brushes
    uint32_t lineCol = m_style.line_color ? m_style.line_color : 0xFFFF0000;
    pD2D->CreateSolidColorBrush(ColorFromHex(lineCol), &m_pLineBrush);
    TelemHudProfile::Count("resource", "CreateSolidColorBrush");

    uint32_t fillCol = m_style.fill_color ? m_style.fill_color : lineCol;
    D2D1_COLOR_F fc = ColorFromHex(fillCol);
    // The Python ABI historically supplied both byte-style alpha (0..255)
    // and normalized alpha (0..1).  Accept either representation; dividing
    // an already-normalized value by 255 made the cadence area effectively
    // invisible in the Native final MP4.
    const float fill_alpha = (m_style.fill_alpha > 1.0f)
        ? (m_style.fill_alpha / 255.0f)
        : m_style.fill_alpha;
    m_fill_alpha_resolved = fill_alpha;
    fc.a = fill_alpha > 0.0f ? fill_alpha : 0.40f;
    pD2D->CreateSolidColorBrush(fc, &m_pFillBrush);
    TelemHudProfile::Count("resource", "CreateSolidColorBrush");

    if (m_key == "fit_cadence_text") {
        TraceAlpha("C++ TelemChartStyle value", "fill_alpha", "float",
                   m_style.fill_alpha, fill_alpha, 200.0f / 255.0f);
        TraceAlpha("ChartIndicator member value", "fill_alpha", "float",
                   m_style.fill_alpha, m_fill_alpha_resolved, 200.0f / 255.0f);
        char brush_line[512] = {};
        std::snprintf(brush_line, sizeof(brush_line),
                      "fill_color=0x%08X\nfill_alpha_raw=%.9g\nfill_alpha_resolved=%.9g\nfill_brush_alpha=%.9g\nfill_enabled=%d",
                      fillCol, m_style.fill_alpha, fill_alpha, fc.a,
                      m_pFillBrush ? 1 : 0);
        AppendCadenceText("cadence_brush_trace.txt", brush_line);
    }

    uint32_t gridCol = m_style.grid_color ? m_style.grid_color : 0xFF444444;
    pD2D->CreateSolidColorBrush(ColorFromHex(gridCol), &m_pGridBrush);
    TelemHudProfile::Count("resource", "CreateSolidColorBrush");
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
    ClearStaticCache();
    if (m_pDWriteFactory) { m_pDWriteFactory->Release(); m_pDWriteFactory = nullptr; }
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

    const bool profile = TelemHudProfile::Enabled();
    const char* chart_name = m_key == "fit_cadence_text" ? "cadence" :
                             (m_key == "fit_heart_rate_text" ? "heart_rate" : m_key.c_str());
    auto mark = [&](const char* stage, double started) {
        if (profile) TelemHudProfile::Record("chart", chart_name, stage,
                                             (TelemHudProfile::NowSeconds() - started) * 1000.0);
    };
    double stage_t = TelemHudProfile::NowSeconds();

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

    if (!m_static_cache_ready) {
        BuildStaticTextCache(plot_x1, plot_x2, plot_y1, plot_y2, header_h, outline_w);
    }

    mark("sample_prep", stage_t);
    stage_t = TelemHudProfile::NowSeconds();

    // 1. Static: Grid lines & Axis labels
    if (!m_static_cache_ready && m_style.show_grid) {
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
    mark("grid", stage_t);
    stage_t = TelemHudProfile::NowSeconds();

    // Time axis labels along bottom.  Legacy uses the active chart history
    // duration (activity/video/window); keep one minute only for old callers
    // that do not provide the duration through the ABI.
    if (!m_static_cache_ready && m_pFmtAxis) {
        const float duration_s = m_style.time_duration_s > 0.0f ? m_style.time_duration_s : 60.0f;
        const float tick_step = duration_s >= 3600.0f ? 1800.0f : (duration_s >= 600.0f ? 300.0f : 60.0f);
        const int tick_count = (int)std::floor(duration_s / tick_step + 0.0001f);
        const int max_ticks = std::min(6, std::max(2, tick_count + 1));
        for (int i = 0; i < max_ticks; ++i) {
            const int tick_index = std::min(i, max_ticks - 1);
            const float tick_s = std::min(duration_s, tick_index * tick_step);
            float frac_x = duration_s > 0.0f ? tick_s / duration_s : (float)i / 4.0f;
            float tx = plot_x1 + frac_x * (plot_x2 - plot_x1);
            D2D1_RECT_F tRect = D2D1::RectF(tx - 40.0f, plot_y2 + 6.0f, tx + 40.0f, plot_y2 + 32.0f);
            wchar_t time_tick[32] = { 0 };
            const int total_seconds = (int)std::lround(tick_s);
            if (duration_s >= 3600.0f) {
                swprintf_s(time_tick, L"%d:%02d", total_seconds / 3600, (total_seconds / 60) % 60);
            } else {
                swprintf_s(time_tick, L"%02d:%02d", total_seconds / 60, total_seconds % 60);
            }
            FontCache::DrawTextOutlined(pD2D, time_tick, m_pFmtAxis, tRect, m_pDimTextBrush, m_pOutlineBrush, outline_w * 0.7f, DWRITE_TEXT_ALIGNMENT_CENTER);
        }
    }
    if (m_static_cache_ready) {
        if (m_pGridGeometry && m_pGridBrush) {
            pD2D->DrawGeometry(m_pGridGeometry, m_pGridBrush, 1.5f);
        }
        for (const auto& item : m_static_text_cache) DrawCachedText(pD2D, item);
    }
    mark("labels_axis", stage_t);
    stage_t = TelemHudProfile::NowSeconds();

    // 2. Static/Header: Title & Live Value Text
    float hdr_x = (m_style.header_canvas_x > 0.0f) ? m_style.header_canvas_x : plot_x1;
    float hdr_y = (m_style.header_canvas_y > 0.0f) ? m_style.header_canvas_y : (plot_y1 - 65.0f);

    if (!m_static_cache_ready && m_style.label[0] && m_pFmtHeader) {
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
    mark("labels_header_value", stage_t);
    stage_t = TelemHudProfile::NowSeconds();

    // 3. Static/Dynamic: Full History curve & Cursor
    if (m_samples.size() >= 2 && m_pD2DFactory) {
        const double path_started = TelemHudProfile::NowSeconds();
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

                mark("geometry_creation", path_started);
                stage_t = TelemHudProfile::NowSeconds();

                // Draw filled polygon and stroke
                if (m_key == "fit_cadence_text") {
                    TraceAlpha("value immediately before Fill call", "fill_alpha", "float",
                               m_style.fill_alpha, m_fill_alpha_resolved,
                               200.0f / 255.0f);
                }
                pD2D->FillGeometry(pPath, m_pFillBrush);
                mark("fill_geometry", stage_t);
                stage_t = TelemHudProfile::NowSeconds();
                // Legacy cadence uses line_width=1; HR keeps its configured
                // two-pixel stroke.  The ABI predates an explicit chart line
                // width field, so bind this narrow NVIDIA-only compatibility
                // choice to the canonical indicator id.
                const float line_width = (m_key == "fit_cadence_text") ? 1.0f : 2.0f;
                pD2D->DrawGeometry(pPath, m_pLineBrush, line_width);
                mark("outline_geometry", stage_t);
                stage_t = TelemHudProfile::NowSeconds();

                if (m_key == "fit_cadence_text" && CadenceTraceFrame(state.frame_index)) {
                    char row[768] = {};
                    const uint32_t point_count = static_cast<uint32_t>(m_samples.size());
                    const uint32_t polygon_point_count = point_count + 2;
                    std::snprintf(
                        row, sizeof(row),
                        "%u,%s,%u,%u,%u,%d,%.9g,%.9g,%d,%d",
                        state.frame_index, m_key.c_str(), point_count, point_count,
                        polygon_point_count, m_pFillBrush ? 1 : 0,
                        m_fill_alpha_resolved, m_fill_alpha_resolved, 1, 1);
                    AppendCadenceCsv(
                        "cadence_draw_trace.csv",
                        "frame,indicator_id,sample_count,point_count,polygon_point_count,fill_enabled,fill_alpha,fill_brush_alpha,FillGeometry_call_count,DrawGeometry_call_count",
                        row);

                    char poly_row[768] = {};
                    std::snprintf(
                        poly_row, sizeof(poly_row),
                        "%u,%u,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%d",
                        state.frame_index, polygon_point_count,
                        plot_x1, first_y, last_x, last_y,
                        plot_x1, plot_x2, plot_y2, 1);
                    AppendCadenceCsv(
                        "cadence_fill_polygon.csv",
                        "frame,polygon_point_count,first_point_x,first_point_y,last_point_x,last_point_y,baseline_left_x,baseline_right_x,baseline_y,closed",
                        poly_row);
                }

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
        mark("cursor", stage_t);
    }
}
