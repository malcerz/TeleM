"""Production 4K Benchmark Runner for SPORTCAMHUD - ETAP 5F.

Verifies:
  - Input: D:/Comparator/GX010344.MP4 (from 120.0s, 3000 frames)
  - FIT: C:/_DEV/_SPORTCAMHUD_ETAP_4B_RESULTS_20261012/fit/24609739177.fit
  - Layout: C:/_DEV/_SPORTCAMHUD_ETAP_4E_RESULTS_20261012/matrix/layouts/A_all_with_effects.json
  - Resolution: 3840x2160 (confirmed by ffprobe)
  - Codec: AMF HEVC FAST QP 28, bitrate 45M
  - Safe production buffer mode (AMD_DIRECT_ROW_TABLE=0)
  - Single Live Mux (video + audio in single pass)
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
OUTPUT_DIR = Path("C:/_DEV/_SPORTCAMHUD_ETAP_5F_RESULTS_20261012/canonical_4k").resolve()
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


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ISOLATION_DIR.mkdir(parents=True, exist_ok=True)

    out_mp4 = OUTPUT_DIR / "etap5f_production_4k.mp4"
    res_json = OUTPUT_DIR / "etap5f_production_4k_result.json"
    prof_json = OUTPUT_DIR / "etap5f_production_4k.mp4.amd_profile.json"
    log_file = OUTPUT_DIR / "etap5f_production_4k.log"

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
    # Explicitly test safe production mode (standard public Pillow API)
    env["AMD_DIRECT_ROW_TABLE"] = "0"

    cli_cmd = [
        str(PYTHON_EXE), str(REPO_ROOT / "SportCamHUD.py"), "--test-amd-export", "--mode", "direct",
        "--video", str(VIDEO_PATH), "--fit", str(FIT_PATH), "--frames", str(FRAMES),
        "--quality", QUALITY, "--codec", CODEC, "--bitrate", BITRATE,
        "--start-seconds", str(START_SECONDS), "--output", str(out_mp4),
        "--result-json", str(res_json), "--layout", str(LAYOUT_PATH),
    ]

    print("=" * 80)
    print("SPORTCAMHUD — ETAP 5F: PRODUCTION 4K EXPORT TEST")
    print(f"CLI Command: {' '.join(cli_cmd)}")
    print(f"Output File: {out_mp4}")
    print(f"Bitrate: {BITRATE}, Quality: {QUALITY}, Codec: {CODEC}")
    print(f"Buffer Mode: Safe Production Default (AMD_DIRECT_ROW_TABLE=0)")
    print("=" * 80)

    t0 = time.perf_counter()
    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cli_cmd, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        rc = proc.wait(timeout=1800)
    wall_s = time.perf_counter() - t0

    if rc != 0 or not res_json.is_file():
        raise RuntimeError(f"Export failed with return code {rc}; check {log_file}")

    result_data = json.loads(res_json.read_text(encoding="utf-8"))
    prof_data = json.loads(prof_json.read_text(encoding="utf-8")) if prof_json.is_file() else {}

    elapsed_s = result_data.get("elapsed_s", wall_s)
    effective_fps = FRAMES / elapsed_s if elapsed_s > 0 else 0.0
    true_fps = prof_data.get("true_fps", effective_fps)
    render_fps = result_data.get("stats", {}).get("render_fps", true_fps)
    stage_timings = prof_data.get("timings", {})

    # Execute direct ffprobe inspection
    ffprobe_cmd = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(out_mp4)
    ]
    ffprobe_res = subprocess.run(ffprobe_cmd, capture_output=True, text=True)
    probe_info = json.loads(ffprobe_res.stdout) if ffprobe_res.returncode == 0 else {}

    v_stream = next((s for s in probe_info.get("streams", []) if s.get("codec_type") == "video"), {})
    a_stream = next((s for s in probe_info.get("streams", []) if s.get("codec_type") == "audio"), {})

    width = v_stream.get("width")
    height = v_stream.get("height")
    codec = v_stream.get("codec_name")
    pix_fmt = v_stream.get("pix_fmt")
    r_fps = v_stream.get("r_frame_rate")
    nb_frames = v_stream.get("nb_frames")

    sha256 = compute_sha256(out_mp4)
    file_size_bytes = out_mp4.stat().st_size

    print("\n" + "=" * 80)
    print("EXPORT COMPLETED — DIRECT VERIFICATION")
    print(f"Output File:       {out_mp4}")
    print(f"Size:              {file_size_bytes} bytes ({file_size_bytes / (1024*1024):.2f} MB)")
    print(f"SHA-256:           {sha256}")
    print(f"Video Stream:      {codec} {width}x{height} @ {r_fps} ({pix_fmt}), nb_frames={nb_frames}")
    print(f"Audio Stream:      {a_stream.get('codec_name')} @ {a_stream.get('sample_rate')} Hz, {a_stream.get('channels')} channels")
    print(f"Effective FPS:     {effective_fps:.2f}")
    print(f"Render FPS:        {render_fps:.2f}")
    print(f"Wall Clock Time:   {wall_s:.2f} s (Elapsed: {elapsed_s:.2f} s)")
    print("=" * 80)

    # 4K RESOLUTION GATE CHECK
    if width != 3840 or height != 2160:
        raise AssertionError(f"4K GATE FAILED: Expected 3840x2160, got {width}x{height}!")

    def get_avg(k: str) -> float:
        v = stage_timings.get(k)
        if isinstance(v, dict):
            return float(v.get("avg_ms", 0.0))
        return 0.0

    summary = {
        "benchmark": "SPORTCAMHUD_ETAP_5F_PRODUCTION_4K",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_video": str(VIDEO_PATH),
        "fit_file": str(FIT_PATH),
        "layout_file": str(LAYOUT_PATH),
        "cli_command": cli_cmd,
        "runtime_config": {
            "resolution": f"{width}x{height}",
            "frames": FRAMES,
            "start_seconds": START_SECONDS,
            "quality": QUALITY,
            "codec": CODEC,
            "bitrate": BITRATE,
            "direct_row_table_enabled": False,
        },
        "artifact": {
            "path": str(out_mp4),
            "size_bytes": file_size_bytes,
            "sha256": sha256,
            "effective_fps": effective_fps,
            "render_fps": render_fps,
            "wall_s": wall_s,
            "elapsed_s": elapsed_s,
        },
        "ffprobe": probe_info,
        "stages": {
            "producer_prepare_ms": get_avg("producer_prepare"),
            "compose_overlay_ms": get_avg("compose_overlay"),
            "buffer_preparation_ms": get_avg("PIL/buffer preparation"),
            "consumer_queue_wait_ms": get_avg("consumer_queue_wait"),
            "speed_text_ms": get_avg("widget.speed_text.total"),
            "fit_distance_text_ms": get_avg("widget.fit_distance_text.total"),
            "fit_curVpower_text_ms": get_avg("widget.fit_curVpower_text.total"),
        },
    }

    summary_file = OUTPUT_DIR / "etap5f_4k_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
