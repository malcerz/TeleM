"""Test script for Vulkan / hwmap hardware acceleration on AMD.
"""

from __future__ import annotations

import subprocess
import shutil
import time

ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

# Test 1: Vulkan init & hwmap
cmd1 = [
    ffmpeg, "-hide_banner", "-y",
    "-init_hw_device", "vulkan=vk",
    "-init_hw_device", "d3d11va=d3d@vk",
    "-filter_hw_device", "vk",
    "-hwaccel", "d3d11va",
    "-hwaccel_output_format", "d3d11",
    "-i", input_video,
    "-vf", "hwmap=derive_device=vulkan,scale_vulkan=format=nv12",
    "-c:v", "hevc_amf",
    "-f", "null", "-"
]

print("Running Vulkan Test 1...")
t0 = time.perf_counter()
res1 = subprocess.run(cmd1, capture_output=True, text=True)
dt1 = time.perf_counter() - t0
print(f"Vulkan Test 1 Return code: {res1.returncode}, Time: {dt1:.2f} s")
if res1.returncode != 0:
    print("Vulkan Test 1 Stderr last 15 lines:\n", "\n".join(res1.stderr.splitlines()[-15:]))
