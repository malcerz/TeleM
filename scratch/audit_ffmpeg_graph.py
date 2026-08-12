"""Audit FFmpeg filtergraph and format conversions for AMD pipeline with loglevel verbose.
"""

from __future__ import annotations

import subprocess
import shutil
import re

ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

def audit_mode(desc, args):
    cmd = [ffmpeg, "-hide_banner", "-y", "-loglevel", "verbose", *args]
    print(f"\n=================== AUDIT: {desc} ===================")
    print("Command:", " ".join(cmd[:12]), "...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    lines = res.stderr.splitlines()

    print("\n--- FFmpeg Filter Graph & Format Logs ---")
    for line in lines:
        if any(k in line for k in ["filter graph", "auto-inserting", "hwdownload", "hwupload", "format", "Stream mapping", "query_formats", "D3D11", "hevc_amf"]):
            print("  ", line)

audit_mode("NO HUD Direct Passthrough", [
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "-frames:v", "10", "-f", "null", "-"
])

audit_mode("Sub-Window HUD Overlay", [
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "484x316", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v]format=nv12[base];[1:v]setpts=PTS-STARTPTS,format=rgba[ov];[base][ov]overlay=22:26:shortest=1[vtemp];[vtemp]null[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "-frames:v", "10", "-f", "null", "-"
])
