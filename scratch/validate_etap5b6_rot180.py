from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scratch"))

from validate_etap5b6_direct import setup
from src.ffmpeg.frame_renderer import render_overlay_frame
from src.ffmpeg.worker_cache import WORKER_CACHE


def main():
    layout, regions, anchor, speed, track, alt = setup()
    WORKER_CACHE["hud_rotate_180"] = True
    result = {}
    for idx in (0, 1350, 2700, 4050, 5399):
        WORKER_CACHE.pop("_prev_frame_data", None); WORKER_CACHE.pop("_prev_atlas_img", None)
        layout["_nvidia_direct_region"] = False
        legacy = render_overlay_frame(idx, anchor, 2, speed, track, alt, 30000 / 1001, 1)
        WORKER_CACHE.pop("_prev_frame_data", None); WORKER_CACHE.pop("_prev_atlas_img", None)
        layout["_nvidia_direct_region"] = True
        direct = render_overlay_frame(idx, anchor, 2, speed, track, alt, 30000 / 1001, 1)
        diff = np.abs(np.asarray(legacy).astype(np.int16) - np.asarray(direct).astype(np.int16))
        result[str(idx)] = {"max_diff": int(diff.max()), "different_pixels": int(np.any(diff != 0, axis=2).sum())}
    (ROOT / "scratch" / "etap5b6_rot180_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
