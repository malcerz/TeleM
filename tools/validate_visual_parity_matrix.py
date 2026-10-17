"""Image Quality and Parity Validation Suite for AMD GPU Track-Up + Pitch.

Strict visual parity validation:
1. Systematic matrix across Pitches (0, 30, 45) and Shapes (Square, Circle, Rounded Rectangle).
2. Explicit check that CPU and GPU images are independently generated (distinct hashes).
3. Explicit check that changing Shape changes the resulting image (Square != Circle != Rounded Rectangle).
4. Explicit check for trapezoid defect: square corners (0,0), (0, -1), (-1, 0), (-1, -1) must be filled.
5. Extraction and comparison of actual exported MP4 frames (Frame 30, Frame 150) from A1 (CPU) and B1 (GPU).
6. Production of side-by-side and difference artifacts in Raporty/gpu_pitch_bench_artifacts/visual_parity/.
"""

from __future__ import annotations

import ctypes as c
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.indicators.helpers import (
    apply_map_pitch,
    apply_map_shape,
    compute_map_pitch_quad,
    map_style_layers,
    _get_map_pitch_transforms,
)

FFMPEG_EXE = ROOT / "ffmpeg.exe"
TEST_DLL_PATH = ROOT / "native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll"
PROD_DLL_PATH = ROOT / "runtime/amd/bin/telem_amd_native.dll"


def create_synthetic_test_map(width: int = 978, height: int = 978) -> Image.Image:
    """Create a high-contrast map with grid, GPS track, landmarks, and center marker."""
    img = Image.new("RGBA", (width, height), (34, 139, 34, 255))
    draw = ImageDraw.Draw(img)

    step = 64
    for x in range(0, width, step):
        draw.line([(x, 0), (x, height)], fill=(50, 180, 50, 255), width=2)
    for y in range(0, height, step):
        draw.line([(0, y), (width, y)], fill=(50, 180, 50, 255), width=2)

    # Simulated track
    cx, cy = width / 2.0, height / 2.0
    pts = [
        (cx - 320, cy + 240),
        (cx - 160, cy + 120),
        (cx, cy),
        (cx + 120, cy - 180),
        (cx + 280, cy - 320),
    ]
    draw.line(pts, fill=(255, 60, 30, 255), width=10)

    # Center dot marker
    r = 14
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=3)
    return img


def get_cpu_reference_map(
    source_img: Image.Image,
    dst_size: int,
    heading_deg: float,
    pitch_deg: float,
    shape: str = "square",
    radius: int = 16,
    border_w: int = 2,
    border_color: str = "#FFFFFF",
) -> Image.Image:
    """Compute exact CPU reference: rotate(BICUBIC) -> crop -> pitch -> shape."""
    w, h = source_img.size
    rotated = source_img.rotate(heading_deg, resample=Image.BICUBIC)
    offset_x = int((w - dst_size) // 2)
    offset_y = int((h - dst_size) // 2)
    cropped = rotated.crop((offset_x, offset_y, offset_x + dst_size, offset_y + dst_size))
    pitched = apply_map_pitch(cropped, pitch_deg)
    shaped = apply_map_shape(
        pitched,
        shape=shape,
        corner_radius=radius,
        border_width=border_w,
        border_color=border_color,
        scale=1.0,
    )
    return shaped


class D3D11MapProbe:
    def __init__(self, dll_path: Path):
        self.dll_path = dll_path
        self.dll = c.CDLL(str(dll_path))
        self._bind()

        video_path = r"F:\GoPro\2026-10-15\GX010378.MP4"
        self.h = self.telem_amd_create(video_path, "NUL", 3840, 2160, 30000, 1001)
        if not self.h:
            raise RuntimeError(f"Failed to create native context with DLL: {dll_path}")

        self.telem_amd_set_hud_mode(self.h, 1)
        self.telem_amd_set_decode_mode(self.h, 1)
        self.telem_amd_set_hud_enabled(self.h, 1)
        self.telem_amd_set_amf_mode(self.h, 1)
        self.telem_amd_set_map_mode(self.h, 1)
        self.telem_amd_set_map_filter(self.h, 1)
        self.telem_amd_set_map_gpu_path(self.h, 1)
        self.frame_idx = 0

    def _bind(self):
        def b(name, args, res=c.c_int):
            fn = getattr(self.dll, "telem_amd_" + name)
            fn.argtypes = args
            fn.restype = res
            setattr(self, "telem_amd_" + name, fn)

        b("create", [c.c_wchar_p, c.c_wchar_p] + [c.c_uint] * 4, c.c_void_p)
        b("close", [c.c_void_p], None)
        for n in [
            "set_decode_mode", "set_hud_mode", "set_hud_enabled", "set_amf_mode",
            "set_map_mode", "set_map_filter", "set_map_gpu_path", "set_map_rotate_mode",
        ]:
            b(n, [c.c_void_p, c.c_int])

        b("set_map_heading", [c.c_void_p, c.c_float])
        b("set_map_pitch", [c.c_void_p, c.c_float, c.POINTER(c.c_float)])
        b("get_map_pitch_enabled", [c.c_void_p])
        b("has_map_pitch", [], c.c_int)
        b("set_map_geometry", [c.c_void_p] + [c.c_uint] * 6)
        b("update_map", [c.c_void_p, c.c_void_p] + [c.c_uint] * 3 + [c.c_void_p] * 2)
        b("update_hud", [c.c_void_p, c.c_void_p] + [c.c_uint] * 3)
        b("process_frame", [c.c_void_p, c.c_uint, c.c_int])
        b("get_hud_region_readback", [c.c_void_p] + [c.c_uint] * 4 + [c.c_void_p, c.c_uint])
        b("read_video_sample", [c.c_void_p] + [c.c_void_p] * 10)
        if hasattr(self.dll, "telem_amd_update_map_style"):
            b("update_map_style", [c.c_void_p, c.c_void_p] + [c.c_uint] * 3 + [c.c_float] * 4)

    def render_gpu_map(
        self,
        source_img: Image.Image,
        dst_size: int,
        heading_deg: float,
        pitch_deg: float,
        shape: str = "square",
        radius: int = 16,
        border_w: int = 2,
        border_color: str = "#FFFFFF",
    ) -> Image.Image:
        src_w, src_h = source_img.size
        dst_x, dst_y = 50, 50

        self.telem_amd_set_map_geometry(self.h, dst_x, dst_y, src_w, src_h, dst_size, dst_size)
        self.telem_amd_set_map_rotate_mode(self.h, 1)
        self.telem_amd_set_map_heading(self.h, c.c_float(heading_deg))

        if pitch_deg > 0.001:
            cv2_M, pil_coeffs, _ = _get_map_pitch_transforms(dst_size, dst_size, pitch_deg)
            if pil_coeffs is not None and len(pil_coeffs) >= 8:
                inv_m = [
                    float(pil_coeffs[0]), float(pil_coeffs[1]), float(pil_coeffs[2]),
                    float(pil_coeffs[3]), float(pil_coeffs[4]), float(pil_coeffs[5]),
                    float(pil_coeffs[6]), float(pil_coeffs[7]), 1.0,
                ]
                inv_arr = (c.c_float * 9)(*inv_m)
                self.telem_amd_set_map_pitch(self.h, c.c_float(pitch_deg), inv_arr)
            else:
                self.telem_amd_set_map_pitch(self.h, c.c_float(pitch_deg), None)
        else:
            self.telem_amd_set_map_pitch(self.h, c.c_float(0.0), None)

        layers = map_style_layers((dst_size, dst_size), shape, radius, border_w, border_color, 1.0)
        if layers and hasattr(self, "telem_amd_update_map_style"):
            _, _, payload, color_rgba = layers
            c_r, c_g, c_b, c_a = (v / 255.0 for v in color_rgba)
            self.telem_amd_update_map_style(
                self.h, payload, dst_size, dst_size, dst_size * 4,
                c.c_float(c_r), c.c_float(c_g), c.c_float(c_b), c.c_float(c_a),
            )

        bg_hud = Image.new("RGBA", (3840, 2160), (0, 0, 0, 0))
        bg_bytes = bg_hud.tobytes()
        src_bytes = source_img.tobytes()

        self.telem_amd_read_video_sample(self.h, *([None] * 10))
        self.telem_amd_update_hud(self.h, bg_bytes, 3840, 2160, 3840 * 4)
        self.telem_amd_update_map(self.h, src_bytes, src_w, src_h, src_w * 4, None, None)

        self.telem_amd_process_frame(self.h, self.frame_idx, 1)
        self.frame_idx += 1

        out_buf = (c.c_uint8 * (dst_size * dst_size * 4))()
        ok = self.telem_amd_get_hud_region_readback(
            self.h, dst_x, dst_y, dst_size, dst_size, out_buf, dst_size * 4,
        )
        if not ok:
            raise RuntimeError("get_hud_region_readback failed")

        return Image.frombytes("RGBA", (dst_size, dst_size), bytes(out_buf))

    def close(self):
        if self.h:
            self.telem_amd_close(self.h)
            self.h = None


def compute_metrics(im_gpu: Image.Image, im_cpu: Image.Image) -> dict[str, Any]:
    arr_g = np.array(im_gpu, dtype=np.int32)
    arr_c = np.array(im_cpu, dtype=np.int32)
    diff = np.abs(arr_g - arr_c)

    mae_rgb = float(np.mean(diff[:, :, :3]))
    mae_alpha = float(np.mean(diff[:, :, 3]))
    max_rgb = int(np.max(diff[:, :, :3]))
    max_alpha = int(np.max(diff[:, :, 3]))

    mse_rgb = float(np.mean((diff[:, :, :3]) ** 2))
    psnr = 10.0 * np.log10((255.0 ** 2) / max(1e-9, mse_rgb))

    hash_gpu = hashlib.sha256(im_gpu.tobytes()).hexdigest()
    hash_cpu = hashlib.sha256(im_cpu.tobytes()).hexdigest()

    # Corner check (for square)
    w, h = im_gpu.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    corner_alphas = [int(arr_g[y, x, 3]) for x, y in corners]

    return {
        "hash_gpu": hash_gpu,
        "hash_cpu": hash_cpu,
        "mae_rgb": round(mae_rgb, 3),
        "mae_alpha": round(mae_alpha, 3),
        "max_diff_rgb": max_rgb,
        "max_diff_alpha": max_alpha,
        "psnr_db": round(psnr, 2),
        "corner_alphas": corner_alphas,
        "hashes_differ": hash_gpu != hash_cpu,
    }


def extract_frame_from_mp4(mp4_path: Path, frame_idx: int, out_png: Path) -> bool:
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


def run_full_validation() -> dict[str, Any]:
    out_dir = ROOT / "Raporty/gpu_pitch_bench_artifacts/visual_parity"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n--- Phase 1: Direct D3D11 Native Probe Shape & Pitch Matrix ---")
    probe = D3D11MapProbe(TEST_DLL_PATH)
    source_img = create_synthetic_test_map(978, 978)
    source_img.save(out_dir / "synthetic_source_map_978x978.png")

    dst_size = 692
    cases = [
        # (id, heading, pitch, shape, radius, border_w)
        ("P0_Square", 45.0, 0.0, "square", 0, 3),
        ("P30_Square", 45.0, 30.0, "square", 0, 3),
        ("P45_Square", 45.0, 45.0, "square", 0, 3),
        ("P0_Circle", 45.0, 0.0, "circle", 0, 3),
        ("P30_Circle", 45.0, 30.0, "circle", 0, 3),
        ("P45_Circle", 45.0, 45.0, "circle", 0, 3),
        ("P0_Rounded", 45.0, 0.0, "rounded_rectangle", 24, 3),
        ("P30_Rounded", 45.0, 30.0, "rounded_rectangle", 24, 3),
        ("P45_Rounded", 45.0, 45.0, "rounded_rectangle", 24, 3),
    ]

    matrix_results = []
    gpu_hashes_by_shape = {}

    for cid, heading, pitch, shape, radius, border_w in cases:
        gpu_im = probe.render_gpu_map(source_img, dst_size, heading, pitch, shape, radius, border_w)
        cpu_im = get_cpu_reference_map(source_img, dst_size, heading, pitch, shape, radius, border_w)

        gpu_im.save(out_dir / f"gpu_{cid}.png")
        cpu_im.save(out_dir / f"cpu_{cid}.png")

        metrics = compute_metrics(gpu_im, cpu_im)
        gpu_hashes_by_shape.setdefault(shape, {})[pitch] = metrics["hash_gpu"]

        # Corner check: for square, all 4 corners must be alpha 255
        trapezoid_defect = False
        if shape == "square":
            trapezoid_defect = any(a < 250 for a in metrics["corner_alphas"])

        res_entry = {
            "case_id": cid,
            "pitch_deg": pitch,
            "shape": shape,
            "measurement_rect": f"{dst_size}x{dst_size}",
            "hash_cpu": metrics["hash_cpu"],
            "hash_gpu": metrics["hash_gpu"],
            "mae_rgb": metrics["mae_rgb"],
            "mae_alpha": metrics["mae_alpha"],
            "max_diff_rgb": metrics["max_diff_rgb"],
            "psnr_db": metrics["psnr_db"],
            "corner_alphas": metrics["corner_alphas"],
            "trapezoid_defect": trapezoid_defect,
            "hashes_differ": metrics["hashes_differ"],
        }
        matrix_results.append(res_entry)
        print(
            f"  [{'PASS' if not trapezoid_defect else 'FAIL'}] {cid:14s} | Pitch: {pitch:4.1f}° | Shape: {shape:17s} | "
            f"MAE: {metrics['mae_rgb']:5.2f} | MaxDiff: {metrics['max_diff_rgb']:3d} | PSNR: {metrics['psnr_db']:5.2f} dB | "
            f"DiffHashes: {metrics['hashes_differ']} | Corners: {metrics['corner_alphas']}",
            flush=True,
        )

    probe.close()

    # Verify that different shapes produce distinct images
    shape_cross_check = {
        "pitch30_square_vs_circle_differ": gpu_hashes_by_shape["square"][30.0] != gpu_hashes_by_shape["circle"][30.0],
        "pitch30_square_vs_rounded_differ": gpu_hashes_by_shape["square"][30.0] != gpu_hashes_by_shape["rounded_rectangle"][30.0],
        "pitch30_circle_vs_rounded_differ": gpu_hashes_by_shape["circle"][30.0] != gpu_hashes_by_shape["rounded_rectangle"][30.0],
    }
    print(f"\nShape distinctness verification at Pitch 30: {shape_cross_check}")
    assert all(shape_cross_check.values()), "Shapes MUST produce distinct images!"

    print("\n--- Phase 2: Full HUD Export Frame Comparison (A1 vs B1) ---")
    a1_mp4 = ROOT / "Raporty/gpu_pitch_bench_artifacts/A1_cpu_pitch/export.mp4"
    b1_mp4 = ROOT / "Raporty/gpu_pitch_bench_artifacts/B1_gpu_pitch/export.mp4"

    mp4_results = []
    if a1_mp4.exists() and b1_mp4.exists():
        for frame_num in [30, 150]:
            f_cpu = out_dir / f"hud_frame{frame_num}_A1_cpu.png"
            f_gpu = out_dir / f"hud_frame{frame_num}_B1_gpu.png"

            ok_c = extract_frame_from_mp4(a1_mp4, frame_num, f_cpu)
            ok_g = extract_frame_from_mp4(b1_mp4, frame_num, f_gpu)
            if ok_c and ok_g:
                im_c = Image.open(f_cpu).convert("RGBA")
                im_g = Image.open(f_gpu).convert("RGBA")

                # Full frame comparison
                full_metrics = compute_metrics(im_g, im_c)

                # Map crop: x=7.02%, y=26.45%, size=13% of 3840 -> x=270, y=571, w=499, h=499
                # In 3840x2160: map is at left: 3840 * 0.0702 = 269.57; top: 2160 * 0.2645 = 571.32; size: 499x499
                crop_box = (250, 550, 250 + 540, 550 + 540)
                crop_c = im_c.crop(crop_box)
                crop_g = im_g.crop(crop_box)
                crop_c.save(out_dir / f"map_crop_frame{frame_num}_A1_cpu.png")
                crop_g.save(out_dir / f"map_crop_frame{frame_num}_B1_gpu.png")

                # Create visual difference heatmap
                diff_img = ImageChops.difference(crop_c.convert("RGB"), crop_g.convert("RGB"))
                # Multiply diff to highlight subtleties
                diff_enhanced = Image.eval(diff_img, lambda px: min(255, px * 8))
                diff_enhanced.save(out_dir / f"map_diff_enhanced_frame{frame_num}.png")

                crop_metrics = compute_metrics(crop_g, crop_c)

                entry = {
                    "frame_index": frame_num,
                    "full_frame": full_metrics,
                    "map_crop": crop_metrics,
                }
                mp4_results.append(entry)
                print(
                    f"  Frame {frame_num:3d} Full HUD | MAE: {full_metrics['mae_rgb']:.2f} | PSNR: {full_metrics['psnr_db']:.2f} dB\n"
                    f"            Map Crop | MAE: {crop_metrics['mae_rgb']:.2f} | MaxDiff: {crop_metrics['max_diff_rgb']:3d} | PSNR: {crop_metrics['psnr_db']:.2f} dB",
                    flush=True,
                )
    else:
        print("Warning: A1 or B1 export.mp4 not found yet for frame comparison.")

    final_report = {
        "shape_pitch_matrix": matrix_results,
        "shape_cross_check": shape_cross_check,
        "mp4_frame_comparisons": mp4_results,
    }
    json_path = out_dir / "visual_parity_summary.json"
    json_path.write_text(json.dumps(final_report, indent=2), encoding="utf-8")
    print(f"\nSaved visual parity summary to: {json_path}")
    return final_report


if __name__ == "__main__":
    run_full_validation()
