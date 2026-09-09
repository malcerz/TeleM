"""Unit tests for preview coordinate transformation and aspect-ratio geometry."""

import pytest
from src.gui.preview_transform import (
    PreviewGeometry,
    calculate_displayed_video_rect,
    calculate_physical_video_rect,
    norm_to_preview_coords,
    preview_to_norm_coords,
    preview_to_source_coords,
    source_to_preview_coords,
)


def test_preview_transform_1920x1080_viewport():
    # 3840x2160 in 1920x1080 viewport (exact 16:9)
    ox, oy, dw, dh = calculate_displayed_video_rect(1920, 1080, 3840, 2160)
    assert ox == 0
    assert oy == 0
    assert dw == 1920
    assert dh == 1080

    # Center mapping
    px, py = source_to_preview_coords(1920, 1080, 1920, 1080, 3840, 2160)
    assert (px, py) == (960.0, 540.0)

    # Roundtrip
    sx, sy = preview_to_source_coords(px, py, 1920, 1080, 3840, 2160)
    assert pytest.approx(sx) == 1920.0
    assert pytest.approx(sy) == 1080.0


def test_preview_transform_1600x900_viewport():
    # 3840x2160 in 1600x900 viewport (exact 16:9)
    ox, oy, dw, dh = calculate_displayed_video_rect(1600, 900, 3840, 2160)
    assert ox == 0
    assert oy == 0
    assert dw == 1600
    assert dh == 900


def test_preview_transform_1366x768_viewport():
    # 3840x2160 in 1366x768 viewport
    # 1366 / 768 = 1.77864..., 16/9 = 1.77777... -> slightly wider -> pillarbox
    ox, oy, dw, dh = calculate_displayed_video_rect(1366, 768, 3840, 2160)
    assert oy == 0
    assert dh == 768
    # 768 * 16 / 9 = 1365.33 -> 1365
    assert dw in (1365, 1366)
    assert ox >= 0
    assert ox + dw <= 1366


def test_preview_transform_2678x1458_viewport():
    # 3840x2160 in 2678x1458 viewport (the user's Qt geometry)
    # 2678 / 1458 = 1.8367... > 1.7777 -> pillarbox
    ox, oy, dw, dh = calculate_displayed_video_rect(2678, 1458, 3840, 2160)
    assert oy == 0
    assert dh == 1458
    # target_w = round(1458 * 16 / 9) = 2592
    assert dw == 2592
    assert ox == (2678 - 2592) // 2
    assert ox == 43
    assert ox + dw <= 2678

    # Normalized center (50%, 50%) should map to the exact center of the video
    px, py = norm_to_preview_coords(50.0, 50.0, 2678, 1458, 3840, 2160)
    assert px == 43 + 2592 / 2
    assert py == 1458 / 2

    # Roundtrip from preview to norm
    nx, ny = preview_to_norm_coords(px, py, 2678, 1458, 3840, 2160)
    assert pytest.approx(nx) == 50.0
    assert pytest.approx(ny) == 50.0


def test_preview_transform_letterbox_viewport():
    # Taller viewport: 1000x1000 (aspect 1.0 < 16:9 -> letterbox)
    ox, oy, dw, dh = calculate_displayed_video_rect(1000, 1000, 3840, 2160)
    assert ox == 0
    assert dw == 1000
    # target_h = round(1000 / (16/9)) = round(562.5) = 562 or 563
    assert dh in (562, 563)
    assert oy == (1000 - dh) // 2
    assert oy > 0
    assert oy + dh <= 1000


def test_preview_transform_physical_rect_with_dpr():
    # DPR = 1.5, viewport 1920x1080
    pox, poy, pw, ph = calculate_physical_video_rect(1920, 1080, 3840, 2160, dpr=1.5)
    assert pox == 0
    assert poy == 0
    assert pw == int(round(1920 * 1.5))  # 2880
    assert ph == int(round(1080 * 1.5))  # 1620


def test_preview_geometry_dataclass():
    geom = PreviewGeometry.compute(2678, 1458, 3840, 2160, dpr=1.25)
    assert geom.viewport_w == 2678
    assert geom.viewport_h == 1458
    assert geom.displayed_w == 2592
    assert geom.displayed_h == 1458
    assert geom.offset_x == 43
    assert geom.offset_y == 0
    assert geom.physical_w == int(round(2592 * 1.25))

    # Top-left of video
    assert geom.source_to_preview(0, 0) == (43.0, 0.0)
    # Bottom-right of video
    assert geom.source_to_preview(3840, 2160) == (43.0 + 2592.0, 1458.0)
    # Normalized top-left
    assert geom.norm_to_preview(0.0, 0.0) == (43.0, 0.0)
    # Normalized bottom-right
    assert geom.norm_to_preview(100.0, 100.0) == (43.0 + 2592.0, 1458.0)


def test_indicator_normalized_position_invariance():
    # An indicator at (20%, 80%) must land on the same relative point
    # on the video regardless of viewport dimensions.
    nx, ny = 20.0, 80.0
    viewports = [
        (1920, 1080),
        (1600, 900),
        (1366, 768),
        (2678, 1458),
        (1000, 1000),
        (2560, 1080),
    ]
    for vw, vh in viewports:
        geom = PreviewGeometry.compute(vw, vh, 3840, 2160)
        px, py = geom.norm_to_preview(nx, ny)
        # Verify preview_to_norm restores the exact percentage
        r_nx, r_ny = geom.preview_to_norm(px, py)
        assert pytest.approx(r_nx, abs=1e-4) == nx
        assert pytest.approx(r_ny, abs=1e-4) == ny
        # Verify that relative position in the displayed video is always (0.2, 0.8)
        rel_x = (px - geom.offset_x) / geom.displayed_w
        rel_y = (py - geom.offset_y) / geom.displayed_h
        assert pytest.approx(rel_x, abs=1e-5) == 0.20
        assert pytest.approx(rel_y, abs=1e-5) == 0.80
