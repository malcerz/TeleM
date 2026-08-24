"""GoPro IMU -> roll/lean angle (ETAP 13).

Audit facts (measured from real ``Video/GX010115.json``):
- ACCL stream: **m/s^2** (gravity ~9.8, dominant on X for the test mount).
- GYRO stream: **rad/s** (angular VELOCITY — *not* an angle).
- Timestamps: real STMP/TSMP grid (irregularities preserved; no fixed-FPS guess).
- No GRAV / CORI / IORI / quaternion / ready orientation stream in this data,
  so there is no ready-made GoPro roll angle -> roll is DERIVED here.

The derived roll timeline is PRECOMPUTED once per material
(``timestamp -> roll_deg``) with a complementary filter (gyro integration
+ accelerometer gravity vector).  Because the whole timeline is computed from
the sample arrays (not from a per-frame rolling state), seek, preview and
final render all interpolate the SAME deterministic roll for a given
timestamp.

Naming contract:
- ``gyro_rate_rad_s`` / ``gyro_rate_deg_s`` — angular VELOCITY (never angle).
- ``accel_roll_deg`` — instantaneous roll from the gravity vector.
- ``fused_roll_deg`` — complementary-filter output (the physical roll).
- ``lean_visual_deg`` — after offset / invert / sensitivity / clamp.
"""

from __future__ import annotations

import bisect
import math
from datetime import datetime, timedelta
from typing import Any, Optional

# default complementary-filter weight: gyro dominates dynamics, accel corrects drift
DEFAULT_ALPHA = 0.98
# do not integrate across gaps longer than this (new clip / telemetry hole)
DEFAULT_MAX_GAP_S = 0.5


def gyro_rate_deg_s(gyro_xyz, roll_axis: str) -> float:
    """Angular VELOCITY on the roll axis, rad/s -> deg/s (NOT an angle)."""
    idx = {"x": 0, "y": 1, "z": 2}.get(str(roll_axis).strip().lower(), 2)
    return float(gyro_xyz[idx]) * 180.0 / math.pi


_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _detect_up_axis(accel) -> str:
    """Empirical 'up' reference: the axis carrying the largest mean |gravity|.

    For the test material the parser reorders GPMF ZXY -> canonical XYZ and the
    gravity lands on canonical Z (~-8.9 m/s^2), so ``up_axis == "z"`` here.
    """
    sums = [0.0, 0.0, 0.0]
    count = 0
    for _dt, vec in accel:
        for i in range(3):
            try:
                sums[i] += abs(float(vec[i]))
            except (TypeError, ValueError, IndexError):
                pass
        count += 1
    if count <= 0:
        return "z"
    up = max(range(3), key=lambda i: sums[i])
    return "xyz"[up]


def accel_roll_deg(accel_xyz, roll_axis: str, up_axis: Optional[str] = None) -> float:
    """Instantaneous roll [deg] from the accelerometer gravity vector.

    For each roll axis the two perpendicular axes are used with the convention
    ``atan2(lateral, -up)``, where ``up`` is the axis carrying gravity when
    level (auto-detected from the data by :func:`_detect_up_axis`; the GUI's
    ``zero_offset`` / ``invert`` / axis selection handle mount differences).

    When the roll axis equals the up axis (rotation around the gravity axis),
    the accelerometer cannot measure roll — a documented convention
    ``atan2(perp_b, -perp_a)`` is used (weak reference, gyro dominates).
    """
    comp = [float(v) for v in accel_xyz]
    roll_idx = _AXIS_INDEX.get(str(roll_axis).strip().lower(), 2)
    up_idx = _AXIS_INDEX.get(str(up_axis).strip().lower() if up_axis else "z", 2)
    perps = [i for i in range(3) if i != roll_idx]
    if up_idx in perps:
        lateral = [i for i in perps if i != up_idx][0]
        return math.degrees(math.atan2(comp[lateral], -comp[up_idx]))
    # degenerate (roll == up axis): use perps[0] as the up reference
    return math.degrees(math.atan2(comp[perps[1]], -comp[perps[0]]))


def grade_to_angle_deg(grade_percent: Optional[float]) -> float:
    """FIT grade % -> physical angle [deg]: ``degrees(atan(grade/100))``.

    5% -> ~2.86°, 10% -> ~5.71°, 20% -> ~11.31°.  This is the terrain incline
    ANGLE, not the raw percent, and not bike lean.
    """
    if grade_percent is None:
        return 0.0
    return math.degrees(math.atan(float(grade_percent) / 100.0))


def _nearest_accel(accel_sorted, accel_times, dt):
    """Nearest-in-time accelerometer VECTOR to ``dt`` (returns the vector only)."""
    i = bisect.bisect_left(accel_times, dt)
    if i >= len(accel_sorted):
        return accel_sorted[-1][1]
    best_dt, best_vec = accel_sorted[i]
    if i > 0:
        prev_dt, prev_vec = accel_sorted[i - 1]
        if abs((prev_dt - dt).total_seconds()) < abs((best_dt - dt).total_seconds()):
            best_dt, best_vec = prev_dt, prev_vec
    return best_vec


def compute_roll_timeline(
    accel: list[tuple[datetime, tuple[float, float, float]]],
    gyro: list[tuple[datetime, tuple[float, float, float]]],
    roll_axis: str = "z",
    alpha: float = DEFAULT_ALPHA,
    max_gap_s: float = DEFAULT_MAX_GAP_S,
) -> list[tuple[datetime, float]]:
    """Deterministic precompute: IMU samples -> (timestamp, roll_deg).

    Complementary filter:
        roll += gyro_rate_deg_s * dt                  (gyro dynamics)
        roll = alpha*roll + (1-alpha)*accel_roll      (accel drift correction)

    Falls back honestly when one stream is missing:
    - gyro only  -> integration from the first accel/0 (drifts; documented),
    - accel only -> accel roll (absolute but noisy).
    """
    roll_axis = str(roll_axis).strip().lower()
    if roll_axis not in ("x", "y", "z"):
        roll_axis = "z"
    # empirical "up" reference (the axis carrying gravity when level)
    up_axis = _detect_up_axis(accel)

    if not gyro:
        # accel-only absolute roll
        return [(dt, accel_roll_deg(vec, roll_axis, up_axis)) for dt, vec in accel]

    gyro_sorted = sorted(gyro, key=lambda s: s[0])
    if not accel:
        # gyro-only integration (drift possible) — start at 0
        out: list[tuple[datetime, float]] = []
        roll = 0.0
        prev_dt: Optional[datetime] = None
        for dt, g in gyro_sorted:
            rate = gyro_rate_deg_s(g, roll_axis)
            if prev_dt is not None:
                dts = (dt - prev_dt).total_seconds()
                if 0 < dts <= max_gap_s:
                    roll += rate * dts
            out.append((dt, roll))
            prev_dt = dt
        return out

    accel_sorted = sorted(accel, key=lambda s: s[0])
    accel_times = [s[0] for s in accel_sorted]
    # initial condition from the first accel roll (no assumption about mount)
    roll = accel_roll_deg(accel_sorted[0][1], roll_axis, up_axis)
    out = []
    prev_dt = None
    for dt, g in gyro_sorted:
        rate = gyro_rate_deg_s(g, roll_axis)
        if prev_dt is not None:
            dts = (dt - prev_dt).total_seconds()
            if 0 < dts <= max_gap_s:
                roll += rate * dts
                a_vec = _nearest_accel(accel_sorted, accel_times, dt)
                a_roll = accel_roll_deg(a_vec, roll_axis, up_axis)
                roll = alpha * roll + (1.0 - alpha) * a_roll
        out.append((dt, roll))
        prev_dt = dt
    return out


def interpolate_roll(
    roll_samples: list[tuple[datetime, float]], target_dt: Optional[datetime]
) -> Optional[float]:
    """Linear interpolation of a precomputed roll timeline (smooth + deterministic).

    Normalises tz-awareness: GPMF-derived roll samples carry ``tzinfo=utc``
    while the GUI timeline yields naive-UTC ``target_dt`` (multifile
    convention).  Stripping the marker (both are the same UTC instant) keeps
    the comparison robust, consistent with ``telemetry_extract`` helpers.
    """
    if not roll_samples or target_dt is None:
        return None
    if target_dt.tzinfo is not None:
        target_dt = target_dt.replace(tzinfo=None)
    def _naive(dt):
        return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
    t0_first = _naive(roll_samples[0][0])
    t_last = _naive(roll_samples[-1][0])
    if target_dt <= t0_first:
        return float(roll_samples[0][1])
    if target_dt >= t_last:
        return float(roll_samples[-1][1])
    times = [_naive(s[0]) for s in roll_samples]
    i = bisect.bisect_left(times, target_dt)
    t0, v0 = _naive(roll_samples[i - 1][0]), roll_samples[i - 1][1]
    t1, v1 = _naive(roll_samples[i][0]), roll_samples[i][1]
    span = (t1 - t0).total_seconds()
    if span <= 0:
        return float(v0)
    frac = (target_dt - t0).total_seconds() / span
    return float(v0 + (v1 - v0) * frac)


def merge_axis_samples(
    xs: list, ys: list, zs: list
) -> list[tuple[datetime, tuple[float, float, float]]]:
    """Merge three per-axis scalar sample lists into canonical XYZ vectors.

    The per-axis lists are produced from the same vector series, so they are
    index-aligned; a defensive length cap avoids mismatch.
    """
    n = min(len(xs), len(ys), len(zs))
    out = []
    for i in range(n):
        dt = xs[i][0]
        out.append((dt, (float(xs[i][1]), float(ys[i][1]), float(zs[i][1]))))
    return out


# ---------------------------------------------------------------------------
# Diagnostic (ETAP 21) — only when TELEM_LEAN_DEBUG=1; never spammy by default
# ---------------------------------------------------------------------------

_LEAN_DEBUG = None


def _lean_debug_enabled() -> bool:
    global _LEAN_DEBUG
    if _LEAN_DEBUG is None:
        import os
        _LEAN_DEBUG = str(os.environ.get("TELEM_LEAN_DEBUG", "")).strip().upper() in {"1", "YES", "ON", "TRUE"}
    return _LEAN_DEBUG


def lean_diagnostic(
    accel, gyro, target_dt, roll_axis: str, cfg: Optional[dict] = None,
) -> None:
    """Print the IMU -> lean pipeline for one timestamp (diagnostic only)."""
    if not _lean_debug_enabled():
        return
    cfg = cfg or {}
    roll_axis = str(roll_axis).strip().lower()
    if roll_axis not in ("x", "y", "z"):
        roll_axis = "z"
    up_axis = _detect_up_axis(accel)

    def _nearest(samples):
        if not samples:
            return None
        times = [s[0] for s in samples]
        i = bisect.bisect_left(times, target_dt)
        if i >= len(samples):
            return samples[-1]
        best = samples[i]
        if i > 0 and abs((samples[i - 1][0] - target_dt).total_seconds()) < abs((best[0] - target_dt).total_seconds()):
            best = samples[i - 1]
        return best

    g = _nearest(gyro)
    a = _nearest(accel)
    gyro_raw = g[1][{"x": 0, "y": 1, "z": 2}[roll_axis]] if g else None
    gyro_dps = gyro_rate_deg_s(g[1], roll_axis) if g else None
    accel_vec = a[1] if a else None
    accel_roll = accel_roll_deg(a[1], roll_axis, up_axis) if a else None
    fused_roll = interpolate_roll(compute_roll_timeline(accel, gyro, roll_axis), target_dt)
    offset = float(cfg.get("zero_offset", 0.0))
    invert = bool(cfg.get("invert_axis", False))
    sensitivity = float(cfg.get("sensitivity", 1.0))
    max_angle = abs(float(cfg.get("max_angle", 30.0)))
    visual = (fused_roll - offset) * (-1.0 if invert else 1.0) * sensitivity if fused_roll is not None else 0.0
    visual = max(-max_angle, min(max_angle, visual))
    print(
        "LEAN IMU: timestamp=%s up=%s axis=%s "
        "gyro_raw=%s gyro_deg_s=%s accel=%s accel_roll=%s fused_roll=%s "
        "offset=%.2f inverted=%s sensitivity=%.2f final_angle=%.2f"
        % (target_dt.isoformat() if target_dt else None, up_axis, roll_axis,
           (f"{gyro_raw:.4f}" if gyro_raw is not None else None),
           (f"{gyro_dps:.4f}" if gyro_dps is not None else None),
           (f"{tuple(round(v,3) for v in accel_vec)}" if accel_vec else None),
           (f"{accel_roll:+.2f}" if accel_roll is not None else None),
           (f"{fused_roll:+.2f}" if fused_roll is not None else None),
           offset, invert, sensitivity, visual),
    )
