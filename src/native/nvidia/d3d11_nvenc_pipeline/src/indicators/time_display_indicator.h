#ifndef TIME_DISPLAY_INDICATOR_H
#define TIME_DISPLAY_INDICATOR_H

#include "indicator_base.h"
#include "font_cache.h"
#include "icon_cache.h"

class TimeDisplayIndicator : public IndicatorBase {
public:
    TimeDisplayIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache, IconCache* pIconCache);
    virtual ~TimeDisplayIndicator();

    virtual bool CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) override;
    virtual void DiscardDeviceResources() override;
    virtual void Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) override;

    virtual const std::string& GetKey() const override { return m_key; }
    virtual TelemIndicatorType GetType() const override { return TELEM_IND_TIME_DISPLAY; }
    virtual int32_t GetZOrder() const override { return m_z_order; }

private:
    std::string             m_key;
    TelemTimeDisplayStyle   m_style;
    float                   m_x;
    float                   m_y;
    float                   m_width;
    float                   m_height;
    float                   m_rotation;
    float                   m_alpha;
    int32_t                 m_z_order;

    FontCache*              m_pFontCache;
    IconCache*              m_pIconCache;

    ID2D1SolidColorBrush*   m_pBrushDate;
    ID2D1SolidColorBrush*   m_pBrushTime;
    ID2D1SolidColorBrush*   m_pBrushElapsed;
    ID2D1SolidColorBrush*   m_pBrushAvgSpeed;
    ID2D1SolidColorBrush*   m_pBrushOutline;

    IDWriteTextFormat*      m_pFmtDate;
    IDWriteTextFormat*      m_pFmtTime;
    IDWriteTextFormat*      m_pFmtElapsed;
    IDWriteTextFormat*      m_pFmtAvgSpeed;
};

#endif // TIME_DISPLAY_INDICATOR_H
