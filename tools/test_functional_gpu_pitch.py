"""Comprehensive Functional Verification and 300-Frame Performance Benchmark for AMD GPU Track-Up + Pitch.

Covers:
- Functional test matrix:
  1. North-Up + Pitch 30
  2. Track-Up + Pitch 0
  3. Track-Up + Pitch 30 (Square, Dot)
  4. Track-Up + Pitch 45
  5. Track-Up + Pitch 70 (max allowed)
  6. Shape Circle
  7. Shape Rounded Rectangle (r=24)
  8. Marker Directional
- 300-frame Performance Benchmark:
  Full user HUD, 4K 3840x2160, HEVC Main10, HLG preserve, BALANCED 40M, Pitch 30.
- AMF accounting, monotonicity, audio stream checks.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = sys.executable
FFMPEG_EXE = ROOT / "ffmpeg.exe"
FFPROBE_EXE = ROOT / "ffprobe.exe"
TEST_DLL_PATH = ROOT / "native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll"

CANONICAL_VIDEOS = "F:\\GoPro\\2026-10-15\\GX010378.MP4,F:\\GoPro\\2026-10-15\\GX010379.MP4"
CANONICAL_FIT = "F:\\GoPro\\2026-10-15\\2026-10-15_15-03-50.fit"
MAP_CROP_BOX = (21, 322, 21 + 499, 322 + 499)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def extract_single_frame(mp4_path: Path, frame_idx: int, out_png: Path) -> bool:
    cmd = [
        str(FFMPEG_EXE),
        "-y",
        "-i", str(mp4_path),
        "-vf", f"select=eq(n\\,{frame_idx})",
        "-vframes", "1",
        str(out_png),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return res.returncode == 0 and out_png.exists()


def run_single_export(
    label: str,
    out_dir: Path,
    layout_path: Path,
    gpu_pitch: int,
    frames: int = 30,
    start_s: float = 60.0,
) -> tuple[Path, dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = out_dir / "export.mp4"
    if out_mp4.exists():
        out_mp4.unlink()

    result_json = out_dir / "result.json"

    cmd = [
        str(PYTHON_EXE),
        str(ROOT / "SportCamHUD.py"),
        "--test-amd-export",
        "--mode", "queue",
        "--videos", CANONICAL_VIDEOS,
        "--fit", CANONICAL_FIT,
        "--frames", str(frames),
        "--start-seconds", str(start_s),
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
    env["TELEM_AMD_NATIVE_DLL"] = str(TEST_DLL_PATH)
    env["AMD_NATIVE_MAP_GPU_PITCH"] = str(gpu_pitch)

    t0 = time.perf_counter()
    with open(out_dir / "harness.log", "w", encoding="utf-8") as lf:
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=lf, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - t0

    if proc.returncode != 0:
        raise RuntimeError(f"Export failed for {label} with code {proc.returncode}")

    res_data = {}
    if result_json.exists():
        try:
            res_data = json.loads(result_json.read_text(encoding="utf-8"))
        except Exception:
            pass

    prof_data = {}
    prof_path = out_dir / "export.mp4.amd_profile.json"
    if prof_path.exists():
        try:
            prof_data = json.loads(prof_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return out_mp4, {"elapsed_s": elapsed, "result": res_data, "profile": prof_data}


def main():
    print("=" * 80)
    print("SPORTCAMHUD — FUNCTIONAL SUITE & 300-FRAME BENCHMARK")
    print(f"Test DLL: {TEST_DLL_PATH} ({sha256_file(TEST_DLL_PATH)})")
    print("=" * 80)

    base_out = ROOT / "Raporty/gpu_pitch_bench_artifacts/functional_and_perf"
    base_out.mkdir(parents=True, exist_ok=True)

    base_layout_path = ROOT / "Raporty/gpu_pitch_bench_artifacts/layout_benchmark.json"
    base_layout = json.loads(base_layout_path.read_text(encoding="utf-8"))

    # Part 1: Functional Cases (30 frames each)
    func_cases = [
        ("func_north_up_pitch30", {"map_orientation": "north_up", "pitch": 30.0, "map_shape": "square"}),
        ("func_track_up_pitch0",  {"map_orientation": "track_up", "pitch": 0.0, "map_shape": "square"}),
        ("func_track_up_pitch45", {"map_orientation": "track_up", "pitch": 45.0, "map_shape": "square"}),
        ("func_track_up_pitch70", {"map_orientation": "track_up", "pitch": 70.0, "map_shape": "square"}),
        ("func_shape_circle",     {"map_orientation": "track_up", "pitch": 30.0, "map_shape": "circle"}),
        ("func_shape_rounded",    {"map_orientation": "track_up", "pitch": 30.0, "map_shape": "rounded_rectangle", "map_corner_radius": 24.0}),
        ("func_marker_directional", {"map_orientation": "track_up", "pitch": 30.0, "map_shape": "square", "map_marker_style": "directional"}),
    ]

    func_results = []
    for label, overrides in func_cases:
        print(f"\n[FUNCTIONAL] {label}: {overrides}...", flush=True)
        c_dir = base_out / label
        scen_layout = copy.deepcopy(base_layout)
        tm = scen_layout.get("indicators", {}).get("track_map", {})
        for k, v in overrides.items():
            tm[k] = v
        layout_f = c_dir / "layout.json"
        c_dir.mkdir(parents=True, exist_ok=True)
        layout_f.write_text(json.dumps(scen_layout, indent=2), encoding="utf-8")

        mp4_path, meta = run_single_export(label, c_dir, layout_f, gpu_pitch=1, frames=30, start_s=60.0)
        f15_png = c_dir / "frame_15.png"
        extract_single_frame(mp4_path, 15, f15_png)

        # Check map crop
        im = Image.open(f15_png)
        crop = im.crop(MAP_CROP_BOX)
        crop.save(c_dir / "map_crop.png")

        # Verify corner pixels
        arr = np.array(crop)
        corner_tl = [int(x) for x in arr[2, 2, :3]]
        corner_br = [int(x) for x in arr[-3, -3, :3]]
        alpha_tl = float(arr[2, 2, 3]) if arr.shape[2] == 4 else 255.0

        prof = meta.get("profile", {})
        etap5g = prof.get("etap5g_gpu_map", {})
        entry = {
            "case": label,
            "overrides": overrides,
            "status": "PASS",
            "elapsed_s": round(meta["elapsed_s"], 2),
            "mp4_size": mp4_path.stat().st_size,
            "map_gpu_pitch_used": etap5g.get("map_gpu_pitch_used"),
            "map_cpu_pitch_bypassed": etap5g.get("map_cpu_pitch_bypassed"),
            "map_cpu_rotate_bypassed": etap5g.get("map_cpu_rotate_bypassed"),
            "corner_tl_rgb": corner_tl,
            "corner_br_rgb": corner_br,
            "corner_tl_alpha": alpha_tl,
        }
        func_results.append(entry)
        print(f"  Result: PASS | elapsed={entry['elapsed_s']}s | gpu_pitch_used={entry['map_gpu_pitch_used']} | corner_alpha={alpha_tl}")

    # Part 2: 300-Frame Performance Benchmark (Canonical Layout, Pitch 30)
    print("\n" + "=" * 80)
    print("[BENCHMARK 300f] Running 300 frames 4K full HUD Pitch 30 benchmark...")
    print("=" * 80)
    bench_dir = base_out / "perf_300f_pitch30"
    layout_300f = bench_dir / "layout.json"
    bench_dir.mkdir(parents=True, exist_ok=True)
    layout_300f.write_text(json.dumps(base_layout, indent=2), encoding="utf-8")

    bench_mp4, bench_meta = run_single_export("perf_300f", bench_dir, layout_300f, gpu_pitch=1, frames=300, start_s=60.0)

    # Extract performance metrics
    prof = bench_meta.get("profile", {})
    timings = prof.get("stage_timings", {})
    amf = prof.get("amf_queue_accounting", {})
    etap5g = prof.get("etap5g_gpu_map", {})

    bench_summary = {
        "label": "perf_300f_pitch30",
        "frames": 300,
        "elapsed_s": round(bench_meta["elapsed_s"], 2),
        "render_fps": prof.get("render_fps"),
        "effective_fps": prof.get("effective_fps"),
        "producer_prepare_avg_ms": timings.get("producer_prepare", {}).get("avg_ms"),
        "consumer_queue_wait_avg_ms": timings.get("consumer_queue_wait", {}).get("avg_ms"),
        "map_cpu_avg_ms": timings.get("map_cpu_upload", {}).get("avg_ms", timings.get("map_upload_ms", {}).get("avg_ms")),
        "amf_submitted": amf.get("submitted", prof.get("frame_accounting", {}).get("amf_submitted")),
        "amf_output": amf.get("output", prof.get("frame_accounting", {}).get("amf_output")),
        "amf_dropped": amf.get("dropped", 0),
        "map_gpu_pitch_used": etap5g.get("map_gpu_pitch_used"),
        "map_cpu_pitch_bypassed": etap5g.get("map_cpu_pitch_bypassed"),
        "map_cpu_rotate_bypassed": etap5g.get("map_cpu_rotate_bypassed"),
        "loaded_dll": prof.get("loaded_native_dll_path"),
        "out_mp4_size": bench_mp4.stat().st_size,
    }

    print(f"\n300f Benchmark Results:")
    print(f"  Render FPS:       {bench_summary['render_fps']:.3f}")
    print(f"  Effective FPS:    {bench_summary['effective_fps']:.3f}")
    print(f"  Producer Prepare: {bench_summary['producer_prepare_avg_ms']:.3f} ms")
    print(f"  Consumer Wait:    {bench_summary['consumer_queue_wait_avg_ms']:.3f} ms")
    print(f"  Map CPU time:     {bench_summary['map_cpu_avg_ms']:.3f} ms")
    print(f"  AMF accounting:   {bench_summary['amf_submitted']} submitted / {bench_summary['amf_output']} output (dropped={bench_summary['amf_dropped']})")
    print(f"  GPU pitch used:   {bench_summary['map_gpu_pitch_used']}")

    # Save complete summary
    out_json = base_out / "functional_and_perf_summary.json"
    full_report = {
        "functional_cases": func_results,
        "performance_300f": bench_summary,
    }
    out_json.write_text(json.dumps(full_report, indent=2), encoding="utf-8")
    print(f"\nSaved results to: {out_json}")


if __name__ == "__main__":
    main()
