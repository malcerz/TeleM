"""Refined fine-grained profiling script for TeleM AMD ETAP 5.
Measures per-indicator and sub-step timing for 300 frames of NORMAL HUD and MAX HUD.
"""

from __future__ import annotations

import json
import os
import sys
import time
import statistics
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

from src.telemetry_gpmf_new import gpmf_to_full_json
from src.telemetry_extract import (
    extract_speed_samples,
    extract_track_samples,
    extract_altitude_samples,
    extract_iso_samples,
    extract_exposure_samples,
    extract_temperature_samples,
    find_gps_anchor,
)
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.ffmpeg.command_builder import get_layout_hud_regions

VIDEO_PATH = Path("Video/GX020079.mp4").resolve()
JSON_PATH = Path("Video/GX020079.json").resolve()

def profile_run(layout_mode: str, num_frames: int = 300):
    print(f"\n================ PROFILING {layout_mode} ({num_frames} frames) ================")

    if JSON_PATH.exists():
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)
    else:
        records = gpmf_to_full_json(VIDEO_PATH)

    speed_samples = extract_speed_samples(records)
    track_samples = extract_track_samples(records)
    alt_samples = extract_altitude_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    start_dt_utc = find_gps_anchor(records)

    with open("def_layout.json", "r", encoding="utf-8") as f:
        layout = json.load(f)

    if layout_mode == "MAX HUD":
        for ind_key, ind_cfg in layout.get("indicators", {}).items():
            if isinstance(ind_cfg, dict):
                ind_cfg["enabled"] = True

    target_fps = 30.0
    update_rate_step = 1
    overlay_w, overlay_h = 1920, 1080

    atlas_w, atlas_h, hud_regions = get_layout_hud_regions(layout, overlay_w, overlay_h, max_regions=3)

    from src.indicators import dispatcher

    orig_render_val = dispatcher.render_value_indicator
    frame_indicator_times = {}

    def wrapped_render_val(*args, **kwargs):
        key = kwargs.get("key") or (args[4] if len(args) > 4 else "unknown")
        cfg = kwargs.get("cfg_override") or layout["indicators"].get(key, {})
        form = cfg.get("form", "text") if isinstance(cfg, dict) else "text"
        t_start = time.perf_counter_ns()
        res = orig_render_val(*args, **kwargs)
        elapsed_ms = (time.perf_counter_ns() - t_start) / 1e6
        frame_indicator_times[form] = frame_indicator_times.get(form, 0.0) + elapsed_ms
        frame_indicator_times[f"ind:{key}"] = frame_indicator_times.get(f"ind:{key}", 0.0) + elapsed_ms
        return res

    dispatcher.render_value_indicator = wrapped_render_val

    timings = {
        "prepare_overlay_frame_data": [],
        "compose_overlay_total": [],
        "form_gauge": [],
        "form_chart": [],
        "form_moving_map": [],
        "form_text": [],
        "form_bar": [],
        "crop_and_atlas": [],
        "numpy_and_shm_copy": [],
    }

    t0 = start_dt_utc if start_dt_utc else datetime(1970, 1, 1, tzinfo=timezone.utc)
    if not isinstance(t0, datetime):
        t0 = datetime.fromtimestamp(float(t0), timezone.utc)

    try:
        start_total = time.perf_counter()
        for idx in range(num_frames):
            frame_indicator_times = {}

            sample_t = (idx * update_rate_step) / target_fps
            current_dt_utc = t0 + timedelta(seconds=sample_t)

            # 1. prepare_overlay_frame_data
            t_data_start = time.perf_counter_ns()
            data = prepare_overlay_frame_data(
                layout=layout,
                target_dt=current_dt_utc,
                tz_offset_hours=0.0,
                start_dt_utc=start_dt_utc,
                speed_samples=speed_samples,
                track_samples=track_samples,
                alt_samples=alt_samples,
                iso_samples=iso_samples,
                exposure_samples=exposure_samples,
                temperature_samples=temp_samples,
                total_frames=num_frames,
                current_index=idx,
            )
            timings["prepare_overlay_frame_data"].append((time.perf_counter_ns() - t_data_start) / 1e6)

            # 2. compose_overlay
            t_comp_start = time.perf_counter_ns()
            img = compose_overlay(
                overlay_w, overlay_h, layout, "Arial",
                data["date_text"], data["time_text"],
                data["speed_value"], data["distance_m"], data["max_distance_m"],
                data["alt_value"], data["min_alt"], data["max_alt"],
                data["iso_value"], data["exposure_value"], data["temp_value"],
                indicator_values=data["indicator_values"],
                max_speed_kmh=data["max_speed_kmh"],
                power_value=data["power_value"],
                atemp_value=data["atemp_value"],
                hr_value=data["hr_value"],
                cad_value=data["cad_value"],
                battery_value=data["battery_value"],
                chart_data=data["chart_data"],
                current_position=data["current_position"],
                extra_indicators=data["extra_indicators"],
                gps_track=data["gps_track"],
                target_dt=data["target_dt"],
                start_dt_utc=data["start_dt_utc"],
                elapsed_seconds=data["elapsed_seconds"],
                avg_speed_kmh=data["avg_speed_kmh"],
            )
            timings["compose_overlay_total"].append((time.perf_counter_ns() - t_comp_start) / 1e6)
            timings["form_gauge"].append(frame_indicator_times.get("gauge", 0.0))
            timings["form_chart"].append(frame_indicator_times.get("chart", 0.0))
            timings["form_moving_map"].append(frame_indicator_times.get("moving_map", 0.0))
            timings["form_text"].append(frame_indicator_times.get("text", 0.0))
            timings["form_bar"].append(frame_indicator_times.get("bar", 0.0))

            # 3. Crop and Atlas
            t_atlas_start = time.perf_counter_ns()
            atlas_img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
            for r in hud_regions:
                dest_x, dest_y, src_x, src_y, rw, rh = r
                r_crop = img.crop((dest_x, dest_y, dest_x + rw, dest_y + rh))
                atlas_img.paste(r_crop, (src_x, src_y))
            timings["crop_and_atlas"].append((time.perf_counter_ns() - t_atlas_start) / 1e6)

            # 4. NumPy & SHM copy simulation
            t_shm_start = time.perf_counter_ns()
            dummy_buf = bytearray(atlas_w * atlas_h * 4)
            shm_arr = np.frombuffer(dummy_buf, dtype=np.uint8).reshape((atlas_h, atlas_w, 4))
            img_arr = np.asarray(atlas_img)
            np.copyto(shm_arr, img_arr)
            timings["numpy_and_shm_copy"].append((time.perf_counter_ns() - t_shm_start) / 1e6)

        total_elapsed = time.perf_counter() - start_total
    finally:
        dispatcher.render_value_indicator = orig_render_val

    total_hud_avg = (
        statistics.mean(timings["prepare_overlay_frame_data"]) +
        statistics.mean(timings["compose_overlay_total"]) +
        statistics.mean(timings["crop_and_atlas"]) +
        statistics.mean(timings["numpy_and_shm_copy"])
    )

    print(f"\n--- REFINED TIMING BREAKDOWN FOR {layout_mode} ({num_frames} frames, {num_frames/total_elapsed:.2f} FPS) ---")
    print(f"{'Component':<30} | {'AVG (ms)':<9} | {'Median':<9} | {'P95 (ms)':<9} | {'P99 (ms)':<9} | {'Min (ms)':<9} | {'Max (ms)':<9} | {'% HUD Time':<10}")
    print("-" * 110)

    display_keys = [
        "numpy_and_shm_copy", "compose_overlay_total", "crop_and_atlas",
        "prepare_overlay_frame_data", "form_chart", "form_gauge",
        "form_moving_map", "form_text", "form_bar"
    ]

    for comp in display_keys:
        vals = timings[comp]
        avg_v = statistics.mean(vals)
        med_v = statistics.median(vals)
        p95_v = float(np.percentile(vals, 95))
        p99_v = float(np.percentile(vals, 99))
        min_v = min(vals)
        max_v = max(vals)
        pct_v = (avg_v / total_hud_avg * 100.0) if total_hud_avg > 0 else 0.0

        print(f"{comp:<30} | {avg_v:<9.2f} | {med_v:<9.2f} | {p95_v:<9.2f} | {p99_v:<9.2f} | {min_v:<9.2f} | {max_v:<9.2f} | {pct_v:<9.1f}%")

    print("-" * 110)
    print(f"{'TOTAL HUD GENERATION AVG':<30} | {total_hud_avg:<9.2f} ms")

if __name__ == "__main__":
    profile_run("NORMAL HUD", 300)
    profile_run("MAX HUD", 300)
