#ifndef GAUGE_INDICATOR_H
#define GAUGE_INDICATOR_H

#include "indicator_base.h"
#include "font_cache.h"

class GaugeIndicator : public IndicatorBase {
public:
    GaugeIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache);
    virtual ~GaugeIndicator();

    virtual bool CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) override;
    virtual void DiscardDeviceResources() override;
    virtual void Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) override;

    virtual const std::string& GetKey() const override { return m_key; }
    virtual TelemIndicatorType GetType() const override { return TELEM_IND_GAUGE; }
    virtual int32_t GetZOrder() const override { return m_z_order; }

private:
    std::string             m_key;
    TelemGaugeStyle         m_style;
    float                   m_cx;
    float                   m_cy;
    float                   m_width;
    float                   m_height;
    float                   m_rotation;
    float                   m_alpha;
    int32_t                 m_z_order;

    FontCache*              m_pFontCache;

    ID2D1SolidColorBrush*   m_pDialBrush;
    ID2D1SolidColorBrush*   m_pShadowBrush;
    ID2D1SolidColorBrush*   m_pTickBrush;
    ID2D1SolidColorBrush*   m_pTextBrush;
    ID2D1SolidColorBrush*   m_pNeedleBrush;
    ID2D1SolidColorBrush*   m_pOutlineBrush;

    IDWriteTextFormat*      m_pFmtGauge;
    IDWriteTextFormat*      m_pFmtValue;
    IDWriteTextFormat*      m_pFmtUnit;
};

#endif // GAUGE_INDICATOR_H
