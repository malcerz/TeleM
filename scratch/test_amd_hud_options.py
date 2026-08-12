"""Test options for AMD HUD overlay filter graphs.
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
        for l in lines[-10:]:
            print("  ", l)

# Option 1: d3d11va decode -> hwdownload -> nv12 -> subwindow overlay -> hevc_amf
# (Avoids full 4K RGBA software scale and full 4K RGBA overlay)
test_cmd("Option 1: d3d11va -> hwdownload nv12 -> subwindow overlay -> hevc_amf", [
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x400", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v]hwdownload,format=nv12[base];[1:v]format=nv12[ov];[base][ov]overlay=0:1760:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-frames:v", "60",
    "-c:v", "hevc_amf", "-b:v", "25M",
    "-f", "null", "-"
])

# Option 2: d3d11va decode -> hwmap / format=nv12 -> overlay -> hevc_amf
test_cmd("Option 2: d3d11va -> format=nv12 -> overlay -> hevc_amf", [
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x400", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v]format=nv12[base];[1:v]format=rgba[ov];[base][ov]overlay=0:1760:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-frames:v", "60",
    "-c:v", "hevc_amf", "-b:v", "25M",
    "-f", "null", "-"
])

# Option 3: scale_amf
test_cmd("Option 3: scale_amf filter", [
    "-hwaccel", "d3d11va", "-hwaccel_output_format", "d3d11",
    "-i", input_video,
    "-vf", "scale_amf=w=1920:h=1080",
    "-frames:v", "30",
    "-c:v", "hevc_amf",
    "-f", "null", "-"
])
