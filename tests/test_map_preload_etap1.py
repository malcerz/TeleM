"""ETAP MAP PRELOAD — równoległe ładowanie mapy podczas GPMF.

Wymagane testy:
  TEST 1  preload startuje przy Wczytaj (worker uruchomiony, nie czeka na GPMF)
  TEST 2  FIT bounds -> MapContext bounds/center
  TEST 3  multi-file + jeden FIT -> bounds obejmują całą aktywność FIT
  TEST 4  overview zoom -> duży bounds zmniejsza szczegółowość (limit tiles)
  TEST 5  cache hit -> network/download = 0 (mapa z cache)
  TEST 6  cache style -> standard z/x/y != satellite z/x/y (osobne wpisy)
  TEST 7  satellite -> właściwy provider generuje nowy obraz
  TEST 8  placeholder -> niegotowa mapa renderuje placeholder z właściwym bbox
  TEST 9  progress -> required=20 ready=10 -> 50%
  TEST 10 stale job -> stary job nie nadpisuje nowego (generation)
  TEST 11 error -> stan błędu bez nieskończonego loading
  TEST 12 no FIT -> fallback GPX / GPMF GPS
"""

from __future__ import annotations

import io
import os
import sys
import time

os.environ.setdefault("TELEM_OFFLINE", "1")

import pytest

from datetime import datetime, timedelta

from src.gui.map_context import MapContext
from src.gui.map_preload import MapPreloadWorker, compute_map_geometry
from src.moving_map import (
    TileCache,
    bounds_from_track,
    get_shared_tile_cache,
    overview_zoom_for,
    download_tile_shared,
)


def _dt(hms):
    h, m, s = hms.split(":")
    return datetime(2026, 8, 14, int(h), int(m), int(float(s)))


def _track(n=200, lat0=52.2, lon0=20.9, dlat=0.001, dlon=0.002):
    t0 = _dt("11:00:00")
    return [(t0 + timedelta(seconds=i), lat0 + i * dlat, lon0 + i * dlon) for i in range(n)]


def _fake_png(size=8):
    try:
        from PIL import Image
    except ImportError:
        return b""
    img = Image.new("RGBA", (size, size), (120, 140, 160, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _seed_plan_tiles(plan, style):
    cache = get_shared_tile_cache()
    data = _fake_png()
    for z, x, y in plan:
        cache.put(z, x, y, style, data)


class TestPreloadGeometry:
    def test_1_preload_starts_worker_and_does_not_wait_for_gpmf(self):
        """MapPreloadWorker.start() runs on a background thread (concurrent)."""
        ctx = MapContext()
        ctx.reset(provider="light_all", generation=1)
        track = _track(300)
        geom = compute_map_geometry(track, max_tiles=16)
        _seed_plan_tiles(geom["tile_plan"], "light_all")
        done = []
        worker = MapPreloadWorker(
            ctx, track, provider="light_all", generation=1,
            done_cb=lambda ok, msg: done.append((ok, msg)),
        )
        worker.start()
        # worker is alive (concurrent) — it must not block the caller
        assert worker.is_alive
        # wait for completion (bounded)
        deadline = time.time() + 20
        while worker.is_alive and time.time() < deadline:
            time.sleep(0.05)
        assert ctx.snapshot()["status"] == "ready"
        assert done and done[0][0] is True

    def test_2_fit_bounds_from_track(self):
        """FIT GPS track -> MapContext bounds/center."""
        track = _track(500)
        geom = compute_map_geometry(track, max_tiles=16)
        assert geom["bounds"] is not None
        min_lat, min_lon, max_lat, max_lon = geom["bounds"]
        assert min_lat < max_lat and min_lon < max_lon
        assert geom["center"] == pytest.approx(
            ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)
        )

    def test_3_multifile_one_fit_full_activity_bounds(self):
        """3 MP4 + 1 FIT: bounds obejmują CAŁĄ aktywność FIT, nie tylko clip1."""
        # Symulacja trasy całej aktywności (clip1 09:40, clip2 11:18, clip3 11:32)
        t0 = _dt("09:40:11")
        track = [
            (t0 + timedelta(seconds=i * 10), 52.0 + i * 0.001, 20.0 + i * 0.002)
            for i in range(1000)
        ]
        geom = compute_map_geometry(track, max_tiles=16)
        min_lat, min_lon, max_lat, max_lon = geom["bounds"]
        # Obejmuje początek (clip1) i koniec (clip3) aktywności
        assert min_lat <= track[0][1] <= max_lat
        assert min_lat <= track[-1][1] <= max_lat
        assert min_lon <= track[0][2] <= max_lon
        assert min_lon <= track[-1][2] <= max_lon

    def test_4_overview_zoom_bounded(self):
        """Duży bounds -> algorytm zmniejsza zoom, by liczba tiles była ograniczona."""
        # Bardzo duży obszar (np. 5° x 5°)
        bounds = (50.0, 18.0, 55.0, 23.0)
        limit = 16
        zoom = overview_zoom_for(bounds, max_tiles=limit)
        from src.moving_map import _tile_count_for_bounds
        count = _tile_count_for_bounds(bounds, zoom)
        assert count <= limit, f"zoom {zoom} -> {count} tiles > limit {limit}"
        assert zoom >= 3

    def test_5_cache_hit_no_network(self):
        """Jeżeli overview tiles są w cache -> download = 0 (mapa z cache)."""
        cache = get_shared_tile_cache()
        # clear relevant entries: write a fake tile first, then read
        data = _fake_png()
        cache.put(10, 1, 1, "light_all", data)
        t0 = time.perf_counter()
        img = download_tile_shared(10, 1, 1, "light_all")
        dt = time.perf_counter() - t0
        assert img is not None
        # must be served from cache (fast, no 0.15s fair-use delay)
        assert dt < 0.05

    def test_6_cache_style_distinct(self):
        """standard z/x/y i satellite z/x/y to OSOBNE wpisy cache."""
        cache = get_shared_tile_cache()
        data_a = _fake_png()
        data_b = _fake_png()
        cache.put(10, 2, 2, "light_all", data_a)
        cache.put(10, 2, 2, "satellite", data_b)
        # distinct namespace -> both retrievable under their own style
        assert cache.get(10, 2, 2, "light_all") is not None
        assert cache.get(10, 2, 2, "satellite") is not None
        # a missing style must NOT return the other style's tile
        assert cache.get(10, 2, 2, "dark_all") is None

    def test_7_satellite_provider_generates_new_image(self):
        """Zmiana provider na satellite -> nowy job/obraz w context."""
        ctx = MapContext()
        track = _track(200)
        geom = compute_map_geometry(track, max_tiles=16)
        _seed_plan_tiles(geom["tile_plan"], "satellite")
        ctx.reset(provider="satellite", generation=7)
        worker = MapPreloadWorker(
            ctx, track, provider="satellite", generation=7,
            done_cb=lambda ok, msg: None,
        )
        worker.start()
        deadline = time.time() + 20
        while worker.is_alive and time.time() < deadline:
            time.sleep(0.05)
        snap = ctx.snapshot()
        assert snap["status"] == "ready"
        assert snap["provider"] == "satellite"
        assert snap["generation_id"] == 7

    def test_8_placeholder_has_correct_bbox(self):
        """Niegotowa mapa -> placeholder z właściwym rozmiarem (bbox)."""
        from src.indicators.map_prepare import render_map_placeholder
        img = render_map_placeholder(180, 180, progress=0.5, loaded=10, required=20)
        assert img is not None
        assert img.size == (180, 180)

    def test_9_progress_real(self):
        """required=20, loaded=10 -> progress=0.5."""
        ctx = MapContext()
        ctx.reset(provider="light_all", generation=1)
        ctx.set_geometry("fit", _track(10), (1, 1, 2, 2), (1.5, 1.5), 10, 20)
        ctx.set_progress(10, 20)
        assert ctx.snapshot()["progress"] == pytest.approx(0.5)
        assert ctx.snapshot()["loaded_tiles"] == 10
        assert ctx.snapshot()["required_tiles"] == 20

    def test_10_stale_job_cannot_overwrite_new(self):
        """Stary job (Standard) kończy się po wyborze Satellite -> nie nadpisuje."""
        ctx = MapContext()
        # Job A (standard, gen 1) starts
        ctx.reset(provider="light_all", generation=1)
        # User switches to satellite -> generation bump + new reset
        ctx.reset(provider="satellite", generation=2)
        # Job A finishes late -> its generation-guarded set_ready(gen=1) is IGNORED
        ctx.set_ready(generation=1)
        snap = ctx.snapshot()
        assert snap["generation_id"] == 2
        assert snap["provider"] == "satellite"
        assert snap["status"] == "preparing", (
            "stale job must not mark the new context ready"
        )
        # The NEW satellite job (gen 2) finishing marks it ready
        ctx.set_ready(generation=2)
        assert ctx.snapshot()["status"] == "ready"

    def test_11_error_state(self):
        """Błąd tiles -> status error (bez nieskończonego loading)."""
        ctx = MapContext()
        ctx.reset(provider="light_all", generation=1)
        ctx.set_error("Nie można pobrać mapy")
        snap = ctx.snapshot()
        assert snap["status"] == "error"
        assert "mapy" in (snap["error"] or "")
        # renderer shows error placeholder (no infinite loading)
        from src.indicators.map_prepare import render_map_placeholder
        img = render_map_placeholder(120, 120, error="Nie udało się wczytać mapy")
        assert img is not None

    def test_12_no_fit_gpmf_gps_fallback(self):
        """Bez FIT -> fallback GPX/GPMF GPS (ten sam mechanizm geometryczny)."""
        # Symulacja: GPMF GPS track (source="gpmf")
        gpmf_track = _track(120, lat0=51.0, lon0=21.0)
        geom = compute_map_geometry(gpmf_track, max_tiles=16)
        assert geom["bounds"] is not None
        assert geom["center"] is not None
        # MapContext can be driven with source="gpmf" and still produce bounds
        ctx = MapContext()
        ctx.gps_source = "gpmf"
        ctx.reset(provider="light_all", generation=3)
        _seed_plan_tiles(geom["tile_plan"], "light_all")
        worker = MapPreloadWorker(
            ctx, gpmf_track, provider="light_all", generation=3,
            done_cb=lambda ok, msg: None,
        )
        worker.start()
        deadline = time.time() + 20
        while worker.is_alive and time.time() < deadline:
            time.sleep(0.05)
        assert ctx.snapshot()["status"] == "ready"
        assert ctx.snapshot()["gps_source"] == "gpmf"


class TestMapContextUnit:
    def test_context_snapshot_and_reset(self):
        ctx = MapContext()
        ctx.reset(provider="satellite", generation=5)
        snap = ctx.snapshot()
        assert snap["status"] == "preparing"
        assert snap["provider"] == "satellite"
        assert snap["generation_id"] == 5
        assert snap["progress"] == 0.0

    def test_is_ready_provider_matches(self):
        ctx = MapContext()
        ctx.reset(provider="light_all", generation=1)
        ctx.set_geometry("fit", [], (1, 1, 2, 2), (1.5, 1.5), 10, 5)
        ctx.set_progress(5, 5)
        ctx.set_ready()
        assert ctx.is_ready("light_all") is True
        assert ctx.is_ready("satellite") is False
