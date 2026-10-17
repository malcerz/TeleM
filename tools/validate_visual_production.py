"""Comprehensive Production Visual Parity Suite for AMD GPU Track-Up + Pitch.

Executes canonical CPU vs GPU export pairs across:
1. Pitch 30, Pos 1 (t=10s, heading ~75°)
2. Pitch 30, Pos 2 (t=60s, heading ~143°)
3. Pitch 30, Pos 3 (t=120s, heading ~120°)
4. Pitch 45, Square
5. Pitch 0, Square
6. Pitch 30, Circle
7. Pitch 30, Rounded Rectangle (r=24)

Generates:
- Full frame & map crop comparisons
- side_by_side.png
- difference.png (boosted 5x)
- overlay_50_percent.png
- Zoomed crops (center/marker, route/track, roads/terrain, corners/border)
- SHA256 hashes, MAE, MaxDiff, PSNR, phase correlation, alpha parity, corner check
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

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = sys.executable
FFMPEG_EXE = ROOT / "ffmpeg.exe"
TEST_DLL_PATH = ROOT / "native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll"

CANONICAL_VIDEOS = "F:\\GoPro\\2026-10-15\\GX010378.MP4,F:\\GoPro\\2026-10-15\\GX010379.MP4"
CANONICAL_FIT = "F:\\GoPro\\2026-10-15\\2026-10-15_15-03-50.fit"

# Map placement in 3840x2160 canvas:
# rx=270, ry=571, map_w=499 -> top_left = (21, 322)
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


def run_export(
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


def analyze_parity(im_c: Image.Image, im_g: Image.Image) -> dict[str, Any]:
    c_arr = np.array(im_c.convert("RGBA"), dtype=np.float32)
    g_arr = np.array(im_g.convert("RGBA"), dtype=np.float32)

    rgb_c = c_arr[:, :, :3]
    rgb_g = g_arr[:, :, :3]
    alpha_c = c_arr[:, :, 3]
    alpha_g = g_arr[:, :, 3]

    diff_rgb = np.abs(rgb_c - rgb_g)
    mae_rgb = float(np.mean(diff_rgb))
    max_diff_rgb = float(np.max(diff_rgb))
    mse_rgb = float(np.mean((rgb_c - rgb_g) ** 2))
    psnr_rgb = float(10.0 * np.log10((255.0 ** 2) / max(1e-9, mse_rgb)))

    diff_alpha = np.abs(alpha_c - alpha_g)
    mae_alpha = float(np.mean(diff_alpha))
    max_diff_alpha = float(np.max(diff_alpha))

    # Phase correlation on grayscale
    c_gray = cv2.cvtColor(np.uint8(rgb_c), cv2.COLOR_RGB2GRAY)
    g_gray = cv2.cvtColor(np.uint8(rgb_g), cv2.COLOR_RGB2GRAY)
    shift, resp = cv2.phaseCorrelate(np.float32(c_gray), np.float32(g_gray))

    # Corner check (top-left, top-right, bottom-left, bottom-right)
    h, w, _ = rgb_g.shape
    corners = {
        "tl": {"rgb": [int(x) for x in rgb_g[2, 2]], "alpha": float(alpha_g[2, 2])},
        "tr": {"rgb": [int(x) for x in rgb_g[2, w - 3]], "alpha": float(alpha_g[2, w - 3])},
        "bl": {"rgb": [int(x) for x in rgb_g[h - 3, 2]], "alpha": float(alpha_g[h - 3, 2])},
        "br": {"rgb": [int(x) for x in rgb_g[h - 3, w - 3]], "alpha": float(alpha_g[h - 3, w - 3])},
    }

    return {
        "mae_rgb": mae_rgb,
        "max_diff_rgb": max_diff_rgb,
        "psnr_rgb": psnr_rgb,
        "mae_alpha": mae_alpha,
        "max_diff_alpha": max_diff_alpha,
        "phase_shift_dx": float(shift[0]),
        "phase_shift_dy": float(shift[1]),
        "phase_response": float(resp),
        "corners": corners,
    }


def generate_visual_artifacts(
    scen_dir: Path,
    c_crop: Image.Image,
    g_crop: Image.Image,
) -> dict[str, str]:
    w, h = c_crop.size

    # 1. CPU.png & GPU.png
    cpu_path = scen_dir / "CPU.png"
    gpu_path = scen_dir / "GPU.png"
    c_crop.save(cpu_path)
    g_crop.save(gpu_path)

    # 2. side_by_side.png
    sbs = Image.new("RGB", (w * 2, h))
    sbs.paste(c_crop.convert("RGB"), (0, 0))
    sbs.paste(g_crop.convert("RGB"), (w, 0))
    sbs_path = scen_dir / "side_by_side.png"
    sbs.save(sbs_path)

    # 3. difference.png (magnified 5x)
    c_arr = np.array(c_crop.convert("RGB"), dtype=np.int32)
    g_arr = np.array(g_crop.convert("RGB"), dtype=np.int32)
    diff = np.abs(c_arr - g_arr)
    diff_boost = np.uint8(np.clip(diff * 5, 0, 255))
    diff_path = scen_dir / "difference.png"
    Image.fromarray(diff_boost).save(diff_path)

    # 4. overlay_50_percent.png
    overlay = Image.blend(c_crop.convert("RGB"), g_crop.convert("RGB"), 0.5)
    overlay_path = scen_dir / "overlay_50_percent.png"
    overlay.save(overlay_path)

    # 5. Zoomed crops (2x nearest-neighbor scaled for crisp pixel inspection)
    # Center / Marker (100x100 around center 249, 249)
    cx, cy = w // 2, h // 2
    box_marker = (cx - 50, cy - 50, cx + 50, cy + 50)
    zm_c = c_crop.crop(box_marker).convert("RGB")
    zm_g = g_crop.crop(box_marker).convert("RGB")
    zm_sbs = Image.new("RGB", (200, 100))
    zm_sbs.paste(zm_c, (0, 0))
    zm_sbs.paste(zm_g, (100, 0))
    zm_sbs_2x = zm_sbs.resize((400, 200), Image.Resampling.NEAREST)
    zm_path = scen_dir / "zoom_center_marker.png"
    zm_sbs_2x.save(zm_path)

    # Route / GPS track (100x100 around bottom-center 249, 360)
    box_route = (cx - 50, cy + 40, cx + 50, cy + 140)
    zr_c = c_crop.crop(box_route).convert("RGB")
    zr_g = g_crop.crop(box_route).convert("RGB")
    zr_sbs = Image.new("RGB", (200, 100))
    zr_sbs.paste(zr_c, (0, 0))
    zr_sbs.paste(zr_g, (100, 0))
    zr_path = scen_dir / "zoom_route_track.png"
    zr_sbs.resize((400, 200), Image.Resampling.NEAREST).save(zr_path)

    # Roads / Terrain / Far distance (top quadrant: 100x100 around 249, 60)
    box_roads = (cx - 50, 10, cx + 50, 110)
    zd_c = c_crop.crop(box_roads).convert("RGB")
    zd_g = g_crop.crop(box_roads).convert("RGB")
    zd_sbs = Image.new("RGB", (200, 100))
    zd_sbs.paste(zd_c, (0, 0))
    zd_sbs.paste(zd_g, (100, 0))
    zd_path = scen_dir / "zoom_roads_terrain.png"
    zd_sbs.resize((400, 200), Image.Resampling.NEAREST).save(zd_path)

    # Corner and Border (top-left 100x100 around 0, 0)
    box_corner = (0, 0, 100, 100)
    zc_c = c_crop.crop(box_corner).convert("RGB")
    zc_g = g_crop.crop(box_corner).convert("RGB")
    zc_sbs = Image.new("RGB", (200, 100))
    zc_sbs.paste(zc_c, (0, 0))
    zc_sbs.paste(zc_g, (100, 0))
    zc_path = scen_dir / "zoom_corners_borders.png"
    zc_sbs.resize((400, 200), Image.Resampling.NEAREST).save(zc_path)

    return {
        "CPU": str(cpu_path),
        "GPU": str(gpu_path),
        "side_by_side": str(sbs_path),
        "difference": str(diff_path),
        "overlay_50": str(overlay_path),
        "zoom_marker": str(zm_path),
        "zoom_route": str(zr_path),
        "zoom_roads": str(zd_path),
        "zoom_corners": str(zc_path),
    }


def main():
    print("=" * 80)
    print("SPORTCAMHUD — FINAL PRODUCTION VISUAL VALIDATION SUITE")
    print(f"Test DLL: {TEST_DLL_PATH}")
    print(f"Test DLL SHA256: {sha256_file(TEST_DLL_PATH)}")
    print("=" * 80)

    base_out = ROOT / "Raporty/gpu_pitch_bench_artifacts/visual_parity_production"
    base_out.mkdir(parents=True, exist_ok=True)

    base_layout_path = ROOT / "Raporty/gpu_pitch_bench_artifacts/layout_benchmark.json"
    base_layout = json.loads(base_layout_path.read_text(encoding="utf-8"))

    scenarios = [
        # (name, pitch, shape, radius, start_s, frames, test_frame, heading_desc)
        ("Pitch30_Pos1_t10", 30.0, "square", 0.0, 10.0, 30, 15, "Heading ~75° (curved road)"),
        ("Pitch30_Pos2_t60", 30.0, "square", 0.0, 60.0, 30, 15, "Heading ~143° (turning corner)"),
        ("Pitch30_Pos3_t120", 30.0, "square", 0.0, 120.0, 30, 15, "Heading ~120° (straight road)"),
        ("Pitch45_Square", 45.0, "square", 0.0, 60.0, 30, 15, "High Pitch 45° (steep perspective)"),
        ("Pitch0_Square", 0.0, "square", 0.0, 60.0, 30, 15, "Flat Pitch 0° (pure Track-Up)"),
        ("Pitch30_Circle", 30.0, "circle", 0.0, 60.0, 30, 15, "Circle mask + Pitch 30°"),
        ("Pitch30_Rounded", 30.0, "rounded_rectangle", 24.0, 60.0, 30, 15, "Rounded Rectangle (r=24) + Pitch 30°"),
    ]

    suite_results = []

    for name, pitch_val, shape_val, radius_val, start_s, frames, test_frame, desc in scenarios:
        print(f"\n[{name}] {desc} | pitch={pitch_val}, shape={shape_val}, r={radius_val}, start={start_s}s...")
        scen_dir = base_out / name
        scen_dir.mkdir(parents=True, exist_ok=True)

        scen_layout = copy.deepcopy(base_layout)
        tm = scen_layout.get("indicators", {}).get("track_map", {})
        tm["pitch"] = pitch_val
        tm["map_shape"] = shape_val
        tm["map_corner_radius"] = radius_val
        layout_file = scen_dir / f"layout_{name}.json"
        layout_file.write_text(json.dumps(scen_layout, indent=2), encoding="utf-8")

        # 1. Render CPU Reference
        print(f"  Rendering CPU reference...", flush=True)
        t0_cpu = time.perf_counter()
        mp4_cpu = run_export(f"{name}_cpu", scen_dir / "cpu", layout_file, gpu_pitch=0, frames=frames, start_s=start_s)
        cpu_time = time.perf_counter() - t0_cpu

        # 2. Render GPU Candidate
        print(f"  Rendering GPU candidate...", flush=True)
        t0_gpu = time.perf_counter()
        mp4_gpu = run_export(f"{name}_gpu", scen_dir / "gpu", layout_file, gpu_pitch=1, frames=frames, start_s=start_s)
        gpu_time = time.perf_counter() - t0_gpu

        # 3. Extract frames
        f_cpu_png = scen_dir / f"frame_{test_frame}_cpu.png"
        f_gpu_png = scen_dir / f"frame_{test_frame}_gpu.png"
        extract_single_frame(mp4_cpu, test_frame, f_cpu_png)
        extract_single_frame(mp4_gpu, test_frame, f_gpu_png)

        im_c = Image.open(f_cpu_png)
        im_g = Image.open(f_gpu_png)

        # 4. Crop Map Region
        crop_c = im_c.crop(MAP_CROP_BOX)
        crop_g = im_g.crop(MAP_CROP_BOX)

        # 5. Parity analysis
        map_metrics = analyze_parity(crop_c, crop_g)
        hud_metrics = analyze_parity(im_c, im_g)

        # 6. Generate artifacts
        art_paths = generate_visual_artifacts(scen_dir, crop_c, crop_g)

        result_entry = {
            "scenario": name,
            "description": desc,
            "pitch": pitch_val,
            "shape": shape_val,
            "radius": radius_val,
            "start_seconds": start_s,
            "frame": test_frame,
            "cpu_render_time_s": round(cpu_time, 2),
            "gpu_render_time_s": round(gpu_time, 2),
            "speedup_pct": round(((cpu_time / max(1e-3, gpu_time)) - 1.0) * 100.0, 1),
            "mp4_cpu_sha256": sha256_file(mp4_cpu),
            "mp4_gpu_sha256": sha256_file(mp4_gpu),
            "map_crop_cpu_sha256": sha256_file(Path(art_paths["CPU"])),
            "map_crop_gpu_sha256": sha256_file(Path(art_paths["GPU"])),
            "map_metrics": map_metrics,
            "full_hud_metrics": hud_metrics,
            "artifacts": art_paths,
        }
        suite_results.append(result_entry)

        print(f"  [METRICS] Map MAE: {map_metrics['mae_rgb']:.3f} | PSNR: {map_metrics['psnr_rgb']:.2f} dB | Shift: ({map_metrics['phase_shift_dx']:.2f}, {map_metrics['phase_shift_dy']:.2f}) | Corr: {map_metrics['phase_response']:.4f}")
        print(f"  [SPEEDUP] CPU: {cpu_time:.2f}s vs GPU: {gpu_time:.2f}s ({result_entry['speedup_pct']:+.1f}%)")

    summary_file = base_out / "visual_validation_summary.json"
    summary_file.write_text(json.dumps(suite_results, indent=2), encoding="utf-8")
    print(f"\nSuite complete. Summary written to: {summary_file}")


if __name__ == "__main__":
    main()
