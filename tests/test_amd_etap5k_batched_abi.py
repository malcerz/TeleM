"""Unit tests for AMD ETAP 5K Batched Native Dirty Regions ABI, edge cases, and safety bounds."""

import pytest
import os
import ctypes
from ctypes import c_void_p, c_uint, c_int, POINTER, c_uint8, c_double, byref
from pathlib import Path
from PIL import Image

from src.ffmpeg.amd_native_exporter import HUDDirtyRect

def test_hud_dirty_rect_layout():
    assert ctypes.sizeof(HUDDirtyRect) == 16
    r = HUDDirtyRect(x=10, y=20, width=300, height=400)
    assert r.x == 10
    assert r.y == 20
    assert r.width == 300
    assert r.height == 400

def test_batched_regions_null_safety():
    dll_path = Path("native/d3d11_amf_pipeline/bin/telem_amd_native.dll").resolve()
    if not dll_path.exists():
        pytest.skip("telem_amd_native.dll not built.")

    if hasattr(os, "add_dll_directory") and os.path.exists("C:/tools/mingw64/bin"):
        os.add_dll_directory("C:/tools/mingw64/bin")

    dll = ctypes.CDLL(str(dll_path))
    dll.telem_amd_update_above_regions_batch.restype = c_int
    dll.telem_amd_update_above_regions_batch.argtypes = [
        c_void_p, POINTER(c_void_p), c_uint, POINTER(HUDDirtyRect), c_uint
    ]

    # Null handle
    assert dll.telem_amd_update_above_regions_batch(None, None, 0, None, 0) == 0
    # Null row table
    rects = (HUDDirtyRect * 1)(HUDDirtyRect(0, 0, 10, 10))
    assert dll.telem_amd_update_above_regions_batch(c_void_p(12345), None, 1920 * 4, rects, 1) == 0
    # Null rects
    assert dll.telem_amd_update_above_regions_batch(c_void_p(12345), c_void_p(12345), 1920 * 4, None, 1) == 0
    # Stride = 0
    assert dll.telem_amd_update_above_regions_batch(c_void_p(12345), c_void_p(12345), 0, rects, 1) == 0

def test_batched_regions_edge_geometries():
    dll_path = Path("native/d3d11_amf_pipeline/bin/telem_amd_native.dll").resolve()
    if not dll_path.exists():
        pytest.skip("telem_amd_native.dll not built.")

    if hasattr(os, "add_dll_directory") and os.path.exists("C:/tools/mingw64/bin"):
        os.add_dll_directory("C:/tools/mingw64/bin")

    dll = ctypes.CDLL(str(dll_path))
    dll.telem_amd_create.restype = c_void_p
    dll.telem_amd_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p, c_uint, c_uint, c_uint, c_uint]
    dll.telem_amd_close.restype = c_int
    dll.telem_amd_close.argtypes = [c_void_p]
    dll.telem_amd_set_above_map_mode.restype = c_int
    dll.telem_amd_set_above_map_mode.argtypes = [c_void_p, c_int]
    dll.telem_amd_update_above_regions_batch.restype = c_int
    dll.telem_amd_update_above_regions_batch.argtypes = [
        c_void_p, POINTER(c_void_p), c_uint, POINTER(HUDDirtyRect), c_uint
    ]

    h_context = dll.telem_amd_create(b"Video/GX020079.MP4", b"scratch/bench_tmp.mp4", 3840, 2160, 30000, 1000)
    assert h_context is not None
    dll.telem_amd_set_above_map_mode(h_context, 1)

    img = Image.new("RGBA", (3840, 2160), (255, 0, 0, 255))
    img.load()
    ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
    ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
    ctypes.pythonapi.PyCapsule_GetName.restype = ctypes.c_char_p
    ctypes.pythonapi.PyCapsule_GetName.argtypes = [ctypes.py_object]
    cap_name = ctypes.pythonapi.PyCapsule_GetName(img.im.ptr)
    raw_ptr = ctypes.pythonapi.PyCapsule_GetPointer(img.im.ptr, cap_name)
    row_table_ptr = ctypes.c_void_p.from_address(raw_ptr + 40).value
    row_table_ptr_c = ctypes.cast(row_table_ptr, POINTER(c_void_p))
    canvas_stride = 3840 * 4

    test_edge_cases = [
        ("1 rect at (0,0)", [(0, 0, 100, 100)]),
        ("2 rects", [(0, 0, 50, 50), (100, 100, 50, 50)]),
        ("6 rects", [(10, 10, 40, 40), (60, 10, 40, 40), (110, 10, 40, 40), (160, 10, 40, 40), (210, 10, 40, 40), (260, 10, 40, 40)]),
        ("8 rects max", [(i * 50, 20, 40, 40) for i in range(8)]),
        ("right edge", [(3740, 100, 100, 100)]),
        ("1x1 pixel rect", [(500, 500, 1, 1)]),
        ("count > MAX (12 rects)", [(i * 30, 50, 20, 20) for i in range(12)]),
    ]

    for label, rect_list in test_edge_cases:
        buf = (HUDDirtyRect * len(rect_list))()
        for i, (rx, ry, rw, rh) in enumerate(rect_list):
            buf[i].x = rx
            buf[i].y = ry
            buf[i].width = rw
            buf[i].height = rh
        ok = dll.telem_amd_update_above_regions_batch(h_context, row_table_ptr_c, canvas_stride, buf, len(rect_list))
        assert ok == 1, f"Failed on edge case: {label}"

    dll.telem_amd_close(h_context)
