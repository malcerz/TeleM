#!/usr/bin/env python3
"""GPX file handling for TeleM – parsing and video timeline synchronisation."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_GPX_EXT_NS: dict[str, str] = {
    'gpxtpx': 'http://www.garmin.com/xmlschemas/TrackPointExtension/v1',
    'gpxx':   'http://www.garmin.com/xmlschemas/GpxExtensions/v3',
    'power':  'http://www.garmin.com/xmlschemas/PowerExtension/v1',
}

# (datetime, lat, lon, ele, extensions)
GpxPoint = tuple[datetime, float, float, float, dict[str, float]]
# (datetime, value)  – generic sample pair
Sample = tuple[datetime, float]


def _parse_extensions(ext_el: Optional[ET.Element]) -> dict[str, float]:
    """Parse the <extensions> element and return a dict with keys:
    power, atemp, hr, cad (or empty dict if absent)."""
    ext: dict[str, float] = {}
    if ext_el is None:
        return ext

    # Match by local tag name (ignores namespace)
    for child in ext_el.iter():
        local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        text = child.text.strip() if child.text else ''
        if local == 'power' and text:
            try:
                ext['power'] = float(text)
            except ValueError:
                pass
        elif local == 'atemp' and text:
            try:
                ext['atemp'] = float(text)
            except ValueError:
                pass
        elif local == 'hr' and text:
            try:
                ext['hr'] = float(text)
            except ValueError:
                pass
        elif local == 'cad' and text:
            try:
                ext['cad'] = float(text)
            except ValueError:
                pass
    return ext


def parse_gpx(gpx_path: Path | str) -> Optional[list[GpxPoint]]:
    """Parse a GPX file and return a list of (datetime, lat, lon, ele, extensions) tuples.

    The extensions dict may contain keys: power, atemp, hr, cad.
    Returns None on failure.
    """
    try:
        tree = ET.parse(gpx_path)
        root = tree.getroot()
    except Exception as exc:
        print(f"[GPX] XML parse error: {exc}", flush=True)
        return None

    ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}

    points: list[GpxPoint] = []
    for trkpt in root.iter('{http://www.topografix.com/GPX/1/1}trkpt'):
        lat = float(trkpt.attrib['lat'])
        lon = float(trkpt.attrib['lon'])

        # Elevation (optional)
        ele_el = trkpt.find('gpx:ele', ns)
        ele = float(ele_el.text) if ele_el is not None and ele_el.text else 0.0

        # Time (required)
        time_el = trkpt.find('gpx:time', ns)
        if time_el is None or not time_el.text:
            continue

        try:
            dt = datetime.strptime(time_el.text.strip(), "%Y-%m-%dT%H:%M:%SZ")
            dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            try:
                dt = datetime.strptime(time_el.text.strip(), "%Y-%m-%dT%H:%M:%S.%fZ")
                dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

        # Filter invalid coordinates
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        # Parse extensions (power, atemp, hr, cad)
        ext_el = trkpt.find('gpx:extensions', ns)
        ext = _parse_extensions(ext_el)

        points.append((dt, lat, lon, ele, ext))

    if not points:
        print("[GPX] No timed points found in GPX file.", flush=True)
        return None

    # Sort by time
    points.sort(key=lambda x: x[0])

    # Deduplicate by timestamp
    deduped: list[GpxPoint] = []
    for pt in points:
        if not deduped or pt[0] != deduped[-1][0]:
            deduped.append(pt)
        else:
            # Merge extensions on duplicate
            _, _, _, _, ext_new = pt
            _, _, _, _, ext_old = deduped[-1]
            merged = {**ext_old, **ext_new}
            deduped[-1] = (pt[0], pt[1], pt[2], pt[3], merged)

    print(f"[GPX] Loaded {len(deduped)} points from {gpx_path.name}", flush=True)
    found: set[str] = set()
    for _, _, _, _, ext in deduped:
        found.update(ext.keys())
    if found:
        print(f"[GPX] Extensions found: {sorted(found)}", flush=True)
    return deduped


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two GPS coordinates using the haversine formula."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def sync_gpx_to_video(
    points: list[GpxPoint],
    video_start_dt: Optional[datetime],
) -> tuple[
    Optional[list[Sample]], Optional[list[Sample]], Optional[list[Sample]],
    Optional[list[Sample]], Optional[list[Sample]], Optional[list[Sample]], Optional[list[Sample]],
]:
    """Synchronise GPX track points to the video timeline.

    Args:
        points: List of (datetime, lat, lon, ele, extensions) – absolute UTC timestamps.
        video_start_dt: UTC datetime of the video start (T=0).

    Returns:
        A 7-tuple of lists: (speed_samples, track_samples, alt_samples,
        power_samples, atemp_samples, hr_samples, cad_samples).
        Each sample is a (datetime, value) pair.
        Returns (None, ...) when there is no data.
    """
    if not points:
        return None, None, None, None, None, None, None

    if video_start_dt is None:
        video_start_dt = points[0][0]

    # Normalise timezone – work with naive UTC throughout
    if video_start_dt.tzinfo is not None:
        video_start_dt = video_start_dt.replace(tzinfo=None)
    pts_clean: list[tuple[datetime, float, float, float, dict[str, float]]] = [
        (dt.replace(tzinfo=None), lat, lon, ele, ext) for dt, lat, lon, ele, ext in points
    ]

    # --- Speed samples ---
    speed_samples: list[Sample] = []
    for i in range(1, len(pts_clean)):
        dt1, lat1, lon1, _, _ = pts_clean[i - 1]
        dt2, lat2, lon2, _, _ = pts_clean[i]
        dt_delta = (dt2 - dt1).total_seconds()
        if dt_delta <= 0:
            continue
        dist_m = haversine_m(lat1, lon1, lat2, lon2)
        speed_ms = dist_m / dt_delta
        speed_kmh = speed_ms * 3.6
        speed_samples.append((dt2, speed_kmh))

    # --- Distance samples (cumulative) ---
    track_samples: list[Sample] = []
    total_m = 0.0
    for i, (dt, lat, lon, _, _) in enumerate(pts_clean):
        if i > 0:
            _, prev_lat, prev_lon, _, _ = pts_clean[i - 1]
            total_m += haversine_m(prev_lat, prev_lon, lat, lon)
        track_samples.append((dt, total_m))

    # --- Altitude samples ---
    alt_samples: list[Sample] = [(dt, ele) for dt, _, _, ele, _ in pts_clean]

    # --- Extensions: power, atemp, hr, cad ---
    power_samples: list[Sample] = []
    atemp_samples: list[Sample] = []
    hr_samples: list[Sample] = []
    cad_samples: list[Sample] = []
    for dt, _, _, _, ext in pts_clean:
        if 'power' in ext:
            power_samples.append((dt, ext['power']))
        if 'atemp' in ext:
            atemp_samples.append((dt, ext['atemp']))
        if 'hr' in ext:
            hr_samples.append((dt, ext['hr']))
        if 'cad' in ext:
            cad_samples.append((dt, ext['cad']))

    print(f"[GPX] Synchro: speed={len(speed_samples)}, track={len(track_samples)}, alt={len(alt_samples)}, "
          f"power={len(power_samples)}, atemp={len(atemp_samples)}, hr={len(hr_samples)}, cad={len(cad_samples)}",
          flush=True)
    return speed_samples, track_samples, alt_samples, power_samples, atemp_samples, hr_samples, cad_samples


def find_gpx_for_video(video_path: Path | str) -> Optional[Path]:
    """Look for a .gpx file with the same base name as the video in the same directory.

    Args:
        video_path: Path to the video file.

    Returns:
        Path to the .gpx file or None.
    """
    video_path = Path(video_path)
    candidates = [
        video_path.with_suffix('.gpx'),
        video_path.with_suffix('.GPX'),
        video_path.parent / f"{video_path.stem}.gpx",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def process_gpx(
    video_path: Path | str,
    video_start_dt: Optional[datetime] = None,
) -> Optional[tuple[
    Optional[list[Sample]], Optional[list[Sample]], Optional[list[Sample]],
    Optional[list[Sample]], Optional[list[Sample]], Optional[list[Sample]], Optional[list[Sample]],
]]:
    """Load the GPX file for a given video and synchronise it to the video timeline.

    Args:
        video_path: Path to the video file.
        video_start_dt: UTC datetime of the video start (optional).

    Returns:
        A 7-tuple matching sync_gpx_to_video(), or None.
    """
    gpx_path = find_gpx_for_video(video_path)
    if gpx_path is None:
        return None

    points = parse_gpx(gpx_path)
    if points is None:
        return None

    return sync_gpx_to_video(points, video_start_dt)
