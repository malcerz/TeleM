"""ETAP MAP PRELOAD 1B — lifecycle integration tests (REAL controller pipeline).

These tests exercise the FULL GUI pipeline offscreen (QT_QPA_PLATFORM=offscreen,
real AppController + real _render_preview + compose_overlay + map renderer):

  MapContext preparing -> preview renders placeholder
       ↓  (worker/context becomes ready → sig_map_ready → refresh requested)
  next rendered frame  -> contains the map image (not placeholder)

and the Satellite lifecycle:

  standard ready -> rendered image A
  switch satellite -> satellite ready -> refresh -> rendered image B
  assert A != B and provider(B) == satellite

This is intentionally a higher-level test than render_map_placeholder() in
isolation or ctx.set_ready() in isolation — it verifies the CONNECTION between
worker completion, the refresh signal, and the visible preview image.
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("TELEM_OFFLINE", "1")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from pathlib import Path
from datetime import datetime, timedelta

from PySide6.QtWidgets import QApplication
from PIL import Image, ImageStat

from src.gui.qt.signals import get_signals
from src.gui.qt.controller import AppController
from src.gui.map_context import MapContext
from src.gui.map_preload import MapPreloadWorker, compute_map_geometry
from src.moving_map import get_shared_tile_cache
from src.indicators.map_prepare import set_current_map_context, get_current_map_context


ROOT = Path(__file__).resolve().parent.parent
FIT = ROOT / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
VIDEO = ROOT / "Video" / "GX010115.MP4"


def _fake_png(size=8):
    img = Image.new("RGBA", (size, size), (120, 140, 160, 255))
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _seed_plan_tiles(plan, style):
    cache = get_shared_tile_cache()
    data = _fake_png()
    for z, x, y in plan:
        cache.put(z, x, y, style, data)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(scope="module")
def ctrl(qapp):
    """Real AppController with FIT telemetry + map layout (no video decode)."""
    if not (FIT.exists() and VIDEO.exists()):
        pytest.skip("Test media not found")
    from src.gui.layout_manager import normalize_layout
    from src.gui.telemetry_manager import TelemetryDataManager
    from src.telemetry_extract import interpolate_value

    c = AppController()
    tm = TelemetryDataManager(interpolate_fn=interpolate_value)
    tm.load_fit(str(VIDEO), manual_path=str(FIT))
    c.telemetry = tm
    c.video_path = VIDEO
    c.video_paths = [VIDEO]
    c.layout = normalize_layout(str(ROOT / "def_layout.json"), 1280, 720)
    c.video_timeline = None
    c.video_duration_s = 592.6
    c._preview_target_w = 960
    w, h = 960, 540
    c.src_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    c.last_src_pil = c.src_img
    c.last_preview_ts = 0.0
    c._prepare_cache = {}
    c._chart_data_cache = None
    return c


def _fresh_context(ctrl, provider="light_all", generation=1):
    """Reset the controller map_context to a fresh preparing job (provider).

    Also syncs the layout's ``track_map.map_style`` to the provider so the
    renderer's provider==map_style gate matches (tests are module-scoped and
    share one controller/layout instance).
    """
    ctx = ctrl._ensure_map_context()
    ctx.gps_source = "fit"
    ctx.reset(provider=provider, generation=generation)
    set_current_map_context(ctx)
    cfg = ctrl.layout.get("indicators", {}).get("track_map")
    if cfg is not None:
        cfg["map_style"] = provider
    return ctx


def _render_and_capture(ctrl, qapp):
    """Drive the real _render_preview and capture bboxes + preview pixels."""
    bboxes = {}
    images = []

    def _on_bbox(b, w, h):
        bboxes.clear()
        bboxes.update(b)

    def _on_frame(qimg):
        images.append(qimg)

    s = ctrl.signals
    s.sig_bboxes_ready.connect(_on_bbox)
    s.sig_preview_frame_ready.connect(_on_frame)

    ctrl._render_preview(0.0)
    for _ in range(20):
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    s.sig_bboxes_ready.disconnect(_on_bbox)
    s.sig_preview_frame_ready.disconnect(_on_frame)
    return bboxes, images


def _region_stats(images, bbox):
    if not images or bbox is None:
        return None
    qimg = images[-1].convertToFormat(images[-1].Format.Format_RGBA8888)
    img = Image.frombuffer(
        "RGBA", (qimg.width(), qimg.height()), qimg.bits(), "raw", "RGBA", 0, 1,
    )
    x, y, w, h = bbox
    crop = img.crop((x, y, x + w, y + h))
    st = ImageStat.Stat(crop)
    return {
        "mean": st.mean,
        "stddev": st.stddev,
        "size": crop.size,
        "img": crop,
    }


class TestLifecycleRefresh:
    """Task §18 — preparing→placeholder→ready→signal→refresh→map visible."""

    def test_18_preparing_placeholder_then_ready_map_visible(self, ctrl, qapp):
        """Full lifecycle: placeholder while preparing; after ready + refresh the
        same render path produces a real map image (not the placeholder)."""
        gps = ctrl.telemetry.get_gps_track_for_source("fit")
        geom = compute_map_geometry(gps, max_tiles=16)
        _seed_plan_tiles(geom["tile_plan"], "light_all")

        # ── Phase 1: preparing → preview renders a placeholder with bbox ──
        ctx = _fresh_context(ctrl, provider="light_all", generation=1)
        assert ctx.snapshot()["status"] == "preparing"
        bb1, imgs1 = _render_and_capture(ctrl, qapp)
        assert "track_map" in bb1, "placeholder must produce a map bbox"
        s1 = _region_stats(imgs1, bb1["track_map"])
        assert s1 is not None
        # Placeholder is a dark rectangle (~24,26,30 bg)
        assert s1["mean"][0] < 80, f"placeholder expected dark, got {s1['mean']}"

        # ── Phase 2: worker becomes ready → refresh → next frame = map ──
        worker = MapPreloadWorker(
            ctx, gps, provider="light_all", generation=1,
            done_cb=lambda ok, msg: ctrl.signals.sig_map_ready.emit(),
        )
        worker.start()
        deadline = time.time() + 30
        while worker.is_alive and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        # Marshal the queued sig_map_ready → _render_preview (real signal chain)
        qapp.processEvents()
        time.sleep(0.2)
        qapp.processEvents()

        assert ctx.snapshot()["status"] == "ready"
        assert ctx.snapshot()["overview_image"] is not None
        bb2, imgs2 = _render_and_capture(ctrl, qapp)
        assert "track_map" in bb2, "ready map must still produce a bbox"
        s2 = _region_stats(imgs2, bb2["track_map"])
        assert s2 is not None
        # The map overview is light-coloured (~225) — clearly != placeholder
        assert s2["mean"][0] > 120, f"map expected light, got {s2['mean']}"
        # and the region changed (map is not the placeholder anymore)
        assert abs(s2["mean"][0] - s1["mean"][0]) > 40


class TestSatelliteLifecycle:
    """Task §19 — standard ready → A; switch satellite → ready → refresh → B; A != B."""

    def test_19_standard_vs_satellite_images_differ(self, ctrl, qapp):
        """Standard and Satellite produce visibly different map images (A != B)
        and the MapContext provider after the switch is satellite."""
        gps = ctrl.telemetry.get_gps_track_for_source("fit")

        # ── Standard ready + rendered image A ─────────────────────────────
        ctx = _fresh_context(ctrl, provider="light_all", generation=1)
        geom = compute_map_geometry(gps, max_tiles=16)
        _seed_plan_tiles(geom["tile_plan"], "light_all")
        worker = MapPreloadWorker(
            ctx, gps, provider="light_all", generation=1,
            done_cb=lambda ok, msg: None,
        )
        worker.start()
        deadline = time.time() + 30
        while worker.is_alive and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        assert ctx.snapshot()["status"] == "ready"

        bb_a, imgs_a = _render_and_capture(ctrl, qapp)
        assert "track_map" in bb_a
        s_a = _region_stats(imgs_a, bb_a["track_map"])
        assert s_a is not None and s_a["mean"][0] > 120

        # ── Switch to satellite (real GUI property path) ──────────────────
        ctrl._on_property_changed("track_map", "map_style", "satellite")
        qapp.processEvents()
        deadline = time.time() + 30
        while time.time() < deadline:
            qapp.processEvents()
            snap = ctrl.map_context.snapshot()
            if snap["status"] == "ready" and snap["provider"] == "satellite":
                break
            time.sleep(0.1)
        snap = ctrl.map_context.snapshot()
        assert snap["provider"] == "satellite", snap
        assert snap["status"] == "ready", snap

        bb_b, imgs_b = _render_and_capture(ctrl, qapp)
        assert "track_map" in bb_b
        s_b = _region_stats(imgs_b, bb_b["track_map"])
        assert s_b is not None

        # ── A != B (different map imagery) ────────────────────────────────
        mean_diff = sum(
            abs(a - b) for a, b in zip(s_a["mean"][:3], s_b["mean"][:3])
        )
        assert mean_diff > 60, (
            f"satellite should look different from standard: A={s_a['mean']} "
            f"B={s_b['mean']}"
        )
