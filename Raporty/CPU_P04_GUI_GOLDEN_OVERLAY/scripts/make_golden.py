"""Freeze the CPU P0.4 Golden HUD for GX010370 frame 1050 from a golden_run directory.

Stores the pre-compression export HUD (8-bit RGBA, lossless PNG, stored 180-degree
orientation and upright copy), the telemetry record, and a manifest with hashes of
all inputs.  Usage: make_golden.py <golden_run_dir> <golden_dir>
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

run, gold = Path(sys.argv[1]), Path(sys.argv[2])
gold.mkdir(parents=True, exist_ok=True)
W, H = 3840, 2160


def sha(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        n = 0
        while chunk := f.read(1 << 22):
            h.update(chunk)
            n += len(chunk)
            if limit and n >= limit:
                break
    return h.hexdigest()


x = np.fromfile(run / "export_hud_f150.rgba", dtype=np.uint8).reshape(H, W, 4)
x = x.copy()
x[x[..., 3] == 0] = 0
Image.fromarray(x, "RGBA").save(gold / "hud_f1050_precompression_stored_rot180.png")
Image.fromarray(x[::-1, ::-1].copy(), "RGBA").save(gold / "hud_f1050_precompression_upright.png")
shutil.copy2(run / "telemetry_f1050.json", gold / "telemetry_f1050.json")
for n in ("LOSSLESS_f150_hable_sdr.png",):
    shutil.copy2(gold.parent / "golden" / "control" / n, gold / n) if (gold.parent / "golden" / "control" / n).exists() and gold != gold.parent / "golden" else None

head = subprocess.run(["git", "-C", r"C:\_DEV\SportCamHUD", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
manifest = {
    "purpose": "CPU P0.4 Golden HUD (editor CPU HUD == export pre-compression HUD at this frame)",
    "video": {"path": r"D:\GoPro\GX010370.MP4", "bytes": Path(r"D:\GoPro\GX010370.MP4").stat().st_size,
              "sha256": sha(r"D:\GoPro\GX010370.MP4")},
    "fit": {"path": r"D:\GoPro\2026-10-13_15-02-49.fit", "sha256": sha(r"D:\GoPro\2026-10-13_15-02-49.fit")},
    "layout": {"path": r"C:\_DEV\SportCamHUD\def_layout.json", "sha256": sha(r"C:\_DEV\SportCamHUD\def_layout.json")},
    "frame": {"export_index": 150, "start_frame": 900, "absolute_frame": 1050, "fps": "30000/1001",
              "canvas": [W, H], "source_rotation": 180},
    "git_head_at_capture": head, "git_note": "working tree had uncommitted changes at capture",
    "hud_rgba_sha256_stored": hashlib.sha256(x.tobytes()).hexdigest(),
    "hud_rgba_sha256_upright": hashlib.sha256(x[::-1, ::-1].tobytes()).hexdigest(),
    "pixel_format": "RGBA8, straight alpha with RGB zeroed where alpha==0",
    "capture_command": ("python SportCamHUD.py --test-cpu-export --mode direct --video D:\\GoPro\\GX010370.MP4 "
                        "--fit D:\\GoPro\\2026-10-13_15-02-49.fit --layout def_layout.json --start-frame 900 "
                        "--frames 160 --profile fast --cpu-rate-mode crf --golden-dir <dir> --golden-frame 150 "
                        "with TELEM_CPU_DIAG_DUMP_FRAMES=150 TELEM_CPU_DIAG_DUMP_DIR=<dir>"),
}
(gold / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
print(json.dumps(manifest, indent=1))
