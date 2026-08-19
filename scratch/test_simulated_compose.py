"""Simulate amd_native_exporter live frame data and compose_overlay."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout, resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.gui.indicator_schemas import BUILTIN_FIELDS
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.overlay_renderer import (
    prepare_overlay_frame_data, build_chart_data, compose_overlay
)
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value, WORKER_CACHE

def test_compose():
    def_layout_path = root / "def_layout.json"
    with open(def_layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)
        
    font_path = resolve_font_path("Arial")
    video_path = root / "Video" / "GX030120.MP4"
    json_path = root / "Video" / "GX030120.json"
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    
    telemetry = TelemetryDataManager(
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
    
    raw_data = load_json_with_fallback(json_path)
    records = ensure_records_list(raw_data)
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    telemetry.load_fit(str(fit_path))
    
    fit_keys = telemetry.register_fit_fields(layout, BUILTIN_FIELDS)
    
    compose_layout, map_above_layout, _ = _ordered_map_layout_parts(layout)
    
    field_samples = {
        "speed_samples": telemetry.speed_samples or [],
        "track_samples": telemetry.track_samples or [],
        "alt_samples": telemetry.alt_samples or [],
        "iso_samples": telemetry.iso_samples or [],
        "exposure_samples": telemetry.exposure_samples or [],
        "temperature_samples": telemetry.temperature_samples or [],
    }
    
    init_worker(
        video_width=1280,
        video_height=720,
        font_path=font_path,
        layout=compose_layout,
        field_samples=field_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        gpx_speed_samples=telemetry.gpx_speed_samples,
        gpx_track_samples=telemetry.gpx_track_samples,
        gpx_alt_samples=telemetry.gpx_alt_samples,
        gpx_power_samples=telemetry.gpx_power_samples,
        gpx_atemp_samples=telemetry.gpx_atemp_samples,
        gpx_hr_samples=telemetry.gpx_hr_samples,
        gpx_cad_samples=telemetry.gpx_cad_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        start_dt_utc=telemetry.start_dt_utc,
        tz_offset_hours=2,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        target_fps=29.97,
        total_overlay_frames=60,
    )
    
    frame_idx = 30
    curr_dt = telemetry.start_dt_utc + timedelta(seconds=frame_idx / 29.97)
    
    chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})
    
    frame_kwargs = prepare_overlay_frame_data(
        layout=compose_layout,
        target_dt=curr_dt,
        start_dt_utc=telemetry.start_dt_utc,
        tz_offset_hours=2,
        speed_samples=telemetry.speed_samples,
        track_samples=telemetry.track_samples,
        alt_samples=telemetry.alt_samples,
        iso_samples=telemetry.iso_samples,
        exposure_samples=telemetry.exposure_samples,
        temperature_samples=telemetry.temperature_samples,
        total_frames=60,
        current_index=frame_idx,
        chart_data=chart_data,
        resolve_cache_value=_resolve_cache_value,
        gpx_speed_samples=telemetry.gpx_speed_samples,
        gpx_track_samples=telemetry.gpx_track_samples,
        gpx_alt_samples=telemetry.gpx_alt_samples,
        gpx_power_samples=telemetry.gpx_power_samples,
        gpx_atemp_samples=telemetry.gpx_atemp_samples,
        gpx_hr_samples=telemetry.gpx_hr_samples,
        gpx_cad_samples=telemetry.gpx_cad_samples,
        fit_data=telemetry.fit_data,
        gps_track=telemetry.get_gps_track_for_source("fit"),
        _range_cache=WORKER_CACHE.get("_prep_cache"),
    )
    
    print("\nframe_kwargs keys:", list(frame_kwargs.keys()))
    print(f"date_text: {frame_kwargs.get('date_text')}, time_text: {frame_kwargs.get('time_text')}")
    print(f"iso_value: {frame_kwargs.get('iso_value')}, exposure_value: {frame_kwargs.get('exposure_value')}, temp_value: {frame_kwargs.get('temp_value')}")
    
    _bboxes = {}
    gpu_capture = {}
    composed_img = compose_overlay(
        canvas_w=1280,
        canvas_h=720,
        layout=compose_layout,
        font_path=font_path,
        _bboxes=_bboxes,
        gpu_capture_keys={"gauge"},
        gpu_capture=gpu_capture,
        split_chart_keys=None,
        **frame_kwargs
    )
    composed_img.save(root / "scratch" / "simulated_composed_img_30.png")
    print("\nRendered bboxes in compose_overlay:", _bboxes)
    
    # Check alpha in top-left
    c = composed_img.crop((0, 0, 200, 150))
    alpha = np.asarray(c.getchannel("A"))
    print(f"Top-left non-zero alpha pixels in composed_img: {np.count_nonzero(alpha)}")

if __name__ == "__main__":
    test_compose()
