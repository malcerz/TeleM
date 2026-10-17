"""Comprehensive Production Benchmark & Validation for AMD D3D11 Native GPU Track-Up + Pitch.

Executes A/B benchmarking series:
- A1: CPU Reference (test DLL, AMD_NATIVE_MAP_GPU_PITCH=0)
- B1: GPU Track-Up + Pitch (test DLL, AMD_NATIVE_MAP_GPU_PITCH=1)
- B2: GPU Track-Up + Pitch (test DLL, AMD_NATIVE_MAP_GPU_PITCH=1)
- A2: CPU Reference (test DLL, AMD_NATIVE_MAP_GPU_PITCH=0)
- A0_prod: Prod DLL fallback check (prod DLL, AMD_NATIVE_MAP_GPU_PITCH=1)
- BOUNDARY: MultiFile clip boundary at t=140s (test DLL, AMD_NATIVE_MAP_GPU_PITCH=1)
- TONEMAP_SDR: HLG->SDR tone mapping at t=60s (test DLL, AMD_NATIVE_MAP_GPU_PITCH=1)
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = sys.executable
FFMPEG_EXE = ROOT / "ffmpeg.exe"
FFPROBE_EXE = ROOT / "ffprobe.exe"

PROD_DLL = ROOT / "runtime/amd/bin/telem_amd_native.dll"
TEST_DLL = ROOT / "native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll"

EXPECTED_PROD_SHA = "e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89"
EXPECTED_TEST_SHA = "6ace4d05b75fbf58cf6477b4c1571f4ce5e972a2377f0d85bae84e839ca9d4b7"

CANONICAL_VIDEOS = [
    Path(r"F:\GoPro\2026-10-15\GX010378.MP4"),
    Path(r"F:\GoPro\2026-10-15\GX010379.MP4"),
]
CANONICAL_FIT = Path(r"F:\GoPro\2026-10-15\2026-10-15_15-03-50.fit")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def verify_dll_metadata(p: Path) -> dict[str, Any]:
    if not p.exists():
        raise FileNotFoundError(f"DLL not found: {p}")
    h = sha256_file(p)
    dll = ctypes.CDLL(str(p))
    abi = dll.telem_amd_get_abi_version() if hasattr(dll, "telem_amd_get_abi_version") else None
    
    build_info = ""
    if hasattr(dll, "telem_amd_get_build_info"):
        dll.telem_amd_get_build_info.restype = ctypes.c_char_p
        build_info = dll.telem_amd_get_build_info().decode("utf-8", errors="replace")
    
    has_pitch_sym = hasattr(dll, "telem_amd_set_map_pitch")
    has_pitch_fn = hasattr(dll, "telem_amd_has_map_pitch")
    pitch_val = dll.telem_amd_has_map_pitch() if has_pitch_fn else 0
    
    return {
        "path": str(p),
        "sha256": h,
        "abi": abi,
        "build_info": build_info,
        "has_telem_amd_set_map_pitch": has_pitch_sym,
        "has_telem_amd_get_map_pitch_enabled": hasattr(dll, "telem_amd_get_map_pitch_enabled"),
        "has_telem_amd_has_map_pitch": has_pitch_fn,
        "telem_amd_has_map_pitch_result": pitch_val,
    }


def run_export_harness(
    label: str,
    out_dir: Path,
    dll_path: Path,
    gpu_pitch_env: int,
    layout_path: Path,
    videos: list[Path],
    fit: Path,
    frames: int = 300,
    start_seconds: float = 60.0,
    hdr_mode: str = "preserve_hlg",
    quality: str = "BALANCED",
    bitrate: str = "40M",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = out_dir / "export.mp4"
    result_json = out_dir / "result.json"
    harness_log = out_dir / "harness.log"
    command_json = out_dir / "command.json"

    if out_mp4.exists():
        out_mp4.unlink()
    if result_json.exists():
        result_json.unlink()

    videos_arg = ",".join(str(v) for v in videos)
    cmd = [
        str(PYTHON_EXE),
        str(ROOT / "SportCamHUD.py"),
        "--test-amd-export",
        "--mode", "queue",
        "--videos", videos_arg,
        "--fit", str(fit),
        "--frames", str(frames),
        "--start-seconds", str(start_seconds),
        "--quality", quality,
        "--codec", "hevc",
        "--bitrate", bitrate,
        "--hdr-mode", hdr_mode,
        "--preview-hud",
        "--layout", str(layout_path),
        "--output", str(out_mp4),
        "--result-json", str(result_json),
    ]

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["TELEM_RENDER_DEBUG"] = "1"
    env["AMD_NATIVE_PROFILING"] = "0"
    env["TELEM_AMD_NATIVE_DLL"] = str(dll_path.resolve())
    env["AMD_NATIVE_MAP_GPU_PITCH"] = str(gpu_pitch_env)

    command_record = {
        "label": label,
        "command": cmd,
        "env": {
            "QT_QPA_PLATFORM": env["QT_QPA_PLATFORM"],
            "TELEM_RENDER_DEBUG": env["TELEM_RENDER_DEBUG"],
            "AMD_NATIVE_PROFILING": env["AMD_NATIVE_PROFILING"],
            "TELEM_AMD_NATIVE_DLL": env["TELEM_AMD_NATIVE_DLL"],
            "AMD_NATIVE_MAP_GPU_PITCH": env["AMD_NATIVE_MAP_GPU_PITCH"],
        },
    }
    command_json.write_text(json.dumps(command_record, indent=2), encoding="utf-8")

    print(f"\n[{label}] Starting harness: DLL={dll_path.name}, GPU_PITCH={gpu_pitch_env}, frames={frames}, start={start_seconds}s, hdr={hdr_mode}...", flush=True)
    t0 = time.perf_counter()
    with open(harness_log, "w", encoding="utf-8") as lf:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
        )
    elapsed = time.perf_counter() - t0
    print(f"[{label}] Finished in {elapsed:.2f}s with exit code {proc.returncode}.", flush=True)

    if proc.returncode != 0:
        print(f"[{label}] ERROR: process exited with code {proc.returncode}. Log: {harness_log}", flush=True)
        return {"label": label, "success": False, "returncode": proc.returncode, "elapsed": elapsed}

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

    # Extract key metrics
    etap8p_a = profile_data.get("etap8p_a", {})
    render_fps = etap8p_a.get("render_fps")
    effective_fps = etap8p_a.get("effective_fps")
    if render_fps is None:
        render_fps = profile_data.get("true_fps", 0.0)
    if effective_fps is None:
        effective_fps = gui_result.get("effective_fps", 0.0)

    timings = profile_data.get("timings", {})
    etap5g = profile_data.get("etap5g", {})
    amf = profile_data.get("amf", {})

    loaded_dll = profile_data.get("dll", {}).get("path", "")
    loaded_build_id = profile_data.get("dll", {}).get("build_id", "")

    summary = {
        "label": label,
        "success": True,
        "returncode": proc.returncode,
        "elapsed_wall_s": elapsed,
        "render_fps": render_fps,
        "effective_fps": effective_fps,
        "producer_prepare_ms": timings.get("producer_prepare", {}).get("avg_ms"),
        "consumer_queue_wait_ms": timings.get("consumer_queue_wait", {}).get("avg_ms"),
        "pipeline_total_ms": timings.get("pipeline_total", {}).get("avg_ms"),
        "map_cpu_ms": timings.get("map_cpu_upload", {}).get("avg_ms", timings.get("map_upload_ms", {}).get("avg_ms")),
        "above_compose_ms": timings.get("above_compose", {}).get("avg_ms"),
        "map_gpu_frames": etap5g.get("map_gpu_frames", 0),
        "map_upload_bytes_total": etap5g.get("map_upload_bytes_total", 0),
        "map_upload_mib_per_frame": etap5g.get("map_upload_mib_per_frame", 0.0),
        "map_gpu_pitch_requested": etap5g.get("map_gpu_pitch_requested"),
        "map_gpu_pitch_used": etap5g.get("map_gpu_pitch_used"),
        "map_gpu_pitch_degrees": etap5g.get("map_gpu_pitch_degrees"),
        "map_cpu_rotate_bypassed": etap5g.get("map_cpu_rotate_bypassed"),
        "map_cpu_pitch_bypassed": etap5g.get("map_cpu_pitch_bypassed"),
        "loaded_dll": loaded_dll,
        "loaded_build_id": loaded_build_id,
        "amf_submitted": amf.get("submitted", profile_data.get("frame_accounting", {}).get("amf_submitted")),
        "amf_output": amf.get("output", profile_data.get("frame_accounting", {}).get("amf_output")),
        "amf_dropped": amf.get("dropped", 0),
        "out_mp4_size": out_mp4.stat().st_size if out_mp4.exists() else 0,
    }

    print(f"[{label}] Render FPS: {summary['render_fps']:.3f} | Effective FPS: {summary['effective_fps']:.3f} | Producer: {summary['producer_prepare_ms']} ms | Map: {summary['map_cpu_ms']} ms | Consumer wait: {summary['consumer_queue_wait_ms']} ms", flush=True)
    return summary


def probe_audio_stream(mp4_path: Path) -> dict[str, Any]:
    cmd = [
        str(FFPROBE_EXE),
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,profile,sample_rate,channels,duration,nb_frames",
        "-show_entries", "packet=pts,dts,duration,size",
        "-of", "json",
        str(mp4_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        return {"error": res.stderr}
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    packets = data.get("packets", [])
    stream_info = streams[0] if streams else {}
    return {
        "codec_name": stream_info.get("codec_name"),
        "profile": stream_info.get("profile"),
        "sample_rate": stream_info.get("sample_rate"),
        "channels": stream_info.get("channels"),
        "duration": stream_info.get("duration"),
        "packet_count": len(packets),
        "first_packet_pts": packets[0].get("pts") if packets else None,
        "last_packet_pts": packets[-1].get("pts") if packets else None,
    }


def main():
    print("=" * 80)
    print("SPORTCAMHUD — AMD GPU TRACK-UP + PITCH BENCHMARK & VALIDATION RUNNER")
    print("=" * 80)

    # 1. Verify DLLs
    meta_prod = verify_dll_metadata(PROD_DLL)
    meta_test = verify_dll_metadata(TEST_DLL)

    print(f"PROD DLL: {meta_prod['path']}")
    print(f"  SHA256: {meta_prod['sha256']}")
    print(f"  ABI:    {meta_prod['abi']}")
    print(f"  Build:  {meta_prod['build_info']}")
    assert meta_prod["sha256"] == EXPECTED_PROD_SHA, f"Prod DLL SHA mismatch: {meta_prod['sha256']} != {EXPECTED_PROD_SHA}"
    assert meta_prod["has_telem_amd_set_map_pitch"] is False, "Prod DLL should not have telem_amd_set_map_pitch"

    print(f"\nTEST DLL: {meta_test['path']}")
    print(f"  SHA256: {meta_test['sha256']}")
    print(f"  ABI:    {meta_test['abi']}")
    print(f"  Build:  {meta_test['build_info']}")
    assert meta_test["sha256"] == EXPECTED_TEST_SHA, f"Test DLL SHA mismatch: {meta_test['sha256']} != {EXPECTED_TEST_SHA}"
    assert meta_test["has_telem_amd_set_map_pitch"] is True, "Test DLL must export telem_amd_set_map_pitch"
    assert meta_test["telem_amd_has_map_pitch_result"] == 1, "telem_amd_has_map_pitch must return 1"

    # 2. Layout
    layout_dir = ROOT / "Raporty/gpu_pitch_bench_artifacts"
    layout_dir.mkdir(parents=True, exist_ok=True)
    benchmark_layout = layout_dir / "layout_benchmark.json"
    shutil.copyfile(ROOT / "def_layout.json", benchmark_layout)
    layout_sha = sha256_file(benchmark_layout)
    print(f"\nBENCHMARK LAYOUT: {benchmark_layout}")
    print(f"  SHA256: {layout_sha}")

    # 3. Canonical test runs
    runs = [
        # (label, dll_path, gpu_pitch_env, frames, start_s, hdr_mode)
        ("WARMUP", TEST_DLL, 1, 300, 60.0, "preserve_hlg"),
        ("A1_cpu_pitch", TEST_DLL, 0, 300, 60.0, "preserve_hlg"),
        ("B1_gpu_pitch", TEST_DLL, 1, 300, 60.0, "preserve_hlg"),
        ("B2_gpu_pitch", TEST_DLL, 1, 300, 60.0, "preserve_hlg"),
        ("A2_cpu_pitch", TEST_DLL, 0, 300, 60.0, "preserve_hlg"),
        ("A0_prod_fallback", PROD_DLL, 1, 300, 60.0, "preserve_hlg"),
        ("BOUNDARY_gpu_pitch", TEST_DLL, 1, 300, 140.0, "preserve_hlg"),
        ("TONEMAP_SDR_gpu_pitch", TEST_DLL, 1, 300, 60.0, "tonemap_sdr"),
    ]

    all_results = []
    for label, dll_path, gpu_pitch_env, frames, start_s, hdr_mode in runs:
        res = run_export_harness(
            label=label,
            out_dir=layout_dir / label,
            dll_path=dll_path,
            gpu_pitch_env=gpu_pitch_env,
            layout_path=benchmark_layout,
            videos=CANONICAL_VIDEOS,
            fit=CANONICAL_FIT,
            frames=frames,
            start_seconds=start_s,
            hdr_mode=hdr_mode,
            quality="BALANCED",
            bitrate="40M",
        )
        all_results.append(res)
        time.sleep(1.0)

    # 4. Save results summary
    summary_path = layout_dir / "benchmark_summary.json"
    summary_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"\nSaved benchmark summary to: {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
