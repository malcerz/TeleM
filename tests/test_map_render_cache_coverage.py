from __future__ import annotations

import io
import math
from datetime import datetime, timezone

from PIL import Image

from src.indicators.moving_map import (
    ensure_map_tiles_cached,
    map_required_tile_margin,
)
from src.moving_map import (
    TILE_SIZE,
    MapTileStats,
    TileCache,
    _lat_lon_to_tile,
    iter_track_center_tiles,
    tile_range_for_center_tile,
    track_up_working_size,
)


def _tile_to_lat_lon(x: float, y: float, zoom: int) -> tuple[float, float]:
    n = float(2**zoom)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lat, lon


def _render_tile_union(track, zoom, render_size):
    cells = iter_track_center_tiles(track, zoom)
    result = set()
    for cx, cy in cells:
        tx1, tx2, ty1, ty2 = tile_range_for_center_tile(
            cx, cy, render_size, render_size,
        )
        result.update((x, y) for x in range(tx1, tx2) for y in range(ty1, ty2))
    return result


def test_prefetch_covers_diagonal_interpolated_center_cells():
    zoom = 18
    # The segment changes x and y in opposite directions.  The old union of
    # endpoint squares misses the diagonal combination used by interpolation.
    p0 = _tile_to_lat_lon(136882.60, 89008.10, zoom)
    p1 = _tile_to_lat_lon(136883.10, 89007.60, zoom)
    track = [
        (datetime(2026, 9, 6, tzinfo=timezone.utc), *p0),
        (datetime(2026, 9, 6, 0, 0, 1, tzinfo=timezone.utc), *p1),
    ]
    render_size = track_up_working_size(691)
    margin = map_required_tile_margin(3840, 691, track_up=True)

    old_endpoint_tiles = set()
    for _, lat, lon in track:
        tx, ty, _, _ = _lat_lon_to_tile(lat, lon, zoom)
        old_endpoint_tiles.update(
            (tx + dx, ty + dy)
            for dx in range(-margin, margin + 1)
            for dy in range(-margin, margin + 1)
        )
    render_tiles = _render_tile_union(track, zoom, render_size)
    new_prefetch_tiles = render_tiles

    assert render_tiles - old_endpoint_tiles
    assert not render_tiles - new_prefetch_tiles


def test_tile_cache_stats_distinguish_hit_miss_and_timings(tmp_path):
    MapTileStats.reset()
    cache = TileCache(tmp_path)
    tile = Image.new("RGBA", (8, 8), (20, 30, 40, 255))
    raw = io.BytesIO()
    tile.save(raw, format="PNG")
    cache.put(18, 10, 20, "satellite", raw.getvalue())

    assert cache.get(18, 10, 20, "satellite") is not None
    assert cache.get(18, 10, 21, "satellite") is None
    stats = MapTileStats.get_stats()
    assert stats["map_cache_hits"] >= 1
    assert stats["map_cache_misses"] >= 1
    assert stats["disk_hits"] == 0  # the shared class LRU serves this lookup
    assert stats["tile_lookup_ms"] >= 0.0


def test_map_render_stats_keep_p90_buckets():
    MapTileStats.reset()
    MapTileStats.record_render_frame(2.0, False)
    MapTileStats.record_render_frame(10.0, True)
    MapTileStats.record_render_frame(4.0, False)
    stats = MapTileStats.get_stats()
    assert stats["render_frames"] == 3
    assert stats["frames_with_cache_miss"] == 1
    assert stats["p90_frame_time_with_miss_ms"] == 10.0
    assert stats["p90_frame_time_without_miss_ms"] == 4.0


def test_ensure_map_tiles_cached_reports_exact_render_footprint(monkeypatch):
    layout = {
        "indicators": {
            "track_map": {
                "enabled": True,
                "size": 18.0,
                "zoom": 16,
                "map_style": "satellite",
                "map_orientation": "track_up",
            }
        }
    }
    track = [
        (datetime(2026, 9, 6, tzinfo=timezone.utc), 54.330, 18.597),
        (datetime(2026, 9, 6, 0, 0, 1, tzinfo=timezone.utc), 54.331, 18.598),
    ]
    requested = []
    monkeypatch.setenv("AMD_MAP_ALIGN", "1")

    class FakeCache:
        def has(self, z, x, y, style):
            requested.append((z, x, y, style))
            return True

    monkeypatch.setattr("src.moving_map.get_shared_tile_cache", lambda: FakeCache())
    info = ensure_map_tiles_cached(3840, 2160, layout, "track_map", track)
    assert info["required"] == len(set(requested))
    assert info["missing"] == 0
    assert info["render_size"] == track_up_working_size(691)
    assert info["required"] == len(_render_tile_union(track, 18, info["render_size"]))
