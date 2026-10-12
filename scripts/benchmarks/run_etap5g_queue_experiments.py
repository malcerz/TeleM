"""Queue Mode Experiments for SPORTCAMHUD - ETAP 5G (Section 3).

Tests 300 frames across:
A. Default ASYNC (q_depth=2)
B. SYNC (pipeline_mode=SYNC)
C. ASYNC (q_depth=1)
D. ASYNC (q_depth=2) [repeat for consistency]
E. ASYNC (q_depth=3)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path("C:/_DEV/BikeRideHUD-main-new").resolve()
VIDEO_PATH = Path("D:/Comparator/GX010344.MP4").resolve()
FIT_PATH = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4B_RESULTS_20261012/fit/24609739177.fit").resolve()
LAYOUT_PATH = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4E_RESULTS_20261012/matrix/layouts/A_all_with_effects.json").resolve()
OUTPUT_DIR = Path("C:/_DEV/_SPORTCAMHUD_ETAP_5G_RESULTS_20261012/queue_matrix").resolve()
PYTHON_EXE = Path(r"C:\Users\Malcerz\AppData\Local\Python\pythoncore-3.14-64\python.exe").resolve()

FRAMES = 300
START_SECONDS = 120.0
QUALITY = "FAST"
CODEC = "hevc"
BITRATE = "45M"

VARIANTS = [
    ("var_A_async_q2", "ASYNC", "2"),
    ("var_B_sync_q0",  "SYNC",  "0"),
    ("var_C_async_q1", "ASYNC", "1"),
    ("var_D_async_q2", "ASYNC", "2"),
    ("var_E_async_q3", "ASYNC", "3"),
]

def run_variant(tag: str, pipeline_mode: str, q_depth: str):
    iso_dir = OUTPUT_DIR / tag / "isolation"
    iso_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = OUTPUT_DIR / tag / f"{tag}.mp4"
    res_json = OUTPUT_DIR / tag / f"{tag}_result.json"
    prof_json = OUTPUT_DIR / tag / f"{tag}.mp4.amd_profile.json"
    log_file = OUTPUT_DIR / tag / f"{tag}.log"

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["AMD_OVERLAY_PROFILE"] = "1"
    env["AMD_PRODUCTION_ACCOUNTING"] = "1"
    env["APPDATA"] = str(iso_dir / "appdata")
    env["TELEM_CACHE_ROOT"] = str(iso_dir / "telemetry_cache")
    env["AMD_DIRECT_ROW_TABLE"] = "0" # strictly safe production mode
    env["AMD_CPU_GPU_PIPELINE"] = pipeline_mode
    env["AMD_QUEUE_DEPTH"] = q_depth

    cli_cmd = [
        str(PYTHON_EXE), str(REPO_ROOT / "SportCamHUD.py"), "--test-amd-export", "--mode", "direct",
        "--video", str(VIDEO_PATH), "--fit", str(FIT_PATH), "--frames", str(FRAMES),
        "--quality", QUALITY, "--codec", CODEC, "--bitrate", BITRATE,
        "--start-seconds", str(START_SECONDS), "--output", str(out_mp4),
        "--result-json", str(res_json), "--layout", str(LAYOUT_PATH),
    ]

    print(f"\n--- Running Variant: {tag} (Pipeline: {pipeline_mode}, Q-Depth: {q_depth}) ---")
    t0 = time.perf_counter()
    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cli_cmd, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        rc = proc.wait(timeout=600)
    wall_s = time.perf_counter() - t0

    if rc != 0 or not res_json.is_file():
        print(f"FAILED: rc={rc}, check {log_file}")
        return None

    res_data = json.loads(res_json.read_text(encoding="utf-8"))
    prof_data = json.loads(prof_json.read_text(encoding="utf-8")) if prof_json.is_file() else {}
    timings = prof_data.get("timings", {})

    eff_fps = FRAMES / wall_s
    true_fps = prof_data.get("true_fps", eff_fps)
    render_fps = res_data.get("stats", {}).get("render_fps", true_fps)

    def _t(k):
        v = timings.get(k)
        if isinstance(v, dict):
            return v.get("avg_ms", 0.0)
        return float(v) if v is not None else 0.0

    stats = {
        "tag": tag,
        "pipeline_mode": pipeline_mode,
        "q_depth": q_depth,
        "wall_s": wall_s,
        "eff_fps": eff_fps,
        "true_fps": true_fps,
        "render_fps": render_fps,
        "producer_prepare": _t("producer_prepare"),
        "consumer_queue_wait": _t("consumer_queue_wait"),
        "producer_queue_wait": _t("producer_queue_wait"),
        "compose_overlay": _t("compose_overlay"),
        "buffer_prep": _t("PIL/buffer preparation"),
        "speed_text": _t("widget.speed_text.total"),
        "fit_distance": _t("widget.fit_distance_text.total"),
        "fit_power": _t("widget.fit_curVpower_text.total"),
    }
    return stats

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_results = []
    for tag, pmode, qd in VARIANTS:
        res = run_variant(tag, pmode, qd)
        if res:
            all_results.append(res)

    print("\n" + "=" * 110)
    print("ETAP 5G — WYNIKI EKSPERYMENTÓW Z KOLEJKAMI (300 KLATEK 4K)")
    print("=" * 110)
    header = f"{'Wariant':<16} | {'Tryb':<6} | {'Q':<2} | {'Wall (s)':<8} | {'Eff FPS':<8} | {'Rnd FPS':<8} | {'Prod Prep':<9} | {'Q Wait':<8} | {'Compose':<8} | {'BufPrep':<8}"
    print(header)
    print("-" * 110)
    for r in all_results:
        print(f"{r['tag']:<16} | {r['pipeline_mode']:<6} | {r['q_depth']:<2} | {r['wall_s']:6.2f} s | {r['eff_fps']:7.2f} | {r['render_fps']:7.2f} | {r['producer_prepare']:7.2f} ms | {r['consumer_queue_wait']:6.2f} ms | {r['compose_overlay']:6.2f} ms | {r['buffer_prep']:6.2f} ms")
    print("=" * 110)

    summary_file = OUTPUT_DIR / "queue_experiments_summary.json"
    summary_file.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"Zapisano podsumowanie do: {summary_file}")

if __name__ == "__main__":
    main()
