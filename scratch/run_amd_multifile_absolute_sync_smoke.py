"""Short native AMD source-switch smoke using the real 014/015/016 timestamps."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.gui.layout_manager import resolve_font_path
from src.multifile import VideoClip, VideoTimeline, build_timeline_from_paths
from telemetry_fit import parse_fit, sync_fit_to_video


VIDEO_ROOT = Path(r"C:\_DEV\TeleM\Video")
FFMPEG = r"C:\tools\ffmpeg.exe"
FFPROBE = r"C:\tools\ffprobe.exe"
PATHS = [VIDEO_ROOT / f"GX01011{n}.MP4" for n in (4, 5, 6)]


def main() -> int:
    real_timeline = build_timeline_from_paths(
        PATHS, ffmpeg_exe=FFMPEG, ffprobe_exe=FFPROBE, use_cache=False,
    )
    # Real production mapping and real source-local ranges: tail/head around
    # both boundaries, plus a non-contiguous jump inside 015.
    smoke_timeline = real_timeline.subset([
        (0, real_timeline.clips[0].duration_s - 10.0,
            real_timeline.clips[0].duration_s),
        (1, 0.0, 10.0),
        (1, real_timeline.clips[1].duration_s - 10.0,
            real_timeline.clips[1].duration_s),
        (2, 0.0, 10.0),
    ])
    records = parse_fit(VIDEO_ROOT / "GX010114_116.fit")
    fit_data = sync_fit_to_video(records, smoke_timeline.clips[0].absolute_start_dt)
    gps_track = [
        (record["timestamp"], record["lat"], record["lon"])
        for record in records
        if record.get("lat") is not None and record.get("lon") is not None
    ]
    layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
    output = ROOT / "scratch" / "amd_multifile_real_ranges_40s.mp4"
    result = stream_overlay_to_ffmpeg(
        ffmpeg_exe=FFMPEG,
        input_files=[str(path) for path in PATHS],
        output_file=str(output), duration_s=smoke_timeline.project_duration_s,
        start_dt_utc=smoke_timeline.clips[0].absolute_start_dt,
        tz_offset_hours=2, speed_samples=[], track_samples=[], alt_samples=[],
        font_path=resolve_font_path("Arial"), layout=layout, field_samples={},
        fit_data=fit_data, gps_track=gps_track,
        target_fps=30000 / 1001, update_rate_step=1, workers=1,
        encoder="amd", gpu=0, video_bitrate="20M", resolution_name="1080p",
        render_w=1920, render_h=1080, overlay_w=1920, overlay_h=1080,
        rotation_degrees=0, container_rotation=0, video_timeline=smoke_timeline,
    )
    print(
        f"RESULT|frames={result}|expected_source_switches=3|output={output}|"
        f"exists={output.exists()}|size={output.stat().st_size if output.exists() else 0}",
        flush=True,
    )
    return 0 if result >= 1 and output.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
