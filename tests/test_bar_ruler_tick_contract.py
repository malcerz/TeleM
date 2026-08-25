"""BAR Ruler tick contract + property/preview parity — regression tests.

Contract:
- major_step <= 0 / brak -> tryb COUNT: major_ticks = liczba głównych przedziałów.
- major_step > 0 (JAWNIE zapisany) -> tryb STEP: krok co major_step jednostek.
- minor_ticks = liczba drobnych podziałek między głównymi (działa przy manual i auto).
- auto_scale zmienia WYŁĄCZNIE zakres (min/max), nie konfigurację ticków.
- Dystans FIT/GPMF zawsze w km (metry NIGDY nie jako km).
- Renderer nie mutuje configu; preview i final render widzą ten sam effective range.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.indicators.bar import _render_ruler
from src.indicators.compositor import compose_overlay
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin

W, H = 1280, 720
FONT = r"C:\Windows\Fonts\arial.ttf"
TICK_RGB = (246, 246, 246)  # tick_color #F6F6F6
MARKER_RGB = (255, 212, 42)  # #FFD42A


def _ruler_cfg(**over) -> dict:
    cfg = {
        "enabled": True, "label": "DISTANCE", "x": 50.0, "y": 74.0, "rotation": 0,
        "form": "bar", "bar_style": "ruler", "font_size": 1.2, "size": 28.0,
        "thickness": 1, "min_val": 0.0, "max_val": 3.0, "ticks": 0,
        "show_value": True, "source": "fit", "unit": "km",
        "marker_color": "#FFD42A", "tick_color": "#F6F6F6",
        "track_color": "#F4F4F4", "text_color": "#F4F4F4",
        "major_ticks": 8, "minor_ticks": 4,
    }
    cfg.update(over)
    return cfg


def _render_ruler_img(cfg, value=1.0, val_min=0.0, val_max=3.0):
    return _render_ruler(
        canvas_w=W, canvas_h=H, font_path=FONT, value=value, unit=cfg.get("unit", "km"),
        label=cfg.get("label", "DISTANCE"), cfg=cfg, val_min=val_min, val_max=val_max,
        ticks=int(cfg.get("ticks", 0)), thickness=int(cfg.get("thickness", 1)),
        size_px=int(0.28 * W), fs=15, outline=1, ss=1, formatted_val="1.0 km",
    )


def _tick_runs(img: Image.Image) -> list[int]:
    """Zwraca listę topmost_y dla każdej kolumny ticka (cluster po ciągłych x)."""
    arr = np.array(img)
    mask = (
        (arr[:, :, 0] == TICK_RGB[0]) & (arr[:, :, 1] == TICK_RGB[1])
        & (arr[:, :, 2] == TICK_RGB[2]) & (arr[:, :, 3] > 200)
    )
    runs: list[tuple[int, int]] = []  # (topmost_y, last_x)
    for x in range(arr.shape[1]):
        ys = np.where(mask[:, x])[0]
        if len(ys) == 0:
            continue
        y = int(ys.min())
        if runs and x - runs[-1][1] <= 2:
            prev_y, last_x = runs[-1]
            runs[-1] = (min(prev_y, y), x)
        else:
            runs.append((y, x))
    return [y for y, _ in runs]


def _marker_fraction(img: Image.Image) -> float:
    arr = np.array(img)
    mask = (
        (arr[:, :, 0] == MARKER_RGB[0]) & (arr[:, :, 1] == MARKER_RGB[1])
        & (arr[:, :, 2] == MARKER_RGB[2]) & (arr[:, :, 3] > 200)
    )
    xs = np.where(mask.any(axis=0))[0]
    assert len(xs) > 0, "marker not found"
    x = float(xs.mean())
    return (x - 10.0) / (0.28 * W)  # pad_x=10, width=0.28*W


# ---------------------------------------------------------------------------
# TEST 1 — MAJOR COUNT: major_ticks steruje liczbą podziałów (COUNT mode)
# ---------------------------------------------------------------------------

def test_major_count_controls_divisions():
    img8 = _render_ruler_img(_ruler_cfg(major_step=0, major_ticks=8), val_max=24.0)
    img16 = _render_ruler_img(_ruler_cfg(major_step=0, major_ticks=16), val_max=24.0)
    runs8 = _tick_runs(img8)
    runs16 = _tick_runs(img16)
    # major_ticks=16 -> więcej ticków niż major_ticks=8
    assert len(runs16) > len(runs8), (len(runs8), len(runs16))
    # COUNT mode: 8 przedziałów * 4 minor + 1 -> 33 ticki; 16 -> 65
    assert len(runs8) == 33, len(runs8)
    assert len(runs16) == 65, len(runs16)


# ---------------------------------------------------------------------------
# TEST 2 — MAJOR STEP: jawny major_step>0 = tryb STEP
# ---------------------------------------------------------------------------

def test_major_step_explicit_step_mode():
    img_step2 = _render_ruler_img(_ruler_cfg(major_step=2.0, major_ticks=8), val_max=24.0)
    img_step3 = _render_ruler_img(_ruler_cfg(major_step=3.0, major_ticks=8), val_max=24.0)
    assert _tick_runs(img_step2) != _tick_runs(img_step3), "major_step zmienia podziałki"
    # STEP mode działa niezależnie od major_ticks: major_step=2 i major_ticks=99 -> ten sam raster
    img_same = _render_ruler_img(_ruler_cfg(major_step=2.0, major_ticks=99), val_max=24.0)
    assert _tick_runs(img_step2) == _tick_runs(img_same)


def test_major_step_zero_equals_absent():
    # major_step=0 traktowane jak brak -> COUNT mode (major_ticks)
    a = _render_ruler_img(_ruler_cfg(major_step=0, major_ticks=8), val_max=24.0)
    b = _render_ruler_img(_ruler_cfg(major_ticks=8), val_max=24.0)
    assert _tick_runs(a) == _tick_runs(b)


# ---------------------------------------------------------------------------
# TEST 3 — HIDDEN STEP REGRESSION: nowy Ruler nie ma ukrytego major_step
# ---------------------------------------------------------------------------

def test_new_ruler_has_no_hidden_major_step():
    """_create_indicator nie ustawia już major_step>0 dla dystansu/temp."""
    class Dummy(IndicatorMixin):
        def __init__(self):
            self.telemetry = type("T", (), {
                "fit_data": {}, "speed_samples": [], "track_samples": [], "alt_samples": [],
                "iso_samples": [], "exposure_samples": [], "temperature_samples": [],
                "gpx_speed_samples": [], "gpx_track_samples": [], "gpx_alt_samples": [],
                "gpx_hr_samples": [], "gpx_cad_samples": [], "gpx_power_samples": [],
                "gpx_atemp_samples": [], "gpx_heading_samples": [], "gpx_slope_samples": [],
                "accel_x_samples": [], "accel_y_samples": [], "accel_z_samples": [],
                "accel_magnitude_samples": [], "gyro_x_samples": [], "gyro_y_samples": [],
                "gyro_z_samples": [], "gyro_magnitude_samples": [], "heading_samples": [],
                "slope_samples": [],
            })()
            self.layout = {"indicators": {}}
            self._selected_stream_key = ""

    d = Dummy()
    for key in ("dist_visual", "dist_text", "fit_distance_text", "alt_text"):
        d._create_indicator(key)
        cfg = d.layout["indicators"][key]
        step = cfg.get("major_step", 0)
        assert float(step or 0) <= 0, f"{key}: ukryty major_step={step} ignoruje major_ticks"


def test_major_ticks_work_without_major_step():
    # config bez major_step -> major_ticks działa (COUNT)
    img8 = _render_ruler_img(_ruler_cfg(major_ticks=8), val_max=24.0)
    img16 = _render_ruler_img(_ruler_cfg(major_ticks=16), val_max=24.0)
    assert _tick_runs(img8) != _tick_runs(img16)


# ---------------------------------------------------------------------------
# TEST 4 — MINOR TICKS działają przy manual i auto
# ---------------------------------------------------------------------------

def test_minor_ticks_change_rendering():
    img4 = _render_ruler_img(_ruler_cfg(minor_ticks=4), val_max=3.0)
    img8 = _render_ruler_img(_ruler_cfg(minor_ticks=8), val_max=3.0)
    runs4 = _tick_runs(img4)
    runs8 = _tick_runs(img8)
    assert len(runs8) > len(runs4), (len(runs4), len(runs8))
    # 8 major * 4 minor + 1 = 33; 8 major * 8 minor + 1 = 65
    assert len(runs4) == 33, len(runs4)
    assert len(runs8) == 65, len(runs8)


# ---------------------------------------------------------------------------
# TEST 5 — AUTO SCALE + TICKS: auto_scale zmienia zakres, nie ticki
# ---------------------------------------------------------------------------

def _compose_marker_fraction(cfg, distance_m, max_distance_m):
    layout = {"indicators": {"dist_visual": deepcopy(cfg)}, "global": {"text_outline": 3}}
    bboxes = {}
    overlay = compose_overlay(
        W, H, layout, FONT, "2026-08-14", "11:18:03", 0.0, distance_m, max_distance_m,
        None, None, None, None, None, None, indicator_values={}, max_speed_kmh=None,
        _bboxes=bboxes,
    )
    bb = bboxes.get("dist_visual")
    assert bb is not None
    crop = overlay.crop((bb[0], bb[1], bb[0] + bb[2], bb[1] + bb[3]))
    arr = np.array(crop)
    mask = (
        (arr[:, :, 0] == MARKER_RGB[0]) & (arr[:, :, 1] == MARKER_RGB[1])
        & (arr[:, :, 2] == MARKER_RGB[2]) & (arr[:, :, 3] > 200)
    )
    xs = np.where(mask.any(axis=0))[0]
    assert len(xs) > 0
    x = float(xs.mean())
    # crop to bar: width ~ 0.28*1280, pad 10 -> fraction
    return (x - 10.0) / (0.28 * W)


def test_auto_scale_changes_range_not_ticks():
    cfg = _ruler_cfg(max_val=3.0, auto_scale=True, major_ticks=8, minor_ticks=4)
    # AUTO: effective max = 24 km (24000 m / 1000)
    frac_mid = _compose_marker_fraction(cfg, distance_m=12000.0, max_distance_m=24000.0)
    assert abs(frac_mid - 0.5) < 0.02, frac_mid  # 12 km na skali 0..24 -> 50%
    # ticki pozostają konfigurowalne pod AUTO: major_ticks 8 vs 16 -> różne ticki
    img8 = _render_ruler_img(_ruler_cfg(auto_scale=True, major_ticks=8), val_max=24.0)
    img16 = _render_ruler_img(_ruler_cfg(auto_scale=True, major_ticks=16), val_max=24.0)
    assert _tick_runs(img8) != _tick_runs(img16)


# ---------------------------------------------------------------------------
# TEST 6 — MANUAL SCALE + TICKS
# ---------------------------------------------------------------------------

def test_manual_scale_and_ticks():
    cfg = _ruler_cfg(auto_scale=False, min_val=0.0, max_val=3.0, major_ticks=6, minor_ticks=4)
    frac = _compose_marker_fraction(cfg, distance_m=1500.0, max_distance_m=24000.0)
    assert abs(frac - 0.5) < 0.02, frac  # 1.5 km na ręcznej skali 0..3 -> 50%
    # 6 major * 4 minor + 1 = 25 ticków
    img = _render_ruler_img(cfg, val_min=0.0, val_max=3.0)
    assert len(_tick_runs(img)) == 25, len(_tick_runs(img))


# ---------------------------------------------------------------------------
# TEST 7 — UNIT CONVERSION: metry nigdy nie jako km
# ---------------------------------------------------------------------------

def test_unit_conversion_meters_never_as_km():
    # max_distance_m=10129.14 -> effective max = 10.129 km, NIE 10129 km
    cfg = _ruler_cfg(max_val=100.0, auto_scale=True, major_ticks=8, minor_ticks=4, unit="km")
    # wartość = pełny dystans (10.129 km) -> marker na ~100% (koniec skali)
    frac_end = _compose_marker_fraction(cfg, distance_m=10129.14, max_distance_m=10129.14)
    assert frac_end > 0.95, frac_end
    # wartość = 5.06 km -> ~50%
    frac_half = _compose_marker_fraction(cfg, distance_m=5064.57, max_distance_m=10129.14)
    assert abs(frac_half - 0.5) < 0.03, frac_half


def test_fit_registered_distance_is_km():
    """register_fit_fields zapisuje max_val dystansu w km (nie metrach)."""
    from src.gui.telemetry_manager import TelemetryDataManager

    class _FD(dict):
        def __init__(self, data, catalog):
            super().__init__(data)
            self.field_catalog = catalog

    tm = TelemetryDataManager(interpolate_fn=lambda *a, **k: None)
    tm.fit_data = _FD(
        {"distance": [(0.0, 0.0), (1.0, 10129.14)]},
        {"distance": {"display_name": "Distance", "unit": "m"}},
    )
    layout = {"indicators": {}}
    tm.register_fit_fields(layout, {})
    cfg = layout["indicators"]["fit_distance_text"]
    assert cfg["unit"] == "km"
    assert cfg["max_val"] == pytest.approx(10.12914, abs=1e-3), cfg["max_val"]
    assert cfg["min_val"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TEST 8 — PROPERTY/MAIN PREVIEW PARITY (ten sam effective range)
# ---------------------------------------------------------------------------

def test_parity_preview_and_render_same_config():
    """Ten sam config -> compose_overlay daje identyczny marker (preview == render)."""
    cfg = _ruler_cfg(auto_scale=True, major_ticks=8, minor_ticks=4)
    f1 = _compose_marker_fraction(cfg, distance_m=6000.0, max_distance_m=12000.0)
    f2 = _compose_marker_fraction(cfg, distance_m=6000.0, max_distance_m=12000.0)
    assert abs(f1 - f2) < 1e-9
    # config nie jest mutowany przez compose_overlay
    before = deepcopy(cfg)
    _compose_marker_fraction(cfg, distance_m=6000.0, max_distance_m=12000.0)
    assert cfg == before


# ---------------------------------------------------------------------------
# TEST 9 — PROPERTY LIVE CHANGE: major_ticks N -> N+1 zmienia tylko ticki
# ---------------------------------------------------------------------------

def test_live_change_major_ticks_only_ticks():
    img8 = _render_ruler_img(_ruler_cfg(major_ticks=8), val_max=3.0)
    img9 = _render_ruler_img(_ruler_cfg(major_ticks=9), val_max=3.0)
    assert _tick_runs(img8) != _tick_runs(img9)  # ticki się zmieniają
    # marker dla tej samej wartości pozostaje w tym samym miejscu
    m8 = _marker_fraction(_render_ruler_img(_ruler_cfg(major_ticks=8), value=1.5, val_max=3.0))
    m9 = _marker_fraction(_render_ruler_img(_ruler_cfg(major_ticks=9), value=1.5, val_max=3.0))
    assert abs(m8 - m9) < 1e-6, (m8, m9)
