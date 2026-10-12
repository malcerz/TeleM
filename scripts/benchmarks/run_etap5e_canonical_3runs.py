"""Runner for SPORTCAMHUD - ETAP 5E Canonical 3x 3000-frame Benchmark Suite.

Executes 3 consecutive canonical export runs for A_all_with_effects:
  - 3000 frames
  - GX010344.MP4 starting from 120.0 seconds
  - AMF HEVC, QP 28 FAST, 45M bitrate
  - Full HUD layout with all 17 widgets and effects enabled
Extracts:
  - Effective FPS & Render FPS
  - Stage timings: producer_prepare, compose_overlay, PIL/buffer preparation, consumer_queue_wait
  - Per-widget timings: speed_text, fit_distance_text, fit_curVpower_text
  - ffprobe integrity and stream validation
  - SHA-256 checksums
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("C:/_DEV/BikeRideHUD-main-new").resolve()
VIDEO_PATH = Path("D:/Comparator/GX010344.MP4").resolve()
FIT_PATH = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4B_RESULTS_20261012/fit/24609739177.fit").resolve()
LAYOUT_PATH = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4E_RESULTS_20261012/matrix/layouts/A_all_with_effects.json").resolve()
OUTPUT_DIR = Path("C:/_DEV/_SPORTCAMHUD_ETAP_5E_RESULTS_20261012/canonical_3000").resolve()
PYTHON_EXE = Path(r"C:\Users\Malcerz\AppData\Local\Python\pythoncore-3.14-64\python.exe").resolve()
ISOLATION_DIR = OUTPUT_DIR / "isolation"

FRAMES = 3000
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


def run_single(run_idx: int) -> dict:
    stem = f"run_{run_idx}"
    out_mp4 = OUTPUT_DIR / f"{stem}.mp4"
    res_json = OUTPUT_DIR / f"{stem}_result.json"
    prof_json = OUTPUT_DIR / f"{stem}.mp4.amd_profile.json"
    log_file = OUTPUT_DIR / f"{stem}.log"

    for f in (out_mp4, res_json, prof_json, log_file):
        if f.exists():
            try:
                f.unlink()
            except OSError:
                pass

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["AMD_OVERLAY_PROFILE"] = "1"
    env["AMD_PRODUCTION_ACCOUNTING"] = "1"
    env["APPDATA"] = str(ISOLATION_DIR / "appdata")
    env["TELEM_CACHE_ROOT"] = str(ISOLATION_DIR / "telemetry_cache")

    cmd = [
        str(PYTHON_EXE), str(REPO_ROOT / "SportCamHUD.py"), "--test-amd-export", "--mode", "direct",
        "--video", str(VIDEO_PATH), "--fit", str(FIT_PATH), "--frames", str(FRAMES),
        "--quality", QUALITY, "--codec", CODEC, "--bitrate", BITRATE,
        "--start-seconds", str(START_SECONDS), "--output", str(out_mp4),
        "--result-json", str(res_json), "--layout", str(LAYOUT_PATH),
    ]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Launching Run {run_idx}/3 (3000 frames)...", flush=True)
    t0 = time.perf_counter()
    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        rc = proc.wait(timeout=1800)
    wall_s = time.perf_counter() - t0

    if rc != 0 or not res_json.is_file():
        raise RuntimeError(f"Run {run_idx} failed with code {rc}; check {log_file}")

    result_data = json.loads(res_json.read_text(encoding="utf-8"))
    prof_data = json.loads(prof_json.read_text(encoding="utf-8")) if prof_json.is_file() else {}

    elapsed_s = result_data.get("elapsed_s", wall_s)
    effective_fps = FRAMES / elapsed_s if elapsed_s > 0 else 0.0
    true_fps = prof_data.get("true_fps", effective_fps)
    render_fps = result_data.get("stats", {}).get("render_fps", true_fps)
    stage_timings = prof_data.get("timings", {})

    def get_avg(k: str) -> float:
        v = stage_timings.get(k)
        if isinstance(v, dict):
            return float(v.get("avg_ms", 0.0))
        return 0.0

    def get_p95(k: str) -> float:
        v = stage_timings.get(k)
        if isinstance(v, dict):
            return float(v.get("p95_ms", 0.0))
        return 0.0

    def get_med(k: str) -> float:
        v = stage_timings.get(k)
        if isinstance(v, dict):
            return float(v.get("median_ms", 0.0))
        return 0.0

    # Probe video with ffprobe
    ffprobe_cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_frames,pix_fmt",
        "-of", "json", str(out_mp4)
    ]
    ffprobe_res = subprocess.run(ffprobe_cmd, capture_output=True, text=True)
    probe_info = json.loads(ffprobe_res.stdout) if ffprobe_res.returncode == 0 else {}

    sha256 = compute_sha256(out_mp4) if out_mp4.is_file() else ""
    file_size_mb = out_mp4.stat().st_size / (1024 * 1024) if out_mp4.is_file() else 0.0

    run_meta = {
        "run_idx": run_idx,
        "wall_s": wall_s,
        "elapsed_s": elapsed_s,
        "effective_fps": effective_fps,
        "true_fps": true_fps,
        "render_fps": render_fps,
        "file_size_mb": file_size_mb,
        "sha256": sha256,
        "probe": probe_info,
        "stages": {
            "producer_prepare": {"avg_ms": get_avg("producer_prepare"), "median_ms": get_med("producer_prepare"), "p95_ms": get_p95("producer_prepare")},
            "compose_overlay": {"avg_ms": get_avg("compose_overlay"), "median_ms": get_med("compose_overlay"), "p95_ms": get_p95("compose_overlay")},
            "buffer_preparation": {"avg_ms": get_avg("PIL/buffer preparation"), "median_ms": get_med("PIL/buffer preparation"), "p95_ms": get_p95("PIL/buffer preparation")},
            "consumer_queue_wait": {"avg_ms": get_avg("consumer_queue_wait"), "median_ms": get_med("consumer_queue_wait"), "p95_ms": get_p95("consumer_queue_wait")},
            "speed_text": {"avg_ms": get_avg("widget.speed_text.total"), "median_ms": get_med("widget.speed_text.total"), "p95_ms": get_p95("widget.speed_text.total")},
            "fit_distance_text": {"avg_ms": get_avg("widget.fit_distance_text.total"), "median_ms": get_med("widget.fit_distance_text.total"), "p95_ms": get_p95("widget.fit_distance_text.total")},
            "fit_curVpower_text": {"avg_ms": get_avg("widget.fit_curVpower_text.total"), "median_ms": get_med("widget.fit_curVpower_text.total"), "p95_ms": get_p95("widget.fit_curVpower_text.total")},
        }
    }
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Run {run_idx} Complete: "
        f"Effective FPS = {effective_fps:.2f}, Render FPS = {render_fps:.2f}, "
        f"Prepare = {run_meta['stages']['producer_prepare']['avg_ms']:.2f}ms, "
        f"BufferPrep = {run_meta['stages']['buffer_preparation']['avg_ms']:.2f}ms, "
        f"Compose = {run_meta['stages']['compose_overlay']['avg_ms']:.2f}ms, "
        f"QueueWait = {run_meta['stages']['consumer_queue_wait']['avg_ms']:.2f}ms",
        flush=True
    )
    return run_meta


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ISOLATION_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("SPORTCAMHUD — ETAP 5E: CANONICAL 3x 3000-FRAME BENCHMARK")
    print(f"Output Directory: {OUTPUT_DIR}")
    print(f"Layout: {LAYOUT_PATH}")
    print(f"Video: {VIDEO_PATH} (from {START_SECONDS}s, {FRAMES} frames)")
    print(f"FIT: {FIT_PATH}")
    print("=" * 80)

    runs = []
    for r in (1, 2, 3):
        runs.append(run_single(r))

    avg_eff_fps = sum(r["effective_fps"] for r in runs) / 3.0
    avg_rnd_fps = sum(r["render_fps"] for r in runs) / 3.0
    avg_prep = sum(r["stages"]["producer_prepare"]["avg_ms"] for r in runs) / 3.0
    avg_buf_prep = sum(r["stages"]["buffer_preparation"]["avg_ms"] for r in runs) / 3.0
    avg_comp = sum(r["stages"]["compose_overlay"]["avg_ms"] for r in runs) / 3.0
    avg_qwait = sum(r["stages"]["consumer_queue_wait"]["avg_ms"] for r in runs) / 3.0

    avg_speed = sum(r["stages"]["speed_text"]["avg_ms"] for r in runs) / 3.0
    avg_dist = sum(r["stages"]["fit_distance_text"]["avg_ms"] for r in runs) / 3.0
    avg_pwr = sum(r["stages"]["fit_curVpower_text"]["avg_ms"] for r in runs) / 3.0

    summary = {
        "benchmark": "SPORTCAMHUD_ETAP_5E_CANONICAL_3x3000",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "aggregate": {
            "avg_effective_fps": avg_eff_fps,
            "avg_render_fps": avg_rnd_fps,
            "avg_producer_prepare_ms": avg_prep,
            "avg_buffer_preparation_ms": avg_buf_prep,
            "avg_compose_overlay_ms": avg_comp,
            "avg_consumer_queue_wait_ms": avg_qwait,
            "avg_speed_text_ms": avg_speed,
            "avg_fit_distance_text_ms": avg_dist,
            "avg_fit_curVpower_text_ms": avg_pwr,
            "three_bottlenecks_total_ms": avg_speed + avg_dist + avg_pwr,
        },
        "runs": runs,
    }

    summary_file = OUTPUT_DIR / "canonical_3runs_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    manifest = {
        f"run_{r['run_idx']}.mp4": {
            "sha256": r["sha256"],
            "size_bytes": int(r["file_size_mb"] * 1024 * 1024),
            "effective_fps": r["effective_fps"],
            "render_fps": r["render_fps"],
        }
        for r in runs
    }
    manifest_file = OUTPUT_DIR / "mp4_manifest_sha256.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\n" + "=" * 80)
    print("CANONICAL 3x 3000 RUNS COMPLETE")
    print(f"Average Effective FPS: {avg_eff_fps:.2f}")
    print(f"Average Render FPS:    {avg_rnd_fps:.2f}")
    print(f"Average Prepare:       {avg_prep:.2f} ms")
    print(f"Average Buffer Prep:   {avg_buf_prep:.2f} ms")
    print(f"Average Compose:       {avg_comp:.2f} ms")
    print(f"Average Queue Wait:    {avg_qwait:.2f} ms")
    print(f"Three Bottlenecks:     {avg_speed + avg_dist + avg_pwr:.2f} ms (Speed: {avg_speed:.2f}ms, Dist: {avg_dist:.2f}ms, Pwr: {avg_pwr:.2f}ms)")
    print(f"Summary written to:    {summary_file}")
    print(f"Manifest written to:   {manifest_file}")
    print("=" * 80)


if __name__ == "__main__":
    main()
