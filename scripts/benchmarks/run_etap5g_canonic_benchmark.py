"""Canonical 4K Benchmark Runner for SPORTCAMHUD - ETAP 5G.

Executes canonical 3000-frame 4K production runs under strictly safe mode:
- Resolution: 3840x2160 @ 29.970 fps
- Bitrate: 45M, Quality: FAST, Codec: hevc
- Single Live Mux (HEVC + AAC)
- Safe production memory architecture (AMD_DIRECT_ROW_TABLE=0, public Pillow API)
- AMD_QUEUE_DEPTH=3, AMD_CPU_GPU_PIPELINE=ASYNC
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
OUTPUT_DIR = Path("C:/_DEV/_SPORTCAMHUD_ETAP_5G_RESULTS_20261012/canonic_4k_safe_production").resolve()
PYTHON_EXE = Path(r"C:\Users\Malcerz\AppData\Local\Python\pythoncore-3.14-64\python.exe").resolve()

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


def probe_video(path: Path) -> dict:
    ffprobe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path)
    ]
    p = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def run_canonical(run_id: int) -> dict:
    iso_dir = OUTPUT_DIR / f"run{run_id}" / "isolation"
    iso_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = OUTPUT_DIR / f"run{run_id}" / f"etap5g_canonic_run{run_id}.mp4"
    res_json = OUTPUT_DIR / f"run{run_id}" / f"etap5g_canonic_run{run_id}_result.json"
    prof_json = OUTPUT_DIR / f"run{run_id}" / f"etap5g_canonic_run{run_id}.mp4.amd_profile.json"
    log_file = OUTPUT_DIR / f"run{run_id}" / f"etap5g_canonic_run{run_id}.log"

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["AMD_OVERLAY_PROFILE"] = "1"
    env["AMD_PRODUCTION_ACCOUNTING"] = "1"
    env["APPDATA"] = str(iso_dir / "appdata")
    env["TELEM_CACHE_ROOT"] = str(iso_dir / "telemetry_cache")
    env["AMD_DIRECT_ROW_TABLE"] = "0"
    env["AMD_CPU_GPU_PIPELINE"] = "ASYNC"
    env["AMD_QUEUE_DEPTH"] = "3"

    cli_cmd = [
        str(PYTHON_EXE), str(REPO_ROOT / "SportCamHUD.py"), "--test-amd-export", "--mode", "direct",
        "--video", str(VIDEO_PATH), "--fit", str(FIT_PATH), "--frames", str(FRAMES),
        "--quality", QUALITY, "--codec", CODEC, "--bitrate", BITRATE,
        "--start-seconds", str(START_SECONDS), "--output", str(out_mp4),
        "--result-json", str(res_json), "--layout", str(LAYOUT_PATH),
    ]

    print(f"\n========================================================")
    print(f"RUNNING CANONICAL 4K BENCHMARK — RUN {run_id} (3000 FRAMES)")
    print(f"Output: {out_mp4}")
    print(f"Pipeline: ASYNC, Queue Depth: 3, Safe Memory: AMD_DIRECT_ROW_TABLE=0")
    print(f"========================================================")

    t0 = time.perf_counter()
    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cli_cmd, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        rc = proc.wait(timeout=1800)
    wall_s = time.perf_counter() - t0

    if rc != 0 or not res_json.is_file():
        raise RuntimeError(f"Run {run_id} FAILED with returncode {rc}; check {log_file}")

    res_data = json.loads(res_json.read_text(encoding="utf-8"))
    prof_data = json.loads(prof_json.read_text(encoding="utf-8")) if prof_json.is_file() else {}
    timings = prof_data.get("timings", {})

    eff_fps = FRAMES / wall_s
    true_fps = prof_data.get("true_fps", eff_fps)
    render_fps = res_data.get("stats", {}).get("render_fps", true_fps)
    sha256 = compute_sha256(out_mp4)
    probe_info = probe_video(out_mp4)

    def _t(k):
        v = timings.get(k)
        if isinstance(v, dict):
            return v.get("avg_ms", 0.0)
        return float(v) if v is not None else 0.0

    summary = {
        "run_id": run_id,
        "wall_s": wall_s,
        "effective_fps": eff_fps,
        "render_fps": render_fps,
        "true_fps": true_fps,
        "out_mp4": str(out_mp4),
        "size_bytes": out_mp4.stat().st_size,
        "sha256": sha256,
        "producer_prepare": _t("producer_prepare"),
        "consumer_queue_wait": _t("consumer_queue_wait"),
        "producer_queue_wait": _t("producer_queue_wait"),
        "compose_overlay": _t("compose_overlay"),
        "buffer_prep": _t("PIL/buffer preparation"),
        "speed_text": _t("widget.speed_text.total"),
        "fit_distance": _t("widget.fit_distance_text.total"),
        "fit_power": _t("widget.fit_curVpower_text.total"),
        "probe": probe_info,
    }
    print(f"Run {run_id} Complete:")
    print(f"  Wall Time    : {wall_s:.2f} s")
    print(f"  Effective FPS: {eff_fps:.2f} FPS")
    print(f"  Render FPS   : {render_fps:.2f} FPS")
    print(f"  Compose      : {summary['compose_overlay']:.2f} ms")
    print(f"  Prod Prepare : {summary['producer_prepare']:.2f} ms")
    print(f"  Queue Wait   : {summary['consumer_queue_wait']:.2f} ms")
    print(f"  SHA-256      : {sha256}")
    return summary


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    num_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    all_runs = []
    for r in range(1, num_runs + 1):
        summary = run_canonical(r)
        all_runs.append(summary)

    summary_file = OUTPUT_DIR / "etap5g_canonic_3runs_summary.json"
    summary_file.write_text(json.dumps(all_runs, indent=2), encoding="utf-8")
    print(f"\nAll {num_runs} runs completed successfully. Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
