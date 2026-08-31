from __future__ import annotations

from bisect import bisect_left
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.multifile import build_timeline_from_paths
from telemetry_fit import parse_fit


VIDEO_ROOT = Path(r"C:\_DEV\TeleM\Video")
FFMPEG = r"C:\tools\ffmpeg.exe"
FFPROBE = r"C:\tools\ffprobe.exe"
PATHS = [VIDEO_ROOT / f"GX01011{n}.MP4" for n in (4, 5, 6)]


def nearest(records, target):
    timestamps = [record["timestamp"] for record in records]
    pos = bisect_left(timestamps, target)
    candidates = records[max(0, pos - 1):min(len(records), pos + 1)]
    return min(candidates, key=lambda record: abs((record["timestamp"] - target).total_seconds()))


def value(record, *keys):
    for key in keys:
        if record.get(key) is not None:
            return record[key]
    return None


def main() -> None:
    timeline = build_timeline_from_paths(
        PATHS, ffmpeg_exe=FFMPEG, ffprobe_exe=FFPROBE, use_cache=False,
    )
    records = parse_fit(VIDEO_ROOT / "GX010114_116.fit")
    print("TIMELINE")
    for index, clip in enumerate(timeline.clips, start=1):
        print(
            f"{index}|{clip.path.name}|global={clip.global_start_s:.6f}..{clip.global_end_s:.6f}|"
            f"absolute={clip.absolute_start_dt.isoformat()}..{clip.absolute_end_dt.isoformat()}|"
            f"source={clip.timestamp_source}|quality={clip.timestamp_quality}|reliable={clip.timestamp_reliable}"
        )
        for label, local in (
            ("start", 0.0),
            ("middle", clip.duration_s / 2.0),
            # Exact global boundaries belong to the following clip.  The
            # visible end control point is therefore the last decodable frame.
            ("end", max(0.0, clip.duration_s - 1.0 / clip.fps)),
        ):
            global_time = clip.global_start_s + local
            absolute = timeline.global_to_absolute(global_time)
            record = nearest(records, absolute)
            print(
                f"  {label}|global={global_time:.3f}|local={local:.3f}|absolute={absolute.isoformat()}|"
                f"fit={record['timestamp'].isoformat()}|distance={value(record, 'distance')}|"
                f"hr={value(record, 'heart_rate')}|cadence={value(record, 'cadence')}|"
                f"speed={value(record, 'enhanced_speed', 'speed')}|"
                f"lat={value(record, 'lat')}|lon={value(record, 'lon')}"
            )


if __name__ == "__main__":
    main()
