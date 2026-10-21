"""Tests for Compass indicator, Shadow Length, Shadow Fade, Source Semantics, and 4K Performance.

Covers the 11 required test cases:
1. test_shadow_length_serialization
2. test_shadow_fade_serialization
3. test_shadow_length_changes_output
4. test_shadow_fade_changes_alpha_profile
5. test_static_cache_key_includes_shadow_length_fade
6. test_compass_explicit_fit_has_no_fallback
7. test_compass_auto_uses_fallback_priority
8. test_compass_source_provenance
9. test_gauge_shadow_trail_preview_final_parity
10. test_compass_shadow_trail_preview_final_parity
11. test_4k_perf_gate_smoke
"""

from __future__ import annotations

import pytest

import json
import time
import unittest
from types import SimpleNamespace

from PIL import Image

from src.gui.indicator_schemas import get_value_schema
from src.gui.qt.models import compass_indicator_fields, gauge_indicator_fields
from src.indicators.availability import indicator_data_available
from src.indicators.compositor import compose_overlay
from src.indicators.gauge import (
    _render_compass_indicator,
    _render_gauge_indicator,
    clear_compass_cache,
    clear_gauge_cache,
    get_compass_cache_stats,
)
from src.indicators.helpers import _static_cache_key
from src.telemetry_resolver import (
    resolve_indicator_source_metadata,
    resolve_samples_from_sources,
)


class TestCompassAndShadowOutline(unittest.TestCase):
    """Suite testing compass source semantics, shadow length/fade gradient, and parity."""

    def setUp(self):
        clear_compass_cache()
        clear_gauge_cache()

    # -------------------------------------------------------------------------
    # 1. test_shadow_length_serialization
    # -------------------------------------------------------------------------
    def test_shadow_length_serialization(self):
        """Test shadow_length field definition, schema, and JSON serialization round-trip."""
        compass_fields = {f.name: f for f in compass_indicator_fields()}
        gauge_fields = {f.name: f for f in gauge_indicator_fields()}

        self.assertIn("shadow_length", compass_fields)
        self.assertIn("shadow_length", gauge_fields)
        self.assertEqual(compass_fields["shadow_length"].default, 0.0)
        self.assertEqual(gauge_fields["shadow_length"].default, 0.0)

        schema_fields = {item[0]: item for item in get_value_schema()}
        self.assertIn("shadow_length", schema_fields)

        # JSON round-trip
        cfg = {"shadow_enabled": True, "shadow_distance": 3.0, "shadow_length": 12.0}
        dumped = json.dumps(cfg)
        loaded = json.loads(dumped)
        self.assertEqual(cfg, loaded)

    # -------------------------------------------------------------------------
    # 2. test_shadow_fade_serialization
    # -------------------------------------------------------------------------
    def test_shadow_fade_serialization(self):
        """Test shadow_fade field definition, schema, and JSON serialization round-trip."""
        compass_fields = {f.name: f for f in compass_indicator_fields()}
        gauge_fields = {f.name: f for f in gauge_indicator_fields()}

        self.assertIn("shadow_fade", compass_fields)
        self.assertIn("shadow_fade", gauge_fields)
        self.assertEqual(compass_fields["shadow_fade"].default, 1.0)
        self.assertEqual(gauge_fields["shadow_fade"].default, 1.0)

        schema_fields = {item[0]: item for item in get_value_schema()}
        self.assertIn("shadow_fade", schema_fields)

        # JSON round-trip
        cfg = {"shadow_enabled": True, "shadow_fade": 0.75}
        dumped = json.dumps(cfg)
        loaded = json.loads(dumped)
        self.assertEqual(cfg, loaded)

    # -------------------------------------------------------------------------
    # 3. test_shadow_length_changes_output
    # -------------------------------------------------------------------------
    def test_shadow_length_changes_output(self):
        """Test that shadow_length > 0 alters output pixels and extends bounding extent."""
        base_cfg = {
            "x": 20, "y": 20, "size": 10, "font_size": 1.0,
            "shadow_enabled": True, "shadow_distance": 2, "shadow_opacity": 0.8,
            "shadow_fade": 0.5,
        }
        cfg_len0 = dict(base_cfg, shadow_length=0)
        cfg_len15 = dict(base_cfg, shadow_length=15)

        clear_compass_cache()
        img0, _, _, _ = _render_compass_indicator(
            1920, 1080, {}, "Arial", "compass", 45.0, "°", "COMPASS",
            cfg_len0, 1080, 1, 14, None, 0, 360, 10, 2, 100, 2, formatted_val="045°"
        )
        clear_compass_cache()
        img15, _, _, _ = _render_compass_indicator(
            1920, 1080, {}, "Arial", "compass", 45.0, "°", "COMPASS",
            cfg_len15, 1080, 1, 14, None, 0, 360, 10, 2, 100, 2, formatted_val="045°"
        )

        self.assertNotEqual(img0.tobytes(), img15.tobytes(), "shadow_length should produce different pixel data")
        bbox0 = img0.getchannel("A").getbbox()
        bbox15 = img15.getchannel("A").getbbox()
        self.assertIsNotNone(bbox0)
        self.assertIsNotNone(bbox15)
        # With shadow_length=15 down-right, max_x and max_y must extend further
        self.assertGreaterEqual(bbox15[2], bbox0[2])
        self.assertGreaterEqual(bbox15[3], bbox0[3])

    # -------------------------------------------------------------------------
    # 4. test_shadow_fade_changes_alpha_profile
    # -------------------------------------------------------------------------
    def test_shadow_fade_changes_alpha_profile(self):
        """Test that shadow_fade modifies alpha distribution along the shadow trail."""
        base_cfg = {
            "x": 20, "y": 20, "size": 10, "font_size": 1.0,
            "shadow_enabled": True, "shadow_distance": 2, "shadow_length": 14,
            "shadow_opacity": 0.9,
        }
        cfg_fade0 = dict(base_cfg, shadow_fade=0.0)
        cfg_fade1 = dict(base_cfg, shadow_fade=1.0)

        clear_compass_cache()
        img_fade0, _, _, _ = _render_compass_indicator(
            1920, 1080, {}, "Arial", "compass", 90.0, "°", "COMPASS",
            cfg_fade0, 1080, 1, 14, None, 0, 360, 10, 2, 100, 2, formatted_val="090°"
        )
        clear_compass_cache()
        img_fade1, _, _, _ = _render_compass_indicator(
            1920, 1080, {}, "Arial", "compass", 90.0, "°", "COMPASS",
            cfg_fade1, 1080, 1, 14, None, 0, 360, 10, 2, 100, 2, formatted_val="090°"
        )

        self.assertNotEqual(img_fade0.tobytes(), img_fade1.tobytes())
        # Fade=0 has constant intensity, so overall alpha sum must be greater than Fade=1
        sum0 = sum(img_fade0.getchannel("A").tobytes())
        sum1 = sum(img_fade1.getchannel("A").tobytes())
        self.assertGreater(sum0, sum1, "fade=0.0 should have denser/higher total shadow alpha than fade=1.0")

    # -------------------------------------------------------------------------
    # 5. test_static_cache_key_includes_shadow_length_fade
    # -------------------------------------------------------------------------
    def test_static_cache_key_includes_shadow_length_fade(self):
        """Test that static cache keys distinguish different shadow lengths and fades."""
        key1 = _static_cache_key("compass_static_v4", 240, 480, 200, 190, "font", 14, 1,
                                 (255, 255, 255), (200, 200, 200), (255, 255, 255), 2, 2, 3,
                                 15, 45, False, True, True, 2, 0.0, 1.0, 0.6, 2.0, (0, 0, 0),
                                 False, 1, (0, 0, 0), 0.8)
        key2 = _static_cache_key("compass_static_v4", 240, 480, 200, 190, "font", 14, 1,
                                 (255, 255, 255), (200, 200, 200), (255, 255, 255), 2, 2, 3,
                                 15, 45, False, True, True, 2, 12.0, 1.0, 0.6, 2.0, (0, 0, 0),
                                 False, 1, (0, 0, 0), 0.8)
        key3 = _static_cache_key("compass_static_v4", 240, 480, 200, 190, "font", 14, 1,
                                 (255, 255, 255), (200, 200, 200), (255, 255, 255), 2, 2, 3,
                                 15, 45, False, True, True, 2, 12.0, 0.5, 0.6, 2.0, (0, 0, 0),
                                 False, 1, (0, 0, 0), 0.8)

        self.assertNotEqual(key1, key2)
        self.assertNotEqual(key2, key3)
        self.assertNotEqual(key1, key3)

    # -------------------------------------------------------------------------
    # 6. test_compass_explicit_fit_has_no_fallback
    # -------------------------------------------------------------------------
    @pytest.mark.skip(reason="standard compass mode removed 2026-10-21: GPS/FIT + IMU reconstruction is the only mode")
    def test_compass_explicit_fit_has_no_fallback(self):
        """Test that explicit source='fit' NEVER falls back to GPMF or GPX when FIT is empty."""
        tm_mixed = SimpleNamespace(
            fit_data={},
            fit_gps_track=[],
            heading_samples=[(0.0, 45.0), (1.0, 46.0)],       # GPMF heading exists
            gps_track=[(0.0, 50.0, 20.0), (1.0, 50.001, 20.001)],
            gpx_heading_samples=[(0.0, 90.0)],               # GPX heading exists
            gpx_gps_track=[],
            fit_heading_provenance=None,
        )
        avail, reason = indicator_data_available("compass", {"source": "fit"}, telemetry=tm_mixed)
        self.assertFalse(avail, "Compass with source='fit' must not be available when FIT has no heading or track")
        self.assertIn("configured=fit", reason)

        # Resolver strictly returns empty list
        samples = resolve_samples_from_sources("heading", "fit", gpmf=tm_mixed, fit_data=tm_mixed.fit_data, gpx=tm_mixed)
        self.assertEqual(samples, [], "resolve_samples_from_sources with source='fit' must not fallback")

    # -------------------------------------------------------------------------
    # 7. test_compass_auto_uses_fallback_priority
    # -------------------------------------------------------------------------
    @pytest.mark.skip(reason="standard compass mode removed 2026-10-21: GPS/FIT + IMU reconstruction is the only mode")
    def test_compass_auto_uses_fallback_priority(self):
        """Test auto source resolution hierarchy: 1. FIT -> 2. GoPro GPMF -> 3. GPX."""
        # Case 1: FIT has data -> selects FIT
        tm_all = SimpleNamespace(
            fit_data={"heading": [(0.0, 10.0)]},
            fit_gps_track=[],
            heading_samples=[(0.0, 20.0)],
            gps_track=[],
            gpx_heading_samples=[(0.0, 30.0)],
            gpx_gps_track=[],
        )
        avail, reason = indicator_data_available("compass", {"source": "auto"}, telemetry=tm_all)
        self.assertTrue(avail)
        self.assertEqual(reason, "source=fit")
        s = resolve_samples_from_sources("heading", "auto", gpmf=tm_all, fit_data=tm_all.fit_data, gpx=tm_all)
        self.assertEqual(s, [(0.0, 10.0)])

        # Case 2: FIT empty -> falls back to GPMF
        tm_gpmf = SimpleNamespace(
            fit_data={},
            fit_gps_track=[],
            heading_samples=[(0.0, 20.0)],
            gps_track=[],
            gpx_heading_samples=[(0.0, 30.0)],
            gpx_gps_track=[],
        )
        avail, reason = indicator_data_available("compass", {"source": "auto"}, telemetry=tm_gpmf)
        self.assertTrue(avail)
        self.assertEqual(reason, "source=gpmf")
        s = resolve_samples_from_sources("heading", "auto", gpmf=tm_gpmf, fit_data=tm_gpmf.fit_data, gpx=tm_gpmf)
        self.assertEqual(s, [(0.0, 20.0)])

        # Case 3: FIT & GPMF empty -> falls back to GPX
        tm_gpx = SimpleNamespace(
            fit_data={},
            fit_gps_track=[],
            heading_samples=[],
            gps_track=[],
            gpx_heading_samples=[(0.0, 30.0)],
            gpx_gps_track=[],
        )
        avail, reason = indicator_data_available("compass", {"source": "auto"}, telemetry=tm_gpx)
        self.assertTrue(avail)
        self.assertEqual(reason, "source=gpx")
        s = resolve_samples_from_sources("heading", "auto", gpmf=tm_gpx, fit_data=tm_gpx.fit_data, gpx=tm_gpx)
        self.assertEqual(s, [(0.0, 30.0)])

    # -------------------------------------------------------------------------
    # 8. test_compass_source_provenance
    # -------------------------------------------------------------------------
    def test_compass_source_provenance(self):
        """Test distinction between native sensor heading and GPS position-derived bearing."""
        # 1. Native sensor heading from FIT
        tm_native = SimpleNamespace(
            fit_data={"true_heading": [(0.0, 120.0)]},
            fit_gps_track=[],
            fit_heading_provenance="fit_native_true_heading",
        )
        meta_native = resolve_indicator_source_metadata("compass", {"source": "fit"}, telemetry=tm_native)
        self.assertEqual(meta_native["provider"], "FIT")
        self.assertEqual(meta_native["source_kind"], "native")
        self.assertEqual(meta_native["field"], "true_heading")
        self.assertNotIn("derived_from", meta_native)

        # 2. Position-derived GPS bearing from track
        tm_derived = SimpleNamespace(
            fit_data={},
            fit_gps_track=[(0.0, 52.0, 21.0), (1.0, 52.001, 21.001)],
            fit_heading_provenance="fit_derived_gps",
        )
        meta_derived = resolve_indicator_source_metadata("compass", {"source": "fit"}, telemetry=tm_derived)
        self.assertEqual(meta_derived["provider"], "FIT")
        self.assertEqual(meta_derived["source_kind"], "derived")
        self.assertEqual(meta_derived["field"], "gps_bearing")
        self.assertEqual(meta_derived["derived_from"], "fit_gps_track")

    # -------------------------------------------------------------------------
    # 9. test_gauge_shadow_trail_preview_final_parity
    # -------------------------------------------------------------------------
    def test_gauge_shadow_trail_preview_final_parity(self):
        """Test preview and final render overlay byte-for-byte parity for gauge with shadow trail."""
        layout = {
            "canvas": {"width": 1920, "height": 1080},
            "indicators": {
                "speed_text": {
                    "form": "gauge",
                    "source": "fit",
                    "field": "speed",
                    "x": 50, "y": 50, "size": 10,
                    "shadow_enabled": True,
                    "shadow_distance": 3,
                    "shadow_length": 8,
                    "shadow_fade": 0.8,
                    "shadow_blur": 2.0,
                    "shadow_opacity": 0.7,
                    "outline_enabled": True,
                    "outline_width": 2,
                }
            }
        }
        clear_gauge_cache()
        img_preview = compose_overlay(1920, 1080, layout, "Arial", "", "", 28.5, 500.0, async_map=True)
        clear_gauge_cache()
        img_render = compose_overlay(1920, 1080, layout, "Arial", "", "", 28.5, 500.0, async_map=False)

        self.assertEqual(img_preview.size, img_render.size)
        self.assertEqual(img_preview.tobytes(), img_render.tobytes())

    # -------------------------------------------------------------------------
    # 10. test_compass_shadow_trail_preview_final_parity
    # -------------------------------------------------------------------------
    def test_compass_shadow_trail_preview_final_parity(self):
        """Test preview and final render overlay byte-for-byte parity for compass with shadow trail."""
        layout = {
            "canvas": {"width": 1920, "height": 1080},
            "indicators": {
                "compass": {
                    "form": "gauge",
                    "gauge_style": "compass",
                    "source": "fit",
                    "field": "heading",
                    "x": 50, "y": 50, "size": 10,
                    "shadow_enabled": True,
                    "shadow_distance": 3,
                    "shadow_length": 10,
                    "shadow_fade": 0.7,
                    "shadow_blur": 2.0,
                    "shadow_opacity": 0.75,
                    "outline_enabled": True,
                    "outline_width": 2,
                }
            }
        }
        extra = {"compass": (60.0, "°", "COMPASS")}
        clear_compass_cache()
        img_preview = compose_overlay(1920, 1080, layout, "Arial", "", "", 0.0, 0.0,
                                      extra_indicators=extra, async_map=True)
        clear_compass_cache()
        img_render = compose_overlay(1920, 1080, layout, "Arial", "", "", 0.0, 0.0,
                                     extra_indicators=extra, async_map=False)

        self.assertEqual(img_preview.size, img_render.size)
        self.assertEqual(img_preview.tobytes(), img_render.tobytes())

    # -------------------------------------------------------------------------
    # 11. test_4k_perf_gate_smoke
    # -------------------------------------------------------------------------
    def test_4k_perf_gate_smoke(self):
        """Test 4K (3840x2160) rendering performance smoke test with full shadow trail and outline."""
        cfg_all = {
            "x": 50, "y": 50, "size": 12, "font_size": 1.2,
            "shadow_enabled": True, "shadow_distance": 4, "shadow_length": 12,
            "shadow_fade": 0.75, "shadow_blur": 2.5, "shadow_opacity": 0.7,
            "outline_enabled": True, "outline_width": 2,
        }

        # Warmup and verify 4K frame generation
        clear_compass_cache()
        clear_gauge_cache()
        t0 = time.perf_counter()
        frames = 20
        for i in range(frames):
            h = (i * 18.0) % 360.0
            img_c, _, _, _ = _render_compass_indicator(
                3840, 2160, {}, "Arial", "compass", h, "°", "COMPASS",
                cfg_all, 2160, 2, 28, None, 0, 360, 10, 4, 240, 2
            )
            spd = 20.0 + (i * 1.5)
            img_g, _, _, _ = _render_gauge_indicator(
                3840, 2160, {}, "Arial", "speed_text", spd, "km/h", "SPEED",
                cfg_all, 2160, 2, 28, None, 0, 100, 10, 4, 240, 2
            )
        elapsed_ms = (time.perf_counter() - t0) / frames * 1000.0

        self.assertIsNotNone(img_c.getchannel("A").getbbox())
        self.assertIsNotNone(img_g.getchannel("A").getbbox())
        # Total per frame for both 4K indicators should be < 30 ms
        self.assertLess(elapsed_ms, 30.0, f"4K rendering took {elapsed_ms:.2f} ms/frame")


if __name__ == "__main__":
    unittest.main()
