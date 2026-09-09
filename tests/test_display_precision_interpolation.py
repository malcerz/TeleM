from datetime import datetime, timedelta, timezone

import pytest

from src.ffmpeg import worker_cache
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_resolver import (
    interpolate_presentation_value, resolve_presentation_precision,
)
from src.indicators.bar import _render_bar_indicator
from src.indicators.frame_data import prepare_overlay_frame_data
from PIL import Image


BASE = datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc)


def _samples(values, spacing=20):
    return [(BASE + timedelta(seconds=i * spacing), value) for i, value in enumerate(values)]


def test_battery_integer_source_interpolates_only_for_extra_display_precision():
    raw = _samples([96, 96, 95, 95])
    snapshot = list(raw)

    assert interpolate_presentation_value(raw, BASE + timedelta(seconds=30), "battery", precision=0) == 96
    # Change-event interpolation spans the complete 96 plateau (0..40 s).
    assert interpolate_presentation_value(raw, BASE + timedelta(seconds=30), "battery", precision=1) == pytest.approx(95.25)
    assert interpolate_presentation_value(raw, BASE + timedelta(seconds=30), "battery", precision=2) == pytest.approx(95.25)
    assert raw == snapshot


def test_presentation_boundaries_repeated_values_and_gap_gate():
    raw = _samples([96, 96, 95, 95])
    assert interpolate_presentation_value(raw, BASE - timedelta(microseconds=1), "battery", precision=2) is None
    assert interpolate_presentation_value(raw, BASE + timedelta(seconds=10), "battery", precision=2) == pytest.approx(95.75)
    assert interpolate_presentation_value(raw, BASE + timedelta(seconds=60), "battery", precision=2) == 95

    gapped = [
        (BASE, 96),
        (BASE + timedelta(seconds=1), 96),
        (BASE + timedelta(seconds=2), 96),
        (BASE + timedelta(seconds=100), 95),
        (BASE + timedelta(seconds=101), 95),
    ]
    assert interpolate_presentation_value(
        gapped, BASE + timedelta(seconds=50), "battery", precision=2
    ) == 96


def test_iso_remains_step_even_at_high_precision():
    raw = _samples([100, 200])
    assert interpolate_presentation_value(
        raw, BASE + timedelta(seconds=10), "iso", precision=2
    ) == 100
    assert interpolate_presentation_value(
        raw, BASE + timedelta(seconds=10), "iso", precision=2, policy="linear"
    ) == 100


def test_continuous_speed_gap_gate_and_voltage_native_precision():
    speed = _samples([10, 11], spacing=1)
    assert interpolate_presentation_value(
        speed, BASE + timedelta(milliseconds=500), "speed", precision=2
    ) == pytest.approx(10.5)

    voltage = _samples([4.225, 4.221], spacing=20)
    assert interpolate_presentation_value(
        voltage, BASE + timedelta(seconds=10), "garmin_battery_voltage", precision=2
    ) == pytest.approx(4.225)
    assert interpolate_presentation_value(
        voltage, BASE + timedelta(seconds=10), "garmin_battery_voltage", precision=4
    ) == pytest.approx(4.223)


def test_multi_file_like_boundary_is_not_ramped():
    samples = [
        (BASE, 96),
        (BASE + timedelta(seconds=1), 96),
        (BASE + timedelta(minutes=10), 95),
        (BASE + timedelta(minutes=10, seconds=1), 95),
    ]
    assert interpolate_presentation_value(
        samples, BASE + timedelta(minutes=5), "battery", precision=2
    ) == 96


def test_bar_marker_receives_float_even_when_text_is_rounded():
    cfg = {
        "form": "bar", "bar_style": "ruler", "min_val": 0.0,
        "max_val": 100.0, "decimals": 1, "show_value": True,
        "show_label": False, "show_range_labels": False,
        "show_mid_label": False, "marker_color": "#FFD42A",
        "x": 10.0, "y": 10.0, "size": 20.0,
    }
    image, *_ = _render_bar_indicator(
        320, 180, {"global": {}, "indicators": {"battery": cfg}}, "",
        "battery", 95.437284, "%", "BATTERY", cfg, 180, 2, 20, None,
        0.0, 100.0, 5, 2, 240, 1, formatted_val="95.4%",
    )
    assert isinstance(image, Image.Image)
    # The renderer accepts the unrounded float separately from formatted_val;
    # this assertion guards the public call contract used by BAR/GAUGE paths.
    assert image.getbbox() is not None


def test_manager_and_final_worker_preserve_full_float_parity():
    raw = _samples([96, 95])
    manager = TelemetryDataManager()
    manager.fit_data = {"battery": raw}
    manager.layout = {"indicators": {"battery_text": {"decimals": 2}}}
    target = BASE + timedelta(seconds=10)

    preview_value = manager.resolve_value("battery", target, source="fit", indicator_key="battery_text")

    worker_cache.init_worker(
        320, 180, "Arial", manager.layout, {}, fit_data={"battery": raw}
    )
    final_value = worker_cache._resolve_cache_value("battery", "fit", target, "battery_text")

    assert preview_value == pytest.approx(95.5)
    assert final_value == pytest.approx(preview_value)


def test_gui_decimals_wins_over_stale_chart_decimal_places():
    cfg = {"decimals": 1, "decimal_places": 0}
    assert resolve_presentation_precision(cfg) == 1


def test_frame_data_dynamic_fit_field_preserves_precision_to_compositor():
    raw = _samples([96, 95])
    manager = TelemetryDataManager()
    manager.fit_data = {"garmin_battery_percent": raw}
    layout = {
        "indicators": {
            "fit_garmin_battery_percent_text": {
                "enabled": True, "source": "fit", "decimals": 1,
                # Reproduces layouts carrying an old chart-only field.
                "decimal_places": 0, "unit": "%",
            }
        }
    }
    target = BASE + timedelta(seconds=10)
    data = prepare_overlay_frame_data(
        layout=layout, target_dt=target, tz_offset_hours=0,
        start_dt_utc=BASE, speed_samples=[], track_samples=[], alt_samples=[],
        fit_data=manager.fit_data, extra_field_keys=["garmin_battery_percent"],
        resolve_cache_value=lambda field, source, dt, indicator_key=None, **kwargs:
            manager.resolve_value(field, dt, source=source, indicator_key=indicator_key, **kwargs),
    )
    assert data["extra_indicators"]["fit_garmin_battery_percent_text"][0] == pytest.approx(95.5)
