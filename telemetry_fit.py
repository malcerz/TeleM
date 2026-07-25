#!/usr/bin/env python3
"""FIT (Garmin) file handling for TeleM – parsing and video timeline synchronisation.

Reads all numeric fields from FIT 'record' messages dynamically instead of
using hardcoded field names.  Every discovered scalar field becomes a sample
stream that the overlay can display.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fitparse
except ImportError:
    fitparse = None  # type: ignore[assignment]


# Semicircles → degrees conversion
_SEMICIRC_DEG: float = 180.0 / 2 ** 31

# Fields that are NOT telemetry data — skipped when building per-field samples.
_EXCLUDED_FIELDS: set[str] = {
    "timestamp",
    "position_lat",
    "position_long",
    "unknown_107",
    "unknown_108",
    "unknown_114",
    "unknown_115",
    "unknown_137",
    "unknown_138",
    "unknown_144",
}

RecordDict = dict[str, Any]
Sample = tuple[datetime, float]


def parse_fit(fit_path: Path | str) -> list[RecordDict] | None:
    """Parse a FIT file and return a list of record dicts.

    Each dict contains:
      - ``timestamp`` (datetime UTC, naive)
      - ``lat`` / ``lon`` (decimal degrees, or None)
      - ``alt`` (metres, from enhanced_altitude)
      - ``speed`` (km/h, converted from m/s)
      - Every other discovered scalar field with its original FIT name.

    Returns ``None`` on failure.
    """
    if fitparse is None:
        print("[FIT] fitparse library not available. Install: pip install fitparse", flush=True)
        return None

    try:
        fitfile = fitparse.FitFile(str(fit_path))
    except Exception as exc:
        print(f"[FIT] Error opening file: {exc}", flush=True)
        return None

    records: list[RecordDict] = []
    for msg in fitfile.get_messages("record"):
        raw: dict[str, Any] = {}
        for field in msg:
            raw[field.name] = field.value

        timestamp = raw.get("timestamp")
        if timestamp is None:
            continue

        if isinstance(timestamp, datetime):
            dt = (
                timestamp.replace(tzinfo=timezone.utc)
                if timestamp.tzinfo is None
                else timestamp.astimezone(timezone.utc)
            )
        else:
            dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)

        rec: RecordDict = {"timestamp": dt.replace(tzinfo=None)}

        # GPS semicircles → degrees
        lat = raw.get("position_lat")
        lon = raw.get("position_long")
        rec["lat"] = lat * _SEMICIRC_DEG if lat is not None else None
        rec["lon"] = lon * _SEMICIRC_DEG if lon is not None else None
        if rec["lat"] is not None and rec["lon"] is not None:
            if not (-90 <= rec["lat"] <= 90 and -180 <= rec["lon"] <= 180):
                rec["lat"] = rec["lon"] = None

        # Altitude
        alt = raw.get("enhanced_altitude") or raw.get("altitude")
        rec["alt"] = _try_float(alt)

        # Speed: m/s → km/h
        speed_ms = raw.get("enhanced_speed") or raw.get("speed")
        rec["speed"] = _try_float(speed_ms, scale=3.6)

        # Every other scalar field
        for name, value in raw.items():
            if name in _EXCLUDED_FIELDS:
                continue
            if name in (
                "timestamp", "position_lat", "position_long",
                "altitude", "speed",
            ):
                continue
            if isinstance(value, (list, tuple)):
                continue
            numeric = _try_float(value)
            if numeric is not None:
                rec[name] = numeric

        records.append(rec)

    if not records:
        print("[FIT] No 'record' messages found in FIT file.", flush=True)
        return None

    records.sort(key=lambda r: r["timestamp"])

    # Deduplicate by timestamp
    deduped: list[RecordDict] = []
    for rec in records:
        if not deduped or rec["timestamp"] != deduped[-1]["timestamp"]:
            deduped.append(rec)
        else:
            merged = dict(deduped[-1])
            for k, v in rec.items():
                if v is not None:
                    merged[k] = v
            deduped[-1] = merged

    print(f"[FIT] Loaded {len(deduped)} points from {Path(fit_path).name}", flush=True)

    discovered: set[str] = set()
    for rec in deduped:
        for k, v in rec.items():
            if k != "timestamp" and v is not None:
                discovered.add(k)
    if discovered:
        print(f"[FIT] Fields discovered: {sorted(discovered)}", flush=True)

    return deduped


def sync_fit_to_video(
    records: list[RecordDict],
    video_start_dt: datetime | None,
) -> dict[str, list[Sample]]:
    """Synchronise FIT records to the video timeline.

    Every numeric field becomes a key in the returned dict:
      - ``speed`` – km/h (with GPS-fallback computation)
      - ``track`` – cumulative distance in metres
      - ``alt``   – altitude in metres
      - All other discovered fields keep their original FIT name.

    Returns:
        Dict mapping field-name to list of (datetime, value) pairs.
    """
    if not records:
        return {}

    if video_start_dt is None:
        video_start_dt = records[0]["timestamp"]
    if video_start_dt.tzinfo is not None:
        video_start_dt = video_start_dt.replace(tzinfo=None)

    pts: list[RecordDict] = []
    for rec in records:
        r = dict(rec)
        t = r["timestamp"]
        if t.tzinfo is not None:
            r["timestamp"] = t.replace(tzinfo=None)
        pts.append(r)

    result: dict[str, list[Sample]] = {}

    # --- speed ---
    speed_samples = [
        (r["timestamp"], r["speed"]) for r in pts if r.get("speed") is not None
    ]
    if not speed_samples:
        for i in range(1, len(pts)):
            t1, lat1, lon1 = pts[i - 1]["timestamp"], pts[i - 1].get("lat"), pts[i - 1].get("lon")
            t2, lat2, lon2 = pts[i]["timestamp"], pts[i].get("lat"), pts[i].get("lon")
            if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
                continue
            dt_delta = (t2 - t1).total_seconds()
            if dt_delta <= 0:
                continue
            dist_m = _haversine(lat1, lon1, lat2, lon2)
            speed_samples.append((t2, dist_m / dt_delta * 3.6))
    if speed_samples:
        result["speed"] = speed_samples

    # --- track (cumulative distance) ---
    track: list[Sample] = []
    total_m = 0.0
    for i, rec in enumerate(pts):
        lat, lon = rec.get("lat"), rec.get("lon")
        if lat is None or lon is None:
            if track:
                track.append((rec["timestamp"], total_m))
            continue
        if i > 0:
            pl, po = pts[i - 1].get("lat"), pts[i - 1].get("lon")
            if pl is not None and po is not None:
                total_m += _haversine(pl, po, lat, lon)
        track.append((rec["timestamp"], total_m))
    if track:
        result["track"] = track

    # --- altitude ---
    alt = [(r["timestamp"], r["alt"]) for r in pts if r.get("alt") is not None]
    if alt:
        result["alt"] = alt

    # --- all other numeric fields ---
    field_keys: set[str] = set()
    for rec in pts:
        for k in rec:
            if k not in ("timestamp", "lat", "lon", "alt", "speed"):
                field_keys.add(k)

    for key in sorted(field_keys):
        samples = [(r["timestamp"], r[key]) for r in pts if r.get(key) is not None]
        if samples:
            result[key] = samples

    # Aliases are resolved at lookup time by resolve_source_value(),
    # not by duplicating keys here – otherwise _register_fit_fields()
    # creates duplicate fit_*_text indicators for the same data.
    print(
        f"[FIT] Synchro: {len(result)} field(s) – { {k: len(v) for k, v in result.items()} }",
        flush=True,
    )

    return result


# ── Helpers ─────────────────────────────────────────────────────────────────


def _try_float(value: Any, scale: float = 1.0) -> float | None:
    """Safely convert a value to float, optionally scaling it."""
    if value is None:
        return None
    try:
        return float(value) * scale
    except (ValueError, TypeError):
        return None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two GPS coordinates."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_fit_for_video(video_path: Path | str) -> Path | None:
    """Look for a .fit file with the same base name as the video."""
    video_path = Path(video_path)
    stem = video_path.stem
    candidates = [
        video_path.with_suffix(".fit"),
        video_path.with_suffix(".FIT"),
        video_path.parent / (stem.lower() + ".fit"),
        video_path.parent / (stem.upper() + ".FIT"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    fits = sorted(video_path.parent.glob("*.fit")) + sorted(video_path.parent.glob("*.FIT"))
    if fits:
        print(f"[FIT] No matching FIT found, using: {fits[0]}", flush=True)
        return fits[0]
    return None


def process_fit(
    video_path: Path | str,
    video_start_dt: datetime | None = None,
) -> dict[str, list[Sample]] | None:
    """Convenience: find FIT file, parse and synchronise in one call."""
    fit_path = find_fit_for_video(video_path)
    if fit_path is None:
        return None
    records = parse_fit(fit_path)
    if records is None:
        return None
    return sync_fit_to_video(records, video_start_dt)
