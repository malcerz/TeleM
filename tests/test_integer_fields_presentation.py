"""Comprehensive tests for integer-only presentation fields (HR, Cadence, Power, ISO, Exposure)."""

from datetime import datetime, timezone, timedelta
import json
import pytest
from PIL import Image

from src.telemetry_resolver import (
    is_integer_only_field,
    resolve_presentation_precision,
    presentation_default_precision,
    resolve_current_presentation,
    presentation_value,
    canonical_telemetry_field,
)
from src.gui.qt.models import (
    get_schema_for_indicator,
    indicator_default_decimals,
    normalize_indicator_decimal_defaults,
)
from src.indicators import compositor
from src.indicators.helpers import resolve_decimal_places


@pytest.mark.parametrize("field_key,expected_is_int", [
    ("heart_rate", True),
    ("hr", True),
    ("fit_heart_rate_text", True),
    ("hr_text", True),
    ("cadence", True),
    ("cad", True),
    ("fit_cadence_text", True),
    ("cad_text", True),
    ("power", True),
    ("curvpower", True),
    ("fit_power_text", True),
    ("power_text", True),
    ("iso", True),
    ("iso_text", True),
    ("exposure", True),
    ("exposure_text", True),
    # Non-integer fields
    ("speed", False),
    ("speed_text", False),
    ("distance", False),
    ("dist_text", False),
    ("alt", False),
    ("altitude", False),
    ("garmin_battery_percent", False),
    ("battery_text", False),
    ("temperature", False),
    ("temp_text", False),
])
def test_field_detection_policy(field_key, expected_is_int):
    assert is_integer_only_field(field_key) is expected_is_int
    assert is_integer_only_field("custom_indicator", {"field": field_key}) is expected_is_int


def test_internal_float_precision_preserved_during_interpolation():
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Power ramp from 200.0 to 300.0 over 10 seconds (power is continuous float in resolver)
    samples = [(start, 200.0), (start + timedelta(seconds=10), 300.0)]
    
    # At t=2.5s, interpolated float is 225.0 (internal math is not degraded or truncated to int)
    val = presentation_value(samples, start + timedelta(seconds=2.5), "power", indicator_config={})
    assert isinstance(val, float)
    assert abs(val - 225.0) < 1e-6

    # curVpower also preserves full float precision
    curv_val = presentation_value(samples, start + timedelta(seconds=2.5), "curVpower", indicator_config={})
    assert isinstance(curv_val, float)
    assert abs(curv_val - 225.0) < 1e-6


def test_presentation_precision_enforces_zero_for_integer_fields():
    # Even if config explicitly contains decimals=1 or 2, resolve_presentation_precision MUST return 0
    for field in ["heart_rate", "cadence", "power", "iso", "exposure", "fit_heart_rate_text", "cad_text"]:
        assert resolve_presentation_precision({"decimals": 1}, default=1, field=field) == 0
        assert resolve_presentation_precision({"decimals": 2}, default=2, field=field) == 0
        assert resolve_presentation_precision({"decimal_places": 1}, default=1, field=field) == 0
        assert presentation_default_precision(field) == 0
        assert resolve_decimal_places({"decimals": 1}, default=1, field=field) == 0
        assert resolve_decimal_places({"decimal_places": 2}, default=1, field=field) == 0


def test_exact_rounding_examples():
    # HR: 87.0 -> 87, 87.4 -> 87, 87.6 -> 88
    for raw_hr, expected_str in [(87.0, "87"), (87.4, "87"), (87.6, "88")]:
        decimals = resolve_presentation_precision({}, field="heart_rate")
        assert f"{raw_hr:.{decimals}f}" == expected_str
        assert "." not in expected_str

    # Cadence: 81.0 -> 81, 81.7 -> 82
    for raw_cad, expected_str in [(81.0, "81"), (81.7, "82")]:
        decimals = resolve_presentation_precision({}, field="cadence")
        assert f"{raw_cad:.{decimals}f}" == expected_str
        assert "." not in expected_str

    # Power: 254.0 -> 254, 254.6 -> 255
    for raw_pwr, expected_str in [(254.0, "254"), (254.6, "255")]:
        decimals = resolve_presentation_precision({}, field="power")
        assert f"{raw_pwr:.{decimals}f}" == expected_str
        assert "." not in expected_str

    # ISO: 100.0 -> 100
    decimals_iso = resolve_presentation_precision({}, field="iso")
    assert f"{100.0:.{decimals_iso}f}" == "100"

    # Exposure: 247.0 -> 247 (formatted as 1/247 in shutter presentation)
    exp_val = int(round(float(247.0)))
    assert exp_val == 247
    assert f"1/{exp_val}" == "1/247"


def test_gui_schema_omits_decimals_for_integer_fields():
    # Integer fields must NOT expose decimals or decimal_places in GUI property editor
    for key in ["fit_heart_rate_text", "hr_text", "fit_cadence_text", "cad_text",
                "fit_power_text", "power_text", "iso_text", "exposure_text"]:
        for form in ["text", "gauge", "bar", "chart"]:
            schema = get_schema_for_indicator(key, form)
            field_names = [f.name for f in schema]
            assert "decimals" not in field_names, f"Key {key} form {form} has 'decimals' in schema"
            assert "decimal_places" not in field_names, f"Key {key} form {form} has 'decimal_places' in schema"

    # Custom indicator with semantic field
    custom_schema = get_schema_for_indicator("custom_stat", "text", cfg={"field": "heart_rate"})
    assert "decimals" not in [f.name for f in custom_schema]


def test_gui_schema_retains_decimals_for_other_fields():
    # Speed (0..2 configurable)
    speed_schema = get_schema_for_indicator("speed_text", "text")
    decimals_f = next((f for f in speed_schema if f.name == "decimals"), None)
    assert decimals_f is not None
    assert decimals_f.min_val == 0
    assert decimals_f.max_val == 2

    # Temperature (1 decimal default)
    temp_schema = get_schema_for_indicator("temp_text", "text")
    decimals_t = next((f for f in temp_schema if f.name == "decimals"), None)
    assert decimals_t is not None
    assert decimals_t.min_val == 0
    assert decimals_t.max_val == 2

    # Garmin Battery (2 decimals default)
    batt_schema = get_schema_for_indicator("fit_garmin_battery_percent_text", "text")
    decimals_b = next((f for f in batt_schema if f.name == "decimals"), None)
    assert decimals_b is not None
    assert decimals_b.default == 2


def test_layout_backward_compatibility_normalizes_and_omits():
    old_layout = {
        "indicators": {
            "hr_text": {"form": "text", "decimals": 1, "field": "heart_rate"},
            "cad_text": {"form": "text", "decimal_places": 2, "field": "cadence"},
            "power_text": {"form": "text", "decimals": 1, "field": "power"},
            "iso_text": {"form": "text", "decimals": 1},
            "exposure_text": {"form": "text", "decimals": 1},
            "speed_text": {"form": "text", "decimals": 2},
            "fit_garmin_battery_percent_text": {"form": "text", "decimals": 2},
        }
    }
    
    # 1. Normalization cleans integer fields and preserves configurable fields
    normalized = normalize_indicator_decimal_defaults(old_layout)
    assert "decimals" not in normalized["indicators"]["hr_text"]
    assert "decimal_places" not in normalized["indicators"]["cad_text"]
    assert "decimals" not in normalized["indicators"]["power_text"]
    assert "decimals" not in normalized["indicators"]["iso_text"]
    assert "decimals" not in normalized["indicators"]["exposure_text"]
    assert normalized["indicators"]["speed_text"]["decimals"] == 2
    assert normalized["indicators"]["fit_garmin_battery_percent_text"]["decimals"] == 2

    # 2. Even before normalization, presentation resolver ignores old decimals: 1
    unnormalized_hr_cfg = {"decimals": 1, "field": "heart_rate"}
    assert resolve_presentation_precision(unnormalized_hr_cfg, field="heart_rate") == 0


def test_compositor_presentation_outputs_pure_integers(monkeypatch):
    rendered_strings = {}

    def fake_render(*args, **kwargs):
        rendered_strings[args[4]] = kwargs.get("formatted_val")
        return Image.new("RGBA", (1, 1)), 0, 0, {}

    monkeypatch.setattr(compositor, "render_value_indicator", fake_render)

    layout = {
        "indicators": {
            "hr_text": {"enabled": True, "form": "text", "show_value": True, "show_units": False, "decimals": 2},
            "cad_text": {"enabled": True, "form": "text", "show_value": True, "show_units": False, "decimals": 1},
            "power_text": {"enabled": True, "form": "text", "show_value": True, "show_units": False, "decimals": 1},
            "iso_text": {"enabled": True, "form": "text", "show_value": True, "show_units": False, "decimals": 2},
            "exposure_text": {"enabled": True, "form": "text", "show_value": True, "show_units": False, "decimals": 1},
        }
    }

    compositor.compose_overlay(
        64, 64, layout, "", "", "", 0, 0,
        hr_value=87.6,
        cad_value=81.7,
        power_value=254.6,
        iso_value=100.0,
        exposure_value=247.0,
        reuse_canvas=False,
    )

    assert rendered_strings["hr_text"] == "88"
    assert rendered_strings["cad_text"] == "82"
    assert rendered_strings["power_text"] == "255"
    assert rendered_strings["iso_text"] == "100"
    assert rendered_strings["exposure_text"] == "1/247"
