#ifndef CHART_INDICATOR_H
#define CHART_INDICATOR_H

#include "indicator_base.h"
#include "font_cache.h"
#include <vector>

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

    ID2D1SolidColorBrush*   m_pLineBrush;
    ID2D1SolidColorBrush*   m_pFillBrush;
    ID2D1SolidColorBrush*   m_pGridBrush;
    ID2D1SolidColorBrush*   m_pTextBrush;
    ID2D1SolidColorBrush*   m_pDimTextBrush;
    ID2D1SolidColorBrush*   m_pCursorBrush;
    ID2D1SolidColorBrush*   m_pOutlineBrush;

    IDWriteTextFormat*      m_pFmtHeader;
    IDWriteTextFormat*      m_pFmtAxis;
    IDWriteTextFormat*      m_pFmtValue;
};

#endif // CHART_INDICATOR_H
