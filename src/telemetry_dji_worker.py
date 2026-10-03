"""Standalone worker process for DJI telemetry parsing.

Runs outside the Qt GUI process so that AdrianEddy/telemetry-parser
(which executes native code without releasing the Python GIL) does not
starve the Qt main thread or cause Windows '(Not Responding)' freezes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import src.telemetry_dji as td


class WorkerHeartbeat:
    """Sends periodic heartbeats to stdout every interval_s seconds."""

    def __init__(self, interval_s: float = 0.5):
        self.interval_s = interval_s
        self.current_stage = "init"
        self.started_at = time.perf_counter()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_stage(self, stage: str) -> None:
        self.current_stage = stage

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_s):
            elapsed = time.perf_counter() - self.started_at
            print(
                f"DJI_WORKER_ALIVE=yes elapsed={elapsed:.1f}s stage={self.current_stage}",
                flush=True,
            )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


def parse_and_cache(video_path: Path, cache_path: Path | None = None) -> dict[str, Any]:
    """Parse DJI telemetry from video_path and save to cache_path atomically."""
    print("[DJI WORKER] stage=init start", flush=True)
    hb = WorkerHeartbeat(interval_s=0.5)
    hb.start()
    try:
        # 1. stage=parser_init
        hb.set_stage("parser_init")
        print("DJI_WORKER_STAGE stage=parser_init", flush=True)
        print("[DJI LOAD] stage=parser_init start", flush=True)
        t0 = time.perf_counter()
        parser = td._parser_module().Parser(str(video_path))
        parser_init_ms = (time.perf_counter() - t0) * 1000.0
        print(f"[DJI LOAD] stage=parser_init end wall_time={parser_init_ms:.1f}ms", flush=True)
        print(f"PARSER_INIT_MS={parser_init_ms:.1f}", flush=True)

        if parser.camera != "DJI":
            raise RuntimeError(f"Expected DJI metadata, parser reported {parser.camera!r}")

        # 2. stage=telemetry
        hb.set_stage("telemetry")
        print("DJI_WORKER_STAGE stage=telemetry", flush=True)
        print("[DJI LOAD] stage=telemetry start", flush=True)
        t0 = time.perf_counter()
        groups = parser.telemetry()
        telemetry_ms = (time.perf_counter() - t0) * 1000.0
        print(f"[DJI LOAD] stage=telemetry end wall_time={telemetry_ms:.1f}ms", flush=True)
        print(f"TELEMETRY_MS={telemetry_ms:.1f}", flush=True)

        # 3. stage=normalized_imu
        hb.set_stage("normalized_imu")
        print("DJI_WORKER_STAGE stage=normalized_imu", flush=True)
        print("[DJI LOAD] stage=normalized_imu start", flush=True)
        t0 = time.perf_counter()
        imu = parser.normalized_imu()
        normalized_imu_ms = (time.perf_counter() - t0) * 1000.0
        print(f"[DJI LOAD] stage=normalized_imu end wall_time={normalized_imu_ms:.1f}ms", flush=True)
        print(f"NORMALIZED_IMU_MS={normalized_imu_ms:.1f}", flush=True)

        # 4. stage=convert
        hb.set_stage("convert")
        print("DJI_WORKER_STAGE stage=convert", flush=True)
        print("[DJI LOAD] stage=convert start", flush=True)
        t0 = time.perf_counter()
        gyro_rows = []
        accel_rows = []
        for sample in imu:
            if not isinstance(sample, dict):
                continue
            stamp = float(sample["timestamp_ms"]) / 1000.0
            gyro = sample.get("gyro")
            accel = sample.get("accl")
            if gyro is not None and len(gyro) == 3:
                gyro_rows.append((stamp, *(math.radians(float(v)) for v in gyro)))
            if accel is not None and len(accel) == 3:
                accel_rows.append((stamp, *(float(v) for v in accel)))

        quats = td._quaternions(groups)
        metadata = {}
        for group in groups:
            if isinstance(group, dict):
                metadata = (group.get("Default") or {}).get("Metadata") or {}
                if metadata:
                    break

        data = {
            "gyro": np.asarray(gyro_rows, dtype=np.float64).reshape(-1, 4),
            "accel": np.asarray(accel_rows, dtype=np.float64).reshape(-1, 4),
            "quaternion": quats,
            "camera": parser.camera,
            "model": parser.model,
            "camera_metadata": metadata,
            "cache_hit": False,
        }
        convert_ms = (time.perf_counter() - t0) * 1000.0
        print(f"[DJI LOAD] stage=convert end wall_time={convert_ms:.1f}ms", flush=True)
        print(f"QUATERNION_CONVERT_MS={convert_ms:.1f}", flush=True)

        # 5. stage=cache_write
        hb.set_stage("cache_write")
        print("DJI_WORKER_STAGE stage=cache_write", flush=True)
        print("[DJI LOAD] stage=cache_write start", flush=True)
        t0 = time.perf_counter()
        final_cache_path = td._write_cache(video_path, data, cache_path=cache_path)
        cache_write_ms = (time.perf_counter() - t0) * 1000.0
        print(f"[DJI LOAD] stage=cache_write end wall_time={cache_write_ms:.1f}ms", flush=True)
        print(f"NPZ_WRITE_MS={cache_write_ms:.1f}", flush=True)

        hb.set_stage("done")
        print("DJI_WORKER_STAGE stage=done", flush=True)
        print(
            f"DJI_WORKER_DONE cache_path={final_cache_path} camera={parser.camera} "
            f"model={parser.model} gyro={len(gyro_rows)} accel={len(accel_rows)} "
            f"quaternion={len(quats)}",
            flush=True,
        )
        return {
            "status": "ok",
            "cache_path": str(final_cache_path),
            "camera": parser.camera,
            "model": parser.model,
            "gyro_count": len(gyro_rows),
            "accel_count": len(accel_rows),
            "quaternion_count": len(quats),
            "timings_ms": {
                "parser_init_ms": parser_init_ms,
                "telemetry_ms": telemetry_ms,
                "normalized_imu_ms": normalized_imu_ms,
                "convert_ms": convert_ms,
                "cache_write_ms": cache_write_ms,
            },
        }
    finally:
        hb.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="DJI Telemetry Worker Process")
    parser.add_argument("--video", required=True, help="Path to DJI MP4 video")
    parser.add_argument("--cache-path", default=None, help="Target cache file path")
    args = parser.parse_args()

    video_path = Path(args.video)
    cache_path = Path(args.cache_path) if args.cache_path else None

    if not video_path.is_file():
        print(f"[DJI WORKER] error=File not found: {video_path}", file=sys.stderr, flush=True)
        print(f"[DJI WORKER] exit_code=2", flush=True)
        return 2

    try:
        result = parse_and_cache(video_path, cache_path)
        print(json.dumps(result), flush=True)
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        err_msg = str(exc) or exc.__class__.__name__
        print(f"[DJI WORKER] error={err_msg}", file=sys.stderr, flush=True)
        print(f"[DJI WORKER] exit_code=1", flush=True)
        print(json.dumps({"status": "error", "error": err_msg}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
