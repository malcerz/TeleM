"""Regression tests for canonical GoPro Battery and ISO decimal defaults."""

from datetime import datetime, timezone, timedelta
import json

from src.gui.qt.models import (
    get_schema_for_indicator,
    normalize_indicator_decimal_defaults,
)
from src.telemetry_resolver import resolve_current_presentation
from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators import compositor
from src.indicators.bar import _render_segments, _resolve_range_decimals
from PIL import Image


def _decimals_field(key: str, form: str = "text"):
    fields = get_schema_for_indicator(key, form, bar_style="segments")
    return next(field for field in fields if field.name == "decimals")


def test_gopro_battery_decimals_property_is_generic_and_zero_default():
    field = _decimals_field("fit_gopro_battery_text", "bar")
    assert field.min_val == 0
    assert field.max_val == 3
    assert field.default == 0
    assert field.label == "Liczba miejsc po przecinku"


def test_gopro_battery_decimal_format_matrix():
    value = 47.43851
    assert f"{value:.0f}%" == "47%"
    assert f"{value:.1f}%" == "47.4%"
    assert f"{value:.2f}%" == "47.44%"
    assert f"{value:.3f}%" == "47.439%"


def test_iso_default_schema_and_step_semantics():
    assert _decimals_field("iso_text").default == 0
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    samples = [(start, 100.0), (start + timedelta(seconds=1), 200.0)]
    cfg = {"decimals": 0, "interpolation_policy": "linear"}
    assert resolve_current_presentation(samples, start + timedelta(seconds=.5), "iso", cfg) == 100.0


def test_legacy_layout_gets_canonical_defaults_and_round_trips(tmp_path):
    layout = {
        "indicators": {
            "fit_gopro_battery_text": {"form": "bar"},
            "iso_text": {"form": "text", "decimal_places": 1},
        }
    }
    normalize_indicator_decimal_defaults(layout)
    assert layout["indicators"]["fit_gopro_battery_text"]["decimals"] == 0
    assert layout["indicators"]["iso_text"]["decimals"] == 0

    path = tmp_path / "layout.json"
    path.write_text(json.dumps(layout), encoding="utf-8")
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    normalize_indicator_decimal_defaults(reloaded)
    assert reloaded["indicators"]["fit_gopro_battery_text"]["decimals"] == 0
    assert reloaded["indicators"]["iso_text"]["decimals"] == 0


def test_explicit_decimal_setting_is_preserved():
    layout = {"indicators": {"iso_text": {"decimals": 2}}}
    normalize_indicator_decimal_defaults(layout)
    assert layout["indicators"]["iso_text"]["decimals"] == 2


def test_compositor_uses_integer_iso_default_without_string_hack(monkeypatch):
    seen = {}

    def fake_render(*args, **kwargs):
        seen[args[4]] = kwargs.get("formatted_val")
        return Image.new("RGBA", (1, 1)), 0, 0, {}

    monkeypatch.setattr(compositor, "render_value_indicator", fake_render)
    layout = {"indicators": {"iso_text": {
        "enabled": True, "form": "text", "show_value": True,
        "show_units": True, "unit": "ISO", "x": 50, "y": 50,
    }}}
    compositor.compose_overlay(
        32, 32, layout, "", "", "", 0, 0, iso_value=800.0,
        reuse_canvas=False,
    )
    assert seen["iso_text"] == "800"


def test_percent_bar_range_labels_are_independent_of_current_decimals():
    cfg = {}
    assert _resolve_range_decimals(cfg, 2, 0.0, 100.0, percent_scale=True) == 0
    assert _resolve_range_decimals({"range_decimals": 1}, 2, 0.0, 100.0,
                                   percent_scale=True) == 1


def test_non_percent_bar_ranges_keep_value_precision():
    assert _resolve_range_decimals({}, 1, 0.0, 8.3, percent_scale=False) == 1
    assert _resolve_range_decimals({}, 2, 0.0, 8.3, percent_scale=False) == 2


def test_segment_renderer_formats_battery_range_as_integer(monkeypatch):
    import src.indicators.bar as bar
    calls = []
    original = bar._fmt_number

    def observe(value, decimals):
        calls.append((float(value), int(decimals)))
        return original(value, decimals)

    monkeypatch.setattr(bar, "_fmt_number", observe)
    _render_segments(
        canvas_w=320, canvas_h=180, font_path="", value=95.48, unit="%",
        label="Garmin Battery %", cfg={"field": "garmin_battery_percent",
        "decimals": 2, "show_min": True, "show_max": True,
        "show_value": True, "show_label": True, "segments": 10},
        val_min=0.0, val_max=100.0, size_px=120, fs=16, outline=1, ss=1,
        formatted_val=None,
    )
    assert (0.0, 0) in calls
    assert (100.0, 0) in calls
    assert any(value == 95.48 and decimals == 2 for value, decimals in calls)


def test_garmin_battery_frame0_and_exact_start_seek_are_numeric():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    samples = [(start - timedelta(seconds=2), 96.0), (start, 95.9)]
    manager = TelemetryDataManager()
    manager.fit_data = {"garmin_battery_percent": samples}
    layout = {"indicators": {"fit_garmin_battery_percent_text": {
        "enabled": True, "source": "fit", "unit": "%", "decimals": 2,
    }}}
    data = prepare_overlay_frame_data(
        layout=layout, target_dt=start, tz_offset_hours=0,
        start_dt_utc=start, speed_samples=[], track_samples=[], alt_samples=[],
        fit_data=manager.fit_data, extra_field_keys=["garmin_battery_percent"],
        resolve_cache_value=lambda field, source, dt, indicator_key=None, **kw:
            manager.resolve_value(field, dt, source=source, indicator_key=indicator_key, **kw),
    )
    assert data["extra_indicators"]["fit_garmin_battery_percent_text"][0] is not None
    assert data["extra_indicators"]["fit_garmin_battery_percent_text"][0] == 95.9
