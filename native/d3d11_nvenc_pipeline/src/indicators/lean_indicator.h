#ifndef LEAN_INDICATOR_H
#define LEAN_INDICATOR_H

#include "indicator_base.h"
#include "font_cache.h"

// Native counterpart of src/indicators/lean.py.  The descriptor carries the
// already-resolved canonical physical-roll/visual-angle state; this class only
// owns the D2D geometry and the deterministic procedural bike marker used when
// no external bike bitmap is configured.
class LeanIndicator : public IndicatorBase {
public:
    LeanIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache);
    ~LeanIndicator() override;

    bool CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) override;
    void DiscardDeviceResources() override;
    void Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) override;

    const std::string& GetKey() const override { return m_key; }
    TelemIndicatorType GetType() const override { return TELEM_IND_LEAN; }
    int32_t GetZOrder() const override { return m_z_order; }

private:
    std::string m_key;
    TelemLeanStyle m_style;
    float m_cx;
    float m_cy;
    float m_width;
    float m_height;
    float m_rotation;
    float m_alpha;
    int32_t m_z_order;
    FontCache* m_pFontCache;
    ID2D1SolidColorBrush* m_pMarkerBrush;
    ID2D1SolidColorBrush* m_pTrackBrush;
    ID2D1SolidColorBrush* m_pTickBrush;
    ID2D1SolidColorBrush* m_pTextBrush;
    ID2D1SolidColorBrush* m_pOutlineBrush;
    IDWriteTextFormat* m_pFmtTitle;
    IDWriteTextFormat* m_pFmtValue;
};

#endif // LEAN_INDICATOR_H
