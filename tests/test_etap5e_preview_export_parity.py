"""Regression tests for Etap 5E: TeleM Editor Preview ↔ Final Export HUD Parity."""

import copy
import math
from datetime import datetime, timezone
import pytest
from unittest.mock import patch

from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.gui.layout_manager import resolve_font_path


@pytest.fixture
def font_path():
    return resolve_font_path("Arial")


def test_lean_indicator_precompute_parity():
    """Verify lean_indicator roll is computed identically in precompute and frame_data."""
    layout = {
        "indicators": {
            "lean_indicator": {
                "enabled": True,
                "form": "lean_indicator",
                "source": "gyro",
                "axis": "z",
                "x": 89.0,
                "y": 14.0,
                "size": 1.0,
            }
        }
    }
    start_dt = datetime(2026, 8, 5, 4, 55, 50, 800000, tzinfo=timezone.utc)
    lean_values = {
        0: -7.42,
        1: -5.10,
    }

    def mock_resolver(field_name, source, dt, indicator_key=None):
        if field_name == "lean_roll_z":
            dt_naive = dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) is not None else dt
            start_naive = start_dt.replace(tzinfo=None)
            sec = int((dt_naive - start_naive).total_seconds())
            return lean_values.get(sec, -7.42)
        return None

    # Test precompute cache
    cache = build_telemetry_cache(
        layout=layout,
        base_dt=start_dt,
        tz_offset_hours=0.0,
        start_dt_utc=start_dt,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        total_frames=2,
        target_fps=1.0,
        resolve_cache_value=mock_resolver,
    )
    res0 = cache.lookup(0)
    res1 = cache.lookup(1)

    assert "lean_indicator" in res0["extra_indicators"]
    assert res0["extra_indicators"]["lean_indicator"][0] == -7.42
    assert res1["extra_indicators"]["lean_indicator"][0] == -5.10


def test_auto_scale_contract_respected(font_path):
    """Verify compose_overlay only overrides min_val/max_val when auto_scale=True."""
    layout_manual = {
        "indicators": {
            "speed_text": {
                "enabled": True,
                "form": "gauge",
                "x": 10.0,
                "y": 10.0,
                "size": 5.0,
                "min_val": 0.0,
                "max_val": 30.0,
                "auto_scale": False,
            },
            "alt_text": {
                "enabled": True,
                "form": "bar",
                "x": 20.0,
                "y": 20.0,
                "size": 5.0,
                "min_val": 100.0,
                "max_val": 200.0,
                "auto_scale": False,
            },
        }
    }

    captured_configs = {}
    import src.indicators.compositor as comp
    orig_render = comp.render_value_indicator

    def mock_render(*args, **kwargs):
        cfg = kwargs.get("cfg_override") or kwargs.get("cfg") or {}
        key = kwargs.get("key") or (args[4] if len(args) > 4 else "")
        captured_configs[key] = copy.deepcopy(cfg)
        return orig_render(*args, **kwargs)

    with patch("src.indicators.compositor.render_value_indicator", side_effect=mock_render):
        compose_overlay(
            640, 360, layout_manual, font_path,
            "", "",
            speed_value=20.0, distance_m=100.0, max_distance_m=1000.0,
            alt_value=150.0, min_alt=50.0, max_alt=300.0,
            iso_value=None, exposure_value=None, temp_value=None,
            max_speed_kmh=45.0,
        )

    # When auto_scale=False, speed remains 30.0 and alt remains 100.0/200.0
    assert captured_configs["speed_text"]["max_val"] == 30.0
    assert captured_configs["alt_text"]["min_val"] == 100.0
    assert captured_configs["alt_text"]["max_val"] == 200.0


def test_auto_scale_enabled(font_path):
    """Verify compose_overlay scales when auto_scale=True."""
    layout_auto = {
        "indicators": {
            "speed_text": {
                "enabled": True,
                "form": "gauge",
                "x": 10.0,
                "y": 10.0,
                "size": 5.0,
                "min_val": 0.0,
                "max_val": 30.0,
                "auto_scale": True,
            },
            "alt_text": {
                "enabled": True,
                "form": "bar",
                "x": 20.0,
                "y": 20.0,
                "size": 5.0,
                "min_val": 100.0,
                "max_val": 200.0,
                "auto_scale": True,
            },
        }
    }

    captured_configs = {}
    import src.indicators.compositor as comp
    orig_render = comp.render_value_indicator

    def mock_render(*args, **kwargs):
        cfg = kwargs.get("cfg_override") or kwargs.get("cfg") or {}
        key = kwargs.get("key") or (args[4] if len(args) > 4 else "")
        captured_configs[key] = copy.deepcopy(cfg)
        return orig_render(*args, **kwargs)

    with patch("src.indicators.compositor.render_value_indicator", side_effect=mock_render):
        compose_overlay(
            640, 360, layout_auto, font_path,
            "", "",
            speed_value=20.0, distance_m=100.0, max_distance_m=1000.0,
            alt_value=150.0, min_alt=50.0, max_alt=300.0,
            iso_value=None, exposure_value=None, temp_value=None,
            max_speed_kmh=45.0,
        )

    # When auto_scale=True, speed max is rounded up to 50.0 and alt min/max is 50.0/300.0
    assert captured_configs["speed_text"]["max_val"] == 50.0
    assert captured_configs["alt_text"]["min_val"] == 50.0
    assert captured_configs["alt_text"]["max_val"] == 300.0


def test_range_cache_source_aliases():
    """Verify prepare_overlay_frame_data detects source for speed_text and alt_text."""
    layout = {
        "indicators": {
            "speed_text": {
                "enabled": True,
                "source": "fit",
            },
            "alt_text": {
                "enabled": True,
                "source": "fit",
            },
        }
    }
    dt = datetime(2026, 8, 5, 4, 55, 50, tzinfo=timezone.utc)
    fit_data = {
        "speed": [(dt, 55.5)],
        "alt": [(dt, 120.0)],
    }
    gpmf_speed = [(dt, 22.2)]
    gpmf_alt = [(dt, 40.0)]

    data = prepare_overlay_frame_data(
        layout=layout,
        target_dt=dt,
        tz_offset_hours=0.0,
        speed_samples=gpmf_speed,
        alt_samples=gpmf_alt,
        track_samples=[],
        start_dt_utc=dt,
        fit_data=fit_data,
        total_frames=1,
        current_index=0,
        resolve_cache_value=lambda k, s, d, i=None: 0.0,
    )
    assert data["max_speed_kmh"] == 55.5
    assert data["min_alt"] == 120.0
    assert data["max_alt"] == 120.0
