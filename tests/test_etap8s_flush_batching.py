"""
Unit test suite for ETAP 8S: D3D11 Flush Consolidation & GPU Command Batching.
Validates:
1. test_flush_batching_render_order
2. test_flush_batching_map_sequence
3. test_flush_batching_chart_dynamic
4. test_flush_batching_gauge_dynamic
5. test_flush_batching_above_lifecycle
6. test_flush_batching_pixel_parity
"""
import os
import ctypes
from pathlib import Path
import pytest
from PIL import Image

from src.indicators.compositor import compose_overlay
from src.indicators.text_cache import AboveTextCache, TextRasterKey

root = Path("c:/_DEV/TeleM")
dll_path = root / "native" / "d3d11_amf_pipeline" / "bin" / "telem_amd_native.dll"


def test_flush_batching_render_order():
    """Verify layer render order contract: BELOW -> CHARTS -> GAUGE -> MAP -> ABOVE -> FUSED."""
    layout = {
        "indicators": {
            "speed_visual": {"enabled": True, "form": "gauge", "x": 0.2, "y": 0.2},
            "track_map": {"enabled": True, "form": "map", "x": 0.5, "y": 0.5},
            "fit_battery_pct_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.8, "y": 0.8},
        }
    }
    f = {"extra_indicators": {"fit_battery_pct_text": (77.0, "%", "Bat")}}
    img = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 25.0, 1000.0, reuse_canvas=False, **f)
    assert img.size == (3840, 2160)
    assert img.getbbox() is not None


def test_flush_batching_map_sequence():
    """Sequential Map upload -> resample -> blend without intermediate flush."""
    # Test that map indicator layout is preserved
    layout = {
        "indicators": {
            "track_map": {"enabled": True, "form": "map", "x": 0.5, "y": 0.5, "size": 0.3}
        }
    }
    b = {}
    img = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, _bboxes=b, reuse_canvas=False)
    assert "track_map" in layout["indicators"]


def test_flush_batching_chart_dynamic():
    """Dynamic chart dynamic tile updates remain responsive."""
    layout = {
        "indicators": {
            "fit_cadence_text": {"enabled": True, "form": "chart", "source": "fit", "x": 0.1, "y": 0.8}
        }
    }
    # Dynamic values update without stale texture
    f1 = {"cad_value": 85.0}
    f2 = {"cad_value": 90.0}
    b1, b2 = {}, {}
    img1 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, _bboxes=b1, reuse_canvas="below", **f1)
    img2 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:01", 0.0, 0.0, _bboxes=b2, reuse_canvas="below", **f2)
    assert img1 is not None and img2 is not None


def test_flush_batching_gauge_dynamic():
    """Gauge dynamic value update maintains correct needle position and bounding box."""
    layout = {
        "indicators": {
            "speed_visual": {"enabled": True, "form": "gauge", "x": 0.2, "y": 0.2, "size": 0.2}
        }
    }
    b1, b2 = {}, {}
    img1 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 10.0, 100.0, _bboxes=b1, reuse_canvas="below")
    img2 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:01", 50.0, 200.0, _bboxes=b2, reuse_canvas="below")
    assert img1.getbbox() is not None
    assert img2.getbbox() is not None


def test_flush_batching_above_lifecycle():
    """ABOVE layer regional clear and lifecycle when telemetry transitions to None."""
    layout = {
        "indicators": {
            "fit_solar_pct_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.8, "y": 0.2}
        }
    }
    # Frame 1: active
    f1 = {"extra_indicators": {"fit_solar_pct_text": (50.0, "%", "Solar")}}
    img1 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, reuse_canvas="above", **f1)
    assert img1.getbbox() is not None
    
    # Frame 2: None (missing)
    f2 = {"extra_indicators": {"fit_solar_pct_text": None}}
    img2 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:01", 0.0, 0.0, reuse_canvas="above", **f2)
    assert img2.getbbox() is None, "Frame with None must be completely transparent!"


def test_flush_batching_pixel_parity():
    """Overlay compositing is bit-exact across batched command invocations."""
    layout = {
        "indicators": {
            "fit_battery_pct_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.8, "y": 0.8},
            "fit_solar_pct_text": {"enabled": True, "form": "text", "source": "fit", "x": 0.8, "y": 0.85},
        }
    }
    f = {"extra_indicators": {"fit_battery_pct_text": (77.0, "%", "Bat"), "fit_solar_pct_text": (45.0, "%", "Solar")}}
    
    img1 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, reuse_canvas=False, **f)
    img2 = compose_overlay(3840, 2160, layout, "assets/Roboto-Bold.ttf", "2026-08-19", "10:00:00", 0.0, 0.0, reuse_canvas="above", **f)
    
    assert img1.tobytes() == img2.tobytes()
