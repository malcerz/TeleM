import sys
import ctypes
from ctypes import c_uint8, POINTER
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

# 1. Test Map unrotated direct pointer
map_w, map_h = 978, 978
map_img = Image.new("RGBA", (map_w, map_h), (50, 100, 150, 255))
d = ImageDraw.Draw(map_img)
d.rectangle((50, 50, 200, 200), fill=(255, 0, 0, 255))

row_table_map = get_row_table_ptr(map_img)
assert row_table_map is not None
top_row = ctypes.c_void_p.from_address(row_table_map).value
bottom_row = ctypes.c_void_p.from_address(row_table_map + (map_h - 1) * 8).value
map_stride = map_w * 4
assert bottom_row == top_row + (map_h - 1) * map_stride

# Compare full map bytes
read_buf = bytearray(map_w * map_h * 4)
for r in range(map_h):
    row_src = (c_uint8 * (map_w * 4)).from_address(top_row + r * map_stride)
    read_buf[r * map_w * 4 : (r + 1) * map_w * 4] = bytes(row_src)

assert bytes(read_buf) == map_img.tobytes("raw", "RGBA")
print("Map Direct Full Upload Pointer Test: SUCCESS!")

# 2. Test Below Canvas Dirty Rect Direct Pointer
canvas_w, canvas_h = 3840, 2160
canvas_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
d2 = ImageDraw.Draw(canvas_img)
d2.rectangle((100, 200, 500, 600), fill=(0, 255, 0, 128))

row_table_canvas = get_row_table_ptr(canvas_img)
assert row_table_canvas is not None
rx, ry, rw, rh = 100, 200, 400, 400
canvas_stride = canvas_w * 4
top_row = ctypes.c_void_p.from_address(row_table_canvas + ry * 8).value
bottom_row = ctypes.c_void_p.from_address(row_table_canvas + (ry + rh - 1) * 8).value
assert bottom_row == top_row + (rh - 1) * canvas_stride
region_ptr = top_row + rx * 4

read_buf2 = bytearray(rw * rh * 4)
for r in range(rh):
    row_src = (c_uint8 * (rw * 4)).from_address(region_ptr + r * canvas_stride)
    read_buf2[r * rw * 4 : (r + 1) * rw * 4] = bytes(row_src)

crop_bytes = canvas_img.crop((rx, ry, rx + rw, ry + rh)).tobytes("raw", "RGBA")
assert bytes(read_buf2) == crop_bytes
print("Below Canvas Direct Strided Dirty Rect Test: SUCCESS!")
