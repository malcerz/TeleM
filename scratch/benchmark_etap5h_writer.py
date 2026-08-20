"""ETAP 5H pipe-only writer syscall A/B on the unchanged FFmpeg graph."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from multiprocessing import shared_memory
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.etap5f_ceilings import ATLAS, FPS, N, VIDEO, ffmpeg_filter


def command():
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda", "-i", str(VIDEO), "-f", "rawvideo",
        "-pix_fmt", "rgba", "-s", f"{ATLAS[0]}x{ATLAS[1]}", "-r", str(FPS), "-i", "pipe:0",
        "-filter_complex", ffmpeg_filter(), "-map", "[vout]", "-frames:v", str(N),
        "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
        "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0", "-f", "null", "-",
    ]


def write_one(mode: str, process, view: memoryview) -> tuple[int, int]:
    requested = len(view)
    if mode == "buffered":
        returned = process.stdin.write(view)
        return int(returned), 1
    if mode in {"raw", "unbuffered"}:
        stream = process.stdin.raw if mode == "raw" else process.stdin
        offset = 0
        calls = 0
        while offset < requested:
            count = stream.write(view[offset:])
            if count is None or count <= 0:
                raise OSError("raw write made no progress")
            offset += int(count)
            calls += 1
        return offset, calls
    if mode == "os_write":
        fd = process.stdin.fileno()
        offset = 0
        calls = 0
        while offset < requested:
            count = os.write(fd, view[offset:])
            if count <= 0:
                raise OSError("os.write made no progress")
            offset += int(count)
            calls += 1
        return offset, calls
    raise ValueError(mode)


def run(mode: str, run_no: int, frames: int = N) -> dict:
    frame_bytes = ATLAS[0] * ATLAS[1] * 4
    shm = shared_memory.SharedMemory(create=True, size=frame_bytes)
    view = shm.buf[:frame_bytes]
    view.cast("B")[:] = b"\0" * frame_bytes
    bufsize = 0 if mode == "unbuffered" else -1
    process = subprocess.Popen(
        command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, bufsize=bufsize,
    )
    started = time.perf_counter()
    returned_total = 0
    calls_total = 0
    try:
        for _ in range(frames):
            returned, calls = write_one(mode, process, view)
            returned_total += returned
            calls_total += calls
        process.stdin.close()
        stderr = process.stderr.read()
        process.wait()
    finally:
        try:
            view.release()
        except Exception:
            pass
        shm.close()
        shm.unlink()
    elapsed = time.perf_counter() - started
    if process.returncode:
        raise RuntimeError(stderr.decode(errors="replace")[-2000:])
    requested_total = frames * frame_bytes
    return {
        "mode": mode,
        "run": run_no,
        "frames": frames,
        "elapsed_s": elapsed,
        "fps": frames / elapsed,
        "buffer_type": type(process.stdin).__name__,
        "bufsize": bufsize,
        "requested_bytes": requested_total,
        "returned_bytes": returned_total,
        "write_calls": calls_total,
        "partial": returned_total != requested_total,
    }


def main() -> None:
    results = {}
    for mode in ("buffered", "raw", "os_write", "unbuffered"):
        rows = [run(mode, i) for i in range(1, 4)]
        results[mode] = {"runs": rows, "median_fps": statistics.median(r["fps"] for r in rows)}
        print(mode, results[mode], flush=True)
    destination = ROOT / "scratch" / "etap5h_writer_benchmark.json"
    destination.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
