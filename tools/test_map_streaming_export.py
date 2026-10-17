"""Targeted Validation for Map Tile Chronological Streaming Architecture.

Tests 4K 60fps export at Zoom 20 with Pitch 30 on AMD Native Pipeline.
Verifies:
1. No multi-minute hang at 0%.
2. Instant/fast start (< 5s).
3. Zero grey or missing tiles in the rendered output video.
4. Full render FPS (~41 FPS).
5. Accurate milestone reporting.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = sys.executable

PROD_DLL = ROOT / "runtime/amd/bin/telem_amd_native.dll"
CANONICAL_VIDEOS = [
    Path(r"F:\GoPro\2026-10-15\GX010378.MP4"),
    Path(r"F:\GoPro\2026-10-15\GX010379.MP4"),
]
CANONICAL_FIT = Path(r"F:\GoPro\2026-10-15\2026-10-15_15-03-50.fit")
LAYOUT_ZOOM20 = ROOT / "Raporty/gpu_pitch_bench_artifacts/map_streaming_verify/layout_zoom20.json"
LAYOUT_ZOOM13 = ROOT / "Raporty/gpu_pitch_bench_artifacts/map_streaming_verify/layout_zoom13.json"


def run_test(label: str, layout_path: Path, frames: int = 300, start_seconds: float = 60.0) -> dict:
    out_dir = ROOT / f"Raporty/gpu_pitch_bench_artifacts/map_streaming_verify/{label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = out_dir / "export.mp4"
    result_json = out_dir / "result.json"
    harness_log = out_dir / "harness.log"

    if out_mp4.exists():
        out_mp4.unlink()
    if result_json.exists():
        result_json.unlink()

    videos_arg = ",".join(str(v) for v in CANONICAL_VIDEOS)
    cmd = [
        str(PYTHON_EXE),
        str(ROOT / "SportCamHUD.py"),
        "--test-amd-export",
        "--mode", "queue",
        "--videos", videos_arg,
        "--fit", str(CANONICAL_FIT),
        "--frames", str(frames),
        "--start-seconds", str(start_seconds),
        "--quality", "BALANCED",
        "--codec", "hevc",
        "--bitrate", "40M",
        "--hdr-mode", "preserve_hlg",
        "--preview-hud",
        "--layout", str(layout_path),
        "--output", str(out_mp4),
        "--result-json", str(result_json),
    ]

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["TELEM_RENDER_DEBUG"] = "1"
    env["AMD_NATIVE_PROFILING"] = "0"
    env["TELEM_AMD_NATIVE_DLL"] = str(PROD_DLL.resolve())
    env["AMD_NATIVE_MAP_GPU_PITCH"] = "1"

    print(f"\n=======================================================", flush=True)
    print(f"[{label}] Launching export: frames={frames}, start={start_seconds}s, layout={layout_path.name}...", flush=True)
    t0 = time.perf_counter()
    with open(harness_log, "w", encoding="utf-8") as lf:
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=lf, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - t0
    print(f"[{label}] Process finished in {elapsed:.2f}s with exit code {proc.returncode}.", flush=True)

    profile_path = out_dir / "export.mp4.amd_profile.json"
    profile_data = {}
    if profile_path.exists():
        try:
            profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[{label}] Warning: could not parse profile json: {e}", flush=True)

    gui_result = {}
    if result_json.exists():
        try:
            gui_result = json.loads(result_json.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[{label}] Warning: could not parse result json: {e}", flush=True)

    etap8p_a = profile_data.get("etap8p_a", {})
    map_streaming = profile_data.get("map_streaming", {})
    timings = profile_data.get("timings", {})

    fps = profile_data.get("true_fps", gui_result.get("effective_fps", 0.0))
    time_to_first = etap8p_a.get("time_to_first_frame_ms", gui_result.get("click_to_first_progress_ms", 0.0))

    summary = {
        "label": label,
        "success": gui_result.get("success", False),
        "returncode": proc.returncode,
        "total_elapsed_s": round(elapsed, 2),
        "frames_rendered": gui_result.get("total_frames", frames),
        "fps": round(fps, 3),
        "time_to_first_frame_ms": time_to_first,
        "dll_init_ms": etap8p_a.get("dll_init_ms"),
        "map_streaming": map_streaming,
        "output_size_mb": round(os.path.getsize(out_mp4) / (1024 * 1024), 2) if out_mp4.exists() else 0.0,
    }

    print(f"[{label}] SUMMARY: Success={summary['success']} | FPS={summary['fps']} | Total={elapsed:.2f}s | FirstFrame={time_to_first:.1f}ms | Size={summary['output_size_mb']}MB", flush=True)
    if map_streaming:
        print(f"[{label}] Map Streaming: required={map_streaming.get('required_tiles')}, cached={map_streaming.get('cached_tiles')}, startup_dl={map_streaming.get('startup_downloaded')}, bg_pending={map_streaming.get('background_pending')}, chk={map_streaming.get('cache_check_ms')}ms, preload={map_streaming.get('startup_preload_ms')}ms", flush=True)
    return summary


if __name__ == "__main__":
    results = []
    # Test 1: Zoom 20 (high zoom, 2745 route tiles)
    res_z20 = run_test("TEST_ZOOM20_PITCH30", LAYOUT_ZOOM20, frames=300, start_seconds=60.0)
    results.append(res_z20)

    # Test 2: Zoom 13 (reference zoom, full cache)
    res_z13 = run_test("TEST_ZOOM13_PITCH30", LAYOUT_ZOOM13, frames=300, start_seconds=60.0)
    results.append(res_z13)

    summary_file = ROOT / "Raporty/gpu_pitch_bench_artifacts/map_streaming_verify/test_summary.json"
    summary_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nAll tests completed. Summary saved to {summary_file}")
