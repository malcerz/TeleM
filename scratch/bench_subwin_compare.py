"""Benchmark option 2 subwindow HUD vs Etap 2 subwindow HUD vs Direct NO HUD (300 frames).
"""

from __future__ import annotations

import subprocess
import shutil
import time

ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

# 1. Direct NO HUD (Zero hwdownload, Zero filter graph)
cmd_nohud_direct = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-frames:v", "300",
    "-map", "0:v", "-map", "0:a?",
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "scratch/output/bench_nohud_direct.mp4"
]

t0 = time.perf_counter()
res = subprocess.run(cmd_nohud_direct, capture_output=True, text=True)
dt_nohud = time.perf_counter() - t0
fps_nohud = 300 / dt_nohud if dt_nohud > 0 else 0
print(f"1. Direct GPU NO HUD: {dt_nohud:.2f} s ({fps_nohud:.2f} FPS)")

# 2. Optimized Sub-Window HUD (1920x400 overlay, no full scale)
cmd_subwin_opt = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x400", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v]format=nv12[base];[1:v]format=rgba[ov];[base][ov]overlay=0:1760:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-frames:v", "300",
    "-c:v", "hevc_amf", "-b:v", "25M",
    "scratch/output/bench_subwin_opt.mp4"
]

t0 = time.perf_counter()
p = subprocess.Popen(cmd_subwin_opt, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
dummy_subwin_bytes = b'\x00' * (1920 * 400 * 4)
for _ in range(300):
    p.stdin.write(dummy_subwin_bytes)
p.stdin.close()
p.wait()
dt_subwin_opt = time.perf_counter() - t0
fps_subwin_opt = 300 / dt_subwin_opt if dt_subwin_opt > 0 else 0
print(f"2. Optimized Sub-Window HUD (1920x400): {dt_subwin_opt:.2f} s ({fps_subwin_opt:.2f} FPS)")

# 3. Old Etap 2 Sub-Window HUD (with scale=3840:2160 Lanczos full scale)
cmd_subwin_old = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x400", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v]scale=3840:2160:flags=lanczos[base];[1:v]format=rgba[ov];[base][ov]overlay=0:1760:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-frames:v", "300",
    "-c:v", "hevc_amf", "-b:v", "25M",
    "scratch/output/bench_subwin_old.mp4"
]

t0 = time.perf_counter()
p = subprocess.Popen(cmd_subwin_old, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(300):
    p.stdin.write(dummy_subwin_bytes)
p.stdin.close()
p.wait()
dt_subwin_old = time.perf_counter() - t0
fps_subwin_old = 300 / dt_subwin_old if dt_subwin_old > 0 else 0
print(f"3. Old Etap 2 Sub-Window HUD (Full Lanczos scale): {dt_subwin_old:.2f} s ({fps_subwin_old:.2f} FPS)")
