"""Intel final HUD: compass / lean per-frame updates and altitude auto scale.

The Intel exporter runs in the GUI process and builds the per-frame cache with
telemetry_precompute.build_telemetry_cache, whose heading and IMU-roll stages
read WORKER_CACHE.  Without initialising WORKER_CACHE for the export, compass
and lean resolve to None (frozen widgets) or to another project's data.
"""
from __future__ import annotations

import inspect
import math
from datetime import datetime, timedelta, timezone

import pytest

from src.ffmpeg import frame_renderer
from src.ffmpeg import intel_native_exporter
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, _worker_lean_roll, init_worker
from src.telemetry_precompute import build_telemetry_cache

BASE = datetime(2026, 10, 15, 13, 3, 50, tzinfo=timezone.utc)
FPS = 30.0
FRAMES = 300


def _dt(s: float) -> datetime:
    return BASE + timedelta(seconds=s)


def _layout():
    return {
        "indicators": {
            "compass": {"enabled": True, "form": "gauge", "source": "gpmf"},
            "lean_indicator": {"enabled": True, "form": "lean", "source": "gyro", "axis": "y"},
            "alt_text": {"enabled": True, "form": "bar", "source": "fit", "auto_scale": True,
                         "min_val": 0.0, "max_val": 1000.0, "decimals": 0},
        }
    }


def _field_samples():
    heading = [(_dt(i * 0.1), (i * 3.0) % 360.0) for i in range(120)]
    accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z = [], [], [], [], [], []
    for i in range(2000):  # 200 Hz, 10 s, tilting left/right
        t = _dt(i / 200.0)
        a = math.radians(25.0 * math.sin(i / 200.0))
        for lst, v in ((accel_x, 9.81 * math.sin(a)), (accel_y, 9.81 * math.sin(a)),
                       (accel_z, 9.81 * math.cos(a)), (gyro_x, 0.0), (gyro_y, 0.0), (gyro_z, 0.0)):
            lst.append((t, v))
    return {
        "heading_samples": heading,
        "accel_x_samples": accel_x, "accel_y_samples": accel_y, "accel_z_samples": accel_z,
        "gyro_x_samples": gyro_x, "gyro_y_samples": gyro_y, "gyro_z_samples": gyro_z,
    }


FIT = {"alt": [(_dt(i), 100.0 + i * 0.5) for i in range(20)]}


def _build(layout):
    return build_telemetry_cache(
        layout=layout, base_dt=BASE, tz_offset_hours=2.0, start_dt_utc=BASE,
        speed_samples=[], track_samples=[], alt_samples=[], fit_data=FIT,
        resolve_cache_value=_resolve_cache_value, total_frames=FRAMES, target_fps=FPS,
        _range_cache={"max_distance_m": 0.0})


def _init(layout, field_samples):
    init_worker(2560, 1440, "Arial", layout, field_samples, fit_data=FIT, start_dt_utc=BASE,
                target_fps=FPS, total_overlay_frames=FRAMES, skip_chart_build=True)


@pytest.fixture(autouse=True)
def _clean_worker_cache():
    WORKER_CACHE.clear()
    yield
    WORKER_CACHE.clear()


def _series(cache, key):
    return [cache.lookup(i)["extra_indicators"][key][0] for i in range(FRAMES)]


def test_uninitialised_worker_cache_freezes_compass_and_lean():
    """Root cause reproduction (pre-fix Intel ordering)."""
    cache = _build(_layout())
    assert set(_series(cache, "compass")) == {None}
    assert set(_series(cache, "lean_indicator")) == {None}


def test_initialised_worker_cache_updates_compass_and_lean_per_frame():
    layout = _layout()
    _init(layout, _field_samples())
    cache = _build(layout)
    compass = _series(cache, "compass")
    lean = _series(cache, "lean_indicator")
    assert None not in compass[:FRAMES // 2]
    assert len({round(v, 3) for v in compass if v is not None}) > 100
    assert len({round(v, 3) for v in lean if v is not None}) > 100
    # consecutive frames move (not stuck on the first sample)
    assert compass[10] != compass[11] and lean[10] != lean[11]


def test_intel_exporter_initialises_worker_cache_before_precompute():
    src = inspect.getsource(intel_native_exporter.export_intel_native_d3d11)
    init_at = src.index("init_worker(*_hud_init_args(None), skip_chart_build=True)")
    build_at = src.index("telemetry_cache = build_telemetry_cache(")
    assert init_at < build_at
    assert "init_args = _hud_init_args(telemetry_cache)" in src


def test_lean_roll_cache_is_bound_to_current_field_samples():
    first = _field_samples()
    WORKER_CACHE["field_samples"] = {}
    assert _worker_lean_roll("y") == []  # IMU-less call must not poison later projects
    WORKER_CACHE["field_samples"] = first
    timeline = _worker_lean_roll("y")
    assert timeline
    other = _field_samples()
    other["accel_x_samples"] = [(t, -v) for t, v in other["accel_x_samples"]]
    other["accel_y_samples"] = [(t, -v) for t, v in other["accel_y_samples"]]
    WORKER_CACHE["field_samples"] = other
    assert _worker_lean_roll("y") != timeline


def test_init_worker_drops_previous_export_state():
    WORKER_CACHE["_lean_roll"] = {"y_0.00": [(_dt(0), 42.0)]}
    WORKER_CACHE["_prev_frame_data"] = {"x": 1}
    WORKER_CACHE["_prev_atlas_img"] = object()
    _init(_layout(), {})
    for key in ("_lean_roll", "_prev_frame_data", "_prev_atlas_img"):
        assert key not in WORKER_CACHE


def test_altitude_auto_scale_reaches_intel_full_canvas_compositor(monkeypatch):
    layout = _layout()
    _init(layout, _field_samples())
    cache = _build(layout)
    assert cache.lookup(0)["auto_ranges"]["alt_text"] == pytest.approx((100.0, 109.5))
    WORKER_CACHE["_telemetry_cache"] = cache
    WORKER_CACHE["hud_regions"] = None
    captured = {}

    def _fake_compose(*args, **kwargs):
        captured.update(kwargs)
        from PIL import Image
        return Image.new("RGBA", (8, 8))

    monkeypatch.setattr(frame_renderer, "compose_overlay", _fake_compose)
    frame_renderer.render_overlay_frame(5, BASE, 2.0, [], [], [], FPS, 1)
    # Without auto_ranges the alt bar falls back to the manual 0..1000 m scale.
    assert captured["auto_ranges"]["alt_text"] == pytest.approx((100.0, 109.5))
