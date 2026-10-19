"""Telemetry ↔ video time synchronization contract (FIT/GPX vs. camera clock).

Single contract used by preview, project editing and every export backend::

    telemetry_time = video_start_time + video_position + sync_offset_s

``video_start_time`` is the absolute anchor of the clip on the camera clock
(GPMF GPS time for GoPro, MP4 ``creation_time`` for DJI).  ``sync_offset_s``
is applied exactly once, by shifting activity (FIT/GPX) sample timestamps by
``-sync_offset_s`` when the samples are (re)derived.  Every consumer — preview
resolver, vectorized export preparation, charts, map marker, pause mapper —
reads the already shifted samples, so the offset is never added a second time
at lookup.  Camera streams (GPMF, DJI IMU) and the video itself never move.

The base alignment computed when an activity is loaded (absolute UTC,
timezone fallback or GoPro GPS trajectory) stays separate and unchanged.

Multi-file projects may carry per-clip corrections: clip ``i`` uses
``sync_offset_s + clip_offsets_s[i]`` inside its own time window.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

SYNC_LAYOUT_KEY = "telemetry_sync_offset_s"
SYNC_CLIP_LAYOUT_KEY = "telemetry_sync_clip_offsets_s"
SYNC_METHOD_LAYOUT_KEY = "telemetry_sync_method"

METHOD_NONE = "none"
METHOD_MANUAL = "manual"
METHOD_SMARTSYNC_IMU = "smartsync_imu"
METHOD_SMARTSYNC_GPS = "smartsync_gps"


SYNC_LAYOUT_KEYS = (SYNC_LAYOUT_KEY, SYNC_CLIP_LAYOUT_KEY, SYNC_METHOD_LAYOUT_KEY)


def strip_sync_keys(layout: Any) -> Any:
    """Remove material-specific sync keys from a HUD preset/default layout."""
    if isinstance(layout, dict):
        for key in SYNC_LAYOUT_KEYS:
            layout.pop(key, None)
    return layout


@dataclass
class TelemetrySyncState:
    offset_s: float = 0.0
    clip_offsets_s: dict[int, float] = field(default_factory=dict)
    method: str = METHOD_NONE
    confidence: Optional[float] = None
    confidence_level: str = ""
    detail: str = ""
    smartsync: Optional[dict[str, Any]] = None   # last SmartSync diagnostics

    def effective_clip_offset(self, clip_index: int) -> float:
        return float(self.offset_s) + float(self.clip_offsets_s.get(int(clip_index), 0.0))

    @property
    def has_clip_offsets(self) -> bool:
        return any(abs(v) > 1e-9 for v in self.clip_offsets_s.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "offset_s": round(float(self.offset_s), 4),
            "clip_offsets_s": {str(k): round(float(v), 4) for k, v in self.clip_offsets_s.items() if abs(v) > 1e-9},
            "method": self.method,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level,
            "detail": self.detail,
            "smartsync": self.smartsync,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "TelemetrySyncState":
        if not isinstance(data, dict):
            return cls()
        clips = {}
        for k, v in (data.get("clip_offsets_s") or {}).items():
            try:
                clips[int(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return cls(
            offset_s=float(data.get("offset_s", 0.0) or 0.0),
            clip_offsets_s=clips,
            method=str(data.get("method") or METHOD_NONE),
            confidence=data.get("confidence"),
            confidence_level=str(data.get("confidence_level") or ""),
            detail=str(data.get("detail") or ""),
            smartsync=data.get("smartsync") if isinstance(data.get("smartsync"), dict) else None,
        )


def _naive(dt: datetime) -> datetime:
    from datetime import timezone
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo is not None else dt


def _segments(
    global_offset_s: float,
    clip_windows: Optional[Sequence[tuple[datetime, datetime]]],
    clip_offsets_s: Optional[dict[int, float]],
) -> Optional[list[tuple[Optional[datetime], Optional[datetime], float]]]:
    """Piecewise mapping segments in *video* time: (lo, hi, offset).

    Boundaries between clips are the midpoints of the gaps between their
    windows, so every display instant belongs to exactly one clip.
    """
    if not clip_windows or not clip_offsets_s or not any(abs(v) > 1e-9 for v in clip_offsets_s.values()):
        return None
    wins = [(_naive(a), _naive(b)) for a, b in clip_windows]
    segs: list[tuple[Optional[datetime], Optional[datetime], float]] = []
    for i, (a, b) in enumerate(wins):
        lo = None if i == 0 else wins[i - 1][1] + (a - wins[i - 1][1]) / 2
        hi = None if i == len(wins) - 1 else b + (wins[i + 1][0] - b) / 2
        segs.append((lo, hi, float(global_offset_s) + float(clip_offsets_s.get(i, 0.0))))
    return segs


def shift_timestamps(
    items: Iterable[Any],
    get_ts,
    with_ts,
    global_offset_s: float,
    clip_windows: Optional[Sequence[tuple[datetime, datetime]]] = None,
    clip_offsets_s: Optional[dict[int, float]] = None,
) -> list[Any]:
    """Return new items whose activity timestamps follow the sync contract.

    An activity sample recorded at ``T`` is shown at video instant
    ``T - offset``.  With per-clip offsets a sample may appear in more than one
    clip window (or in none); the result stays sorted by display time.
    """
    segs = _segments(global_offset_s, clip_windows, clip_offsets_s)
    items = list(items)
    if segs is None:
        delta = timedelta(seconds=-float(global_offset_s))
        if abs(global_offset_s) < 1e-9:
            return [with_ts(it, get_ts(it)) for it in items]
        return [with_ts(it, get_ts(it) + delta) for it in items]
    out: list[Any] = []
    for lo, hi, off in segs:
        delta = timedelta(seconds=-off)
        for it in items:
            shown = get_ts(it) + delta
            naive_shown = _naive(shown)
            if lo is not None and naive_shown < lo:
                continue
            if hi is not None and naive_shown >= hi:
                continue
            out.append(with_ts(it, shown))
    out.sort(key=lambda it: _naive(get_ts(it)))
    return out


def representative_offset(state: TelemetrySyncState, clip_count: int = 1) -> float:
    """Single offset for activity-wide models (pause mapper, laps)."""
    if not state.has_clip_offsets or clip_count <= 1:
        return float(state.offset_s)
    vals = sorted(state.effective_clip_offset(i) for i in range(clip_count))
    return float(vals[len(vals) // 2])


# ---------------------------------------------------------------------------
# Per-material persistence (AppData, never next to the user's videos)
# ---------------------------------------------------------------------------

_STORE_LOCK = threading.Lock()


def _store_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or (Path.home() / ".bikeridehud"))
    d = base / "SportCamHUD" / "session"
    d.mkdir(parents=True, exist_ok=True)
    return d / "telemetry_sync.json"


def material_key(video_paths: Sequence[Path | str], activity_path: Optional[Path | str]) -> str:
    """Identity of a video set + activity file (path, size, mtime)."""
    parts: list[str] = []
    for p in list(video_paths) + ([activity_path] if activity_path else []):
        path = Path(p)
        try:
            st = path.stat()
            parts.append(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}")
        except OSError:
            parts.append(f"{path}|missing")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def load_sync_state(key: str, store_path: Optional[Path] = None) -> Optional[TelemetrySyncState]:
    path = store_path or _store_path()
    with _STORE_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    entry = (data.get("entries") or {}).get(key) if isinstance(data, dict) else None
    return TelemetrySyncState.from_dict(entry) if entry else None


def save_sync_state(key: str, state: Optional[TelemetrySyncState], store_path: Optional[Path] = None,
                    label: str = "") -> None:
    path = store_path or _store_path()
    with _STORE_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        entries = data.setdefault("entries", {})
        if state is None:
            entries.pop(key, None)
        else:
            entry = state.to_dict()
            entry["label"] = label
            entry["saved_at"] = datetime.now().isoformat(timespec="seconds")
            entries[key] = entry
        data["schema"] = 1
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
