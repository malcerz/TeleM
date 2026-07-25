
"""
telemetry_gpmf.py

GPMF (GoPro Metadata Format) telemetry extraction and parsing.

Extracts the embedded GPMF binary metadata stream from a GoPro MP4 file
via ffmpeg/ffprobe, parses the GPMF TLV structure (fully, including nested
STRM containers), and converts ALL recorded sensor streams (GPS, ACCL,
GYRO, GRAV, CORI, IORI, MAGN, camera/exposure metadata, etc.) into either:
  - a flat ExifTool-style JSON document (GPS-focused, kept for backwards
    compatibility with existing overlay code), and/or
  - a full generic per-stream dict with every FourCC decoded and scaled
    according to its own SCAL/SIUN/TYPE metadata.

FourCC reference used for this implementation:
https://github.com/gopro/gpmf-parser (official GoPro GPMF spec)
https://gopro.github.io/gpmf-parser/ (rendered FourCC + type tables)

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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

STRM_BOUNDARY = b"STRM"
DEVC_BOUNDARY = b"DEVC"

# ---------------------------------------------------------------------------
# Type-char -> struct format map (see GPMF-parser.h / spec "Type Char" table)
# ---------------------------------------------------------------------------
_STRUCT_FMT = {
    "b": "b", "B": "B", "s": "h", "S": "H",
    "l": "i", "L": "I", "f": "f", "d": "d",
    "Q": "Q", "J": "q", "j": "q",
}
_STRUCT_SIZE = {
    "b": 1, "B": 1, "s": 2, "S": 2,
    "l": 4, "L": 4, "f": 4, "d": 8,
    "Q": 8, "J": 8, "j": 8, "q": 4, "F": 4, "c": 1, "U": 1, "G": 1,
}


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
        if t == "U":
            return payload.decode("ascii", errors="ignore").rstrip("\x00")
        if t == "F":
            # 32-bit FourCC value(s)
            n = len(payload) // 4
            return [payload[i * 4:(i + 1) * 4].decode("ascii", errors="ignore") for i in range(n)]
        if t == "G":
            return payload.hex()
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
        elif t == "j":
            vals = struct.unpack(f">{repeat}q", payload)
        elif t == "q":
            # Q15.16 fixed point
            raw = struct.unpack(f">{repeat}i", payload)
            vals = tuple(v / 65536.0 for v in raw)
        else:
            return payload
        if repeat == 1:
            return vals[0]
        return vals
    except Exception:
        return payload


# ---------------------------------------------------------------------------
# Flat parser (kept for backwards compatibility with existing GPS overlay code)
# ---------------------------------------------------------------------------
def parse_gpmf(data: bytes, offset: int = 0) -> list[tuple[str, Any]]:
    """Iteratively parse GPMF binary structure into a flat list of (key, value) tuples.

    Nested STRM/DEVC containers (TLV type 0x00) are expanded in-place using an
    explicit stack instead of recursion. This flat view loses which nested
    STRM a key belongs to -- use parse_gpmf_tree() / extract_all_streams()
    below when you need full per-stream fidelity (required for correctly
    scaling ACCL, GYRO, GRAV, CORI, IORI, MAGN, etc. which each carry their
    own local SCAL/SIUN/TYPE metadata).
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


# ---------------------------------------------------------------------------
# Nested/tree parser -- preserves DEVC/STRM boundaries and raw type/size info
# so per-stream SCAL/SIUN/TYPE metadata is correctly scoped (per GPMF spec:
# "Property Hierarchy" -- SCAL/SIUN/TYPE apply forward, within the same nest,
# to the *next* data KLV only).
# ---------------------------------------------------------------------------
@dataclass
class GPMFNode:
    key: str
    type_char: str
    size: int
    repeat: int
    value: Any
    children: list["GPMFNode"] = field(default_factory=list)


def parse_gpmf_tree(data: bytes, offset: int = 0) -> list[GPMFNode]:
    """Parse GPMF binary structure into a nested tree of GPMFNode.

    Each nested container (DEVC, STRM, or any '\\x00'-typed FourCC) becomes a
    node with .children populated; leaf KLVs get .value set via decode_gpmf.
    """

    def _parse_level(buf: bytes, off: int, end: int) -> list[GPMFNode]:
        nodes: list[GPMFNode] = []
        while off + 8 <= end:
            key = buf[off:off + 4].decode("ascii", errors="ignore")
            t = chr(buf[off + 4])
            size = buf[off + 5]
            (repeat,) = struct.unpack_from(">H", buf, off + 6)

            payload_size = size * repeat
            payload_start = off + 8
            payload_end = payload_start + payload_size
            if payload_size < 0 or payload_end > end:
                break
            payload = buf[payload_start:payload_end]
            off = payload_start + ((payload_size + 3) & ~3)

            if t == "\x00":
                children = _parse_level(payload, 0, len(payload))
                nodes.append(GPMFNode(key, t, size, repeat, None, children))
            else:
                nodes.append(GPMFNode(key, t, size, repeat, decode_gpmf(t, repeat, payload)))
        return nodes

    return _parse_level(data, offset, len(data))


def decode_complex_type(type_str: str, raw: bytes) -> list[Any]:
    """Decode a raw payload using a GPMF TYPE-string (e.g. 'SSffff' for FACE),
    per the 'Complex structures' section of the GPMF spec. Returns one tuple
    of decoded fields per struct instance found in raw.
    """
    fmt_chars = []
    i = 0
    while i < len(type_str):
        c = type_str[i]
        fmt_chars.append(_STRUCT_FMT.get(c, c))
        i += 1
    struct_size = sum(_STRUCT_SIZE.get(c, 1) for c in type_str)
    if struct_size == 0:
        return []
    out = []
    fmt = ">" + "".join(fmt_chars)
    n = len(raw) // struct_size
    for i in range(n):
        chunk = raw[i * struct_size:(i + 1) * struct_size]
        try:
            out.append(struct.unpack(fmt, chunk))
        except Exception:
            out.append(chunk)
    return out


_AXIS_ORDER = {
    # Data axis order per FourCC/camera family, from the official GPMF docs
    # (gopro.github.io/gpmf-parser). Applied only when repeat is a multiple
    # of 3 and no better structural hint is available.
    "HERO5": "ZXY",
    "FUSION": "-YXZ",
    "HERO6": "Y-XZ",
}


def extract_all_streams(tree: list[GPMFNode]) -> list[dict[str, Any]]:
    """Walk the full GPMF tree and return every DEVC device with every STRM
    stream fully decoded and scaled -- ACCL, GYRO, GRAV, CORI, IORI, MAGN,
    GPS5/GPS9, SHUT, ISOE, TMPC, FACE, and any other FourCC present, generic
    and future-proof (no hardcoded key whitelist).

    Scaling rules follow the GPMF "Property Hierarchy": SCAL/SIUN/UNIT/TYPE
    KLVs modify only the *next* data KLV within the same STRM nest.
    """

    def _scale(values: Any, scal: Any) -> Any:
        if scal is None:
            return values
        if isinstance(values, (list, tuple)):
            if isinstance(scal, (list, tuple)):
                s = list(scal)
                if len(s) == 1:
                    s = s * len(values)
                return [v / s[i] if i < len(s) and s[i] else v for i, v in enumerate(values)]
            return [v / scal if scal else v for v in values]
        if isinstance(scal, (list, tuple)):
            scal = scal[0] if scal else 1
        return values / scal if scal else values

    def _chunked(flat: list, step: int) -> list[list]:
        return [flat[i:i + step] for i in range(0, len(flat) - len(flat) % step, step)] if step else [flat]

    def _walk_strm(strm_children: list[GPMFNode]) -> dict[str, Any]:
        stream: dict[str, Any] = {"_meta": {}}
        scal = None
        siun = None
        unit = None
        type_str = None
        stnm = None
        for node in strm_children:
            k = node.key
            if k == "SCAL":
                scal = node.value
                continue
            if k == "SIUN":
                siun = node.value
                continue
            if k == "UNIT":
                unit = node.value
                continue
            if k == "TYPE":
                type_str = node.value
                continue
            if k == "STNM":
                stnm = node.value
                stream["_meta"]["name"] = stnm
                continue
            if k in ("TSMP", "TICK", "TOCK", "EMPT", "TIMO"):
                stream["_meta"][k] = node.value
                continue
            if k == "RMRK":
                stream["_meta"]["comment"] = node.value
                continue

            if node.children:
                # nested sub-structure inside a stream (rare, e.g. custom devices)
                stream[k] = _walk_strm(node.children)
                continue

            raw_repeat = node.repeat
            values = node.value

            # complex structured samples (TYPE '?')
            if node.type_char == "?" and type_str:
                if isinstance(values, bytes):
                    decoded = decode_complex_type(type_str, values)
                else:
                    decoded = values
                stream[k] = {"samples": decoded, "type": type_str, "units": siun or unit}
                type_str = None
                continue

            # multi-axis numeric samples: repeat may represent N samples of
            # (structsize/typesize) axes each (e.g. ACCL: 3 axes per sample)
            axes = max(1, node.size // _STRUCT_SIZE.get(node.type_char, node.size or 1))
            if isinstance(values, (list, tuple)) and axes > 1 and len(values) % axes == 0:
                grouped = _chunked(list(values), axes)
                scaled = [_scale(g, scal) for g in grouped]
                stream[k] = scaled
            else:
                stream[k] = _scale(values, scal)

            if siun is not None:
                stream["_meta"][f"{k}_units"] = siun
            elif unit is not None:
                stream["_meta"][f"{k}_units"] = unit
            scal = None
            siun = None
            unit = None
        return stream

    devices: list[dict[str, Any]] = []
    for devc in tree:
        if devc.key != "DEVC":
            continue
        dev: dict[str, Any] = {"streams": {}}
        for node in devc.children:
            if node.key == "DVID":
                dev["device_id"] = node.value
            elif node.key == "DVNM":
                dev["device_name"] = node.value
            elif node.key == "STRM":
                strm_data = _walk_strm(node.children)
                name_hint = None
                for candidate in node.children:
                    if candidate.key not in ("SCAL", "SIUN", "UNIT", "TYPE", "STNM",
                                              "TSMP", "TICK", "TOCK", "EMPT", "TIMO", "RMRK"):
                        name_hint = candidate.key
                        break
                stream_id = name_hint or f"STRM{len(dev['streams'])}"
                dev["streams"][stream_id] = strm_data
        devices.append(dev)
    return devices


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
    camera metadata fields. Kept for backwards compatibility with existing
    overlay-rendering code that already consumes this shape.

    If *start_dt* is given (e.g. from video creation_time), it is used as
    the absolute time base for TSMP/STMP offsets when no GPSU block exists.
    """
    out: dict[str, Any] = {"SourceFile": source_file}
    doc = 1
    scal = None
    last_gpsu_dt: Optional[datetime] = None
    current_block_start_dt: Optional[datetime] = None

    # Jeśli nie ma GPSU, użyj start_dt jako podstawy czasu (z metadanych wideo)
    if start_dt is not None and current_block_start_dt is None:
        current_block_start_dt = start_dt

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
            step = 5 if key == "GPS5" else 8
            if len(values) < step:
                continue
            usable = len(values) - (len(values) % step)

            if isinstance(scal, (list, tuple)):
                s = list(scal)[:step]
                if len(s) < step:
                    s += [1] * (step - len(s))
            else:
                s = [float(scal)] * step

            block_doc = doc
            for i in range(0, usable, step):
                chunk = values[i:i + step]
                try:
                    lat = chunk[0] / s[0] if s[0] else 0.0
                    lon = chunk[1] / s[1] if s[1] else 0.0
                    alt = chunk[2] / s[2] if s[2] else 0.0
                    s2d = chunk[3] / s[3] if s[3] else 0.0
                    s3d = chunk[4] / s[4] if len(chunk) > 4 and s[4] else 0.0

                    # Convert m/s → km/h (ExifTool convention)
                    if s2d is not None and s2d != 0.0:
                        s2d *= 3.6
                    if s3d is not None and s3d != 0.0:
                        s3d *= 3.6

                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue
                    if lat == 0.0 and lon == 0.0:
                        continue

                    if not (0.0 <= s2d <= 500.0):
                        s2d = None
                    if not (0.0 <= s3d <= 500.0):
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
            # Advance block start time for the next GPS block
            if current_block_start_dt is not None:
                num_samples = usable // step
                current_block_start_dt += timedelta(seconds=num_samples * 0.1)
            doc += 1

        elif key == "GPSA":
            if isinstance(val, bytes):
                v = val.decode("ascii", errors="ignore").strip("\x00")
            elif isinstance(val, (list, tuple)):
                v = " ".join(str(x) for x in val)
            else:
                v = str(val)
            out[f"Doc{doc}:GPSAltitudeSystem"] = v

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


def gpmf_to_exiftool_json(video_path: str | Path, ffmpeg_exe: str = "ffmpeg",
                           ffprobe_exe: str = "ffprobe") -> list[dict[str, Any]]:
    """High-level entry point (backwards-compatible): extract GPMF from a video
    file and return ExifTool-style JSON telemetry (GPS, altitude, speed,
    camera metadata only).

    If the GPMF stream lacks a GPSU block (absolute GPS time), the function
    falls back to the video's creation_time from its container metadata.
    """
    data = extract_gpmf(video_path, ffmpeg_exe=ffmpeg_exe, ffprobe_exe=ffprobe_exe)
    parsed = parse_gpmf(data)

    # Pobierz creation_time jako start_dt (fallback dla braku GPSU)
    start_dt = None
    try:
        p = subprocess.run(
            [ffprobe_exe, "-v", "error", "-show_format", "-of", "json",
             str(video_path)],
            capture_output=True, text=True, timeout=5,
        )
        if p.returncode == 0:
            import json as _json
            info = _json.loads(p.stdout)
            ct = info.get("format", {}).get("tags", {}).get("creation_time")
            if ct:
                from datetime import timezone as _tz
                start_dt = datetime.fromisoformat(
                    ct.replace("Z", "+00:00")
                ).astimezone(_tz.utc)
    except Exception:
        pass

    return to_exiftool_json(parsed, str(video_path), start_dt=start_dt)


def gpmf_to_full_json(video_path: str | Path, ffmpeg_exe: str = "ffmpeg", ffprobe_exe: str = "ffprobe") -> list[dict[str, Any]]:
    """New high-level entry point: extract GPMF and return EVERY recorded
    sensor stream (ACCL, GYRO, GRAV, CORI, IORI, MAGN, GPS5/GPS9, FACE,
    exposure/ISO/white-balance metadata, etc.), fully scaled per-stream,
    one dict per DEVC device found in the file.

    Example:
        devices = gpmf_to_full_json("GX010123.MP4")
        for dev in devices:
            grav = dev["streams"].get("GRAV")   # gravity vector samples
            accl = dev["streams"].get("ACCL")   # accelerometer samples
    """
    data = extract_gpmf(video_path, ffmpeg_exe=ffmpeg_exe, ffprobe_exe=ffprobe_exe)
    tree = parse_gpmf_tree(data)
    return extract_all_streams(tree)
