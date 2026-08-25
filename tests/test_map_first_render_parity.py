"""Regression tests for CPU/AMD map first-render tile readiness."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image

import src.indicators.moving_map as indicator_map
import src.moving_map as moving_map


W, H = 3840, 2160
STYLE = "light_all"
CONFIGURED_ZOOM = 14
REAL_RENDERER = moving_map.MovingMapRenderer


def _fixture() -> tuple[dict, list, datetime, int, int, dict[tuple[int, int], bytes]]:
    start = datetime(2026, 8, 18, 4, 47, tzinfo=timezone.utc)
    track = [
        (start + timedelta(seconds=i), 54.35 + i * 0.00005, 18.62 + i * 0.00005)
        for i in range(12)
    ]
    layout = {
        "version": 6,
        "global": {"text_outline": 1},
        "indicators": {
            "track_map": {
                "enabled": True,
                "x": 86.0,
                "y": 38.0,
                "form": "map",
                "size": 20.0,
                "zoom": CONFIGURED_ZOOM,
                "map_style": STYLE,
                "map_shape": "square",
                "marker_size": 7,
                "marker_color": "#FFFFFF",
                "track_color": "#FF3C1E",
                "track_width": 2,
            }
        },
        "custom_texts": [],
    }
    map_w = int(round(20.0 * W / 100.0))
    plan = indicator_map._map_render_plan(W, map_w, CONFIGURED_ZOOM)
    target = start + timedelta(seconds=5)
    probe = moving_map.MovingMapRenderer(
        track, zoom=plan["effective_zoom"], style=STYLE,
        marker_color=(255, 255, 255, 255), marker_radius=28,
        track_color=(255, 60, 30, 220), track_width=8,
    )
    ts = (target - start).total_seconds()
    cpx, cpy = probe._interp_pos(ts)
    cx, cy = int(cpx // moving_map.TILE_SIZE), int(cpy // moving_map.TILE_SIZE)
    half_w = int(np.ceil(plan["working_size"] / 2 / moving_map.TILE_SIZE)) + 1
    half_h = int(np.ceil(plan["working_size"] / 2 / moving_map.TILE_SIZE)) + 1
    tx1, tx2 = cx - half_w, cx + half_w + 1
    ty1, ty2 = cy - half_h, cy + half_h + 1

    payloads: dict[tuple[int, int], bytes] = {}
    for ty in range(ty1, ty2):
        for tx in range(tx1, tx2):
            color = ((tx * 37) % 256, (ty * 53) % 256, ((tx + ty) * 17) % 256, 255)
            tile = Image.new("RGBA", (moving_map.TILE_SIZE, moving_map.TILE_SIZE), color)
            raw = io.BytesIO()
            tile.save(raw, format="PNG")
            payloads[(tx, ty)] = raw.getvalue()
    return layout, track, target, plan["effective_zoom"], plan["working_size"], payloads


def _seed_cache(cache_dir, payloads, zoom, omit=None):
    cache = moving_map.TileCache(cache_dir)
    for (tx, ty), payload in payloads.items():
        if (tx, ty) != omit:
            cache.put(zoom, tx, ty, STYLE, payload)
    moving_map.TileCache._mem.clear()
    moving_map.TileCache._mem_order.clear()


def _reset_renderer_cache(monkeypatch, cache_dir):
    real_renderer = REAL_RENDERER

    def factory(gps_track, *args, **kwargs):
        return real_renderer(gps_track, *args, cache_dir=cache_dir, **kwargs)

    monkeypatch.setattr(moving_map, "MovingMapRenderer", factory)
    # The test isolates first-render policy; network work is supplied by the
    # local fake below, so the production daemon does not race the fixture.
    monkeypatch.setattr(real_renderer, "background_precache", lambda *args, **kwargs: None)
    indicator_map._render_moving_map_indicator._map_renderers = {}
    moving_map.TileCache._mem.clear()
    moving_map.TileCache._mem_order.clear()


def _cpu_render(layout, track, target):
    cfg = layout["indicators"]["track_map"]
    map_w = int(round(float(cfg["size"]) * W / 100.0))
    raw, *_ = indicator_map._render_moving_map_indicator(
        canvas_w=W,
        canvas_h=H,
        layout=layout,
        font_path="",
        key="track_map",
        value=0.0,
        unit="",
        label="MAP",
        cfg=cfg,
        min_dim=min(W, H),
        outline=0,
        fs=8,
        font=None,
        val_min=0.0,
        val_max=1.0,
        ticks=0,
        thickness=1,
        size_px=map_w,
        ss=1,
        gps_track=track,
        target_dt=target,
        current_position=0.0,
    )
    assert raw is not None
    return raw


def _amd_style_render(layout, track, target):
    raw, bbox = indicator_map.render_map_working_image(
        W, H, layout, "track_map", track, target_dt=target, current_position=0.0
    )
    assert raw is not None
    assert bbox == (2918, 437, 768, 768)
    return raw


def _local_downloader(payloads, calls, fail=False):
    def download(z, x, y, style):
        calls.append((z, x, y, style))
        if fail:
            return None
        return payloads.get((x, y))

    return download


def test_first_render_cpu_and_amd_preparation_match_with_missing_tile(tmp_path, monkeypatch):
    layout, track, target, zoom, _, payloads = _fixture()
    missing = sorted(payloads)[len(payloads) // 2]

    cpu_cache = tmp_path / "cpu"
    cpu_calls = []
    _seed_cache(cpu_cache, payloads, zoom, omit=missing)
    _reset_renderer_cache(monkeypatch, cpu_cache)
    monkeypatch.setattr(moving_map, "_download_tile_raw", _local_downloader(payloads, cpu_calls))
    cpu_raw = _cpu_render(layout, track, target)
    cpu_second = _cpu_render(layout, track, target)
    assert cpu_calls.count((zoom, missing[0], missing[1], STYLE)) == 1
    assert np.array_equal(np.asarray(cpu_raw), np.asarray(cpu_second))

    amd_cache = tmp_path / "amd"
    amd_calls = []
    _seed_cache(amd_cache, payloads, zoom, omit=missing)
    _reset_renderer_cache(monkeypatch, amd_cache)
    monkeypatch.setattr(moving_map, "_download_tile_raw", _local_downloader(payloads, amd_calls))
    amd_raw = _amd_style_render(layout, track, target)

    assert np.array_equal(np.asarray(cpu_raw), np.asarray(amd_raw))
    assert amd_calls.count((zoom, missing[0], missing[1], STYLE)) == 1


def test_first_render_offline_fallback_is_deterministic(tmp_path, monkeypatch):
    layout, track, target, zoom, _, payloads = _fixture()
    missing = sorted(payloads)[len(payloads) // 2]

    cpu_cache = tmp_path / "offline_cpu"
    cpu_calls = []
    _seed_cache(cpu_cache, payloads, zoom, omit=missing)
    _reset_renderer_cache(monkeypatch, cpu_cache)
    monkeypatch.setattr(moving_map, "_download_tile_raw", _local_downloader(payloads, cpu_calls, fail=True))
    cpu_raw = _cpu_render(layout, track, target)

    amd_cache = tmp_path / "offline_amd"
    amd_calls = []
    _seed_cache(amd_cache, payloads, zoom, omit=missing)
    _reset_renderer_cache(monkeypatch, amd_cache)
    monkeypatch.setattr(moving_map, "_download_tile_raw", _local_downloader(payloads, amd_calls, fail=True))
    amd_raw = _amd_style_render(layout, track, target)

    assert np.array_equal(np.asarray(cpu_raw), np.asarray(amd_raw))
    assert cpu_calls.count((zoom, missing[0], missing[1], STYLE)) == 1
    assert amd_calls.count((zoom, missing[0], missing[1], STYLE)) == 1


def test_complete_cache_has_no_first_render_download(tmp_path, monkeypatch):
    layout, track, target, zoom, _, payloads = _fixture()
    calls = []
    cache = tmp_path / "complete"
    _seed_cache(cache, payloads, zoom)
    _reset_renderer_cache(monkeypatch, cache)
    monkeypatch.setattr(moving_map, "_download_tile_raw", _local_downloader(payloads, calls))
    _cpu_render(layout, track, target)
    assert calls == []
