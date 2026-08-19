"""Run real 720p export and preview with step-by-step canvas inspection."""
import json
import sys
import os
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
    prepare_overlay_frame_data, build_chart_data, render_preview, compose_overlay
)
from src.indicators.time_block import render_time_block
from src.indicators.dispatcher import render_value_indicator
from src.indicators.compositor import rotated_paste
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

def step_by_step_preview():
    print("=== Step-by-step Canvas Preview (720p: 1280x720) ===")
    def_layout_path = root / "def_layout.json"
    with open(def_layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)
        
    font_path = resolve_font_path("Arial")
    print(f"Font path: {font_path}")
    
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
    
    raw_data = load_json_with_fallback(root / "Video" / "GX030120.json")
    records = ensure_records_list(raw_data)
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    telemetry.load_fit(str(root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"))
    
    fit_keys = telemetry.register_fit_fields(layout, BUILTIN_FIELDS)
    
    current_ts = 7.95
    target_dt = telemetry.start_dt_utc + timedelta(seconds=current_ts)
    
    chart_data = build_chart_data(
        layout,
        telemetry.get_samples_for_source,
        lambda field, src, key=None: telemetry.resolve_samples(field, src, indicator_key=key),
        start_dt_utc=telemetry.start_dt_utc,
        end_dt_utc=telemetry.start_dt_utc + timedelta(seconds=180.0),
    )
    
    prepare_cache = {
        "min_alt": None, "max_alt": None, "max_speed_kmh": None, "fit_fields": {}
    }
    
    frame_kwargs = prepare_overlay_frame_data(
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
        extra_field_keys=list(fit_keys),
        resolve_cache_value=lambda k, src, dt, indicator_key=None: telemetry.resolve_value(
            k, dt, source=src, indicator_key=indicator_key
        ),
        _range_cache=prepare_cache,
    )
    
    # Trace step-by-step
    canvas_w, canvas_h = 1280, 720
    base_img = Image.new("RGBA", (canvas_w, canvas_h), (20, 20, 20, 255))
    base_img.save(root / "scratch" / "01_base_preview.png")
    
    # 02 time_block
    img_tb = base_img.copy()
    tb, tbx, tby = render_time_block(
        canvas_w, canvas_h, layout, font_path,
        frame_kwargs["date_text"], frame_kwargs["time_text"]
    )
    print(f"[TRACE time_block] layout=yes enabled={layout.get('indicators',{}).get('time_block',{}).get('enabled')} date_text={frame_kwargs['date_text']} time_text={frame_kwargs['time_text']} tb_size={tb.size if tb else None} pos=({tbx},{tby})")
    if tb:
        cx = tbx + tb.width // 2
        cy = tby + tb.height // 2
        rotated_paste(img_tb, tb, cx, cy, 0)
    img_tb.save(root / "scratch" / "02_after_time_block.png")
    
    # 03 ISO
    img_iso = img_tb.copy()
    iso_cfg = layout["indicators"].get("iso_text", {})
    iso_val = frame_kwargs.get("iso_value")
    print(f"[TRACE iso_text] layout=yes enabled={iso_cfg.get('enabled')} value={iso_val}")
    res_iso, rx, ry, _ = render_value_indicator(
        canvas_w, canvas_h, layout, font_path,
        "iso_text", iso_val, "ISO", "ISO",
        cfg_override=iso_cfg,
        formatted_val=None,
    )
    print(f"  iso rendered: size={res_iso.size if res_iso else None} pos=({rx},{ry})")
    if res_iso:
        cx = rx + res_iso.width // 2
        cy = ry + res_iso.height // 2
        rotated_paste(img_iso, res_iso, cx, cy, 0)
    img_iso.save(root / "scratch" / "03_after_iso.png")
    
    # 04 Exposure
    img_exp = img_iso.copy()
    exp_cfg = layout["indicators"].get("exposure_text", {})
    exp_val = frame_kwargs.get("exposure_value")
    print(f"[TRACE exposure_text] layout=yes enabled={exp_cfg.get('enabled')} value={exp_val}")
    res_exp, rx, ry, _ = render_value_indicator(
        canvas_w, canvas_h, layout, font_path,
        "exposure_text", exp_val, "", "Ext",
        cfg_override=exp_cfg,
        formatted_val=f"1/{exp_val}" if exp_val else None,
    )
    print(f"  exp rendered: size={res_exp.size if res_exp else None} pos=({rx},{ry})")
    if res_exp:
        cx = rx + res_exp.width // 2
        cy = ry + res_exp.height // 2
        rotated_paste(img_exp, res_exp, cx, cy, 0)
    img_exp.save(root / "scratch" / "04_after_exposure.png")
    
    # 05 Temp
    img_tmp = img_exp.copy()
    tmp_cfg = layout["indicators"].get("temp_text", {})
    tmp_val = frame_kwargs.get("temp_value")
    print(f"[TRACE temp_text] layout=yes enabled={tmp_cfg.get('enabled')} value={tmp_val}")
    res_tmp, rx, ry, _ = render_value_indicator(
        canvas_w, canvas_h, layout, font_path,
        "temp_text", tmp_val, "°C", "TGP",
        cfg_override=tmp_cfg,
        formatted_val=None,
    )
    print(f"  temp rendered: size={res_tmp.size if res_tmp else None} pos=({rx},{ry})")
    if res_tmp:
        cx = rx + res_tmp.width // 2
        cy = ry + res_tmp.height // 2
        rotated_paste(img_tmp, res_tmp, cx, cy, 0)
    img_tmp.save(root / "scratch" / "05_after_temp.png")
    
    # 06 Full Preview via render_preview
    full_preview = render_preview(
        base_img, layout, font_path,
        frame_kwargs["date_text"], frame_kwargs["time_text"],
        frame_kwargs["speed_value"],
        frame_kwargs["distance_m"],
        frame_kwargs["max_distance_m"],
        frame_kwargs["alt_value"],
        frame_kwargs["min_alt"],
        frame_kwargs["max_alt"],
        frame_kwargs["iso_value"],
        frame_kwargs["exposure_value"],
        frame_kwargs["temp_value"],
        indicator_values=frame_kwargs["indicator_values"],
        max_speed_kmh=frame_kwargs["max_speed_kmh"],
        power_value=frame_kwargs["power_value"],
        atemp_value=frame_kwargs["atemp_value"],
        hr_value=frame_kwargs["hr_value"],
        cad_value=frame_kwargs["cad_value"],
        battery_value=frame_kwargs["battery_value"],
        _bboxes={},
        extra_indicators=frame_kwargs["extra_indicators"],
        chart_data=frame_kwargs["chart_data"],
        current_position=0.05,
        gps_track=frame_kwargs["gps_track"],
        target_dt=frame_kwargs["target_dt"],
        start_dt_utc=frame_kwargs["start_dt_utc"],
        elapsed_seconds=frame_kwargs["elapsed_seconds"],
        avg_speed_kmh=frame_kwargs["avg_speed_kmh"],
        inplace=False,
    )
    full_preview.save(root / "scratch" / "06_final_preview.png")
    print("Saved all 6 step-by-step images to scratch/")

if __name__ == "__main__":
    step_by_step_preview()
