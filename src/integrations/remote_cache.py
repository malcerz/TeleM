"""Local disk cache for remote activity telemetry and video-to-activity linkage."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def get_remote_cache_root() -> Path:
    """Return root directory for remote telemetry cache in LocalAppData."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        root = Path(base) / "BikeRideHUD" / "remote_telemetry"
    else:
        root = Path.home() / ".bikeridehud" / "remote_telemetry"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_provider_cache_dir(provider: str) -> Path:
    """Return cache subdirectory for a specific provider ('garmin' or 'strava')."""
    d = get_remote_cache_root() / provider.lower()
    d.mkdir(parents=True, exist_ok=True)
    return d


def compute_video_fingerprint(video_paths: list[Path | str]) -> str:
    """Compute stable fingerprint for a video or sequence of video clips."""
    tokens: list[str] = []
    for p in video_paths:
        path = Path(p)
        if path.exists():
            stat = path.stat()
            tokens.append(f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}")
        else:
            tokens.append(f"{path.name}:nonexistent")
    raw = "|".join(tokens)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_index_file() -> Path:
    return get_remote_cache_root() / "video_index.json"


def _read_index() -> dict[str, dict]:
    idx_file = _get_index_file()
    if not idx_file.exists():
        return {}
    try:
        data = json.loads(idx_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _write_index(index_data: dict[str, dict]) -> None:
    idx_file = _get_index_file()
    try:
        idx_file.write_text(json.dumps(index_data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def find_cached_video_telemetry(video_paths: list[Path | str]) -> Optional[tuple[str, str, Path]]:
    """Check if video sequence has cached remote telemetry.

    Returns (provider, activity_id, file_path) if valid cache hit, else None.
    """
    if not video_paths:
        return None
    fp = compute_video_fingerprint(video_paths)
    index = _read_index()
    entry = index.get(fp)
    if not entry:
        return None

    provider = entry.get("provider", "")
    activity_id = str(entry.get("activity_id", ""))
    cached_path_str = entry.get("file_path", "")
    if not cached_path_str:
        return None

    path = Path(cached_path_str)
    if path.is_file() and path.stat().st_size > 0:
        return provider, activity_id, path

    # If full path moved, check standard provider cache location
    provider_dir = get_provider_cache_dir(provider)
    for ext in (".fit", ".gpx"):
        cand = provider_dir / f"{activity_id}{ext}"
        if cand.is_file() and cand.stat().st_size > 0:
            return provider, activity_id, cand

    return None


def save_cached_video_telemetry(
    video_paths: list[Path | str],
    provider: str,
    activity_id: str,
    telemetry_file: Path,
    metadata: Optional[dict] = None,
) -> None:
    """Save video-to-activity linkage and write metadata JSON alongside telemetry file."""
    if not video_paths or not telemetry_file.exists():
        return

    fp = compute_video_fingerprint(video_paths)
    index = _read_index()
    index[fp] = {
        "provider": provider.lower(),
        "activity_id": str(activity_id),
        "file_path": str(telemetry_file.resolve()),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "first_video_name": Path(video_paths[0]).name,
        "clip_count": len(video_paths),
    }
    _write_index(index)

    # Save activity metadata JSON in provider cache directory
    prov_dir = get_provider_cache_dir(provider)
    meta_path = prov_dir / f"{activity_id}.json"
    meta_payload = {
        "provider": provider.lower(),
        "activity_id": str(activity_id),
        "file_path": str(telemetry_file.resolve()),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }
    try:
        meta_path.write_text(json.dumps(meta_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
