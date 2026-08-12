"""Audit script part 2: D3D11 format conversion (p010le -> nv12) & AMF compatibility.
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess

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
    dummy_rgba_frame = b"\x00" * (1920 * 1080 * 4 * 10)

    # 1. Test D3D11VA p010le -> format=nv12 -> hevc_amf (Zero-copy GPU-resident passthrough)
    run_ffmpeg_audit("1. D3D11VA p010le -> format=nv12 -> hevc_amf", [
        "-hwaccel", "d3d11va",
        "-i", input_video,
        "-vframes", "30",
        "-filter_complex", "[0:v]format=nv12[vout]",
        "-map", "[vout]",
        "-c:v", "hevc_amf", "-b:v", "25M",
        "-f", "null", "-"
    ])

    # 2. Test OpenCL derive device with format=nv12 hardware frames
    run_ffmpeg_audit("2. D3D11VA -> OpenCL derive + format=nv12 + overlay_opencl", [
        "-init_hw_device", "opencl=ocl",
        "-filter_hw_device", "ocl",
        "-hwaccel", "d3d11va",
        "-i", input_video,
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x1080", "-r", "30.0", "-i", "pipe:0",
        "-filter_complex", "[0:v]format=nv12,hwupload[base];[1:v]hwupload[ov];[base][ov]overlay_opencl[v_ocl];[v_ocl]hwdownload,format=nv12[vout]",
        "-map", "[vout]",
        "-vframes", "10",
        "-c:v", "hevc_amf", "-b:v", "25M",
        "-f", "null", "-"
    ], pipe_bytes=dummy_rgba_frame)

    # 3. Test Direct D3D11VA -> hwdownload nv12 -> software overlay vs GPU compositor
    run_ffmpeg_audit("3. D3D11VA (nv12) -> hardware vs software overlay", [
        "-hwaccel", "d3d11va",
        "-i", input_video,
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x1080", "-r", "30.0", "-i", "pipe:0",
        "-filter_complex", "[0:v]format=nv12[base];[1:v]format=rgba[ov];[base][ov]overlay=0:0:shortest=1[vout]",
        "-map", "[vout]",
        "-vframes", "30",
        "-c:v", "hevc_amf", "-b:v", "25M",
        "-f", "null", "-"
    ], pipe_bytes=dummy_rgba_frame)
