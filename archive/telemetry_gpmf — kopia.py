"""GPMF (GoPro Metadata Format) binary stream parser.

Handles extraction of GPMF binary streams from video files via ffmpeg,
parsing the binary structure, and conversion to ExifTool-compatible JSON format.
"""

from __future__ import annotations

import ast
import json
import os
import shlex
import struct
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ── Stream detection & extraction ───────────────────────────────────────────


def find_gpmf_stream_index(
    video_path: str | Path, ffprobe_exe: str = "ffprobe"
) -> Optional[int]:
    """Find the index of the GPMF metadata stream in a video file.

    Args:
        video_path: Path to the video file.
        ffprobe_exe: Path to ffprobe executable.

    Returns:
        Stream index or None if not found.
    """
    try:
        p = subprocess.run(
            [ffprobe_exe, "-v", "error", "-show_streams", "-of", "json", str(video_path)],
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            return None
        data = json.loads(p.stdout)
        fallback_index = None
        for stream in data.get("streams", []):
            codec_name = str(stream.get("codec_name", "")).lower()
            codec_tag = str(stream.get("codec_tag_string", "")).lower()
            handler = str(stream.get("tags", {}).get("handler_name", "")).lower()
            if any(x in codec_name for x in ("gpmd", "gpmf")) or any(
                x in codec_tag for x in ("gpmd", "gpmf")
            ):
                return int(stream.get("index", 0))
            if stream.get("codec_type", "").lower() == "data":
                if "go pro" in handler and "met" in handler:
                    return int(stream.get("index", 0))
                if fallback_index is None:
                    fallback_index = int(stream.get("index", 0))
        return fallback_index
    except Exception:
        return None


def extract_gpmf(
    video_path: str | Path,
    ffmpeg_exe: str = "ffmpeg",
    ffprobe_exe: str = "ffprobe",
) -> bytes:
    """Extract the raw GPMF binary stream from a video file using ffmpeg.

    Args:
        video_path: Path to the video file.
        ffmpeg_exe: Path to ffmpeg executable.
        ffprobe_exe: Path to ffprobe executable.

    Returns:
        Raw GPMF binary data.

    Raises:
        RuntimeError: If the GPMF stream cannot be found or extracted.
    """
    stream_index = find_gpmf_stream_index(video_path, ffprobe_exe=ffprobe_exe)
    if stream_index is None:
        raise RuntimeError("No GPMF stream found in the file.")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
    tmp.close()
    try:
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i",
            str(video_path),
            "-map",
            f"0:{stream_index}",
            "-c",
            "copy",
            "-f",
            "data",
            tmp.name,
        ]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0:
            raise RuntimeError(
                "GPMF stream extraction failed.\n"
                f"Command: {shlex.join(cmd)}\n"
                f"Return code: {p.returncode}\n"
                f"stderr:\n{(p.stderr or '').strip()}"
            )
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# ── Binary decoding ─────────────────────────────────────────────────────────


def decode_gpmf(t: str, repeat: int, payload: bytes) -> Any:
    """Decode a single GPMF field value from its raw binary payload.

    Args:
        t: GPMF type character (e.g. 'c' for ASCII, 'f' for float, 'l' for int32).
        repeat: Number of elements of this type.
        payload: Raw binary data.

    Returns:
        Decoded value (single scalar for repeat=1, tuple for repeat>1, or raw bytes).
    """
    try:
        if t == "c":
            return payload.decode("ascii", errors="ignore").rstrip("\x00")
        if t == "b":
            fmt = ">" + "b" * repeat
            vals = struct.unpack(fmt, payload)
        elif t == "B":
            fmt = ">" + "B" * repeat
            vals = struct.unpack(fmt, payload)
        elif t == "s":
            fmt = ">" + "h" * repeat
            vals = struct.unpack(fmt, payload)
        elif t == "S":
            fmt = ">" + "H" * repeat
            vals = struct.unpack(fmt, payload)
        elif t == "l":
            fmt = ">" + "i" * repeat
            vals = struct.unpack(fmt, payload)
        elif t == "L":
            fmt = ">" + "I" * repeat
            vals = struct.unpack(fmt, payload)
        elif t == "f":
            fmt = ">" + "f" * repeat
            vals = struct.unpack(fmt, payload)
        elif t == "d":
            fmt = ">" + "d" * repeat
            vals = struct.unpack(fmt, payload)
        elif t == "Q":
            fmt = ">" + "Q" * repeat
            vals = struct.unpack(fmt, payload)
        elif t == "J":
            fmt = ">" + "q" * repeat
            vals = struct.unpack(fmt, payload)
        else:
            return payload

        if repeat == 1:
            return vals[0]
        return vals
    except Exception:
        return payload


# ── GPMF structure parsing ────────────────────────────────────────────────


def parse_gpmf(data: bytes, offset: int = 0) -> list[tuple[str, Any]]:
    """Recursively parse a GPMF binary structure.

    Args:
        data: Raw GPMF binary data.
        offset: Starting offset (for recursive calls).

    Returns:
        List of (key, decoded_value) tuples.
    """
    results: list[tuple[str, Any]] = []
    while offset + 8 <= len(data):
        try:
            key = data[offset : offset + 4].decode("ascii", errors="ignore")
        except Exception:
            break
        t = chr(data[offset + 4])
        size = data[offset + 5]
        if offset + 8 > len(data):
            break
        try:
            repeat = struct.unpack(">H", data[offset + 6 : offset + 8])[0]
        except struct.error:
            break
        payload_size = size * repeat
        if payload_size < 0 or payload_size > len(data):
            break
        payload_start = offset + 8
        payload_end = payload_start + payload_size
        if payload_end > len(data):
            break
        payload = data[payload_start:payload_end]
        padded = (payload_size + 3) & ~3
        offset = payload_start + padded
        if t == "\x00":
            results.extend(parse_gpmf(payload, 0))
        else:
            results.append((key, decode_gpmf(t, repeat, payload)))
    return results


def try_decode_8byte_stmp(raw: bytes) -> Optional[float]:
    """Attempt to decode an 8-byte STMP value as uint64 (microseconds) or double.

    Args:
        raw: 8-byte payload.

    Returns:
        Seconds as float, or None on failure.
    """
    if not isinstance(raw, bytes) or len(raw) != 8:
        return None
    try:
        us = struct.unpack(">Q", raw)[0]
        if us > 0:
            return us / 1_000_000.0
    except Exception:
        pass
    try:
        return struct.unpack(">d", raw)[0]
    except Exception:
        pass
    return None


# ── GPS9 value decoding ─────────────────────────────────────────────────────


def _decode_gps9_values(
    val: Any, scal: Any
) -> list[tuple[float, float, float, float, float]]:
    """Decode GPS9 data: 9 int32 values per sample, scaled by a SCAL tuple.

    Returns:
        List of (lat, lon, alt_m, s2d, s3d) tuples.
    """
    results: list[tuple[float, float, float, float, float]] = []
    raw_vals: Optional[list[int]] = None
    if isinstance(val, (list, tuple)):
        raw_vals = list(val)
    elif isinstance(val, bytes) and len(val) > 0:
        try:
            n = len(val) // 4
            raw_vals = list(struct.unpack(f">{n}i", val[: n * 4]))
        except Exception:
            return results

    if not raw_vals or len(raw_vals) < 9:
        return results

    if not isinstance(scal, (list, tuple)):
        scal = (scal,) * 9
    s = list(scal) + [1] * max(0, 9 - len(scal))

    for i in range(0, len(raw_vals) - len(raw_vals) % 9, 9):
        chunk = raw_vals[i : i + 9]
        try:
            lat = chunk[0] / s[0] if s[0] else 0.0
            lon = chunk[1] / s[1] if s[1] else 0.0
            alt = chunk[2] / s[2] if s[2] else 0.0
            s2d = chunk[4] / s[4] if s[4] else 0.0
            s3d = chunk[5] / s[5] if s[5] else 0.0
            results.append((lat, lon, alt, s2d, s3d))
        except Exception:
            continue
    return results


# ── Conversion to ExifTool JSON format ───────────────────────────────────────


def to_exiftool_json(
    parsed: list[tuple[str, Any]], source_file: str
) -> list[dict[str, Any]]:
    """Convert parsed GPMF data to ExifTool-compatible JSON format.

    Args:
        parsed: List of (key, decoded_value) tuples from parse_gpmf().
        source_file: Source video file path.

    Returns:
        List containing a single dict with ExifTool-style key-value pairs.
    """
    out: dict[str, Any] = {"SourceFile": source_file}
    doc = 1
    scal = None
    last_gpsu_dt: Optional[datetime] = None
    current_block_start_dt: Optional[datetime] = None

    def _fmt_dt(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y:%m:%d %H:%M:%S.%f")[:-3]

    def _parse_int32_values(val: Any) -> list[int]:
        if isinstance(val, (list, tuple)):
            return list(val)
        if isinstance(val, bytes):
            try:
                n = len(val) // 4
                return list(struct.unpack(f">{n}i", val[: n * 4]))
            except Exception:
                return []
        return []

    for key, val in parsed:
        if key == "SCAL":
            scal = val

        elif key == "GPSU":
            try:
                if isinstance(val, (list, tuple)) and len(val) >= 7:
                    year = int(val[0])
                    month = int(val[1])
                    day = int(val[2])
                    hour = int(val[3])
                    minute = int(val[4])
                    sec = int(val[5])
                    ms = int(val[6])

                    last_gpsu_dt = datetime(
                        year, month, day, hour, minute, sec, ms * 1000,
                        tzinfo=timezone.utc,
                    )
                    current_block_start_dt = last_gpsu_dt
                    out[f"Doc{doc}:GPSDateTime"] = _fmt_dt(last_gpsu_dt)
                    out[f"Doc{doc}:SampleTime"] = "0.000"
                    print(
                        "GPSU decoded:", out[f"Doc{doc}:GPSDateTime"], flush=True
                    )
            except Exception as e:
                print("GPSU decode failed:", e, flush=True)

        elif key in ("GPS5", "GPS9"):
            values = _parse_int32_values(val)
            step = 5 if key == "GPS5" else 9

            if len(values) < step:
                continue

            usable = len(values) - (len(values) % step)

            if isinstance(scal, (list, tuple)):
                s = list(scal)[:step]
                if len(s) < step:
                    s += [1] * (step - len(s))
            else:
                s = [1.0] * step

            block_doc = doc

            for i in range(0, usable, step):
                chunk = values[i : i + step]

                try:
                    if key == "GPS5":
                        lat = chunk[0] / s[0] if s[0] else 0.0
                        lon = chunk[1] / s[1] if s[1] else 0.0
                        alt = chunk[2] / s[2] if s[2] else 0.0
                        s2d = chunk[3] / s[3] if s[3] else 0.0
                        s3d = chunk[4] / s[4] if s[4] else 0.0
                        ts_val = None
                    else:
                        lat = chunk[0] / s[0] if s[0] else 0.0
                        lon = chunk[1] / s[1] if s[1] else 0.0
                        alt = chunk[2] / s[2] if s[2] else 0.0
                        s2d = chunk[4] / s[4] if s[4] else 0.0
                        s3d = chunk[5] / s[5] if s[5] else 0.0
                        ts_val = chunk[8]

                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue

                    if abs(s2d) > 300:
                        s2d = 0.0
                    if abs(s3d) > 300:
                        s3d = 0.0

                    prefix = f"Doc{block_doc}" if i == 0 else f"Doc{block_doc}-{i // step}"

                    out[f"{prefix}:GPSLatitude"] = lat
                    out[f"{prefix}:GPSLongitude"] = lon
                    out[f"{prefix}:GPSAltitude"] = f"{alt} m"
                    out[f"{prefix}:GPSSpeed"] = s2d
                    out[f"{prefix}:GPSSpeed3D"] = s3d

                    if ts_val is not None:
                        out[f"{prefix}:TimeStamp"] = str(ts_val)

                    if current_block_start_dt is not None and key == "GPS9":
                        sample_idx = i // step
                        sample_dt = current_block_start_dt + timedelta(
                            seconds=sample_idx * 0.1
                        )
                        out[f"{prefix}:GPSDateTime"] = _fmt_dt(sample_dt)
                        out[f"{prefix}:SampleTime"] = f"{sample_idx * 0.1:.3f}"

                except Exception:
                    continue

            doc += 1

        elif key == "GPSA":
            if isinstance(val, bytes):
                out[f"Doc{doc}:GPSAltitudeSystem"] = (
                    val.decode("ascii", errors="ignore").strip("\x00")
                )
            else:
                out[f"Doc{doc}:GPSAltitudeSystem"] = str(val)

        elif key == "TMPC":
            out[f"Doc{doc}:CameraTemperature"] = f"{val} C"

        elif key == "SHUT":
            if isinstance(val, (list, tuple)):
                exp = " ".join([f"1/{int(1/x)}" if x != 0 else "0" for x in val])
            else:
                exp = str(val)
            out[f"Doc{doc}:ExposureTimes"] = exp

        elif key == "ISOE":
            out[f"Doc{doc}:ISO"] = val

        elif key == "STMP":
            sample_time = val
            if isinstance(val, bytes):
                try:
                    sample_time = float(val.decode("ascii", errors="ignore"))
                except Exception:
                    try:
                        sample_time = float(
                            ast.literal_eval(val.decode("ascii", errors="ignore"))
                        )
                    except Exception:
                        sample_time = try_decode_8byte_stmp(val)
            out[f"Doc{doc}:SampleTime"] = (
                sample_time if sample_time is None else str(sample_time)
            )

        elif key == "TSMP":
            timestamp = val
            if isinstance(val, bytes):
                try:
                    timestamp = float(val.decode("ascii", errors="ignore"))
                except Exception:
                    try:
                        timestamp = float(
                            ast.literal_eval(val.decode("ascii", errors="ignore"))
                        )
                    except Exception:
                        timestamp = None
            out[f"Doc{doc}:TimeStamp"] = timestamp

    gps_dt_count = sum(1 for k in out if k.endswith(":GPSDateTime"))
    print(f"[GPMF] GPSDateTime fields generated: {gps_dt_count}", flush=True)

    return [out]


def gpmf_to_exiftool_json(
    video_path: str | Path,
    ffmpeg_exe: str = "ffmpeg",
    ffprobe_exe: str = "ffprobe",
) -> list[dict[str, Any]]:
    """Extract GPMF data from a video file and convert to ExifTool JSON format.

    Args:
        video_path: Path to the video file.
        ffmpeg_exe: Path to ffmpeg executable.
        ffprobe_exe: Path to ffprobe executable.

    Returns:
        List with one dict of ExifTool-style key-value pairs.
    """
    data = extract_gpmf(video_path, ffmpeg_exe=ffmpeg_exe, ffprobe_exe=ffprobe_exe)
    parsed = parse_gpmf(data)
    keys_found = sorted(set(k for k, _ in parsed))
    print(f"[GPMF] Keys: {keys_found}", flush=True)
    print(
        f"[GPMF] GPS5={'GPS5' in keys_found} GPS9={'GPS9' in keys_found} "
        f"GPSU={'GPSU' in keys_found}  records={len(parsed)}",
        flush=True,
    )
    return to_exiftool_json(parsed, str(video_path))
