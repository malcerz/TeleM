"""Benchmark HUD Atlas vs Multi-Region Overlay in FFmpeg for AMD AMF pipeline (300 frames).
"""

from __future__ import annotations

import subprocess
import shutil
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
input_video = "Video/GX020079.mp4"

# 1. Single Bbox HUD (Etap 3): 3818x2134 (31.1 MB/frame)
cmd_single = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "3818x2134", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v]format=nv12[base];[1:v]setpts=PTS-STARTPTS,format=rgba[ov];[base][ov]overlay=22:26:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-frames:v", "300",
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "scratch/output/test_single_bbox.mp4"
]

# 2. Multi-Region (2 Streams): Region 1 (3840x400 Top) + Region 2 (3840x400 Bottom) -> 12.3 MB/frame
cmd_multi2 = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "3840x400", "-r", "30.0", "-i", "pipe:0",
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "3840x400", "-r", "30.0", "-i", "pipe:1",
    "-filter_complex", "[0:v]format=nv12[base];[1:v]setpts=PTS-STARTPTS,format=rgba[ov1];[2:v]setpts=PTS-STARTPTS,format=rgba[ov2];[base][ov1]overlay=0:0[v1];[v1][ov2]overlay=0:1760:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-frames:v", "300",
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "scratch/output/test_multi2_region.mp4"
]

# 3. HUD Atlas (Single 1920x600 Stream -> Crop & Overlay in FFmpeg): 4.6 MB/frame
cmd_atlas = [
    ffmpeg, "-hide_banner", "-y",
    "-hwaccel", "d3d11va",
    "-i", input_video,
    "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x600", "-r", "30.0", "-i", "pipe:0",
    "-filter_complex", "[0:v]format=nv12[base];[1:v]setpts=PTS-STARTPTS,format=rgba,split=2[ov1_raw][ov2_raw];[ov1_raw]crop=1920:300:0:0[ov1];[ov2_raw]crop=1920:300:0:300[ov2];[base][ov1]overlay=0:0[v1];[v1][ov2]overlay=0:1760:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a?",
    "-frames:v", "300",
    "-c:v", "hevc_amf", "-pix_fmt", "nv12", "-b:v", "25M",
    "scratch/output/test_atlas.mp4"
]

def run_bench(desc, cmd, stdin_bytes_per_frame, pipes_count=1):
    print(f"\nRunning {desc}...")
    t0 = time.perf_counter()
    if pipes_count == 1:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dummy_bytes = b'\x00' * stdin_bytes_per_frame
        for _ in range(300):
            p.stdin.write(dummy_bytes)
        p.stdin.close()
        p.wait()
    else:
        # Multi-pipe test
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dummy_bytes = b'\x00' * stdin_bytes_per_frame
        for _ in range(300):
            p.stdin.write(dummy_bytes)
        p.stdin.close()
        p.wait()
    dt = time.perf_counter() - t0
    fps = 300 / dt if dt > 0 else 0
    print(f"Result {desc}: {dt:.2f} s ({fps:.2f} FPS)")
    return fps

def main():
    fps1 = run_bench("1. Single Bbox (31.1 MB/frame)", cmd_single, 3818 * 2134 * 4)
    fps3 = run_bench("3. HUD Atlas (4.6 MB/frame)", cmd_atlas, 1920 * 600 * 4)

    print("\n=================== BENCHMARK SUMMARY ===================")
    print(f"Single Bbox (31.1 MB) : {fps1:.2f} FPS")
    print(f"HUD Atlas   ( 4.6 MB) : {fps3:.2f} FPS")
    print(f"Speedup               : +{((fps3 - fps1) / fps1) * 100:.1f}%")
    print("=========================================================")

if __name__ == "__main__":
    main()
