"""Tests for indicator data availability engine and v1.0 release."""

import pytest
import numpy as np
from PIL import Image

from src.indicators.availability import (
    indicator_data_available,
    compute_indicator_availability,
    get_effective_indicator_availability,
    log_indicator_availability,
)
from src.indicators.compositor import compose_overlay
from src.ffmpeg.nvidia_native_exporter import build_canonical_indicators, build_map_indicator_desc
from src.ffmpeg.intel_native_exporter import _compute_layout_widget_boxes
from src.gui.qt.main_window import APP_VERSION, APP_TITLE


def test_app_version_is_v1():
    """Verify application version is bumped to 1.0 in both code and pyproject.toml."""
    assert APP_VERSION == "1.0"
    from pathlib import Path
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "1.0"' in pyproject


def test_dji_without_fit_telemetry_availability():
    """DJI clip with only IMU/camera metadata:
    - IMU/lean visible
    - HR, Cadence, Garmin battery, Solar, Speed, Altitude, Distance, Track map HIDDEN
    """
    layout = {
        "indicators": {
            "time_display": {"enabled": True},
            "speed_text": {"enabled": True, "source": "auto"},
            "alt_text": {"enabled": True, "source": "auto"},
            "fit_heart_rate_text": {"enabled": True, "source": "auto"},
            "fit_cadence_text": {"enabled": True, "source": "auto"},
            "fit_garmin_battery_percent_text": {"enabled": True, "source": "auto"},
            "fit_solar_text": {"enabled": True, "source": "auto"},
            "fit_distance_text": {"enabled": True, "source": "auto"},
            "track_map": {"enabled": True, "gps_source": "auto"},
            "lean_indicator": {"enabled": True, "source": "gyro"},
            "gyro_x_text": {"enabled": True},
            "accel_x_text": {"enabled": True},
        }
    }

    class DummyDjiTelemetry:
        video_duration_s = 120.0
        start_dt_utc = None
        video_timeline = None
        gyroscope_samples = [(0.0, 0.1, 0.2, 0.3)]
        accelerometer_samples = [(0.0, 0.0, 9.8, 0.0)]
        speed_samples = []
        track_samples = []
        alt_samples = []
        gps_track = []
        fit_data = None
        fit_gps_track = None
        available_fit_fields = []

    avail = compute_indicator_availability(layout, telemetry=DummyDjiTelemetry())

    # Time display & IMU should be visible
    assert avail["time_display"][0] is True
    assert avail["lean_indicator"][0] is True
    assert avail["gyro_x_text"][0] is True
    assert avail["accel_x_text"][0] is True

    # Sensors / GPS / Motion missing in DJI should be HIDDEN
    assert avail["speed_text"][0] is False
    assert avail["alt_text"][0] is False
    assert avail["fit_heart_rate_text"][0] is False
    assert avail["fit_cadence_text"][0] is False
    assert avail["fit_garmin_battery_percent_text"][0] is False
    assert avail["fit_solar_text"][0] is False
    assert avail["fit_distance_text"][0] is False
    assert avail["track_map"][0] is False


def test_dji_with_fit_telemetry_availability():
    """DJI clip with attached FIT dataset: HR, Cadence, Speed, Map become SHOW."""
    layout = {
        "indicators": {
            "speed_text": {"enabled": True, "source": "auto"},
            "alt_text": {"enabled": True, "source": "auto"},
            "fit_heart_rate_text": {"enabled": True, "source": "auto"},
            "fit_cadence_text": {"enabled": True, "source": "auto"},
            "track_map": {"enabled": True, "gps_source": "auto"},
            "lean_indicator": {"enabled": True, "source": "gyro"},
        }
    }

    class DummyDjiWithFit:
        video_duration_s = 120.0
        start_dt_utc = None
        video_timeline = None
        gyroscope_samples = [(0.0, 0.1, 0.2, 0.3)]
        accelerometer_samples = [(0.0, 0.0, 9.8, 0.0)]
        speed_samples = []
        track_samples = []
        alt_samples = []
        gps_track = []
        fit_gps_track = [(0.0, 52.0, 21.0), (1.0, 52.001, 21.001)]
        fit_data = {
            "speed": [(0.0, 25.0)],
            "altitude": [(0.0, 150.0)],
            "heart_rate": [(0.0, 140.0)],
            "cadence": [(0.0, 85.0)],
        }
        available_fit_fields = ["speed", "altitude", "heart_rate", "cadence"]

    avail = compute_indicator_availability(layout, telemetry=DummyDjiWithFit())

    assert avail["lean_indicator"][0] is True
    assert avail["speed_text"][0] is True
    assert avail["alt_text"][0] is True
    assert avail["fit_heart_rate_text"][0] is True
    assert avail["fit_cadence_text"][0] is True
    assert avail["track_map"][0] is True


def test_gopro_without_fit_availability():
    """GoPro GPMF without FIT:
    - Speed, Altitude, Map, ISO, Exposure: SHOW
    - HR, Cadence: HIDE
    """
    layout = {
        "indicators": {
            "speed_text": {"enabled": True, "source": "auto"},
            "alt_text": {"enabled": True, "source": "auto"},
            "iso_text": {"enabled": True, "source": "auto"},
            "exposure_text": {"enabled": True, "source": "auto"},
            "track_map": {"enabled": True, "gps_source": "auto"},
            "fit_heart_rate_text": {"enabled": True, "source": "auto"},
            "fit_cadence_text": {"enabled": True, "source": "auto"},
        }
    }

    class DummyGoProTelemetry:
        video_duration_s = 60.0
        start_dt_utc = None
        video_timeline = None
        speed_samples = [(0.0, 30.0)]
        track_samples = [(0.0, 100.0)]
        alt_samples = [(0.0, 200.0)]
        iso_samples = [(0.0, 100.0)]
        exposure_samples = [(0.0, 0.002)]
        gps_track = [(0.0, 50.0, 19.0), (1.0, 50.001, 19.001)]
        fit_data = None
        fit_gps_track = None
        available_fit_fields = []

    avail = compute_indicator_availability(layout, telemetry=DummyGoProTelemetry())

    assert avail["speed_text"][0] is True
    assert avail["alt_text"][0] is True
    assert avail["iso_text"][0] is True
    assert avail["exposure_text"][0] is True
    assert avail["track_map"][0] is True
    assert avail["fit_heart_rate_text"][0] is False
    assert avail["fit_cadence_text"][0] is False


def test_explicit_source_selection_no_fallback():
    """When indicator specifies explicit source='fit', but FIT is missing while GPMF is present,
    it MUST be HIDDEN (no illegal fallback).
    """
    layout = {
        "indicators": {
            "speed_text": {"enabled": True, "source": "fit"},
        }
    }

    class DummyGoProOnly:
        speed_samples = [(0.0, 35.0)]
        fit_data = None

    avail = compute_indicator_availability(layout, telemetry=DummyGoProOnly())
    assert avail["speed_text"][0] is False
    assert "configured=fit" in avail["speed_text"][1]


def test_dynamic_fit_fields_availability():
    """Dynamic fit_*_text indicators must check available_fit_fields and fit_data."""
    layout = {
        "indicators": {
            "fit_gear_ratio_text": {"enabled": True},
            "fit_solar_pct_text": {"enabled": True},
        }
    }

    class DummyFitData:
        available_fit_fields = ["solar_pct"]
        fit_data = {
            "solar_pct": [(0.0, 75.0)],
        }

    avail = compute_indicator_availability(layout, telemetry=DummyFitData())
    assert avail["fit_solar_pct_text"][0] is True
    assert avail["fit_gear_ratio_text"][0] is False


def test_compositor_zero_placeholder_leak_for_hidden_indicators():
    """When an indicator is unavailable:
    - compose_overlay must skip it entirely
    - bounding box must NOT be registered in _bboxes
    - resulting image pixels in that area must remain transparent (zero leak)
    """
    layout = {
        "indicators": {
            "fit_heart_rate_text": {
                "enabled": True,
                "x": 100,
                "y": 100,
                "size": 50,
                "label": "HR",
                "unit": "BPM",
                "bg_enabled": True,
                "bg_color": "#FF0000",
            }
        },
        "_indicator_availability": {
            "fit_heart_rate_text": False,
        }
    }

    bboxes = {}
    overlay = compose_overlay(
        canvas_w=1920,
        canvas_h=1080,
        layout=layout,
        font_path="assets/Roboto-Bold.ttf",
        date_text="",
        time_text="",
        speed_value=0.0,
        distance_m=0.0,
        _bboxes=bboxes,
        indicator_availability=layout["_indicator_availability"],
        reuse_canvas=False,
    )

    # Indicator should NOT be in bboxes
    assert "fit_heart_rate_text" not in bboxes

    # Overlay should be completely blank/transparent
    arr = np.array(overlay)
    assert np.all(arr == 0)


def test_case_a_vs_case_b():
    """Case A (Project-level missing data source) -> indicator completely HIDDEN.
    Case B (Data source present in project, but single frame value is None) -> SHOW with '--'.
    """
    layout = {
        "indicators": {
            "fit_heart_rate_text": {
                "enabled": True,
                "x": 50,
                "y": 50,
                "size": 30,
                "label": "TĘTNO",
                "unit": "BPM",
            }
        }
    }

    # Case A: Project has no FIT dataset
    avail_a = compute_indicator_availability(layout, telemetry=None)
    assert avail_a["fit_heart_rate_text"][0] is False

    bboxes_a = {}
    img_a = compose_overlay(
        canvas_w=1280,
        canvas_h=720,
        layout=layout,
        font_path="assets/Roboto-Bold.ttf",
        date_text="",
        time_text="",
        speed_value=0.0,
        distance_m=0.0,
        hr_value=None,
        _bboxes=bboxes_a,
        indicator_availability={k: v[0] for k, v in avail_a.items()},
        reuse_canvas=False,
    )
    assert "fit_heart_rate_text" not in bboxes_a
    assert np.all(np.array(img_a) == 0)

    # Case B: Project HAS FIT dataset with HR, but this specific frame has hr_value=0.0 or None
    class DummyFitTelemetry:
        video_duration_s = 60.0
        fit_data = {"heart_rate": [(0.0, 120.0), (1.0, 125.0)]}
        available_fit_fields = ["heart_rate"]

    avail_b = compute_indicator_availability(layout, telemetry=DummyFitTelemetry())
    assert avail_b["fit_heart_rate_text"][0] is True

    bboxes_b = {}
    img_b = compose_overlay(
        canvas_w=1280,
        canvas_h=720,
        layout=layout,
        font_path="assets/Roboto-Bold.ttf",
        date_text="",
        time_text="",
        speed_value=0.0,
        distance_m=0.0,
        hr_value=None,  # Frame gap!
        _bboxes=bboxes_b,
        indicator_availability={k: v[0] for k, v in avail_b.items()},
        reuse_canvas=False,
    )
    # Case B: Should be registered in bboxes and drawn with '--' placeholder
    assert "fit_heart_rate_text" in bboxes_b
    assert np.any(np.array(img_b) > 0)


def test_nvidia_and_intel_exporters_parity():
    """Verify NVIDIA and Intel native pipeline helpers respect _indicator_availability."""
    layout = {
        "indicators": {
            "time_display": {"enabled": True},
            "speed_text": {"enabled": True},
            "fit_heart_rate_text": {"enabled": True},
            "track_map": {"enabled": True},
        },
        "_indicator_availability": {
            "time_display": True,
            "speed_text": True,
            "fit_heart_rate_text": False,
            "track_map": False,
        }
    }

    # NVIDIA
    nv_inds = build_canonical_indicators(layout)
    nv_keys = [desc.key.decode("utf-8") for desc in nv_inds]
    assert "time_display" in nv_keys
    assert "speed_text" in nv_keys
    assert "fit_heart_rate_text" not in nv_keys

    map_desc = build_map_indicator_desc(layout)
    assert map_desc is None

    # Intel
    boxes = _compute_layout_widget_boxes(layout, canvas_w=1920, canvas_h=1080)
    assert "time_display" in boxes
    assert "speed_text" in boxes
    assert "fit_heart_rate_text" not in boxes
    assert "track_map" not in boxes
