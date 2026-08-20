"""ETAP 5G proof/parity check on the real five-region production layout."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import setup
from src.ffmpeg.shared_memory import (
    SharedFramePool, _close_shm_in_worker, _init_shm_in_worker, render_frame_shm_job,
)
import src.ffmpeg.shared_memory as shm_module


def main() -> None:
    layout, regions, *_ = setup()
    atlas_w, atlas_h = layout["_nvidia_atlas_size"]
    frame_bytes = atlas_w * atlas_h * 4
    pool = SharedFramePool(1, frame_bytes)
    _init_shm_in_worker(pool.shm_names(), frame_bytes)
    results = {"atlas": [atlas_w, atlas_h], "regions": len(regions), "frames": {}}
    try:
        # 5000 is immediately before the ~1880 s FIT gap in this 180 s
        # source timeline; 5200 is inside that gap.  The first post-gap FIT
        # sample is outside the 5400-frame video and is covered by chart
        # segment unit tests instead.
        for index in (0, 540, 1350, 2700, 4050, 4860, 5000, 5200, 5399):
            os.environ["TELEM_ZERO_COPY_SHM"] = "0"
            np.frombuffer(shm_module._SHM_BLOCKS[0].buf, dtype=np.uint8,
                          count=frame_bytes).fill(0)
            before_result = render_frame_shm_job((index, 0, True))
            before = np.frombuffer(pool._shm_blocks[0].buf, dtype=np.uint8, count=frame_bytes).copy()

            os.environ["TELEM_ZERO_COPY_SHM"] = "1"
            np.frombuffer(shm_module._SHM_BLOCKS[0].buf, dtype=np.uint8,
                          count=frame_bytes).fill(0)
            after_result = render_frame_shm_job((index, 0, True))
            after = np.frombuffer(pool._shm_blocks[0].buf, dtype=np.uint8, count=frame_bytes).copy()
            diff = np.abs(before.astype(np.int16) - after.astype(np.int16))
            results["frames"][str(index)] = {
                "before": list(before_result), "after": list(after_result),
                "max_diff": int(diff.max()),
                "different_bytes": int(np.count_nonzero(diff)),
            }
    finally:
        os.environ.pop("TELEM_ZERO_COPY_SHM", None)
        _close_shm_in_worker()
        pool.close()
    destination = ROOT / "scratch" / "etap5g_poc.json"
    destination.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
