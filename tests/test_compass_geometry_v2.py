"""Compass geometry v2: thickness scales with Rozmiar, subticks = count."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from src.indicators.dispatcher import _render_value_indicator
from src.indicators.gauge import (
    COMPASS_MAX_SUBTICKS,
    compass_geometry_scale,
    compass_tick_angles,
    migrate_compass_geometry,
)
from src.indicators.helpers import _STATIC_CACHE

V1 = {
    "enabled": True, "form": "gauge", "gauge_style": "compass", "x": 50.0, "y": 50.0,
    "size": 8.0, "font_size": 1.2, "compass_rotation_mode": "rose",
    "compass_tick_degrees": 5, "compass_major_tick_degrees": 45,
    "compass_ring_width": 2, "compass_needle_width": 6, "compass_tick_width": 1,
    "compass_marker_size": 8.5, "shadow_enabled": True, "outline_enabled": True,
}


def _render(cfg, w=3840, h=2160, value=123.4):
    _STATIC_CACHE.clear()
    layout = {"indicators": {"compass": cfg}, "global": {"text_outline": 3}}
    img, *_ = _render_value_indicator(w, h, layout, "", "compass", value, "°", "C",
                                      cfg_override=cfg, supersample=2)
    return np.asarray(img.convert("RGBA"))


@pytest.mark.parametrize("size", [3.9, 8.0, 16.0])
def test_migration_keeps_the_4k_final_raster_identical(size):
    v1 = dict(V1, size=size)
    v2 = copy.deepcopy(v1)
    assert migrate_compass_geometry(v2)
    assert v2["compass_geometry_version"] == 2 and "compass_tick_degrees" not in v2
    assert np.array_equal(_render(v1), _render(v2))


def test_migration_at_reference_size_keeps_numbers_and_converts_spacing():
    v2 = copy.deepcopy(V1)
    migrate_compass_geometry(v2)
    assert v2["compass_subticks"] == 8  # 45° majors every 5° = 8 between
    assert v2["compass_ring_width"] == pytest.approx(2 * 172.8 / 173)
    assert not migrate_compass_geometry(v2)  # idempotent


def test_v2_thickness_is_proportional_to_rozmiar():
    v2 = copy.deepcopy(V1)
    migrate_compass_geometry(v2)
    base = compass_geometry_scale(v2, 100.0)
    assert compass_geometry_scale(v2, 200.0) == pytest.approx(2 * base)
    assert compass_geometry_scale(v2, 50.0) == pytest.approx(base / 2)
    assert compass_geometry_scale(dict(V1), 200.0) == 1.0  # legacy unchanged
    # Rendered raster grows with Rozmiar, without deformation (square).
    small, big = _render(dict(v2, size=4.0)), _render(dict(v2, size=16.0))
    assert small.shape[0] == small.shape[1] and big.shape[0] == big.shape[1]
    assert big.shape[0] == pytest.approx(4 * small.shape[0], rel=0.02)


def test_more_subticks_means_denser_dial():
    cfg = {"compass_geometry_version": 2, "compass_major_tick_degrees": 45}
    counts = [len(compass_tick_angles(dict(cfg, compass_subticks=n))) for n in (0, 1, 4, 8)]
    assert counts == [8, 16, 40, 72]
    over = compass_tick_angles(dict(cfg, compass_subticks=999))
    assert len(over) == len(compass_tick_angles(dict(cfg, compass_subticks=COMPASS_MAX_SUBTICKS)))
    assert sum(1 for _, major in over if major) == 8
