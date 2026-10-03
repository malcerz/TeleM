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
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from src.process_lifecycle import RenderProcessRegistry
from src.telemetry_cache_manager import get_media_cache_dir


UPSTREAM_COMMIT = "d45ebf2afce85fa691838fd32b3da8ae2fcac773"
DJI_CACHE_SCHEMA = 1
try:
    from src.runtime_paths import get_telemetry_parser_dir
    DJI_RUNTIME = get_telemetry_parser_dir()
except Exception:
    DJI_RUNTIME = Path(__file__).resolve().parents[1] / "runtime" / "telemetry_parser"


def detect_camera_telemetry(path: Path | str, ffprobe_exe: str) -> str | None:
    """Use MP4 stream tags, never the camera filename."""
    print("[DJI LOAD] stage=detect start", flush=True)
    t0 = time.perf_counter()
    result = subprocess.run(
        [ffprobe_exe, "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_tag_string:stream_tags=handler_name",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(result.stdout).get("streams", [])
    detected = None
    for stream in streams:
        if str(stream.get("codec_tag_string", "")).lower() == "gpmd":
            detected = "gopro_gpmf"
            break
    if detected is None:
        for stream in streams:
            tag = str(stream.get("codec_tag_string", "")).lower()
            handler = str((stream.get("tags") or {}).get("handler_name", "")).lower()
            if stream.get("codec_type") == "data" and tag == "djmd" and (
                "cam meta" in handler or "dji meta" in handler
            ):
                detected = "dji_djmd"
                break

    detect_ms = (time.perf_counter() - t0) * 1000.0
    print(f"[DJI LOAD] stage=detect end wall_time={detect_ms:.1f}ms source={detected}", flush=True)
    return detected


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


_default_parser_module = _parser_module


def _cache_path(source: Path) -> Path:
    return get_media_cache_dir(source) / "dji_imu.npz"


def _cleanup_temp_cache(source: Path) -> None:
    """Safely remove leftover temporary cache files for this source."""
    try:
        parent = _cache_path(source).parent
        if parent.is_dir():
            for tmp in parent.glob("dji_imu_*.tmp.npz"):
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass


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


def _write_cache(source: Path, data: dict[str, Any], cache_path: Path | None = None) -> Path:
    path = cache_path or _cache_path(source)
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
        return path
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
    """In-process parsing (used by worker process or unit tests)."""
    t0_init = time.perf_counter()
    parser = _parser_module().Parser(str(source))
    init_ms = (time.perf_counter() - t0_init) * 1000.0
    if parser.camera != "DJI":
        raise RuntimeError(f"Expected DJI metadata, parser reported {parser.camera!r}")

    t0_telem = time.perf_counter()
    groups = parser.telemetry()
    telem_ms = (time.perf_counter() - t0_telem) * 1000.0

    t0_imu = time.perf_counter()
    imu = parser.normalized_imu()
    imu_ms = (time.perf_counter() - t0_imu) * 1000.0

    t0_conv = time.perf_counter()
    gyro_rows = []
    accel_rows = []
    for sample in imu:
        if not isinstance(sample, dict):
            continue
        stamp = float(sample["timestamp_ms"]) / 1000.0
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
    conv_ms = (time.perf_counter() - t0_conv) * 1000.0

    return {
        "gyro": np.asarray(gyro_rows, dtype=np.float64).reshape(-1, 4),
        "accel": np.asarray(accel_rows, dtype=np.float64).reshape(-1, 4),
        "quaternion": _quaternions(groups),
        "camera": parser.camera, "model": parser.model,
        "camera_metadata": metadata, "cache_hit": False,
        "_timings_ms": {
            "parser_init_ms": init_ms,
            "telemetry_ms": telem_ms,
            "normalized_imu_ms": imu_ms,
            "convert_ms": conv_ms,
        }
    }


def spawn_dji_worker(
    video_path: Path | str,
    cache_path: Path | str | None = None,
    progress_cb: Callable[[str, float, str], None] | None = None,
    cancel_event: Any = None,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Execute heavy DJI telemetry parsing in an isolated worker process.

    This ensures the Qt GUI process is NEVER blocked by native telemetry-parser
    code holding the Python GIL.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("DJI parsing was cancelled by user")

    video_path = Path(video_path).resolve()
    worker_script = Path(__file__).resolve().parent / "telemetry_dji_worker.py"

    cmd = [sys.executable, str(worker_script), "--video", str(video_path)]
    if cache_path:
        cmd.extend(["--cache-path", str(cache_path)])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    RenderProcessRegistry.get_instance().register(proc, "dji_worker")

    line_queue: queue.Queue[str | None] = queue.Queue()

    def _reader(pipe: Any) -> None:
        try:
            for line in iter(pipe.readline, ""):
                line_queue.put(line)
        except Exception:
            pass
        finally:
            line_queue.put(None)

    reader_thread = threading.Thread(target=_reader, args=(proc.stdout,), daemon=True)
    reader_thread.start()

    started_at = time.monotonic()
    last_activity_time = time.monotonic()
    current_stage = "parser_init"
    stage_desc_map = {
        "init": "przygotowanie...",
        "parser_init": "odczyt telemetrii...",
        "telemetry": "przetwarzanie telemetrii...",
        "normalized_imu": "przetwarzanie IMU...",
        "convert": "konwersja kwaternionów...",
        "cache_write": "zapis cache...",
        "done": "zakończono",
    }
    last_ui_update = 0.0

    def _terminate_worker(p: subprocess.Popen) -> None:
        try:
            p.terminate()
            p.wait(timeout=1.5)
        except Exception:
            try:
                p.kill()
                p.wait(timeout=1.0)
            except Exception:
                pass

    try:
        while proc.poll() is None:
            # 1. User cancellation
            if cancel_event is not None and cancel_event.is_set():
                print(f"[DJI WORKER] Cancellation requested, terminating worker pid={proc.pid}", flush=True)
                _terminate_worker(proc)
                _cleanup_temp_cache(video_path)
                raise RuntimeError("DJI parsing was cancelled by user")

            # 2. Watchdog timeout
            now = time.monotonic()
            if now - last_activity_time > timeout_s:
                print(f"[DJI WORKER] Watchdog timeout ({timeout_s}s), terminating worker pid={proc.pid}", flush=True)
                _terminate_worker(proc)
                _cleanup_temp_cache(video_path)
                raise TimeoutError(f"DJI worker timed out after {timeout_s}s without heartbeat/output")

            # 3. Drain lines from worker stdout
            while True:
                try:
                    line = line_queue.get_nowait()
                    if line is None:
                        break
                    last_activity_time = time.monotonic()
                    line_str = line.strip()
                    if line_str:
                        print(f"[DJI WORKER] {line_str}", flush=True)
                        if line_str.startswith("DJI_WORKER_STAGE stage="):
                            current_stage = line_str.split("stage=", 1)[1].split()[0]
                except queue.Empty:
                    break

            # 4. Update UI progress with heartbeat elapsed time every ~0.5s
            now = time.monotonic()
            if now - last_ui_update >= 0.5:
                last_ui_update = now
                elapsed = now - started_at
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                time_str = f"{mins:02d}:{secs:02d}"
                stage_desc = stage_desc_map.get(current_stage, "odczyt telemetrii...")
                msg = f"{stage_desc} {time_str}"
                if progress_cb is not None:
                    try:
                        progress_cb(current_stage, elapsed, msg)
                    except Exception:
                        pass

            time.sleep(0.05)

        retcode = proc.wait()

        # Drain any remaining lines
        while True:
            try:
                line = line_queue.get_nowait()
                if line is None:
                    break
                line_str = line.strip()
                if line_str:
                    print(f"[DJI WORKER] {line_str}", flush=True)
            except queue.Empty:
                break

        stderr_output = proc.stderr.read() if proc.stderr else ""
        if retcode != 0:
            print(f"[DJI WORKER] exit_code={retcode}", flush=True)
            print(f"[DJI WORKER] error={stderr_output.strip()}", flush=True)
            _cleanup_temp_cache(video_path)
            raise RuntimeError(
                f"DJI telemetry worker failed with exit code {retcode}: {stderr_output.strip()}"
            )

        # Worker finished with exit code 0
        cache_data = _read_cache(video_path)
        if cache_data is None:
            raise RuntimeError(
                f"DJI worker completed with code 0 but cache was not found or invalid at {_cache_path(video_path)}"
            )
        return cache_data

    finally:
        RenderProcessRegistry.get_instance().unregister(proc)


def load_dji_telemetry(
    source: Path | str,
    clip_start_utc: datetime,
    progress_cb: Callable[[str, float, str], None] | None = None,
    cancel_event: Any = None,
    use_worker: bool | None = None,
) -> dict[str, Any]:
    """Return camera samples as TeleM's timestamped fields, without GPS fields."""
    source = Path(source)
    started = time.perf_counter()

    # Fast path: check valid cache first
    data = _read_cache(source)
    cache_hit = (data is not None)
    if data is None:
        # Determine whether to use external worker process
        if use_worker is None:
            use_worker = (_parser_module is _default_parser_module)

        if use_worker:
            data = spawn_dji_worker(
                source,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
            )
        else:
            data = _parse(source)
            _write_cache(source, data)
        data["cache_hit"] = False

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
