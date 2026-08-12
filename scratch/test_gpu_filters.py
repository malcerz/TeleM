"""Test hardware filters in FFmpeg for AMD GPU (D3D11 / Vulkan / OpenCL / HW MAP).
"""

from __future__ import annotations

import subprocess
import shutil

ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

def test_cmd(desc, args):
    cmd = [ffmpeg, "-hide_banner", "-y", *args]
    print(f"\nTesting {desc}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"SUCCESS: {desc}")
    else:
        print(f"FAILED: {desc}")
        lines = res.stderr.splitlines()
        for l in lines:
            if "Error" in l or "error" in l or "Invalid" in l or "Failed" in l:
                print("  ", l)

# 1. Test D3D11 scale filter
test_cmd("scale_d3d11va filter", [
    "-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11",
    "-i", input_video,
    "-vf", "scale_d3d11va=w=1920:h=1080",
    "-c:v", "hevc_amf", "-frames:v", "30", "-f", "null", "-"
])

# 2. Test overlay_vulkan filter
test_cmd("vulkan init & map", [
    "-init_hw_device", "vulkan=vk",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-vf", "hwmap=derive_device=vulkan,format=vulkan",
    "-c:v", "hevc_amf", "-frames:v", "30", "-f", "null", "-"
])

# 3. Test d3d11 overlay if available
test_cmd("overlay_d3d11 filter", [
    "-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "400x100", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v][1:v]overlay_d3d11=x=10:y=10",
    "-c:v", "hevc_amf", "-frames:v", "30", "-f", "null", "-"
])

# 4. Test hwupload sub-window overlay via hwmap / OpenCL / CPU
test_cmd("hwupload_cuda / hwupload for d3d11", [
    "-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "400x100", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[1:v]hwupload[ov];[0:v][ov]overlay=x=10:y=10",
    "-c:v", "hevc_amf", "-frames:v", "30", "-f", "null", "-"
])
