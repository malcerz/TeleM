"""Telemetry data extraction, interpolation, and smoothing functions.

Handles parsing ExifTool JSON records, extracting speed/altitude/track/ISO/exposure/
temperature samples, interpolation between timestamps, and smoothing algorithms.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import orjson
except ImportError:
    orjson = None


# ── JSON / helpers ──────────────────────────────────────────────────────────


def json_loads(text: str) -> Any:
    """Load JSON with optional orjson acceleration."""
    if orjson is not None:
        return orjson.loads(text)
    return json.loads(text)


def load_json_with_fallback(path: Path) -> Any:
    """Load a JSON file trying multiple encodings."""
    last_error = None
    for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "cp1252"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception as e:
            last_error = e
    raise RuntimeError(
        f"Failed to read JSON from: {path}\nLast error: {last_error}"
    )


# ── Record flattening ───────────────────────────────────────────────────────


def flatten_value(prefix: str, value: Any, out: dict[str, Any]) -> None:
    """Recursively flatten a nested dict/list structure into dot-separated keys."""
    if isinstance(value, dict):
        for k, v in value.items():
            nk = f"{prefix}.{k}" if prefix else str(k)
            flatten_value(nk, v, out)
    elif isinstance(value, list):
        if value and all(not isinstance(x, (dict, list)) for x in value):
            out[prefix] = " ".join(str(x) for x in value)
        else:
            for i, v in enumerate(value):
                flatten_value(f"{prefix}[{i}]", v, out)
    else:
        out[prefix] = value


def flatten_record(rec: Any) -> dict[str, Any]:
    """Flatten a single ExifTool record (nested dict) into a flat dict."""
    out: dict[str, Any] = {}
    if isinstance(rec, dict):
        for k, v in rec.items():
            flatten_value(str(k), v, out)
    return out


def ensure_records_list(records: Any) -> list[dict[str, Any]]:
    """Normalise records to a list of dicts."""
    if isinstance(records, list):
        return records
    if isinstance(records, dict):
        return [records]
    raise RuntimeError("Invalid telemetry JSON format: expected list or dict.")


# ── Datetime / value parsing ────────────────────────────────────────────────


def parse_exif_datetime(val: Any) -> Optional[datetime]:
    """Parse an ExifTool datetime string (format '%Y:%m:%d %H:%M:%S.%f')."""
    if not val:
        return None
    txt = str(val).strip().replace("Z", "").strip()
    try:
        if "." in txt:
            return datetime.strptime(txt, "%Y:%m:%d %H:%M:%S.%f").replace(
                tzinfo=timezone.utc
            )
        else:
            return datetime.strptime(txt, "%Y:%m:%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
    except Exception:
        return None


def parse_float_maybe(val: Any) -> Optional[float]:
    """Safely parse a float from various input types."""
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        try:
            return float(str(val).split()[0].replace(",", "."))
        except Exception:
            return None


def parse_gps_coord(val: Any) -> Optional[float]:
    """Parse a GPS coordinate to decimal degrees.

    Accepts:
      - ExifTool format: ``"54 deg 19' 51.3\" N"`` or ``"54 19 51.3 N"``
      - Decimal degrees: ``54.3307535`` (float or string)
    """
    if not val:
        return None

    # Already a number or parseable as decimal degree
    try:
        return float(val)
    except (ValueError, TypeError):
        pass

    # ExifTool deg/min/sec format
    txt = str(val)
    try:
        parts = txt.replace("deg", "").replace("'", "").replace('"', "").split()
        deg = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        hemi = parts[3]
        dec = deg + minutes / 60 + seconds / 3600
        if hemi in ("S", "W"):
            dec = -dec
        return dec
    except Exception:
        return None


# ── Distance calculation ────────────────────────────────────────────────────


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two GPS coordinates."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── GPS anchor / value lookup ───────────────────────────────────────────────


def get_all_values_by_suffix(rec: dict, suffix: str) -> dict[str, Any]:
    """Get all values from a record whose keys end with ':suffix'."""
    if not rec or not suffix:
        return {}
    flat = flatten_record(rec)
    wanted = ":" + suffix
    return {
        k[: -len(wanted)]: v
        for k, v in flat.items()
        if k.startswith("Doc") and k.endswith(wanted)
    }


def get_value_by_suffix_for_prefix(
    rec: dict, prefix: str, suffix: str
) -> Optional[Any]:
    """Get a single value from a record by 'prefix:suffix' key."""
    if not rec or not prefix or not suffix:
        return None
    return flatten_record(rec).get(f"{prefix}:{suffix}")


def find_gps_anchor(records: list[dict[str, Any]]) -> Optional[datetime]:
    """Find the absolute UTC start time from GPSDateTime anchors."""
    records = ensure_records_list(records)
    for rec in records:
        if not isinstance(rec, dict):
            continue
        datetimes = get_all_values_by_suffix(rec, "GPSDateTime")
        for prefix, dt_str in datetimes.items():
            dt = parse_exif_datetime(dt_str)
            if dt is None:
                continue
            st_val = get_value_by_suffix_for_prefix(rec, prefix, "SampleTime")
            if st_val is not None:
                st_sec = parse_float_maybe(str(st_val).replace(" s", ""))
                if st_sec is not None:
                    return dt - timedelta(seconds=st_sec)
            ts_val = get_value_by_suffix_for_prefix(rec, prefix, "TimeStamp")
            if ts_val is not None:
                ts_sec = parse_float_maybe(ts_val)
                if ts_sec is not None:
                    return dt - timedelta(seconds=ts_sec)
    return None


# ── Speed-at-time lookup ────────────────────────────────────────────────────


def speed_at_time(
    samples: list[tuple[datetime, float]], target_dt: datetime
) -> float:
    """Linear interpolation of speed at a given datetime."""
    if not samples:
        return 0.0
    times = [dt for dt, _ in samples]
    idx = bisect_left(times, target_dt)
    if idx == 0:
        return max(0.0, samples[0][1])
    if idx >= len(samples):
        return max(0.0, samples[-1][1])
    t0, s0 = samples[idx - 1]
    t1, s1 = samples[idx]
    dt_total = (t1 - t0).total_seconds()
    if dt_total == 0:
        return max(0.0, s0)
    ratio = (target_dt - t0).total_seconds() / dt_total
    return max(0.0, s0 + (s1 - s0) * ratio)


# ─── ExifTool invocation ────────────────────────────────────────────────────


def load_telemetry_exiftool(video_path: str | Path) -> dict[str, Any]:
    """Run exiftool on a video file and return the parsed JSON record."""
    cmd = ["exiftool", "-ee", "-G3", "-j", str(video_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ExifTool error:\n" + result.stderr)
    data = json.loads(result.stdout)
    if not data:
        return {}
    return data[0]


# ── JSON metadata path helpers ──────────────────────────────────────────────


def find_metadata_json(video_path: str | Path) -> Path:
    """Return the default JSON path alongside the video file."""
    return Path(video_path).with_suffix(".json")


def _set_hidden(path: Path) -> None:
    """Set the hidden attribute on Windows."""
    try:
        if os.name == "nt":
            import ctypes

            FILE_ATTRIBUTE_HIDDEN = 0x02
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs != -1:
                ctypes.windll.kernel32.SetFileAttributesW(
                    str(path), attrs | FILE_ATTRIBUTE_HIDDEN
                )
    except Exception:
        pass


def find_metadata_json_for_write(video_path: str | Path) -> Path:
    """Find or create a writable path for metadata JSON."""
    video_path = Path(video_path)
    same_dir = video_path.with_suffix(".json")
    hidden_dir = Path(tempfile.gettempdir()) / "TeleM" / "telemetry_hidden"
    hidden = hidden_dir / f"{video_path.stem}.json"
    fallback_dir = Path(tempfile.gettempdir()) / "TeleM" / "telemetry_hidden"
    fallback = fallback_dir / f"{video_path.stem}.json"
    for candidate in (same_dir, hidden, fallback):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with open(candidate, "a", encoding="utf-8"):
                pass
            return candidate
        except Exception:
            continue
    try:
        tmp = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f"_{video_path.stem}.json",
            dir=tempfile.gettempdir(),
        )
        tmp.close()
        return Path(tmp.name)
    except Exception:
        return hidden


def write_records_to_json(
    out_json: str | Path, records: list[dict[str, Any]]
) -> Path:
    """Write telemetry records to a JSON file with fallback."""
    try:
        out_json_parent = Path(out_json).parent
        out_json_parent.mkdir(parents=True, exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        return Path(out_json)
    except Exception as exc:
        print(f"write_records_to_json: failed writing to {out_json}: {exc}", flush=True)

    try:
        tmp = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f"_{Path(out_json).stem}.json",
            dir=tempfile.gettempdir(),
        )
        tmp.close()
        with open(tmp.name, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        _set_hidden(Path(tmp.name))
        return Path(tmp.name)
    except Exception as exc:
        raise RuntimeError(f"Failed to write metadata JSON: {exc}") from exc


# ── Data extraction: ISO ────────────────────────────────────────────────────


def extract_iso_samples(
    records: list[dict[str, Any]]
) -> list[tuple[datetime, int]]:
    """Extract ISO samples from ExifTool records."""
    records = ensure_records_list(records)
    samples: list[tuple[datetime, int]] = []

    for rec in records:
        flat = flatten_record(rec)

        prefixes: set[str] = set()
        for key in flat.keys():
            if key.startswith("Doc") and (
                key.endswith(":ISOSpeeds")
                or key.endswith(":ISO")
                or key.endswith(":ISOSpeed")
                or key.endswith(":ISOSpeedRatings")
            ):
                prefixes.add(key.split(":")[0])

        for prefix in prefixes:
            iso_raw = (
                flat.get(f"{prefix}:ISOSpeeds")
                or flat.get(f"{prefix}:ISO")
                or flat.get(f"{prefix}:ISOSpeed")
                or flat.get(f"{prefix}:ISOSpeedRatings")
            )
            if iso_raw is None:
                continue

            iso_txt = str(iso_raw).strip()
            iso_parts = iso_txt.split()
            if not iso_parts:
                continue
            iso_values = []
            for part in iso_parts:
                val = parse_float_maybe(part)
                if val is not None:
                    iso_values.append(int(round(val)))
            if not iso_values:
                continue

            dt = _parse_timestamp(flat, prefix)
            if dt is None:
                continue

            n_vals = len(iso_values)
            for i, val in enumerate(iso_values):
                frame_dt = dt + timedelta(seconds=i / float(n_vals)) if n_vals > 1 else dt
                samples.append((frame_dt, val))

    samples.sort(key=lambda x: x[0])
    return _dedupe_samples(samples)


# ── Data extraction: Exposure ───────────────────────────────────────────────


def extract_exposure_samples(
    records: list[dict[str, Any]]
) -> list[tuple[datetime, int]]:
    """Extract exposure time samples (denominator of '1/xxx') from ExifTool records."""
    records = ensure_records_list(records)
    samples: list[tuple[datetime, int]] = []

    for rec in records:
        flat = flatten_record(rec)

        prefixes: set[str] = set()
        for key in flat.keys():
            if key.startswith("Doc") and key.endswith(":ExposureTimes"):
                prefixes.add(key.split(":")[0])

        for prefix in prefixes:
            raw = flat.get(f"{prefix}:ExposureTimes")
            if raw is None:
                continue

            txt = str(raw).strip()
            parts = txt.split()
            if not parts:
                continue
            exp_values = []
            for part in parts:
                try:
                    if "/" in part:
                        numerator, denominator = part.split("/")
                        exp_values.append(int(round(float(denominator))))
                    else:
                        val = parse_float_maybe(part)
                        if val is not None:
                            exp_values.append(int(round(val)))
                except Exception:
                    pass
            if not exp_values:
                continue

            dt = _parse_timestamp(flat, prefix)
            if dt is None:
                continue

            n_vals = len(exp_values)
            for i, val in enumerate(exp_values):
                frame_dt = dt + timedelta(seconds=i / float(n_vals)) if n_vals > 1 else dt
                samples.append((frame_dt, val))

    samples.sort(key=lambda x: x[0])
    return _dedupe_samples(samples)


# ── Data extraction: Temperature ────────────────────────────────────────────


def extract_temperature_samples(
    records: list[dict[str, Any]]
) -> list[tuple[datetime, int]]:
    """Extract camera temperature samples from ExifTool records."""
    records = ensure_records_list(records)
    samples: list[tuple[datetime, int]] = []

    for rec in records:
        flat = flatten_record(rec)

        prefixes: set[str] = set()
        for key in flat.keys():
            if key.startswith("Doc") and key.endswith(":CameraTemperature"):
                prefixes.add(key.split(":")[0])

        for prefix in prefixes:
            raw = flat.get(f"{prefix}:CameraTemperature")
            if raw is None:
                continue
            temp_val = parse_float_maybe(raw)
            if temp_val is None:
                continue
            temp_val = int(round(temp_val))

            dt = _parse_timestamp(flat, prefix)
            if dt is None:
                continue

            samples.append((dt, temp_val))

    samples.sort(key=lambda x: x[0])
    return _dedupe_samples(samples)


# ── Data extraction: Speed ──────────────────────────────────────────────────


def extract_speed_samples(
    records: list[dict[str, Any]], prefer_3d: bool = True
) -> list[tuple[datetime, float]]:
    """Extract speed samples (2D or 3D) from ExifTool records."""
    records = ensure_records_list(records)
    samples: list[tuple[datetime, float]] = []

    for rec in records:
        flat = flatten_record(rec)

        prefixes: set[str] = set()
        for key in flat.keys():
            if key.startswith("Doc") and (
                key.endswith(":GPSSpeed") or key.endswith(":GPSSpeed3D")
            ):
                prefixes.add(key.split(":")[0])

        for prefix in prefixes:
            speed_2d = parse_float_maybe(flat.get(f"{prefix}:GPSSpeed"))
            speed_3d = parse_float_maybe(flat.get(f"{prefix}:GPSSpeed3D"))

            if prefer_3d:
                speed = speed_3d if speed_3d not in (None, 0.0) else speed_2d
            else:
                speed = speed_2d if speed_2d not in (None, 0.0) else speed_3d

            if speed is None:
                continue

            dt = _parse_timestamp(flat, prefix)
            if dt is None:
                continue

            samples.append((dt, max(0.0, speed)))

    samples.sort(key=lambda x: x[0])
    return _dedupe_samples(samples)


# ── Data extraction: Altitude ───────────────────────────────────────────────


def extract_altitude_samples(
    records: list[dict[str, Any]]
) -> list[tuple[datetime, float]]:
    """Extract altitude samples from ExifTool records."""
    records = ensure_records_list(records)
    samples: list[tuple[datetime, float]] = []

    for rec in records:
        flat = flatten_record(rec)

        prefixes: set[str] = set()
        for key in flat.keys():
            if key.startswith("Doc") and key.endswith(":GPSAltitude"):
                prefixes.add(key.split(":")[0])

        for prefix in prefixes:
            raw_alt = flat.get(f"{prefix}:GPSAltitude")
            alt = parse_float_maybe(raw_alt)
            if alt is None:
                continue

            dt = _parse_timestamp(flat, prefix)
            if dt is None:
                continue

            samples.append((dt, alt))

    samples.sort(key=lambda x: x[0])
    return _dedupe_samples(samples)


# ── Data extraction: Track (lat/lon → cumulative distance) ─────────────────


def extract_track_samples(
    records: list[dict[str, Any]]
) -> list[tuple[datetime, float]]:
    """Extract track (GPS position) samples as cumulative distance in metres."""
    records = ensure_records_list(records)
    points: list[tuple[datetime, float, float]] = []

    for rec in records:
        flat = flatten_record(rec)

        for key, val in flat.items():
            if not key.endswith(":GPSDateTime"):
                continue

            prefix = key.split(":")[0]
            dt = parse_exif_datetime(val)
            if dt is None:
                continue

            raw_lat = flat.get(f"{prefix}:GPSLatitude")
            raw_lon = flat.get(f"{prefix}:GPSLongitude")
            lat = parse_gps_coord(raw_lat)
            lon = parse_gps_coord(raw_lon)

            if lat is None or lon is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue

            points.append((dt, lat, lon))

    points.sort(key=lambda x: x[0])

    # Deduplicate
    deduped: list[tuple[datetime, float, float]] = []
    for dt, lat, lon in points:
        if not deduped or dt != deduped[-1][0]:
            deduped.append((dt, lat, lon))

    # Cumulative distance
    cumulative: list[tuple[datetime, float]] = []
    total_m = 0.0
    for i, (dt, lat, lon) in enumerate(deduped):
        if i > 0:
            _, prev_lat, prev_lon = deduped[i - 1]
            total_m += haversine_m(prev_lat, prev_lon, lat, lon)
        cumulative.append((dt, total_m))

    return cumulative


def extract_gps_track(
    records: list[dict[str, Any]]
) -> list[tuple[datetime, float, float]]:
    """Extract raw GPS lat/lon track points (for map rendering).

    Unlike ``extract_track_samples`` which returns cumulative distance,
    this returns the actual geographic coordinates.
    """
    records = ensure_records_list(records)
    points: list[tuple[datetime, float, float]] = []

    for rec in records:
        flat = flatten_record(rec)
        for key, val in flat.items():
            if not key.endswith(":GPSDateTime"):
                continue
            prefix = key.split(":")[0]
            dt = parse_exif_datetime(val)
            if dt is None:
                continue
            raw_lat = flat.get(f"{prefix}:GPSLatitude")
            raw_lon = flat.get(f"{prefix}:GPSLongitude")
            lat = parse_gps_coord(raw_lat)
            lon = parse_gps_coord(raw_lon)
            if lat is None or lon is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            points.append((dt, lat, lon))

    points.sort(key=lambda x: x[0])

    # Deduplicate by timestamp
    deduped: list[tuple[datetime, float, float]] = []
    for dt, lat, lon in points:
        if not deduped or dt != deduped[-1][0]:
            deduped.append((dt, lat, lon))
    return deduped


# ── Data extraction: ExifTool flat-dict helpers ─────────────────────────────


def extract_samples_exiftool(
    flat: dict[str, Any]
) -> list[tuple[datetime, float]]:
    """Extract speed samples from a flat ExifTool dict (legacy format)."""
    samples: list[tuple[datetime, float]] = []

    prefixes: set[str] = set()
    for key in flat.keys():
        if key.startswith("Doc") and ":GPSDateTime" in key:
            prefixes.add(key.split(":")[0])

    for prefix in sorted(prefixes):
        dt_str = flat.get(f"{prefix}:GPSDateTime")
        speed = flat.get(f"{prefix}:GPSSpeed")
        if not dt_str:
            continue

        try:
            dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S.%f").replace(
                tzinfo=None
            )
        except Exception:
            try:
                dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").replace(
                    tzinfo=None
                )
            except Exception:
                continue

        try:
            speed = float(speed) if speed is not None else 0.0
        except Exception:
            speed = 0.0

        samples.append((dt, speed))

    samples.sort(key=lambda x: x[0])
    return samples


def extract_altitude_samples_exiftool(
    flat: dict[str, Any]
) -> list[tuple[datetime, float]]:
    """Extract altitude samples from a flat ExifTool dict (legacy format)."""
    samples: list[tuple[datetime, float]] = []

    prefixes: set[str] = set()
    for key in flat.keys():
        if key.startswith("Doc") and ":GPSDateTime" in key:
            prefixes.add(key.split(":")[0])

    for prefix in sorted(prefixes):
        dt_str = flat.get(f"{prefix}:GPSDateTime")
        alt_str = flat.get(f"{prefix}:GPSAltitude")
        if not dt_str:
            continue

        try:
            dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S.%f").replace(
                tzinfo=None
            )
        except Exception:
            try:
                dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").replace(
                    tzinfo=None
                )
            except Exception:
                continue

        alt = parse_float_maybe(alt_str)
        if alt is None:
            alt = 0.0
        samples.append((dt, alt))

    samples.sort(key=lambda x: x[0])
    return samples


# ── Smoothing ───────────────────────────────────────────────────────────────


def smooth_speed_values(values: list[float], window: int = 5) -> list[float]:
    """Simple moving-window average smoother."""
    out: list[float] = []
    for i in range(len(values)):
        acc = 0.0
        count = 0
        for j in range(max(0, i - window), min(len(values), i + window + 1)):
            acc += values[j]
            count += 1
        out.append(acc / count if count else values[i])
    return out


def moving_average(values: list[float], window: int) -> list[float]:
    """Moving average filter."""
    if window <= 1 or not values:
        return values[:]
    out: list[float] = []
    acc = 0.0
    queue: list[float] = []
    for v in values:
        queue.append(v)
        acc += v
        if len(queue) > window:
            acc -= queue.pop(0)
        out.append(acc / len(queue))
    return out


def exponential_moving_average(values: list[float], alpha: float) -> list[float]:
    """Exponential moving average filter."""
    if not values:
        return values[:]
    alpha = max(0.01, min(1.0, alpha))
    out: list[float] = [values[0]]
    prev = values[0]
    for v in values[1:]:
        prev = alpha * v + (1.0 - alpha) * prev
        out.append(prev)
    return out


def smooth_speed_samples(
    samples: list[tuple[datetime, float]],
    method: str = "off",
    strength: float = 3,
) -> list[tuple[datetime, float]]:
    """Smooth speed samples using the specified method."""
    if not samples or method == "off":
        return samples
    times = [t for t, _ in samples]
    vals = [v for _, v in samples]
    if method == "moving_average":
        smoothed = moving_average(vals, max(1, int(round(strength))))
    elif method == "ema":
        smoothed = exponential_moving_average(vals, max(0.05, min(1.0, float(strength))))
    else:
        smoothed = vals
    return list(zip(times, smoothed))


# ── Interpolation ───────────────────────────────────────────────────────────


def _normalise_dt(target_dt: datetime) -> datetime:
    """Strip timezone info for comparison with naive datetimes."""
    if target_dt.tzinfo is not None:
        return target_dt.replace(tzinfo=None)
    return target_dt


def _normalise_samples(
    samples: list[tuple[datetime, Any]]
) -> list[tuple[datetime, Any]]:
    """Strip timezone info from all sample datetimes."""
    return [(dt.replace(tzinfo=None), v) for dt, v in samples]


def interpolate_speed(
    samples: list[tuple[datetime, float]], target_dt: datetime
) -> float:
    """Linear interpolation of speed at a given timestamp (clamped to 0)."""
    target_dt = _normalise_dt(target_dt)
    samples = _normalise_samples(samples)
    if not samples:
        return 0.0
    times = [dt for dt, _ in samples]
    idx = bisect_left(times, target_dt)
    if idx <= 0:
        if samples and target_dt < samples[0][0]:
            return 0.0
        return max(0.0, samples[0][1]) if samples else 0.0
    if idx >= len(samples):
        return max(0.0, samples[-1][1])
    t1, s1 = samples[idx - 1]
    t2, s2 = samples[idx]
    dt_total = (t2 - t1).total_seconds()
    if dt_total <= 0:
        return max(0.0, s1)
    return max(0.0, s1 + (s2 - s1) * (target_dt - t1).total_seconds() / dt_total)


def interpolate_distance(
    track_samples: list[tuple[datetime, float]], target_dt: datetime
) -> float:
    """Linear interpolation of cumulative distance at a given timestamp."""
    target_dt = _normalise_dt(target_dt)
    track_samples = _normalise_samples(track_samples)
    if not track_samples:
        return 0.0
    times = [dt for dt, _ in track_samples]
    idx = bisect_left(times, target_dt)
    if idx <= 0:
        if track_samples and target_dt < track_samples[0][0]:
            return 0.0
        return track_samples[0][1] if track_samples else 0.0
    if idx >= len(track_samples):
        return track_samples[-1][1]
    t1, d1 = track_samples[idx - 1]
    t2, d2 = track_samples[idx]
    dt_total = (t2 - t1).total_seconds()
    if dt_total <= 0:
        return d1
    return d1 + (d2 - d1) * (target_dt - t1).total_seconds() / dt_total


def interpolate_altitude(
    samples: list[tuple[datetime, float]], target_dt: datetime
) -> float:
    """Linear interpolation of altitude at a given timestamp."""
    target_dt = _normalise_dt(target_dt)
    samples = _normalise_samples(samples)
    if not samples:
        return 0.0
    times = [dt for dt, _ in samples]
    idx = bisect_left(times, target_dt)
    if idx <= 0:
        if samples and target_dt < samples[0][0]:
            return samples[0][1]
        return samples[0][1] if samples else 0.0
    if idx >= len(samples):
        return samples[-1][1]
    t1, s1 = samples[idx - 1]
    t2, s2 = samples[idx]
    dt_total = (t2 - t1).total_seconds()
    if dt_total <= 0:
        return s1
    return s1 + (s2 - s1) * (target_dt - t1).total_seconds() / dt_total


def interpolate_iso(
    samples: list[tuple[datetime, int]], target_dt: datetime
) -> int:
    """Step interpolation of ISO at a given timestamp."""
    target_dt = _normalise_dt(target_dt)
    samples = _normalise_samples(samples)
    if not samples:
        return 0
    times = [dt for dt, _ in samples]
    idx = bisect_left(times, target_dt)
    if idx <= 0:
        return samples[0][1]
    if idx >= len(samples):
        return samples[-1][1]
    return samples[idx - 1][1]


def interpolate_exposure(
    samples: list[tuple[datetime, int]], target_dt: datetime
) -> int:
    """Step interpolation of exposure at a given timestamp."""
    target_dt = _normalise_dt(target_dt)
    samples = _normalise_samples(samples)
    if not samples:
        return 0
    times = [dt for dt, _ in samples]
    idx = bisect_left(times, target_dt)
    if idx <= 0:
        return samples[0][1]
    if idx >= len(samples):
        return samples[-1][1]
    return samples[idx - 1][1]


def interpolate_temperature(
    samples: list[tuple[datetime, int]], target_dt: datetime
) -> int:
    """Step interpolation of temperature at a given timestamp."""
    target_dt = _normalise_dt(target_dt)
    samples = _normalise_samples(samples)
    if not samples:
        return 0
    times = [dt for dt, _ in samples]
    idx = bisect_left(times, target_dt)
    if idx <= 0:
        return samples[0][1]
    if idx >= len(samples):
        return samples[-1][1]
    return samples[idx - 1][1]


def interpolate_value(
    samples: list[tuple[datetime, float]], target_dt: datetime
) -> float:
    """Generic step interpolation for scalar values (power, atemp, hr, cad)."""
    if not samples:
        return 0
    target_dt = _normalise_dt(target_dt)
    samples = _normalise_samples(samples)
    times = [dt for dt, _ in samples]
    idx = bisect_left(times, target_dt)
    if idx <= 0:
        return samples[0][1]
    if idx >= len(samples):
        return samples[-1][1]
    return samples[idx - 1][1]


# ── Timestamp helper ────────────────────────────────────────────────────────


def _parse_timestamp(
    flat: dict[str, Any], prefix: str
) -> Optional[datetime]:
    """Parse a timestamp from a flattened record using GPSDateTime, SampleTime, or TimeStamp."""
    gps_dt = flat.get(f"{prefix}:GPSDateTime")
    if gps_dt is not None:
        dt = parse_exif_datetime(gps_dt)
        if dt is not None:
            return dt

    st = parse_float_maybe(flat.get(f"{prefix}:SampleTime"))
    if st is not None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=st)

    ts = parse_float_maybe(flat.get(f"{prefix}:TimeStamp"))
    if ts is not None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=ts)

    return None


# ── Sample deduplication ────────────────────────────────────────────────────


def _dedupe_samples(
    samples: list[tuple[datetime, Any]],
) -> list[tuple[datetime, Any]]:
    """Remove consecutive duplicate timestamps."""
    deduped: list[tuple[datetime, Any]] = []
    for dt, val in samples:
        if not deduped or dt != deduped[-1][0]:
            deduped.append((dt, val))
        else:
            deduped[-1] = (dt, val)
    return deduped


# ── Formatters ──────────────────────────────────────────────────────────────


def format_time(t: Any) -> str:
    """Normalise a time value to string."""
    if isinstance(t, str):
        return t.replace("T", " ").replace("-", ":").replace("Z", "")
    return str(t)


def format_raw_value(key: str, raw: Any) -> str:
    """Format a raw ExifTool value for display."""
    if raw is None:
        return ""
    txt = str(raw).strip()
    if "Binary data" in txt:
        return ""
    if key.endswith("ExposureTimes"):
        return txt.split()[0]
    if key.endswith("ISOSpeeds"):
        return txt.split()[0]
    if key.endswith("CameraTemperature"):
        parts = txt.split()
        try:
            return f"{int(round(float(parts[0])))} C"
        except Exception:
            return txt
    parts = txt.split()
    if len(parts) > 1 and all(
        p.replace(".", "", 1).replace("-", "", 1).isdigit() for p in parts[:3]
    ):
        return parts[0]
    return txt


# ── Rotation helpers ────────────────────────────────────────────────────────


def get_rotation_from_metadata(records: list[dict[str, Any]]) -> int:
    """Extract rotation from ExifTool metadata (AutoRotation / Rotation tags)."""
    for rec in ensure_records_list(records):
        if not isinstance(rec, dict):
            continue
        flat = flatten_record(rec)
        if "Main:AutoRotation" in flat:
            ar = flat["Main:AutoRotation"]
            if ar:
                ar_lower = str(ar).lower().strip()
                if ar_lower == "down":
                    return 180
                elif ar_lower == "up":
                    return 0
                elif ar_lower == "left":
                    return 270
                elif ar_lower == "right":
                    return 90
        if "Main:Rotation" in flat:
            try:
                return int(float(str(flat["Main:Rotation"]).strip())) % 360
            except (ValueError, TypeError):
                pass
    return 0


def get_container_rotation(ffprobe_exe: str, video_path: str | Path) -> int:
    """Read the 'rotate' tag from the MP4 container metadata using ffprobe."""
    if isinstance(video_path, list):
        video_path = video_path[0] if video_path else None
    if video_path is None:
        return 0
    try:
        p = subprocess.run(
            [
                ffprobe_exe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream_tags=rotate:stream_side_data=rotation",
                "-of",
                "json",
                str(video_path),
            ],
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            return 0
        data = json.loads(p.stdout)
        streams = data.get("streams", [])
        if streams:
            rotate_tag = streams[0].get("tags", {}).get("rotate", None)
            if rotate_tag is not None:
                return int(float(str(rotate_tag))) % 360
            for sd in streams[0].get("side_data_list", []):
                rot = sd.get("rotation", None)
                if rot is not None:
                    return abs(int(float(str(rot)))) % 360
    except Exception:
        pass
    return 0
