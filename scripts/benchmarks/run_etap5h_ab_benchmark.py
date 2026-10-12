"""Comprehensive A/B Benchmark Runner for SPORTCAMHUD - ETAP 5H.

Executes rigorous A/B comparisons (Q=2 vs Q=3) and canonical 3000-frame 4K production runs:
- Resolution: 3840x2160 @ 29.970 fps
- Bitrate: 45M, Quality: FAST, Codec: hevc
- Single Live Mux (HEVC + AAC)
- Strictly safe production memory architecture:
  * AMD_DIRECT_ROW_TABLE=0 (Zero private Pillow offsets)
  * Public Pillow API
  * ASYNC Producer-Consumer pipeline
- Strict 8-counter reporting:
  1. frames_encoded
  2. frames_rendered
  3. process_wall_s
  4. render_active_s
  5. startup_s
  6. finalization_s
  7. render_fps
  8. effective_fps
- Peak RSS memory tracking (via psutil)
- Detailed indicator & composite timings breakdown
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

REPO_ROOT = Path("C:/_DEV/BikeRideHUD-main-new").resolve()
VIDEO_PATH = Path("D:/Comparator/GX010344.MP4").resolve()
FIT_PATH = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4B_RESULTS_20261012/fit/24609739177.fit").resolve()
LAYOUT_PATH = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4E_RESULTS_20261012/matrix/layouts/A_all_with_effects.json").resolve()
OUTPUT_DIR = Path("C:/_DEV/_SPORTCAMHUD_ETAP_5H_RESULTS_20261012").resolve()
PYTHON_EXE = Path(r"C:\Users\Malcerz\AppData\Local\Python\pythoncore-3.14-64\python.exe").resolve()

START_SECONDS = 120.0
QUALITY = "FAST"
CODEC = "hevc"
BITRATE = "45M"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def probe_video(path: Path) -> dict[str, Any]:
    ffprobe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path)
    ]
    p = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def track_process_memory(proc: subprocess.Popen, peak_mem_container: list[float], stop_event: threading.Event):
    """Periodically sample RSS memory of the process and its children."""
    try:
        p = psutil.Process(proc.pid)
    except Exception:
        return

    peak = 0.0
    while not stop_event.is_set() and proc.poll() is None:
        try:
            mem = p.memory_info().rss
            for child in p.children(recursive=True):
                try:
                    mem += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            peak = max(peak, mem / (1024 * 1024)) # MB
            time.sleep(0.05)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break
    peak_mem_container[0] = peak


def run_benchmark_trial(
    tag: str,
    frames: int,
    q_depth: int,
    pipeline_mode: str = "ASYNC",
    direct_row_table: str = "0",
    is_warmup: bool = False,
    subfolder: str = "trials",
) -> dict[str, Any]:
    run_dir = OUTPUT_DIR / subfolder / tag
    iso_dir = run_dir / "isolation"
    iso_dir.mkdir(parents=True, exist_ok=True)

    out_mp4 = run_dir / f"{tag}.mp4"
    res_json = run_dir / f"{tag}_result.json"
    prof_json = run_dir / f"{tag}.mp4.amd_profile.json"
    log_file = run_dir / f"{tag}.log"

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["AMD_OVERLAY_PROFILE"] = "1"
    env["AMD_PRODUCTION_ACCOUNTING"] = "1"
    env["APPDATA"] = str(iso_dir / "appdata")
    env["TELEM_CACHE_ROOT"] = str(iso_dir / "telemetry_cache")
    env["AMD_DIRECT_ROW_TABLE"] = direct_row_table
    env["AMD_CPU_GPU_PIPELINE"] = pipeline_mode
    env["AMD_QUEUE_DEPTH"] = str(q_depth)

    cli_cmd = [
        str(PYTHON_EXE), str(REPO_ROOT / "SportCamHUD.py"), "--test-amd-export", "--mode", "direct",
        "--video", str(VIDEO_PATH), "--fit", str(FIT_PATH), "--frames", str(frames),
        "--quality", QUALITY, "--codec", CODEC, "--bitrate", BITRATE,
        "--start-seconds", str(START_SECONDS), "--output", str(out_mp4),
        "--result-json", str(res_json), "--layout", str(LAYOUT_PATH),
    ]

    print(f"\n========================================================")
    print(f"RUNNING TRIAL: {tag} ({frames} FRAMES, Q={q_depth}, {'WARMUP' if is_warmup else 'MEASURED'})")
    print(f"Command: {' '.join(cli_cmd[:6])} ...")
    print(f"========================================================")

    peak_rss = [0.0]
    stop_mem_tracking = threading.Event()

    t_process_start = time.perf_counter()
    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cli_cmd, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        mem_thread = threading.Thread(target=track_process_memory, args=(proc, peak_rss, stop_mem_tracking), daemon=True)
        mem_thread.start()
        rc = proc.wait(timeout=1800)
        stop_mem_tracking.set()
        mem_thread.join(timeout=1.0)
    process_wall_s = time.perf_counter() - t_process_start

    if rc != 0 or not res_json.is_file():
        raise RuntimeError(f"Trial {tag} FAILED with code {rc}; see {log_file}")

    res_data = json.loads(res_json.read_text(encoding="utf-8"))
    prof_data = json.loads(prof_json.read_text(encoding="utf-8")) if prof_json.is_file() else {}
    timings = prof_data.get("timings", {})

    frames_encoded = res_data.get("total_frames", frames)
    frames_rendered = frames_encoded # 1:1 in non-dropping mode

    stats_block = res_data.get("stats", {})
    render_fps = float(stats_block.get("render_fps", prof_data.get("true_fps", 0.0)))
    if render_fps > 0:
        render_active_s = frames_rendered / render_fps
    else:
        render_active_s = process_wall_s

    # Strict definitions
    effective_fps = frames_encoded / process_wall_s if process_wall_s > 0 else 0.0

    # Startup & finalization derivation
    # elapsed_s in res_data is time inside GUI worker
    gui_elapsed_s = float(res_data.get("elapsed_s", process_wall_s))
    startup_s = max(0.0, process_wall_s - gui_elapsed_s)
    # The active render time is inside gui_elapsed_s:
    # gui_elapsed_s = render_active_s + finalization_s
    finalization_s = max(0.0, gui_elapsed_s - render_active_s)

    # Cross-check: startup_s + render_active_s + finalization_s == process_wall_s
    residual = abs(process_wall_s - (startup_s + render_active_s + finalization_s))

    sha256 = compute_sha256(out_mp4) if out_mp4.is_file() else ""
    probe_info = probe_video(out_mp4) if out_mp4.is_file() else {}

    def _t(k):
        v = timings.get(k)
        if isinstance(v, dict):
            return v.get("avg_ms", 0.0)
        return float(v) if v is not None else 0.0

    summary = {
        "tag": tag,
        "is_warmup": is_warmup,
        "frames_encoded": frames_encoded,
        "frames_rendered": frames_rendered,
        "process_wall_s": round(process_wall_s, 3),
        "render_active_s": round(render_active_s, 3),
        "startup_s": round(startup_s, 3),
        "finalization_s": round(finalization_s, 3),
        "render_fps": round(render_fps, 3),
        "effective_fps": round(effective_fps, 3),
        "peak_rss_mb": round(peak_rss[0], 2),
        "q_depth": q_depth,
        "pipeline_mode": pipeline_mode,
        "direct_row_table": direct_row_table,
        "sha256": sha256,
        "out_mp4": str(out_mp4),
        "size_bytes": out_mp4.stat().st_size if out_mp4.is_file() else 0,
        "producer_prepare_ms": _t("producer_prepare"),
        "consumer_queue_wait_ms": _t("consumer_queue_wait"),
        "producer_queue_wait_ms": _t("producer_queue_wait"),
        "compose_overlay_ms": _t("compose_overlay"),
        "buffer_prep_ms": _t("PIL/buffer preparation"),
        "speed_text_ms": _t("widget.speed_text.total"),
        "fit_distance_ms": _t("widget.fit_distance_text.total"),
        "fit_power_ms": _t("widget.fit_curVpower_text.total"),
        "probe": probe_info,
    }

    print(f"\n--- TRIAL RESULTS: {tag} ---")
    print(f"  Frames Encoded      : {frames_encoded}")
    print(f"  Process Wall Time   : {process_wall_s:.2f} s")
    print(f"  Render Active Time  : {render_active_s:.2f} s (Startup: {startup_s:.2f}s, Finalize: {finalization_s:.2f}s)")
    print(f"  Render FPS          : {render_fps:.2f} FPS")
    print(f"  Effective FPS       : {effective_fps:.2f} FPS")
    print(f"  Peak Memory (RSS)   : {peak_rss[0]:.1f} MB")
    print(f"  compose_overlay     : {summary['compose_overlay_ms']:.2f} ms")
    print(f"  producer_prepare    : {summary['producer_prepare_ms']:.2f} ms")
    print(f"  consumer_queue_wait : {summary['consumer_queue_wait_ms']:.2f} ms")
    print(f"  widget.fit_distance : {summary['fit_distance_ms']:.3f} ms")
    print(f"  widget.speed_text   : {summary['speed_text_ms']:.3f} ms")
    print(f"  SHA-256             : {sha256}")
    return summary


def run_ab_matrix_1000():
    """Run A/B Queue comparison for 1000 frames with warmup and alternating sequence."""
    print("\n================================================================================")
    print("STARTING ETAP 5H A/B MATRIX (1000 FRAMES): Q=2 vs Q=3 (WARMUP + ALTERNATING)")
    print("================================================================================")

    # 1. Warmup run (discarded)
    print("\n[STEP 1/5] WARMUP RUN (Q=2, 1000 frames) - will be excluded from comparative analysis")
    warmup_res = run_benchmark_trial("warmup_q2_1000f", 1000, q_depth=2, is_warmup=True, subfolder="matrix_1000f")

    # 2. Alternating trials: Q=2, Q=3, Q=2, Q=3
    sequence = [
        ("run1_q2_1000f", 2),
        ("run2_q3_1000f", 3),
        ("run3_q2_1000f", 2),
        ("run4_q3_1000f", 3),
    ]

    trials = [warmup_res]
    for tag, q in sequence:
        res = run_benchmark_trial(tag, 1000, q_depth=q, is_warmup=False, subfolder="matrix_1000f")
        trials.append(res)

    out_file = OUTPUT_DIR / "matrix_1000f" / "etap5h_ab_1000f_summary.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(trials, indent=2), encoding="utf-8")
    print(f"\n1000-Frame A/B Matrix complete. Summary saved to {out_file}")
    return trials


def run_canonical_3000(q_depth: int = 3, runs: int = 3):
    """Run canonical 3000-frame 4K production runs."""
    print("\n================================================================================")
    print(f"STARTING ETAP 5H CANONICAL 3000-FRAME 4K RUNS (Q={q_depth}, {runs} RUNS)")
    print("================================================================================")

    results = []
    for r in range(1, runs + 1):
        tag = f"etap5h_canonical_run{r}_3000f"
        res = run_benchmark_trial(tag, 3000, q_depth=q_depth, is_warmup=False, subfolder="canonical_3000f")
        results.append(res)

    out_file = OUTPUT_DIR / "canonical_3000f" / f"etap5h_canonical_3000f_q{q_depth}_summary.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nCanonical 3000-Frame Benchmark complete. Summary saved to {out_file}")
    return results


def main():
    parser = argparse.ArgumentParser(description="SPORTCAMHUD ETAP 5H Benchmark Runner")
    parser.add_argument("--mode", choices=["all", "matrix1000", "canonical3000"], default="all")
    parser.add_argument("--q-depth", type=int, default=3, help="Default queue depth for canonical runs")
    parser.add_argument("--runs", type=int, default=3, help="Number of canonical runs")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.mode in ("all", "matrix1000"):
        run_ab_matrix_1000()

    if args.mode in ("all", "canonical3000"):
        run_canonical_3000(q_depth=args.q_depth, runs=args.runs)


if __name__ == "__main__":
    main()
