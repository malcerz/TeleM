from __future__ import annotations

import json
import time
from pathlib import Path

from validate_etap5c_direct import setup, N, FPS
from src.ffmpeg.frame_renderer import render_overlay_frame
from src.ffmpeg.worker_cache import WORKER_CACHE

ROOT = Path(__file__).resolve().parent.parent


def main():
    layout, regions, anchor, speed, track, alt = setup()
    WORKER_CACHE.pop("_prev_frame_data", None); WORKER_CACHE.pop("_prev_atlas_img", None)
    t0 = time.perf_counter(); frames = 0; cache_hits = 0
    previous = None
    for idx in range(N):
        img = render_overlay_frame(idx, anchor, 2, speed, track, alt, FPS, 1)
        frames += 1
        if previous is img: cache_hits += 1
        previous = img
        if img.size != tuple(layout["_nvidia_atlas_size"]): raise AssertionError((idx, img.size))
    result = {"frames": frames, "cache_hits": cache_hits, "elapsed_s": time.perf_counter()-t0, "atlas": list(layout["_nvidia_atlas_size"]), "regions": [list(r) for r in regions]}
    (ROOT / "scratch" / "etap5c_full_timeline.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
