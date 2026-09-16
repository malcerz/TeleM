#include "map_indicator.h"
#include <iostream>

MapIndicator::MapIndicator(const TelemIndicatorDesc& desc)
    : m_desc(desc)
    , m_key(desc.key)
    , m_pD2D(nullptr)
    , m_pWicFactory(nullptr)
    , m_pTrackBrush(nullptr)
    , m_pMarkerBrush(nullptr)
    , m_pMarkerBorderBrush(nullptr)
    , m_pBorderBrush(nullptr)
    , m_pBgBrush(nullptr)
    , m_pTrackStrokeStyle(nullptr)
    , m_pLayer(nullptr)
    , m_pRouteGeometry(nullptr)
    , m_cache_hits(0)
    , m_cache_misses(0)
    , m_peak_vram_bytes(0)
{
}

MapIndicator::~MapIndicator() {
    DiscardDeviceResources();
    if (m_pWicFactory) {
        m_pWicFactory->Release();
        m_pWicFactory = nullptr;
    }
}

void MapIndicator::SetRoute(const double* lats, const double* lons, uint32_t count) {
    m_route_lat_lon.clear();
    if (lats && lons && count > 0) {
        m_route_lat_lon.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            m_route_lat_lon.push_back({ lats[i], lons[i] });
        }
    }

    if (m_pD2D) {
        ID2D1Factory* pFactory = nullptr;
        m_pD2D->GetFactory(&pFactory);
        if (pFactory) {
            BuildRouteGeometry(pFactory);
            pFactory->Release();
        }
    }
}

bool MapIndicator::PreloadTile(int32_t z, int32_t x, int32_t y, const void* data, uint32_t size_bytes) {
    if (!data || size_bytes == 0) return false;

    if (m_pD2D) {
        return DecodeTileToBitmap(z, x, y, data, size_bytes);
    } else {
        auto key = std::make_tuple(z, x, y);
        const uint8_t* bytePtr = static_cast<const uint8_t*>(data);
        m_pending_tiles[key] = std::vector<uint8_t>(bytePtr, bytePtr + size_bytes);
        return true;
    }
}

void MapIndicator::GetCacheStats(TelemMapCacheStats& out_stats) const {
    out_stats.total_tiles = (uint32_t)(m_tile_bitmaps.size() + m_pending_tiles.size());
    out_stats.decoded_tiles = (uint32_t)m_tile_bitmaps.size();
    out_stats.cache_hits = m_cache_hits;
    out_stats.cache_misses = m_cache_misses;
    out_stats.vram_bytes = (uint64_t)m_tile_bitmaps.size() * 256 * 256 * 4;
    out_stats.peak_vram_bytes = m_peak_vram_bytes;
}

bool MapIndicator::CreateDeviceResources(ID2D1DeviceContext* pD2D, IDWriteFactory* pDWrite) {
    (void)pDWrite;
    DiscardDeviceResources();
    if (!pD2D) return false;
    m_pD2D = pD2D;

    m_pD2D->CreateSolidColorBrush(ColorFromHex(m_desc.style.map.track_color), &m_pTrackBrush);
    m_pD2D->CreateSolidColorBrush(ColorFromHex(m_desc.style.map.marker_color), &m_pMarkerBrush);
    
    uint32_t markerBorderColor = m_desc.style.map.marker_border_color;
    if ((markerBorderColor & 0xFF000000) == 0) markerBorderColor = 0xDC000000;
    m_pD2D->CreateSolidColorBrush(ColorFromHex(markerBorderColor), &m_pMarkerBorderBrush);

    uint32_t borderColor = m_desc.style.map.border_color;
    if ((borderColor & 0xFF000000) == 0) borderColor = 0xFF333333;
    m_pD2D->CreateSolidColorBrush(ColorFromHex(borderColor), &m_pBorderBrush);

    m_pD2D->CreateSolidColorBrush(D2D1::ColorF(0.1176f, 0.1176f, 0.1176f, 1.0f), &m_pBgBrush);

    m_pD2D->CreateLayer(nullptr, &m_pLayer);

    ID2D1Factory* pFactory = nullptr;
    m_pD2D->GetFactory(&pFactory);
    if (pFactory) {
        D2D1_STROKE_STYLE_PROPERTIES strokeProps = D2D1::StrokeStyleProperties(
            D2D1_CAP_STYLE_ROUND,
            D2D1_CAP_STYLE_ROUND,
            D2D1_CAP_STYLE_ROUND,
            D2D1_LINE_JOIN_ROUND
        );
        pFactory->CreateStrokeStyle(&strokeProps, nullptr, 0, &m_pTrackStrokeStyle);

        BuildRouteGeometry(pFactory);
        pFactory->Release();
    }

    // Decode any preloaded pending tiles
    if (!m_pending_tiles.empty()) {
        for (const auto& kv : m_pending_tiles) {
            int32_t z = std::get<0>(kv.first);
            int32_t x = std::get<1>(kv.first);
            int32_t y = std::get<2>(kv.first);
            DecodeTileToBitmap(z, x, y, kv.second.data(), (uint32_t)kv.second.size());
        }
        m_pending_tiles.clear();
    }

    return true;
}

void MapIndicator::DiscardDeviceResources() {
    if (m_pTrackBrush) { m_pTrackBrush->Release(); m_pTrackBrush = nullptr; }
    if (m_pMarkerBrush) { m_pMarkerBrush->Release(); m_pMarkerBrush = nullptr; }
    if (m_pMarkerBorderBrush) { m_pMarkerBorderBrush->Release(); m_pMarkerBorderBrush = nullptr; }
    if (m_pBorderBrush) { m_pBorderBrush->Release(); m_pBorderBrush = nullptr; }
    if (m_pBgBrush) { m_pBgBrush->Release(); m_pBgBrush = nullptr; }
    if (m_pTrackStrokeStyle) { m_pTrackStrokeStyle->Release(); m_pTrackStrokeStyle = nullptr; }
    if (m_pLayer) { m_pLayer->Release(); m_pLayer = nullptr; }
    if (m_pRouteGeometry) { m_pRouteGeometry->Release(); m_pRouteGeometry = nullptr; }

    for (auto& pair : m_tile_bitmaps) {
        if (pair.second) {
            pair.second->Release();
        }
    }
    m_tile_bitmaps.clear();
    m_pD2D = nullptr;
}

bool MapIndicator::DecodeTileToBitmap(int32_t z, int32_t x, int32_t y, const void* data, uint32_t size_bytes) {
    if (!m_pD2D || !data || size_bytes == 0) return false;

    if (!m_pWicFactory) {
        HRESULT hr = CoCreateInstance(
            CLSID_WICImagingFactory,
            NULL,
            CLSCTX_INPROC_SERVER,
            IID_PPV_ARGS(&m_pWicFactory)
        );
        if (FAILED(hr) || !m_pWicFactory) return false;
    }

    IWICStream* pStream = nullptr;
    HRESULT hr = m_pWicFactory->CreateStream(&pStream);
    if (FAILED(hr) || !pStream) return false;

    hr = pStream->InitializeFromMemory(reinterpret_cast<BYTE*>(const_cast<void*>(data)), size_bytes);
    if (FAILED(hr)) {
        pStream->Release();
        return false;
    }

    IWICBitmapDecoder* pDecoder = nullptr;
    hr = m_pWicFactory->CreateDecoderFromStream(pStream, NULL, WICDecodeMetadataCacheOnDemand, &pDecoder);
    pStream->Release();
    if (FAILED(hr) || !pDecoder) return false;

    IWICBitmapFrameDecode* pFrame = nullptr;
    hr = pDecoder->GetFrame(0, &pFrame);
    if (FAILED(hr) || !pFrame) {
        pDecoder->Release();
        return false;
    }

    IWICFormatConverter* pConverter = nullptr;
    hr = m_pWicFactory->CreateFormatConverter(&pConverter);
    if (FAILED(hr) || !pConverter) {
        pFrame->Release();
        pDecoder->Release();
        return false;
    }

    hr = pConverter->Initialize(
        pFrame,
        GUID_WICPixelFormat32bppPBGRA,
        WICBitmapDitherTypeNone,
        NULL,
        0.0,
        WICBitmapPaletteTypeCustom
    );

    ID2D1Bitmap* pBitmap = nullptr;
    if (SUCCEEDED(hr)) {
        hr = m_pD2D->CreateBitmapFromWicBitmap(pConverter, NULL, &pBitmap);
    }

    pConverter->Release();
    pFrame->Release();
    pDecoder->Release();

    if (SUCCEEDED(hr) && pBitmap) {
        auto key = std::make_tuple(z, x, y);
        auto it = m_tile_bitmaps.find(key);
        if (it != m_tile_bitmaps.end() && it->second) {
            it->second->Release();
        }
        m_tile_bitmaps[key] = pBitmap;
        uint64_t current_vram = (uint64_t)m_tile_bitmaps.size() * 256 * 256 * 4;
        if (current_vram > m_peak_vram_bytes) {
            m_peak_vram_bytes = current_vram;
        }
        return true;
    }
    return false;
}

void MapIndicator::BuildRouteGeometry(ID2D1Factory* pFactory) {
    if (!pFactory || m_route_lat_lon.size() < 2) return;
    if (m_pRouteGeometry) {
        m_pRouteGeometry->Release();
        m_pRouteGeometry = nullptr;
    }

    int zoom = m_desc.style.map.zoom;
    HRESULT hr = pFactory->CreatePathGeometry(&m_pRouteGeometry);
    if (FAILED(hr) || !m_pRouteGeometry) return;

    ID2D1GeometrySink* pSink = nullptr;
    hr = m_pRouteGeometry->Open(&pSink);
    if (FAILED(hr) || !pSink) {
        m_pRouteGeometry->Release();
        m_pRouteGeometry = nullptr;
        return;
    }

    pSink->SetFillMode(D2D1_FILL_MODE_WINDING);
    MercatorPoint p0 = LatLonToWorldPixels(m_route_lat_lon[0].first, m_route_lat_lon[0].second, zoom);
    pSink->BeginFigure(D2D1::Point2F((float)p0.x, (float)p0.y), D2D1_FIGURE_BEGIN_HOLLOW);

    std::vector<D2D1_POINT_2F> points(m_route_lat_lon.size() - 1);
    for (size_t i = 1; i < m_route_lat_lon.size(); ++i) {
        MercatorPoint pt = LatLonToWorldPixels(m_route_lat_lon[i].first, m_route_lat_lon[i].second, zoom);
        points[i - 1] = D2D1::Point2F((float)pt.x, (float)pt.y);
    }
    pSink->AddLines(points.data(), (UINT32)points.size());
    pSink->EndFigure(D2D1_FIGURE_END_OPEN);
    pSink->Close();
    pSink->Release();
}

void MapIndicator::Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state) {
    if (!pD2D || !m_pLayer) return;

    float cx = m_desc.style.map.canvas_x;
    float cy = m_desc.style.map.canvas_y;
    float w = m_desc.style.map.width;
    float h = m_desc.style.map.height;
    float left = cx - w * 0.5f;
    float top = cy - h * 0.5f;
    D2D1_RECT_F dstRect = D2D1::RectF(left, top, left + w, top + h);
    float radius = m_desc.style.map.corner_radius;

    ID2D1Factory* pFactory = nullptr;
    pD2D->GetFactory(&pFactory);
    if (!pFactory) return;

    D2D1_ROUNDED_RECT roundedRect = D2D1::RoundedRect(dstRect, radius, radius);
    ID2D1RoundedRectangleGeometry* pRoundedGeom = nullptr;
    pFactory->CreateRoundedRectangleGeometry(&roundedRect, &pRoundedGeom);

    float alpha = m_desc.style.map.alpha;
    if (alpha > 1.0f) alpha /= 255.0f;
    alpha = std::max(0.0f, std::min(1.0f, alpha));

    D2D1_LAYER_PARAMETERS layerParams = D2D1::LayerParameters(
        D2D1::InfiniteRect(),
        pRoundedGeom,
        D2D1_ANTIALIAS_MODE_PER_PRIMITIVE,
        D2D1::Matrix3x2F::Identity(),
        alpha,
        nullptr,
        D2D1_LAYER_OPTIONS_NONE
    );

    pD2D->PushLayer(&layerParams, m_pLayer);

    // 1. Background fill
    if (m_pBgBrush) {
        pD2D->FillRoundedRectangle(&roundedRect, m_pBgBrush);
    }

    // 2. World position & transform
    int zoom = m_desc.style.map.zoom;
    double lat = state.map_latitude;
    double lon = state.map_longitude;
    MercatorPoint curPos = LatLonToWorldPixels(lat, lon, zoom);
    double cpx = curPos.x;
    double cpy = curPos.y;

    float heading = 0.0f;
    if (m_desc.style.map.rotate_map && state.has_map_heading) {
        heading = state.map_heading_deg;
    }

    D2D1_MATRIX_3X2_F mapTransform =
        D2D1::Matrix3x2F::Translation((float)-cpx, (float)-cpy) *
        D2D1::Matrix3x2F::Rotation(-heading) *
        D2D1::Matrix3x2F::Translation(cx, cy);

    pD2D->SetTransform(mapTransform);

    // 3. Tile selection & drawing
    float render_w = m_desc.style.map.rotate_map ? (float)std::ceil(w * 1.41421356f) : w;
    float render_h = m_desc.style.map.rotate_map ? (float)std::ceil(h * 1.41421356f) : h;

    int center_tile_x = (int)std::floor(cpx / 256.0);
    int center_tile_y = (int)std::floor(cpy / 256.0);
    int half_w = (int)std::ceil(render_w / 2.0f / 256.0f) + 1;
    int half_h = (int)std::ceil(render_h / 2.0f / 256.0f) + 1;
    int tx1 = center_tile_x - half_w;
    int tx2 = center_tile_x + half_w + 1;
    int ty1 = center_tile_y - half_h;
    int ty2 = center_tile_y + half_h + 1;

    for (int ty = ty1; ty < ty2; ++ty) {
        for (int tx = tx1; tx < tx2; ++tx) {
            auto key = std::make_tuple(zoom, tx, ty);
            auto it = m_tile_bitmaps.find(key);
            if (it != m_tile_bitmaps.end() && it->second != nullptr) {
                m_cache_hits++;
                D2D1_RECT_F tileRect = D2D1::RectF(
                    (float)(tx * 256.0),
                    (float)(ty * 256.0),
                    (float)((tx + 1) * 256.0),
                    (float)((ty + 1) * 256.0)
                );
                pD2D->DrawBitmap(it->second, &tileRect);
            } else {
                m_cache_misses++;
            }
        }
    }

    // 4. Track vector route
    if (m_pRouteGeometry && m_pTrackBrush) {
        pD2D->DrawGeometry(m_pRouteGeometry, m_pTrackBrush, m_desc.style.map.track_width, m_pTrackStrokeStyle);
    }

    // 5. Reset transform for marker
    pD2D->SetTransform(D2D1::Matrix3x2F::Identity());

    // 6. Current position marker at widget center
    if (m_desc.style.map.marker_style == 1) { // Directional
        float r = m_desc.style.map.marker_radius;
        D2D1_POINT_2F tip = D2D1::Point2F(cx, cy - r * 1.8f);
        D2D1_POINT_2F pLeft = D2D1::Point2F(cx - r * 0.65f, cy + r * 0.75f);
        D2D1_POINT_2F pRight = D2D1::Point2F(cx + r * 0.65f, cy + r * 0.75f);

        ID2D1PathGeometry* pArrowGeom = nullptr;
        if (SUCCEEDED(pFactory->CreatePathGeometry(&pArrowGeom))) {
            ID2D1GeometrySink* pSink = nullptr;
            if (SUCCEEDED(pArrowGeom->Open(&pSink))) {
                pSink->BeginFigure(tip, D2D1_FIGURE_BEGIN_FILLED);
                pSink->AddLine(pLeft);
                pSink->AddLine(pRight);
                pSink->EndFigure(D2D1_FIGURE_END_CLOSED);
                pSink->Close();
                pSink->Release();

                if (m_pMarkerBrush) pD2D->FillGeometry(pArrowGeom, m_pMarkerBrush);
                if (m_pMarkerBorderBrush) pD2D->DrawGeometry(pArrowGeom, m_pMarkerBorderBrush, 2.0f);
            }
            pArrowGeom->Release();
        }
    } else { // Dot
        float r = m_desc.style.map.marker_radius;
        D2D1_ELLIPSE el = D2D1::Ellipse(D2D1::Point2F(cx, cy), r, r);
        if (m_pMarkerBrush) pD2D->FillEllipse(&el, m_pMarkerBrush);
        if (m_pMarkerBorderBrush) pD2D->DrawEllipse(&el, m_pMarkerBorderBrush, 2.0f);
    }

    // Pop layer
    pD2D->PopLayer();

    if (pRoundedGeom) pRoundedGeom->Release();
    pFactory->Release();

    // 7. Outer border
    if (m_desc.style.map.border_width > 0.0f && m_pBorderBrush) {
        pD2D->DrawRoundedRectangle(&roundedRect, m_pBorderBrush, m_desc.style.map.border_width);
    }
}
