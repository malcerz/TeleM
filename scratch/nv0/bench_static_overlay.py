"""bench_static_overlay.py
STATIC OVERLAY test — pre-generated RGBA frame piped 1131 times.
Same pipeline: rawvideo pipe → format=rgba → hwupload_cuda → overlay_cuda → NVENC.
No CPU HUD rendering per frame.
Measures TRUE FPS for GPU overlay path without CPU HUD bottleneck.
"""
import sys, subprocess, time, json, shutil, os
from pathlib import Path
from PIL import Image
import io

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

VIDEO_PATH = BASE_DIR / "Video" / "GX020079.MP4"
OUTPUT_PATH = BASE_DIR / "Raporty" / "NVIDIA_NV0" / "nv0_static_overlay.mp4"
TARGET_FRAMES = 1131

# Generate a static RGBA frame (3840x2160, mostly transparent with a small watermark)
W, H = 3840, 2160
import struct

# Create a simple static 4K RGBA frame (transparent black)
frame_bytes = bytes(W * H * 4)  # all zeros = fully transparent
frame_size = len(frame_bytes)
print(f"Static frame: {W}x{H} RGBA = {frame_size / 1024 / 1024:.1f} MiB")
print(f"Total pipe data: {frame_size * TARGET_FRAMES / 1024 / 1024:.0f} MiB")

ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.EXE")
if not ffmpeg:
    print("[ERROR] ffmpeg not found")
    sys.exit(1)

# Same filter_complex as production
filter_complex = (
    "[0:v]scale_cuda=format=yuv420p[base];"
    "[1:v]setpts=PTS-STARTPTS,format=rgba,hwupload_cuda[ov];"
    "[base][ov]overlay_cuda=x=0:y=0[vtemp];"
    "[vtemp]null[vout]"
)

import subprocess as sp
cmd = [
    ffmpeg, "-y",
    "-hwaccel", "cuda",
    "-hwaccel_output_format", "cuda",
    "-i", str(VIDEO_PATH),
    "-f", "rawvideo",
    "-pix_fmt", "rgba",
    "-s", f"{W}x{H}",
    "-r", "29.97002997002997",
    "-i", "pipe:0",
    "-i", str(VIDEO_PATH),
    "-filter_complex", filter_complex,
    "-map", "[vout]",
    "-map", "2:a?",
    "-map_metadata", "-1",
    "-metadata:s:v:0", "rotate=0",
    "-c:v", "hevc_nvenc",
    "-preset", "p1",
    "-tune", "hq",
    "-rc", "vbr",
    "-cq", "24",
    "-pix_fmt", "cuda",
    "-gpu", "0",
    "-c:a", "copy",
    "-b:v", "40M",
    "-maxrate", "40M",
    "-bufsize", "80M",
    str(OUTPUT_PATH),
    "-progress", "pipe:1",
    "-nostats",
    "-loglevel", "error",
]

print("=== STATIC OVERLAY TEST ===")
print("Command:", " ".join(cmd))
print()

startupinfo = None
if os.name == "nt":
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

t_start = time.perf_counter()

process = sp.Popen(
    cmd,
    stdin=sp.PIPE,
    stdout=sp.PIPE,
    stderr=sp.STDOUT,
    universal_newlines=False,
    startupinfo=startupinfo,
)

# Reader thread
import threading
stdout_lines = []

def reader():
    for line in process.stdout:
        l = line.decode("utf-8", errors="replace").strip()
        stdout_lines.append(l)

rt = threading.Thread(target=reader, daemon=True)
rt.start()

# Pipe static frame 1131 times
write_times = []
for i in range(TARGET_FRAMES):
    t0 = time.perf_counter()
    process.stdin.write(frame_bytes)
    t1 = time.perf_counter()
    write_times.append((t1 - t0) * 1000)
    if i % 100 == 0:
        print(f"  Piped {i+1}/{TARGET_FRAMES} frames, write={write_times[-1]:.1f}ms")

process.stdin.close()
rt.join()
process.wait()

t_end = time.perf_counter()
wall = t_end - t_start
fps = TARGET_FRAMES / wall if wall > 0 else 0.0

import statistics
print()
print(f"=== STATIC OVERLAY RESULTS ===")
print(f"Wall-clock: {wall:.3f} s")
print(f"TRUE FPS (static overlay): {fps:.2f}")
print(f"vs FULL production 27.15 FPS")
print()
wt = sorted(write_times)
print(f"stdin.write timing:")
print(f"  avg:    {statistics.mean(write_times):.2f} ms/frame")
print(f"  median: {statistics.median(write_times):.2f} ms/frame")
print(f"  P95:    {wt[int(TARGET_FRAMES*0.95)]:.2f} ms/frame")
print(f"  P99:    {wt[int(TARGET_FRAMES*0.99)]:.2f} ms/frame")
print(f"  max:    {max(write_times):.2f} ms/frame")

result = {
    "test": "static_overlay_cuda",
    "frame_size_bytes": frame_size,
    "target_frames": TARGET_FRAMES,
    "wall_s": wall,
    "true_fps": fps,
    "full_pipeline_fps": 27.15,
    "stdin_write_avg_ms": statistics.mean(write_times),
    "stdin_write_median_ms": statistics.median(write_times),
    "stdin_write_p95_ms": wt[int(TARGET_FRAMES * 0.95)],
    "stdin_write_p99_ms": wt[int(TARGET_FRAMES * 0.99)],
    "stdin_write_max_ms": max(write_times),
}

report_dir = BASE_DIR / "Raporty" / "NVIDIA_NV0"
with open(report_dir / "bench_static_overlay.json", "w") as f:
    json.dump(result, f, indent=2)
print(f"\nResults saved to Raporty/NVIDIA_NV0/bench_static_overlay.json")
