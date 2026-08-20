"""ETAP 5G real-layout microbenchmark for the SHM render target."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, N, setup
from src.ffmpeg.shared_memory import (
    SharedFramePool, _close_shm_in_worker, _init_shm_in_worker,
    render_frame_shm_job,
)
import src.ffmpeg.shared_memory as shm_module
from src.ffmpeg.worker_cache import WORKER_CACHE


def percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


def run(label: str, zero_copy: bool, count: int = 2000) -> dict:
    os.environ["TELEM_ZERO_COPY_SHM"] = "1" if zero_copy else "0"
    WORKER_CACHE.pop("_prev_frame_data", None)
    WORKER_CACHE.pop("_prev_atlas_img", None)
    results: list[tuple] = []
    wall_ns: list[int] = []
    # Warm up font caches, Pillow and the mapped-buffer adapter.
    for index in range(30):
        render_frame_shm_job((index, 0, True))
    for index in range(count):
        started = time.perf_counter_ns()
        result = render_frame_shm_job((index, 0, True))
        wall_ns.append(time.perf_counter_ns() - started)
        results.append(result)

    def ms(values: list[int]) -> dict[str, float]:
        converted = [value / 1e6 for value in values]
        return {
            "avg": statistics.fmean(converted),
            "median": statistics.median(converted),
            "p95": percentile(converted, 0.95),
        }

    render = [r[5] - r[4] for r in results]
    clear = [r[8] - r[7] for r in results if r[7] is not None]
    transfer = [r[6] - r[5] for r in results]
    return {
        "label": label,
        "zero_copy": zero_copy,
        "frames": count,
        "render_ms": ms(render),
        "clear_ms": ms(clear) if clear else None,
        "shm_transfer_ms": ms(transfer),
        "worker_wall_ms": ms(wall_ns),
        "zero_copy_frames": sum(bool(r[9]) for r in results),
    }


def main() -> None:
    layout, regions, *_ = setup()
    atlas_w, atlas_h = layout["_nvidia_atlas_size"]
    frame_bytes = atlas_w * atlas_h * 4
    pool = SharedFramePool(1, frame_bytes)
    _init_shm_in_worker(pool.shm_names(), frame_bytes)
    try:
        before = run("copy_path", False)
        after = run("mapped_target", True)
    finally:
        os.environ.pop("TELEM_ZERO_COPY_SHM", None)
        _close_shm_in_worker()
        pool.close()
    output = {"atlas": [atlas_w, atlas_h], "regions": len(regions),
              "before": before, "after": after}
    destination = ROOT / "scratch" / "etap5g_target_benchmark.json"
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2), flush=True)


if __name__ == "__main__":
    main()
