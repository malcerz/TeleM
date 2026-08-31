"""Multi-file video support for TeleM — VideoClip model + global timeline.

This module provides the mapping between the *compressed project-global* time
axis (the continuous final movie) and the *absolute telemetry* timestamps.

Core invariants (see AGENTS.md / RAPORT_MULTIFILE_ETAP_1_AUDYT.md):

    GLOBAL VIDEO TIME != ABSOLUTE TELEMETRY TIME

    global_time -> clip -> local_time -> absolute_timestamp -> telemetry

``VideoTimeline`` is pure logic (no GUI, no ffmpeg runtime dependency for the
mapping itself).  ``build_timeline_from_paths`` is the only place that probes
real files with ffprobe.  This keeps the module fully unit-testable and safe to
use from renderer worker processes.

Semantics:
- The project global axis is the *sum* of clip durations (gaps between the real
  recordings are REMOVED from the final movie).
- Each clip keeps its own absolute start/end so telemetry lookup always uses the
  real absolute timestamp of the active clip.
- ``project_duration_s`` is NEVER ``last_absolute - first_absolute``.
- Clip order is the order given by the user; nothing is re-sorted.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.render_logging import render_print

print = render_print
from typing import Any, Callable, Optional

# datetime convention: naive UTC (matches the rest of TeleM).
_UTC = timezone.utc


def _as_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Return *dt* as a naive-UTC datetime (or None)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(_UTC).replace(tzinfo=None)
    return dt


def _parse_fps(rate_text: Optional[str], default_fps: float = 30.0) -> float:
    """Parse an ffprobe frame-rate string like '30000/1001' or '30.0'."""
    if not rate_text or rate_text == "0/0":
        return default_fps
    if "/" in str(rate_text):
        a, b = str(rate_text).split("/")
        try:
            a, b = float(a), float(b)
        except ValueError:
            return default_fps
        if b == 0:
            return default_fps
        return a / b
    try:
        return float(rate_text)
    except (TypeError, ValueError):
        return default_fps


def _parse_creation_time(text: Optional[str]) -> Optional[datetime]:
    """Parse an ffprobe ``creation_time`` tag into naive-UTC datetime."""
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
        return _as_naive_utc(dt)
    except (TypeError, ValueError):
        return None


# ── ETAP 3: per-clip absolute timestamp resolution ─────────────────────────

# Canonical timestamp sources.  Priority when resolving a clip's absolute
# start (see RAPORT_MULTIFILE_ETAP_3_PER_CLIP_TIME.md):
#   1. gpmf_gps9            — embedded GPS9 days+secs (real absolute GPS time)
#   2. gpmf_gpsu            — GPSU block absolute datetime
#   3. container_creation_time — ffprobe creation_time tag
#   4. continuous_fallback  — base_dt + clip.global_start_s (unreliable)
TIMESTAMP_SOURCE_GPMF_GPS9 = "gpmf_gps9"
TIMESTAMP_SOURCE_GPMF_GPSU = "gpmf_gpsu"
TIMESTAMP_SOURCE_CREATION_TIME = "container_creation_time"
TIMESTAMP_SOURCE_CONTINUOUS_FALLBACK = "continuous_fallback"
TIMESTAMP_SOURCE_UNKNOWN = "unknown"

#: GPMF-only failure modes that fall through to creation_time.
_GPMF_NO_TIME_SOURCES = {
    "gpmf_failed",
    "gpmf_unavailable",
    "no_gps_time",
}

_GPMF_RELIABLE_SOURCES = {
    TIMESTAMP_SOURCE_GPMF_GPS9,
    TIMESTAMP_SOURCE_GPMF_GPSU,
}

# Timestamp quality — precision of the resolved absolute clip start.
#   exact     — GPS9 absolute time corrected by a file-local sample offset
#               (STMP <= clip duration): true clip start, sub-ms precision.
#   estimated — real absolute source (GPS9/GPSU/creation_time) but the exact
#               file-local sample offset is unknown: start approximated by the
#               GPS sample time (sub-second error) or by the container time.
#   fallback  — no reliable absolute source (continuous_fallback / unknown).
TIMESTAMP_QUALITY_EXACT = "exact"
TIMESTAMP_QUALITY_ESTIMATED = "estimated"
TIMESTAMP_QUALITY_FALLBACK = "fallback"


@dataclass
class ClipTimestampResolution:
    """Outcome of resolving one clip's absolute start time.

    ``absolute_start_dt`` is the true start of the clip (naive UTC).  When only
    the first GPS *sample* time is known without its local offset, the start is
    approximated by that sample time (documented in ``timestamp_detail``) and
    ``timestamp_quality`` is set to ``estimated`` (not ``exact``).
    """

    absolute_start_dt: Optional[datetime] = None
    absolute_end_dt: Optional[datetime] = None
    timestamp_source: str = TIMESTAMP_SOURCE_UNKNOWN
    timestamp_reliable: bool = False
    timestamp_detail: str = ""
    timestamp_quality: str = TIMESTAMP_QUALITY_FALLBACK


# In-memory cache: once a clip's timestamp is resolved it is reused within the
# process (avoids re-extracting GPMF of multi-GB files on rebuilds).  The key
# includes the clip duration because the STMP file-local decision depends on it.
_TIME_RESOLUTION_CACHE: dict[tuple[str, Optional[float]], ClipTimestampResolution] = {}


def clear_time_resolution_cache() -> None:
    """Drop the in-memory per-clip timestamp cache."""
    _TIME_RESOLUTION_CACHE.clear()


def _resolution_cache_key(
    path: Path | str, duration_s: Optional[float]
) -> tuple[str, Optional[float]]:
    key = str(Path(path).resolve())
    if duration_s is None:
        return (key, None)
    return (key, round(float(duration_s), 6))


def _to_number(value: Any) -> Optional[float]:
    """Best-effort scalar conversion for STMP/TSMP fields."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, bytes):
        try:
            return float(value.decode("ascii", errors="ignore"))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)):
        try:
            return float(value[0])
        except (TypeError, ValueError, IndexError):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_gpsu_datetime(val: Any) -> Optional[datetime]:
    """GPSU block: (year, month, day, hour, minute, sec, ms, ...) -> UTC."""
    try:
        if isinstance(val, (list, tuple)) and len(val) >= 7:
            year, month, day, hour, minute, sec, ms = (int(x) for x in val[:7])
            return datetime(
                year, month, day, hour, minute, sec, ms * 1000, tzinfo=_UTC
            )
    except (TypeError, ValueError):
        pass
    return None


def _fmt_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds")


def _first_absolute_time_from_parsed(
    parsed: list, duration_s: Optional[float] = None
) -> ClipTimestampResolution:
    """Walk a flat GPMF parse and derive the clip start from GPS9/GPSU.

    Uses the GPMF "Property Hierarchy" convention: within a STRM the last seen
    STMP/TSMP/TYPE/SCAL scope the following data block.  For the first valid
    GPS9 sample:

        candidate_local = STMP / 1_000_000  (+ sample_idx * 0.1)
        clip_start     = GPS9_absolute_time - candidate_local

    The STMP-based local offset is applied ONLY when it is plausibly file-local
    (``candidate_local <= duration_s + tolerance``).  GoPro STMP is relative to
    the *recording session*, so a later chapter can carry a STMP far larger than
    the clip itself; in that case the file-local offset is unknowable from this
    clip alone and the GPS sample's absolute time is used as the clip start
    (sub-second error), which is still more authoritative than creation_time.
    """
    stmp: Optional[float] = None
    tsmp: Optional[float] = None
    type_str: Optional[str] = None
    scal: Any = None
    gpsu_start: Optional[datetime] = None
    gpsu_detail = ""

    for key, val in parsed:
        if key == "STMP":
            stmp = _to_number(val)
        elif key == "TSMP":
            tsmp = _to_number(val)
        elif key == "TYPE":
            type_str = (
                val.decode("ascii", errors="ignore").rstrip("\x00")
                if isinstance(val, bytes) else str(val)
            )
        elif key == "SCAL":
            scal = val
        elif key == "GPSU":
            dt = _parse_gpsu_datetime(val)
            if dt is not None and gpsu_start is None:
                gpsu_start = dt
                gpsu_detail = f"gpsu={_fmt_iso(dt)}"
        elif key == "GPS9":
            try:
                from src.telemetry_gpmf_new import _decode_gps9_real_samples
                samples = _decode_gps9_real_samples(val, type_str, scal)
            except Exception:
                samples = []
            if samples:
                for si, fields in enumerate(samples):
                    lat, lon, _alt, _s2d, _s3d, days, secs, _dop, _fix = fields
                    try:
                        if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
                            continue
                        if float(lat) == 0.0 and float(lon) == 0.0:
                            continue
                    except (TypeError, ValueError):
                        continue
                    try:
                        from src.telemetry_gpmf_new import _gps9_datetime as _g9
                        dt = _g9(days, secs)
                    except Exception:
                        dt = None
                    if dt is None:
                        continue

                    def _file_local(cand: Optional[float]) -> bool:
                        if cand is None:
                            return False
                        if duration_s is None:
                            return True
                        return cand <= duration_s + 1.0

                    local_s: Optional[float] = None
                    local_reason = "no_stmp"
                    if stmp is not None:
                        cand = stmp / 1_000_000.0 + si * 0.1
                        if _file_local(cand):
                            local_s = cand
                            local_reason = "stmp"
                        else:
                            local_reason = (
                                f"stmp_not_file_local({cand:.3f}s > "
                                f"duration {duration_s:.3f}s)"
                            )
                    elif tsmp is not None:
                        cand = tsmp / 1_000_000.0 + si * 0.1
                        if _file_local(cand):
                            local_s = cand
                            local_reason = "tsmp"
                        else:
                            local_reason = (
                                f"tsmp_not_file_local({cand:.3f}s > "
                                f"duration {duration_s:.3f}s)"
                            )
                    detail = (
                        f"gps9_first_abs={_fmt_iso(dt)} "
                        f"stmp={stmp!r} tsmp={tsmp!r} local_s={local_s} "
                        f"reason={local_reason}"
                    )
                    if local_s is not None:
                        start = dt - timedelta(seconds=local_s)
                        return ClipTimestampResolution(
                            _as_naive_utc(start), None,
                            TIMESTAMP_SOURCE_GPMF_GPS9, True, detail,
                            TIMESTAMP_QUALITY_EXACT,
                        )
                    # Local offset unknowable -> GPS sample time as clip start
                    # (authoritative over creation_time, but only estimated).
                    return ClipTimestampResolution(
                        _as_naive_utc(dt), None,
                        TIMESTAMP_SOURCE_GPMF_GPS9, True,
                        detail + " (using GPS sample time as clip start)",
                        TIMESTAMP_QUALITY_ESTIMATED,
                    )
            continue

    if gpsu_start is not None:
        return ClipTimestampResolution(
            _as_naive_utc(gpsu_start), None,
            TIMESTAMP_SOURCE_GPMF_GPSU, True, gpsu_detail,
            TIMESTAMP_QUALITY_ESTIMATED,
        )
    return ClipTimestampResolution(
        None, None, "no_gps_time", False,
        "no GPS9/GPSU absolute time in GPMF",
        TIMESTAMP_QUALITY_FALLBACK,
    )


def _resolve_from_gpmf(
    path: Path | str, ffmpeg_exe: str, ffprobe_exe: str,
    duration_s: Optional[float] = None,
) -> ClipTimestampResolution:
    """Extract + parse the clip's GPMF and resolve its absolute start."""
    try:
        from src.telemetry_gpmf_new import extract_gpmf, parse_gpmf
    except Exception as exc:  # pragma: no cover - import guard
        return ClipTimestampResolution(
            None, None, "gpmf_unavailable", False, str(exc)
        )
    try:
        raw = extract_gpmf(path, ffmpeg_exe=ffmpeg_exe, ffprobe_exe=ffprobe_exe)
        parsed = parse_gpmf(raw)
    except Exception as exc:
        return ClipTimestampResolution(
            None, None, "gpmf_failed", False, str(exc)
        )
    return _first_absolute_time_from_parsed(parsed, duration_s=duration_s)


# ── Disk cache (sidecar next to the video, following the existing GPMF
#    JSON sidecar convention `<video>.json` / `<video>.json.meta.json`).
TELEM_TIME_CACHE_VERSION = 1


def _telem_time_cache_paths(video_path: Path | str) -> tuple[Path, Path]:
    p = Path(video_path)
    cache_path = p.with_name(f"{p.name}.telem_time.json")
    return cache_path, cache_path.with_name(f"{cache_path.name}.meta.json")


def _write_telem_time_cache(
    video_path: Path | str, res: ClipTimestampResolution,
    duration_s: Optional[float] = None,
) -> None:
    """Atomically persist a resolved clip timestamp (best-effort).

    Only written when the resolution was computed with a known clip duration
    (so the STMP file-local decision is reproducible across processes).
    """
    if res.absolute_start_dt is None or duration_s is None:
        return
    try:
        cache_path, meta_path = _telem_time_cache_paths(video_path)
        source = Path(video_path)
        stat = source.stat()
        payload = {
            "_telem_time_cache": {
                "version": TELEM_TIME_CACHE_VERSION,
                "source_size": stat.st_size,
                "source_mtime_ns": stat.st_mtime_ns,
                "duration_s": round(float(duration_s), 6),
            },
            "absolute_start_dt": res.absolute_start_dt.isoformat(),
            "timestamp_source": res.timestamp_source,
            "timestamp_reliable": bool(res.timestamp_reliable),
            "timestamp_detail": res.timestamp_detail or "",
        }
        import tempfile
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        for path, value in ((cache_path, payload), (meta_path, {
            "_telem_time_cache": payload["_telem_time_cache"],
        })):
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                tmp = Path(handle.name)
                json.dump(value, handle, indent=2, ensure_ascii=False)
                handle.flush()
            import os
            os.replace(tmp, path)
    except Exception as exc:  # cache is best-effort, never fatal
        print(f"[MultiFile] telem_time cache write skipped: {exc}", flush=True)


def _load_valid_telem_time_cache(
    video_path: Path | str, duration_s: Optional[float] = None
) -> Optional[ClipTimestampResolution]:
    """Load a cached resolution only when its source fingerprint matches."""
    try:
        cache_path, meta_path = _telem_time_cache_paths(video_path)
        if not cache_path.exists() or not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        contract = meta.get("_telem_time_cache", {})
        if contract.get("version") != TELEM_TIME_CACHE_VERSION:
            return None
        source = Path(video_path)
        stat = source.stat()
        if contract.get("source_size") != stat.st_size:
            return None
        if contract.get("source_mtime_ns") != stat.st_mtime_ns:
            return None
        if duration_s is not None and contract.get("duration_s") is not None:
            if abs(float(contract["duration_s"]) - float(duration_s)) > 0.01:
                return None
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        start = data.get("absolute_start_dt")
        if not start:
            return None
        return ClipTimestampResolution(
            absolute_start_dt=_as_naive_utc(datetime.fromisoformat(start)),
            timestamp_source=data.get("timestamp_source", TIMESTAMP_SOURCE_UNKNOWN),
            timestamp_reliable=bool(data.get("timestamp_reliable", False)),
            timestamp_detail=data.get("timestamp_detail", ""),
            # Version-1 caches predate the explicit quality field.  Preserve
            # their proven GPMF reliability instead of silently relabelling
            # them as continuous/fallback timestamps.
            timestamp_quality=data.get(
                "timestamp_quality",
                TIMESTAMP_QUALITY_EXACT
                if data.get("timestamp_source") in _GPMF_RELIABLE_SOURCES
                else TIMESTAMP_QUALITY_ESTIMATED,
            ),
        )
    except Exception:
        return None


def resolve_clip_timestamp(
    path: Path | str,
    ffmpeg_exe: str = "ffmpeg",
    ffprobe_exe: str = "ffprobe",
    use_cache: bool = True,
    duration_s: Optional[float] = None,
) -> ClipTimestampResolution:
    """Resolve one clip's absolute start (single logical layer).

    Priority (see report):
        1. GPMF GPS9 (embedded real GPS time, with STMP local-offset correction
           only when the STMP is file-local)
        2. GPMF GPSU (absolute block datetime)
        3. container creation_time (ffprobe)
        4. no reliable source -> ``unknown`` (the timeline then applies the
           explicit ``continuous_fallback`` marker)

    ``duration_s`` (clip duration) is used to decide whether STMP is a
    file-local offset (<= duration) or a session-relative one (larger).  When
    it is not file-local the GPS sample absolute time is used as the clip start.

    Result is cached in memory and in a fingerprint-checked disk sidecar.
    """
    key = _resolution_cache_key(path, duration_s)
    if use_cache and key in _TIME_RESOLUTION_CACHE:
        return _TIME_RESOLUTION_CACHE[key]

    if use_cache:
        cached = _load_valid_telem_time_cache(path, duration_s=duration_s)
        if cached is not None:
            _TIME_RESOLUTION_CACHE[key] = cached
            return cached

    res = _resolve_from_gpmf(path, ffmpeg_exe, ffprobe_exe, duration_s=duration_s)
    if res.timestamp_source in _GPMF_RELIABLE_SOURCES:
        if use_cache:
            _TIME_RESOLUTION_CACHE[key] = res
            _write_telem_time_cache(path, res, duration_s=duration_s)
        return res

    # GPMF unavailable / no GPS time -> creation_time fallback (estimated).
    ct = resolve_clip_absolute_start(path, ffprobe_exe)
    if ct is not None:
        res = ClipTimestampResolution(
            absolute_start_dt=ct,
            timestamp_source=TIMESTAMP_SOURCE_CREATION_TIME,
            timestamp_reliable=True,
            timestamp_detail=f"creation_time={_fmt_iso(ct)} (GPMF: {res.timestamp_source})",
            timestamp_quality=TIMESTAMP_QUALITY_ESTIMATED,
        )
        if use_cache:
            _TIME_RESOLUTION_CACHE[key] = res
            _write_telem_time_cache(path, res, duration_s=duration_s)
        return res

    if use_cache:
        _TIME_RESOLUTION_CACHE[key] = res
    return res


@dataclass
class VideoClip:
    """One input video file within a multi-clip project.

    Fields:
        path:              path to the video file.
        duration_s:        duration of this clip (seconds, from ffprobe).
        fps / width / height: primary video stream properties.
        absolute_start_dt: real absolute start time of this clip (naive UTC).
                           For clip 0 this is the project ``start_dt_utc``.
        absolute_end_dt:   ``absolute_start_dt + duration_s`` (recomputed by
                           ``VideoTimeline._rebuild``).
        global_start_s:    start of this clip on the compressed project axis.
        global_end_s:      end of this clip on the compressed project axis.
    """

    path: Path
    duration_s: float = 0.0
    fps: float = 30.0
    width: int = 0
    height: int = 0
    absolute_start_dt: Optional[datetime] = None
    absolute_end_dt: Optional[datetime] = None
    global_start_s: float = 0.0
    global_end_s: float = 0.0
    # ── ETAP 3/4A: provenance of the absolute start time ─────────────────
    # timestamp_source:   gpmf_gps9 | gpmf_gpsu | container_creation_time |
    #                     continuous_fallback | unknown
    # timestamp_reliable: True for GPMF/creation-time, False for fallback.
    # timestamp_quality:  exact | estimated | fallback
    #                     (exact only when a file-local sample offset is known)
    # timestamp_detail:   human-readable explanation (first GPS sample, STMP,
    #                     creation_time value, fallback reason, ...).
    timestamp_source: str = TIMESTAMP_SOURCE_UNKNOWN
    timestamp_reliable: bool = False
    timestamp_detail: str = ""
    timestamp_quality: str = TIMESTAMP_QUALITY_FALLBACK
    metadata: dict = field(default_factory=dict)
    frame_count: int = 0
    local_start_s: float = 0.0
    source_duration_s: float = 0.0
    # Position on the original compressed activity axis.  Export subsets keep
    # this anchor so activity-global statistics do not restart at range 0.
    activity_start_s: Optional[float] = None

    @property
    def local_duration_s(self) -> float:
        """Duration on the local (inside-clip) axis."""
        return self.duration_s

    @property
    def local_end_s(self) -> float:
        return self.local_start_s + self.duration_s

    def output_frame_count(self, target_fps: float) -> int:
        """Return this clip's canonical output-frame contribution.

        Preserve the probed source count when source and output rates match.
        Otherwise use the clip's visual duration on the requested CFR grid.
        """
        full_source = (
            self.local_start_s == 0.0
            and (self.source_duration_s <= 0.0
                 or abs(self.source_duration_s - self.duration_s) < 1e-6)
        )
        if full_source and self.frame_count > 0 and abs(self.fps - target_fps) < 1e-6:
            return self.frame_count
        return max(0, int(round(self.duration_s * target_fps)))


class VideoTimeline:
    """Ordered list of clips mapped onto one compressed global timeline.

    Example (two clips with a real 20-minute gap):

        clip0: abs 10:05-10:15, global 0-10
        clip1: abs 10:35-10:50, global 10-25

        global 12:00 -> clip1, local 2:00 -> absolute 10:37:00
    """

    def __init__(
        self,
        clips: Optional[list[VideoClip]] = None,
        base_dt: Optional[datetime] = None,
    ) -> None:
        #: Project absolute start (telemetry.start_dt_utc). Used as clip0 start.
        self.base_dt: Optional[datetime] = _as_naive_utc(base_dt)
        self.clips: list[VideoClip] = []
        if clips:
            self._rebuild(list(clips))

    # ── Construction helpers ────────────────────────────────────────────────

    def _rebuild(self, clips: list[VideoClip]) -> None:
        """Recompute global offsets and absolute ends for all clips.

        Also finalises the timestamp provenance:
        - project ``base_dt`` fills clip 0 only when that clip has no reliable
          source-local absolute timestamp;
        - a clip with no reliable absolute start is explicitly marked
          ``continuous_fallback`` (the mapping-time degraded fallback).
        """
        offset = 0.0
        base = self.base_dt
        for i, clip in enumerate(clips):
            clip.global_start_s = offset
            clip.global_end_s = offset + clip.duration_s
            if clip.activity_start_s is None:
                clip.activity_start_s = offset
            if (
                i == 0 and base is not None
                and (clip.absolute_start_dt is None or not clip.timestamp_reliable)
            ):
                # Project anchor is a fallback only. A reliable clip-local GPMF
                # timestamp remains authoritative even when it differs from the
                # telemetry manager's legacy start anchor.
                clip.absolute_start_dt = base
                clip.timestamp_reliable = True
                if clip.timestamp_source not in (
                    _GPMF_RELIABLE_SOURCES
                    | {TIMESTAMP_SOURCE_CREATION_TIME,
                       "project_start_anchor", "custom_resolver"}
                ):
                    # Legacy: project start_dt_utc derives from the first clip's
                    # GPMF anchor, so treat it as GPS-derived when available.
                    clip.timestamp_source = (
                        TIMESTAMP_SOURCE_GPMF_GPS9
                        if clip.timestamp_reliable
                        else TIMESTAMP_SOURCE_CREATION_TIME
                    )
                if clip.timestamp_quality == TIMESTAMP_QUALITY_FALLBACK:
                    # Project start_dt_utc is the telemetry GPMF anchor.
                    clip.timestamp_quality = TIMESTAMP_QUALITY_EXACT
                clip.timestamp_detail = (
                    f"{clip.timestamp_detail} | "
                    f"re-anchored to project start_dt_utc={_fmt_iso(base)}"
                ).strip(" |")
            clip.absolute_start_dt = _as_naive_utc(clip.absolute_start_dt)
            if clip.absolute_start_dt is not None:
                clip.absolute_end_dt = clip.absolute_start_dt + timedelta(
                    seconds=clip.local_end_s
                )
            else:
                clip.absolute_end_dt = None
                clip.timestamp_source = TIMESTAMP_SOURCE_CONTINUOUS_FALLBACK
                clip.timestamp_reliable = False
                clip.timestamp_quality = TIMESTAMP_QUALITY_FALLBACK
                clip.timestamp_detail = (
                    f"{clip.timestamp_detail} | continuous fallback "
                    f"(base_dt + global_start_s)"
                ).strip(" |")
            offset = clip.global_end_s
        self.clips = clips

    def set_base_dt(self, base_dt: Optional[datetime]) -> None:
        """Set the project absolute start and rebuild (re-anchors clip 0)."""
        self.base_dt = _as_naive_utc(base_dt)
        if self.clips:
            self._rebuild(self.clips)

    @classmethod
    def from_clips(cls, clips: list[VideoClip], base_dt: Optional[datetime] = None) -> "VideoTimeline":
        """Build a timeline from already-created clips (pure, no probing)."""
        return cls(clips, base_dt=base_dt)

    # ── Basic properties ────────────────────────────────────────────────────

    @property
    def project_duration_s(self) -> float:
        """Total duration of the compressed project (sum of clip durations)."""
        if not self.clips:
            return 0.0
        return self.clips[-1].global_end_s

    @property
    def clip_count(self) -> int:
        return len(self.clips)

    @property
    def is_single_file(self) -> bool:
        """True when the project contains exactly one clip (legacy mode)."""
        return len(self.clips) == 1

    def output_frame_counts(self, target_fps: float) -> list[int]:
        """Canonical per-clip frame plan for a CFR export."""
        return [clip.output_frame_count(target_fps) for clip in self.clips]

    def output_frame_count(self, target_fps: float) -> int:
        """Canonical total frame count for a CFR export."""
        return sum(self.output_frame_counts(target_fps))

    def frame_to_clip(
        self, frame_index: int, target_fps: float
    ) -> tuple[Optional[int], int]:
        """Map a global output frame to ``(clip index, local frame)``.

        Integer boundaries avoid source switches depending on container
        duration rounding or floating-point time comparisons.
        """
        counts = self.output_frame_counts(target_fps)
        if not counts:
            return None, 0
        frame = max(0, int(frame_index))
        offset = 0
        for idx, count in enumerate(counts):
            if frame < offset + count:
                local_start_frame = int(round(
                    self.clips[idx].local_start_s * target_fps
                ))
                return idx, local_start_frame + frame - offset
            offset += count
        local_start_frame = int(round(
            self.clips[-1].local_start_s * target_fps
        ))
        return (
            len(counts) - 1,
            local_start_frame + max(0, counts[-1] - 1),
        )

    def frame_to_activity_elapsed(
        self, frame_index: int, target_fps: float
    ) -> float:
        """Map an output frame to elapsed time on the original activity axis."""
        clip_index, local_frame = self.frame_to_clip(frame_index, target_fps)
        if clip_index is None or target_fps <= 0:
            return 0.0
        clip = self.clips[clip_index]
        anchor = (
            float(clip.activity_start_s)
            if clip.activity_start_s is not None else clip.global_start_s
        )
        return max(
            0.0,
            anchor + local_frame / target_fps - clip.local_start_s,
        )

    def subset(self, ranges: list[tuple[int, float, float]]) -> "VideoTimeline":
        """Create an export timeline from real per-source local ranges.

        Each tuple is ``(clip_index, local_start_s, local_end_s)``. Repeated
        source clips are allowed and remain distinct decoder segments.
        """
        selected: list[VideoClip] = []
        for clip_index, local_start, local_end in ranges:
            source = self.clips[int(clip_index)]
            start = max(0.0, float(local_start))
            end = min(source.local_end_s, float(local_end))
            if end <= start:
                raise ValueError("timeline subset range must have end > start")
            selected.append(VideoClip(
                path=source.path,
                duration_s=end - start,
                fps=source.fps,
                width=source.width,
                height=source.height,
                absolute_start_dt=source.absolute_start_dt,
                timestamp_source=source.timestamp_source,
                timestamp_reliable=source.timestamp_reliable,
                timestamp_detail=source.timestamp_detail,
                timestamp_quality=source.timestamp_quality,
                metadata=dict(source.metadata),
                frame_count=max(0, int(round((end - start) * source.fps))),
                local_start_s=start,
                source_duration_s=(
                    source.source_duration_s or source.local_end_s
                ),
                activity_start_s=(
                    float(source.activity_start_s)
                    if source.activity_start_s is not None
                    else source.global_start_s
                ) + start - source.local_start_s,
            ))
        return VideoTimeline(selected, base_dt=self.base_dt)

    # ── Global → clip / local ───────────────────────────────────────────────

    def global_to_clip(self, global_time: float) -> tuple[Optional[int], float]:
        """Map a global time to ``(clip_index, local_time_within_clip)``.

        Out-of-range values are clamped to the valid axis.  A value exactly at
        a clip boundary belongs to the *next* clip (first frame of next clip),
        matching the "last frame of clip i / first frame of clip i+1" contract.
        """
        if not self.clips:
            return None, 0.0
        g = max(0.0, min(float(global_time), self.project_duration_s))
        for i, clip in enumerate(self.clips):
            if g < clip.global_end_s:
                return i, clip.local_start_s + g - clip.global_start_s
        # At (or past) the exact project end -> last clip, its last local time.
        last = self.clips[-1]
        return len(self.clips) - 1, last.local_end_s

    def clip_at(self, global_time: float) -> Optional[VideoClip]:
        """Return the active clip for a given global time (or None)."""
        idx, _ = self.global_to_clip(global_time)
        if idx is None:
            return None
        return self.clips[idx]

    def global_to_local(self, global_time: float) -> tuple[Optional[VideoClip], float]:
        """Convenience: ``(clip, local_time)`` for a global time."""
        idx, local = self.global_to_clip(global_time)
        if idx is None:
            return None, 0.0
        return self.clips[idx], local

    # ── Global → absolute timestamp (the core resolver) ─────────────────────

    def global_to_absolute(
        self, global_time: float, base_dt: Optional[datetime] = None
    ) -> Optional[datetime]:
        """Map a global time to the absolute telemetry timestamp.

        ``global_time -> clip -> local_time -> clip.absolute_start_dt + local``.

        If the active clip has no resolved absolute start, it degrades to the
        contiguous assumption (``base_dt + clip.global_start_s``) and the caller
        is expected to log this as a fallback.
        """
        idx, local = self.global_to_clip(global_time)
        if idx is None:
            return None
        clip = self.clips[idx]
        start = clip.absolute_start_dt
        if start is None:
            base = base_dt if base_dt is not None else self.base_dt
            if base is None:
                return None
            start = _as_naive_utc(base) + timedelta(seconds=clip.global_start_s)
        return start + timedelta(seconds=local)

    def frame_to_absolute(
        self, frame_index: int, target_fps: float, update_rate_step: int = 1
    ) -> Optional[datetime]:
        """Map an overlay frame index to an absolute timestamp.

        Matches the existing linear grid ``sample_t = index/fps`` and then
        applies the clip-aware absolute mapping.
        """
        sample_t = (frame_index * update_rate_step) / target_fps
        return self.global_to_absolute(sample_t)

    # ── Absolute timestamp → global (reverse, for precompute/SmartSync) ─────

    def absolute_to_global(self, absolute_dt: datetime) -> Optional[float]:
        """Map an absolute timestamp back to the global axis.

        Returns the global time of the clip whose ``[absolute_start, absolute_end]``
        window contains *absolute_dt*, or None when no clip covers it.
        """
        if not self.clips:
            return None
        dt = _as_naive_utc(absolute_dt)
        if dt is None:
            return None
        for clip in self.clips:
            start = _as_naive_utc(clip.absolute_start_dt)
            if start is None:
                continue
            local = (dt - start).total_seconds()
            if clip.local_start_s - 1e-6 <= local <= clip.local_end_s + 1e-6:
                return clip.global_start_s + local - clip.local_start_s
        return None


# ── File probing (the only ffprobe-dependent part) ─────────────────────────


def probe_video_info(
    ffprobe_exe: str, path: Path | str, default_fps: float = 30.0
) -> dict:
    """Probe duration/fps/width/height of one video via ffprobe.

    Returns a dict with keys ``duration_s``, ``fps``, ``width``, ``height``.
    Never raises: on any failure returns zeros + ``default_fps``.
    """
    cmd = [
        ffprobe_exe, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=r_frame_rate,avg_frame_rate,width,height,duration,nb_frames:format=duration",
        "-of", "json", str(path),
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return {"duration_s": 0.0, "fps": default_fps, "width": 0, "height": 0, "frame_count": 0}
    if p.returncode != 0:
        return {"duration_s": 0.0, "fps": default_fps, "width": 0, "height": 0, "frame_count": 0}
    try:
        data = json.loads(p.stdout or "{}")
    except (json.JSONDecodeError, ValueError):
        return {"duration_s": 0.0, "fps": default_fps, "width": 0, "height": 0, "frame_count": 0}

    streams = data.get("streams", [])
    try:
        duration_s = float(data.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration_s = 0.0

    fps = default_fps
    width = 0
    height = 0
    frame_count = 0
    if streams:
        rate = streams[0].get("avg_frame_rate") or streams[0].get("r_frame_rate")
        fps = _parse_fps(rate, default_fps)
        try:
            width = int(streams[0].get("width", 0) or 0)
            height = int(streams[0].get("height", 0) or 0)
            frame_count = int(streams[0].get("nb_frames", 0) or 0)
        except (TypeError, ValueError):
            width = height = frame_count = 0
        # The visual stream, not container/audio/GPMF duration, owns clip
        # boundaries.  This prevents MF EOS from arriving before a switch.
        if frame_count > 0 and fps > 0:
            duration_s = frame_count / fps
        elif streams[0].get("duration") is not None:
            try:
                duration_s = float(streams[0]["duration"])
            except (TypeError, ValueError):
                pass
    return {
        "duration_s": duration_s, "fps": fps, "width": width,
        "height": height, "frame_count": frame_count,
    }


def resolve_clip_absolute_start(
    path: Path | str, ffprobe_exe: str = "ffprobe"
) -> Optional[datetime]:
    """Resolve a clip's absolute start from its container ``creation_time``.

    Naive-UTC result.  Returns None when unavailable.  This is the STAGE-1
    fallback; a later stage upgrades clip starts to each clip's own GPMF GPS
    anchor (which is more accurate for GoPro chapter files).
    """
    cmd = [
        ffprobe_exe, "-v", "error",
        "-show_entries", "format_tags=creation_time",
        "-of", "json", str(path),
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return None
    if p.returncode != 0:
        return None
    try:
        data = json.loads(p.stdout or "{}")
        ct = data.get("format", {}).get("tags", {}).get("creation_time")
    except (json.JSONDecodeError, ValueError):
        return None
    return _parse_creation_time(ct)


def build_timeline_from_paths(
    paths: list[Path | str],
    ffmpeg_exe: str = "ffmpeg",
    ffprobe_exe: str = "ffprobe",
    base_dt: Optional[datetime] = None,
    default_fps: float = 30.0,
    absolute_start_fn: Optional[Callable[[Path], Optional[datetime]]] = None,
    use_cache: bool = True,
) -> VideoTimeline:
    """Probe every clip and build a ``VideoTimeline``.

    Args:
        paths: ordered list of video files (order is preserved, never sorted).
        ffmpeg_exe: ffmpeg binary path (used to extract each clip's GPMF).
        ffprobe_exe: ffprobe binary path.
        base_dt: project absolute start (telemetry.start_dt_utc). Used only as
            fallback when clip 0 has no reliable source-local timestamp.
        default_fps: fallback FPS when probing fails.
        absolute_start_fn: optional per-clip absolute-start override (used by
            tests / callers that already know the start).
        use_cache: use the in-memory + disk per-clip timestamp cache.
    """
    clips: list[VideoClip] = []
    for idx, p in enumerate(paths):
        path = Path(p)
        info = probe_video_info(ffprobe_exe, path, default_fps=default_fps)
        if absolute_start_fn is not None:
            try:
                start = _as_naive_utc(absolute_start_fn(path))
            except Exception:
                start = None
            res = ClipTimestampResolution(
                absolute_start_dt=start,
                timestamp_source="custom_resolver" if start is not None else TIMESTAMP_SOURCE_UNKNOWN,
                timestamp_reliable=start is not None,
                timestamp_detail="absolute_start_fn override",
                timestamp_quality=(
                    TIMESTAMP_QUALITY_ESTIMATED if start is not None
                    else TIMESTAMP_QUALITY_FALLBACK
                ),
            )
        else:
            res = resolve_clip_timestamp(
                path, ffmpeg_exe=ffmpeg_exe, ffprobe_exe=ffprobe_exe,
                use_cache=use_cache, duration_s=info["duration_s"],
            )
        clips.append(
            VideoClip(
                path=path,
                duration_s=info["duration_s"],
                frame_count=info.get("frame_count", 0),
                source_duration_s=info["duration_s"],
                fps=info["fps"],
                width=info["width"],
                height=info["height"],
                absolute_start_dt=res.absolute_start_dt,
                timestamp_source=res.timestamp_source,
                timestamp_reliable=res.timestamp_reliable,
                timestamp_detail=res.timestamp_detail,
                timestamp_quality=res.timestamp_quality,
            )
        )
    return VideoTimeline(clips, base_dt=base_dt)


def timeline_absolute_ranges(
    timeline: "VideoTimeline",
) -> list[tuple[datetime, datetime]]:
    """Return ``[(absolute_start, absolute_end), ...]`` per clip.

    Only clips with BOTH absolute bounds are included (a clip without a
    reliable absolute start cannot contribute a range).  Used by the render
    pipeline / charts instead of assuming the telemetry fits in
    ``[start_dt_utc, start_dt_utc + project_duration]``.
    """
    out: list[tuple[datetime, datetime]] = []
    for clip in timeline.clips:
        if clip.absolute_start_dt is not None and clip.absolute_end_dt is not None:
            out.append((clip.absolute_start_dt, clip.absolute_end_dt))
    return out


def timeline_absolute_end(timeline: "VideoTimeline") -> Optional[datetime]:
    """Return the latest absolute END across all clips (or None)."""
    ranges = timeline_absolute_ranges(timeline)
    if not ranges:
        return None
    return max(end for _, end in ranges)


def resolve_render_target_dt(
    timeline: Optional["VideoTimeline"],
    start_dt_utc: Optional[datetime],
    global_time: float,
    t0: Optional[datetime] = None,
) -> Optional[datetime]:
    """Map a frame's GLOBAL time to the ABSOLUTE target datetime for rendering.

    Single shared contract used by preview and the final renderer:
        global_time -> VideoTimeline.global_to_absolute -> absolute target_dt

    Falls back to the legacy ``start_dt_utc + global_time`` when no timeline
    exists (single-file / old projects).  ``t0`` is an alternative base for the
    legacy fallback when ``start_dt_utc`` is None.
    """
    if timeline is not None and getattr(timeline, "clip_count", 0):
        dt = timeline.global_to_absolute(global_time, base_dt=start_dt_utc)
        if dt is not None:
            return dt
    base = start_dt_utc or t0
    if base is not None:
        return base + timedelta(seconds=global_time)
    return None


def format_timeline_diagnostics(timeline: "VideoTimeline") -> list[str]:
    """Return human-readable per-clip + gap diagnostics for a timeline.

    Used by the project loader for the ``[MultiFile]`` log.  Gap information is
    purely diagnostic: the absolute gap between clips is *removed* from the
    final global axis (never filled with empty frames).
    """
    lines: list[str] = []
    if not timeline.clips:
        return lines
    lines.append(
        f"[MultiFile] Timeline: {timeline.clip_count} clips, "
        f"project_duration={timeline.project_duration_s:.1f}s"
    )
    for i, clip in enumerate(timeline.clips, start=1):
        start_txt = (
            _fmt_iso(clip.absolute_start_dt) if clip.absolute_start_dt else "N/A"
        )
        end_txt = (
            _fmt_iso(clip.absolute_end_dt) if clip.absolute_end_dt else "N/A"
        )
        lines.append(f"[MultiFile] Clip {i}/{timeline.clip_count}")
        lines.append(f"  path={clip.path.name}")
        lines.append(
            f"  global={clip.global_start_s:.3f}-{clip.global_end_s:.3f}"
        )
        lines.append(f"  absolute={start_txt}-{end_txt}")
        lines.append(
            f"  source={clip.timestamp_source} reliable={clip.timestamp_reliable} "
            f"quality={clip.timestamp_quality}"
        )
        if clip.timestamp_detail:
            lines.append(f"  detail={clip.timestamp_detail}")
    # Absolute gaps between consecutive clips (diagnostic only).
    for i in range(len(timeline.clips) - 1):
        c0 = timeline.clips[i]
        c1 = timeline.clips[i + 1]
        if c0.absolute_end_dt is None or c1.absolute_start_dt is None:
            continue
        gap_s = (c1.absolute_start_dt - c0.absolute_end_dt).total_seconds()
        if gap_s > 1.0:
            mins, secs = divmod(int(gap_s), 60)
            lines.append(
                f"[MultiFile] GAP removed from final timeline: "
                f"{mins}m{secs:02d}s between clip {i + 1} and clip {i + 2}"
            )
    return lines
