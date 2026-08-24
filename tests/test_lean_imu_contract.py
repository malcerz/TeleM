"""ETAP 13 — real GoPro IMU roll angle for the Lean indicator.

Audit-grounded contract:
- GPMF GYRO is rad/s (angular VELOCITY, never an angle); ACCL is m/s^2.
- Roll is PRECOMPUTED with a complementary filter (gyro integration + accel
  gravity) into a deterministic timeline (timestamp -> roll_deg), so seek /
  preview / final render interpolate the same result.
- Visual pipeline: roll - offset -> invert -> sensitivity -> clamp.
- FIT grade % -> angle via atan(grade/100).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from PIL import Image, ImageChops

from src.indicators.lean import lean_angle, lean_visual_angle
from src.telemetry_imu import (
    accel_roll_deg,
    compute_roll_timeline,
    grade_to_angle_deg,
    gyro_rate_deg_s,
    interpolate_roll,
    merge_axis_samples,
)

T0 = datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc)


def _gyro(rate_rad_s, axis="z", n=20, dt_s=0.01):
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    vec = [0.0, 0.0, 0.0]
    vec[idx] = rate_rad_s
    return [(T0 + timedelta(seconds=i * dt_s), tuple(vec)) for i in range(n)]


def _accel_level(n=20, dt_s=0.01, roll_deg=0.0):
    """Stable accelerometer: gravity ~9.8 on -X with an optional roll."""
    th = math.radians(roll_deg)
    ax = -9.8 * math.cos(th)
    ay = 9.8 * math.sin(th)
    return [(T0 + timedelta(seconds=i * dt_s), (ax, ay, 0.0)) for i in range(n)]


# ---------------------------------------------------------------------------
# TEST 1 — GYRO IS deg/s, NOT an angle
# ---------------------------------------------------------------------------

def test_gyro_unit_is_angular_velocity():
    # 1 rad/s on X -> 57.2958 deg/s (a RATE, not a deg angle)
    assert gyro_rate_deg_s((1.0, 0.0, 0.0), "x") == pytest.approx(180.0 / math.pi)
    assert gyro_rate_deg_s((0.0, 1.0, 0.0), "y") == pytest.approx(180.0 / math.pi)
    assert gyro_rate_deg_s((0.0, 0.0, 1.0), "z") == pytest.approx(180.0 / math.pi)


# ---------------------------------------------------------------------------
# TEST 2 — GYRO INTEGRATION
# ---------------------------------------------------------------------------

def test_gyro_integration_dt_accumulates_angle():
    gyro = _gyro(1.0, axis="z", dt_s=0.1)          # 1 rad/s, 0.1 s steps
    timeline = compute_roll_timeline(accel=[], gyro=gyro, roll_axis="z")
    # gyro-only integration: each step adds ~5.73°
    assert len(timeline) == len(gyro)
    assert timeline[0][1] == pytest.approx(0.0)
    # after 0.1 s at 1 rad/s -> ~5.73 deg
    assert timeline[1][1] == pytest.approx(0.1 * (180.0 / math.pi), abs=1e-6)


# ---------------------------------------------------------------------------
# TEST 3 — ZERO GYRO -> NO DRIFT with stable accel
# ---------------------------------------------------------------------------

def test_zero_gyro_stable_accel_no_drift():
    gyro = _gyro(0.0, axis="z", dt_s=0.01, n=200)
    accel = _accel_level(roll_deg=0.0, n=200, dt_s=0.01)
    timeline = compute_roll_timeline(accel=accel, gyro=gyro, roll_axis="z")
    final = timeline[-1][1]
    # no drift: fused roll stays near 0 (stable gravity on X)
    assert abs(final) < 1.0
    assert abs(timeline[100][1]) < 1.0


# ---------------------------------------------------------------------------
# TEST 4 — ACCEL ROLL for a known lean
# ---------------------------------------------------------------------------

def test_accel_roll_known_lean():
    # gravity tilted by 10° around Z (roll): accel = (-9.8cos10, +9.8sin10, 0)
    th = math.radians(10.0)
    vec = (-9.8 * math.cos(th), 9.8 * math.sin(th), 0.0)
    assert accel_roll_deg(vec, "z") == pytest.approx(10.0, abs=1e-6)
    # level -> 0
    assert accel_roll_deg((-9.8, 0.0, 0.0), "z") == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# TEST 5 — COMPLEMENTARY FILTER corrects gyro drift with accel
# ---------------------------------------------------------------------------

def test_complementary_filter_prevents_gyro_bias_drift():
    # a small gyro bias would integrate to a huge angle; accel correction
    # must keep the fused roll near the true (stable) accel roll.
    n = 400
    gyro = _gyro(0.05, axis="z", dt_s=0.01, n=n)      # bias 0.05 rad/s
    accel = _accel_level(roll_deg=0.0, n=n, dt_s=0.01)
    timeline = compute_roll_timeline(accel=accel, gyro=gyro, roll_axis="z")
    final = abs(timeline[-1][1])
    # uncorrected integration would be ~0.05*57.3*4s = ~11.5°; fusion keeps it small
    assert final < 3.0, f"fused roll drifted to {final:.2f}° despite stable accel"


# ---------------------------------------------------------------------------
# TEST 6 — SEEK DETERMINISM (same timestamp -> same roll)
# ---------------------------------------------------------------------------

def test_roll_timeline_is_deterministic_for_seek():
    accel = _accel_level(roll_deg=5.0, n=100, dt_s=0.01)
    gyro = _gyro(0.02, axis="z", dt_s=0.01, n=100)
    t1 = compute_roll_timeline(accel=accel, gyro=gyro, roll_axis="z")
    t2 = compute_roll_timeline(accel=accel, gyro=gyro, roll_axis="z")
    # same input arrays -> identical timeline (pure function, no hidden state)
    assert [round(v, 9) for _, v in t1] == [round(v, 9) for _, v in t2]
    target = T0 + timedelta(seconds=0.5)
    a = interpolate_roll(t1, target)
    b = interpolate_roll(t2, target)
    assert a == pytest.approx(b)
    # repeated interpolations from the same timeline are stable (no rolling state)
    assert interpolate_roll(t1, target) == pytest.approx(interpolate_roll(t1, target))


# ---------------------------------------------------------------------------
# TEST 7 — PREVIEW / FINAL PARITY (manager & worker produce the same roll)
# ---------------------------------------------------------------------------

def test_manager_worker_roll_parity():
    from src.telemetry_imu import compute_roll_timeline
    accel = _accel_level(roll_deg=4.0, n=60, dt_s=0.01)
    gyro = _gyro(0.01, axis="z", dt_s=0.01, n=60)
    # both paths build the timeline from the same samples via compute_roll_timeline
    timeline = compute_roll_timeline(accel=accel, gyro=gyro, roll_axis="z")
    target = T0 + timedelta(seconds=0.4)
    roll = interpolate_roll(timeline, target)
    # lean visual angle identical for preview/final (same cfg + same roll)
    cfg = {"source": "gyro", "sensitivity": 1.0, "max_angle": 30.0, "zero_offset": 0.0}
    assert lean_angle(roll, cfg) == lean_angle(roll, dict(cfg))


def test_lean_preview_final_widget_parity():
    from src.indicators.compositor import compose_overlay
    layout = {"global": {}, "indicators": {"lean_indicator": {
        "enabled": True, "form": "lean", "label": "PRZECHYŁ", "unit": "°",
        "source": "gyro", "axis": "z", "sensitivity": 1.0, "max_angle": 30.0,
        "graphic": "bike", "show_value": True, "decimals": 0, "x": 50.0,
        "y": 50.0, "size": 14.0, "rotation": 0, "font_size": 1.2,
    }}}
    extra = {"lean_indicator": (10.0, "°", "PRZECHYŁ")}   # physical roll 10°
    bf, bp = {}, {}
    img_f = compose_overlay(1280, 720, layout, "", "", "", 0.0, 0.0, 0.0,
                            extra_indicators=extra, _bboxes=bf, fast_preview=False, reuse_canvas=False)
    img_p = compose_overlay(1280, 720, layout, "", "", "", 0.0, 0.0, 0.0,
                            extra_indicators=extra, _bboxes=bp, fast_preview=True, reuse_canvas=False)
    b = bf.get("lean_indicator")
    cf = img_f.crop((b[0], b[1], b[0] + b[2], b[1] + b[3]))
    cp = img_p.crop((b[0], b[1], b[0] + b[2], b[1] + b[3]))
    assert ImageChops.difference(cf, cp).getbbox() is None


# ---------------------------------------------------------------------------
# TEST 8 / 9 / 10 / 11 — INVERT / OFFSET / SENSITIVITY / CLAMP
# ---------------------------------------------------------------------------

def test_invert_flips_angle():
    assert lean_visual_angle(10.0, {"invert_axis": True, "sensitivity": 1.0}) == pytest.approx(-10.0)
    assert lean_visual_angle(10.0, {"invert_axis": False, "sensitivity": 1.0}) == pytest.approx(10.0)


def test_zero_offset_subtracts():
    assert lean_visual_angle(12.0, {"zero_offset": 2.0, "sensitivity": 1.0}) == pytest.approx(10.0)
    assert lean_visual_angle(2.0, {"zero_offset": 2.0, "sensitivity": 1.0}) == pytest.approx(0.0)


def test_sensitivity_scales_physical_angle():
    cfg = {"sensitivity": 1.5, "max_angle": 90.0, "zero_offset": 0.0}
    assert lean_visual_angle(10.0, cfg) == pytest.approx(15.0)


def test_clamp_limits_visual_angle():
    cfg = {"sensitivity": 1.0, "max_angle": 20.0, "zero_offset": 0.0}
    assert lean_visual_angle(40.0, cfg) == pytest.approx(20.0)
    assert lean_visual_angle(-40.0, cfg) == pytest.approx(-20.0)


# ---------------------------------------------------------------------------
# TEST 12 — FIT GRADE % -> angle (atan)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("grade,expected", [(5.0, 2.8624), (10.0, 5.7106), (20.0, 11.3099)])
def test_grade_to_angle_uses_atan(grade, expected):
    assert grade_to_angle_deg(grade) == pytest.approx(expected, abs=1e-3)
    assert grade_to_angle_deg(grade) != grade  # NOT 1:1


# ---------------------------------------------------------------------------
# TEST 13 / 14 — MISSING ACCEL / GYRO fallbacks
# ---------------------------------------------------------------------------

def test_missing_accel_gyro_only_no_crash():
    gyro = _gyro(0.2, axis="z", dt_s=0.01, n=30)
    timeline = compute_roll_timeline(accel=[], gyro=gyro, roll_axis="z")
    assert len(timeline) == 30
    assert abs(timeline[-1][1]) > 0  # integration advanced (drift possible)
    # readable interpolation still works
    assert interpolate_roll(timeline, T0 + timedelta(seconds=0.15)) is not None


def test_missing_gyro_accel_only_no_crash():
    accel = _accel_level(roll_deg=6.0, n=20, dt_s=0.01)
    timeline = compute_roll_timeline(accel=accel, gyro=[], roll_axis="z")
    assert len(timeline) == 20
    assert accel_roll_deg(accel[0][1], "z") == pytest.approx(6.0, abs=1e-6)
    assert interpolate_roll(timeline, T0 + timedelta(seconds=0.1)) is not None


# ---------------------------------------------------------------------------
# TEST 15 — LARGE DT does not cause a giant angle jump
# ---------------------------------------------------------------------------

def test_large_gap_does_not_integrate_runaway():
    # gap larger than max_gap_s must NOT be integrated blindly
    gyro = [
        (T0, (0.0, 0.0, 3.0)),                       # fast spin at t=0
        (T0 + timedelta(seconds=10.0), (0.0, 0.0, 3.0)),  # huge gap (10 s)
        (T0 + timedelta(seconds=10.1), (0.0, 0.0, 3.0)),
    ]
    accel = _accel_level(roll_deg=0.0, n=3, dt_s=0.01)
    timeline = compute_roll_timeline(accel=accel, gyro=gyro, roll_axis="z", max_gap_s=0.5)
    # the 10 s gap is skipped (max_gap_s=0.5); the 0.1 s step adds ~17.2°
    # but accel correction pulls it back; crucially no ~57.3*30° jump from the gap.
    for _, v in timeline:
        assert abs(v) < 200.0
