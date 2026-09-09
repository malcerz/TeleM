"""Unified FIT activity clock and active-time mapper (CEL 3 & CEL 4).

Provides a single shared model for:
- Mapping wall-clock UTC datetime <-> cumulative active timer seconds.
- Determining if a given instant is inside a pause.
- Collapsing pauses from chart X-axes (charts_skip_pauses).
- Computing dynamic average speed (active_distance / active_time).

Built once per FIT file from FIT timer events (`event=timer`, `event_type=start` vs `stop`/`stop_all`)
or fallback from session/records.
"""

from __future__ import annotations

import bisect
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class ActiveTimeMapper:
    """Immutable model of active intervals and pauses for a single activity.

    Attributes:
        active_intervals: list of (start_dt, end_dt) in chronological order.
        pause_intervals: list of (pause_start_dt, pause_end_dt).
        start_dt: activity start datetime (naive UTC).
        end_dt: activity end datetime (naive UTC).
        total_active_seconds: total active timer time in seconds.
        total_elapsed_seconds: total wall-clock elapsed time from start to end.
    """

    __slots__ = (
        "active_intervals",
        "pause_intervals",
        "start_dt",
        "end_dt",
        "total_active_seconds",
        "total_elapsed_seconds",
        "_active_starts",
        "_active_ends",
        "_cum_active_at_interval_start",
        "_cum_active_at_interval_end",
    )

    def __init__(
        self,
        active_intervals: Sequence[tuple[datetime, datetime]],
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
    ) -> None:
        cleaned_intervals: list[tuple[datetime, datetime]] = []
        for s, e in active_intervals:
            s_clean = _to_naive_utc(s)
            e_clean = _to_naive_utc(e)
            if e_clean > s_clean:
                cleaned_intervals.append((s_clean, e_clean))

        cleaned_intervals.sort(key=lambda x: x[0])
        # Merge overlapping/contiguous intervals if any
        merged: list[tuple[datetime, datetime]] = []
        for s, e in cleaned_intervals:
            if not merged:
                merged.append((s, e))
            else:
                prev_s, prev_e = merged[-1]
                if s <= prev_e:
                    merged[-1] = (prev_s, max(prev_e, e))
                else:
                    merged.append((s, e))

        self.active_intervals = merged

        # Derive pause intervals
        pauses: list[tuple[datetime, datetime]] = []
        for i in range(len(self.active_intervals) - 1):
            p_start = self.active_intervals[i][1]
            p_end = self.active_intervals[i + 1][0]
            if p_end > p_start:
                pauses.append((p_start, p_end))
        self.pause_intervals = pauses

        if self.active_intervals:
            self.start_dt = self.active_intervals[0][0] if start_dt is None else _to_naive_utc(start_dt)
            self.end_dt = self.active_intervals[-1][1] if end_dt is None else _to_naive_utc(end_dt)
        else:
            self.start_dt = _to_naive_utc(start_dt) if start_dt is not None else None
            self.end_dt = _to_naive_utc(end_dt) if end_dt is not None else None

        self._active_starts = [inv[0] for inv in self.active_intervals]
        self._active_ends = [inv[1] for inv in self.active_intervals]

        # Precompute cumulative active time at interval boundaries
        cum_starts: list[float] = []
        cum_ends: list[float] = []
        running = 0.0
        for s, e in self.active_intervals:
            cum_starts.append(running)
            dur = (e - s).total_seconds()
            running += dur
            cum_ends.append(running)

        self._cum_active_at_interval_start = cum_starts
        self._cum_active_at_interval_end = cum_ends
        self.total_active_seconds = running

        if self.start_dt is not None and self.end_dt is not None and self.end_dt >= self.start_dt:
            self.total_elapsed_seconds = (self.end_dt - self.start_dt).total_seconds()
        else:
            self.total_elapsed_seconds = self.total_active_seconds

    def is_paused(self, dt: datetime) -> bool:
        """Return True if ``dt`` falls strictly inside a pause interval."""
        if not self.active_intervals:
            return False
        dt_clean = _to_naive_utc(dt)
        # Check against pauses
        for p_start, p_end in self.pause_intervals:
            if p_start <= dt_clean < p_end:
                return True
        return False

    def wall_to_active_seconds(self, dt: datetime) -> float:
        """Convert a wall UTC datetime to cumulative active timer seconds from activity start."""
        if not self.active_intervals or self.start_dt is None:
            return 0.0
        dt_clean = _to_naive_utc(dt)
        if dt_clean <= self.start_dt:
            return 0.0

        # Bisect in _active_starts: find rightmost interval where start <= dt_clean
        idx = bisect.bisect_right(self._active_starts, dt_clean) - 1
        if idx < 0:
            return 0.0

        inv_start = self._active_starts[idx]
        inv_end = self._active_ends[idx]
        cum_start = self._cum_active_at_interval_start[idx]

        if dt_clean <= inv_end:
            # Inside active interval idx
            return cum_start + (dt_clean - inv_start).total_seconds()
        else:
            # In a pause after interval idx (or after end of all intervals)
            return self._cum_active_at_interval_end[idx]

    def cumulative_active_time(self, dt: datetime) -> float:
        """Alias for wall_to_active_seconds."""
        return self.wall_to_active_seconds(dt)

    def active_to_wall_dt(self, active_s: float) -> Optional[datetime]:
        """Convert cumulative active timer seconds back to a wall UTC datetime."""
        if not self.active_intervals or self.start_dt is None:
            return None
        if active_s <= 0.0:
            return self.start_dt
        if active_s >= self.total_active_seconds:
            return self.end_dt

        idx = bisect.bisect_right(self._cum_active_at_interval_end, active_s)
        if idx >= len(self.active_intervals):
            return self.end_dt

        inv_start = self._active_starts[idx]
        cum_start = self._cum_active_at_interval_start[idx]
        rem_s = active_s - cum_start
        return inv_start + timedelta(seconds=rem_s)


def build_active_time_mapper_from_events(
    events: Sequence[dict[str, Any]],
    records: Optional[Sequence[dict[str, Any]]] = None,
    session: Optional[dict[str, Any]] = None,
) -> ActiveTimeMapper:
    """Build an ActiveTimeMapper from parsed FIT events, records, and session data.

    Events of interest:
      event == 'timer'
      event_type in ('start', 'stop', 'stop_all')
    """
    timer_events: list[tuple[datetime, str]] = []
    for ev in events:
        if ev.get("event") == "timer":
            ev_type = str(ev.get("event_type", "")).strip().lower()
            ts = ev.get("timestamp")
            if ts and isinstance(ts, datetime):
                timer_events.append((_to_naive_utc(ts), ev_type))

    timer_events.sort(key=lambda x: x[0])

    intervals: list[tuple[datetime, datetime]] = []
    current_start: Optional[datetime] = None

    for ts, ev_type in timer_events:
        if ev_type == "start":
            if current_start is None:
                current_start = ts
        elif ev_type in ("stop", "stop_all"):
            if current_start is not None:
                if ts > current_start:
                    intervals.append((current_start, ts))
                current_start = None

    # If the activity ended while still running (or missing final stop event)
    if current_start is not None:
        last_dt = None
        if records:
            last_rec_ts = records[-1].get("timestamp")
            if isinstance(last_rec_ts, datetime):
                last_dt = _to_naive_utc(last_rec_ts)
        if last_dt and last_dt > current_start:
            intervals.append((current_start, last_dt))
        elif session and session.get("start_time") and session.get("total_elapsed_time"):
            st = _to_naive_utc(session["start_time"])
            calc_end = st + timedelta(seconds=float(session["total_elapsed_time"]))
            if calc_end > current_start:
                intervals.append((current_start, calc_end))

    # If no timer events found, fallback to full span from records or session
    if not intervals:
        start_dt = None
        end_dt = None
        if session and session.get("start_time"):
            start_dt = _to_naive_utc(session["start_time"])
            if session.get("total_elapsed_time"):
                end_dt = start_dt + timedelta(seconds=float(session["total_elapsed_time"]))
        if start_dt is None and records:
            r0 = records[0].get("timestamp")
            r1 = records[-1].get("timestamp")
            if isinstance(r0, datetime) and isinstance(r1, datetime):
                start_dt = _to_naive_utc(r0)
                end_dt = _to_naive_utc(r1)
        if start_dt and end_dt and end_dt > start_dt:
            intervals.append((start_dt, end_dt))

    sess_start = _to_naive_utc(session["start_time"]) if (session and session.get("start_time")) else None
    sess_end = None
    if sess_start and session and session.get("total_elapsed_time"):
        sess_end = sess_start + timedelta(seconds=float(session["total_elapsed_time"]))

    return ActiveTimeMapper(intervals, start_dt=sess_start, end_dt=sess_end)


def _is_valid_distance_stream(samples: Any) -> bool:
    if not samples or not isinstance(samples, (list, tuple)) or len(samples) == 0:
        return False
    first = samples[0]
    if not isinstance(first, (list, tuple)) or len(first) != 2:
        return False
    if isinstance(first[1], (tuple, list, dict)):
        return False
    try:
        float(first[1])
        return True
    except (TypeError, ValueError):
        return False


def compute_activity_distance_and_avg_speed(
    fit_data: Any,
    gpx_track_samples: Optional[list],
    gpmf_track_samples: Optional[list],
    target_dt: Optional[datetime],
    active_elapsed_s: float,
    fallback_distance_m: Optional[float] = None,
) -> tuple[Optional[float], float]:
    """Canonical activity distance and average speed calculator.

    Decouples average speed calculation from display distance widgets.
    When FIT data exists and contains recorded distance (or track), activity distance
    is computed exclusively from FIT samples relative to activity start.
    Returns (activity_distance_m, avg_speed_kmh).
    """
    from src.telemetry_extract import interpolate_distance

    activity_distance_m: Optional[float] = None

    if fit_data and target_dt is not None:
        fit_dist = (
            fit_data.get("distance")
            if isinstance(fit_data, dict)
            else getattr(fit_data, "distance", None)
        )
        if not _is_valid_distance_stream(fit_dist):
            fit_dist = (
                fit_data.get("track")
                if isinstance(fit_data, dict)
                else getattr(fit_data, "track", None)
            )
        if _is_valid_distance_stream(fit_dist):
            d_raw = interpolate_distance(fit_dist, target_dt)
            d_start = fit_dist[0][1] if fit_dist and len(fit_dist) > 0 else 0.0
            if d_raw is not None:
                activity_distance_m = max(0.0, float(d_raw) - float(d_start))

    if activity_distance_m is None and _is_valid_distance_stream(gpx_track_samples) and target_dt is not None:
        d_gpx = interpolate_distance(gpx_track_samples, target_dt)
        if d_gpx is not None:
            d_start_gpx = gpx_track_samples[0][1] if len(gpx_track_samples) > 0 else 0.0
            activity_distance_m = max(0.0, float(d_gpx) - float(d_start_gpx))

    if activity_distance_m is None:
        activity_distance_m = fallback_distance_m

    avg_speed_kmh = 0.0
    if active_elapsed_s > 0 and activity_distance_m is not None and activity_distance_m > 0:
        avg_speed_kmh = (activity_distance_m / active_elapsed_s) * 3.6

    return activity_distance_m, avg_speed_kmh

