"""CPU_REFERENCE Compass geometry and canonical binding tests for ETAP 8C."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from PIL import ImageChops

from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import build_active_fit_field_plan, prepare_overlay_frame_data
from src.indicators.gauge import _render_gauge_indicator
from src.gui.qt.models import compass_indicator_fields
from src.ffmpeg.worker_cache import init_worker
from src.telemetry_precompute import build_telemetry_cache


def _compass_cfg(**overrides):
    cfg = {
        "enabled": True,
        "x": 50.0,
        "y": 50.0,
        "rotation": 0,
        "form": "gauge",
        "gauge_style": "compass",
        "size": 100.0,
        "font_size": 18.0,
        "show_value": True,
        "show_units": False,
        "compass_show_cardinals": True,
        "compass_show_heading": True,
        "compass_tick_degrees": 15,
        "compass_major_tick_degrees": 45,
        "compass_needle_color": "#FF0000",
    }
    cfg.update(overrides)
    return cfg


def _render_compass(value, *, ss=1, rotation=0):
    cfg = _compass_cfg(rotation=rotation)
    formatted = "--°" if value is None else f"{int(round(float(value))) % 360:03d}°"
    if value is None:
        cfg["_compass_missing"] = True
        value = 0.0
    return _render_gauge_indicator(
        1920, 1080, {"indicators": {"compass": cfg}}, "", "compass",
        value, "°", "Compass", cfg, 1080, 1, 18, None, 0, 360, 0, 10,
        100, ss, formatted_val=formatted,
    )[0]


def _red_points(image):
    arr = np.asarray(image)
    mask = (
        (arr[:, :, 0] > 220) & (arr[:, :, 1] < 80) &
        (arr[:, :, 2] < 80) & (arr[:, :, 3] > 200)
    )
    return np.argwhere(mask)


def test_compass_cardinal_headings_point_to_screen_cardinals():
    cx = cy = 120
    for heading, predicate in (
        (0, lambda x, y: y < cy and abs(x - cx) <= 8),
        (90, lambda x, y: x > cx and abs(y - cy) <= 8),
        (180, lambda x, y: y > cy and abs(x - cx) <= 8),
        (270, lambda x, y: x < cx and abs(y - cy) <= 8),
    ):
        points = _red_points(_render_compass(heading))
        assert len(points) > 0
        assert any(predicate(int(x), int(y)) for y, x in points)


def test_compass_intermediate_and_wrap_headings_are_absolute_not_snapped():
    for heading, x_sign, y_sign in (
        (45, 1, -1), (135, 1, 1), (225, -1, 1), (315, -1, -1),
        (359, 0, -1), (0, 0, -1), (1, 0, -1),
    ):
        points = _red_points(_render_compass(heading))
        assert len(points) > 0
        mean_y, mean_x = points.mean(axis=0)
        if x_sign:
            assert (mean_x - 120) * x_sign > 2
        if y_sign:
            assert (mean_y - 120) * y_sign > 2


def test_compass_normalizes_out_of_range_values_without_crashing():
    for heading in (360, -1, 721):
        image = _render_compass(heading)
        assert image.getbbox() is not None
        assert len(_red_points(image)) > 0


def test_compass_missing_heading_keeps_dial_without_false_north_needle():
    image = _render_compass(None)
    assert image.getbbox() is not None
    assert len(_red_points(image)) == 0


def test_compass_geometry_fits_requested_render_sizes():
    for width, height in ((3840, 2160), (1920, 1080), (1280, 720)):
        cfg = _compass_cfg(size=15.0, font_size=1.5)
        image, _, _, _ = _render_gauge_indicator(
            width, height, {"indicators": {"compass": cfg}}, "", "compass",
            359.0, "°", "Compass", cfg, min(width, height), 1,
            max(8, round(1.5 * min(width, height) / 100)), None, 0, 360,
            0, 10, max(1, round(15.0 * min(width, height) / 100)), 1,
            formatted_val="359°",
        )
        assert image.getbbox() is not None
        alpha = np.asarray(image)[:, :, 3]
        ys, xs = np.where(alpha > 0)
        assert xs.min() >= 0 and ys.min() >= 0
        assert xs.max() < image.width and ys.max() < image.height


def test_compass_widget_rotation_is_compositor_transform_only():
    cfg = _compass_cfg(x=50.0, y=50.0, size=15.0, font_size=1.5)
    layout = {"global": {}, "indicators": {"compass": cfg}}
    bboxes = {}
    canvas = compose_overlay(
        1920, 1080, layout, "", "", "", 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0, 0, 0.0, indicator_values={"compass": 90.0},
        _bboxes=bboxes, reuse_canvas=False,
    )
    assert "compass" in bboxes
    assert canvas.getbbox() is not None
    assert cfg["rotation"] == 0
    cfg["rotation"] = 90
    bboxes_rotated = {}
    rotated_canvas = compose_overlay(
        1920, 1080, layout, "", "", "", 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0, 0, 0.0, indicator_values={"compass": 90.0},
        _bboxes=bboxes_rotated, reuse_canvas=False,
    )
    # A square widget keeps the same bbox; the raster itself must carry the
    # widget rotation independently of the internal heading angle.
    assert ImageChops.difference(canvas, rotated_canvas).getbbox() is not None


def test_compass_uses_heading_consumer_and_not_a_renderer_side_channel():
    layout = {"indicators": {"compass": {
        "enabled": True, "field": "heading", "source": "fit",
    }}}
    plan = build_active_fit_field_plan(layout, [])
    assert plan["active_standard_resolve_fields"] == ["heading"]
    assert plan["unique_resolve_fields"] == ["heading"]

    calls = []

    def resolve(field, source, target_dt, *args):
        calls.append((field, source))
        return 123.4

    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    data = prepare_overlay_frame_data(
        layout=layout, target_dt=dt, tz_offset_hours=0, start_dt_utc=dt,
        speed_samples=[], track_samples=[], alt_samples=[], fit_data={"heading": []},
        resolve_cache_value=resolve,
    )
    assert data["extra_indicators"]["compass"] == (
        123.4, "deg", "GPS Course Over Ground"
    )
    assert ("heading", "fit") in calls


def test_compass_precompute_exposes_heading_through_existing_extra_indicators():
    heading = [
        (datetime(2026, 1, 1, tzinfo=timezone.utc), 359.0),
        (datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc), 1.0),
    ]
    layout = {"indicators": {"compass": {
        "enabled": True, "field": "heading", "source": "gpmf",
        "unit": "°", "label": "Compass",
    }}}
    init_worker(
        640, 360, "", layout, {"heading_samples": heading},
        total_overlay_frames=3, target_fps=1.0,
    )
    cache = build_telemetry_cache(
        layout=layout, base_dt=heading[0][0], tz_offset_hours=0.0,
        start_dt_utc=heading[0][0], speed_samples=[], track_samples=[],
        alt_samples=[], total_frames=3, target_fps=1.0,
        fit_field_plan={
            "active_fit_fields": [],
            "active_standard_resolve_fields": ["heading"],
        },
    )
    assert cache.lookup(1)["extra_indicators"]["compass"][0] == 0.0


def test_compass_gui_schema_exposes_common_and_compass_specific_controls():
    names = {field.name for field in compass_indicator_fields()}
    for name in (
        "x", "y", "size", "rotation", "opacity", "font_size",
        "field", "source", "gauge_style", "compass_tick_degrees",
        "compass_tick_color", "compass_needle_color", "compass_cardinal_color",
        "compass_show_heading",
    ):
        assert name in names
