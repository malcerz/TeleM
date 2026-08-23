import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from datetime import timedelta
import numpy as np
from src.gui.telemetry_manager import TelemetryDataManager

root = Path(__file__).resolve().parents[1]
video_path = str(root / "Video" / "GX010115.MP4")
json_path = str(root / "Video" / "GX010115.json")
fit_path = str(root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit")
preset_path = str(root / "presets" / "cycling_dashboard_v10.json")

# Let's inspect how preview renders distance at 0s, 30s, 60s, 90s, 120s
from src.gui.qt._mixins.preview_mixin import PreviewMixin

class MockApp(PreviewMixin):
    def __init__(self):
        self.video_path = video_path
        with open(preset_path, "r", encoding="utf-8") as f:
            self.layout = json.load(f)
        self._preview_target_w = 1280
        self._preview_mode = "cpu"
        self.last_src_pil = None
        self._prepare_cache = None
        self._chart_data_cache = None
        self.video_duration_s = 120.0
        self.ffmpeg_exe = "ffmpeg"
        self.ffprobe_exe = "ffprobe"
        
        from src.telemetry_extract import (
            extract_speed_samples, extract_altitude_samples, extract_track_samples,
            extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
            ensure_records_list, extract_gps_track,
            smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
            get_container_rotation, find_metadata_json, load_json_with_fallback,
            smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
        )
        with open(json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        records = ensure_records_list(meta)

        self.telemetry = TelemetryDataManager(
            extract_speed_fn=extract_speed_samples,
            extract_altitude_fn=extract_altitude_samples,
            extract_track_fn=extract_track_samples,
            extract_iso_fn=extract_iso_samples,
            extract_exposure_fn=extract_exposure_samples,
            extract_temperature_fn=extract_temperature_samples,
            smooth_fn=smooth_speed_samples,
            interpolate_fn=interpolate_value,
            get_rotation_meta_fn=get_rotation_from_metadata,
            get_container_rotation_fn=get_container_rotation,
            find_meta_json_fn=find_metadata_json,
            find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
            load_telemetry_fn=lambda *a: None,
            ensure_records_fn=ensure_records_list,
            load_json_fallback_fn=load_json_with_fallback,
            write_records_fn=lambda p, r: None,
            extract_samples_exiftool_fn=lambda f: [],
            extract_altitude_exiftool_fn=lambda f: [],
            extract_gps_track_fn=extract_gps_track,
            find_gps_anchor_fn=lambda r: None,
            smooth_values_fn=smooth_speed_values,
            extract_accelerometer_fn=extract_accelerometer_samples,
            extract_gyroscope_fn=extract_gyroscope_samples,
        )
        self.telemetry.load_gpmf_records(records)
        self.telemetry.load_gps_track(records)
        self.telemetry.load_fit(video_path, self.telemetry.start_dt_utc, manual_path=fit_path)

    def is_using_mpv(self):
        return False

app = MockApp()
app._build_prepare_cache()
print("Prepare cache:", app._prepare_cache)

from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay

for ts in [0.0, 10.0, 30.0, 60.0, 90.0, 120.0]:
    dt = app.telemetry.start_dt_utc + timedelta(seconds=ts)
    overlay_data = prepare_overlay_frame_data(
        layout=app.layout,
        target_dt=dt,
        tz_offset_hours=2,
        start_dt_utc=app.telemetry.start_dt_utc,
        speed_samples=app.telemetry.speed_samples or [],
        track_samples=app.telemetry.track_samples or [],
        alt_samples=app.telemetry.alt_samples or [],
        iso_samples=app.telemetry.iso_samples,
        exposure_samples=app.telemetry.exposure_samples,
        temperature_samples=app.telemetry.temperature_samples,
        fit_data=app.telemetry.fit_data,
        gps_track=app.telemetry.get_gps_track_for_source("fit"),
        total_frames=120,
        current_index=int(ts),
        chart_data=None,
        resolve_cache_value=lambda k, src, d, indicator_key=None: app.telemetry.resolve_value(
            k, d, source=src, indicator_key=indicator_key
        ),
        _range_cache=app._prepare_cache,
    )
    bboxes = {}
    overlay = compose_overlay(1280, 720, app.layout, "", _bboxes=bboxes, **overlay_data)
    
    # Check marker in overlay around dist_visual bbox
    # dist_visual is at (50% x, 74% y)
    bbox = bboxes.get("dist_visual")
    ox, oy, ow, oh = bbox
    crop = overlay.crop((ox, oy, ox + ow, oy + oh))
    arr = np.array(crop)
    marker_color = (255, 212, 42)
    mask = (arr[:, :, 0] == marker_color[0]) & (arr[:, :, 1] == marker_color[1]) & (arr[:, :, 2] == marker_color[2]) & (arr[:, :, 3] > 200)
    ys, xs = np.where(mask)
    marker_cx = float(np.mean(xs)) if len(xs) > 0 else None
    print(f"t={ts:5.1f}s | dist={overlay_data.get('distance_m'):6.1f}m ({overlay_data.get('distance_m')/1000.0:.3f}km) | max_val_m={app._prepare_cache['max_distance_m']:.1f}m | marker_local_x={marker_cx}")

