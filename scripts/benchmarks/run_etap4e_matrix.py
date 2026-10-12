"""Benchmark runner for SPORTCAMHUD - ETAP 4E: Root Cause Per Graphical Indicator.

Executes AMD Native export runs for the matrix layouts:
  - Global variants: A_all_with_effects, B_all_no_effects, C_text_only, F_graphical_no_effects, G_graphical_with_effects
  - Per-widget variants: D (no effects), E (with effects), S (shadow only), O (outline only) for each of the 12 graphical indicators
Extracts:
  - Render FPS & Effective FPS
  - Timing breakdown: producer_prepare, compose_overlay, consumer_queue_wait, amf_submit, MF ReadSample, etc.
  - Per-widget timing samples (base_render, effects, shadow, outline, needle_ms, paste, render)
  - Dirty rect count and upload bytes
  - GPU engine utilization (Video Codec 0, 3D, CPU)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path("C:/_DEV/BikeRideHUD-main-new").resolve()
VIDEO_PATH = Path("D:/Comparator/GX010344.MP4").resolve()
FIT_PATH = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4B_RESULTS_20261012/fit/24609739177.fit").resolve()
BASE_RESULTS_DIR = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4E_RESULTS_20261012").resolve()
LAYOUTS_DIR = BASE_RESULTS_DIR / "matrix" / "layouts"
RUNS_DIR = BASE_RESULTS_DIR / "matrix" / "runs"
ISOLATION_DIR = BASE_RESULTS_DIR / "matrix" / "isolation"
MONITOR_SCRIPT = REPO_ROOT / "tools" / "amd_stage4b_gpu_monitor.ps1"
PYTHON_EXE = Path(sys.executable).resolve()


def ensure_dirs() -> None:
    for d in (RUNS_DIR, ISOLATION_DIR / "appdata", ISOLATION_DIR / "localappdata", ISOLATION_DIR / "telemetry_cache"):
        d.mkdir(parents=True, exist_ok=True)


def parse_gpu_csv(csv_path: Path) -> dict[str, float]:
    """Parse GPU monitor CSV to extract median and peak utilization for Video Codec 0 and 3D."""
    if not csv_path.is_file():
        return {}
    video_vals: list[float] = []
    gpu_3d_vals: list[float] = []
    try:
        with csv_path.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                eng_type = (row.get("EngineType") or "").strip().lower()
                pct_str = row.get("UtilizationPct") or "0"
                try:
                    pct = float(pct_str)
                except ValueError:
                    continue
                if "video" in eng_type or "codec" in eng_type:
                    video_vals.append(pct)
                elif "3d" in eng_type:
                    gpu_3d_vals.append(pct)
    except Exception as e:
        print(f"[WARN] Failed parsing GPU CSV {csv_path}: {e}")

    def _stats(arr: list[float], prefix: str) -> dict[str, float]:
        if not arr:
            return {f"{prefix}_median": 0.0, f"{prefix}_max": 0.0, f"{prefix}_avg": 0.0}
        s = sorted(arr)
        mid = len(s) // 2
        med = (s[mid] if len(s) % 2 != 0 else (s[mid - 1] + s[mid]) / 2.0)
        return {
            f"{prefix}_median": round(med, 2),
            f"{prefix}_max": round(max(arr), 2),
            f"{prefix}_avg": round(sum(arr) / len(arr), 2),
        }

    res = {}
    res.update(_stats(video_vals, "gpu_video_codec"))
    res.update(_stats(gpu_3d_vals, "gpu_3d"))
    return res


def run_benchmark(
    layout_name: str,
    frames: int = 300,
    start_seconds: float = 120.0,
    quality: str = "FAST",
    bitrate: str = "40M",
    profile_effects: bool = False,
) -> dict[str, Any]:
    ensure_dirs()
    layout_file = LAYOUTS_DIR / f"{layout_name}.json"
    if not layout_file.is_file():
        raise FileNotFoundError(f"Layout not found: {layout_file}")

    stem = f"{layout_name}_f{frames}"
    output_mp4 = RUNS_DIR / f"{stem}.mp4"
    result_json = RUNS_DIR / f"{stem}.json"
    profile_json = RUNS_DIR / f"{stem}.mp4.amd_profile.json"
    stdout_log = RUNS_DIR / f"{stem}.log"
    monitor_base = RUNS_DIR / f"{stem}_mon"
    monitor_out = RUNS_DIR / f"{stem}_mon_stdout.log"
    monitor_err = RUNS_DIR / f"{stem}_mon_stderr.log"

    # Cleanup any prior run outputs if rerun is requested
    for f in (output_mp4, result_json, profile_json, stdout_log,
              Path(str(monitor_base) + "_gpu.csv"), Path(str(monitor_base) + "_system.csv")):
        if f.exists():
            try:
                f.unlink()
            except OSError:
                pass

    env = os.environ.copy()
    env["APPDATA"] = str(ISOLATION_DIR / "appdata")
    env["LOCALAPPDATA"] = str(ISOLATION_DIR / "localappdata")
    env["TELEM_CACHE_ROOT"] = str(ISOLATION_DIR / "telemetry_cache")
    env["PYTHONUTF8"] = "1"
    if profile_effects:
        env["TELEM_EFFECTS_CACHE_PROFILE"] = "1"
        env["AMD_OVERLAY_PROFILE"] = "1"
        env["AMD_PRODUCTION_ACCOUNTING"] = "1"

    cmd = [
        str(PYTHON_EXE), str(REPO_ROOT / "SportCamHUD.py"), "--test-amd-export", "--mode", "direct",
        "--video", str(VIDEO_PATH), "--fit", str(FIT_PATH), "--frames", str(frames),
        "--quality", quality, "--codec", "hevc", "--bitrate", bitrate,
        "--start-seconds", str(start_seconds), "--output", str(output_mp4),
        "--result-json", str(result_json), "--layout", str(layout_file),
    ]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Launching: {stem} ({frames} frames)...", flush=True)
    t0 = time.perf_counter()
    started_utc = datetime.now(timezone.utc).isoformat()

    with stdout_log.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        mon_log = monitor_out.open("w", encoding="utf-8", errors="replace")
        mon_err = monitor_err.open("w", encoding="utf-8", errors="replace")
        mon_proc = None
        if MONITOR_SCRIPT.is_file():
            mon_proc = subprocess.Popen(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(MONITOR_SCRIPT),
                    "-RootPid", str(proc.pid), "-OutputPrefix", str(monitor_base),
                ],
                cwd=REPO_ROOT,
                env=env,
                stdout=mon_log,
                stderr=mon_err,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        try:
            rc = proc.wait(timeout=1800)
        finally:
            if mon_proc is not None:
                try:
                    mon_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    mon_proc.terminate()
                    mon_proc.wait(timeout=5)
            mon_log.close()
            mon_err.close()

    wall_s = time.perf_counter() - t0
    finished_utc = datetime.now(timezone.utc).isoformat()

    if rc != 0 or not result_json.is_file():
        raise RuntimeError(f"Run {stem} failed with returncode {rc}; see {stdout_log}")

    res_data = json.loads(result_json.read_text(encoding="utf-8"))
    if not res_data.get("success"):
        raise RuntimeError(f"Run {stem} failed (success=False): {res_data.get('error')}; see {stdout_log}")
    prof_data = json.loads(profile_json.read_text(encoding="utf-8")) if profile_json.is_file() else {}
    gpu_stats = parse_gpu_csv(Path(str(monitor_base) + "_gpu.csv"))

    # Extract metrics
    app_elapsed_s = res_data.get("elapsed_s", wall_s)
    render_fps = res_data.get("stats", {}).get("render_fps", (frames / app_elapsed_s if app_elapsed_s > 0 else 0.0))
    effective_fps = frames / app_elapsed_s if app_elapsed_s > 0 else 0.0

    timings = prof_data.get("timings", {})
    hud_sec = prof_data.get("hud_texture_pipeline", {})
    bench_sec = prof_data.get("benchmark", {})

    # Extract all per-widget breakdown stats from timings
    widget_metrics: dict[str, float] = {}
    for k, v in timings.items():
        if k.startswith("widget.") and isinstance(v, dict):
            widget_metrics[k] = v.get("avg_ms", 0.0)

    summary = {
        "layout": layout_name,
        "frames": frames,
        "wall_time_s": round(wall_s, 2),
        "app_elapsed_s": round(app_elapsed_s, 2),
        "render_fps": round(render_fps, 2),
        "effective_fps": round(effective_fps, 2),
        "amf_qp": res_data.get("stats", {}).get("avg_qp"),
        "producer_prepare_ms": (timings.get("producer_prepare") or {}).get("avg_ms", 0.0),
        "compose_overlay_ms": (timings.get("compose_overlay") or {}).get("avg_ms", 0.0),
        "consumer_queue_wait_ms": (timings.get("consumer_queue_wait") or {}).get("avg_ms", 0.0),
        "decode_wait_ms": (timings.get("Decode/pipe wait") or {}).get("avg_ms", 0.0),
        "mf_readsample_ms": (timings.get("MF ReadSample/decode availability") or {}).get("avg_ms", 0.0),
        "hud_upload_ms": (timings.get("HUD texture upload") or {}).get("avg_ms", 0.0),
        "amf_submit_ms": (timings.get("AMF submit/backpressure") or {}).get("avg_ms", 0.0),
        "dirty_bbox_ms": (timings.get("HUD dirty bbox") or {}).get("avg_ms", 0.0),
        "pil_buffer_prep_ms": (timings.get("PIL/buffer preparation") or {}).get("avg_ms", 0.0),
        "avg_dirty_rects": hud_sec.get("dirty_rect_count_avg", 0.0),
        "avg_upload_bytes_frame": hud_sec.get("requested_upload_bytes_avg", 0.0),
        "gpu_stats": gpu_stats,
        "widget_metrics": widget_metrics,
        "output_mp4": str(output_mp4),
        "output_size_bytes": output_mp4.stat().st_size if output_mp4.exists() else 0,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
    }

    print(
        f"  -> Done in {wall_s:.1f}s | Effective FPS: {effective_fps:.2f} | "
        f"Render FPS: {render_fps:.2f} | Compose: {summary['compose_overlay_ms']:.2f}ms | "
        f"Upload: {summary['avg_upload_bytes_frame']/1024/1024:.2f}MB/f | "
        f"Video Codec: {gpu_stats.get('gpu_video_codec_median', 0.0)}%",
        flush=True,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", nargs="+", help="Specific layouts to run; defaults to standard matrix")
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--canonical-frames", type=int, default=3000)
    parser.add_argument("--skip-canonical", action="store_true", help="Skip 3000-frame canonical runs")
    args = parser.parse_args()

    results: dict[str, Any] = {}
    summary_path = BASE_RESULTS_DIR / "matrix_summary.json"
    if summary_path.is_file():
        try:
            results = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 1. Target variants to run
    graphical_keys = [
        "alt_text",
        "fit_cadence_text",
        "fit_curVpower_text",
        "fit_distance_text",
        "fit_garmin_battery_percent_text",
        "fit_heart_rate_text",
        "fit_solar_text",
        "fit_temperature_text",
        "lean_indicator",
        "speed_text",
        "track_map",
        "compass",
    ]

    if args.variants:
        target_list = args.variants
    else:
        # Standard matrix:
        # Global runs:
        target_list = [
            "A_all_with_effects",
            "B_all_no_effects",
            "C_text_only",
            "F_graphical_no_effects",
            "G_graphical_with_effects",
        ]
        # Per-widget runs:
        for k in graphical_keys:
            target_list.extend([
                f"D_{k}_no_effects",
                f"E_{k}_with_effects",
                f"S_{k}_shadow_only",
                f"O_{k}_outline_only",
            ])

    print(f"=== SPORTCAMHUD ETAP 4E BENCHMARK MATRIX ({len(target_list)} variants, {args.frames} frames each) ===", flush=True)

    for layout_name in target_list:
        if layout_name in results and results[layout_name].get("frames") == args.frames:
            print(f"Skipping already completed {layout_name} ({args.frames} frames)...", flush=True)
            continue
        try:
            res = run_benchmark(layout_name, frames=args.frames)
            results[layout_name] = res
            summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as e:
            print(f"[ERROR] Failed {layout_name}: {e}", flush=True)

    # 2. Canonical runs (3000 frames) for decisive variants A, B, C
    if not args.skip_canonical:
        canonical_variants = ["A_all_with_effects", "B_all_no_effects", "C_text_only"]
        print(f"\n=== CANONICAL RUNS ({len(canonical_variants)} variants, {args.canonical_frames} frames each) ===", flush=True)
        for layout_name in canonical_variants:
            c_key = f"{layout_name}_canonical"
            if c_key in results and results[c_key].get("frames") == args.canonical_frames:
                print(f"Skipping already completed {c_key} ({args.canonical_frames} frames)...", flush=True)
                continue
            try:
                res = run_benchmark(layout_name, frames=args.canonical_frames)
                results[c_key] = res
                summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            except Exception as e:
                print(f"[ERROR] Failed {c_key}: {e}", flush=True)

    print(f"\n=== BENCHMARK MATRIX COMPLETE! Results saved to {summary_path} ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
