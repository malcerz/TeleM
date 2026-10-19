#ifndef TEXT_INDICATOR_H
#define TEXT_INDICATOR_H

#include "indicator_base.h"
#include "font_cache.h"
#include "icon_cache.h"

class TextIndicator : public IndicatorBase {
public:
    TextIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache, IconCache* pIconCache);
    virtual ~TextIndicator();

    virtual bool CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) override;
    virtual void DiscardDeviceResources() override;
    virtual void Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) override;

    virtual const std::string& GetKey() const override { return m_key; }
    virtual TelemIndicatorType GetType() const override { return TELEM_IND_TEXT; }
    virtual int32_t GetZOrder() const override { return m_z_order; }

private:
    std::string             m_key;
    TelemTextStyle          m_style;
    float                   m_x;
    float                   m_y;
    float                   m_width;
    float                   m_height;
    float                   m_rotation;
    float                   m_alpha;
    int32_t                 m_z_order;

    FontCache*              m_pFontCache;
    IconCache*              m_pIconCache;

    ID2D1SolidColorBrush*   m_pTextBrush;
    ID2D1SolidColorBrush*   m_pOutlineBrush;
    IDWriteTextFormat*      m_pTextFormat;
};

#endif // TEXT_INDICATOR_H
