import sys, os, time, json
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from datetime import datetime, timedelta
import numpy as np
from PIL import Image

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_extract import (
    load_json_with_fallback, ensure_records_list,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor,
)
from src.indicators.chart_builder import build_chart_data
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value
from src.ffmpeg.command_builder import get_layout_hud_regions

def test_material(video_json_name: str, fit_name: str, total_frames: int, fps: float):
    print(f"\n{'='*80}")
    print(f"TESTING MATERIAL: {video_json_name} + {fit_name} ({total_frames} frames @ {fps} FPS)")
    print(f"{'='*80}")

    json_path = Path("Video") / video_json_name
    fit_path = Path("Video") / fit_name

    raw_records = ensure_records_list(load_json_with_fallback(json_path))
    anchor_dt = find_gps_anchor(raw_records)
    fit_data = process_fit(str(fit_path), video_start_dt=anchor_dt)

    speed_samples = extract_speed_samples(raw_records)
    alt_samples = extract_altitude_samples(raw_records)
    track_samples = extract_track_samples(raw_records)
    iso_samples = extract_iso_samples(raw_records)
    exposure_samples = extract_exposure_samples(raw_records)
    temp_samples = extract_temperature_samples(raw_records)

    field_samples = {
        "start_dt_utc": anchor_dt,
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temp_samples": temp_samples,
    }

    layout = normalize_layout("def_layout.json", 1920, 1080)

    # Init worker cache
    init_worker(
        video_width=1920, video_height=1080,
        field_samples=field_samples,
        layout=layout,
        font_path="",
        fit_data=fit_data,
        start_dt_utc=anchor_dt,
        target_fps=fps,
        total_overlay_frames=total_frames,
        gps_track=fit_data.get("track"),
    )

    # Prepare chart_data using streaming.py logic
    duration_s = total_frames / fps
    end_dt_utc = anchor_dt + timedelta(seconds=duration_s)
    source_ranges = {}
    if fit_data:
        all_fit_pts = [s for s in fit_data.values() if s]
        if all_fit_pts:
            source_ranges["fit"] = (
                min(s[0][0] for s in all_fit_pts),
                max(s[-1][0] for s in all_fit_pts),
            )

    def _get_src_samples(src_name: str) -> tuple[list, list, list]:
        if src_name == "gpx":
            return ([], [], [])
        if src_name == "fit":
            fit_d = fit_data or {}
            return (fit_d.get("speed", []), fit_d.get("track", []), fit_d.get("alt", []))
        return (speed_samples or [], track_samples or [], alt_samples or [])

    def _resolve_samples(field_name: str, source: str = "fit", indicator_key: str | None = None) -> list:
        if source == "fit":
            fit_d = fit_data or {}
            aliases = {
                "power": ("power", "curVpower"), "hr": ("hr", "heart_rate"),
                "cad": ("cad", "cadence"), "atemp": ("atemp", "temperature"),
                "battery": ("battery", "battery_soc"),
            }.get(field_name, (field_name,))
            for name in aliases:
                if fit_d.get(name):
                    return list(fit_d[name])
            return []
        if source == "gpmf":
            gpmf_map = {
                "speed": speed_samples, "alt": alt_samples, "altitude": alt_samples,
                "dist": track_samples, "track": track_samples, "iso": iso_samples,
                "exposure": exposure_samples, "temperature": temp_samples,
            }
            return list(gpmf_map.get(field_name, []) or [])
        return []

    chart_data = build_chart_data(
        layout,
        _get_src_samples,
        _resolve_samples,
        start_dt_utc=anchor_dt, end_dt_utc=end_dt_utc,
        source_activity_ranges=source_ranges,
    )

    print(f"Chart data keys ({len(chart_data)}):")
    for k, v in chart_data.items():
        print(f"  {k:25s}: {len(v)} pts | scope={getattr(v, 'time_scope', None)} | start={getattr(v, 'chart_start_dt', None)} | end={getattr(v, 'chart_end_dt', None)}")

    precompute_cache = build_telemetry_cache(
        layout=layout,
        base_dt=anchor_dt,
        tz_offset_hours=0.0,
        start_dt_utc=anchor_dt,
        speed_samples=speed_samples,
        track_samples=track_samples,
        alt_samples=alt_samples,
        iso_samples=iso_samples,
        exposure_samples=exposure_samples,
        temperature_samples=temp_samples,
        fit_data=fit_data,
        gps_track=fit_data.get("track"),
        chart_data=chart_data,
        total_frames=total_frames,
        target_fps=fps,
    )

    # 1. Test parity across 5 checkpoints
    checkpoints = [0, int(total_frames * 0.25), int(total_frames * 0.50), int(total_frames * 0.75), total_frames - 1]
    for cp in checkpoints:
        target_dt = anchor_dt + timedelta(seconds=cp / fps)
        fd_off = prepare_overlay_frame_data(
            layout=layout,
            target_dt=target_dt,
            tz_offset_hours=0.0,
            start_dt_utc=anchor_dt,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temp_samples,
            fit_data=fit_data,
            gps_track=fit_data.get("track"),
            total_frames=total_frames,
            current_index=cp,
            chart_data=chart_data,
            resolve_cache_value=_resolve_cache_value,
            _range_cache=WORKER_CACHE.get("_prep_cache"),
        )
        fd_on = precompute_cache.lookup(cp)

        img_off = compose_overlay(1920, 1080, layout, font_path="", **fd_off)
        img_on = compose_overlay(1920, 1080, layout, font_path="", **fd_on)

        arr_off = np.array(img_off)
        arr_on = np.array(img_on)
        diff = np.abs(arr_off.astype(np.int32) - arr_on.astype(np.int32))
        max_d = np.max(diff)
        diff_px = np.count_nonzero(diff)
        print(f"  Checkpoint frame {cp:5d} ({(cp/(total_frames-1))*100:5.1f}%): max_diff={max_d}, diff_pixels={diff_px}")
        assert max_d == 0 and diff_px == 0, f"Pixel mismatch at frame {cp}: max_diff={max_d}, diff_pixels={diff_px}"

    print(f"[OK] 100% BIT-EXACT PIXEL PARITY VERIFIED FOR {video_json_name}!")

def main():
    # Test 1: GX030120.json (5400 frames) + Poranna_jazda_na_rowerze.fit
    test_material("GX030120.json", "Poranna_jazda_na_rowerze.fit", 5400, 29.97)

    # Test 2: GX020079.json (1132 frames) + Morning_Ride.fit
    test_material("GX020079.json", "Morning_Ride.fit", 1132, 29.97)

if __name__ == "__main__":
    main()
