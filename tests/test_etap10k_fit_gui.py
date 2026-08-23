import pytest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from telemetry_fit import parse_fit, sync_fit_to_video, FitRecords, FitDataset
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import interpolate_value
from src.gui.indicator_schemas import get_value_schema
from src.gui.qt.models import get_schema_for_form, compass_indicator_fields
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin, DataStream
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.indicators.bar import _render_ruler

FIT_PATH = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
VIDEO_PATH = Path("Video/GX010115.MP4")


class MockSignals:
    def __init__(self):
        self.properties = []
        self.errors = []
    def emit(self, *args):
        pass


class MockController(IndicatorMixin):
    def __init__(self, tm):
        self.signals = MockSignals()
        self.signals.sig_properties_ready = self.signals
        self.signals.sig_error = self.signals
        self.telemetry = tm
        self.layout = {"version": 10, "indicators": {}}
        self.font_path = ""
        self._prepare_cache = {}
        self._chart_data_cache = None

    def _render_preview(self):
        pass


def test_fit_parser_developer_field_identities():
    records = parse_fit(FIT_PATH)
    assert records is not None
    assert isinstance(records, FitRecords)
    assert len(records) == 4299

    # Verify field catalog
    catalog = records.field_catalog
    assert "battery_pct_2_1" in catalog
    assert "battery_pct_3_2" in catalog
    assert "battery_pct" in catalog  # backward compatibility alias
    assert "solar_pct" in catalog
    assert "solar" in catalog
    assert "curVpower" in catalog
    assert "battery" in catalog
    assert "temperature" in catalog
    assert "discharge" in catalog
    assert "K1" in catalog
    assert "K2" in catalog

    assert catalog["battery_pct_2_1"]["is_dev"] is True
    assert catalog["battery_pct_2_1"]["dev_data_index"] == 2
    assert catalog["battery_pct_2_1"]["field_def_num"] == 1
    assert catalog["battery_pct_3_2"]["dev_data_index"] == 3
    assert catalog["battery_pct_3_2"]["field_def_num"] == 2


def test_fit_sync_and_dataset():
    records = parse_fit(FIT_PATH)
    dataset = sync_fit_to_video(records, video_start_dt=None)
    assert isinstance(dataset, FitDataset)
    assert len(dataset["battery_pct_2_1"]) == 2340
    assert len(dataset["battery_pct_3_2"]) == 4299
    assert len(dataset["solar_pct"]) == 2340
    assert len(dataset["solar"]) == 4299
    assert len(dataset["curVpower"]) == 4299
    assert len(dataset["temperature"]) == 4299
    assert len(dataset["battery"]) == 4299


def test_gui_stream_discovery():
    tm = TelemetryDataManager(interpolate_fn=interpolate_value)
    tm.load_fit(VIDEO_PATH, manual_path=FIT_PATH)

    ctrl = MockController(tm)
    streams = ctrl._discover_data_streams()
    stream_keys = {s.key: s for s in streams}

    expected_keys = [
        "fit_temperature_text",
        "fit_solar_text",
        "fit_solar_pct_text",
        "fit_curVpower_text",
        "fit_battery_text",
        "fit_battery_pct_text",
        "fit_battery_pct_2_1_text",
        "fit_battery_pct_3_2_text",
    ]
    for k in expected_keys:
        assert k in stream_keys, f"Expected {k} in discovered streams"

    assert stream_keys["fit_temperature_text"].unit == "°C"
    assert stream_keys["fit_curVpower_text"].unit == "W"
    assert stream_keys["fit_solar_text"].unit == "%"
    assert stream_keys["fit_solar_pct_text"].unit == "%"
    assert stream_keys["fit_battery_text"].unit == "%"


def test_gui_add_indicator_defaults():
    tm = TelemetryDataManager(interpolate_fn=interpolate_value)
    tm.load_fit(VIDEO_PATH, manual_path=FIT_PATH)

    ctrl = MockController(tm)

    for k in ["fit_temperature_text", "fit_solar_text", "fit_curVpower_text", "fit_battery_text"]:
        ctrl._on_stream_clicked(k)
        assert k in ctrl.layout["indicators"]
        cfg = ctrl.layout["indicators"][k]
        assert cfg["enabled"] is True
        assert cfg["source"] == "fit"
        assert cfg["label"] != k  # Must be friendly label, not raw key name
        assert cfg["unit"] != ""   # Must have unit populated


def test_gui_size_limit_100():
    # Schema check
    schema = get_value_schema()
    size_field = next(f for f in schema if f[0] == "size")
    assert size_field[3] >= 100.0, "Size schema max should be >= 100.0"

    # Property editor schema check
    form_schema = get_schema_for_form("bar")
    size_schema_field = next(f for f in form_schema if f.name == "size")
    assert size_schema_field.max_val >= 100.0, "Model schema max should be >= 100.0"


def test_major_step_ruler():
    from src.indicators.bar import _render_bar_indicator
    # 1. Distance ruler with default major_step = 1.0 km
    cfg_dist = {
        "x": 50.0, "y": 50.0, "size": 15.0, "form": "bar", "bar_style": "ruler",
        "min_val": 0.0, "max_val": 5.0, "unit": "km", "label": "Distance",
    }
    img1, x1, y1, _ = _render_bar_indicator(
        1280, 720, {"indicators": {"dist": cfg_dist}}, "", "dist", 2.5, "km", "Distance",
        cfg_dist, 720, 1, 20, None, 0.0, 5.0, 0, 2, 200, 2,
    )
    assert img1 is not None

    # 2. Temperature ruler with default major_step = 1.0 °C
    cfg_temp = {
        "x": 50.0, "y": 50.0, "size": 15.0, "form": "bar", "bar_style": "ruler",
        "min_val": 20.0, "max_val": 40.0, "unit": "°C", "label": "Temperature",
    }
    img2, x2, y2, _ = _render_bar_indicator(
        1280, 720, {"indicators": {"temp": cfg_temp}}, "", "temp", 30.0, "°C", "Temperature",
        cfg_temp, 720, 1, 20, None, 20.0, 40.0, 0, 2, 200, 2,
    )
    assert img2 is not None

    # 3. Explicit major_step override
    cfg_override = {
        "x": 50.0, "y": 50.0, "size": 15.0, "form": "bar", "bar_style": "ruler",
        "min_val": 0.0, "max_val": 10.0, "unit": "km", "label": "Distance", "major_step": 2.0,
    }
    img3, x3, y3, _ = _render_bar_indicator(
        1280, 720, {"indicators": {"dist": cfg_override}}, "", "dist", 4.0, "km", "Distance",
        cfg_override, 720, 1, 20, None, 0.0, 10.0, 0, 2, 200, 2,
    )
    assert img3 is not None


def test_overlay_rendering_with_added_fit_indicators():
    tm = TelemetryDataManager(interpolate_fn=interpolate_value)
    tm.load_fit(VIDEO_PATH, manual_path=FIT_PATH)

    ctrl = MockController(tm)
    for k in [
        "fit_temperature_text",
        "fit_solar_text",
        "fit_solar_pct_text",
        "fit_curVpower_text",
        "fit_battery_text",
        "fit_battery_pct_text",
    ]:
        ctrl._on_stream_clicked(k)

    t0 = tm.fit_data["speed"][0][0]
    frame_data = prepare_overlay_frame_data(
        layout=ctrl.layout,
        target_dt=t0,
        tz_offset_hours=0.0,
        start_dt_utc=t0,
        speed_samples=tm.fit_data.get("speed", []),
        track_samples=tm.fit_data.get("track", []),
        alt_samples=tm.fit_data.get("alt", []),
        fit_data=tm.fit_data,
        resolve_cache_value=lambda k, src, dt, indicator_key=None: tm.resolve_value(
            k, dt, source=src, indicator_key=indicator_key
        ),
    )

    overlay = compose_overlay(
        1280, 720, ctrl.layout, "",
        frame_data["date_text"], frame_data["time_text"],
        frame_data["speed_value"], frame_data["distance_m"], frame_data["max_distance_m"],
        frame_data["alt_value"], frame_data["min_alt"], frame_data["max_alt"],
        frame_data["iso_value"], frame_data["exposure_value"], frame_data["temp_value"],
        indicator_values=frame_data["indicator_values"],
        max_speed_kmh=frame_data["max_speed_kmh"],
        power_value=frame_data["power_value"],
        atemp_value=frame_data["atemp_value"],
        hr_value=frame_data["hr_value"],
        cad_value=frame_data["cad_value"],
        battery_value=frame_data["battery_value"],
        extra_indicators=frame_data["extra_indicators"],
        chart_data=frame_data["chart_data"],
        current_position=0.0,
        gps_track=frame_data["gps_track"],
        target_dt=frame_data["target_dt"],
        start_dt_utc=frame_data["start_dt_utc"],
        elapsed_seconds=frame_data["elapsed_seconds"],
        avg_speed_kmh=frame_data["avg_speed_kmh"],
    )
    assert overlay is not None
    assert overlay.size == (1280, 720)
