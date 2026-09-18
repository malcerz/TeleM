#ifndef CHART_INDICATOR_H
#define CHART_INDICATOR_H

#include "indicator_base.h"
#include "font_cache.h"
#include <vector>

struct ChartCachedText {
    IDWriteTextLayout* layout = nullptr;
    D2D1_POINT_2F origin{};
    ID2D1Brush* text_brush = nullptr;
    ID2D1Brush* outline_brush = nullptr;
    float outline_width = 0.0f;
};

class ChartIndicator : public IndicatorBase {
public:
    ChartIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache);
    virtual ~ChartIndicator();

    virtual bool CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) override;
    virtual void DiscardDeviceResources() override;
    virtual void Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) override;

    void SetSamples(const float* samples, uint32_t count);

    virtual const std::string& GetKey() const override { return m_key; }
    virtual TelemIndicatorType GetType() const override { return TELEM_IND_CHART; }
    virtual int32_t GetZOrder() const override { return m_z_order; }

private:
    void BuildStaticTextCache(float plot_x1, float plot_x2, float plot_y1,
                              float plot_y2, float header_h, float outline_w);
    void DrawCachedText(ID2D1DeviceContext* pD2D, const ChartCachedText& item) const;
    void ClearStaticCache();

    std::string             m_key;
    TelemChartStyle         m_style;
    float                   m_cx;
    float                   m_cy;
    float                   m_width;
    float                   m_height;
    float                   m_rotation;
    float                   m_alpha;
    int32_t                 m_z_order;

    std::vector<float>      m_samples;

    FontCache*              m_pFontCache;
    ID2D1Factory*           m_pD2DFactory;
    IDWriteFactory*         m_pDWriteFactory;
    ID2D1PathGeometry*      m_pGridGeometry;
    std::vector<ChartCachedText> m_static_text_cache;
    bool                    m_static_cache_ready;

    ID2D1SolidColorBrush*   m_pLineBrush;
    ID2D1SolidColorBrush*   m_pFillBrush;
    ID2D1SolidColorBrush*   m_pGridBrush;
    ID2D1SolidColorBrush*   m_pTextBrush;
    ID2D1SolidColorBrush*   m_pDimTextBrush;
    ID2D1SolidColorBrush*   m_pCursorBrush;
    ID2D1SolidColorBrush*   m_pOutlineBrush;

    // Diagnostic-only resolved brush alpha.  It is populated when the
    // cadence trace is enabled and is otherwise just the normal rendering
    // value used by the fill brush.
    float                   m_fill_alpha_resolved = 0.0f;

    IDWriteTextFormat*      m_pFmtHeader;
    IDWriteTextFormat*      m_pFmtAxis;
    IDWriteTextFormat*      m_pFmtValue;
};

#endif // CHART_INDICATOR_H
