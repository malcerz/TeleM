"""Test hardware format conversion filter on D3D11 GPU surfaces for AMF.
"""

from __future__ import annotations

import subprocess
import shutil
import time

ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

# Test 3: scale_d3d11va filter on GPU
cmd3 = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-hwaccel_output_format", "d3d11",
    "-i", input_video,
    "-vf", "scale_d3d11va=format=nv12",
    "-c:v", "hevc_amf",
    "-f", "null", "-"
]

print("Running Test 3: scale_d3d11va=format=nv12 ...")
t0 = time.perf_counter()
res3 = subprocess.run(cmd3, capture_output=True, text=True)
dt3 = time.perf_counter() - t0
print(f"Test 3 Return code: {res3.returncode}, Time: {dt3:.2f} s")
if res3.returncode != 0:
    print("Test 3 Stderr last 10 lines:\n", "\n".join(res3.stderr.splitlines()[-10:]))

# Test 4: format=nv12 filter
cmd4 = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-hwaccel_output_format", "d3d11",
    "-i", input_video,
    "-vf", "format=nv12",
    "-c:v", "hevc_amf",
    "-f", "null", "-"
]

print("\nRunning Test 4: format=nv12 ...")
t0 = time.perf_counter()
res4 = subprocess.run(cmd4, capture_output=True, text=True)
dt4 = time.perf_counter() - t0
print(f"Test 4 Return code: {res4.returncode}, Time: {dt4:.2f} s")
if res4.returncode != 0:
    print("Test 4 Stderr last 10 lines:\n", "\n".join(res4.stderr.splitlines()[-10:]))
