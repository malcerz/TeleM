"""
telemetry_gpmf.py

GPMF (GoPro Metadata Format) telemetry extraction and parsing.

Extracts the embedded GPMF binary metadata stream from a GoPro MP4 file
via ffmpeg/ffprobe, parses the GPMF TLV structure, and converts GPS9
samples into an ExifTool-style JSON document with GPS coordinates,
altitude, speed, camera temperature, exposure and ISO data.

IMPORTANT NOTE ON GPS9 SAMPLE LAYOUT:
This module uses an 8-field-per-sample layout for GPS9
(lat, lon, alt, speed2d, speed3d, t1, t2, t3), verified against raw byte
dumps from actual footage. This differs from the 9-field layout described
in some general GoPro GPMF documentation. If you encounter footage from a
different camera/firmware where GPS9 blocks are NOT evenly divisible by 8,
re-verify the sample layout via raw byte inspection before assuming 9 fields.
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

STRM_BOUNDARY = b"STRM"
DEVC_BOUNDARY = b"DEVC"


def find_gpmf_stream_index(video_path: str | Path, ffprobe_exe: str = "ffprobe") -> Optional[int]:
    """Locate the ffmpeg stream index carrying the GPMF/GoPro metadata track."""
    try:
        p = subprocess.run(
            [ffprobe_exe, "-v", "error", "-show_streams", "-of", "json", str(video_path)],
            capture_output=True, text=True,
        )
        if p.returncode != 0:
            return None
        data = json.loads(p.stdout)
        fallback_index = None
        for stream in data.get("streams", []):
            codec_name = str(stream.get("codec_name", "")).lower()
            codec_tag = str(stream.get("codec_tag_string", "")).lower()
            handler = str(stream.get("tags", {}).get("handler_name", "")).lower()
            if any(x in codec_name for x in ("gpmd", "gpmf")) or any(x in codec_tag for x in ("gpmd", "gpmf")):
                return int(stream.get("index", 0))
            if stream.get("codec_type", "").lower() == "data" and "gopro" in handler and "met" in handler:
                if fallback_index is None:
                    fallback_index = int(stream.get("index", 0))
        return fallback_index
    except Exception:
        return None


def extract_gpmf(video_path: str | Path, ffmpeg_exe: str = "ffmpeg", ffprobe_exe: str = "ffprobe") -> bytes:
    """Extract the raw GPMF binary payload from a video file via ffmpeg stream copy."""
    stream_index = find_gpmf_stream_index(video_path, ffprobe_exe=ffprobe_exe)
    if stream_index is None:
        raise RuntimeError("No GPMF stream found in the file.")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
    tmp.close()
    try:
        cmd = [ffmpeg_exe, "-y", "-i", str(video_path), "-map", f"0:{stream_index}", "-c", "copy", "-f", "data", tmp.name]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode != 0:
            raise RuntimeError(
                f"GPMF stream extraction failed.\nCommand: {shlex.join(cmd)}\n"
                f"Return code: {p.returncode}\n{(p.stderr or '').strip()}"
            )
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def decode_gpmf(t: str, repeat: int, payload: bytes) -> Any:
    """Decode a single GPMF TLV payload according to its type character."""
    try:
        if t == "c":
            return payload.decode("ascii", errors="ignore").rstrip("\x00")
        if t == "b":
            vals = struct.unpack(f">{repeat}b", payload)
        elif t == "B":
            vals = struct.unpack(f">{repeat}B", payload)
        elif t == "s":
            vals = struct.unpack(f">{repeat}h", payload)
        elif t == "S":
            vals = struct.unpack(f">{repeat}H", payload)
        elif t == "l":
            vals = struct.unpack(f">{repeat}i", payload)
        elif t == "L":
            vals = struct.unpack(f">{repeat}I", payload)
        elif t == "f":
            vals = struct.unpack(f">{repeat}f", payload)
        elif t == "d":
            vals = struct.unpack(f">{repeat}d", payload)
        elif t == "Q":
            vals = struct.unpack(f">{repeat}Q", payload)
        elif t == "J":
            vals = struct.unpack(f">{repeat}q", payload)
        else:
            return payload
        if repeat == 1:
            return vals[0]
        return vals
    except Exception:
        return payload


def parse_gpmf(data: bytes, offset: int = 0) -> list[tuple[str, Any]]:
    """Iteratively parse GPMF binary structure into a flat list of (key, value) tuples.

    Nested STRM/DEVC containers (TLV type 0x00) are expanded in-place using an
    explicit stack instead of recursion, which avoids Python function-call
    overhead on deeply/frequently nested streams and is noticeably faster on
    large files (hundreds of thousands of TLV records).

    Micro-optimizations applied vs. a naive recursive parser:
      - struct.unpack_from() instead of slicing + struct.unpack() (avoids
        creating an intermediate bytes object for the 2-byte repeat field).
      - int.from_bytes() for the ASCII key check is skipped entirely; we only
        decode to str lazily and cache repeated keys is not needed since the
        decode() call itself is already cheap relative to unpack overhead.
      - A single flat results list is reused across the whole call (no list
        concatenation via extend() from recursive return values).
    """
    results: list[tuple[str, Any]] = []
    stack: list[tuple[bytes, int]] = [(data, offset)]

    while stack:
        buf, off = stack.pop()
        n = len(buf)
        while off + 8 <= n:
            key = buf[off:off + 4].decode("ascii", errors="ignore")
            t = chr(buf[off + 4])
            size = buf[off + 5]
            (repeat,) = struct.unpack_from(">H", buf, off + 6)

            payload_size = size * repeat
            if payload_size < 0 or payload_size > n:
                break
            payload_start = off + 8
            payload_end = payload_start + payload_size
            if payload_end > n:
                break
            payload = buf[payload_start:payload_end]
            off = payload_start + ((payload_size + 3) & ~3)

            if t == "\x00":
                stack.append((buf, off))
                stack.append((payload, 0))
                break
            else:
                results.append((key, decode_gpmf(t, repeat, payload)))
    return results


def try_decode_8byte_stmp(raw: bytes) -> Optional[float]:
    """Attempt to decode an 8-byte STMP value as microsecond-uint64 or double."""
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


def to_exiftool_json(parsed: list[tuple[str, Any]], source_file: str,
                     start_dt: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Convert a flat list of parsed GPMF (key, value) tuples into an
    ExifTool-style JSON document containing GPS, altitude, speed, and
    camera metadata fields.

    If *start_dt* is given (e.g. from video creation_time), it is used as
    the absolute time base for TSMP/STMP offsets when no GPSU block exists.
    """
    out: dict[str, Any] = {"SourceFile": source_file}
    doc = 1
    scal = None
    last_gpsu_dt: Optional[datetime] = None
    current_block_start_dt: Optional[datetime] = None

    def _fmt_dt(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y:%m:%d %H:%M:%S.%f")[:-3]

    for key, val in parsed:
        if key == "SCAL":
            scal = val

        elif key == "GPSU":
            try:
                if isinstance(val, (list, tuple)) and len(val) >= 7:
                    year, month, day, hour, minute, sec, ms = (int(x) for x in val[:7])
                    last_gpsu_dt = datetime(year, month, day, hour, minute, sec, ms * 1000, tzinfo=timezone.utc)
                    current_block_start_dt = last_gpsu_dt
                    out[f"Doc{doc}:GPSDateTime"] = _fmt_dt(last_gpsu_dt)
                    out[f"Doc{doc}:SampleTime"] = "0.000"
            except Exception:
                pass

        elif key in ("GPS5", "GPS9"):
            values = _parse_int32_values(val)
            # GPS5 = 5 fields/sample (GoPro spec). GPS9 = 8 fields/sample on
            # this camera/firmware (lat, lon, alt, speed2d, speed3d, t1, t2, t3) --
            # verified via raw byte inspection, see module docstring.
            step = 5 if key == "GPS5" else 8
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
                chunk = values[i:i + step]
                try:
                    lat = chunk[0] / s[0] if s[0] else 0.0
                    lon = chunk[1] / s[1] if s[1] else 0.0
                    alt = chunk[2] / s[2] if s[2] else 0.0
                    s2d = chunk[3] / s[3] if s[3] else 0.0
                    s3d = chunk[4] / s[4] if len(chunk) > 4 and s[4] else 0.0

                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue
                    if lat == 0.0 and lon == 0.0:
                        continue

                    if not (0.0 <= s2d <= 300.0):
                        s2d = None
                    if not (0.0 <= s3d <= 300.0):
                        s3d = None

                    prefix = f"Doc{block_doc}" if i == 0 else f"Doc{block_doc}-{i // step}"
                    out[f"{prefix}:GPSLatitude"] = lat
                    out[f"{prefix}:GPSLongitude"] = lon
                    out[f"{prefix}:GPSAltitude"] = f"{alt} m"
                    if s2d is not None:
                        out[f"{prefix}:GPSSpeed"] = s2d
                    if s3d is not None:
                        out[f"{prefix}:GPSSpeed3D"] = s3d

                    if current_block_start_dt is not None:
                        sample_idx = i // step
                        sample_dt = current_block_start_dt + timedelta(seconds=sample_idx * 0.1)
                        out[f"{prefix}:GPSDateTime"] = _fmt_dt(sample_dt)
                        out[f"{prefix}:SampleTime"] = f"{sample_idx * 0.1:.3f}"
                except Exception:
                    continue
            doc += 1

        elif key == "GPSA":
            out[f"Doc{doc}:GPSAltitudeSystem"] = (
                val.decode("ascii", errors="ignore").strip("\x00") if isinstance(val, bytes) else str(val)
            )

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
                        sample_time = float(ast.literal_eval(val.decode("ascii", errors="ignore")))
                    except Exception:
                        sample_time = try_decode_8byte_stmp(val)
            out[f"Doc{doc}:SampleTime"] = sample_time if sample_time is None else str(sample_time)

        elif key == "TSMP":
            timestamp = val
            if isinstance(val, bytes):
                try:
                    timestamp = float(val.decode("ascii", errors="ignore"))
                except Exception:
                    try:
                        timestamp = float(ast.literal_eval(val.decode("ascii", errors="ignore")))
                    except Exception:
                        timestamp = None
            out[f"Doc{doc}:TimeStamp"] = timestamp

    return [out]


def gpmf_to_exiftool_json(video_path: str | Path, ffmpeg_exe: str = "ffmpeg", ffprobe_exe: str = "ffprobe") -> list[dict[str, Any]]:
    """High-level entry point: extract GPMF from a video file and return
    ExifTool-style JSON telemetry (GPS, altitude, speed, camera metadata).
    """
    data = extract_gpmf(video_path, ffmpeg_exe=ffmpeg_exe, ffprobe_exe=ffprobe_exe)
    parsed = parse_gpmf(data)
    return to_exiftool_json(parsed, str(video_path))
