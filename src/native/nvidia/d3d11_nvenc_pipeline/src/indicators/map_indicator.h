#ifndef MAP_INDICATOR_H
#define MAP_INDICATOR_H

#include "indicator_base.h"
#include <wincodec.h>
#include <vector>
#include <map>
#include <tuple>
#include <memory>
#include <mutex>
#include <cmath>
#include <algorithm>

struct MercatorPoint {
    double x; // world pixel X at current zoom
    double y; // world pixel Y at current zoom
};

inline MercatorPoint LatLonToWorldPixels(double lat, double lon, int zoom) {
    double n = std::pow(2.0, zoom);
    double x_tile = (lon + 180.0) / 360.0 * n;
    double lat_rad = lat * (3.14159265358979323846 / 180.0);
    double y_tile = (1.0 - std::log(std::tan(lat_rad) + 1.0 / std::cos(lat_rad)) / 3.14159265358979323846) / 2.0 * n;
    return { x_tile * 256.0, y_tile * 256.0 };
}

class MapIndicator : public IndicatorBase {
public:
    MapIndicator(const TelemIndicatorDesc& desc);
    virtual ~MapIndicator();

    bool CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) override;
    void DiscardDeviceResources() override;
    void Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) override;

    const std::string& GetKey() const override { return m_key; }
    TelemIndicatorType GetType() const override { return TELEM_IND_MAP; }
    int32_t GetZOrder() const override { return m_desc.z_order; }

    void SetRoute(const double* lats, const double* lons, uint32_t count);
    bool PreloadTile(int32_t z, int32_t x, int32_t y, const void* data, uint32_t size_bytes);
    void GetCacheStats(TelemMapCacheStats& out_stats) const;

private:
    bool DecodeTileToBitmap(int32_t z, int32_t x, int32_t y, const void* data, uint32_t size_bytes);
    void BuildRouteGeometry(ID2D1Factory* pFactory);

private:
    TelemIndicatorDesc m_desc;
    std::string        m_key;

    // Direct2D & WIC resources
    ID2D1DeviceContext*             m_pD2D;
    IWICImagingFactory*             m_pWicFactory;
    ID2D1SolidColorBrush*           m_pTrackBrush;
    ID2D1SolidColorBrush*           m_pMarkerBrush;
    ID2D1SolidColorBrush*           m_pMarkerBorderBrush;
    ID2D1SolidColorBrush*           m_pBorderBrush;
    ID2D1SolidColorBrush*           m_pBgBrush;
    ID2D1StrokeStyle*               m_pTrackStrokeStyle;
    ID2D1Layer*                     m_pLayer;
    ID2D1PathGeometry*              m_pRouteGeometry;

    // Route points in lat/lon
    std::vector<std::pair<double, double>> m_route_lat_lon;

    // Tile storage: raw buffers kept until D2D context is ready
    std::map<std::tuple<int, int, int>, std::vector<uint8_t>> m_pending_tiles;
    // Decoded D2D bitmap cache
    std::map<std::tuple<int, int, int>, ID2D1Bitmap*>         m_tile_bitmaps;

    // Cache accounting
    mutable uint32_t m_cache_hits;
    mutable uint32_t m_cache_misses;
    uint64_t         m_peak_vram_bytes;
};

#endif // MAP_INDICATOR_H
