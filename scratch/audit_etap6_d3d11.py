"""Audit script for TeleM AMD ETAP 6: D3D11 & AMF Hardware Pipeline Analysis.
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess
from pathlib import Path

ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

def run_ffmpeg_audit(desc: str, args: list[str], pipe_bytes: bytes | None = None):
    cmd = [ffmpeg_exe, "-hide_banner", "-y", *args]
    print(f"\n================ AUDIT: {desc} ================")
    print("Command:", " ".join(cmd))
    res = subprocess.run(cmd, input=pipe_bytes, capture_output=True)
    stdout_str = res.stdout.decode("utf-8", errors="replace")
    stderr_str = res.stderr.decode("utf-8", errors="replace")
    print("Returncode:", res.returncode)
    lines = stderr_str.splitlines()
    for l in lines:
        if any(k in l.lower() for k in ("format", "hwaccel", "d3d11", "nv12", "amf", "pix_fmt", "surface", "error", "impossible", "opencl", "vulkan", "overlay")):
            print("  [LOG]", l)
    return res, stderr_str

if __name__ == "__main__":
    # 1. Test D3D11VA Decoder Output Format
    run_ffmpeg_audit("1. D3D11VA Decoder Output Format", [
        "-hwaccel", "d3d11va",
        "-i", input_video,
        "-vframes", "5",
        "-f", "null", "-"
    ])

    # 2. Test Direct GPU Passthrough (NO HUD mode: D3D11VA -> hevc_amf)
    run_ffmpeg_audit("2. Direct D3D11VA -> HEVC_AMF Zero-Copy", [
        "-hwaccel", "d3d11va",
        "-hwaccel_output_format", "d3d11",
        "-i", input_video,
        "-vframes", "30",
        "-c:v", "hevc_amf", "-b:v", "25M",
        "-f", "null", "-"
    ])

    dummy_rgba_frame = b"\x00" * (1920 * 1080 * 4 * 10)

    # 3. Test OpenCL derive from D3D11VA + overlay_opencl
    run_ffmpeg_audit("3. D3D11VA -> OpenCL derive + overlay_opencl", [
        "-init_hw_device", "d3d11va=d3d",
        "-init_hw_device", "opencl=ocl@d3d",
        "-filter_hw_device", "ocl",
        "-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11",
        "-i", input_video,
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x1080", "-r", "30.0", "-i", "pipe:0",
        "-filter_complex", "[0:v]hwmap=derive_device=opencl,format=opencl[base];[1:v]hwupload[ov];[base][ov]overlay_opencl[vout]",
        "-map", "[vout]",
        "-vframes", "10",
        "-c:v", "hevc_amf", "-b:v", "25M",
        "-f", "null", "-"
    ], pipe_bytes=dummy_rgba_frame)

    # 4. Test Vulkan derive from D3D11VA + overlay_vulkan
    run_ffmpeg_audit("4. D3D11VA -> Vulkan derive + overlay_vulkan", [
        "-init_hw_device", "d3d11va=d3d",
        "-init_hw_device", "vulkan=vk@d3d",
        "-filter_hw_device", "vk",
        "-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11",
        "-i", input_video,
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x1080", "-r", "30.0", "-i", "pipe:0",
        "-filter_complex", "[0:v]hwmap=derive_device=vulkan,format=vulkan[base];[1:v]hwupload[ov];[base][ov]overlay_vulkan[vout]",
        "-map", "[vout]",
        "-vframes", "10",
        "-c:v", "hevc_amf", "-b:v", "25M",
        "-f", "null", "-"
    ], pipe_bytes=dummy_rgba_frame)
