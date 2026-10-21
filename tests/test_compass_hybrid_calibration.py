import numpy as np
import pytest

from src.telemetry_compass_hybrid import (
    DEFAULTS, HybridResult, calibrate_segment, cori_attitude, gyro_attitude,
    multiply, reconstruct, reference_observations, rotate, sample_hybrid_axis, wrap180,
)


def _axis(duration=450, rate=10):
    t = np.arange(0, duration+.001, 1/rate)
    yaw = 25*np.sin(t/13)+t*.35
    return np.column_stack((t, yaw))


def _observations(axis, start=0, speed=20, offset=350, drift=0):
    t = np.arange(start, axis[-1, 0]+.001)
    values = np.interp(t, axis[:, 0], axis[:, 1])
    return np.column_stack((t, (values+offset+drift*t) % 360,
                            np.full(len(t), speed), np.ones(len(t))))


def _model(result):
    return result.diagnostics["segments"][0].get("model")


def test_fix_requires_stable_segment_then_separate_thirty_second_stabilization():
    imu = _axis(180)
    obs = _observations(imu)
    obs[8, 3] = 0  # bad fix after coordinates first appeared
    model, diag = calibrate_segment(imu, obs, DEFAULTS)
    assert diag["status"] == "ok"
    assert model["stable_fix_ts"] == 14  # 5 continuous seconds after the loss
    assert model["calibration_start_ts"] == 44
    assert model["calibration_end_ts"] == 74
    assert model["window_seconds"] == 30


def test_initial_fix_outliers_never_anchor_the_backwards_axis():
    imu = _axis(180)
    obs = _observations(imu, start=10)
    obs[:4, 1] = 180
    obs[4, 3] = 0
    r = reconstruct(imu, obs, DEFAULTS)
    assert _model(r)["stable_fix_ts"] >= 20
    expected = (imu[:, 1]+350) % 360
    assert np.max(abs(wrap180(r.axis[:100, 1]-expected[:100]))) < 1e-4
    assert np.ptp(r.axis[:100, 1]) > 10  # not the first GPS sample pasted backwards


@pytest.mark.parametrize("desired,bad_seconds", [(60, 15), (120, 28), (180, 42), (240, 57), (300, 72)])
def test_adaptive_window_extends_only_as_far_as_needed(desired, bad_seconds):
    imu = _axis(400)
    obs = _observations(imu)
    # Calibration starts at t=35. Large alternating angular outliers initially
    # fail robust coverage; the first sufficiently clean window must win.
    bad = (obs[:, 0] >= 35) & (obs[:, 0] < 35+bad_seconds)
    obs[bad, 1] = (obs[bad, 1]+np.where(np.arange(np.count_nonzero(bad)) % 2, 50., -50.)) % 360
    r = reconstruct(imu, obs, DEFAULTS)
    assert _model(r)["window_seconds"] == desired
    assert _model(r)["rejected_samples"] >= bad_seconds-1


def test_no_quality_after_maximum_is_unavailable_instead_of_forced():
    imu = _axis(400)
    obs = _observations(imu)
    obs[:, 1] = (obs[:, 1]+45*np.sin(obs[:, 0]*1.13)) % 360
    r = reconstruct(imu, obs, DEFAULTS)
    assert r.diagnostics["status"] == "unavailable"
    assert np.all(np.isnan(r.axis[:, 1]))
    assert r.diagnostics["segments"][0]["attempts"][-1]["window_seconds"] == 300


@pytest.mark.parametrize("speed", [0, 7.9])
def test_no_motion_or_below_eight_kmh_is_not_a_heading_anchor(speed):
    imu = _axis()
    r = reconstruct(imu, _observations(imu, speed=speed), DEFAULTS)
    assert r.diagnostics["status"] == "unavailable"


def test_north_wrap_offset_drift_and_backward_reconstruction():
    imu = _axis(220)
    obs = _observations(imu, start=79, offset=359, drift=.12)
    r = reconstruct(imu, obs, DEFAULTS)
    m = _model(r)
    assert m["drift_applied"]
    assert m["drift_deg_s"] == pytest.approx(.12, abs=1e-5)
    expected = (imu[:, 1]+359+.12*imu[:, 0]) % 360
    assert np.max(abs(wrap180(r.axis[:790, 1]-expected[:790]))) < 1e-4
    assert r.lookup(0) == pytest.approx(359)


def test_wrong_gyro_sign_cannot_pass_a_turning_calibration():
    imu = _axis()
    obs = _observations(imu)
    wrong = imu.copy()
    wrong[:, 1] *= -1
    r = reconstruct(wrong, obs, DEFAULTS)
    assert r.diagnostics["status"] == "unavailable"


def test_gap_prevents_reconstruction_into_an_unanchored_imu_segment():
    imu = _axis(300)
    imu[(imu[:, 0] >= 70) & (imu[:, 0] <= 80), 1] = np.nan
    obs = _observations(_axis(300), start=90)
    r = reconstruct(imu, obs, DEFAULTS)
    assert np.all(np.isnan(r.axis[r.axis[:, 0] <= 80, 1]))
    assert np.any(np.isfinite(r.axis[r.axis[:, 0] > 80, 1]))


def test_drift_disabled_uses_only_offset_and_reports_limited_backward_extent():
    imu = _axis(300)
    obs = _observations(imu, start=120, drift=.12)
    r = reconstruct(imu, obs, dict(DEFAULTS, compass_drift_correction=False))
    assert not _model(r)["drift_applied"]
    assert np.isnan(r.axis[0, 1])  # uncertain distant extrapolation is withheld


def _q(axis, angle):
    return np.r_[np.cos(angle/2), np.asarray(axis)*np.sin(angle/2)]


def _physical_imu(duration=8, dt=.01):
    t = np.arange(0, duration+dt/2, dt)
    heading = np.deg2rad(350+35*np.sin(t*.6))
    roll = np.deg2rad(20*np.sin(t*.8))
    pitch = np.deg2rad(15*np.sin(t*.4))
    quats = np.array([multiply(multiply(_q([0, 0, 1], -h), _q([0, 1, 0], p)), _q([1, 0, 0], r))
                      for h, p, r in zip(heading, pitch, roll)])
    accel = rotate(quats*[1, -1, -1, -1], np.tile([0., 0., 9.81], (len(t), 1)))
    rates = []
    for a, b in zip(quats, quats[1:]):
        d = multiply(a*[1, -1, -1, -1], b)
        angle = 2*np.arctan2(np.linalg.norm(d[1:]), abs(d[0]))
        rates.append(d[1:]/max(np.linalg.norm(d[1:]), 1e-12)*angle/dt)
    rates.append(rates[-1])
    return t, heading, quats, np.column_stack((t, rates)), np.column_stack((t, accel))


def test_full_quaternion_gyro_handles_roll_pitch_and_correct_turn_sign():
    t, heading, _qv, gyro, accel = _physical_imu()
    axis, diag = gyro_attitude(gyro, accel)
    assert diag["method"] == "GYRO+ACCL quaternion"
    # Compare against the optical axis projected into the horizontal plane,
    # not the Euler Z angle (which differs with simultaneous pitch/roll).
    forward = rotate(_qv, np.tile([0., 1., 0.], (len(t), 1)))
    expected = np.rad2deg(np.unwrap(np.arctan2(forward[:, 0], forward[:, 1])))
    expected -= expected[0]
    error = wrap180(axis[:, 1]-np.interp(axis[:, 0], t, expected))
    assert np.percentile(abs(error), 95) < .7


def test_cori_priority_when_gravity_and_quaternion_frame_are_consistent():
    t = np.arange(0, 5, .02)
    heading = np.deg2rad(350+10*t)
    q = np.array([multiply(_q([0, 0, 1], -h), _q([1, 0, 0], -np.pi/2)) for h in heading])
    g = rotate(q*[1, -1, -1, -1], np.tile([0., 0., 1.], (len(q), 1)))
    axis, diag = cori_attitude(np.column_stack((t, q)), np.column_stack((t, g)))
    assert diag["method"] == "CORI+GRAV"
    assert np.max(abs(wrap180(axis[:, 1]-(np.rad2deg(heading)-350)))) < 1e-8


def test_missing_cori_and_missing_all_imu_are_explicitly_unavailable():
    assert cori_attitude(np.empty((0, 5)), np.empty((0, 4)))[0] is None
    axis, diag = gyro_attitude(np.empty((0, 4)), np.empty((0, 4)))
    assert not len(axis)
    assert "missing" in diag["reason"]


def test_position_jump_quality_and_high_rate_deduplication():
    t = np.arange(0, 100, .1)
    # Straight 20 km/h track north, with one impossible GPS jump.
    track = np.column_stack((t, 54+t*(20/3.6)/111195, np.full(len(t), 18.)))
    track[100, 1] += 1
    quality = np.column_stack((t, np.ones(len(t)), np.full(len(t), 3)))
    quality[(t > 20) & (t < 25), 2] = 0
    obs, diag = reference_observations(track, quality=quality)
    assert len(obs) < 101  # 1000 GPS records do not become 1000 anchors
    assert diag["gps_rejected"] > 5
    assert np.all(obs[(obs[:, 0] >= 10) & (obs[:, 0] <= 11), 3] == 0)
    assert np.all(obs[(obs[:, 0] > 21) & (obs[:, 0] < 24), 3] == 0)


def test_canonical_sampling_preserves_missing_north_wrap_and_float32():
    axis = np.array([[0., 359.], [1., 1.], [2., np.nan], [3., 180.]])
    r = HybridResult(axis)
    values = sample_hybrid_axis(axis, np.array([-.1, 0., .5, 1., 2., 3., 4.]))
    assert values.dtype == np.float32
    assert values[2] == 0
    assert r.lookup(.5) == 0
    assert r.lookup(2) is None
    assert r.lookup(4) is None
