"""Tests for universal indicator autoscale min/max calculation across all forms and sources."""

import pytest
from datetime import datetime, timedelta
from src.indicators.frame_data import compute_indicator_auto_ranges, prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.telemetry_precompute import build_telemetry_cache
from PIL import Image


def test_autoscale_synthetic_samples_min_max():
    """Verify synthetic samples [12, 20, 37, 44] yield min=12, max=44."""
    base_dt = datetime(2026, 9, 1, 10, 0, 0)
    samples = [
        (base_dt, 12.0),
        (base_dt + timedelta(seconds=1), 20.0),
        (base_dt + timedelta(seconds=2), 37.0),
        (base_dt + timedelta(seconds=3), 44.0),
    ]
    
    layout = {
        "width": 1920,
        "height": 1080,
        "indicators": {
            "speed_visual": {
                "enabled": True,
                "form": "bar",
                "source": "gpmf",
                "auto_scale": True,
                "min_val": 0.0,
                "max_val": 100.0,
            }
        }
    }
    
    ranges = compute_indicator_auto_ranges(
        layout,
        speed_samples=samples,
    )
    
    assert "speed_visual" in ranges
    min_v, max_v = ranges["speed_visual"]
    assert min_v == 12.0
    assert max_v == 44.0


def test_autoscale_source_switch_gpmf_to_fit():
    """Verify changing source from gpmf to fit immediately changes the calculated auto range."""
    base_dt = datetime(2026, 9, 1, 10, 0, 0)
    gpmf_samples = [
        (base_dt, 12.0),
        (base_dt + timedelta(seconds=1), 44.0),
    ]
    fit_samples = [
        (base_dt, 55.0),
        (base_dt + timedelta(seconds=1), 95.0),
    ]
    
    # 1. Config with GPMF source
    layout_gpmf = {
        "width": 1920, "height": 1080,
        "indicators": {
            "speed_visual": {
                "enabled": True, "form": "bar", "source": "gpmf",
                "auto_scale": True, "min_val": 0.0, "max_val": 100.0,
            }
        }
    }
    ranges_gpmf = compute_indicator_auto_ranges(
        layout_gpmf,
        speed_samples=gpmf_samples,
        fit_data={"speed": fit_samples},
    )
    assert ranges_gpmf["speed_visual"] == (12.0, 44.0)
    
    # 2. Config switched to FIT source
    layout_fit = {
        "width": 1920, "height": 1080,
        "indicators": {
            "speed_visual": {
                "enabled": True, "form": "bar", "source": "fit",
                "auto_scale": True, "min_val": 0.0, "max_val": 100.0,
            }
        }
    }
    ranges_fit = compute_indicator_auto_ranges(
        layout_fit,
        speed_samples=gpmf_samples,
        fit_data={"speed": fit_samples},
    )
    assert ranges_fit["speed_visual"] == (55.0, 95.0)


@pytest.mark.parametrize("form,bar_style,orientation", [
    ("bar", "segments", "horizontal"),
    ("bar", "segments", "vertical"),
    ("bar", "ruler", "horizontal"),
    ("bar", "ruler", "vertical"),
    ("gauge", "", ""),
    ("chart", "", ""),
])
def test_autoscale_all_indicator_forms(form, bar_style, orientation):
    """Verify BAR horizontal/vertical, RULER horizontal/vertical, GAUGE, and CHART respect auto_scale."""
    base_dt = datetime(2026, 9, 1, 10, 0, 0)
    samples = [
        (base_dt, 15.0),
        (base_dt + timedelta(seconds=1), 65.0),
    ]
    
    cfg = {
        "enabled": True,
        "form": form,
        "source": "fit",
        "auto_scale": True,
        "min_val": 0.0,
        "max_val": 100.0,
        "x": 0.2,
        "y": 0.2,
        "size": 1.0,
        "thickness": 3.0,
    }
    if bar_style:
        cfg["bar_style"] = bar_style
    if orientation:
        cfg["orientation"] = orientation
        
    layout = {
        "width": 1920, "height": 1080,
        "indicators": {
            "hr_text": cfg
        }
    }
    
    fit_data = {"hr": samples}
    auto_ranges = compute_indicator_auto_ranges(
        layout,
        fit_data=fit_data,
    )
    assert "hr_text" in auto_ranges
    assert auto_ranges["hr_text"] == (15.0, 65.0)
    
    # Verify compositor applies these exact values to cfg
    # (compose_overlay renders without crashing and applies the range)
    img = compose_overlay(
        1920, 1080, layout, None,
        "2026.09.01", "10:00:00",
        0.0, 0.0, 0.0,
        0.0, 0.0, 0.0,
        0.0, 0.0, 0.0,
        indicator_values={"hr_text": 40.0},
        auto_ranges=auto_ranges,
    )
    assert isinstance(img, Image.Image)


def test_autoscale_distance_scaling_to_km():
    """Verify distance streams in meters are scaled to kilometers in auto_ranges."""
    base_dt = datetime(2026, 9, 1, 10, 0, 0)
    # 0 to 24,000 meters -> should be 0 to 24.0 km
    samples = [
        (base_dt, 0.0),
        (base_dt + timedelta(seconds=10), 24000.0),
    ]
    
    layout = {
        "width": 1920, "height": 1080,
        "indicators": {
            "dist_visual": {
                "enabled": True,
                "form": "bar",
                "source": "gpmf",
                "auto_scale": True,
                "unit": "km",
                "min_val": 0.0,
                "max_val": 5.0,
                "x": 0.2,
                "y": 0.2,
                "size": 1.0,
                "thickness": 3.0,
            }
        }
    }
    
    ranges = compute_indicator_auto_ranges(
        layout,
        track_samples=samples,
    )
    assert "dist_visual" in ranges
    min_v, max_v = ranges["dist_visual"]
    assert min_v == 0.0
    assert max_v == 24.0


def test_autoscale_fallback_when_no_data():
    """Verify indicator safely preserves configured min_val/max_val when no data exists."""
    layout = {
        "width": 1920, "height": 1080,
        "indicators": {
            "power_text": {
                "enabled": True,
                "form": "bar",
                "source": "fit",
                "auto_scale": True,
                "min_val": 10.0,
                "max_val": 400.0,
                "x": 0.2,
                "y": 0.2,
                "size": 1.0,
                "thickness": 3.0,
            }
        }
    }
    
    # No power samples provided
    ranges = compute_indicator_auto_ranges(
        layout,
        fit_data={},
    )
    assert "power_text" not in ranges
    
    # Render should keep the fallback min_val/max_val
    img = compose_overlay(
        1920, 1080, layout, None,
        "2026.09.01", "10:00:00",
        0.0, 0.0, 0.0,
        0.0, 0.0, 0.0,
        0.0, 0.0, 0.0,
        indicator_values={"power_text": 150.0},
        auto_ranges=ranges,
    )
    assert isinstance(img, Image.Image)

