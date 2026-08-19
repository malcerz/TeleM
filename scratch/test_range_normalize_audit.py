"""Audit NormalizeD3D11VARangeNV12 mathematics, ranges, and behavior."""
import sys
import numpy as np

def scale_luma(y: int) -> int:
    return min(235, ((219 * y + 127) // 255) + 16)

def scale_chroma(val: int) -> int:
    centered = val - 128
    if centered >= 0:
        scaled = (centered * 224 + 127) // 255
    else:
        scaled = (centered * 224 - 127) // 255
    return max(0, min(255, 128 + scaled))

def pass1_y(y):
    return scale_luma(y)

def pass2_y(y):
    return scale_luma(scale_luma(y))

def pass1_uv(uv):
    return scale_chroma(uv)

def pass2_uv(uv):
    return scale_chroma(scale_chroma(uv))

print("=== LUMA Y MAPPING ===")
for y in [0, 16, 64, 128, 192, 235, 255]:
    p1 = pass1_y(y)
    p2 = pass2_y(y)
    print(f"Input Y={y:3d} -> Pass 1 Y={p1:3d} -> Pass 2 Y={p2:3d}")

print("\n=== CHROMA UV MAPPING ===")
for uv in [0, 16, 64, 128, 192, 240, 255]:
    p1 = pass1_uv(uv)
    p2 = pass2_uv(uv)
    print(f"Input UV={uv:3d} -> Pass 1 UV={p1:3d} -> Pass 2 UV={p2:3d}")
