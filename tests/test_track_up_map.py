"""ETAP 8F coverage for Track-Up map rotation and heading binding."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PIL import Image

import src.moving_map as moving_map
from src.ffmpeg.worker_cache import init_worker
from src.indicators.frame_data import build_active_fit_field_plan, prepare_overlay_frame_data
from src.gui.indicator_schemas import BUILTIN_FIELDS
from src.telemetry_precompute import build_telemetry_cache


T0 = datetime(2026, 8, 18, 4, 47, tzinfo=timezone.utc)


def _eastbound_track() -> list[tuple[datetime, float, float]]:
    return [
        (T0 + timedelta(seconds=i), 54.35, 18.62 + i * 0.001)
        for i in range(30)
    ]


def _seed_tiles(cache_dir, track, zoom: int, max_size: int) -> None:
    renderer = moving_map.MovingMapRenderer(track, zoom=zoom, cache_dir=cache_dir)
    cpx, cpy = renderer._interp_pos(0.0)
    cx, cy = int(cpx // moving_map.TILE_SIZE), int(cpy // moving_map.TILE_SIZE)
    half = int(np.ceil(max_size / 2 / moving_map.TILE_SIZE)) + 1
    payload = io.BytesIO()
    Image.new("RGBA", (moving_map.TILE_SIZE, moving_map.TILE_SIZE), (85, 105, 125, 255)).save(
        payload, format="PNG"
    )
    cache = moving_map.TileCache(cache_dir)
    for ty in range(cy - half, cy + half + 1):
        for tx in range(cx - half, cx + half + 1):
            cache.put(zoom, tx, ty, moving_map.DEFAULT_STYLE, payload.getvalue())
    moving_map.TileCache._mem.clear()
    moving_map.TileCache._mem_order.clear()


def _renderer(cache_dir, track):
    _seed_tiles(cache_dir, track, 14, moving_map.track_up_working_size(256))
    return moving_map.MovingMapRenderer(
        track,
        zoom=14,
        cache_dir=cache_dir,
        track_color=(255, 60, 30, 255),
        track_width=5,
        marker_radius=7,
    )


def _red_centroid(image: Image.Image) -> tuple[float, float]:
    pixels = np.asarray(image.convert("RGBA"))
    mask = (pixels[:, :, 0] > 170) & (pixels[:, :, 1] < 120) & (pixels[:, :, 2] < 100)
    ys, xs = np.nonzero(mask)
    assert len(xs) > 20
    return float(xs.mean()), float(ys.mean())


def test_track_up_cardinal_rotation_and_exact_output_size(tmp_path):
    track = _eastbound_track()
    renderer = _renderer(tmp_path, track)

    north = renderer.render(0.0, 256, 256, download_missing=False)
    assert moving_map.track_up_working_size(256) == 363
    assert renderer.render_track_up(0.0, 256, heading=None, download_missing=False).tobytes() == north.tobytes()
    assert renderer.render_track_up(0.0, 256, heading=0.0, download_missing=False).tobytes() == north.tobytes()

    north_x, north_y = _red_centroid(north)
    track_up_x, track_up_y = _red_centroid(
        renderer.render_track_up(0.0, 256, heading=90.0, download_missing=False)
    )
    assert north_x > 128.0
    assert abs(north_y - 128.0) < 12.0
    assert track_up_y < 128.0
    assert abs(track_up_x - 128.0) < 12.0

    for heading in (0.0, 90.0, 180.0, 270.0, 45.0):
        image = renderer.render_track_up(0.0, 256, heading=heading, download_missing=False)
        assert image.size == (256, 256)
        assert image.getbbox() == (0, 0, 256, 256)


def test_track_up_keeps_zoom_cache_independent_of_heading(tmp_path):
    track = _eastbound_track()
    renderer = _renderer(tmp_path, track)
    renderer.render_track_up(0.0, 256, heading=35.0, download_missing=False)
    key_35 = renderer._grid_cache_key
    renderer.render_track_up(0.0, 256, heading=215.0, download_missing=False)
    key_215 = renderer._grid_cache_key
    assert key_35 == key_215
    assert key_35[4] == 14


def test_track_map_heading_is_source_aware_in_reference_and_precompute():
    layout = {
        "indicators": {
            "track_map": {
                "enabled": True,
                "source": "fit",
                "map_orientation": "track_up",
            }
        }
    }
    calls = []

    def resolve(field, source, target_dt, indicator_key=None):
        calls.append((field, source, indicator_key))
        return {"gpmf": 90.0, "fit": 270.0}[source]

    reference = prepare_overlay_frame_data(
        layout=layout,
        target_dt=T0,
        start_dt_utc=T0,
        tz_offset_hours=0.0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        resolve_cache_value=resolve,
        fit_field_plan=build_active_fit_field_plan(layout, set()),
    )
    assert reference["map_heading"] == 270.0
    assert calls == [("heading", "fit", "track_map")]

    init_worker(
        640,
        360,
        "",
        layout,
        {"heading_samples": [(T0, 90.0)]},
        fit_data={"heading": [(T0, 270.0)]},
        total_overlay_frames=1,
        target_fps=1.0,
    )
    cache = build_telemetry_cache(
        layout=layout,
        base_dt=T0,
        tz_offset_hours=0.0,
        start_dt_utc=T0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        total_frames=1,
        target_fps=1.0,
        fit_field_plan=build_active_fit_field_plan(layout, {"heading"}),
    )
    assert cache.lookup(0)["map_heading"] == pytest.approx(270.0)

    layout["indicators"]["track_map"]["source"] = "gpmf"
    cache = build_telemetry_cache(
        layout=layout,
        base_dt=T0,
        tz_offset_hours=0.0,
        start_dt_utc=T0,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        total_frames=1,
        target_fps=1.0,
        fit_field_plan=build_active_fit_field_plan(layout, {"heading"}),
    )
    assert cache.lookup(0)["map_heading"] == pytest.approx(90.0)


def test_track_up_schema_and_v6_preset_leave_v5_unchanged():
    assert any(field[0] == "map_orientation" for field in BUILTIN_FIELDS["track_map"])
    with open("presets/cycling_dashboard_v5.json", encoding="utf-8") as handle:
        v5 = json.load(handle)
    with open("presets/cycling_dashboard_v6.json", encoding="utf-8") as handle:
        v6 = json.load(handle)
    assert "map_orientation" not in v5["indicators"]["track_map"]
    assert v6["indicators"]["track_map"]["map_orientation"] == "track_up"
    v6["indicators"]["track_map"].pop("map_orientation")
    v6["preset_name"] = "cycling_dashboard_v5"
    assert v6 == v5
