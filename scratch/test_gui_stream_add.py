import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from datetime import datetime, timezone, timedelta
from PIL import Image

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    interpolate_value, extract_speed_samples, extract_altitude_samples,
    extract_track_samples, extract_iso_samples, extract_exposure_samples,
    extract_temperature_samples, smooth_speed_samples, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples
)
from src.gui.layout_manager import LayoutManager, default_layout, normalize_layout
from src.gui.indicator_schemas import BUILTIN_FIELDS, get_value_schema
from src.gui.qt.models import get_schema_for_form, compass_indicator_fields
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay

class MockSignals:
    def __init__(self):
        self.properties_ready = []
        self.errors = []
    def emit(self, *args):
        pass

class MockSigHolder:
    def __init__(self):
        self.sig_properties_ready = self
        self.sig_error = self
        self.sig_progress = self
        self.sig_data_streams_ready = self
    def emit(self, *args):
        # print("EMIT:", args[0] if args else "")
        pass

class SimController(IndicatorMixin):
    def __init__(self):
        self.signals = MockSigHolder()
        self.telemetry = TelemetryDataManager(
            extract_speed_fn=extract_speed_samples,
            extract_altitude_fn=extract_altitude_samples,
            extract_track_fn=extract_track_samples,
            extract_iso_fn=extract_iso_samples,
            extract_exposure_fn=extract_exposure_samples,
            extract_temperature_fn=extract_temperature_samples,
            smooth_fn=smooth_speed_samples,
            interpolate_fn=interpolate_value,
            extract_gps_track_fn=extract_gps_track,
            smooth_values_fn=smooth_speed_values,
            extract_accelerometer_fn=extract_accelerometer_samples,
            extract_gyroscope_fn=extract_gyroscope_samples,
        )
        self.layout = {"version": 10, "indicators": {}}
        self.layout_mgr = LayoutManager(
            default_layout_fn=default_layout,
            normalize_layout_fn=normalize_layout,
        )
        self.font_path = ""
        self.src_img = Image.new("RGBA", (1280, 720), (50, 50, 50, 255))
        self.video_duration_s = 60.0
        self._prepare_cache = {}
        self._chart_data_cache = None
        self.indicator_bboxes = {}
        self._playing = False

    def _render_preview(self, seek_seconds=0):
        t0 = self.telemetry.start_dt_utc
        target_dt = t0 + timedelta(seconds=seek_seconds) if t0 else None
        overlay_data = prepare_overlay_frame_data(
            layout=self.layout,
            target_dt=target_dt,
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
        overlay = compose_overlay(
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
        return overlay_data, overlay

ctrl = SimController()
ctrl.telemetry.load_fit("Video/GX010115.MP4", manual_path=Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit"))
streams = ctrl._discover_data_streams()
print(f"Discovered {len(streams)} streams.")

test_stream_keys = [
    "fit_temperature_text",
    "fit_solar_text",
    "fit_solar_pct_text",
    "fit_curVpower_text",
    "fit_battery_text",
    "fit_battery_pct_text",
]

for skey in test_stream_keys:
    print(f"\n==================== CLICKING STREAM: {skey} ====================")
    ctrl._on_stream_clicked(skey)
    cfg = ctrl.layout["indicators"].get(skey, {})
    print(f"Config: form={cfg.get('form')}, label='{cfg.get('label')}', unit='{cfg.get('unit')}', min={cfg.get('min_val')}, max={cfg.get('max_val')}, source='{cfg.get('source')}'")
    
    # Render at t=0
    odata0, ov0 = ctrl._render_preview(seek_seconds=0)
    extra0 = odata0["extra_indicators"].get(skey)
    print(f"Preview at t=0: resolved extra_indicators = {extra0}")
    
    # Render at t=60 (when solar_pct has data)
    odata60, ov60 = ctrl._render_preview(seek_seconds=60)
    extra60 = odata60["extra_indicators"].get(skey)
    print(f"Preview at t=60: resolved extra_indicators = {extra60}")
