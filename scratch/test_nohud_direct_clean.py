"""Clean synchronous comparison of NO HUD Etap 2 vs Direct GPU-resident NO HUD (300 frames).
"""

from __future__ import annotations

import subprocess
import shutil
import time

ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

# Test 1: Etap 2 NO HUD with CPU overlay filter graph (300 frames)
cmd_etap2 = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "2x2", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v]scale=3840:2160:flags=lanczos[base];[1:v]setpts=PTS-STARTPTS,format=rgba[ov];[base][ov]overlay=0:0:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-frames:v", "300",
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "scratch/output/test_nohud_etap2.mp4"
]

print("Running Test 1 (Etap 2 NO HUD with CPU filter graph)...")
t0 = time.perf_counter()
p1 = subprocess.Popen(cmd_etap2, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
p1.stdin.write(b'\x00' * (2 * 2 * 4 * 300))
p1.stdin.close()
p1.wait()
dt1 = time.perf_counter() - t0
fps1 = 300 / dt1 if dt1 > 0 else 0
print(f"Etap 2 NO HUD: {dt1:.2f} s ({fps1:.2f} FPS)")

# Test 2: Direct GPU-resident NO HUD (NO filter graph, NO hwdownload, NO overlay)
cmd_direct = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-frames:v", "300",
    "-map", "0:v", "-map", "0:a?",
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "scratch/output/test_nohud_direct.mp4"
]

print("\nRunning Test 2 (Direct GPU-resident NO HUD, zero hwdownload)...")
t0 = time.perf_counter()
res2 = subprocess.run(cmd_direct, capture_output=True, text=True)
dt2 = time.perf_counter() - t0
fps2 = 300 / dt2 if dt2 > 0 else 0
print(f"Direct GPU NO HUD: {dt2:.2f} s ({fps2:.2f} FPS)")
print(f"FPS Gain for NO HUD: +{((fps2 - fps1) / fps1) * 100:.1f}%")
