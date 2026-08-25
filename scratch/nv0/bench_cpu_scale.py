"""bench_cpu_scale.py
Measures the cost of CPU bilinear scale 1920x1080 RGBA → 3840x2160 RGBA
using FFmpeg (not Python), since this scale happens inside FFmpeg filter graph.
We measure per-frame cost by scaling 1131 RGBA frames and dividing.
"""
import sys, subprocess, time, json, shutil, os, statistics
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

TARGET_FRAMES = 1131
W_SRC, H_SRC = 1920, 1080
W_DST, H_DST = 3840, 2160

# Generate one static 1920x1080 RGBA frame
frame_src = bytes(W_SRC * H_SRC * 4)  # transparent
frame_size_src = len(frame_src)
print(f"Source frame: {W_SRC}x{H_SRC} RGBA = {frame_size_src/1024/1024:.2f} MiB")

ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.EXE")

# Method 1: FFmpeg rawvideo in → scale (CPU) → rawvideo out, measure wall-clock
# This isolates exactly the bilinear scale cost
OUTPUT_PATH = BASE_DIR / "Raporty" / "NVIDIA_NV0" / "cpu_scale_test.raw"

cmd = [
    ffmpeg, "-y",
    "-f", "rawvideo",
    "-pix_fmt", "rgba",
    "-s", f"{W_SRC}x{H_SRC}",
    "-r", "29.97",
    "-i", "pipe:0",
    "-vf", f"scale={W_DST}:{H_DST}:flags=bilinear",
    "-f", "rawvideo",
    "-pix_fmt", "rgba",
    "pipe:1",
    "-nostats", "-loglevel", "error",
]

startupinfo = None
if os.name == "nt":
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

print(f"=== CPU SCALE BENCHMARK ===")
print(f"FFmpeg bilinear scale {W_SRC}x{H_SRC} -> {W_DST}x{H_DST} for {TARGET_FRAMES} frames")
print()

process = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    startupinfo=startupinfo,
)

t_start = time.perf_counter()

# Pipe frames and drain output in threads
import threading

output_consumed = [0]
def drain_output():
    buf_size = W_DST * H_DST * 4
    while True:
        data = process.stdout.read(buf_size)
        if not data:
            break
        output_consumed[0] += len(data)

drain_t = threading.Thread(target=drain_output, daemon=True)
drain_t.start()

for i in range(TARGET_FRAMES):
    process.stdin.write(frame_src)

process.stdin.close()
drain_t.join()
process.wait()

t_end = time.perf_counter()
wall = t_end - t_start
fps = TARGET_FRAMES / wall
ms_per_frame = wall * 1000 / TARGET_FRAMES

print(f"Wall-clock: {wall:.3f} s")
print(f"Frames: {TARGET_FRAMES}")
print(f"FPS: {fps:.2f}")
print(f"Per-frame: {ms_per_frame:.2f} ms/frame")
print(f"Output consumed: {output_consumed[0]/1024**3:.2f} GiB")

result = {
    "test": "cpu_scale_1080p_to_4k",
    "src_res": f"{W_SRC}x{H_SRC}",
    "dst_res": f"{W_DST}x{H_DST}",
    "frames": TARGET_FRAMES,
    "wall_s": wall,
    "fps": fps,
    "ms_per_frame": ms_per_frame,
}

report_dir = BASE_DIR / "Raporty" / "NVIDIA_NV0"
with open(report_dir / "bench_cpu_scale.json", "w") as f:
    json.dump(result, f, indent=2)
print(f"\nResults saved to Raporty/NVIDIA_NV0/bench_cpu_scale.json")
