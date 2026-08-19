"""Synthetic map quadrant test to prove full area survival across upload and blend."""
import os
import sys
import ctypes
from ctypes import byref, c_int, c_uint64, c_uint8, c_uint, c_void_p, c_char_p
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

def test_synthetic_quadrants():
    w, h = 692, 692
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:h//2, :w//2] = [0, 255, 0, 255]       # TL = Green
    arr[:h//2, w//2:] = [255, 255, 0, 255]     # TR = Yellow
    arr[h//2:, :w//2] = [255, 0, 0, 255]       # BL = Red
    arr[h//2:, w//2:] = [0, 0, 255, 255]       # BR = Blue
    
    synth_img = Image.fromarray(arr, "RGBA")
    diag_dir = root / "scratch" / "quadrant_diag"
    diag_dir.mkdir(parents=True, exist_ok=True)
    synth_img.save(diag_dir / "01_synthetic_input.png")
    
    # Load native DLL
    os.add_dll_directory(r"C:\tools\mingw64\bin")
    dll_path = root / "native" / "d3d11_amf_pipeline" / "bin" / "telem_amd_native.dll"
    os.add_dll_directory(str(dll_path.parent))
    dll = ctypes.CDLL(str(dll_path))
    
    # Setup DLL function prototypes
    dll.telem_amd_create.restype = c_void_p
    dll.telem_amd_create.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, c_uint, c_uint, c_uint, c_uint]
    
    dll.telem_amd_set_map_mode.restype = c_int
    dll.telem_amd_set_map_mode.argtypes = [c_void_p, c_int]
    
    dll.telem_amd_set_map_geometry.restype = c_int
    dll.telem_amd_set_map_geometry.argtypes = [c_void_p, c_uint, c_uint, c_uint, c_uint, c_uint, c_uint]
    
    dll.telem_amd_update_map.restype = c_int
    dll.telem_amd_update_map.argtypes = [c_void_p, c_char_p, c_uint, c_uint, c_uint, ctypes.POINTER(c_uint64), ctypes.POINTER(c_int)]
    
    dll.telem_amd_set_above_map_mode.restype = c_int
    dll.telem_amd_set_above_map_mode.argtypes = [c_void_p, c_int]
    
    dll.telem_amd_update_above_map.restype = c_int
    dll.telem_amd_update_above_map.argtypes = [c_void_p, c_char_p, c_uint, c_uint, c_uint, c_uint, c_uint, c_int]
    
    dll.telem_amd_process_frame.restype = c_int
    dll.telem_amd_process_frame.argtypes = [c_void_p, c_uint, c_uint64, c_uint, c_int, c_void_p]
    
    dll.telem_amd_get_map_resample.restype = c_int
    dll.telem_amd_get_map_resample.argtypes = [c_void_p, ctypes.POINTER(c_uint8), c_uint]
    
    dll.telem_amd_close.restype = None
    dll.telem_amd_close.argtypes = [c_void_p]
    
    # Create context at 3840x2160
    ctx = dll.telem_amd_create(None, None, 3840, 2160, 30000, 1001)
    assert ctx, "Failed to create TelemAMDContext"
    
    dll.telem_amd_set_map_mode(ctx, 1)
    # dst=(3035, 137), src=692x692, out=691x691
    dll.telem_amd_set_map_geometry(ctx, 3035, 137, 692, 692, 691, 691)
    
    # Upload synthetic map
    uploaded_bytes = c_uint64(0)
    tex_created = c_int(0)
    raw_bytes = synth_img.tobytes("raw", "RGBA")
    ok = dll.telem_amd_update_map(ctx, raw_bytes, 692, 692, 692 * 4, byref(uploaded_bytes), byref(tex_created))
    assert ok, "telem_amd_update_map failed"
    
    # Simulate an overlapping CPU_ABOVE_MAP layer with mostly transparent pixels and a small text
    # spanning over the map region [3000, 100, 800, 800]
    above_arr = np.zeros((800, 800, 4), dtype=np.uint8)
    above_arr[50:80, 200:400] = [255, 255, 255, 255]  # A small white text box at top
    above_img = Image.fromarray(above_arr, "RGBA")
    above_bytes = above_img.tobytes("raw", "RGBA")
    
    dll.telem_amd_set_above_map_mode(ctx, 1)
    dll.telem_amd_update_above_map(ctx, above_bytes, 800, 800, 800 * 4, 3000, 100, 1)
    
    # Process 1 frame (without video input, HUD/map composite test)
    dll.telem_amd_process_frame(ctx, 0, 0, 0, 1, None)
    
    # Read back 691x691 map from HUD canvas
    readback_buf = (c_uint8 * (691 * 691 * 4))()
    ok = dll.telem_amd_get_map_resample(ctx, readback_buf, 691 * 4)
    assert ok, "telem_amd_get_map_resample failed"
    
    rb_arr = np.frombuffer(readback_buf, dtype=np.uint8).reshape((691, 691, 4))
    rb_img = Image.fromarray(rb_arr, "RGBA")
    rb_img.save(diag_dir / "02_synthetic_readback.png")
    
    dll.telem_amd_close(ctx)
    
    # Check all 4 quadrants in readback:
    tl = rb_arr[100, 100]  # Should be Green (0, 255, 0, 255)
    tr = rb_arr[100, 500]  # Should be Yellow (255, 255, 0, 255)
    bl = rb_arr[500, 100]  # Should be Red (255, 0, 0, 255)
    br = rb_arr[500, 500]  # Should be Blue (0, 0, 255, 255)
    
    print(f"Readback Top-Left:     RGBA={tl} (expected ~Green [0, 255, 0, 255])")
    print(f"Readback Top-Right:    RGBA={tr} (expected ~Yellow [255, 255, 0, 255])")
    print(f"Readback Bottom-Left:  RGBA={bl} (expected ~Red [255, 0, 0, 255])")
    print(f"Readback Bottom-Right: RGBA={br} (expected ~Blue [0, 0, 255, 255])")
    
    # Assert alpha is 255 across all quadrants (NOT 0, not erased!)
    assert tl[3] > 200, f"Top-left erased: {tl}"
    assert tr[3] > 200, f"Top-right erased: {tr}"
    assert bl[3] > 200, f"Bottom-left erased: {bl}"
    assert br[3] > 200, f"Bottom-right erased: {br}"
    print("ALL 4 QUADRANTS SURVIVED WITH FULL ALPHA: PASS!")

if __name__ == "__main__":
    test_synthetic_quadrants()
