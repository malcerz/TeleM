#ifndef INDICATOR_BASE_H
#define INDICATOR_BASE_H

#include <d2d1_1.h>
#include <dwrite.h>
#include <string>
#include <memory>
#include "telem_nvenc_api.h"

// Diagnostic-only Direct2D stack accounting.  The pointer is set by the
// native pipeline on the rendering thread; production leaves it null.
struct TelemD2DStateTrace {
    int clip_depth = 0;
    int layer_depth = 0;
    int begin_draw_depth = 0;
};

extern thread_local TelemD2DStateTrace* g_telem_d2d_state_trace;

inline void TelemD2DTracePushClip() {
    if (g_telem_d2d_state_trace) ++g_telem_d2d_state_trace->clip_depth;
}

inline void TelemD2DTracePopClip() {
    if (g_telem_d2d_state_trace) --g_telem_d2d_state_trace->clip_depth;
}

inline void TelemD2DTracePushLayer() {
    if (g_telem_d2d_state_trace) ++g_telem_d2d_state_trace->layer_depth;
}

inline void TelemD2DTracePopLayer() {
    if (g_telem_d2d_state_trace) --g_telem_d2d_state_trace->layer_depth;
}

// Helper to convert 0xAARRGGBB to D2D1_COLOR_F
inline D2D1_COLOR_F ColorFromHex(uint32_t c) {
    float a = ((c >> 24) & 0xFF) / 255.0f;
    float r = ((c >> 16) & 0xFF) / 255.0f;
    float g = ((c >> 8) & 0xFF) / 255.0f;
    float b = (c & 0xFF) / 255.0f;
    return D2D1::ColorF(r, g, b, a);
}

class IndicatorBase {
public:
    virtual ~IndicatorBase() = default;

    virtual bool CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) = 0;
    virtual void DiscardDeviceResources() = 0;
    virtual void Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) = 0;

    virtual const std::string& GetKey() const = 0;
    virtual TelemIndicatorType GetType() const = 0;
    virtual int32_t GetZOrder() const = 0;
};

#endif // INDICATOR_BASE_H
