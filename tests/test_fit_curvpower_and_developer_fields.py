"""Regression tests for FIT Developer Field curVPower / power resolution."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from telemetry_fit import FitRecords, sync_fit_to_video, parse_fit
from src.telemetry_resolver import (
    resolve_samples_from_sources,
    resolve_current_presentation,
    numeric_presentation_plan,
    SOURCE_ALIASES,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
from src.multifile import build_timeline_from_paths


def test_developer_field_survives_when_standard_power_absent():
    """Developer curVPower present (native field 7 absent) -> developer value survives."""
    base_t = datetime(2026, 9, 16, 4, 30, 20)
    records = [
        {"timestamp": base_t + timedelta(seconds=i), "curVpower": float(val)}
        for i, val in enumerate([0, 0, 6, 7, 8, 10, 14, 111, 0])
    ]
    fit_records = FitRecords(records, catalog={
        "curVpower": {
            "name": "curVpower",
            "field_name": "curVPower",
            "source": "fit",
            "is_dev": True,
            "unit": "W",
        }
    })
    dataset = sync_fit_to_video(fit_records, base_t)
    assert "curVpower" in dataset
    assert len(dataset["curVpower"]) == 9

    # Both power and curVpower queries must resolve the developer values
    samples_curv = resolve_samples_from_sources("curVpower", "fit", gpmf=None, fit_data=dataset)
    samples_pwr = resolve_samples_from_sources("power", "fit", gpmf=None, fit_data=dataset)
    assert len(samples_curv) == 9
    assert len(samples_pwr) == 9

    # Test exact presentation value at index 7 (111 W)
    t_111 = base_t + timedelta(seconds=7)
    val_curv = resolve_current_presentation(samples_curv, t_111, "curVpower", {})
    val_pwr = resolve_current_presentation(samples_pwr, t_111, "power", {})
    assert val_curv == 111.0
    assert val_pwr == 111.0


def test_developer_zero_is_valid_value():
    """curVpower = 0 is a valid number, not None or missing."""
    base_t = datetime(2026, 9, 16, 4, 30, 20)
    samples = [(base_t, 0.0), (base_t + timedelta(seconds=10), 0.0)]
    val = resolve_current_presentation(samples, base_t + timedelta(seconds=5), "curVpower", {})
    assert val == 0.0
    assert val is not None


def test_standard_power_and_developer_curvpower_coexistence_precedence():
    """When both native power and developer curVpower exist:
    - Explicit curVpower query returns developer value.
    - Generic power query returns native power value.
    """
    base_t = datetime(2026, 9, 16, 4, 30, 20)
    fit_data = {
        "power": [(base_t, 250.0)],
        "curVpower": [(base_t, 180.0)],
    }
    s_curv = resolve_samples_from_sources("curVpower", "fit", gpmf=None, fit_data=fit_data)
    s_pwr = resolve_samples_from_sources("power", "fit", gpmf=None, fit_data=fit_data)

    assert s_curv[0][1] == 180.0  # Developer field preserved
    assert s_pwr[0][1] == 250.0   # Standard power preferred for generic 'power'


def test_gx010298_ground_truth_timestamps():
    """Verify ground truth on real GX010298.fit dataset across all target timestamps."""
    root_dir = Path("C:/_DEV/BikeRideHUD")
    video_path = root_dir / "Video" / "GX010298.MP4"
    fit_path = root_dir / "Video" / "GX010298.fit"
    layout_path = root_dir / "Video" / "GX010298.layout.json"

    if not fit_path.exists() or not video_path.exists():
        pytest.skip("Test dataset files not present")

    tm = TelemetryDataManager()
    tm.load_fit(video_path, None, manual_path=fit_path)

    timeline = build_timeline_from_paths([video_path])
    tm.timeline = timeline
    tm.video_timeline = timeline
    if timeline.clips and timeline.clips[0].absolute_start_dt is not None:
        tm.start_dt_utc = timeline.clips[0].absolute_start_dt
        tm._coverage_start = timeline.clips[0].absolute_start_dt

    layout = json.loads(layout_path.read_text(encoding="utf-8"))

    # Ground truth values:
    # 06:30:26 local (04:30:26 UTC) -> 6 W
    # 06:30:27 local (04:30:27 UTC) -> 7 W
    # 06:30:28 local (04:30:28 UTC) -> 8 W
    # 06:30:29 local (04:30:29 UTC) -> 10 W
    # 06:30:30 local (04:30:30 UTC) -> 14 W
    # 06:31:07 local (04:31:07 UTC) -> 111 W
    # 06:31:12 local (04:31:12 UTC) -> 0 W
    expected_values = [
        (datetime(2026, 9, 16, 4, 30, 26), 6.0),
        (datetime(2026, 9, 16, 4, 30, 27), 7.0),
        (datetime(2026, 9, 16, 4, 30, 28), 8.0),
        (datetime(2026, 9, 16, 4, 30, 29), 10.0),
        (datetime(2026, 9, 16, 4, 30, 30), 14.0),
        (datetime(2026, 9, 16, 4, 31, 7), 111.0),
        (datetime(2026, 9, 16, 4, 31, 12), 0.0),
    ]

    for dt, exp in expected_values:
        val = tm.resolve_value("curVpower", dt, source="fit", indicator_key="fit_curVpower_text")
        assert val == pytest.approx(exp, abs=0.1), f"Mismatch at {dt}: got {val}, expected {exp}"

        # Test frame_data resolution
        fd = prepare_overlay_frame_data(
            layout=layout,
            target_dt=dt,
            tz_offset_hours=2.0,
            start_dt_utc=timeline.clips[0].absolute_start_dt,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            fit_data=tm.fit_data,
            resolve_cache_value=lambda k, src, d, indicator_key=None, **kwargs: tm.resolve_value(
                k, d, source=src, indicator_key=indicator_key, **kwargs
            ),
        )
        extra = fd.get("extra_indicators", {})
        text_tuple = extra.get("fit_curVpower_text")
        assert text_tuple is not None
        assert text_tuple[0] == pytest.approx(exp, abs=0.1)
        assert text_tuple[1] == "W"
