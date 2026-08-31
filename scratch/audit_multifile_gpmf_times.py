from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.multifile import probe_video_info
from src.telemetry_gpmf_new import (
    _decode_gps9_real_samples,
    _gps9_datetime,
    extract_gpmf,
    parse_gpmf,
)


VIDEO_ROOT = Path(r"C:\_DEV\TeleM\Video")
FFMPEG = r"C:\tools\ffmpeg.exe"
FFPROBE = r"C:\tools\ffprobe.exe"


def number(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (list, tuple)) and value:
        return number(value[0])
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    for name in ("GX010114.MP4", "GX010115.MP4", "GX010116.MP4"):
        path = VIDEO_ROOT / name
        info = probe_video_info(FFPROBE, path)
        parsed = parse_gpmf(extract_gpmf(path, ffmpeg_exe=FFMPEG, ffprobe_exe=FFPROBE))
        stmp = tsmp = None
        type_str = None
        scal = None
        samples: list[tuple[datetime, float | None]] = []
        for key, value in parsed:
            if key == "STMP":
                stmp = number(value)
            elif key == "TSMP":
                tsmp = number(value)
            elif key == "TYPE":
                type_str = value.decode("ascii", errors="ignore").rstrip("\0") if isinstance(value, bytes) else str(value)
            elif key == "SCAL":
                scal = value
            elif key == "GPS9":
                for sample_idx, fields in enumerate(_decode_gps9_real_samples(value, type_str, scal)):
                    lat, lon, _alt, _s2d, _s3d, days, secs, _dop, _fix = fields
                    if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180) or (float(lat) == 0 and float(lon) == 0):
                        continue
                    absolute = _gps9_datetime(days, secs)
                    local = (stmp / 1_000_000.0 + sample_idx * 0.1) if stmp is not None else None
                    samples.append((absolute, local))
        first_abs, first_local = samples[0]
        last_abs, last_local = samples[-1]
        print(
            f"{name}|duration={info['duration_s']:.6f}|fps={info['fps']:.9f}|"
            f"source=gpmf_gps9|samples={len(samples)}|"
            f"first_abs={first_abs.isoformat()}|first_local={first_local}|"
            f"last_abs={last_abs.isoformat()}|last_local={last_local}"
        )


if __name__ == "__main__":
    main()
