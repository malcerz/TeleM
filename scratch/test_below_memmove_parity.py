import sys
import ctypes
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

def get_row_table_ptr(img: Image.Image):
    if hasattr(img, "im") and hasattr(img.im, "ptr"):
        try:
            ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
            ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
            ctypes.pythonapi.PyCapsule_GetName.restype = ctypes.c_char_p
            ctypes.pythonapi.PyCapsule_GetName.argtypes = [ctypes.py_object]
            cap_name = ctypes.pythonapi.PyCapsule_GetName(img.im.ptr)
            raw_ptr = ctypes.pythonapi.PyCapsule_GetPointer(img.im.ptr, cap_name)
            if raw_ptr:
                return ctypes.c_void_p.from_address(raw_ptr + 40).value
        except Exception:
            return None
    return None

w, h = 3840, 2160
img = Image.new("RGBA", (w, h), (10, 20, 30, 255))
d = ImageDraw.Draw(img)
d.rectangle((500, 500, 1000, 1000), fill=(255, 128, 64, 255))

# Target backing array
backing = np.zeros((h, w, 4), dtype=np.uint8)
backing_addr = backing.ctypes.data

# Dirty rect
rx, ry, rw, rh = 500, 500, 500, 500
stride = w * 4

# Old method
slice_img = img.crop((rx, ry, rx + rw, ry + rh))
slice_bytes = slice_img.tobytes("raw", "RGBA")
r_arr = np.frombuffer(slice_bytes, dtype=np.uint8).reshape(rh, rw, 4)
backing_old = np.zeros((h, w, 4), dtype=np.uint8)
np.copyto(backing_old[ry:ry + rh, rx:rx + rw], r_arr)

# New method: direct memmove
row_table = get_row_table_ptr(img)
top_row = ctypes.c_void_p.from_address(row_table).value
src_base = top_row + ry * stride + rx * 4
dst_base = backing_addr + ry * stride + rx * 4
for r in range(rh):
    ctypes.memmove(dst_base + r * stride, src_base + r * stride, rw * 4)

assert np.array_equal(backing, backing_old)
print("Below HUD Direct Memmove Dirty Rect Test: SUCCESS! Exact pixel match!")
