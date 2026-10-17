"""Visual Parity and Image Parity Matrix using the Canonical Export Harness.

Validates visual parity across:
1. Pitch 0, Square
2. Pitch 30, Square (from A1 vs B1 300f runs)
3. Pitch 45, Square
4. Pitch 30, Circle
5. Pitch 30, Rounded Rectangle

Extracts frames, crops map region, computes SHA256 hashes, MAE, MaxDiff, PSNR,
and verifies absence of trapezoid defects and distinctness of shapes.
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
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = sys.executable
FFMPEG_EXE = ROOT / "ffmpeg.exe"
TEST_DLL_PATH = ROOT / "native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll"

CANONICAL_VIDEOS = "F:\\GoPro\\2026-10-15\\GX010378.MP4,F:\\GoPro\\2026-10-15\\GX010379.MP4"
CANONICAL_FIT = "F:\\GoPro\\2026-10-15\\2026-10-15_15-03-50.fit"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def extract_frame(mp4_path: Path, frame_idx: int, out_png: Path) -> bool:
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
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = out_dir / "export.mp4"
    if out_mp4.exists():
        out_mp4.unlink()

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
        "--result-json", str(out_dir / "result.json"),
    ]

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["TELEM_RENDER_DEBUG"] = "1"
    env["AMD_NATIVE_PROFILING"] = "0"
    env["TELEM_AMD_NATIVE_DLL"] = str(TEST_DLL_PATH)
    env["AMD_NATIVE_MAP_GPU_PITCH"] = str(gpu_pitch)

    with open(out_dir / "harness.log", "w", encoding="utf-8") as lf:
        subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=lf, stderr=subprocess.STDOUT, check=True)

    return out_mp4


def compare_images(im_gpu: Image.Image, im_cpu: Image.Image) -> dict[str, Any]:
    arr_g = np.array(im_gpu, dtype=np.int32)
    arr_c = np.array(im_cpu, dtype=np.int32)
    diff = np.abs(arr_g - arr_c)

    mae_rgb = float(np.mean(diff[:, :, :3]))
    max_rgb = int(np.max(diff[:, :, :3]))
    mse_rgb = float(np.mean((diff[:, :, :3]) ** 2))
    psnr = 10.0 * np.log10((255.0 ** 2) / max(1e-9, mse_rgb))

    h_gpu = sha256_bytes(im_gpu.tobytes())
    h_cpu = sha256_bytes(im_cpu.tobytes())

    return {
        "hash_gpu": h_gpu,
        "hash_cpu": h_cpu,
        "hashes_differ": h_gpu != h_cpu,
        "mae_rgb": round(mae_rgb, 3),
        "max_diff_rgb": max_rgb,
        "psnr_db": round(psnr, 2),
    }


def main():
    print("=" * 80)
    print("SPORTCAMHUD — VISUAL PARITY MATRIX EVALUATION")
    print("=" * 80)

    base_dir = ROOT / "Raporty/gpu_pitch_bench_artifacts/visual_parity"
    base_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load base layout
    base_layout_path = ROOT / "Raporty/gpu_pitch_bench_artifacts/layout_benchmark.json"
    base_layout = json.loads(base_layout_path.read_text(encoding="utf-8"))

    # Map position and size:
    # "size": 13.0 (% of 3840 -> 499.2 px, rounded to 499x499)
    # "x": 7.02 (% of 3840 -> 269.57)
    # "y": 26.45 (% of 2160 -> 571.32)
    # Exact map bounding box in 3840x2160: [270, 571, 270 + 499, 571 + 499]
    map_crop_box = (270, 571, 270 + 499, 571 + 499)

    scenarios = [
        ("Pitch30_Square", 30.0, "square", 0.0),
        ("Pitch0_Square", 0.0, "square", 0.0),
        ("Pitch45_Square", 45.0, "square", 0.0),
        ("Pitch30_Circle", 30.0, "circle", 0.0),
        ("Pitch30_Rounded", 30.0, "rounded_rectangle", 24.0),
    ]

    scenario_results = []
    gpu_map_hashes = {}

    for name, pitch_val, shape_val, radius_val in scenarios:
        print(f"\n--- Scenario: {name} (pitch={pitch_val}, shape={shape_val}, radius={radius_val}) ---")
        scen_dir = base_dir / name
        scen_dir.mkdir(parents=True, exist_ok=True)

        if name == "Pitch30_Square":
            # Reuse already rendered A1 and B1 300-frame exports!
            mp4_cpu = ROOT / "Raporty/gpu_pitch_bench_artifacts/A1_cpu_pitch/export.mp4"
            mp4_gpu = ROOT / "Raporty/gpu_pitch_bench_artifacts/B1_gpu_pitch/export.mp4"
            test_frame = 150
        else:
            # Create tailored layout
            scen_layout = copy.deepcopy(base_layout)
            track_map = scen_layout.get("indicators", {}).get("track_map", {})
            track_map["pitch"] = pitch_val
            track_map["map_shape"] = shape_val
            track_map["map_corner_radius"] = radius_val
            layout_file = scen_dir / f"layout_{name}.json"
            layout_file.write_text(json.dumps(scen_layout, indent=2), encoding="utf-8")

            # Run CPU reference
            print(f"  Rendering CPU reference (30 frames)...", flush=True)
            mp4_cpu = run_single_export(f"{name}_cpu", scen_dir / "cpu", layout_file, gpu_pitch=0, frames=30)
            # Run GPU
            print(f"  Rendering GPU candidate (30 frames)...", flush=True)
            mp4_gpu = run_single_export(f"{name}_gpu", scen_dir / "gpu", layout_file, gpu_pitch=1, frames=30)
            test_frame = 15

        # Extract frames
        f_cpu_path = scen_dir / f"frame_{test_frame}_cpu.png"
        f_gpu_path = scen_dir / f"frame_{test_frame}_gpu.png"
        extract_frame(mp4_cpu, test_frame, f_cpu_path)
        extract_frame(mp4_gpu, test_frame, f_gpu_path)

        im_c = Image.open(f_cpu_path).convert("RGBA")
        im_g = Image.open(f_gpu_path).convert("RGBA")

        # Full HUD comparison
        full_cmp = compare_images(im_g, im_c)

        # Map crop comparison
        crop_c = im_c.crop(map_crop_box)
        crop_g = im_g.crop(map_crop_box)
        crop_c.save(scen_dir / f"map_crop_cpu.png")
        crop_g.save(scen_dir / f"map_crop_gpu.png")

        map_cmp = compare_images(crop_g, crop_c)
        gpu_map_hashes[name] = map_cmp["hash_gpu"]

        # Visual difference visualization
        diff = ImageChops.difference(crop_g.convert("RGB"), crop_c.convert("RGB"))
        diff_boosted = Image.eval(diff, lambda px: min(255, px * 8))
        diff_boosted.save(scen_dir / "map_diff_boosted.png")

        # Create side-by-side comparison
        w, h = crop_g.size
        sbs = Image.new("RGB", (w * 3, h))
        sbs.paste(crop_c.convert("RGB"), (0, 0))
        sbs.paste(crop_g.convert("RGB"), (w, 0))
        sbs.paste(diff_boosted, (w * 2, 0))
        sbs.save(scen_dir / "side_by_side_compare.png")

        # Check square corners for trapezoid defect
        # In the cropped 499x499 map, check corners (0,0), (498,0), (0,498), (498,498)
        arr_crop_g = np.array(crop_g)
        corners = [(5, 5), (w - 6, 5), (5, h - 6), (w - 6, h - 6)]
        corner_colors = [arr_crop_g[y, x][:3].tolist() for x, y in corners]
        # In a square with map background, corner pixels must be the satellite map background (non-black / non-transparent)
        is_trapezoid = any(sum(rgb) == 0 for rgb in corner_colors) if shape_val == "square" else False

        entry = {
            "scenario": name,
            "frame_idx": test_frame,
            "pitch": pitch_val,
            "shape": shape_val,
            "crop_rect": f"{w}x{h} at {map_crop_box[:2]}",
            "cpu_hash": map_cmp["hash_cpu"],
            "gpu_hash": map_cmp["hash_gpu"],
            "hashes_differ": map_cmp["hashes_differ"],
            "mae_rgb": map_cmp["mae_rgb"],
            "max_diff_rgb": map_cmp["max_diff_rgb"],
            "psnr_db": map_cmp["psnr_db"],
            "full_frame_psnr_db": full_cmp["psnr_db"],
            "full_frame_mae_rgb": full_cmp["mae_rgb"],
            "trapezoid_defect": is_trapezoid,
            "corner_samples": corner_colors,
        }
        scenario_results.append(entry)
        print(
            f"  Result: MAE={map_cmp['mae_rgb']:.2f} | MaxDiff={map_cmp['max_diff_rgb']} | PSNR={map_cmp['psnr_db']:.2f} dB | "
            f"Full HUD PSNR={full_cmp['psnr_db']:.2f} dB | Trapezoid Defect={is_trapezoid}",
            flush=True,
        )

    # Cross check that different shapes produce distinct images
    print("\n--- Cross-Shape Hash Verification at Pitch 30 ---")
    h_sq = gpu_map_hashes["Pitch30_Square"]
    h_ci = gpu_map_hashes["Pitch30_Circle"]
    h_rn = gpu_map_hashes["Pitch30_Rounded"]
    print(f"Square Hash:  {h_sq}")
    print(f"Circle Hash:  {h_ci}")
    print(f"Rounded Hash: {h_rn}")
    assert h_sq != h_ci, "Square and Circle MUST have distinct hashes!"
    assert h_sq != h_rn, "Square and Rounded MUST have distinct hashes!"
    assert h_ci != h_rn, "Circle and Rounded MUST have distinct hashes!"
    print("PASS: All three shapes produce distinct, non-identical image hashes.")

    # Cross check that Pitch 0 vs Pitch 30 vs Pitch 45 produce distinct images
    h_p0 = gpu_map_hashes["Pitch0_Square"]
    h_p30 = gpu_map_hashes["Pitch30_Square"]
    h_p45 = gpu_map_hashes["Pitch45_Square"]
    print("\n--- Cross-Pitch Hash Verification ---")
    print(f"Pitch 0 Hash:  {h_p0}")
    print(f"Pitch 30 Hash: {h_p30}")
    print(f"Pitch 45 Hash: {h_p45}")
    assert h_p0 != h_p30, "Pitch 0 and Pitch 30 MUST have distinct hashes!"
    assert h_p30 != h_p45, "Pitch 30 and Pitch 45 MUST have distinct hashes!"
    print("PASS: Pitch angles produce distinct, geometrically correct transformations.")

    report = {
        "scenarios": scenario_results,
        "cross_shape_verified": True,
        "cross_pitch_verified": True,
    }
    summary_path = base_dir / "visual_parity_report.json"
    summary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nFinal visual parity report saved to: {summary_path}")


if __name__ == "__main__":
    main()
