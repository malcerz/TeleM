#include "text_indicator.h"
#include <vector>

TextIndicator::TextIndicator(const TelemIndicatorDesc& desc, FontCache* pFontCache, IconCache* pIconCache)
    : m_key(desc.key)
    , m_style(desc.style.text)
    , m_x(desc.x)
    , m_y(desc.y)
    , m_width(desc.width)
    , m_height(desc.height)
    , m_rotation(desc.rotation)
    , m_alpha(desc.alpha)
    , m_z_order(desc.z_order)
    , m_pFontCache(pFontCache)
    , m_pIconCache(pIconCache)
    , m_pTextBrush(nullptr)
    , m_pOutlineBrush(nullptr)
    , m_pTextFormat(nullptr)
{
}

TextIndicator::~TextIndicator() {
    DiscardDeviceResources();
}

bool TextIndicator::CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) {
    DiscardDeviceResources();

    if (!pD2D || !pDWrite || !m_pFontCache) return false;

    // Brushes
    D2D1_COLOR_F textColor = ColorFromHex(m_style.text_color ? m_style.text_color : 0xFFFFFFFF);
    pD2D->CreateSolidColorBrush(textColor, &m_pTextBrush);

    D2D1_COLOR_F outlineColor = ColorFromHex(m_style.outline_color ? m_style.outline_color : 0xFF000000);
    pD2D->CreateSolidColorBrush(outlineColor, &m_pOutlineBrush);

    // Format
    m_pTextFormat = m_pFontCache->GetFormat(
        m_style.font_family[0] ? m_style.font_family : L"Arial",
        m_style.font_size > 0 ? m_style.font_size : 54.0f,
        DWRITE_FONT_WEIGHT_NORMAL
    );

    return (m_pTextBrush != nullptr && m_pOutlineBrush != nullptr && m_pTextFormat != nullptr);
}

void TextIndicator::DiscardDeviceResources() {
    if (m_pTextBrush) {
        m_pTextBrush->Release();
        m_pTextBrush = nullptr;
    }
    if (m_pOutlineBrush) {
        m_pOutlineBrush->Release();
        m_pOutlineBrush = nullptr;
    }
    m_pTextFormat = nullptr; // managed by FontCache
}

void TextIndicator::Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    if (!pD2D || !m_pTextFormat || !m_pTextBrush) return;

    // 1. Resolve live string
    const char* val_str = "";
    if (m_key == "exposure_text" || m_style.telemetry_field == TELEM_FIELD_EXPOSURE) {
        val_str = state.exposure_str;
    } else if (m_key == "iso_text" || m_style.telemetry_field == TELEM_FIELD_ISO) {
        val_str = state.iso_str;
    } else if (m_key == "temp_text" || m_style.telemetry_field == TELEM_FIELD_TEMPERATURE) {
        val_str = state.temp_str;
    } else if (m_key == "fit_gopro_battery_text" || m_style.telemetry_field == TELEM_FIELD_GOPRO_BATTERY) {
        val_str = state.gopro_battery_str;
    }

    // Convert value string to wide
    wchar_t wVal[64] = { 0 };
    if (val_str && val_str[0]) {
        MultiByteToWideChar(CP_UTF8, 0, val_str, -1, wVal, 64);
    }

    // Construct full display string: "Label: Value" or "Value"
    std::wstring displayText;
    if (m_style.label[0] && wVal[0]) {
        displayText = std::wstring(m_style.label) + L": " + wVal;
    } else if (m_style.label[0]) {
        displayText = m_style.label;
    } else {
        displayText = wVal;
    }

    if (displayText.empty()) return;

    // 2. Icon handling
    float start_x = (m_style.canvas_x > 0.0f) ? m_style.canvas_x : m_x;
    float start_y = (m_style.canvas_y > 0.0f) ? m_style.canvas_y : m_y;
    float current_x = start_x;
    float fs = m_style.font_size > 0 ? m_style.font_size : 54.0f;
    float icon_dim = m_style.icon_size > 0 ? m_style.icon_size : (fs * 0.90f);
    float gap = fs * 0.22f;

    ID2D1Bitmap* pIconBitmap = nullptr;
    if (m_pIconCache && m_style.icon_name[0] && strcmp(m_style.icon_name, "none") != 0) {
        pIconBitmap = m_pIconCache->GetIcon(pD2D, m_style.icon_name);
    }

    if (pIconBitmap) {
        D2D1_SIZE_F bitmapSize = pIconBitmap->GetSize();
        float aspect = bitmapSize.width / (bitmapSize.height > 0.1f ? bitmapSize.height : 1.0f);
        float icon_w = icon_dim * aspect;
        float icon_h = icon_dim;

        // Optical vertical alignment with text
        float icon_y = start_y + ((m_style.icon_offset_y != 0.0f) ? m_style.icon_offset_y : (fs - icon_h) * 0.5f);
        D2D1_RECT_F iconRect = D2D1::RectF(current_x, icon_y, current_x + icon_w, icon_y + icon_h);
        pD2D->DrawBitmap(pIconBitmap, &iconRect);

        current_x += icon_w + gap;
    }

    // 3. Draw text with outline
    float text_y = start_y + m_style.text_offset_y;
    D2D1_RECT_F textRect = D2D1::RectF(current_x, text_y, current_x + 1000.0f, text_y + fs * 1.5f);
    float outline_w = m_style.outline_width > 0 ? m_style.outline_width : 6.0f;

    FontCache::DrawTextOutlined(
        pD2D,
        displayText,
        m_pTextFormat,
        textRect,
        m_pTextBrush,
        m_pOutlineBrush,
        outline_w,
        DWRITE_TEXT_ALIGNMENT_LEADING
    );
}
