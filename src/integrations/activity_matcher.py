"""Activity matching algorithm for correlating video intervals with remote activities."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from src.integrations.activity_provider import ActivityCandidate

AUTO_MATCH_THRESHOLD = 0.90
SELECTION_THRESHOLD = 0.60


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points in kilometers."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def score_candidate(
    candidate: ActivityCandidate,
    project_start_utc: datetime,
    project_end_utc: datetime,
    video_gps_point: Optional[tuple[float, float]] = None,
) -> float:
    """Compute matching score [0.0 .. 1.0] for a candidate activity.

    Evaluates:
    1. TIME_OVERLAP: ratio of video covered by activity
    2. START_TIME_DELTA: difference between video start and activity start
    3. DURATION_DELTA: similarity of total duration
    4. GPS_DISTANCE (optional): proximity of activity start to video GPS location
    """
    v_start = _ensure_utc(project_start_utc)
    v_end = _ensure_utc(project_end_utc)
    v_dur = max(1.0, (v_end - v_start).total_seconds())

    a_start = _ensure_utc(candidate.start_dt)
    a_end = _ensure_utc(candidate.end_dt)
    a_dur = max(1.0, candidate.duration_s)

    # 1. TIME OVERLAP
    overlap_start = max(a_start, v_start)
    overlap_end = min(a_end, v_end)
    overlap_s = max(0.0, (overlap_end - overlap_start).total_seconds())
    overlap_score = min(1.0, overlap_s / v_dur)

    # 2. START TIME DELTA (linear decay over 3600 seconds)
    delta_s = abs((a_start - v_start).total_seconds())
    start_score = max(0.0, 1.0 - (delta_s / 3600.0))

    # 3. DURATION DELTA
    dur_score = min(a_dur, v_dur) / max(a_dur, v_dur)

    # 4. GPS PROXIMITY
    has_gps = (
        video_gps_point is not None
        and candidate.start_lat is not None
        and candidate.start_lon is not None
    )

    if has_gps:
        v_lat, v_lon = video_gps_point  # type: ignore[misc]
        dist_km = haversine_km(v_lat, v_lon, candidate.start_lat, candidate.start_lon)  # type: ignore[arg-type]
        gps_score = max(0.0, 1.0 - (dist_km / 10.0))  # 1.0 at 0km, 0.0 at >= 10km
        total_score = (
            0.45 * overlap_score
            + 0.25 * start_score
            + 0.15 * dur_score
            + 0.15 * gps_score
        )
    else:
        total_score = (
            0.55 * overlap_score
            + 0.30 * start_score
            + 0.15 * dur_score
        )

    return max(0.0, min(1.0, float(total_score)))


def rank_and_evaluate_candidates(
    candidates: list[ActivityCandidate],
    project_start_utc: datetime,
    project_end_utc: datetime,
    video_gps_point: Optional[tuple[float, float]] = None,
) -> tuple[str, list[tuple[ActivityCandidate, float]]]:
    """Rank candidates and return (decision, ranked_pairs).

    Decision is one of:
    - 'AUTO_ACCEPT': Single clear match >= 0.90
    - 'NEEDS_SELECTION': Candidates available with score >= 0.60
    - 'NO_MATCH': No candidates with score >= 0.60
    """
    if not candidates:
        return "NO_MATCH", []

    scored: list[tuple[ActivityCandidate, float]] = []
    for cand in candidates:
        sc = score_candidate(
            cand,
            project_start_utc,
            project_end_utc,
            video_gps_point=video_gps_point,
        )
        scored.append((cand, sc))

    # Sort descending by score
    scored.sort(key=lambda x: x[1], reverse=True)
    best_cand, best_score = scored[0]

    if best_score >= AUTO_MATCH_THRESHOLD:
        if len(scored) == 1:
            return "AUTO_ACCEPT", scored
        second_score = scored[1][1]
        if (best_score - second_score) >= 0.10:
            return "AUTO_ACCEPT", scored
        # Multiple candidates very close to each other
        return "NEEDS_SELECTION", scored

    if best_score >= SELECTION_THRESHOLD:
        return "NEEDS_SELECTION", scored

    return "NO_MATCH", scored
