#ifndef FONT_CACHE_H
#define FONT_CACHE_H

#include <d2d1_1.h>
#include <dwrite.h>
#include <string>
#include <map>
#include <tuple>

class FontCache {
public:
    FontCache();
    ~FontCache();

    void Init(IDWriteFactory* pDWriteFactory);
    void Clear();

    IDWriteTextFormat* GetFormat(const std::wstring& family, float size, DWRITE_FONT_WEIGHT weight = DWRITE_FONT_WEIGHT_NORMAL, DWRITE_FONT_STYLE style = DWRITE_FONT_STYLE_NORMAL);

    // Static helper to draw outlined text cleanly
    static void DrawTextOutlined(
        ID2D1DeviceContext* pD2D,
        const std::wstring& text,
        IDWriteTextFormat* pFormat,
        const D2D1_RECT_F& layoutRect,
        ID2D1Brush* pTextBrush,
        ID2D1Brush* pOutlineBrush,
        float outlineWidth,
        DWRITE_TEXT_ALIGNMENT align = DWRITE_TEXT_ALIGNMENT_LEADING
    );

private:
    IDWriteFactory* m_pDWriteFactory;
    std::map<std::tuple<std::wstring, int, int, int>, IDWriteTextFormat*> m_formats;
};

#endif // FONT_CACHE_H
