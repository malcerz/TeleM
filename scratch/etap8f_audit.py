"""ETAP 8F Diagnostic Audit Runner & Analyzer."""
from __future__ import annotations

import argparse
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

from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.gui.layout_manager import resolve_font_path
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

out_dir = root / "Raporty" / "AMD_ETAP8F"
out_dir.mkdir(parents=True, exist_ok=True)


def run_export(
    tag: str,
    frames: int = 900,
    map_enabled: bool = True,
    gauge_enabled: bool = True,
    above_enabled: bool = True,
    profile: bool = True,
    gpu_hud_off: bool = False,
):
    print(f"\n=======================================================")
    print(f"=== RUNNING EXPORT: tag={tag} (frames={frames}) ===")
    print(f"=======================================================")

    env = {
        "AMD_MAP_PATH": "GPU",
        "AMD_MAP_FILTER": "LANCZOS",
        "AMD_CHART_PATH": "GPU_SPLIT",
        "AMD_GAUGE_PATH": "GPU",
        "AMD_TELEMETRY_MODE": "PRECOMPUTED",
        "AMD_FRAME_ACCOUNTING": "1",
        "AMD_NATIVE_FRAME_ACCOUNTING": "1" if profile else "0",
        "AMD_GPU_TIMESTAMP_PROFILE": "1" if profile else "0",
        "AMD_OVERLAY_PROFILE": "1" if profile else "0",
        "AMD_AMF_DIAG": "1",
    }
    if gpu_hud_off:
        env["AMD_GPU_HUD_OFF"] = "1"
    os.environ.update(env)

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
    tm.start_dt_utc = tm.speed_samples[0][0]

    with (root / "def_layout.json").open(encoding="utf-8") as fh:
        layout = json.load(fh)

    if not map_enabled:
        if "track_map" in layout.get("indicators", {}):
            layout["indicators"]["track_map"]["enabled"] = False
    if not gauge_enabled:
        if "speed_visual" in layout.get("indicators", {}):
            layout["indicators"]["speed_visual"]["enabled"] = False
    if not above_enabled:
        before_map = True
        for key, ind_cfg in layout.get("indicators", {}).items():
            if key == "track_map":
                before_map = False
                continue
            if not before_map:
                ind_cfg["enabled"] = False
        layout["custom_texts"] = []

    speed = smooth_speed_samples(tm.speed_samples, "moving_average", 5)
    alt = smooth_speed_samples(tm.alt_samples, "moving_average", 5)
    track = tm.track_samples
    out_mp4 = out_dir / f"{tag}.mp4"

    duration = frames * (1001 / 30000)

    t0 = time.perf_counter()
    result = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(root / "Video" / "GX030120.MP4")],
        output_file=str(out_mp4),
        duration_s=duration,
        start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=0.0,
        speed_samples=speed,
        track_samples=track,
        alt_samples=alt,
        font_path=resolve_font_path("Arial"),
        layout=layout,
        field_samples={"speed_samples": speed, "track_samples": track, "alt_samples": alt},
        max_distance_m=track[-1][1] if track else 0,
        target_fps=30000 / 1001,
        update_rate_step=1,
        workers=1,
        iso_samples=tm.iso_samples,
        exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples,
        fit_data=tm.fit_data,
        gps_track=tm.get_gps_track_for_source(layout.get("indicators", {}).get("track_map", {}).get("source", "fit")),
        encoder="amd",
        gpu=0,
    )
    wall_s = time.perf_counter() - t0
    fps = frames / wall_s if wall_s > 0 else 0
    print(f"Export {tag} done: wall={wall_s:.3f}s, FPS={fps:.3f}")
    return {
        "tag": tag,
        "frames": frames,
        "wall_s": wall_s,
        "fps": fps,
        "mp4": out_mp4,
        "result": result,
    }


def parse_csv(path: Path) -> dict[str, np.ndarray]:
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if len(lines) < 2:
        return {}
    headers = [h.strip() for h in lines[0].split(",")]
    cols: dict[str, list[float]] = {h: [] for h in headers}
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) != len(headers):
            continue
        for h, p in zip(headers, parts):
            try:
                cols[h].append(float(p))
            except ValueError:
                cols[h].append(0.0)
    return {h: np.array(v) for h, v in cols.items()}


def analyze_run(tag: str):
    py_csv = out_dir / f"{tag}.mp4.frame_accounting.csv"
    gpu_csv = out_dir / f"{tag}.mp4.gpu_timeline.csv"

    py_data = parse_csv(py_csv)
    gpu_data = parse_csv(gpu_csv)

    print(f"\n--- Analysis for {tag} ---")
    if "process_frame_total" in py_data:
        pf_tot = py_data["process_frame_total"]
        vp_tot = py_data["vp_total"]
        vp_blt = py_data["vp_blt"]
        clear_prev = py_data.get("clear_prev_above", np.zeros_like(vp_blt))
        chart_blend = py_data.get("vp_chart_blend", np.zeros_like(vp_blt))
        chart_flush = py_data.get("chart_flush", np.zeros_like(vp_blt))
        gauge_blend = py_data.get("vp_gauge_blend", np.zeros_like(vp_blt))
        gauge_flush = py_data.get("gauge_flush", np.zeros_like(vp_blt))
        map_resample = py_data.get("map_resample", np.zeros_like(vp_blt))
        map_blend = py_data.get("vp_map_blend", np.zeros_like(vp_blt))
        map_f1 = py_data.get("map_flush1", np.zeros_like(vp_blt))
        map_f2 = py_data.get("map_flush2", np.zeros_like(vp_blt))
        above_blend = py_data.get("above_blend", np.zeros_like(vp_blt))
        above_flush = py_data.get("above_flush", np.zeros_like(vp_blt))
        flush_tot = py_data.get("flush_total", np.zeros_like(vp_blt))
        hud_comp = py_data["vp_hud_compute"]
        amf_surf = py_data["amf_create_surface"]
        amf_sub = py_data["amf_submit_input"]
        amf_q = py_data["amf_query"]
        amf_w = py_data["amf_packet_write"]
        retries = py_data.get("retries", np.zeros_like(vp_blt))

        print(f"Frames analyzed: {len(pf_tot)}")
        print(f"ProcessFrame Total CPU Wall: median={np.median(pf_tot):.3f} ms, p95={np.percentile(pf_tot, 95):.3f} ms, mean={np.mean(pf_tot):.3f} ms, max={np.max(pf_tot):.3f} ms")
        print(f"  |-- VP Total:              median={np.median(vp_tot):.3f} ms, p95={np.percentile(vp_tot, 95):.3f} ms")
        print(f"  |    |-- base VideoProc:   median={np.median(vp_blt):.3f} ms, p95={np.percentile(vp_blt, 95):.3f} ms")
        print(f"  |    |-- clear prev above: median={np.median(clear_prev):.3f} ms, p95={np.percentile(clear_prev, 95):.3f} ms")
        print(f"  |    |-- chart blend:      median={np.median(chart_blend):.3f} ms, p95={np.percentile(chart_blend, 95):.3f} ms (flush={np.median(chart_flush):.3f} ms)")
        print(f"  |    |-- gauge blend:      median={np.median(gauge_blend):.3f} ms, p95={np.percentile(gauge_blend, 95):.3f} ms (flush={np.median(gauge_flush):.3f} ms)")
        print(f"  |    |-- map resample:     median={np.median(map_resample):.3f} ms, p95={np.percentile(map_resample, 95):.3f} ms (flush1={np.median(map_f1):.3f} ms)")
        print(f"  |    |-- map blend:        median={np.median(map_blend):.3f} ms, p95={np.percentile(map_blend, 95):.3f} ms (flush2={np.median(map_f2):.3f} ms)")
        print(f"  |    |-- above blend:      median={np.median(above_blend):.3f} ms, p95={np.percentile(above_blend, 95):.3f} ms (flush={np.median(above_flush):.3f} ms)")
        print(f"  |    |-- HUD compute NV12: median={np.median(hud_comp):.3f} ms, p95={np.percentile(hud_comp, 95):.3f} ms")
        print(f"  |    \-- Total Flush:      median={np.median(flush_tot):.3f} ms, p95={np.percentile(flush_tot, 95):.3f} ms")
        print(f"  |-- AMF CreateSurface:     median={np.median(amf_surf):.3f} ms, p95={np.percentile(amf_surf, 95):.3f} ms")
        print(f"  |-- AMF SubmitInput:       median={np.median(amf_sub):.3f} ms, p95={np.percentile(amf_sub, 95):.3f} ms (retries tot={np.sum(retries)})")
        print(f"  |-- AMF QueryOutput:       median={np.median(amf_q):.3f} ms, p95={np.percentile(amf_q, 95):.3f} ms")
        print(f"  \-- Packet Write:          median={np.median(amf_w):.3f} ms, p95={np.percentile(amf_w, 95):.3f} ms")

    if "span_ms" in gpu_data:
        gpu_span = gpu_data["span_ms"]
        gpu_vp = gpu_data.get("vp_ms", np.zeros_like(gpu_span))
        gpu_charts = gpu_data.get("charts_ms", np.zeros_like(gpu_span))
        gpu_gauge = gpu_data.get("gauge_ms", np.zeros_like(gpu_span))
        gpu_map = gpu_data.get("map_ms", np.zeros_like(gpu_span))
        gpu_hud = gpu_data.get("hud_ms", np.zeros_like(gpu_span))
        print(f"GPU Async Execution (D3D11 timestamps):")
        print(f"  Total GPU frame span: median={np.median(gpu_span):.3f} ms, p95={np.percentile(gpu_span, 95):.3f} ms")
        print(f"  |-- Base VPBlit:       median={np.median(gpu_vp):.3f} ms, p95={np.percentile(gpu_vp, 95):.3f} ms")
        print(f"  |-- Charts:            median={np.median(gpu_charts):.3f} ms, p95={np.percentile(gpu_charts, 95):.3f} ms")
        print(f"  |-- Gauge:             median={np.median(gpu_gauge):.3f} ms, p95={np.percentile(gpu_gauge, 95):.3f} ms")
        print(f"  |-- Map:               median={np.median(gpu_map):.3f} ms, p95={np.percentile(gpu_map, 95):.3f} ms")
        print(f"  \-- HUD Compute:       median={np.median(gpu_hud):.3f} ms, p95={np.percentile(gpu_hud, 95):.3f} ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("full3", "ablation", "control", "profile_cmp", "all"), default="all")
    args = parser.parse_args()

    results = {}
    if args.mode in ("full3", "all"):
        for tag in ("8ffull1", "8ffull2", "8ffull3"):
            res = run_export(tag, frames=900)
            results[tag] = res
            analyze_run(tag)

    if args.mode in ("ablation", "all"):
        ab_runs = [
            ("8f_ablation_full", True, True, True),
            ("8f_ablation_map_off", False, True, True),
            ("8f_ablation_gauge_off", True, False, True),
            ("8f_ablation_map_gauge_off", False, False, True),
        ]
        for tag, m_on, g_on, ab_on in ab_runs:
            res = run_export(tag, frames=900, map_enabled=m_on, gauge_enabled=g_on, above_enabled=ab_on)
            results[tag] = res
            analyze_run(tag)

    if args.mode in ("control", "all"):
        res = run_export("8f_control_hud_only", frames=900, map_enabled=False, gauge_enabled=False, above_enabled=False)
        results["8f_control_hud_only"] = res
        analyze_run("8f_control_hud_only")

    if args.mode in ("profile_cmp", "all"):
        res_off = run_export("8f_profile_off", frames=900, profile=False)
        results["8f_profile_off"] = res_off
        res_on = run_export("8f_profile_on", frames=900, profile=True)
        results["8f_profile_on"] = res_on
        analyze_run("8f_profile_on")

    print("\n=======================================================")
    print("=== SUMMARY OF ALL ETAP 8F BENCHMARK RUNS ===")
    print("=======================================================")
    for k, v in results.items():
        print(f"{k:26s} | frames={v['frames']:4d} | wall={v['wall_s']:6.2f}s | FPS={v['fps']:6.3f}")
