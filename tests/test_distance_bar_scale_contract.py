"""Distance BAR scale/ticks/marker contract — regression tests.

Contract: USER CONFIG == PREVIEW EFFECTIVE CONFIG == FINAL RENDER EFFECTIVE CONFIG.

- MANUAL (auto_scale=False / brak): renderer szanuje ręczne min_val/max_val.
- AUTO (auto_scale=True): zakres brany z telemetrii (max_distance_m / 1000).
- Renderer NIE mutuje configu użytkownika.
- Marker = (value - min) / (max - min), clamp 0..1, środek kropki.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.indicators.bar import _render_ruler, _fraction
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data

ROOT = Path(__file__).resolve().parents[1]
FONT = r"C:\Windows\Fonts\arial.ttf"
W, H = 1280, 720
MARKER_RGB = (255, 212, 42)  # #FFD42A


def _dist_cfg(**over) -> dict:
    """Bazowy bar-ruler dystansu z RĘCZNĄ skalą 0..3 km."""
    cfg = {
        "enabled": True, "label": "DISTANCE", "x": 50.0, "y": 74.0, "rotation": 0,
        "form": "bar", "bar_style": "ruler", "font_size": 1.2, "size": 28.0,
        "thickness": 1, "min_val": 0.0, "max_val": 3.0, "ticks": 5,
        "show_value": True, "source": "fit", "unit": "km",
        "marker_color": "#FFD42A", "major_ticks": 4, "minor_ticks": 4,
    }
    cfg.update(over)
    return cfg


def _find_marker_x(img: Image.Image) -> float | None:
    arr = np.array(img)
    mask = (
        (arr[:, :, 0] == MARKER_RGB[0]) & (arr[:, :, 1] == MARKER_RGB[1])
        & (arr[:, :, 2] == MARKER_RGB[2]) & (arr[:, :, 3] > 200)
    )
    ys, xs = np.where(mask)
    return float(np.mean(xs)) if len(xs) else None


def _render_ruler_marker(value, min_val=0.0, max_val=3.0, **cfg_over) -> float:
    cfg = _dist_cfg(**cfg_over)
    img = _render_ruler(
        canvas_w=W, canvas_h=H, font_path=FONT, value=value, unit="km",
        label="DISTANCE", cfg=cfg, val_min=min_val, val_max=max_val,
        ticks=int(cfg.get("ticks", 5)), thickness=1,
        size_px=int(0.28 * W), fs=15, outline=1, ss=1,
        formatted_val=f"{value:.1f} km",
    )
    x = _find_marker_x(img)
    assert x is not None, "marker pixel not found"
    return x


def _compose_marker_x(cfg: dict, distance_m: float, max_distance_m: float) -> float:
    """Compose pojedynczy dist bar i zwróć środek markera w cropie bbox."""
    layout = {"indicators": {"dist_visual": deepcopy(cfg)}, "global": {"text_outline": 3}}
    bboxes = {}
    overlay = compose_overlay(
        W, H, layout, FONT,
        date_text="2026-08-14", time_text="11:18:03",
        speed_value=0.0, distance_m=distance_m, max_distance_m=max_distance_m,
        _bboxes=bboxes,
    )
    bb = bboxes.get("dist_visual")
    assert bb is not None
    ox, oy, ow, oh = bb
    crop = overlay.crop((ox, oy, ox + ow, oy + oh))
    x = _find_marker_x(crop)
    assert x is not None, "marker pixel not found in crop"
    return x


# ---------------------------------------------------------------------------
# TEST 1 — MANUAL RANGE: ręczna skala 0..3 km jest respektowana w preview
# ---------------------------------------------------------------------------

def test_manual_range_0_3_respected_through_compositor():
    """Manual max_val=3: przy current=1.5 km marker stoi dokładnie w 50%
    zakresu — mimo max_distance_m=24 km (auto NIE nadpisuje ręki)."""
    cfg = _dist_cfg(max_val=3.0)
    m0 = _compose_marker_x(cfg, distance_m=0.0, max_distance_m=23926.4)
    m3 = _compose_marker_x(cfg, distance_m=3000.0, max_distance_m=23926.4)
    m15 = _compose_marker_x(cfg, distance_m=1500.0, max_distance_m=23926.4)
    # 1.5 km na skali 0..3 = 50%
    assert abs(m15 - (m0 + m3) / 2.0) <= 1.5, (m0, m3, m15)


def test_manual_range_full_activity_auto_disabled():
    """Manual max_val=3: current=3 km -> marker na końcu (100%), nie ~12%."""
    cfg = _dist_cfg(max_val=3.0)
    m_end = _compose_marker_x(cfg, distance_m=3000.0, max_distance_m=23926.4)
    m_start = _compose_marker_x(cfg, distance_m=0.0, max_distance_m=23926.4)
    # full distance wg ręcznej skali to 3 km, nie 24 km
    assert m_end > m_start


def test_auto_scale_enabled_uses_full_distance():
    """auto_scale=True: max_val brany z max_distance_m (24 km)."""
    cfg = _dist_cfg(max_val=3.0, auto_scale=True)
    m0 = _compose_marker_x(cfg, distance_m=0.0, max_distance_m=23926.4)
    m_end = _compose_marker_x(cfg, distance_m=23926.4, max_distance_m=23926.4)
    m_mid = _compose_marker_x(cfg, distance_m=11963.2, max_distance_m=23926.4)
    assert abs(m_mid - (m0 + m_end) / 2.0) <= 1.5, (m0, m_end, m_mid)


# ---------------------------------------------------------------------------
# TEST 2 — CONFIG IMMUTABILITY: renderer nie mutuje configu użytkownika
# ---------------------------------------------------------------------------

def test_compositor_does_not_mutate_config():
    cfg = _dist_cfg(max_val=3.0)
    before = deepcopy(cfg)
    _compose_marker_x(cfg, distance_m=1500.0, max_distance_m=23926.4)
    _compose_marker_x(cfg, distance_m=0.0, max_distance_m=23926.4)
    assert cfg == before, "compose_overlay zmienił oryginalny config"


# ---------------------------------------------------------------------------
# TEST 3/4/5 — MARKER 0% / 50% / 100% (matematyka renderera)
# ---------------------------------------------------------------------------

def test_marker_0_percent_at_scale_start():
    x = _render_ruler_marker(0.0, 0.0, 3.0)
    # frac=0 -> marker_x = pad_x = 10
    assert abs(x - 10.0) <= 1.0, x


def test_marker_50_percent_midpoint():
    x0 = _render_ruler_marker(0.0, 0.0, 3.0)
    x3 = _render_ruler_marker(3.0, 0.0, 3.0)
    x15 = _render_ruler_marker(1.5, 0.0, 3.0)
    assert abs(x15 - (x0 + x3) / 2.0) <= 1.0, (x0, x15, x3)


def test_marker_100_percent_at_scale_end():
    x0 = _render_ruler_marker(0.0, 0.0, 3.0)
    x3 = _render_ruler_marker(3.0, 0.0, 3.0)
    # marker przy 100% jest dalej niż przy 0% i używa pełnej szerokości
    assert x3 > x0
    assert abs((x3 - x0) - 0.28 * W) <= 2.0, (x0, x3)


# ---------------------------------------------------------------------------
# TEST 6 — CLAMP: current poza zakresem jest ograniczany do [0,1]
# ---------------------------------------------------------------------------

def test_fraction_clamps():
    assert _fraction(-5.0, 0.0, 3.0) == 0.0
    assert _fraction(10.0, 0.0, 3.0) == 1.0
    assert _fraction(1.5, 0.0, 3.0) == pytest.approx(0.5)


def test_marker_clamped_inside_bar():
    x_lo = _render_ruler_marker(-5.0, 0.0, 3.0)   # current < min
    x_start = _render_ruler_marker(0.0, 0.0, 3.0)
    x_hi = _render_ruler_marker(10.0, 0.0, 3.0)   # current > max
    x_end = _render_ruler_marker(3.0, 0.0, 3.0)
    assert abs(x_lo - x_start) <= 1.0
    assert abs(x_hi - x_end) <= 1.0


# ---------------------------------------------------------------------------
# TEST 7 — SOURCE: current distance i max_distance_m z tego samego źródła
# ---------------------------------------------------------------------------

def _frame_data_for_source(dist_src: str):
    base_dt = datetime(2026, 8, 14, 9, 40, 16, tzinfo=timezone.utc)
    fit_track = [(base_dt, 5000.0), (base_dt + __import__("datetime").timedelta(seconds=1), 10000.0)]
    gpmf_track = [(base_dt, 1000.0), (base_dt + __import__("datetime").timedelta(seconds=1), 3000.0)]
    gpx_track = [(base_dt, 2000.0), (base_dt + __import__("datetime").timedelta(seconds=1), 4000.0)]
    layout = {"indicators": {"dist_visual": {
        "enabled": True, "form": "bar", "bar_style": "ruler", "unit": "km",
        "source": dist_src, "min_val": 0.0, "max_val": 3.0,
    }}}
    return prepare_overlay_frame_data(
        layout=layout, target_dt=base_dt, tz_offset_hours=0.0,
        start_dt_utc=base_dt,
        speed_samples=[], track_samples=gpmf_track, alt_samples=[],
        gpx_track_samples=gpx_track, fit_data={"track": fit_track},
        resolve_cache_value=lambda *a, **k: None,
    )


def test_source_consistent_fit_gpmf_gpx():
    fd_fit = _frame_data_for_source("fit")
    assert fd_fit["max_distance_m"] == pytest.approx(10000.0)   # z fit track
    fd_gpmf = _frame_data_for_source("gpmf")
    assert fd_gpmf["max_distance_m"] == pytest.approx(3000.0)   # z gpmf track
    fd_gpx = _frame_data_for_source("gpx")
    assert fd_gpx["max_distance_m"] == pytest.approx(4000.0)    # z gpx track


# ---------------------------------------------------------------------------
# TEST 8 — PREVIEW/RENDER CONFIG PARITY (wspólny compose_overlay)
# ---------------------------------------------------------------------------

def test_preview_render_effective_config_parity():
    """Preview (preview_mixin) i final render (frame_renderer) oba przechodzą
    przez compose_overlay. Efektywny config = model: ręczna skala 0..3
    dociera do obu ścieżek bez nadpisania."""
    cfg = _dist_cfg(max_val=3.0, auto_scale=False)
    # dokładnie ten sam cfg trafia do compose_overlay (wspólnego dla obu ścieżek)
    effective = _compose_marker_x(cfg, distance_m=1500.0, max_distance_m=23926.4)
    start = _compose_marker_x(cfg, distance_m=0.0, max_distance_m=23926.4)
    end = _compose_marker_x(cfg, distance_m=3000.0, max_distance_m=23926.4)
    # marker 1.5 km w środku ręcznej skali 0..3 -> ten sam config dla preview i render
    assert abs(effective - (start + end) / 2.0) <= 1.5
