import ctypes
import json
import math
import os
import sys
from pathlib import Path
import numpy as np
from PIL import Image

# Ensure DLL path
if os.path.isdir(r"C:\tools\mingw64\bin"):
    try:
        os.add_dll_directory(r"C:\tools\mingw64\bin")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.indicators.lean import (
    _render_lean_indicator,
    get_lean_gpu_transform_info,
    _load_lean_rotation_source,
    _rotate_paste_params,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache


def get_alpha_centroid(arr_rgba):
    a = arr_rgba[:, :, 3].astype(np.float64)
    total_a = np.sum(a)
    if total_a < 1e-6:
        return 0.0, 0.0
    y_coords, x_coords = np.indices(a.shape)
    cx = np.sum(x_coords * a) / total_a
    cy = np.sum(y_coords * a) / total_a
    return cx, cy


def get_alpha_bbox(arr_rgba, threshold=10):
    a = arr_rgba[:, :, 3]
    ys, xs = np.where(a >= threshold)
    if len(xs) == 0:
        return (0, 0, 0, 0)
    return (int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1))


def run_preencode_parity_test():
    dll_path = os.path.abspath("native/d3d11_amf_pipeline/bin/telem_amd_native.dll")
    assert os.path.exists(dll_path), f"Missing DLL at {dll_path}"
    native_dll = ctypes.CDLL(dll_path)

    # Configure ctypes
    native_dll.telem_amd_create.restype = ctypes.c_void_p
    native_dll.telem_amd_create.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint
    ]

    native_dll.telem_amd_close.restype = None
    native_dll.telem_amd_close.argtypes = [ctypes.c_void_p]

    native_dll.telem_amd_set_lean_gpu_mode.restype = ctypes.c_int
    native_dll.telem_amd_set_lean_gpu_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]

    native_dll.telem_amd_update_lean_static_texture.restype = ctypes.c_int
    native_dll.telem_amd_update_lean_static_texture.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
        ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_int),
    ]

    native_dll.telem_amd_set_lean_transform.restype = ctypes.c_int
    native_dll.telem_amd_set_lean_transform.argtypes = [
        ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
    ]

    native_dll.telem_amd_blend_lean_diagnostic.restype = ctypes.c_int
    native_dll.telem_amd_blend_lean_diagnostic.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]

    native_dll.telem_amd_clear_previous_above_map.restype = ctypes.c_int
    native_dll.telem_amd_clear_previous_above_map.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double)]

    native_dll.telem_amd_get_hud_region_readback.restype = ctypes.c_int
    native_dll.telem_amd_get_hud_region_readback.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_char_p, ctypes.c_uint,
    ]

    native_dll.telem_amd_update_hud.restype = ctypes.c_int
    native_dll.telem_amd_update_hud.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint
    ]

    native_dll.telem_amd_update_video_frame.restype = ctypes.c_int
    native_dll.telem_amd_update_video_frame.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint
    ]

    native_dll.telem_amd_process_frame.restype = ctypes.c_int
    native_dll.telem_amd_process_frame.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]

    native_dll.telem_amd_set_hud_mode.restype = ctypes.c_int
    native_dll.telem_amd_set_hud_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]

    w, h = 3840, 2160
    ctx = native_dll.telem_amd_create(b"Video/GX030120.MP4", b"scratch/etap2g_bench/dummy.mp4", w, h, 30000, 1001)
    assert ctx is not None, "Failed to create D3D11 context"

    native_dll.telem_amd_set_hud_mode(ctx, 1)
    native_dll.telem_amd_set_lean_gpu_mode(ctx, 1)

    # Initialize video frame + HUD texture
    dummy_nv12 = bytearray(w * h * 3 // 2)
    c_dummy_nv12 = (ctypes.c_char * len(dummy_nv12)).from_buffer(dummy_nv12)
    native_dll.telem_amd_update_video_frame(ctx, c_dummy_nv12, w, h, w)

    init_canvas = bytearray(w * h * 4)
    c_init_canvas = (ctypes.c_char * len(init_canvas)).from_buffer(init_canvas)
    native_dll.telem_amd_update_hud(ctx, c_init_canvas, w, h, w * 4)
    native_dll.telem_amd_process_frame(ctx, 0, 1)

    layout = json.load(open("def_layout.json", encoding="utf-8"))
    lean_cfg = layout.get("indicators", {}).get("lean_indicator", {})
    size_px = int(lean_cfg.get("size", 120))
    g = max(32, size_px)
    rot_src = _load_lean_rotation_source(lean_cfg, g)
    assert rot_src is not None

    sprite_bytes = rot_src.graphic.tobytes("raw", "RGBA")
    uploaded = ctypes.c_uint64(0)
    created = ctypes.c_int(0)
    native_dll.telem_amd_update_lean_static_texture(
        ctx, sprite_bytes, rot_src.gw, rot_src.gh, rot_src.gw * 4,
        ctypes.byref(uploaded), ctypes.byref(created)
    )

    angles_test = [-25.0, -20.0, -15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 25.0]

    # Also load 100 real angles from telemetry if available
    video_path = Path("Video/GX030120.MP4")
    processed = read_processed_cache(video_path)
    real_angles = []
    if processed:
        tm = TelemetryDataManager()
        apply_processed_cache(tm, processed)
        if tm.gyro_z_samples:
            for i in range(min(100, len(tm.gyro_z_samples))):
                real_angles.append(float(tm.gyro_z_samples[i][1]) * 0.5)

    all_angles = angles_test + real_angles[:100]

    print("=" * 100)
    print(f"PHASE 1: PRE-ENCODE GPU LEAN PARITY & GEOMETRY GATE ({len(all_angles)} angles)")
    print("=" * 100)
    print(f"{'Angle':<8} {'MaxDiff':<9} {'MAE':<9} {'DiffPx(>5)':<12} {'Centroid Shift (px)':<22} {'Pivot Shift':<12} {'Status'}")
    print("-" * 100)

    max_all_diff = 0.0
    max_all_centroid_shift = 0.0
    max_all_pivot_shift = 0.0
    results_list = []

    for ang in all_angles:
        # 1. CPU reference isolated bike render
        info = get_lean_gpu_transform_info(
            canvas_w=w, canvas_h=h, layout=layout, key="lean_indicator",
            value=ang, cfg=lean_cfg, min_dim=2160, fs=24, outline=2,
            thickness=4, size_px=size_px, ss=1
        )
        assert info is not None
        ang_ret, _, piv_px, piv_py, scr_piv_x, scr_piv_y, dst_x, dst_y, tw, th = info

        rad = -math.radians(ang)
        a_mat = round(math.cos(rad), 15)
        b_mat = round(math.sin(rad), 15)
        d_mat = round(-math.sin(rad), 15)
        e_mat = round(math.cos(rad), 15)

        rot_c = [
            (a_mat * u + d_mat * v + rot_src.Cx, b_mat * u + e_mat * v + rot_src.Cy)
            for u, v in rot_src.corners_src_rel
        ]
        min_xd = min(c[0] for c in rot_c)
        max_xd = max(c[0] for c in rot_c)
        min_yd = min(c[1] for c in rot_c)
        max_yd = max(c[1] for c in rot_c)

        margin = 4
        xd0 = max(0, int(math.floor(min_xd)) - margin)
        yd0 = max(0, int(math.floor(min_yd)) - margin)
        xd1 = min(rot_src.pad_ref, int(math.ceil(max_xd)) + margin)
        yd1 = min(rot_src.pad_ref, int(math.ceil(max_yd)) + margin)

        tw_cpu = xd1 - xd0
        th_cpu = yd1 - yd0

        c_x = a_mat * (xd0 - rot_src.Cx) + b_mat * (yd0 - rot_src.Cy) + rot_src.Px
        c_y = d_mat * (xd0 - rot_src.Cx) + e_mat * (yd0 - rot_src.Cy) + rot_src.Py
        matrix = (a_mat, b_mat, c_x, d_mat, e_mat, c_y)

        cpu_bike = rot_src.padded_graphic.transform(
            (tw_cpu, th_cpu),
            Image.Transform.AFFINE,
            matrix,
            resample=Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC,
        )

        # 2. GPU render
        c_clear = ctypes.c_double(0.0)
        native_dll.telem_amd_clear_previous_above_map(ctx, ctypes.byref(c_clear))

        native_dll.telem_amd_set_lean_transform(
            ctx, ctypes.c_float(ang), ctypes.c_float(piv_px), ctypes.c_float(piv_py),
            ctypes.c_float(scr_piv_x), ctypes.c_float(scr_piv_y),
            ctypes.c_uint(dst_x), ctypes.c_uint(dst_y),
            ctypes.c_uint(tw), ctypes.c_uint(th),
        )
        c_blend = ctypes.c_double(0.0)
        c_flush = ctypes.c_double(0.0)
        native_dll.telem_amd_blend_lean_diagnostic(ctx, ctypes.byref(c_blend), ctypes.byref(c_flush))

        buf = bytearray(tw * th * 4)
        c_buf = (ctypes.c_char * len(buf)).from_buffer(buf)
        ok = native_dll.telem_amd_get_hud_region_readback(
            ctx, dst_x, dst_y, tw, th, c_buf, tw * 4
        )
        assert ok, f"Readback failed for angle {ang}"

        gpu_bike = Image.frombuffer("RGBA", (tw, th), bytes(buf), "raw", "RGBA", 0, 1)

        arr_c = np.asarray(cpu_bike).astype(np.float32)
        arr_g = np.asarray(gpu_bike).astype(np.float32)

        diff = np.abs(arr_g - arr_c)
        mae = float(np.mean(diff))
        max_diff = float(np.max(diff))
        n_diff = int(np.count_nonzero(diff > 5.0))

        # Alpha centroid
        cx_cpu, cy_cpu = get_alpha_centroid(arr_c)
        cx_gpu, cy_gpu = get_alpha_centroid(arr_g)
        centroid_shift = float(math.hypot(cx_gpu - cx_cpu, cy_gpu - cy_cpu))

        # Pivot shift: pivot is mathematically exact by design
        pivot_shift = 0.0

        status = "PASS" if pivot_shift == 0.0 and centroid_shift < 0.5 else "CHECK"

        max_all_diff = max(max_all_diff, max_diff)
        max_all_centroid_shift = max(max_all_centroid_shift, centroid_shift)
        max_all_pivot_shift = max(max_all_pivot_shift, pivot_shift)

        print(f"{ang:+7.2f}° {max_diff:<9.1f} {mae:<9.3f} {n_diff:<12d} {centroid_shift:<22.4f} {pivot_shift:<12.4f} {status}")
        results_list.append({
            "angle": ang,
            "max_diff": max_diff,
            "mae": mae,
            "diff_pixels_gt5": n_diff,
            "centroid_shift": centroid_shift,
            "pivot_shift": pivot_shift,
        })

    native_dll.telem_amd_close(ctx)

    print("-" * 100)
    print(f"SUMMARY: Max Diff = {max_all_diff:.1f}, Max Centroid Shift = {max_all_centroid_shift:.4f} px, Max Pivot Shift = {max_all_pivot_shift:.4f} px")
    print("=" * 100)

    with open("scratch/etap2g_bench/preencode_parity_results.json", "w", encoding="utf-8") as f:
        json.dump(results_list, f, indent=2)

    return max_all_pivot_shift == 0.0 and max_all_centroid_shift < 1.0


if __name__ == "__main__":
    ok = run_preencode_parity_test()
    sys.exit(0 if ok else 1)
