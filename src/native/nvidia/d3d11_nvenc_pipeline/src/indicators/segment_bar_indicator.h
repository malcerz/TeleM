#ifndef SEGMENT_BAR_INDICATOR_H
#define SEGMENT_BAR_INDICATOR_H

#include "indicator_base.h"
#include "font_cache.h"

class SegmentBarIndicator : public IndicatorBase {
public:
    SegmentBarIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache);
    virtual ~SegmentBarIndicator();

    virtual bool CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) override;
    virtual void DiscardDeviceResources() override;
    virtual void Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) override;

    virtual const std::string& GetKey() const override { return m_key; }
    virtual TelemIndicatorType GetType() const override { return TELEM_IND_BAR_SEGMENTS; }
    virtual int32_t GetZOrder() const override { return m_z_order; }

private:
    std::string             m_key;
    TelemSegmentBarStyle    m_style;
    float                   m_cx;
    float                   m_cy;
    float                   m_width;
    float                   m_height;
    float                   m_rotation;
    float                   m_alpha;
    int32_t                 m_z_order;

    FontCache*              m_pFontCache;

    ID2D1SolidColorBrush*   m_pActiveBrush;
    ID2D1SolidColorBrush*   m_pInactiveBrush;
    ID2D1SolidColorBrush*   m_pSegBrushes[64];
    int                     m_numSegBrushes;
    ID2D1SolidColorBrush*   m_pTextBrush;
    ID2D1SolidColorBrush*   m_pDimBrush;
    ID2D1SolidColorBrush*   m_pOutlineBrush;

    IDWriteTextFormat*      m_pFmtLabel;
    IDWriteTextFormat*      m_pFmtValue;
    IDWriteTextFormat*      m_pFmtRange;
};

#endif // SEGMENT_BAR_INDICATOR_H
