"""Gate-2 / NV2-style pipeline PoC.

Simulates the NV2 CUDA fast-path for rotation=180 on the real GX020079 source:

    -hwaccel cuda -hwaccel_output_format cuda -noautorotate -i GX020079.MP4
    [0:v]scale_cuda=3840:2160:format=yuv420p[base]              # NO vflip/hflip
    [1:v]...format=rgba,scale=3840:2160:flags=bilinear,hwupload_cuda[ov]   # rotated-180 HUD
    [base][ov]overlay_cuda=x=0:y=0[vtemp]
    -> hevc_nvenc -pix_fmt cuda
    metadata: preserve source displaymatrix (rotate=180)

Run from repo root or this dir. Uses the project's ffmpeg/ffprobe.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(r"F:\_DEV\TeleM")
FFMPEG = BASE / "ffmpeg.exe"
FFPROBE = BASE / "ffprobe.exe"
SRC = BASE / "Video" / "GX020079.MP4"
HUD = Path(__file__).resolve().parent / "hud_rot180.png"
OUT = Path(__file__).resolve().parent / "nv2_poc.mp4"


def run(cmd: list[str]) -> int:
    print("CMD:", " ".join(map(str, cmd)), flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = "\n".join(p.stderr.strip().splitlines()[-12:])
    print(tail, flush=True)
    print(f"rc={p.returncode}", flush=True)
    return p.returncode


def probe_rotation(path: Path) -> None:
    cmd = [str(FFPROBE), "-v", "error", "-show_entries",
           "stream=codec_name,width,height:stream_side_data=rotation", "-of", "json", str(path)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("PROBE:", p.stdout, flush=True)


def main() -> None:
    filter_complex = (
        "[0:v]scale_cuda=3840:2160:format=yuv420p[base];"
        "[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,hwupload_cuda[ov];"
        "[base][ov]overlay_cuda=x=0:y=0[vtemp];"
        "[vtemp]null[vout]"
    )
    cmd = [
        str(FFMPEG), "-y",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-noautorotate",
        "-t", "4", "-i", str(SRC),
        "-loop", "1", "-framerate", "29.97", "-t", "4", "-i", str(HUD),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr", "-cq", "24",
        "-pix_fmt", "cuda",
        "-c:a", "copy",
        "-map_metadata", "-1", "-metadata:s:v:0", "rotate=180",
        str(OUT),
    ]
    rc = run(cmd)
    if rc == 0:
        probe_rotation(OUT)
    else:
        print("NV2 PoC FAILED", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
