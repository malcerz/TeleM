from PIL import Image
import numpy as np
import ctypes, json, os, sys, math
from pathlib import Path

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

dll_path = os.path.abspath("native/d3d11_amf_pipeline/bin/telem_amd_native.dll")
native_dll = ctypes.CDLL(dll_path)

native_dll.telem_amd_create.restype = ctypes.c_void_p
native_dll.telem_amd_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
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
native_dll.telem_amd_set_hud_mode.restype = ctypes.c_int
native_dll.telem_amd_set_hud_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
native_dll.telem_amd_update_video_frame.restype = ctypes.c_int
native_dll.telem_amd_update_video_frame.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
native_dll.telem_amd_update_hud.restype = ctypes.c_int
native_dll.telem_amd_update_hud.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
native_dll.telem_amd_process_frame.restype = ctypes.c_int
native_dll.telem_amd_process_frame.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]

w, h = 3840, 2160
ctx = native_dll.telem_amd_create(b"Video/GX030120.MP4", b"scratch/etap2g_bench/dummy.mp4", w, h, 30000, 1001)

native_dll.telem_amd_set_hud_mode(ctx, 1)
native_dll.telem_amd_set_lean_gpu_mode(ctx, 1)

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

sprite_bytes = rot_src.graphic.tobytes("raw", "RGBA")
uploaded = ctypes.c_uint64(0)
created = ctypes.c_int(0)
native_dll.telem_amd_update_lean_static_texture(
    ctx, sprite_bytes, rot_src.gw, rot_src.gh, rot_src.gw * 4,
    ctypes.byref(uploaded), ctypes.byref(created)
)

print("=" * 95)
print("EXACT PIVOT-MATCHED PRE-ENCODE PARITY")
print("=" * 95)

# Exact pivot matching Pillow
piv_px_exact = float(rot_src.Cx - rot_src.gx_ref)
piv_py_exact = float(rot_src.Cy - rot_src.gy_ref)

for ang in [-25.0, -15.0, -5.0, 0.0, 5.0, 15.0, 25.0]:
    info = get_lean_gpu_transform_info(
        canvas_w=w, canvas_h=h, layout=layout, key="lean_indicator",
        value=ang, cfg=lean_cfg, min_dim=2160, fs=24, outline=2,
        thickness=4, size_px=size_px, ss=1
    )
    ang_ret, _, _, _, scr_piv_x, scr_piv_y, dst_x, dst_y, tw, th = info

    # 1. CPU isolated bike render (Pillow AFFINE)
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

    # 2. GPU render with exact pivot
    c_clear = ctypes.c_double(0.0)
    native_dll.telem_amd_clear_previous_above_map(ctx, ctypes.byref(c_clear))

    native_dll.telem_amd_set_lean_transform(
        ctx, ctypes.c_float(ang), ctypes.c_float(piv_px_exact), ctypes.c_float(piv_py_exact),
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
    assert ok

    gpu_bike = Image.frombuffer("RGBA", (tw, th), bytes(buf), "raw", "RGBA", 0, 1)

    arr_c = np.asarray(cpu_bike).astype(np.float32)
    arr_g = np.asarray(gpu_bike).astype(np.float32)

    diff = np.abs(arr_g - arr_c)
    max_d = np.max(diff)
    mae = np.mean(diff)

    def get_c(a):
        al = a[:, :, 3].astype(float)
        t = np.sum(al)
        if t == 0: return 0, 0
        ys, xs = np.indices(al.shape)
        return np.sum(xs * al) / t, np.sum(ys * al) / t

    cxc, cyc = get_c(arr_c)
    cxg, cyg = get_c(arr_g)
    shift = math.hypot(cxg - cxc, cyg - cyc)

    print(f"Angle {ang:+6.1f}° | MaxDiff = {max_d:5.1f} | MAE = {mae:6.3f} | Centroid shift = {shift:.4f} px (CPU: {cxc:.2f},{cyc:.2f} vs GPU: {cxg:.2f},{cyg:.2f})")

native_dll.telem_amd_close(ctx)
