from __future__ import annotations

import json
from pathlib import Path
import numpy as np

from validate_etap5c_direct import setup
from src.ffmpeg.frame_renderer import render_overlay_frame
from src.ffmpeg.worker_cache import WORKER_CACHE

ROOT = Path(__file__).resolve().parent.parent


def main():
    layout, regions, anchor, speed, track, alt = setup()
    WORKER_CACHE["hud_rotate_180"] = True
    result = {}
    for idx in [0, 540, 1350, 2700, 4050, 4860, 5399]:
        layout["_nvidia_direct_region"] = False; WORKER_CACHE.pop("_prev_frame_data", None); WORKER_CACHE.pop("_prev_atlas_img", None)
        legacy = render_overlay_frame(idx, anchor, 2, speed, track, alt, 30000/1001, 1)
        layout["_nvidia_direct_region"] = True; WORKER_CACHE.pop("_prev_frame_data", None); WORKER_CACHE.pop("_prev_atlas_img", None)
        direct = render_overlay_frame(idx, anchor, 2, speed, track, alt, 30000/1001, 1)
        diff = np.abs(np.asarray(legacy).astype(np.int16) - np.asarray(direct).astype(np.int16))
        result[str(idx)] = {"max_diff": int(diff.max()), "different_pixels": int(np.any(diff != 0, axis=2).sum())}
    (ROOT / "scratch" / "etap5c_rot180_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
