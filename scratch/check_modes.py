"""Analyze Mode 2 and Mode 3 frame 30."""
import numpy as np
from pathlib import Path

root = Path("c:/_DEV/TeleM")

def read_nv12(yuv_path: str, width: int = 3840, height: int = 2160):
    raw = open(yuv_path, "rb").read()
    y_size = width * height
    uv_size = width * height // 2
    y_plane = np.frombuffer(raw[:y_size], dtype=np.uint8).reshape((height, width))
    uv_raw = np.frombuffer(raw[y_size:y_size + uv_size], dtype=np.uint8).reshape((height // 2, width // 2, 2))
    u_plane = uv_raw[:, :, 0]
    v_plane = uv_raw[:, :, 1]
    return y_plane, u_plane, v_plane

for mode in [2, 3]:
    p = root / "scratch" / "diag_vp_raw_frame_30.yuv"
    # Let's see what's in p
    y, u, v = read_nv12(str(p))
    print(f"Mode {mode} (last run): Y min={np.min(y)}, max={np.max(y)}, mean={np.mean(y):.2f}, med={np.median(y)}")
