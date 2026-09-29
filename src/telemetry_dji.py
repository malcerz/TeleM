"""DJI camera IMU adapter for AdrianEddy/telemetry-parser.

Only camera motion enters TeleM here. FIT/GPX remain responsible for GPS,
speed, altitude and other activity streams.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.telemetry_cache_manager import get_media_cache_dir


from src.runtime_paths import get_telemetry_parser_dir

UPSTREAM_COMMIT = "d45ebf2afce85fa691838fd32b3da8ae2fcac773"
DJI_CACHE_SCHEMA = 1
DJI_RUNTIME = get_telemetry_parser_dir()


def detect_camera_telemetry(path: Path | str, ffprobe_exe: str) -> str | None:
    """Use MP4 stream tags, never the camera filename."""
    result = subprocess.run(
        [ffprobe_exe, "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_tag_string:stream_tags=handler_name",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(result.stdout).get("streams", [])
    for stream in streams:
        if str(stream.get("codec_tag_string", "")).lower() == "gpmd":
            return "gopro_gpmf"
    for stream in streams:
        tag = str(stream.get("codec_tag_string", "")).lower()
        handler = str((stream.get("tags") or {}).get("handler_name", "")).lower()
        if stream.get("codec_type") == "data" and tag == "djmd" and (
            "cam meta" in handler or "dji meta" in handler
        ):
            return "dji_djmd"
    return None


def _parser_module() -> Any:
    if str(DJI_RUNTIME) not in sys.path:
        sys.path.insert(0, str(DJI_RUNTIME))
    package = DJI_RUNTIME / "telemetry_parser"
    suffixes = importlib.machinery.EXTENSION_SUFFIXES
    compatible = any(any(package.glob(f"telemetry_parser{suffix}")) for suffix in suffixes)
    if not compatible:
        raise RuntimeError(
            f"DJI telemetry parser is unavailable for Python {sys.version_info.major}.{sys.version_info.minor}; "
            f"build the pinned runtime in {DJI_RUNTIME}"
        )
    try:
        module = importlib.import_module("telemetry_parser")
        if not Path(module.__file__).resolve().is_relative_to(DJI_RUNTIME.resolve()):
            raise RuntimeError("DJI telemetry parser was loaded outside the bundled runtime")
        return module
    except ImportError as exc:
        raise RuntimeError(
            f"DJI telemetry parser is unavailable for Python {sys.version_info.major}.{sys.version_info.minor}: {exc}"
        ) from exc


def _cache_path(source: Path) -> Path:
    return get_media_cache_dir(source) / "dji_imu.npz"


def _identity(source: Path) -> dict[str, Any]:
    stat = source.stat()
    return {
        "schema": DJI_CACHE_SCHEMA,
        "upstream_commit": UPSTREAM_COMMIT,
        "path": str(source.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _read_cache(source: Path) -> dict[str, Any] | None:
    path = _cache_path(source)
    if not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as archive:
            meta = json.loads(archive["meta"].tobytes().decode("utf-8"))
            if any(meta.get(k) != v for k, v in _identity(source).items()):
                return None
            return {
                "gyro": archive["gyro"], "accel": archive["accel"],
                "quaternion": archive["quaternion"],
                "camera": meta.get("camera"), "model": meta.get("model"),
                "camera_metadata": meta.get("camera_metadata") or {},
                "cache_hit": True,
            }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(source: Path, data: dict[str, Any]) -> None:
    path = _cache_path(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        **_identity(source),
        "camera": data["camera"], "model": data["model"],
        "camera_metadata": data["camera_metadata"],
    }
    temporary = path.with_name(f"dji_imu_{os.getpid()}_{time.time_ns()}.tmp.npz")
    try:
        np.savez_compressed(
            temporary,
            gyro=data["gyro"], accel=data["accel"],
            quaternion=data["quaternion"],
            meta=np.frombuffer(json.dumps(meta, default=str).encode("utf-8"), dtype=np.uint8),
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _quaternions(groups: list[Any]) -> np.ndarray:
    rows: list[tuple[float, float, float, float, float]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        quat_group = group.get("Quaternion") or {}
        samples = quat_group.get("Data") or quat_group.get("Quaternion data") or []
        for sample in samples if isinstance(samples, list) else []:
            if not isinstance(sample, dict):
                continue
            value = sample.get("v") or sample.get("value") or {}
            if isinstance(value, dict):
                components = [value.get(k) for k in ("w", "x", "y", "z")]
            elif isinstance(value, (list, tuple)) and len(value) == 4:
                components = list(value)
            else:
                continue
            stamp = sample.get("t", sample.get("timestamp"))
            if stamp is None or any(v is None for v in components):
                continue
            rows.append((float(stamp), *(float(v) for v in components)))
    return np.asarray(rows, dtype=np.float64).reshape(-1, 5)


def _parse(source: Path) -> dict[str, Any]:
    parser = _parser_module().Parser(str(source))
    if parser.camera != "DJI":
        raise RuntimeError(f"Expected DJI metadata, parser reported {parser.camera!r}")
    groups = parser.telemetry()
    imu = parser.normalized_imu()
    gyro_rows = []
    accel_rows = []
    for sample in imu:
        if not isinstance(sample, dict):
            continue
        stamp = float(sample["timestamp_ms"]) / 1000.0
        # telemetry-parser normalizes gyroscope to degrees/s and accelerometer
        # to m/s². TeleM's existing gyro convention is radians/s.
        gyro = sample.get("gyro")
        accel = sample.get("accl")
        if gyro is not None and len(gyro) == 3:
            gyro_rows.append((stamp, *(math.radians(float(v)) for v in gyro)))
        if accel is not None and len(accel) == 3:
            accel_rows.append((stamp, *(float(v) for v in accel)))
    metadata = {}
    for group in groups:
        if isinstance(group, dict):
            metadata = (group.get("Default") or {}).get("Metadata") or {}
            if metadata:
                break
    return {
        "gyro": np.asarray(gyro_rows, dtype=np.float64).reshape(-1, 4),
        "accel": np.asarray(accel_rows, dtype=np.float64).reshape(-1, 4),
        "quaternion": _quaternions(groups),
        "camera": parser.camera, "model": parser.model,
        "camera_metadata": metadata, "cache_hit": False,
    }


def load_dji_telemetry(source: Path | str, clip_start_utc: datetime) -> dict[str, Any]:
    """Return camera samples as TeleM's timestamped fields, without GPS fields."""
    source = Path(source)
    started = time.perf_counter()
    data = _read_cache(source)
    if data is None:
        data = _parse(source)
        _write_cache(source, data)
    anchor = clip_start_utc
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    else:
        anchor = anchor.astimezone(timezone.utc)

    def vectors(rows: np.ndarray) -> list[tuple[datetime, tuple[float, float, float]]]:
        return [
            (anchor + timedelta(seconds=float(row[0])), tuple(float(v) for v in row[1:4]))
            for row in rows
        ]

    result = {
        "gyroscope_samples": vectors(data["gyro"]),
        "accelerometer_samples": vectors(data["accel"]),
        "quaternion_samples": [
            (anchor + timedelta(seconds=float(row[0])), tuple(float(v) for v in row[1:5]))
            for row in data["quaternion"]
        ],
        "camera_metadata": data["camera_metadata"],
        "camera": data["camera"], "model": data["model"],
        "cache_hit": data["cache_hit"],
        "elapsed_s": time.perf_counter() - started,
    }
    print(
        f"[Telemetry] camera source: DJI djmd model={result['model']} "
        f"gyro={len(result['gyroscope_samples'])} "
        f"accel={len(result['accelerometer_samples'])} "
        f"quaternion={len(result['quaternion_samples'])} "
        f"cache={'HIT' if data['cache_hit'] else 'MISS'}",
        flush=True,
    )
    return result
