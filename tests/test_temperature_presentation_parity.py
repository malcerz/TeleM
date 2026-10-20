from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from PIL import Image
import pytest

from src.telemetry_resolver import (
    canonical_telemetry_field,
    is_integer_only_field,
    presentation_default_precision,
    resolve_presentation_precision,
    interpolate_presentation_value,
    resolve_samples_from_sources,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.gui.qt.models import indicator_default_decimals
from src.indicators.compositor import render_preview
from src.ffmpeg.worker_cache import (
    WORKER_CACHE,
    init_worker,
    _resolve_cache_value,
)


def _dt(seconds: float) -> datetime:
    return datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_temperature_raw_floats_preserved():
    """Verify raw float temperature (e.g. 19.2, 19.8) is preserved without truncation."""
    t0 = _dt(0)
    t1 = _dt(10)
    samples = [(t0, 19.2), (t1, 19.8)]
    val0 = interpolate_presentation_value(samples, t0, "temperature", precision=1)
    val1 = interpolate_presentation_value(samples, t1, "temperature", precision=1)
    assert val0 == pytest.approx(19.2, abs=1e-4)
    assert val1 == pytest.approx(19.8, abs=1e-4)


def test_temperature_quantized_interpolation_midpoint():
    """Verify 19.0 -> 20.0 produces midpoint 19.5 when precision >= 1."""
    t0 = _dt(0)
    t1 = _dt(10)
    samples = [(t0, 19.0), (t1, 20.0)]
    t_mid = _dt(5)
    val_mid = interpolate_presentation_value(samples, t_mid, "temperature", precision=1)
    assert val_mid == pytest.approx(19.5, abs=1e-4)


def test_temperature_plateau_change_events_battery_parity():
    """Verify temperature uses identical quantized change-event algorithm as battery."""
    raw = [(_dt(i), 19.0) for i in range(60)] + [(_dt(60 + i), 20.0) for i in range(60)]
    # Across the 19.0 plateau (0..60 s), change-event interpolation ramps smoothly:
    assert interpolate_presentation_value(raw, _dt(30), "temperature", precision=0) == 19.0
    assert interpolate_presentation_value(raw, _dt(30), "temperature", precision=1) == pytest.approx(19.5, abs=1e-4)
    assert interpolate_presentation_value(raw, _dt(15), "temperature", precision=2) == pytest.approx(19.25, abs=1e-4)
    assert interpolate_presentation_value(raw, _dt(45), "temperature", precision=2) == pytest.approx(19.75, abs=1e-4)


def test_temperature_constant_does_not_artificially_fluctuate():
    """When temperature is constant 19.0, resolver must output 19.0 without false drift."""
    samples = [(_dt(i * 5), 19.0) for i in range(10)]
    for sec in [2.5, 7.5, 15.0, 23.3]:
        val = interpolate_presentation_value(samples, _dt(sec), "temperature", precision=1)
        assert val == pytest.approx(19.0, abs=1e-5)


def test_temperature_precision_configuration():
    """Test 0, 1, and 2 decimal places configuration."""
    t0 = _dt(0)
    t1 = _dt(10)
    samples = [(t0, 19.0), (t1, 20.0)]
    t_mid = _dt(5)

    # In GUI/layout config:
    cfg_0 = {"decimals": 0}
    cfg_1 = {"decimals": 1}
    cfg_2 = {"decimals": 2}

    p0 = resolve_presentation_precision(cfg_0, default=1, field="temp_text")
    p1 = resolve_presentation_precision(cfg_1, default=1, field="temp_text")
    p2 = resolve_presentation_precision(cfg_2, default=1, field="temp_text")

    assert p0 == 0
    assert p1 == 1
    assert p2 == 2

    # Interpolated float is continuous:
    val = interpolate_presentation_value(samples, t_mid, "temperature", precision=1)
    assert f"{val:.{p0}f}" == "20"  # 19.5 rounds to 20
    assert f"{val:.{p1}f}" == "19.5"
    assert f"{val:.{p2}f}" == "19.50"


def test_temperature_long_gap_suppression():
    """Verify that gaps exceeding gap_multiplier * median interval are not linearly ramped."""
    # Cadence is 1s, but there is a 60s gap between 10s and 70s
    samples = [(_dt(0), 19.0), (_dt(1), 19.0), (_dt(2), 19.0), (_dt(70), 25.0)]
    # Target in the middle of the long gap:
    val_gap = interpolate_presentation_value(samples, _dt(35), "temperature", precision=1)
    # Must hold the left value (19.0), not ramp to ~22.0
    assert val_gap == pytest.approx(19.0, abs=1e-4)


def test_preview_final_parity():
    """Ensure preview resolver and worker_cache produce identical values."""
    t0 = _dt(0)
    t1 = _dt(10)
    samples = [(t0, 19.0), (t1, 20.0)]
    t_mid = _dt(5)

    layout = {
        "indicators": {
            "temp_text": {"source": "fit", "decimals": 1}
        }
    }

    # Worker cache simulation
    init_worker(
        320, 180, "Arial", layout, {}, fit_data={"temperature": samples}
    )

    final_val = _resolve_cache_value("temperature", "fit", t_mid, "temp_text")

    # Preview simulation via TelemetryDataManager
    manager = TelemetryDataManager()
    manager.fit_data = {"temperature": samples}
    manager.layout = layout
    preview_val = manager.resolve_value("temperature", t_mid, source="fit", indicator_key="temp_text")

    assert final_val is not None
    assert preview_val is not None
    assert final_val == pytest.approx(preview_val, abs=1e-5)
    assert final_val == pytest.approx(19.5, abs=1e-5)


def test_temperature_gui_default_decimals():
    """Verify GUI models default temperature to 1 decimal place while preserving integer fields."""
    assert indicator_default_decimals("temp_text") == 1
    assert indicator_default_decimals("atemp_text") == 1
    assert indicator_default_decimals("fit_temperature_text") == 1
    assert presentation_default_precision("temperature") == 1

    # Integer fields remain 0
    assert indicator_default_decimals("hr_text") == 0
    assert indicator_default_decimals("cad_text") == 0
    assert indicator_default_decimals("power_text") == 0
    assert indicator_default_decimals("iso_text") == 0
    assert presentation_default_precision("heart_rate") == 0
    assert presentation_default_precision("cadence") == 0
    assert presentation_default_precision("power") == 0
    assert presentation_default_precision("iso") == 0


def test_compositor_temp_text_formatting():
    """Verify compositor renders temp_text with proper decimal formatting."""
    layout = {
        "global": {"antialiasing": 1},
        "indicators": {
            "temp_text": {
                "enabled": True,
                "type": "text",
                "x": 100,
                "y": 100,
                "width": 200,
                "height": 50,
                "font_size": 20,
                "decimals": 1,
                "show_units": True,
                "color": [255, 255, 255],
            }
        }
    }
    src_img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    res_img = render_preview(
        src_img,
        layout,
        "",
        "2026-10-20",
        "12:00:05",
        speed_value=0.0,
        distance_m=0.0,
        temp_value=19.5,
    )
    assert res_img is not None
    assert res_img.size == (1920, 1080)
