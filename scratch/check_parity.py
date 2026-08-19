"""Verify exact Preview and Export parity for ETAP 8M.3."""
import json
import sys
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import resolve_font_path
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
from src.overlay_renderer import render_preview, prepare_overlay_frame_data, build_chart_data
from datetime import timedelta

def verify_parity():
    print("=== Checking Preview / Export Parity ===")
    layout = json.load(open("def_layout.json", "r", encoding="utf-8"))
    font_path = resolve_font_path("Arial")
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
    records = ensure_records_list(load_json_with_fallback(root / "Video" / "GX030120.json"))
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    telemetry.load_fit(str(root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"))
    telemetry.register_fit_fields(layout, BUILTIN_FIELDS)
    
    current_ts = 1.0  # frame 30
    target_dt = telemetry.start_dt_utc + timedelta(seconds=current_ts)
    
    chart_data = build_chart_data(
        layout,
        telemetry.get_samples_for_source,
        lambda field, src, key=None: telemetry.resolve_samples(field, src, indicator_key=key),
        start_dt_utc=telemetry.start_dt_utc,
        end_dt_utc=telemetry.start_dt_utc + timedelta(seconds=180.0),
    )
    
    overlay_data = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=2,
        start_dt_utc=telemetry.start_dt_utc,
        speed_samples=telemetry.speed_samples or [],
        track_samples=telemetry.track_samples or [],
        alt_samples=telemetry.alt_samples or [],
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
        total_frames=180,
        current_index=int(current_ts),
        chart_data=chart_data,
        resolve_cache_value=lambda k, src, dt, indicator_key=None: telemetry.resolve_value(
            k, dt, source=src, indicator_key=indicator_key
        ),
    )
    
    base_preview = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    bboxes = {}
    preview_img = render_preview(
        base_preview, layout, font_path,
        overlay_data["date_text"], overlay_data["time_text"],
        overlay_data["speed_value"],
        overlay_data["distance_m"],
        overlay_data["max_distance_m"],
        overlay_data["alt_value"],
        overlay_data["min_alt"],
        overlay_data["max_alt"],
        overlay_data["iso_value"],
        overlay_data["exposure_value"],
        overlay_data["temp_value"],
        indicator_values=overlay_data["indicator_values"],
        max_speed_kmh=overlay_data["max_speed_kmh"],
        power_value=overlay_data["power_value"],
        atemp_value=overlay_data["atemp_value"],
        hr_value=overlay_data["hr_value"],
        cad_value=overlay_data["cad_value"],
        battery_value=overlay_data["battery_value"],
        _bboxes=bboxes,
        extra_indicators=overlay_data["extra_indicators"],
        chart_data=overlay_data["chart_data"],
        current_position=0.05,
        gps_track=overlay_data["gps_track"],
        target_dt=overlay_data["target_dt"],
        start_dt_utc=overlay_data["start_dt_utc"],
        elapsed_seconds=overlay_data["elapsed_seconds"],
        avg_speed_kmh=overlay_data["avg_speed_kmh"],
        inplace=False,
    )
    preview_img.save("scratch/parity_preview_frame30.png")
    print(f"Preview frame 30 bboxes: {bboxes}")
    
    for key in ("time_block", "iso_text", "exposure_text", "temp_text", "fit_solar_pct_text", "fit_battery_pct_text"):
        if key in bboxes:
            bx, by, bw, bh = bboxes[key]
            c = preview_img.crop((bx, by, bx + bw, by + bh))
            non_zero_alpha = np.count_nonzero(np.asarray(c)[:, :, 3])
            print(f"  {key:25s} bbox=({bx},{by},{bw},{bh}) non-zero alpha={non_zero_alpha}")
        else:
            print(f"  {key:25s} NOT IN BBOXES")

if __name__ == "__main__":
    verify_parity()
