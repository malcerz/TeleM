"""Optional, versioned CORI/GRAV reader; never changes the production GPMF DLL.

Quaternions retain GoPro's w,x,y,z order. STMP and actual block lengths define
the sample grid; the existing native gyro first sample is the file-time origin.
Only the compass hybrid mode requests this data.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from src.telemetry_gpmf_new import parse_gpmf_tree, find_gpmf_stream_index, decode_complex_type, _gps9_datetime

READER_VERSION = 1


def source_fingerprint(path):
    p = Path(path).resolve()
    st = p.stat()
    return (str(p), st.st_size, st.st_mtime_ns)


def _numeric(node, scale):
    types = {"s": ">i2", "S": ">u2", "l": ">i4", "L": ">u4", "f": ">f4", "d": ">f8"}
    if node.type_char not in types or not isinstance(node.value, bytes):
        return None
    values = np.frombuffer(node.value, dtype=types[node.type_char]).astype(np.float64)
    values = values.reshape(node.repeat, -1)
    return values / np.asarray(scale or 1.0)


def _read_exact(stream, size):
    chunks = []
    while size:
        part = stream.read(size)
        if not part:
            raise ValueError("Truncated GPMF block")
        chunks.append(part)
        size -= len(part)
    return b"".join(chunks)


def read_orientation(path, start_ts, *, cache_dir=None, ffmpeg=None, ffprobe=None):
    root = Path(__file__).resolve().parents[1]
    ffmpeg = str(ffmpeg or root / "runtime/common/ffmpeg/ffmpeg.exe")
    ffprobe = str(ffprobe or root / "runtime/common/ffmpeg/ffprobe.exe")
    signature = {"source": source_fingerprint(path), "start_ts": float(start_ts), "version": READER_VERSION}
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    folder = Path(cache_dir or root / "cache/compass_orientation")
    target = folder / f"{key}.npz"
    if target.exists():
        try:
            with np.load(target, allow_pickle=False) as archive:
                result = {k: archive[k] for k in archive.files if k != "metadata"}
                meta = json.loads(str(archive["metadata"]))
            meta["cache_hit"] = True
            return result, meta
        except (OSError, ValueError, KeyError):
            pass
    index = find_gpmf_stream_index(path, ffprobe)
    if index is None:
        return {}, {"status": "no_gpmf", "cache_hit": False}
    blocks = {"CORI": [], "GRAV": []}
    gps_quality = []
    seen = set()
    origins = []
    meta_streams = {}
    # stderr cannot fill a pipe while Python consumes the binary stdout.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([ffmpeg, "-v", "error", "-i", str(path), "-map", f"0:{index}",
                                    "-c", "copy", "-f", "data", "pipe:1"],
                                   stdout=subprocess.PIPE, stderr=errors, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            while True:
                header = process.stdout.read(8)
                if not header:
                    break
                if len(header) != 8:
                    raise ValueError("Truncated GPMF header")
                _key, _typ, size, repeat = struct.unpack(">4scBH", header)
                length = size * repeat
                payload = _read_exact(process.stdout, (length + 3) & ~3)
                for device in parse_gpmf_tree(header + payload):
                    for stream in device.children:
                        if stream.key != "STRM":
                            continue
                        children = {n.key: n for n in stream.children}
                        seen.update(children)
                        stamp = children.get("STMP")
                        if stamp is None:
                            continue
                        stmp = float(stamp.value)
                        for family in ("GYRO", "ACCL"):
                            if family in children:
                                origins.append(stmp)
                                meta_streams.setdefault(family, {
                                    k: children[k].value for k in ("ORIN", "ORIO", "SIUN") if k in children})
                        for family in blocks:
                            if family not in children:
                                continue
                            scale = children.get("SCAL")
                            values = _numeric(children[family], scale.value if scale else 1.0)
                            if values is not None:
                                blocks[family].append((stmp, values))
                        if "GPS9" in children and "TYPE" in children:
                            node = children["GPS9"]
                            values = decode_complex_type(children["TYPE"].value, node.value)
                            scale = children["SCAL"].value
                            for raw in values:
                                vals = np.asarray(raw, dtype=float) / np.asarray(scale)
                                dt = _gps9_datetime(vals[5], vals[6])
                                if dt is not None:
                                    from datetime import timezone
                                    ts = dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp()
                                    gps_quality.append((ts, vals[7], vals[8]))
            code = process.wait()
            if code:
                errors.seek(0)
                raise ValueError(errors.read().decode(errors="replace")[-1000:])
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()
    origin = min(origins) if origins else None
    result = {}
    for family, items in blocks.items():
        if not items or origin is None:
            continue
        rows = []
        previous_step = None
        for i, (stamp, values) in enumerate(items):
            step = (items[i+1][0] - stamp) / len(values) if i+1 < len(items) else previous_step
            if step is None or step <= 0:
                continue
            previous_step = step
            times = start_ts + (stamp - origin + np.arange(len(values)) * step) * 1e-6
            rows.append(np.column_stack((times, values)))
        if rows:
            result[family] = np.concatenate(rows)
    if gps_quality:
        result["GPS_QUALITY"] = np.asarray(gps_quality, dtype=float)
    metadata = {"signature": signature, "present_channels": sorted(seen), "streams": meta_streams,
                "origin_stmp_us": origin, "cache_hit": False, "status": "ok"}
    folder.mkdir(parents=True, exist_ok=True)
    # Atomic replace: a failed extraction cannot publish a partial cache.
    with tempfile.NamedTemporaryFile(suffix=".npz", dir=folder, delete=False) as handle:
        temp = Path(handle.name)
    try:
        np.savez_compressed(temp, **result, metadata=json.dumps(metadata))
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return result, metadata
