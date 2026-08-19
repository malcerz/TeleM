"""Trace all checkpoints from Python HUD to Final MP4."""
from PIL import Image
import numpy as np
from pathlib import Path

checkpoints = [
    ("01_python_hud_30.png", "Python Pillow composed_img"),
    ("02_buffer_sent_to_dll.png", "hud_backing_view sent to DLL"),
    ("H_hud_canvas_30.png", "GPU m_hudTexture canvas"),
    ("D_after_gpu_hud.png", "GPU NV12 after HUD compositor"),
    ("E_amf_input.png", "Texture submitted to AMF encoder"),
    ("F_final_mp4.png", "Final frame from MP4 stream"),
]

crops = {
    "time_block": (21, 22, 21 + 76, 22 + 46),
    "iso_text": (22, 300, 22 + 89, 300 + 17),
    "exposure_text": (22, 329, 22 + 84, 329 + 17),
    "temp_text": (21, 356, 21 + 106, 356 + 17),
    "solar_pct": (600, 50, 750, 80),
    "battery_pct": (1180, 50, 1270, 80),
}

for fname, desc in checkpoints:
    p = Path(fname)
    if not p.exists():
        print(f"[-] {fname} ({desc}) NOT FOUND")
        continue
    img = Image.open(p)
    print(f"\n[+] {fname} ({desc}) size={img.size} mode={img.mode}")
    for ind_name, bbox in crops.items():
        c = img.crop(bbox)
        arr = np.asarray(c)
        if img.mode == "RGBA":
            alpha_cnt = np.count_nonzero(arr[:, :, 3])
            print(f"    {ind_name:15s} bbox={bbox} non-zero alpha={alpha_cnt:4d} min_RGBA={arr.min(axis=(0,1))} max_RGBA={arr.max(axis=(0,1))}")
        else:
            dark_cnt = np.count_nonzero((arr[:, :, 0] < 40) & (arr[:, :, 1] < 40) & (arr[:, :, 2] < 40))
            bright_cnt = np.count_nonzero((arr[:, :, 0] > 220) & (arr[:, :, 1] > 220) & (arr[:, :, 2] > 220))
            print(f"    {ind_name:15s} bbox={bbox} dark_px={dark_cnt:4d} bright_px={bright_cnt:4d} min_RGB={arr.min(axis=(0,1))} max_RGB={arr.max(axis=(0,1))}")
