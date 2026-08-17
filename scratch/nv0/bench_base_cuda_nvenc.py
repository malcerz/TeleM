"""bench_base_cuda_nvenc.py
BASE CUDA+NVENC ceiling test — no HUD pipe.
Runs FFmpeg with NVDEC decode + scale_cuda + NVENC encode on the same input,
1131 frames, same settings as production (preset p1, vbr cq24, hevc_nvenc).
Measures true wall-clock FPS.
"""
import sys, subprocess, time, json, shutil, re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

VIDEO_PATH = BASE_DIR / "Video" / "GX020079.MP4"
OUTPUT_PATH = BASE_DIR / "Raporty" / "NVIDIA_NV0" / "nv0_base_cuda_nvenc.mp4"
TARGET_FRAMES = 1131

ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.EXE")
if not ffmpeg:
    print("[ERROR] ffmpeg not found")
    sys.exit(1)

# Production-compatible CUDA pipeline without HUD pipe:
# -hwaccel cuda -hwaccel_output_format cuda → NVDEC decode → GPU surface
# scale_cuda (format conversion to yuv420p, same res = no-op scale)
# hevc_nvenc preset p1 tune hq vbr cq24
# Same bitrate, pix_fmt cuda, gpu 0

cmd = [
    ffmpeg, "-y",
    "-hwaccel", "cuda",
    "-hwaccel_output_format", "cuda",
    "-i", str(VIDEO_PATH),
    "-filter_complex",
    "[0:v]scale_cuda=format=yuv420p[vout]",
    "-map", "[vout]",
    "-map", "0:a?",
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

print("=== BASE CUDA+NVENC TEST (no HUD) ===")
print("Command:", " ".join(cmd))
print()

startupinfo = None
import os
if os.name == "nt":
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

t_start = time.perf_counter()

process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    universal_newlines=True,
    startupinfo=startupinfo,
)

last_frame = 0
for line in process.stdout:
    line = line.strip()
    if line.startswith("frame="):
        try:
            last_frame = int(line.split("=")[1])
        except:
            pass
    elif line.startswith("progress=end"):
        break

process.wait()
t_end = time.perf_counter()
wall = t_end - t_start
fps = TARGET_FRAMES / wall if wall > 0 else 0.0

print(f"Output: {OUTPUT_PATH}")
print(f"Wall-clock: {wall:.3f} s")
print(f"Target frames: {TARGET_FRAMES}")
print(f"FFmpeg last_frame: {last_frame}")
print(f"TRUE FPS (base CUDA+NVENC): {fps:.2f}")
print(f"vs FULL production 27.15 FPS")
print(f"Overhead factor: {fps/27.15:.2f}x")

result = {
    "test": "base_cuda_nvenc_no_hud",
    "input": str(VIDEO_PATH),
    "output": str(OUTPUT_PATH),
    "target_frames": TARGET_FRAMES,
    "wall_s": wall,
    "true_fps": fps,
    "full_pipeline_fps": 27.15,
    "overhead_factor": fps / 27.15 if fps > 0 else None,
}

report_dir = BASE_DIR / "Raporty" / "NVIDIA_NV0"
with open(report_dir / "bench_base_cuda_nvenc.json", "w") as f:
    json.dump(result, f, indent=2)
print(f"\nResults saved to Raporty/NVIDIA_NV0/bench_base_cuda_nvenc.json")
