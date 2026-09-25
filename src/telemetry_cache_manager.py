"""Central Telemetry and Media Cache Manager for BikeRideHUD / TeleM.

Provides a unified, versioned, atomic AppData storage for all automatically
generated media sidecars (GPMF JSON, Processed Telemetry NPZ, Telem Time mapping,
and metadata index), ensuring source video directories remain 100% clean.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional


CACHE_FORMAT_VERSION = 1
CACHE_KEY_ALGORITHM = "stem + sha256(canonical_path|size|mtime_ns|format_version)[:16]"

_LOGGED_CACHE_EVENTS: set[tuple[str, str, str]] = set()


def get_cache_root() -> Path:
    """Return the central cache root directory (%LOCALAPPDATA%\\BikeRideHUD\\cache)."""
    env_root = os.environ.get("TELEM_CACHE_ROOT")
    if env_root:
        root = Path(env_root)
    else:
        local_appdata = os.environ.get(
            "LOCALAPPDATA",
            str(Path.home() / "AppData" / "Local")
        )
        root = Path(local_appdata) / "BikeRideHUD" / "cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def compute_source_key(source_path: Path | str) -> str:
    """Compute a stable, canonical cache key for a source media file.

    Key is derived from the resolved canonical absolute path, file size,
    modification time, and the CACHE_FORMAT_VERSION.
    """
    p = Path(source_path)
    try:
        resolved = str(p.resolve())
    except Exception:
        resolved = str(p.absolute())

    size = 0
    mtime_ns = 0
    try:
        stat = p.stat()
        size = stat.st_size
        mtime_ns = stat.st_mtime_ns
    except OSError:
        pass

    raw = f"{resolved}|{size}|{mtime_ns}|{CACHE_FORMAT_VERSION}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    stem = p.stem or "media"
    return f"{stem}_{digest}"


def get_media_cache_dir(source_path: Path | str, create: bool = True) -> Path:
    """Return the per-source media cache directory."""
    key = compute_source_key(source_path)
    d = get_cache_root() / "media" / key
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def get_telemetry_npz_path(source_path: Path | str, create_dir: bool = True) -> Path:
    """Return the central cache path for processed telemetry NPZ."""
    return get_media_cache_dir(source_path, create=create_dir) / "telemetry.npz"


def get_gpmf_json_path(source_path: Path | str, create_dir: bool = True) -> Path:
    """Return the central cache path for raw GPMF JSON."""
    return get_media_cache_dir(source_path, create=create_dir) / "gpmf.json"


def get_gpmf_metadata_path(source_path: Path | str, create_dir: bool = True) -> Path:
    """Return the central cache path for GPMF contract metadata."""
    return get_media_cache_dir(source_path, create=create_dir) / "gpmf.meta.json"


def get_telem_time_json_path(source_path: Path | str, create_dir: bool = True) -> Path:
    """Return the central cache path for telem_time JSON."""
    return get_media_cache_dir(source_path, create=create_dir) / "telem_time.json"


def get_telem_time_metadata_path(source_path: Path | str, create_dir: bool = True) -> Path:
    """Return the central cache path for telem_time contract metadata."""
    return get_media_cache_dir(source_path, create=create_dir) / "telem_time.meta.json"


def get_media_metadata_path(source_path: Path | str, create_dir: bool = True) -> Path:
    """Return the index metadata path for the source cache."""
    return get_media_cache_dir(source_path, create=create_dir) / "metadata.json"


# ── Legacy Sidecar Paths (Read-Only) ────────────────────────────────────────

def get_legacy_telemetry_npz_path(source_path: Path | str) -> Path:
    p = Path(source_path)
    return p.with_name(p.stem + ".telemetry.npz")


def get_legacy_gpmf_json_path(source_path: Path | str) -> Path:
    p = Path(source_path)
    return p.with_suffix(".json")


def get_legacy_gpmf_meta_paths(source_path: Path | str) -> list[Path]:
    json_path = get_legacy_gpmf_json_path(source_path)
    return [
        json_path.with_name(f"{json_path.name}.meta.json"),
        json_path.with_name(f"{json_path.stem}.json.meta"),
        json_path.with_suffix(".json.meta"),
    ]


def get_legacy_telem_time_paths(source_path: Path | str) -> tuple[Path, Path]:
    p = Path(source_path)
    cache_path = p.with_name(f"{p.name}.telem_time.json")
    meta_path = cache_path.with_name(f"{cache_path.name}.meta.json")
    return cache_path, meta_path


# ── Logging ─────────────────────────────────────────────────────────────────

def log_cache_event(source: Path | str, status: str, path: Path | str, extra: str = "") -> None:
    """Log telemetry cache events once per source/status to avoid console spam."""
    src_p = Path(source)
    key = compute_source_key(src_p)
    dedup_key = (key, status, str(path))
    if dedup_key in _LOGGED_CACHE_EVENTS:
        return
    _LOGGED_CACHE_EVENTS.add(dedup_key)
    extra_str = f" ({extra})" if extra else ""
    print(
        f"[TELEMETRY CACHE] source={src_p.name} key={key} status={status} path={path}{extra_str}",
        flush=True,
    )


# ── Atomic File Write ───────────────────────────────────────────────────────

def atomic_write_file(destination: Path, write_fn: Callable[[Path], None]) -> None:
    """Atomically write a file using a PID-tagged temporary file and os.replace."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(
        f"{destination.name}.{os.getpid()}_{time.time_ns()}.tmp"
    )
    try:
        write_fn(temp_path)
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def atomic_save_json(destination: Path, data: Any) -> None:
    """Atomically save JSON payload to destination."""
    def _write(tmp: Path) -> None:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            f.flush()
            os.fsync(f.fileno())

    atomic_write_file(destination, _write)


def update_source_metadata(source_path: Path | str, artifact_name: str, size: int) -> None:
    """Update or create metadata.json for the media cache directory."""
    meta_path = get_media_metadata_path(source_path)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data: dict[str, Any] = {}
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    p = Path(source_path)
    if not data:
        data = {
            "source_key": compute_source_key(p),
            "source_path": str(p.resolve() if p.exists() else p.absolute()),
            "cache_format_version": CACHE_FORMAT_VERSION,
            "created_at": now_iso,
            "artifacts": {},
        }
        try:
            st = p.stat()
            data["source_size"] = st.st_size
            data["source_mtime_ns"] = st.st_mtime_ns
        except OSError:
            data["source_size"] = 0
            data["source_mtime_ns"] = 0

    data["last_accessed_at"] = now_iso
    artifacts = data.setdefault("artifacts", {})
    artifacts[artifact_name] = {
        "size": size,
        "updated_at": now_iso,
    }
    try:
        atomic_save_json(meta_path, data)
    except Exception as exc:
        print(f"[TelemetryCache] Failed to update metadata: {exc}", flush=True)


# ── Cache Cleanup Policy ────────────────────────────────────────────────────

def cleanup_cache(
    max_size_gb: float = 10.0,
    protected_keys: Optional[set[str]] = None,
) -> int:
    """Prune oldest cache directories until total size <= max_size_gb.

    Returns the number of bytes freed.
    """
    media_dir = get_cache_root() / "media"
    if not media_dir.exists():
        return 0

    protected = protected_keys or set()
    entries: list[tuple[float, int, Path]] = []
    total_bytes = 0

    for d in media_dir.iterdir():
        if not d.is_dir():
            continue
        if d.name in protected:
            continue

        dir_size = 0
        latest_mtime = 0.0
        meta_file = d / "metadata.json"
        if meta_file.exists():
            try:
                latest_mtime = meta_file.stat().st_mtime
            except OSError:
                pass

        for f in d.rglob("*"):
            if f.is_file():
                try:
                    st = f.stat()
                    dir_size += st.st_size
                    if st.st_mtime > latest_mtime:
                        latest_mtime = st.st_mtime
                except OSError:
                    pass

        entries.append((latest_mtime, dir_size, d))
        total_bytes += dir_size

    max_bytes = int(max_size_gb * (1024 ** 3))
    if total_bytes <= max_bytes:
        return 0

    # Sort oldest first
    entries.sort(key=lambda x: x[0])
    freed = 0
    for _, size, d in entries:
        if total_bytes - freed <= max_bytes:
            break
        try:
            shutil.rmtree(d, ignore_errors=True)
            freed += size
        except Exception:
            pass

    return freed


def clear_generated_cache() -> dict[str, int]:
    """Remove generated per-source entries under the managed ``media`` root.

    The cache root itself and files beside ``media`` are preserved. This keeps
    settings, capability metadata, user files, source media, and project data
    outside the cleanup scope.
    """
    media_dir = get_cache_root() / "media"
    result = {"files_removed": 0, "bytes_removed": 0, "entries_removed": 0}
    if not media_dir.exists():
        return result

    for entry in list(media_dir.iterdir()):
        if entry.is_dir():
            files = [path for path in entry.rglob("*") if path.is_file()]
        elif entry.is_file():
            files = [entry]
        else:
            continue

        entry_bytes = 0
        for path in files:
            try:
                entry_bytes += path.stat().st_size
            except OSError:
                pass

        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError as exc:
            print(f"[TelemetryCache] Cleanup skipped {entry}: {exc}", flush=True)
            continue

        result["files_removed"] += len(files)
        result["bytes_removed"] += entry_bytes
        result["entries_removed"] += 1

    return result
