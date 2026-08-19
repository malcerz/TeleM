"""Trace exact GUI runtime layout and pipeline execution for ETAP 8M.3."""
import json
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from PIL import Image

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.layout_manager import normalize_layout, default_layout, resolve_font_path
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

def compute_layout_hash(layout_dict: dict) -> str:
    # Stable canonical JSON serialization for hashing
    canonical = json.dumps(layout_dict, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

def trace_etap8m3():
    print("=== [ETAP 8M.3] STARTING EXACT REAL RUNTIME AUDIT ===")
    
    # 1. Canonical def_layout.json
    def_layout_path = root / "def_layout.json"
    with open(def_layout_path, "r", encoding="utf-8") as f:
        canonical_layout = json.load(f)
    can_hash = compute_layout_hash(canonical_layout)
    print(f"1. Canonical def_layout.json hash: {can_hash}")
    
    # 2. Controller Initialization
    font_path = resolve_font_path("Arial")
    # In controller.__init__:
    layout = normalize_layout(def_layout_path, 1280, 720)
    init_hash = compute_layout_hash(layout)
    print(f"2. Controller init layout hash: {init_hash}")
    
    # 3. TelemetryDataManager
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
    
    # 4. Loading Video & FIT (ProjectMixin._load_telemetry_for_video)
    video_path = root / "Video" / "GX030120.MP4"
    json_path = root / "Video" / "GX030120.json"
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    
    # Video dimensions (4K: 3840x2160)
    w, h = 3840, 2160
    # ProjectMixin layout loading logic:
    preset_path = layout.get("_startup_preset", "")
    if preset_path and Path(preset_path).exists():
        layout = json.loads(Path(preset_path).read_text(encoding="utf-8"))
    else:
        layout = normalize_layout(def_layout_path, w, h)
        
    raw_data = load_json_with_fallback(json_path)
    records = ensure_records_list(raw_data)
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    telemetry.load_fit(str(fit_path))
    
    # Register FIT fields in layout
    fit_ext_fields = []
    if telemetry.fit_data:
        fit_keys = telemetry.register_fit_fields(layout, BUILTIN_FIELDS)
        fit_ext_fields = list(fit_keys)
        
    print(f"3. After register_fit_fields, layout hash: {compute_layout_hash(layout)}")
    print(f"   fit_ext_fields registered: {len(fit_ext_fields)} fields -> {fit_ext_fields}")
    
    # 5. Runtime GPMF Inventory
    print("\n=== RUNTIME GPMF INVENTORY (self.telemetry) ===")
    print(f"  len(iso_samples): {len(telemetry.iso_samples)}")
    print(f"  len(exposure_samples): {len(telemetry.exposure_samples)}")
    print(f"  len(temperature_samples): {len(telemetry.temperature_samples)}")
    print(f"  len(speed_samples): {len(telemetry.speed_samples)}")
    print(f"  start_dt_utc: {telemetry.start_dt_utc}")
    
    # 6. Dump Preview Runtime Layout
    preview_runtime_layout_path = root / "scratch" / "etap8m3_preview_runtime_layout.json"
    with open(preview_runtime_layout_path, "w", encoding="utf-8") as f:
        json.dump(layout, f, indent=2, ensure_ascii=False)
    prev_hash = compute_layout_hash(layout)
    print(f"\n4. Dumped Preview runtime layout to: {preview_runtime_layout_path}")
    print(f"   Preview runtime layout hash: {prev_hash}")
    
    # 7. Simulate Preview Frame Rendering for target_dt (e.g. t = 7.95s)
    current_ts = 7.95
    target_dt = telemetry.start_dt_utc + timedelta(seconds=current_ts) if telemetry.start_dt_utc else None
    if target_dt and target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)
        
    chart_data = build_chart_data(
        layout,
        telemetry.get_samples_for_source,
        lambda field, src, key=None: telemetry.resolve_samples(field, src, indicator_key=key),
        start_dt_utc=telemetry.start_dt_utc,
        end_dt_utc=(telemetry.start_dt_utc + timedelta(seconds=180.0)) if telemetry.start_dt_utc else None,
    )
    
    prepare_cache = {
        "min_alt": None, "max_alt": None, "max_speed_kmh": None,
        "fit_fields": {}
    }
    
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
        gps_track=telemetry.get_gps_track_for_source(
            layout.get("indicators", {}).get("track_map", {}).get("source", "fit")
        ),
        total_frames=180,
        current_index=int(current_ts),
        chart_data=chart_data,
        extra_field_keys=fit_ext_fields,
        resolve_cache_value=lambda k, src, dt, indicator_key=None: telemetry.resolve_value(
            k, dt, source=src, indicator_key=indicator_key
        ),
        _range_cache=prepare_cache,
    )
    
    print("\n=== RUNTIME VALUES AT t = 7.95s ===")
    print(f"  date_text: {overlay_data.get('date_text')}")
    print(f"  time_text: {overlay_data.get('time_text')}")
    print(f"  iso_value: {overlay_data.get('iso_value')}")
    print(f"  exposure_value: {overlay_data.get('exposure_value')}")
    print(f"  temp_value: {overlay_data.get('temp_value')}")
    print(f"  speed_value: {overlay_data.get('speed_value')}")
    
    # 8. Dump Export Runtime Layout (as passed to exporter)
    export_layout = dict(layout, cut_regions=[])
    export_runtime_layout_path = root / "scratch" / "etap8m3_export_runtime_layout.json"
    with open(export_runtime_layout_path, "w", encoding="utf-8") as f:
        json.dump(export_layout, f, indent=2, ensure_ascii=False)
    exp_hash = compute_layout_hash(export_layout)
    print(f"\n5. Dumped Export runtime layout to: {export_runtime_layout_path}")
    print(f"   Export runtime layout hash: {exp_hash}")

if __name__ == "__main__":
    trace_etap8m3()
