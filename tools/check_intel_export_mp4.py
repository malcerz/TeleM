"""Packet-level check of an exported MP4: frame count, PTS continuity, tail frame, A/V.

Usage: python tools/check_intel_export_mp4.py OUTPUT.mp4 --expected-frames N [--json OUT]
Exit code 0 only when every check passes.
"""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FFPROBE = ROOT / "runtime/common/ffmpeg/ffprobe.exe"


def _probe(path: Path) -> dict:
    out = subprocess.check_output([
        str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-show_packets",
        "-show_entries", "stream=index,codec_type,codec_name,profile,pix_fmt,color_transfer,time_base,r_frame_rate,"
                         "nb_frames,duration:format=duration:packet=stream_index,pts,dts,duration,flags",
        "-of", "json", str(path)], text=True)
    return json.loads(out)


def check(path: Path, expected_frames: int) -> dict:
    data = _probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    vidx = video["index"]
    tb = Fraction(video["time_base"])
    fps = Fraction(video["r_frame_rate"])
    frame_ticks = 1 / (fps * tb)
    pts = sorted(int(p["pts"]) for p in data["packets"] if p["stream_index"] == vidx and p.get("pts") not in (None, "N/A"))
    diffs = [b - a for a, b in zip(pts, pts[1:])]
    duplicates = len(pts) - len(set(pts))
    irregular = [d for d in diffs if abs(d - frame_ticks) > 1]
    expected_last = pts[0] + (expected_frames - 1) * frame_ticks if pts else None
    video_duration = float(video.get("duration") or 0.0)
    expected_duration = float(expected_frames / fps)
    res = {
        "path": str(path),
        "codec": video["codec_name"], "profile": video.get("profile"), "pix_fmt": video.get("pix_fmt"),
        "color_transfer": video.get("color_transfer"),
        "packets": len(pts), "expected_frames": expected_frames,
        "duplicates": duplicates, "irregular_steps": len(irregular),
        "first_pts": pts[0] if pts else None, "last_pts": pts[-1] if pts else None,
        "expected_last_pts": float(expected_last) if expected_last is not None else None,
        "video_duration_s": video_duration, "expected_duration_s": expected_duration,
        "audio": bool(audio), "audio_duration_s": float(audio.get("duration") or 0.0) if audio else None,
    }
    res["checks"] = {
        "frame_count": len(pts) == expected_frames,
        "no_duplicates": duplicates == 0,
        "continuous_pts": not irregular,
        "tail_frame_present": bool(pts) and abs(pts[-1] - expected_last) <= 1,
        "duration": abs(video_duration - expected_duration) <= float(1 / fps) + 1e-6,
        "audio_present": bool(audio),
        "av_sync": bool(audio) and abs(res["audio_duration_s"] - video_duration) < 0.1,
    }
    res["ok"] = all(res["checks"].values())
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mp4", type=Path)
    ap.add_argument("--expected-frames", type=int, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    res = check(args.mp4, args.expected_frames)
    if args.json:
        args.json.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "path"}))
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
