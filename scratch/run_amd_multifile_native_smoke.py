from __future__ import annotations

import json
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.gui.layout_manager import resolve_font_path
from src.multifile import VideoClip, VideoTimeline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single", action="store_true")
    args = parser.parse_args()
    old = Path(r"C:\_DEV\TeleM\Video")
    def clip(name: str, start: datetime) -> VideoClip:
        return VideoClip(
            path=old / name, duration_s=5.0, fps=29.97, width=3840, height=2160,
            absolute_start_dt=start, timestamp_source="gpmf_gps9",
            timestamp_reliable=True, timestamp_quality="exact",
        )

    clips = [clip("GX010115.MP4", datetime(2026, 8, 14, 11, 18, 2, 250270))]
    if not args.single:
        clips = [
            clip("GX010114.MP4", datetime(2026, 8, 14, 9, 40, 11, 704000)),
            clip("GX010115.MP4", datetime(2026, 8, 14, 11, 18, 2, 250270)),
            clip("GX010116.MP4", datetime(2026, 8, 14, 11, 32, 9, 735793)),
        ]
    timeline = VideoTimeline.from_clips(
        clips, base_dt=datetime(2026, 8, 14, 11, 18, 2, 250270)
    )
    with (ROOT / "def_layout.json").open(encoding="utf-8") as handle:
        layout = json.load(handle)
    output = ROOT / "scratch" / ("amd_single_native_smoke.mp4" if args.single else "amd_multifile_native_smoke.mp4")
    result = stream_overlay_to_ffmpeg(
        ffmpeg_exe=r"C:\tools\ffmpeg.exe",
        input_files=[str(c.path) for c in clips], output_file=output,
        duration_s=timeline.project_duration_s,
        start_dt_utc=timeline.base_dt, tz_offset_hours=2,
        speed_samples=[], track_samples=[], alt_samples=[],
        font_path=resolve_font_path("Arial"), layout=layout, field_samples={},
        target_fps=30000 / 1001, update_rate_step=1, workers=1,
        encoder="amd", gpu=0, video_bitrate="25M", resolution_name="4k",
        render_w=3840, render_h=2160, overlay_w=1920, overlay_h=1080,
        rotation_degrees=0, container_rotation=0, video_timeline=timeline,
    )
    print(f"SMOKE_RESULT frames={result} output={output} exists={output.exists()}")
    return 0 if result >= 1 and output.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
