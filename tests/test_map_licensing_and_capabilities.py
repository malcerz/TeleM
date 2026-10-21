"""Tests for map provider licensing compliance, capabilities, API key management, and prefetch gating."""

import io
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from PIL import Image

from src.integrations import credential_store
from src.map_attribution import MapAttributionRenderer
from src.map_providers import (
    ExportPermission,
    MapProviderCapabilities,
    MapProviderRegistry,
    mask_url,
)
from src.moving_map import (
    MovingMapRenderer,
    RouteTilePrefetcher,
    TileCache,
    _download_tile_raw,
    is_map_network_allowed,
    set_map_network_allowed,
)


@pytest.fixture(autouse=True)
def _clean_credential_mock():
    credential_store.set_mock_mode(True)
    yield
    credential_store.set_mock_mode(True)


def test_provider_registry_resolution_and_defaults():
    osm = MapProviderRegistry.get_capabilities("osm")
    assert osm.provider_id == "osm"
    assert osm.allows_route_prefetch is False
    assert osm.cache_max_age == 7
    assert osm.requires_api_key is False
    assert osm.video_export_permission == ExportPermission.CONDITIONAL

    carto = MapProviderRegistry.get_capabilities("light_all")
    assert carto.provider_id == "light_all"
    assert carto.requires_api_key is True
    assert carto.allows_route_prefetch is False
    assert carto.cache_max_age == 30
    assert "CARTO" in carto.attribution_text

    satellite = MapProviderRegistry.get_capabilities("satellite")
    assert satellite.provider_id == "satellite"
    assert satellite.allows_route_prefetch is False
    assert satellite.allows_offline_cache is False
    assert satellite.commercial_use_permission == ExportPermission.PROHIBITED

    custom = MapProviderRegistry.get_capabilities("custom")
    assert custom.provider_id == "custom"
    assert custom.allows_route_prefetch is True
    assert custom.video_export_permission == ExportPermission.CONFIRMED


def test_custom_url_provider_inference():
    custom_url = "http://my-tile-server.lan:8080/tiles/{z}/{x}/{y}.png"
    caps = MapProviderRegistry.get_capabilities(custom_url)
    assert caps.allows_route_prefetch is True
    assert caps.video_export_permission == ExportPermission.CONFIRMED
    assert caps.service_url == custom_url


def test_unknown_provider_treated_as_unconfirmed():
    caps = MapProviderRegistry.get_capabilities("some_random_unknown_style")
    assert caps.video_export_permission == ExportPermission.UNKNOWN
    assert caps.allows_route_prefetch is False
    status, reason = MapProviderRegistry.can_export_video("some_random_unknown_style")
    assert status == ExportPermission.UNKNOWN


def test_api_key_secure_storage_and_masking():
    credential_store.save_map_api_key("carto", "secret_carto_key_99999")
    retrieved = credential_store.get_map_api_key("carto")
    assert retrieved == "secret_carto_key_99999"

    # URL formatting injects key
    formatted = MapProviderRegistry.format_tile_url("light_all", 14, 8000, 5000)
    assert "api_key=secret_carto_key_99999" in formatted

    # Masking ensures secrets never appear in logs
    masked = mask_url(formatted)
    assert "secret_carto_key_99999" not in masked
    assert "api_key=***" in masked

    credential_store.delete_map_api_key("carto")
    assert credential_store.get_map_api_key("carto") is None


def test_osm_prefetch_strictly_denied():
    assert MapProviderRegistry.can_prefetch("osm") is False

    # RouteTilePrefetcher refuses to enqueue tiles for OSM
    tiles = [(14, 100, 200), (14, 101, 200)]
    prefetcher = RouteTilePrefetcher(tiles, "osm")
    assert len(prefetcher._tiles) == 0

    # MovingMapRenderer.precache_tiles returns 0 without network activity
    track = [
        (datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc), 52.23, 21.01),
        (datetime(2026, 8, 22, 10, 1, 0, tzinfo=timezone.utc), 52.24, 21.02),
    ]
    renderer = MovingMapRenderer(track, zoom=14, style="osm")
    with patch("src.moving_map._download_tile_raw") as mock_dl:
        cnt = renderer.precache_tiles(margin=2)
        assert cnt == 0
        mock_dl.assert_not_called()


def test_custom_source_prefetch_allowed():
    assert MapProviderRegistry.can_prefetch("custom") is True
    tiles = [(14, 100, 200), (14, 101, 200)]
    prefetcher = RouteTilePrefetcher(tiles, "custom")
    assert len(prefetcher._tiles) == 2


def test_tile_cache_expiry_and_provider_isolation(tmp_path):
    cache = TileCache(tmp_path)
    img = Image.new("RGBA", (16, 16), (10, 20, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    now = time.time()
    # 1. Fresh CARTO tile (cached now)
    cache.put(14, 10, 20, "light_all", data, cached_at=now)
    assert cache.has(14, 10, 20, "light_all") is True
    assert cache.get(14, 10, 20, "light_all") is not None

    # 2. Expired CARTO tile (>30 days old)
    thirty_one_days_ago = now - (31 * 86400)
    cache.put(14, 11, 20, "light_all", data, cached_at=thirty_one_days_ago)
    TileCache._mem.clear()
    assert cache.has(14, 11, 20, "light_all") is False
    assert cache.get(14, 11, 20, "light_all") is None

    # 3. Provider isolation: same z,x,y for osm vs light_all
    cache.put(14, 10, 20, "osm", data, cached_at=now)
    assert cache.has(14, 10, 20, "osm") is True
    # Deleting or missing for satellite does not affect osm or light_all
    assert cache.has(14, 10, 20, "satellite") is False


def test_attribution_renderer_cached_overlay():
    MapAttributionRenderer.clear_cache()
    overlay1 = MapAttributionRenderer.get_attribution_overlay("light_all", 300, 300)
    assert overlay1 is not None
    assert overlay1.size == (300, 300)

    # Subsequent call returns statically cached instance without re-rendering
    overlay2 = MapAttributionRenderer.get_attribution_overlay("light_all", 300, 300)
    assert overlay1 is overlay2


def test_offline_mode_returns_none_cleanly():
    set_map_network_allowed(False)
    try:
        assert is_map_network_allowed() is False
        res = _download_tile_raw(14, 1234, 5678, "light_all")
        assert res is None
    finally:
        set_map_network_allowed(True)


def test_ensure_map_tiles_cached_respects_prefetch_policy():
    from src.indicators.moving_map import ensure_map_tiles_cached
    layout = {
        "indicators": {
            "track_map": {
                "enabled": True,
                "size": 0.18,
                "zoom": 14,
                "map_style": "osm",
                "map_orientation": "north_up",
            }
        }
    }
    track = [
        (datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc), 52.23, 21.01),
        (datetime(2026, 8, 22, 10, 1, 0, tzinfo=timezone.utc), 52.24, 21.02),
    ]

    # For OSM, ensure_map_tiles_cached recognizes prefetch is not allowed and skips route prefetch
    with patch("src.moving_map._download_tile_raw") as mock_dl:
        info = ensure_map_tiles_cached(1920, 1080, layout, "track_map", track)
        assert info["prefetch_allowed"] is False
        assert info["downloaded"] == 0
        mock_dl.assert_not_called()
