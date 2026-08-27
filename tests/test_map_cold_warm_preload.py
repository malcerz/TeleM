import pytest
from unittest.mock import patch, MagicMock
from src.indicators.moving_map import map_required_tile_margin, ensure_map_tiles_cached
from src.moving_map import (
    TileCache,
    MapTileStats,
    set_map_network_allowed,
    is_map_network_allowed,
    reset_map_tile_stats,
    get_map_tile_stats,
    _download_tile_raw,
)
from datetime import datetime, timezone

def test_map_required_tile_margin():
    # 4K resolution (3840x2160), map_w ~ 691 px -> working_size ~ 978 px -> half_tiles = 3
    margin_4k = map_required_tile_margin(3840, 691, track_up=True)
    assert margin_4k == 3

    # 1080p resolution (1920x1080), map_w ~ 345 px -> working_size ~ 488 px -> half_tiles = 2
    margin_1080p = map_required_tile_margin(1920, 345, track_up=True)
    assert margin_1080p == 2

    # North-up (no rotation working size inflation)
    margin_north_up = map_required_tile_margin(1920, 345, track_up=False)
    assert margin_north_up == 2


def test_map_network_allowed_gating():
    set_map_network_allowed(False)
    assert not is_map_network_allowed()

    # When network is disabled, _download_tile_raw returns None immediately without HTTP requests
    result = _download_tile_raw(16, 1234, 5678, "satellite")
    assert result is None

    set_map_network_allowed(True)
    assert is_map_network_allowed()


def test_map_tile_stats_accounting():
    reset_map_tile_stats()
    stats = get_map_tile_stats()
    assert stats["tiles_requested"] == 0
    assert stats["memory_hits"] == 0
    assert stats["disk_hits"] == 0
    assert stats["network_misses"] == 0
    assert stats["network_requests"] == 0


def test_ensure_map_tiles_cached_all_cached(tmp_path):
    layout = {
        "indicators": {
            "track_map": {
                "enabled": True,
                "size": 0.18,
                "zoom": 14,
                "map_style": "satellite",
                "map_orientation": "track_up",
            }
        }
    }
    gps_track = [
        (datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc), 52.23, 21.01),
        (datetime(2026, 8, 22, 10, 1, 0, tzinfo=timezone.utc), 52.24, 21.02),
    ]

    with patch("src.moving_map.TileCache.has", return_value=True):
        info = ensure_map_tiles_cached(3840, 2160, layout, "track_map", gps_track)
        assert info["required"] > 0
        assert info["cached"] == info["required"]
        assert info["downloaded"] == 0
        assert info["missing"] == 0
