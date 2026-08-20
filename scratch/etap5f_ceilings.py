"""ETAP 5F diagnostic ceilings: worker-only, pipe-only and FFmpeg graph.

These are measurement harnesses only.  They do not call the production
streamer and do not change its defaults.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from multiprocessing import shared_memory
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.shared_memory import SharedFramePool, _init_worker_with_shm, render_frame_shm_job
from src.ffmpeg.worker_cache import WORKER_CACHE

VIDEO = ROOT / "Video" / "GX030120.MP4"
RECTS = [
    (1646, 414, 0, 0, 102, 20),
    (1472, 118, 106, 0, 448, 244),
    (958, 78, 558, 0, 74, 84),
    (46, 754, 0, 248, 1828, 326),
    (30, 30, 1832, 248, 64, 514),
]
ATLAS = (1900, 762)


def gpu_monitor():
    try:
        return subprocess.Popen(
            ["nvidia-smi", "dmon", "-s", "pucvmet", "-d", "1"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except OSError:
        return None


def stop_monitor(proc):
    if proc is None:
        return {}
    proc.terminate()
    try:
        output, _ = proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate()
    values = {"sm": [], "enc": [], "dec": [], "mem": []}
    for line in output.splitlines():
        cols = line.split()
        if not cols or not cols[0].isdigit() or len(cols) < 9:
            continue
        for key, index in (("sm", 4), ("enc", 6), ("dec", 7), ("mem", 8)):
            try:
                values[key].append(float(cols[index]))
            except (ValueError, IndexError):
                pass
    return {
        key: {"avg": statistics.fmean(value) if value else None,
              "max": max(value) if value else None, "samples": len(value)}
        for key, value in values.items()
    }


def ffmpeg_filter():
    labels = "".join(f"[ov_raw_{i}]" for i in range(len(RECTS)))
    chains = []
    overlays = []
    previous = "[base]"
    for i, (dx, dy, ax, ay, rw, rh) in enumerate(RECTS):
        chains.append(
            f"[ov_raw_{i}]crop={rw}:{rh}:{ax}:{ay},"
            f"scale={rw * 2}:{rh * 2}:flags=bilinear,format=yuva420p,hwupload_cuda[ov_{i}]"
        )
        next_label = f"[v_step_{i}]" if i < len(RECTS) - 1 else "[vout]"
        overlays.append(f"{previous}[ov_{i}]overlay_cuda=x={dx * 2}:y={dy * 2}{next_label}")
        previous = next_label
    return (
        "[0:v]scale_cuda=format=yuv420p[base];"
        f"[1:v]setpts=PTS-STARTPTS,format=rgba,split={len(RECTS)}{labels};"
        + ";".join(chains) + ";" + ";".join(overlays)
    )


def run_ffmpeg_graph(label: str, frames: int = N):
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda", "-i", str(VIDEO), "-f", "lavfi", "-i",
        f"color=c=black@0.0:s={ATLAS[0]}x{ATLAS[1]}:r={FPS}",
        "-filter_complex", ffmpeg_filter(), "-map", "[vout]", "-frames:v", str(frames),
        "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
        "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0", "-f", "null", "-",
    ]
    results = []
    for run in range(1, 4):
        monitor = gpu_monitor()
        started = time.perf_counter()
        completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        elapsed = time.perf_counter() - started
        gpu = stop_monitor(monitor)
        if completed.returncode:
            raise RuntimeError(completed.stderr[-2000:])
        item = {"run": run, "frames": frames, "elapsed_s": elapsed,
                "fps": frames / elapsed, "gpu": gpu}
        results.append(item)
        print(f"{label} run={run} fps={item['fps']:.2f} gpu={gpu}", flush=True)
    return {"label": label, "runs": results,
            "median_fps": statistics.median(item["fps"] for item in results)}


def initargs_from_cache(layout, regions, anchor, speed, track, alt):
    cache = WORKER_CACHE
    return (
        W, H, "", layout, cache.get("field_samples", {}), cache.get("max_distance_m"),
        cache.get("iso_samples", []), cache.get("exposure_samples", []), cache.get("temperature_samples", []),
        cache.get("gpx_speed_samples", []), cache.get("gpx_track_samples", []), cache.get("gpx_alt_samples", []),
        cache.get("gpx_power_samples", []), cache.get("gpx_atemp_samples", []), cache.get("gpx_hr_samples", []),
        cache.get("gpx_cad_samples", []), cache.get("fit_data", {}), cache.get("gps_track", []),
        anchor, 2, speed, track, alt, FPS, 1, N, cache.get("_cut_regions", []),
        cache.get("effective_rotation", 0), None, regions, cache.get("hud_rotate_180", False),
        cache.get("_telemetry_cache"),
    )


def run_worker_only(label: str, frames: int = N, workers: int = 4, slots: int = 8):
    layout, regions, anchor, speed, track, alt = setup()
    frame_size = ATLAS[0] * ATLAS[1] * 4
    pool = SharedFramePool(slots, frame_size)
    initargs = initargs_from_cache(layout, regions, anchor, speed, track, alt)
    submitted = 0
    completed = 0
    started = time.perf_counter()
    busy_ns = []
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker_with_shm,
        initargs=(pool.shm_names(), frame_size, *initargs),
    ) as executor:
        pending = {}
        while completed < frames:
            while submitted < frames and len(pending) < slots:
                slot = pool.acquire(timeout=30)
                future = executor.submit(render_frame_shm_job, (submitted, slot, True))
                pending[future] = slot
                submitted += 1
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                result = future.result()
                _, slot, _pid, worker_started = result[:4]
                copy_finished = result[6]
                busy_ns.append(copy_finished - worker_started)
                pool.release(slot)
                del pending[future]
                completed += 1
    elapsed = time.perf_counter() - started
    result = {
        "label": label, "frames": frames, "workers": workers, "slots": slots,
        "elapsed_s": elapsed, "fps": frames / elapsed,
        "worker_job_ms": {"avg": statistics.fmean(busy_ns) / 1e6,
                           "median": statistics.median(busy_ns) / 1e6,
                           "p95": sorted(busy_ns)[int(len(busy_ns) * .95)] / 1e6},
    }
    pool.close()
    print(f"{label} fps={result['fps']:.2f} job={result['worker_job_ms']}", flush=True)
    return result


def run_pipe_only(label: str, frames: int = N):
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda", "-i", str(VIDEO), "-f", "rawvideo",
        "-pix_fmt", "rgba", "-s", f"{ATLAS[0]}x{ATLAS[1]}", "-r", str(FPS), "-i", "pipe:0",
        "-filter_complex", ffmpeg_filter(), "-map", "[vout]", "-frames:v", str(frames),
        "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr", "-cq", "24",
        "-pix_fmt", "cuda", "-gpu", "0", "-f", "null", "-",
    ]
    frame = bytes(ATLAS[0] * ATLAS[1] * 4)
    results = []
    for run in range(1, 4):
        monitor = gpu_monitor()
        started = time.perf_counter()
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(frames):
                process.stdin.write(frame)
            process.stdin.close()
        except BrokenPipeError:
            pass
        stderr = process.stderr.read()
        process.wait()
        elapsed = time.perf_counter() - started
        gpu = stop_monitor(monitor)
        if process.returncode:
            raise RuntimeError(stderr.decode(errors="replace")[-2000:])
        item = {"run": run, "frames": frames, "elapsed_s": elapsed,
                "fps": frames / elapsed, "gpu": gpu}
        results.append(item)
        print(f"{label} run={run} fps={item['fps']:.2f} gpu={gpu}", flush=True)
    return {"label": label, "runs": results,
            "median_fps": statistics.median(item["fps"] for item in results)}


if __name__ == "__main__":
    results = {
        "ffmpeg_graph": run_ffmpeg_graph("ffmpeg_graph"),
        "pipe_only": run_pipe_only("pipe_only"),
        "worker_only": [run_worker_only(f"worker_only_{i}") for i in range(1, 4)],
    }
    (ROOT / "scratch" / "etap5f_ceilings.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)
