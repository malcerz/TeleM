import pytest
from datetime import datetime, timezone, timedelta
import numpy as np
from PIL import Image

from src.indicators.frame_data import prepare_overlay_frame_data
import src.indicators.compositor as compositor
import src.indicators.chart as chart
import src.indicators.chart_utils as chart_utils


@pytest.fixture
def mock_chart_telemetry():
    base_dt = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)
    # Create 600 samples (10 minutes) with 2 pauses
    timestamps = []
    hr_vals = []
    cad_vals = []
    t = base_dt
    for i in range(600):
        timestamps.append(t)
        if 100 <= i < 150 or 350 <= i < 400:
            # Pauses: gap in time or None
            t += timedelta(seconds=5.0)
            hr_vals.append(None)
            cad_vals.append(None)
        else:
            t += timedelta(seconds=1.0)
            hr_vals.append(120.0 + (i % 40))
            cad_vals.append(85.0 + (i % 25))
    return {
        "base_dt": base_dt,
        "timestamps": timestamps,
        "hr_vals": hr_vals,
        "cad_vals": cad_vals,
    }


def test_chart_dynamic_layer_direct_vs_sequential_parity(mock_chart_telemetry):
    """Direct seek to arbitrary timestamps matches sequential rendering byte-for-byte."""
    base_dt = mock_chart_telemetry["base_dt"]
    timestamps = mock_chart_telemetry["timestamps"]
    hr_vals = mock_chart_telemetry["hr_vals"]
    cad_vals = mock_chart_telemetry["cad_vals"]

    layout = {
        "global": {"text_outline": 3},
        "indicators": {
            "fit_heart_rate_text": {
                "enabled": True, "label": "HEART RATE", "x": 59.0, "y": 82.0,
                "form": "chart", "unit": "BPM", "min_val": 40.0, "max_val": 220.0,
                "chart_time_scope": "activity", "size": 27.0, "font_size": 1.2,
            },
            "fit_cadence_text": {
                "enabled": True, "label": "CADENCE", "x": 24.0, "y": 82.0,
                "form": "chart", "unit": "rpm", "min_val": 0.0, "max_val": 200.0,
                "chart_time_scope": "activity", "size": 27.0, "font_size": 1.2,
            }
        }
    }

    test_indices = [7, 60, 147, 300, 585]
    for idx in test_indices:
        target_dt = timestamps[min(idx, len(timestamps) - 1)]
        
        # 1. Fresh direct seek
        chart._FINAL_STATIC_CHART_CACHE.clear()
        chart._DOT_TILES_CACHE.clear()
        
        fd_direct = prepare_overlay_frame_data(
            target_dt=target_dt,
            start_dt_utc=base_dt,
            tz_offset_hours=0.0,
            layout=layout,
            speed_samples=[], track_samples=[], alt_samples=[],
            iso_samples=[], exposure_samples=[], temperature_samples=[],
            fit_data={
                "heart_rate": list(zip(timestamps, hr_vals)),
                "cadence": list(zip(timestamps, cad_vals)),
            },
            resolve_cache_value=lambda k, src, dt, ind=None: 145.0 if "heart" in k else 90.0,
        )
        img_direct = compositor.compose_overlay(1280, 720, layout, "", reuse_canvas=False, **fd_direct)

        # 2. Cached sequential
        fd_seq = prepare_overlay_frame_data(
            target_dt=target_dt,
            start_dt_utc=base_dt,
            tz_offset_hours=0.0,
            layout=layout,
            speed_samples=[], track_samples=[], alt_samples=[],
            iso_samples=[], exposure_samples=[], temperature_samples=[],
            fit_data={
                "heart_rate": list(zip(timestamps, hr_vals)),
                "cadence": list(zip(timestamps, cad_vals)),
            },
            resolve_cache_value=lambda k, src, dt, ind=None: 145.0 if "heart" in k else 90.0,
        )
        img_seq = compositor.compose_overlay(1280, 720, layout, "", reuse_canvas=False, **fd_seq)

        diff = np.abs(np.array(img_direct, dtype=int) - np.array(img_seq, dtype=int))
        assert np.max(diff) == 0, f"Pixel difference on direct seek to index {idx}"


def test_chart_none_value_handling(mock_chart_telemetry):
    """When value is None, charts render safely showing '--' with background intact."""
    base_dt = mock_chart_telemetry["base_dt"]
    timestamps = mock_chart_telemetry["timestamps"]
    hr_vals = mock_chart_telemetry["hr_vals"]

    layout = {
        "global": {"text_outline": 3},
        "indicators": {
            "fit_heart_rate_text": {
                "enabled": True, "label": "HEART RATE", "x": 59.0, "y": 82.0,
                "form": "chart", "unit": "BPM", "min_val": 40.0, "max_val": 220.0,
                "chart_time_scope": "activity", "size": 27.0, "font_size": 1.2,
            }
        }
    }

    target_dt = timestamps[10]
    fd = prepare_overlay_frame_data(
        target_dt=target_dt,
        start_dt_utc=base_dt,
        tz_offset_hours=0.0,
        layout=layout,
        speed_samples=[], track_samples=[], alt_samples=[],
        iso_samples=[], exposure_samples=[], temperature_samples=[],
        fit_data={"heart_rate": list(zip(timestamps, hr_vals))},
        resolve_cache_value=lambda k, src, dt, ind=None: None,
    )
    img = compositor.compose_overlay(1280, 720, layout, "", reuse_canvas=False, **fd)
    assert img is not None
    assert img.size == (1280, 720)


def test_chart_font_switching(mock_chart_telemetry):
    """Switching fonts properly clears/updates dynamic text cache."""
    base_dt = mock_chart_telemetry["base_dt"]
    timestamps = mock_chart_telemetry["timestamps"]
    hr_vals = mock_chart_telemetry["hr_vals"]

    layout = {
        "global": {"text_outline": 3},
        "indicators": {
            "fit_heart_rate_text": {
                "enabled": True, "label": "HEART RATE", "x": 59.0, "y": 82.0,
                "form": "chart", "unit": "BPM", "min_val": 40.0, "max_val": 220.0,
                "chart_time_scope": "activity", "size": 27.0, "font_size": 1.2,
            }
        }
    }

    target_dt = timestamps[10]
    fd = prepare_overlay_frame_data(
        target_dt=target_dt,
        start_dt_utc=base_dt,
        tz_offset_hours=0.0,
        layout=layout,
        speed_samples=[], track_samples=[], alt_samples=[],
        iso_samples=[], exposure_samples=[], temperature_samples=[],
        fit_data={"heart_rate": list(zip(timestamps, hr_vals))},
        resolve_cache_value=lambda k, src, dt, ind=None: 150.0,
    )

    for font_name in ["", "Comic Sans MS", "Digital-7"]:
        img = compositor.compose_overlay(1280, 720, layout, font_name, reuse_canvas=False, **fd)
        assert img is not None
