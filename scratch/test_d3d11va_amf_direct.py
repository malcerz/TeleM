"""Test script for D3D11VA -> AMF direct hardware passthrough.
"""

from __future__ import annotations

import subprocess
import shutil
import time

ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

# Test 1: Direct D3D11VA decode -> HEVC_AMF without any filter graph
cmd1 = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-c:v", "hevc_amf",
    "-pix_fmt", "nv12",
    "-f", "null", "-"
]

print("Running Test 1: -hwaccel d3d11va -i input -c:v hevc_amf ...")
t0 = time.perf_counter()
res1 = subprocess.run(cmd1, capture_output=True, text=True)
dt1 = time.perf_counter() - t0
print(f"Test 1 Return code: {res1.returncode}, Time: {dt1:.2f} s")
if res1.returncode != 0:
    print("Test 1 Stderr last 10 lines:\n", "\n".join(res1.stderr.splitlines()[-10:]))

# Test 2: D3D11VA with hwupload/hwmap/d3d11va output format
cmd2 = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-hwaccel_output_format", "d3d11",
    "-i", input_video,
    "-c:v", "hevc_amf",
    "-f", "null", "-"
]

print("\nRunning Test 2: -hwaccel d3d11va -hwaccel_output_format d3d11 -i input -c:v hevc_amf ...")
t0 = time.perf_counter()
res2 = subprocess.run(cmd2, capture_output=True, text=True)
dt2 = time.perf_counter() - t0
print(f"Test 2 Return code: {res2.returncode}, Time: {dt2:.2f} s")
if res2.returncode != 0:
    print("Test 2 Stderr last 10 lines:\n", "\n".join(res2.stderr.splitlines()[-10:]))
