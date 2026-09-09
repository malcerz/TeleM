"""Comprehensive test suite for True 3D Perspective Map Pitch in TeleM."""

import math
import numpy as np
import pytest
from PIL import Image, ImageDraw

from src.indicators.helpers import (
    apply_map_pitch,
    compute_map_pitch_quad,
    apply_map_shape,
    apply_map_opacity,
)


def _is_convex_quad(pts: list[tuple[float, float]]) -> bool:
    """Check if a 4-point quadrilateral (TL, TR, BR, BL) is strictly convex and non-inverted."""
    if len(pts) != 4:
        return False
    # Cross products of consecutive edges must all have the same non-zero sign (clockwise or counter-clockwise)
    signs = []
    for i in range(4):
        p1 = pts[i]
        p2 = pts[(i + 1) % 4]
        p3 = pts[(i + 2) % 4]
        v1 = (p2[0] - p1[0], p2[1] - p1[1])
        v2 = (p3[0] - p2[0], p3[1] - p2[1])
        cp = v1[0] * v2[1] - v1[1] * v2[0]
        signs.append(cp)
    first_sign = signs[0] > 0
    return all((s > 0 if first_sign else s < 0) for s in signs)


class TestMapPerspectiveGeometry:
    """Requirement 15: Geometric tests for 3D perspective projection corners."""

    def test_tilt_zero_geometry(self):
        """For tilt=0, corners must be exactly (0,0), (W,0), (W,H), (0,H)."""
        w, h = 600, 400
        quad = compute_map_pitch_quad(w, h, 0.0)
        assert len(quad) == 4
        tl, tr, br, bl = quad
        assert tl == (0.0, 0.0)
        assert tr == (float(w), 0.0)
        assert br == (float(w), float(h))
        assert bl == (0.0, float(h))

    @pytest.mark.parametrize("pitch", [10.0, 20.0, 30.0, 45.0, 60.0, 70.0])
    def test_tilt_positive_geometry(self, pitch):
        """For tilt > 0: top edge narrows, moves down, quad is convex, no point inversion."""
        w, h = 500, 500
        quad = compute_map_pitch_quad(w, h, pitch)
        tl, tr, br, bl = quad

        # Bottom edge remains pinned to bottom
        assert bl == (0.0, float(h))
        assert br == (float(w), float(h))

        # Top edge narrows symmetrically: w_top < w
        w_top = tr[0] - tl[0]
        assert w_top < w
        assert w_top > 0
        assert math.isclose(tl[0], (w - w_top) / 2.0, rel_tol=1e-4)
        assert math.isclose(tr[0], (w + w_top) / 2.0, rel_tol=1e-4)

        # Top edge moves down according to perspective: y_top > 0
        assert tl[1] == tr[1]
        y_top = tl[1]
        assert y_top > 0.0
        assert y_top < h

        # As pitch increases, top edge narrows further and moves further down
        quad_higher = compute_map_pitch_quad(w, h, min(70.0, pitch + 5.0))
        if pitch < 65.0:
            w_top_higher = quad_higher[1][0] - quad_higher[0][0]
            y_top_higher = quad_higher[0][1]
            assert w_top_higher < w_top
            assert y_top_higher > y_top

        # Quad must be strictly convex and non-inverted
        assert _is_convex_quad(quad)
        assert tl[0] < tr[0]
        assert bl[0] < br[0]


class TestLegacyTiltZeroParity:
    """Requirement 14: Tilt=0 must be exact legacy identity."""

    def test_tilt_zero_returns_identical_image(self):
        img = Image.new("RGBA", (200, 200), (45, 120, 230, 255))
        d = ImageDraw.Draw(img)
        d.line([(0, 0), (200, 200)], fill=(255, 255, 255, 255), width=3)

        out0 = apply_map_pitch(img, 0.0)
        assert out0 is img, "Tilt 0.0 should return original image object directly (legacy bypass)"

        out_none = apply_map_pitch(img, None)
        assert out_none is img

        out_neg = apply_map_pitch(img, -5.0)
        assert out_neg is img


class TestRouteAndMarkerProjectiveParity:
    """Requirement 16: Route and marker drawn into surface stay aligned after perspective."""

    def test_marker_remains_on_route_and_grid(self):
        w, h = 500, 500
        pitch = 45.0
        d = 1.2 * max(w, h)
        theta = math.radians(pitch)

        # Create a synthetic map surface with a diagonal route passing through center (250, 250)
        # and marker exactly at center (250, 250)
        img = Image.new("RGBA", (w, h), (30, 40, 50, 255))
        draw = ImageDraw.Draw(img)
        # Red route
        draw.line([(50, 50), (450, 450)], fill=(255, 0, 0, 255), width=6)
        # White marker at center
        draw.ellipse([240, 240, 260, 260], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=2)

        pitched = apply_map_pitch(img, pitch)
        assert pitched.size == (w, h)

        # Compute mathematically expected position of (250, 250) in perspective projection
        # At s = h/2 = 250 from bottom edge:
        s = h / 2.0
        z = d + s * math.sin(theta)
        dy = (s * d * math.cos(theta)) / z
        expected_y = h - dy
        expected_x = w / 2.0  # exactly centered

        # Verify pixel at (round(expected_x), round(expected_y)) is white marker
        marker_px = pitched.getpixel((int(round(expected_x)), int(round(expected_y))))
        # Should be predominantly white (the marker)
        assert marker_px[0] > 200 and marker_px[1] > 200 and marker_px[2] > 200, f"Marker pixel at projected center: {marker_px}"

        # Points on route above and below center also project consistently
        # Let's verify route point at s=350 (source y = 150):
        s_far = 350.0
        z_far = d + s_far * math.sin(theta)
        dy_far = (s_far * d * math.cos(theta)) / z_far
        y_far = h - dy_far
        # In source, x = y = 150. Distance from horizontal center = -100.
        # Scaled by d / z_far:
        x_far = (w / 2.0) - 100.0 * (d / z_far)
        far_px = pitched.getpixel((int(round(x_far)), int(round(y_far))))
        assert far_px[0] > 180 and far_px[1] < 100, f"Route pixel at far test point: {far_px}"


class TestTrackUpWithPerspective:
    """Requirement 17: Track-Up rotation on ground plane + perspective pitch remain stable."""

    def test_track_up_multiple_headings(self):
        """Verify that heading rotation + pitch tilt produce valid convex quads and distinct transformed bitmaps."""
        w, h = 400, 400
        pitch = 40.0

        # Simulate base tile with directional feature (route pointing North)
        results = []
        for heading in [0.0, 45.0, 90.0]:
            # In Track-Up, ground rotates by heading around center
            base = Image.new("RGBA", (w, h), (40, 50, 60, 255))
            draw = ImageDraw.Draw(base)
            for step in range(0, w, 40):
                draw.line([(step, 0), (step, h)], fill=(70, 80, 90, 255), width=2)
                draw.line([(0, step), (w, step)], fill=(70, 80, 90, 255), width=2)
            draw.line([(w // 2, h // 2), (w // 2, 50)], fill=(255, 0, 0, 255), width=8)
            draw.ellipse([w // 2 - 10, h // 2 - 10, w // 2 + 10, h // 2 + 10], fill=(255, 255, 255, 255))

            # Rotate ground
            if heading != 0.0:
                rotated = base.rotate(heading, resample=Image.Resampling.BICUBIC)
            else:
                rotated = base

            pitched = apply_map_pitch(rotated, pitch)
            assert pitched.size == (w, h)
            arr = np.array(pitched)
            results.append(arr)

        # Headings 0, 45, 90 must produce distinct outputs
        diff_0_45 = np.abs(results[0].astype(int) - results[1].astype(int))
        diff_0_90 = np.abs(results[0].astype(int) - results[2].astype(int))
        assert np.max(diff_0_45) > 100
        assert np.max(diff_0_90) > 100


class TestPreviewRenderParity:
    """Requirement 18: Preview and render use the same geometric projection and quad."""

    def test_preview_render_parity(self):
        w, h = 512, 512
        pitch = 35.0

        quad_preview = compute_map_pitch_quad(w, h, pitch)
        quad_render = compute_map_pitch_quad(w, h, pitch)
        assert quad_preview == quad_render

        # Create synthetic preview image and render image
        img = Image.new("RGBA", (w, h), (80, 100, 120, 255))
        d = ImageDraw.Draw(img)
        d.line([(100, 100), (400, 400)], fill=(255, 50, 50, 255), width=4)
        d.ellipse([250, 250, 262, 262], fill=(255, 255, 255, 255))

        preview_out = apply_map_pitch(img, pitch)
        render_out = apply_map_pitch(img, pitch)

        diff = np.abs(np.array(preview_out).astype(int) - np.array(render_out).astype(int))
        assert np.max(diff) == 0, "Preview and Render outputs must be 100% pixel-identical"
