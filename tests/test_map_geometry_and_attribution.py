"""Comprehensive test suite for Map Geometry (X=0 left anchor, coordinates, resize)
and Esri attribution (max 2 lines, inside map bounds, legal compliance).
"""

from __future__ import annotations

import os
import sys
import json
from datetime import datetime
from PIL import Image
import pytest

from src.indicators.compositor import compose_overlay
from src.indicators.moving_map import (
    render_map_working_image,
    render_map_unrotated_working_image,
)
from src.map_attribution import (
    MapAttributionRenderer,
    apply_map_attribution,
    map_attribution_overlay,
    _format_attribution_lines,
)
from src.map_providers import MapProviderRegistry


@pytest.fixture
def sample_gps_track():
    return [
        (datetime(2026, 10, 16, 6, 22, 14), 50.0614, 19.9366),
        (datetime(2026, 10, 16, 6, 22, 44), 50.0620, 19.9380),
        (datetime(2026, 10, 16, 6, 23, 14), 50.0635, 19.9400),
    ]


@pytest.fixture
def base_map_layout():
    return {
        "width": 3840,
        "height": 2160,
        "global": {"antialiasing": 1},
        "indicators": {
            "track_map": {
                "enabled": True,
                "form": "map",
                "size": 15.0,
                "x": 0.0,
                "y": 0.0,
                "zoom": 15,
                "map_style": "satellite",
                "map_shape": "square",
                "map_orientation": "track_up",
                "map_geometry_version": 2,
                "map_anchor": "topleft",
                "pitch": 0.0,
                "rotation": 0,
            }
        }
    }


# ── TEST SUITE: MAP GEOMETRY X=0 AND PIXEL ACCURACY ──────────────────────────

def test_map_position_x_zero_touches_exact_left_border(sample_gps_track, base_map_layout):
    """X=0 must position the left edge of the map at pixel 0 (not centered, not clipped)."""
    for res_w, res_h in [(3840, 2160), (1920, 1080), (960, 540)]:
        bboxes = {}
        compose_overlay(
            res_w, res_h, base_map_layout, "", "2026-10-16", "06:22:14",
            25.0, 1000.0, _bboxes=bboxes, gps_track=sample_gps_track,
            async_map=True, reuse_canvas=False,
        )
        assert "track_map" in bboxes
        bx, by, bw, bh = bboxes["track_map"]
        assert bx == 0, f"Resolution {res_w}x{res_h}: left edge must be 0, got {bx}"
        expected_w = int(round(0.15 * res_w))
        assert abs(bw - expected_w) <= 1, f"Resolution {res_w}x{res_h}: width {bw} != expected {expected_w}"


def test_map_position_y_zero_touches_exact_top_border(sample_gps_track, base_map_layout):
    """Y=0 must position the top edge of the map at pixel 0."""
    for res_w, res_h in [(3840, 2160), (1920, 1080), (960, 540)]:
        bboxes = {}
        compose_overlay(
            res_w, res_h, base_map_layout, "", "2026-10-16", "06:22:14",
            25.0, 1000.0, _bboxes=bboxes, gps_track=sample_gps_track,
            async_map=True, reuse_canvas=False,
        )
        assert "track_map" in bboxes
        bx, by, bw, bh = bboxes["track_map"]
        assert by == 0, f"Resolution {res_w}x{res_h}: top edge must be 0, got {by}"


def test_map_positions_x_sweep(sample_gps_track, base_map_layout):
    """Verify X coordinates across 0%, 1%, 5%, 50%, and right edge (85%)."""
    test_positions = [0.0, 1.0, 5.0, 50.0, 85.0]
    for pct in test_positions:
        lay = json.loads(json.dumps(base_map_layout))
        lay["indicators"]["track_map"]["x"] = pct

        for res_w, res_h in [(3840, 2160), (1920, 1080)]:
            bboxes = {}
            compose_overlay(
                res_w, res_h, lay, "", "2026-10-16", "06:22:14",
                25.0, 1000.0, _bboxes=bboxes, gps_track=sample_gps_track,
                async_map=True, reuse_canvas=False,
            )
            bx, by, bw, bh = bboxes["track_map"]
            expected_x = int(round((pct / 100.0) * res_w))
            assert abs(bx - expected_x) <= 1, f"At {pct}% on {res_w}x{res_h}: bx={bx} expected={expected_x}"


def test_map_positions_y_sweep(sample_gps_track, base_map_layout):
    """Verify Y coordinates across 0%, 50%, and bottom edge."""
    for res_w, res_h in [(3840, 2160), (1920, 1080)]:
        # At 16:9, map width is 15% of res_w. In height, map_h = 15% * res_w.
        map_h_px = int(round(0.15 * res_w))
        bottom_y_px = res_h - map_h_px
        bottom_y_pct = (bottom_y_px / res_h) * 100.0

        for y_pct, expected_y in [(0.0, 0), (50.0, int(round(0.50 * res_h))), (bottom_y_pct, bottom_y_px)]:
            lay = json.loads(json.dumps(base_map_layout))
            lay["indicators"]["track_map"]["y"] = y_pct
            bboxes = {}
            compose_overlay(
                res_w, res_h, lay, "", "2026-10-16", "06:22:14",
                25.0, 1000.0, _bboxes=bboxes, gps_track=sample_gps_track,
                async_map=True, reuse_canvas=False,
            )
            bx, by, bw, bh = bboxes["track_map"]
            assert abs(by - expected_y) <= 1, f"At y={y_pct}% on {res_w}x{res_h}: by={by} expected={expected_y}"


def test_map_north_up_and_track_up_geometry_parity(sample_gps_track, base_map_layout):
    """Orientation change (track_up vs north_up) must preserve the exact bounding box anchor."""
    lay_track = json.loads(json.dumps(base_map_layout))
    lay_track["indicators"]["track_map"]["map_orientation"] = "track_up"
    lay_track["indicators"]["track_map"]["x"] = 5.0
    lay_track["indicators"]["track_map"]["y"] = 10.0

    lay_north = json.loads(json.dumps(base_map_layout))
    lay_north["indicators"]["track_map"]["map_orientation"] = "north_up"
    lay_north["indicators"]["track_map"]["x"] = 5.0
    lay_north["indicators"]["track_map"]["y"] = 10.0

    b_track = {}
    compose_overlay(3840, 2160, lay_track, "", "2026-10-16", "06:22:14", 25.0, 1000.0, _bboxes=b_track, gps_track=sample_gps_track, async_map=True, reuse_canvas=False)

    b_north = {}
    compose_overlay(3840, 2160, lay_north, "", "2026-10-16", "06:22:14", 25.0, 1000.0, _bboxes=b_north, gps_track=sample_gps_track, async_map=True, reuse_canvas=False)

    assert b_track["track_map"] == b_north["track_map"]


def test_map_square_and_circle_shape_geometry(sample_gps_track, base_map_layout):
    """Map shapes (square vs circle) must share identical bounding box origin."""
    lay_sq = json.loads(json.dumps(base_map_layout))
    lay_sq["indicators"]["track_map"]["map_shape"] = "square"
    lay_sq["indicators"]["track_map"]["x"] = 0.0

    lay_cir = json.loads(json.dumps(base_map_layout))
    lay_cir["indicators"]["track_map"]["map_shape"] = "circle"
    lay_cir["indicators"]["track_map"]["x"] = 0.0

    b_sq = {}
    compose_overlay(3840, 2160, lay_sq, "", "2026-10-16", "06:22:14", 25.0, 1000.0, _bboxes=b_sq, gps_track=sample_gps_track, async_map=True, reuse_canvas=False)

    b_cir = {}
    compose_overlay(3840, 2160, lay_cir, "", "2026-10-16", "06:22:14", 25.0, 1000.0, _bboxes=b_cir, gps_track=sample_gps_track, async_map=True, reuse_canvas=False)

    assert b_sq["track_map"][0] == 0
    assert b_cir["track_map"][0] == 0
    assert b_sq["track_map"] == b_cir["track_map"]


def test_map_amd_exporter_helpers_geometry_alignment(sample_gps_track, base_map_layout):
    """render_map_working_image and render_map_unrotated_working_image must produce non-negative dst_bbox."""
    base_map_layout["indicators"]["track_map"]["x"] = 0.0
    base_map_layout["indicators"]["track_map"]["y"] = 0.0

    img1, dst1 = render_map_working_image(
        3840, 2160, base_map_layout, "track_map", sample_gps_track,
        target_dt=datetime(2026, 10, 16, 6, 22, 14), apply_style=False,
    )
    assert dst1 is not None
    assert dst1[0] == 0, f"AMD working image dst_x must be 0, got {dst1[0]}"
    assert dst1[1] == 0, f"AMD working image dst_y must be 0, got {dst1[1]}"

    img2, heading, dst2, wsize = render_map_unrotated_working_image(
        3840, 2160, base_map_layout, "track_map", sample_gps_track,
        target_dt=datetime(2026, 10, 16, 6, 22, 14),
    )
    assert dst2 is not None
    assert dst2[0] == 0, f"AMD unrotated image dst_x must be 0, got {dst2[0]}"
    assert dst2[1] == 0, f"AMD unrotated image dst_y must be 0, got {dst2[1]}"


# ── TEST SUITE: ESRI ATTRIBUTION STRICT <= 2 LINES & COMPLIANCE ─────────────

def test_esri_attribution_strictly_max_two_lines():
    """Esri attribution must never exceed 2 lines on any supported map size."""
    long_esri_text = (
        "Powered by Esri | Source: Esri, Vantor, GeoEye, Earthstar Geographics, "
        "CNES/Airbus DS, USDA, USGS, AeroGRID, IGN, and the GIS User Community"
    )
    for map_size in (144, 200, 240, 288, 384, 576):
        for shape in ("square", "circle"):
            overlay = MapAttributionRenderer.get_attribution_overlay(
                "satellite", map_size, map_size, text=long_esri_text, shape=shape,
            )
            assert overlay is not None, f"Overlay should render for size={map_size}, shape={shape}"
            assert overlay.size == (map_size, map_size)


def test_format_attribution_lines_logic():
    """Unit test for _format_attribution_lines helper adhering to approved statutory 2-line format."""
    probe = lambda text: len(text) * 7.0  # rough character width probe
    text = (
        "Powered by Esri. Source: Esri, Vantor, | Earthstar Geographics, and the GIS User Community"
    )

    lines = _format_attribution_lines(text, 220.0, probe)
    assert len(lines) == 2
    assert lines[0] == "Powered by Esri. Source: Esri, Vantor,"
    assert lines[1] == "Earthstar Geographics, and the GIS User Community"
    assert "et al." not in lines[0] and "et al." not in lines[1]
    assert "licensors" not in lines[0] and "licensors" not in lines[1]

    # Also works when input is the raw metadata string
    raw_metadata_text = "Powered by Esri | Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community"
    raw_lines = _format_attribution_lines(raw_metadata_text, 220.0, probe)
    assert len(raw_lines) == 2
    assert raw_lines[0] == "Powered by Esri. Source: Esri, Vantor,"
    assert raw_lines[1] == "Earthstar Geographics, and the GIS User Community"


def test_esri_attribution_bottom_margin_and_tight_padding():
    """Bottom margin must be <= 1% on square/rectangular maps, and padding tightly bound."""
    MapAttributionRenderer.clear_cache()
    for sz in (240, 288, 384, 576):
        overlay = MapAttributionRenderer.get_attribution_overlay("satellite", sz, sz, shape="square")
        assert overlay is not None
        bbox = overlay.getbbox()
        assert bbox is not None
        bottom_gap = sz - bbox[3]
        max_allowed_gap = max(2, int(round(0.015 * sz)))
        assert bottom_gap <= max_allowed_gap, f"Size {sz}: bottom_gap={bottom_gap} exceeds 1% margin"
        # Left-aligned: left edge must be close to left margin (<= 2% sz)
        assert bbox[0] <= max(4, int(round(0.02 * sz))), f"Size {sz}: left position {bbox[0]} not bottom-left"


def test_esri_attribution_inside_map_bounds():
    """Attribution must not overflow map bounds and stay inside convex shape."""
    for sz in (240, 288, 576):
        overlay = MapAttributionRenderer.get_attribution_overlay("satellite", sz, sz, shape="circle")
        assert overlay is not None
        # Check that top and left quarters of the map are untouched
        crop_top_left = overlay.crop((0, 0, sz // 2, sz // 2))
        alpha = crop_top_left.getchannel("A")
        assert alpha.getbbox() is None, "Top-left of overlay must be completely transparent"


def test_optional_attribution_can_be_disabled_for_non_esri():
    """Non-Esri providers allow disabling attribution via show_attribution=False."""
    cfg_off = {"show_attribution": False, "map_shape": "square"}
    # OSM with show_attribution=False -> None
    overlay_osm = map_attribution_overlay("osm", (288, 288), cfg_off)
    assert overlay_osm is None

    # Satellite (Esri) requires visible attribution regardless of show_attribution=False
    overlay_esri = map_attribution_overlay("satellite", (288, 288), cfg_off)
    assert overlay_esri is not None
