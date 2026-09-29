#ifndef BAR_INDICATOR_H
#define BAR_INDICATOR_H

#include "indicator_base.h"
#include "font_cache.h"
#include <vector>

class BarIndicator : public IndicatorBase {
public:
    BarIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache);
    virtual ~BarIndicator();

    virtual bool CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) override;
    virtual void DiscardDeviceResources() override;
    virtual void Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) override;

    virtual const std::string& GetKey() const override { return m_key; }
    virtual TelemIndicatorType GetType() const override { return m_type; }
    virtual int32_t GetZOrder() const override { return m_z_order; }

private:
    void RenderHorizontal(ID2D1DeviceContext* pD2D, const TelemFrameState& state);
    void RenderVertical(ID2D1DeviceContext* pD2D, const TelemFrameState& state);

private:
    std::string             m_key;
    TelemIndicatorType      m_type;
    TelemBarStyle           m_style;
    float                   m_cx;
    float                   m_cy;
    float                   m_width;
    float                   m_height;
    float                   m_rotation;
    float                   m_alpha;
    int32_t                 m_z_order;

    FontCache*              m_pFontCache;

    ID2D1SolidColorBrush*   m_pTrackBrush;
    ID2D1SolidColorBrush*   m_pShadowBrush;
    ID2D1SolidColorBrush*   m_pTickBrush;
    ID2D1SolidColorBrush*   m_pTextBrush;
    ID2D1SolidColorBrush*   m_pDimTextBrush;
    ID2D1SolidColorBrush*   m_pMarkerBrush;
    ID2D1SolidColorBrush*   m_pMarkerBorderBrush;
    ID2D1SolidColorBrush*   m_pOutlineBrush;

    IDWriteTextFormat*      m_pFmtTitle;
    IDWriteTextFormat*      m_pFmtRange;
    IDWriteTextFormat*      m_pFmtValue;
};

#endif // BAR_INDICATOR_H
