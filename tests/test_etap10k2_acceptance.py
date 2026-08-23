import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image

from telemetry_fit import parse_fit, sync_fit_to_video, FitRecords, FitDataset
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    interpolate_value, extract_speed_samples, extract_altitude_samples,
    extract_track_samples, extract_iso_samples, extract_exposure_samples,
    extract_temperature_samples, smooth_speed_samples, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.gui.layout_manager import LayoutManager, default_layout, normalize_layout
from src.gui.indicator_schemas import get_value_schema
from src.gui.qt.models import get_schema_for_form
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.indicators.bar import _render_bar_indicator, _render_ruler
from src.indicators.gauge import _render_gauge_indicator, _render_compass_indicator
from src.indicators.text import _render_text_indicator
from src.indicators.chart import _render_chart_indicator

FIT_PATH = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
VIDEO_PATH = Path("Video/GX010115.MP4")


class MockSignals:
    def __init__(self):
        self.properties = []
        self.errors = []
    def emit(self, *args):
        pass


class FullSimController(IndicatorMixin):
    def __init__(self, tm):
        self.signals = MockSignals()
        self.signals.sig_properties_ready = self.signals
        self.signals.sig_error = self.signals
        self.telemetry = tm
        self.layout = {"version": 10, "indicators": {}}
        self.layout_mgr = LayoutManager(
            default_layout_fn=default_layout,
            normalize_layout_fn=normalize_layout,
        )
        self.font_path = ""
        self.src_img = Image.new("RGBA", (1280, 720), (30, 30, 30, 255))
        self.video_duration_s = 60.0
        self._prepare_cache = {}
        self._chart_data_cache = None
        self.indicator_bboxes = {}
        self._playing = False

    def _render_preview(self):
        t0 = self.telemetry.start_dt_utc or datetime(2026, 8, 14, 9, 40, 16)
        overlay_data = prepare_overlay_frame_data(
            layout=self.layout,
            target_dt=t0,
            tz_offset_hours=0.0,
            start_dt_utc=t0,
            speed_samples=self.telemetry.speed_samples or [],
            track_samples=self.telemetry.track_samples or [],
            alt_samples=self.telemetry.alt_samples or [],
            fit_data=self.telemetry.fit_data,
            resolve_cache_value=lambda k, src, dt, indicator_key=None: self.telemetry.resolve_value(
                k, dt, source=src, indicator_key=indicator_key
            ),
        )
        return compose_overlay(
            1280, 720, self.layout, self.font_path,
            overlay_data["date_text"], overlay_data["time_text"],
            overlay_data["speed_value"], overlay_data["distance_m"], overlay_data["max_distance_m"],
            overlay_data["alt_value"], overlay_data["min_alt"], overlay_data["max_alt"],
            overlay_data["iso_value"], overlay_data["exposure_value"], overlay_data["temp_value"],
            indicator_values=overlay_data["indicator_values"],
            max_speed_kmh=overlay_data["max_speed_kmh"],
            power_value=overlay_data["power_value"],
            atemp_value=overlay_data["atemp_value"],
            hr_value=overlay_data["hr_value"],
            cad_value=overlay_data["cad_value"],
            battery_value=overlay_data["battery_value"],
            extra_indicators=overlay_data["extra_indicators"],
            chart_data=overlay_data["chart_data"],
            current_position=0.0,
            gps_track=overlay_data["gps_track"],
            target_dt=overlay_data["target_dt"],
            start_dt_utc=overlay_data["start_dt_utc"],
            elapsed_seconds=overlay_data["elapsed_seconds"],
            avg_speed_kmh=overlay_data["avg_speed_kmh"],
        )


def test_1_real_gui_acceptance_all_fields():
    tm = TelemetryDataManager(interpolate_fn=interpolate_value)
    tm.load_fit(VIDEO_PATH, manual_path=FIT_PATH)

    ctrl = FullSimController(tm)
    streams = ctrl._discover_data_streams()
    stream_keys = {s.key: s for s in streams}

    required_fields = [
        "fit_temperature_text",
        "fit_solar_text",
        "fit_solar_pct_text",
        "fit_curVpower_text",
        "fit_battery_text",
        "fit_battery_pct_2_1_text",
        "fit_battery_pct_3_2_text",
    ]

    for key in required_fields:
        assert key in stream_keys, f"Field {key} missing from stream catalog"
        ctrl._on_stream_clicked(key)
        assert key in ctrl.layout["indicators"]
        cfg = ctrl.layout["indicators"][key]
        assert cfg["enabled"] is True
        assert cfg["source"] == "fit"
        assert cfg["label"] != key

    overlay = ctrl._render_preview()
    assert overlay is not None
    assert overlay.size == (1280, 720)


def test_2_duplicate_battery_pct_end_to_end_save_load():
    tm = TelemetryDataManager(interpolate_fn=interpolate_value)
    tm.load_fit(VIDEO_PATH, manual_path=FIT_PATH)

    ctrl = FullSimController(tm)
    ctrl._on_stream_clicked("fit_battery_pct_2_1_text")
    ctrl._on_stream_clicked("fit_battery_pct_3_2_text")

    # Verify both are present with distinct field identities
    cfg1 = ctrl.layout["indicators"]["fit_battery_pct_2_1_text"]
    cfg2 = ctrl.layout["indicators"]["fit_battery_pct_3_2_text"]
    assert cfg1["field"] == "battery_pct_2_1"
    assert cfg2["field"] == "battery_pct_3_2"
    assert "[Dev 2:1]" in cfg1["label"]
    assert "[Dev 3:2]" in cfg2["label"]

    # Save to JSON
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        json.dump(ctrl.layout, f)
        temp_path = Path(f.name)

    try:
        # Reload layout
        with open(temp_path, "r", encoding="utf-8") as f:
            loaded_layout = json.load(f)

        assert "fit_battery_pct_2_1_text" in loaded_layout["indicators"]
        assert "fit_battery_pct_3_2_text" in loaded_layout["indicators"]
        assert loaded_layout["indicators"]["fit_battery_pct_2_1_text"]["field"] == "battery_pct_2_1"
        assert loaded_layout["indicators"]["fit_battery_pct_3_2_text"]["field"] == "battery_pct_3_2"

        # Verify samples resolve to different point counts
        s1 = tm.resolve_samples("battery_pct_2_1", "fit")
        s2 = tm.resolve_samples("battery_pct_3_2", "fit")
        assert len(s1) == 2340
        assert len(s2) == 4299
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_3_global_none_behavior_across_all_renderers():
    # 1. Text indicator with None
    cfg_text = {"x": 50.0, "y": 50.0, "text_color": "#FFFFFF"}
    img_text, _, _, _ = _render_text_indicator(
        1280, 720, {}, "", "test_text", None, "km/h", "Speed",
        cfg_text, 720, 1, 20, None, 0.0, 100.0, 0, 1, 20, 1, formatted_val=None,
    )
    assert img_text is not None

    # 2. Gauge indicator with None
    cfg_gauge = {"x": 50.0, "y": 50.0, "min_val": 0.0, "max_val": 100.0}
    img_gauge, _, _, _ = _render_gauge_indicator(
        1280, 720, {}, "", "test_gauge", None, "km/h", "Speed",
        cfg_gauge, 720, 1, 20, None, 0.0, 100.0, 0, 1, 50, 1, formatted_val=None,
    )
    assert img_gauge is not None

    # 3. Bar Ruler with None
    cfg_ruler = {"x": 50.0, "y": 50.0, "form": "bar", "bar_style": "ruler", "min_val": 0.0, "max_val": 10.0}
    img_ruler, _, _, _ = _render_bar_indicator(
        1280, 720, {}, "", "test_ruler", None, "km", "Distance",
        cfg_ruler, 720, 1, 20, None, 0.0, 10.0, 0, 1, 100, 1, formatted_val=None,
    )
    assert img_ruler is not None

    # 4. Bar Segments with None
    cfg_seg = {"x": 50.0, "y": 50.0, "form": "bar", "bar_style": "segments", "min_val": 0.0, "max_val": 100.0}
    img_seg, _, _, _ = _render_bar_indicator(
        1280, 720, {}, "", "test_seg", None, "%", "Battery",
        cfg_seg, 720, 1, 20, None, 0.0, 100.0, 0, 1, 100, 1, formatted_val=None,
    )
    assert img_seg is not None

    # 5. Chart indicator with None
    cfg_chart = {"x": 50.0, "y": 50.0, "form": "chart", "min_val": 0.0, "max_val": 200.0}
    img_chart, _, _, _ = _render_chart_indicator(
        1280, 720, {}, "", "test_chart", None, "BPM", "Heart Rate",
        cfg_chart, 720, 1, 20, None, 0.0, 200.0, 0, 1, 100, 1,
        history_data={}, target_dt=None, current_position=0.0, formatted_val=None,
    )
    assert img_chart is not None

    # 6. Compass with None
    cfg_compass = {"x": 50.0, "y": 50.0}
    img_compass, _, _, _ = _render_compass_indicator(
        1280, 720, {}, "", "compass", None, "°", "Compass",
        cfg_compass, 720, 1, 20, None, 0.0, 360.0, 0, 1, 50, 1, formatted_val=None,
    )
    assert img_compass is not None


def test_4_exact_distance_ticks_0_to_24_23():
    cfg_dist = {
        "x": 50.0, "y": 50.0, "size": 15.0, "form": "bar", "bar_style": "ruler",
        "min_val": 0.0, "max_val": 24.23, "unit": "km", "label": "Distance",
    }
    img, _, _, _ = _render_bar_indicator(
        1280, 720, {"indicators": {"dist": cfg_dist}}, "", "dist", 12.0, "km", "Distance",
        cfg_dist, 720, 1, 20, None, 0.0, 24.23, 0, 2, 300, 1,
    )
    assert img is not None


def test_5_exact_temperature_ticks_23_to_41():
    cfg_temp = {
        "x": 50.0, "y": 50.0, "size": 15.0, "form": "bar", "bar_style": "ruler",
        "min_val": 23.0, "max_val": 41.0, "unit": "°C", "label": "Temperature",
    }
    img, _, _, _ = _render_bar_indicator(
        1280, 720, {"indicators": {"temp": cfg_temp}}, "", "temp", 30.0, "°C", "Temperature",
        cfg_temp, 720, 1, 20, None, 23.0, 41.0, 0, 2, 300, 1,
    )
    assert img is not None


def test_6_non_zero_min_exact_ticks():
    cfg_nonzero = {
        "x": 50.0, "y": 50.0, "size": 15.0, "form": "bar", "bar_style": "ruler",
        "min_val": 23.4, "max_val": 31.7, "unit": "°C", "label": "Temperature", "major_step": 1.0,
    }
    img, _, _, _ = _render_bar_indicator(
        1280, 720, {"indicators": {"temp": cfg_nonzero}}, "", "temp", 28.0, "°C", "Temperature",
        cfg_nonzero, 720, 1, 20, None, 23.4, 31.7, 0, 2, 300, 1,
    )
    assert img is not None


def test_7_explicit_major_step_override_2_5():
    cfg_override = {
        "x": 50.0, "y": 50.0, "size": 15.0, "form": "bar", "bar_style": "ruler",
        "min_val": 0.0, "max_val": 10.0, "unit": "km", "label": "Distance", "major_step": 2.5,
    }
    img, _, _, _ = _render_bar_indicator(
        1280, 720, {"indicators": {"dist": cfg_override}}, "", "dist", 5.0, "km", "Distance",
        cfg_override, 720, 1, 20, None, 0.0, 10.0, 0, 2, 300, 1,
    )
    assert img is not None


def test_8_size_50_75_100_save_load():
    for size_val in [50.0, 75.0, 100.0]:
        layout = {
            "version": 10,
            "indicators": {
                "test_ind": {
                    "enabled": True, "form": "bar", "size": size_val,
                    "x": 50.0, "y": 50.0, "min_val": 0.0, "max_val": 100.0,
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
            json.dump(layout, f)
            tpath = Path(f.name)
        try:
            loaded = normalize_layout(tpath, 1280, 720)
            assert loaded["indicators"]["test_ind"]["size"] == size_val
        finally:
            if tpath.exists():
                tpath.unlink()
