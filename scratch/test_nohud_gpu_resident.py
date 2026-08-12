"""Test NO HUD direct GPU-resident decoding & encoding in FFmpeg on AMD.
"""

from __future__ import annotations

import subprocess
import shutil
import time

ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

# Test 1: Baseline NO HUD with CPU overlay graph (Etap 2)
cmd_etap2 = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "2x2", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v]null[base];[1:v]setpts=PTS-STARTPTS,format=rgba[ov];[base][ov]overlay=0:0:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "scratch/output/test_nohud_etap2.mp4"
]

# Test 2: Direct GPU-resident NO HUD (NO CPU overlay, NO hwdownload filter)
cmd_direct = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-map", "0:v", "-map", "0:a?",
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "scratch/output/test_nohud_direct.mp4"
]

print("Running Test 1 (Etap 2 NO HUD with CPU overlay graph)...")
t0 = time.perf_counter()
p1 = subprocess.Popen(cmd_etap2, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
p1.stdin.write(b'\x00' * (2 * 2 * 4 * 300)) # 300 dummy 2x2 frames
p1.stdin.close()
p1.wait()
dt1 = time.perf_counter() - t0
fps1 = 300 / dt1
print(f"Etap 2 NO HUD: {dt1:.2f} s ({fps1:.2f} FPS)")

print("\nRunning Test 2 (Direct GPU-resident NO HUD, zero hwdownload)...")
t0 = time.perf_counter()
res2 = subprocess.run(cmd_direct, capture_output=True, text=True)
dt2 = time.perf_counter() - t0
# GX020079 is 1131 frames (37.7s)
fps2 = 1131 / dt2
print(f"Direct GPU NO HUD: {dt2:.2f} s ({fps2:.2f} FPS)")
