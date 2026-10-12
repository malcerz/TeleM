"""Runner for SPORTCAMHUD - ETAP 5A Canonical 3x 3000-frame Benchmark Suite.

Executes 3 consecutive canonical export runs for A_all_with_effects:
  - 3000 frames
  - GX010344.MP4 starting from 120.0 seconds
  - AMF HEVC, QP 28 FAST, 45M bitrate
  - Full HUD layout with all 17 widgets and effects enabled
Extracts:
  - Effective FPS & Render FPS
  - Compose Overlay ms, Producer Prepare ms, Consumer Queue Wait ms
  - speed_text.total ms, fit_distance_text.total ms, fit_curVpower_text.total ms
  - ffprobe container/stream integrity check
"""
from __future__ import annotations

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
OUTPUT_DIR = Path("C:/_DEV/_SPORTCAMHUD_ETAP_5A_RESULTS_20261012/canonical_3000").resolve()
PYTHON_EXE = Path(r"C:\Users\Malcerz\AppData\Local\Python\pythoncore-3.14-64\python.exe").resolve()
ISOLATION_DIR = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4E_RESULTS_20261012/matrix/isolation").resolve()

FRAMES = 3000
START_SECONDS = 120.0
QUALITY = "FAST"
CODEC = "hevc"
BITRATE = "45M"

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

    # Extract metrics
    elapsed_s = result_data.get("elapsed_s", wall_s)
    effective_fps = FRAMES / elapsed_s if elapsed_s > 0 else 0.0
    true_fps = prof_data.get("true_fps", effective_fps)
    # Native render FPS reported in direct stage timings or result
    stage_timings = prof_data.get("timings", {})
    render_fps = result_data.get("stats", {}).get("render_fps", true_fps)

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

    # Probe video with ffprobe
    probe_v = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,width,height,r_frame_rate,duration,bit_rate", "-of", "json", str(out_mp4)],
        capture_output=True, text=True, check=False,
    )
    probe_a = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name,sample_rate,channels,duration", "-of", "json", str(out_mp4)],
        capture_output=True, text=True, check=False,
    )

    v_info = json.loads(probe_v.stdout).get("streams", [{}])[0] if probe_v.stdout else {}
    a_info = json.loads(probe_a.stdout).get("streams", [{}])[0] if probe_a.stdout else {}

    summary = {
        "run_idx": run_idx,
        "frames": FRAMES,
        "wall_time_s": wall_s,
        "elapsed_s": elapsed_s,
        "effective_fps": effective_fps,
        "render_fps": render_fps,
        "true_fps": true_fps,
        "compose_overlay_avg_ms": get_avg("compose_overlay"),
        "compose_overlay_p95_ms": get_p95("compose_overlay"),
        "producer_prepare_avg_ms": get_avg("producer_prepare"),
        "producer_prepare_p95_ms": get_p95("producer_prepare"),
        "consumer_queue_wait_avg_ms": get_avg("consumer_queue_wait"),
        "consumer_queue_wait_p95_ms": get_p95("consumer_queue_wait"),
        "speed_text_avg_ms": get_avg("widget.speed_text.total"),
        "speed_text_p95_ms": get_p95("widget.speed_text.total"),
        "fit_distance_text_avg_ms": get_avg("widget.fit_distance_text.total"),
        "fit_distance_text_p95_ms": get_p95("widget.fit_distance_text.total"),
        "fit_curVpower_text_avg_ms": get_avg("widget.fit_curVpower_text.total"),
        "fit_curVpower_text_p95_ms": get_p95("widget.fit_curVpower_text.total"),
        "output_size_bytes": out_mp4.stat().st_size if out_mp4.is_file() else 0,
        "ffprobe_video": v_info,
        "ffprobe_audio": a_info,
    }

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Run {run_idx} finished: Effective FPS={effective_fps:.2f}, Render FPS={render_fps:.2f}, Compose={summary['compose_overlay_avg_ms']:.2f} ms", flush=True)
    return summary

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for i in (1, 2, 3):
        res = run_single(i)
        runs.append(res)

    # Average metrics
    avg_effective_fps = sum(r["effective_fps"] for r in runs) / 3.0
    avg_render_fps = sum(r["render_fps"] for r in runs) / 3.0
    avg_compose = sum(r["compose_overlay_avg_ms"] for r in runs) / 3.0
    avg_producer = sum(r["producer_prepare_avg_ms"] for r in runs) / 3.0
    avg_queue = sum(r["consumer_queue_wait_avg_ms"] for r in runs) / 3.0
    avg_speed = sum(r["speed_text_avg_ms"] for r in runs) / 3.0
    avg_dist = sum(r["fit_distance_text_avg_ms"] for r in runs) / 3.0
    avg_power = sum(r["fit_curVpower_text_avg_ms"] for r in runs) / 3.0

    final_report = {
        "benchmark": "SPORTCAMHUD_ETAP_5A_CANONICAL_3000",
        "variant": "A_all_with_effects",
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
        "averages": {
            "effective_fps": avg_effective_fps,
            "render_fps": avg_render_fps,
            "compose_overlay_ms": avg_compose,
            "producer_prepare_ms": avg_producer,
            "consumer_queue_wait_ms": avg_queue,
            "speed_text_ms": avg_speed,
            "fit_distance_text_ms": avg_dist,
            "fit_curVpower_text_ms": avg_power,
            "three_bottlenecks_total_ms": avg_speed + avg_dist + avg_power,
        }
    }

    report_file = OUTPUT_DIR / "etap5a_canonical_summary.json"
    report_file.write_text(json.dumps(final_report, indent=2), encoding="utf-8")
    print(f"\n[DONE] Summary written to {report_file}")
    print(f"Average Effective FPS: {avg_effective_fps:.2f}")
    print(f"Average Render FPS:    {avg_render_fps:.2f}")
    print(f"Average Compose Overlay: {avg_compose:.2f} ms")
    print(f"3 Bottlenecks Total:    {avg_speed + avg_dist + avg_power:.2f} ms")

if __name__ == "__main__":
    main()
