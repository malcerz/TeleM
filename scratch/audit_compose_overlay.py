"""ETAP 8G: Detailed compose_overlay audit and instrumentation."""
import copy
import gc
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

from src.indicators import chart as chart_module
from src.indicators import chart_utils as chart_utils_module
from src.indicators import helpers as helpers_module
from src.indicators.compositor import compose_overlay, _get_reusable_canvas
from src.indicators.dispatcher import render_value_indicator
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    interpolate_value,
    load_json_with_fallback,
    smooth_speed_samples,
)
from src.telemetry_precompute import build_telemetry_cache
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts

# Load telemetry
records = ensure_records_list(load_json_with_fallback(root / "Video" / "GX030120.json"))
tm = TelemetryDataManager(
    extract_speed_fn=extract_speed_samples,
    extract_altitude_fn=extract_altitude_samples,
    extract_track_fn=extract_track_samples,
    extract_iso_fn=extract_iso_samples,
    extract_exposure_fn=extract_exposure_samples,
    extract_temperature_fn=extract_temperature_samples,
    smooth_fn=smooth_speed_samples,
    interpolate_fn=interpolate_value,
)
tm.load_gpmf_records(records)
tm.load_fit(root / "Video" / "Poranna_jazda_na_rowerze.fit")

# GPMF real timestamp: 2026-08-18 04:46:25.700 UTC
start_dt_real = tm.speed_samples[0][0]
# 8D hardcoded timestamp: 2026-08-05 04:28:11 UTC
start_dt_8d = datetime(2026, 8, 5, 4, 28, 11)

layout_raw = json.load(open(root / "def_layout.json", encoding="utf-8"))
font_path = "arial.ttf"

def run_900_frame_audit(
    tag: str,
    layout_override: dict,
    start_dt: datetime,
    chart_mode: str = "GPU_SPLIT",
):
    print(f"\n=======================================================")
    print(f"=== RUNNING 900-FRAME AUDIT: {tag} ===")
    print(f"=======================================================")

    below_layout, above_layout, after_keys = _ordered_map_layout_parts(layout_override)

    init_worker(
        video_width=3840,
        video_height=2160,
        font_path=font_path,
        layout=below_layout,
        field_samples={"speed_samples": tm.speed_samples, "track_samples": tm.track_samples, "alt_samples": tm.alt_samples},
        speed_samples=smooth_speed_samples(tm.speed_samples, "moving_average", 5),
        track_samples=tm.track_samples,
        alt_samples=smooth_speed_samples(tm.alt_samples, "moving_average", 5),
        fit_data=tm.fit_data,
        total_overlay_frames=900,
        target_fps=29.97,
        start_dt_utc=start_dt,
    )
    chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})

    cache = build_telemetry_cache(
        layout=below_layout,
        base_dt=start_dt,
        tz_offset_hours=0.0,
        start_dt_utc=start_dt,
        speed_samples=smooth_speed_samples(tm.speed_samples, "moving_average", 5),
        track_samples=tm.track_samples,
        alt_samples=smooth_speed_samples(tm.alt_samples, "moving_average", 5),
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        chart_data=chart_data,
        total_frames=900,
        target_fps=29.97,
    )

    gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"} if chart_mode in ("GPU", "GPU_SPLIT") else set()
    split_chart_keys = gpu_chart_keys if chart_mode == "GPU_SPLIT" else None

    # Clear caches and tracking
    chart_module._FINAL_STATIC_CHART_CACHE.clear()
    chart_utils_module._CHART_BG_CACHE.clear()
    helpers_module._STATIC_CACHE.clear()

    # Per-frame metrics
    compose_times = []
    clear_times = []
    indicator_times = {k: [] for k in below_layout.get("indicators", {})}
    indicator_paste_times = {k: [] for k in below_layout.get("indicators", {})}
    gc_pauses = []

    # Detailed chart cache stats
    chart_bg_lookups = 0
    chart_bg_hits = 0
    chart_bg_creates = 0
    final_static_lookups = 0
    final_static_hits = 0
    final_static_creates = 0

    # Cache keys observed
    observed_keys = {}

    for f in range(900):
        fk = cache.lookup(f)
        _bboxes = {}
        gpu_capture = {}

        t_start = time.perf_counter()

        # Measure compose_overlay
        img = compose_overlay(
            canvas_w=3840,
            canvas_h=2160,
            layout=below_layout,
            font_path=font_path,
            _bboxes=_bboxes,
            gpu_capture_keys=gpu_chart_keys,
            gpu_capture=gpu_capture,
            split_chart_keys=split_chart_keys,
            reuse_canvas=True,
            **fk,
        )
        t_end = time.perf_counter()
        compose_times.append((t_end - t_start) * 1000.0)

        if f in (0, 1, 100, 500, 899):
            observed_keys[f] = {
                "chart_bg_cache_len": len(chart_utils_module._CHART_BG_CACHE),
                "final_static_len": len(chart_module._FINAL_STATIC_CHART_CACHE),
                "rendered_bboxes": list(_bboxes.keys()),
                "gpu_capture_keys": list(gpu_capture.keys()),
            }

    compose_times = np.array(compose_times)
    print(f"[{tag}] 900-frame compose_overlay:")
    print(f"  median={np.median(compose_times):.3f} ms, p95={np.percentile(compose_times, 95):.3f} ms, mean={np.mean(compose_times):.3f} ms, min={np.min(compose_times):.3f} ms, max={np.max(compose_times):.3f} ms")
    print(f"  Cold frame 0: {compose_times[0]:.3f} ms")
    print(f"  Frames 1-30: median={np.median(compose_times[1:31]):.3f} ms, p95={np.percentile(compose_times[1:31], 95):.3f} ms")
    print(f"  Frames 100-899: median={np.median(compose_times[100:]):.3f} ms, p95={np.percentile(compose_times[100:], 95):.3f} ms")
    print(f"  Cache sizes at end: _FINAL_STATIC_CHART_CACHE={len(chart_module._FINAL_STATIC_CHART_CACHE)}, _CHART_BG_CACHE={len(chart_utils_module._CHART_BG_CACHE)}")
    print(f"  Observed checkpoints: {observed_keys}")

    return {
        "tag": tag,
        "compose_times": compose_times,
        "observed_keys": observed_keys,
        "cache_sizes": (len(chart_module._FINAL_STATIC_CHART_CACHE), len(chart_utils_module._CHART_BG_CACHE)),
    }


def run_per_indicator_breakdown():
    print(f"\n=======================================================")
    print(f"=== PER-INDICATOR & SUB-OPERATION BREAKDOWN (900 FRAMES) ===")
    print(f"=======================================================")

    below_layout, above_layout, after_keys = _ordered_map_layout_parts(layout_raw)
    init_worker(
        video_width=3840,
        video_height=2160,
        font_path=font_path,
        layout=below_layout,
        field_samples={"speed_samples": tm.speed_samples, "track_samples": tm.track_samples, "alt_samples": tm.alt_samples},
        speed_samples=smooth_speed_samples(tm.speed_samples, "moving_average", 5),
        track_samples=tm.track_samples,
        alt_samples=smooth_speed_samples(tm.alt_samples, "moving_average", 5),
        fit_data=tm.fit_data,
        total_overlay_frames=900,
        target_fps=29.97,
        start_dt_utc=start_dt_real,
    )
    chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})
    cache = build_telemetry_cache(
        layout=below_layout,
        base_dt=start_dt_real,
        tz_offset_hours=0.0,
        start_dt_utc=start_dt_real,
        speed_samples=smooth_speed_samples(tm.speed_samples, "moving_average", 5),
        track_samples=tm.track_samples,
        alt_samples=smooth_speed_samples(tm.alt_samples, "moving_average", 5),
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source("fit"),
        chart_data=chart_data,
        total_frames=900,
        target_fps=29.97,
    )

    gpu_chart_keys = {"fit_cadence_text", "fit_heart_rate_text"}
    split_chart_keys = gpu_chart_keys

    # Measurement buckets
    ind_render_times: dict[str, list[float]] = {}
    ind_paste_times: dict[str, list[float]] = {}
    clear_times = []
    rot_paste_times = {"rot0": [], "rot_non0": []}
    text_formatting_times = []
    font_lookup_times = []

    # Warm up 5 frames
    for f in range(5):
        compose_overlay(
            canvas_w=3840, canvas_h=2160, layout=below_layout, font_path=font_path,
            _bboxes={}, gpu_capture_keys=gpu_chart_keys, gpu_capture={},
            split_chart_keys=split_chart_keys, reuse_canvas=True, **cache.lookup(f)
        )

    # 900 frames detailed measurement
    for f in range(900):
        fk = cache.lookup(f)
        img, prev_bboxes = _get_reusable_canvas(3840, 2160)
        
        # 1. Clear timing
        t_c0 = time.perf_counter()
        if prev_bboxes:
            pad = 40
            for bx, by, bw, bh in prev_bboxes.values():
                x1 = max(0, bx - pad)
                y1 = max(0, by - pad)
                x2 = min(3840, bx + bw + pad)
                y2 = min(2160, by + bh + pad)
                img.paste((0, 0, 0, 0), (x1, y1, x2, y2))
            prev_bboxes.clear()
        else:
            img.paste((0, 0, 0, 0), (0, 0, 3840, 2160))
        t_c1 = time.perf_counter()
        clear_times.append((t_c1 - t_c0) * 1000.0)

        # 2. Time block
        t_tb0 = time.perf_counter()
        from src.indicators.time_block import render_time_block
        from src.indicators.rotated_paste import rotated_paste
        tb, tbx, tby = render_time_block(3840, 2160, below_layout, font_path, fk["date_text"], fk["time_text"])
        t_tb1 = time.perf_counter()
        ind_render_times.setdefault("time_block", []).append((t_tb1 - t_tb0) * 1000.0)
        
        if tb:
            t_p0 = time.perf_counter()
            cx = tbx + tb.width // 2
            cy = tby + tb.height // 2
            rotated_paste(img, tb, cx, cy, 0, cache_key="time_block")
            t_p1 = time.perf_counter()
            ind_paste_times.setdefault("time_block", []).append((t_p1 - t_p0) * 1000.0)
            rot_paste_times["rot0"].append((t_p1 - t_p0) * 1000.0)

        # 3. Value indicators
        known_vals = {
            "iso_text": (fk["iso_value"], "ISO", "ISO"),
            "exposure_text": (fk["exposure_value"], "", "Exp"),
            "temp_text": (fk["temp_value"], "°C", "Temp"),
            "fit_enhanced_speed_text": fk["extra_indicators"].get("fit_enhanced_speed_text", (None, "km/h", "Speed")),
            "fit_temperature_text": fk["extra_indicators"].get("fit_temperature_text", (None, "°C", "Temp")),
            "fit_cadence_text": fk["extra_indicators"].get("fit_cadence_text", (None, "RPM", "Cadence")),
            "fit_heart_rate_text": fk["extra_indicators"].get("fit_heart_rate_text", (None, "BPM", "Heart Rate")),
        }

        for key, cfg in below_layout.get("indicators", {}).items():
            if key in ("time_block", "time_display", "track_map"):
                continue
            if not cfg or not cfg.get("enabled", True):
                continue
            
            raw_entry = known_vals.get(key)
            if raw_entry is None:
                continue
            val, unit, label = raw_entry
            if val is None:
                continue

            current_cfg = cfg.copy()
            # Formatting timing
            t_fmt0 = time.perf_counter()
            default_decimals = 0 if key in ("iso_text", "exposure_text", "temp_text", "fit_heart_rate_text", "fit_cadence_text", "fit_temperature_text") else 1
            decimals = int(current_cfg.get("decimals", default_decimals))
            if key == "exposure_text":
                val_str = f"1/{int(val)}" if val and int(val) > 0 else ""
            else:
                val_str = f"{val:.{decimals}f}"
            show_units = current_cfg.get("show_units", True)
            if show_units and unit:
                fv = f"{val_str} {unit}"
            else:
                fv = val_str
            t_fmt1 = time.perf_counter()
            text_formatting_times.append((t_fmt1 - t_fmt0) * 1000.0)

            chart_vals = fk["chart_data"].get(key) if fk.get("chart_data") else None

            # Render timing
            t_r0 = time.perf_counter()
            res, rx, ry, extra = render_value_indicator(
                3840, 2160, below_layout, font_path, key, val, unit, label,
                cfg_override=current_cfg, formatted_val=fv, history_data=chart_vals,
                current_position=fk.get("current_position"), supersample=1,
                target_dt=fk.get("target_dt"), split_chart_keys=split_chart_keys,
            )
            t_r1 = time.perf_counter()
            ind_render_times.setdefault(key, []).append((t_r1 - t_r0) * 1000.0)

            # Paste timing (for non-gpu-capture widgets)
            if res and key not in gpu_chart_keys:
                t_p0 = time.perf_counter()
                cx = rx + res.width // 2
                cy = ry + res.height // 2
                rot = int(current_cfg.get("rotation", 0))
                rotated_paste(img, res, cx, cy, rot, cache_key=key)
                t_p1 = time.perf_counter()
                ind_paste_times.setdefault(key, []).append((t_p1 - t_p0) * 1000.0)
                if rot == 0:
                    rot_paste_times["rot0"].append((t_p1 - t_p0) * 1000.0)
                else:
                    rot_paste_times["rot_non0"].append((t_p1 - t_p0) * 1000.0)

    print("\n--- SUMMARY OF INDICATOR TIMINGS (MEDIAN & P95 MS) ---")
    print(f"{'Indicator':30s} | {'Form':6s} | {'Render Med':10s} | {'Render P95':10s} | {'Paste Med':10s} | {'Paste P95':10s} | {'Total Med':10s}")
    print("-" * 100)
    for ind in sorted(ind_render_times.keys()):
        r_arr = np.array(ind_render_times[ind])
        p_arr = np.array(ind_paste_times[ind]) if ind in ind_paste_times else np.zeros_like(r_arr)
        tot_arr = r_arr + p_arr
        form = below_layout.get("indicators", {}).get(ind, {}).get("form", "text" if ind != "time_block" else "time")
        print(f"{ind:30s} | {form:6s} | {np.median(r_arr):8.3f} ms | {np.percentile(r_arr, 95):8.3f} ms | {np.median(p_arr):8.3f} ms | {np.percentile(p_arr, 95):8.3f} ms | {np.median(tot_arr):8.3f} ms")

    clear_arr = np.array(clear_times)
    print(f"\nCanvas regional_clear (900 frames): median={np.median(clear_arr):.4f} ms, p95={np.percentile(clear_arr, 95):.4f} ms, max={np.max(clear_arr):.4f} ms")
    
    fmt_arr = np.array(text_formatting_times)
    print(f"Text formatting (per call): median={np.median(fmt_arr):.4f} ms, p95={np.percentile(fmt_arr, 95):.4f} ms")

    p0_arr = np.array(rot_paste_times["rot0"])
    print(f"rotated_paste (rot=0, per call): median={np.median(p0_arr):.4f} ms, p95={np.percentile(p0_arr, 95):.4f} ms")


if __name__ == "__main__":
    # 1. 3x 900 production baseline runs
    run_900_frame_audit("baseline_run1", layout_raw, start_dt_real)
    run_900_frame_audit("baseline_run2", layout_raw, start_dt_real)
    run_900_frame_audit("baseline_run3", layout_raw, start_dt_real)

    # 2. 8D reproduction test
    run_900_frame_audit("8d_reproduction_fit_none", layout_raw, start_dt_8d)

    # 3. Ablation matrix: 0 charts, 1 chart (HR), 1 chart (CAD), text-only
    l_0chart = copy.deepcopy(layout_raw)
    l_0chart["indicators"]["fit_cadence_text"]["enabled"] = False
    l_0chart["indicators"]["fit_heart_rate_text"]["enabled"] = False
    run_900_frame_audit("ablation_0_charts", l_0chart, start_dt_real)

    l_hr_only = copy.deepcopy(layout_raw)
    l_hr_only["indicators"]["fit_cadence_text"]["enabled"] = False
    l_hr_only["indicators"]["fit_heart_rate_text"]["enabled"] = True
    run_900_frame_audit("ablation_1_chart_hr_only", l_hr_only, start_dt_real)

    l_cad_only = copy.deepcopy(layout_raw)
    l_cad_only["indicators"]["fit_cadence_text"]["enabled"] = True
    l_cad_only["indicators"]["fit_heart_rate_text"]["enabled"] = False
    run_900_frame_audit("ablation_1_chart_cad_only", l_cad_only, start_dt_real)

    l_text_only = copy.deepcopy(layout_raw)
    l_text_only["indicators"]["fit_cadence_text"]["enabled"] = False
    l_text_only["indicators"]["fit_heart_rate_text"]["enabled"] = False
    l_text_only["indicators"]["track_map"]["enabled"] = False
    run_900_frame_audit("ablation_text_only", l_text_only, start_dt_real)

    # 4. Detailed per-indicator breakdown
    run_per_indicator_breakdown()
