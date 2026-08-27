from PIL import Image
import numpy as np

# Load and inspect for angle 0 and 15
import ctypes, json, os, sys
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

for ang in [0.0, 15.0]:
    cfg_cpu = dict(lean_cfg)
    cfg_cpu["_skip_dynamic_graphic"] = False
    img_cpu, x_cpu, y_cpu, _ = _render_lean_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path="arial.ttf",
        key="lean_indicator", value=ang, unit="°", label="LEAN",
        cfg=cfg_cpu, min_dim=2160, outline=2, fs=24, font=None,
        val_min=-30.0, val_max=30.0, ticks=5, thickness=4, size_px=size_px, ss=1
    )

    info = get_lean_gpu_transform_info(
        canvas_w=w, canvas_h=h, layout=layout, key="lean_indicator",
        value=ang, cfg=lean_cfg, min_dim=2160, fs=24, outline=2,
        thickness=4, size_px=size_px, ss=1
    )
    ang_ret, _, piv_px, piv_py, scr_piv_x, scr_piv_y, dst_x, dst_y, tw, th = info

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
    assert ok

    gpu_crop = Image.frombuffer("RGBA", (tw, th), bytes(buf), "raw", "RGBA", 0, 1)

    full_cpu = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    full_cpu.alpha_composite(img_cpu, (x_cpu, y_cpu))
    cpu_crop = full_cpu.crop((dst_x, dst_y, dst_x + tw, dst_y + th))

    gpu_crop.save(f"scratch/etap2g_bench/direct_gpu_ang{int(ang)}.png")
    cpu_crop.save(f"scratch/etap2g_bench/direct_cpu_ang{int(ang)}.png")

    arr_g = np.asarray(gpu_crop)
    arr_c = np.asarray(cpu_crop)

    # find bbox of non-zero alpha
    yg, xg = np.where(arr_g[:, :, 3] > 0)
    yc, xc = np.where(arr_c[:, :, 3] > 0)

    print(f"\n--- ANGLE {ang}° ---")
    if len(xg):
        print(f"GPU non-zero alpha bbox in crop: x=[{xg.min()}, {xg.max()}], y=[{yg.min()}, {yg.max()}], center=({xg.mean():.2f}, {yg.mean():.2f})")
    if len(xc):
        print(f"CPU non-zero alpha bbox in crop: x=[{xc.min()}, {xc.max()}], y=[{yc.min()}, {yc.max()}], center=({xc.mean():.2f}, {yc.mean():.2f})")

native_dll.telem_amd_close(ctx)
