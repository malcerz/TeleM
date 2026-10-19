"""Telemetry sync contract + SmartSync IMU (synthetic data with known offsets)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from smartsync_synth import make_ride  # noqa: E402
from src.telemetry_smartsync_imu import estimate_imu_offset  # noqa: E402
from src.telemetry_sync import (  # noqa: E402
    TelemetrySyncState, load_sync_state, material_key, save_sync_state, shift_timestamps,
)


def _estimate(ride, **kw):
    return estimate_imu_offset(
        gyro=ride.gyro, accel=ride.accel, video_t0_epoch=ride.video_t0_epoch,
        fit_t_epoch=ride.fit_t, fit_speed_kmh=ride.fit_speed_kmh,
        fit_lat=ride.fit_lat, fit_lon=ride.fit_lon, **kw,
    )


# ── SmartSync IMU ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("true_offset", [1.5, -3.2])
def test_known_offset_recovered(true_offset):          # A, B
    r = _estimate(make_ride(duration_s=300.0, true_offset_s=true_offset, seed=2))
    assert r.status == "OK" and r.confidence_level == "high"
    assert abs(r.offset_s - true_offset) <= 0.25
    assert r.events >= 4


@pytest.mark.parametrize("true_offset", [47.6, -250.0])
def test_wrong_camera_start_time_adaptive_search(true_offset):   # C
    r = _estimate(make_ride(duration_s=300.0, true_offset_s=true_offset, seed=1))
    assert r.status == "OK"
    assert abs(r.offset_s - true_offset) <= 0.25


def test_no_imu_reports_message():                      # E
    ride = make_ride(duration_s=120.0, seed=0)
    r = estimate_imu_offset(gyro=None, accel=None, video_t0_epoch=ride.video_t0_epoch,
                            fit_t_epoch=ride.fit_t, fit_speed_kmh=ride.fit_speed_kmh,
                            fit_lat=ride.fit_lat, fit_lon=ride.fit_lon)
    assert r.status == "NO_IMU" and r.offset_s is None and "IMU" in r.message


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_constant_straight_ride_is_not_applied(seed):   # F
    r = _estimate(make_ride(duration_s=180.0, true_offset_s=2.0, seed=seed, straight=True, constant_speed=True))
    assert r.status != "OK"


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_different_activity_is_not_applied(seed):       # G
    r = _estimate(make_ride(duration_s=180.0, true_offset_s=2.0, seed=seed, fit_from_other_ride=True))
    assert r.status != "OK"


def test_short_clip_not_overconfident():
    for seed in range(3):
        r = _estimate(make_ride(duration_s=60.0, true_offset_s=1.5, seed=seed))
        if r.status == "OK":
            assert abs(r.offset_s - 1.5) <= 0.5


# ── Contract / data layer ──────────────────────────────────────────────────

def _records(start: datetime, n: int = 600):
    out = []
    for i in range(n):
        out.append({
            "timestamp": start + timedelta(seconds=i), "speed": 20.0 + (i % 30),
            "heart_rate": 100 + i % 50, "lat": 54.36 + i * 1e-5, "lon": 18.62 + i * 1e-5,
        })
    return out


def _loaded_manager(tmp_path, start):
    from telemetry_fit import FitRecords
    from src.gui.telemetry_manager import TelemetryDataManager
    from src.telemetry_active_time import ActiveTimeMapper
    fit = tmp_path / "a.fit"
    fit.write_bytes(b"\0")
    mapper = ActiveTimeMapper([(start, start + timedelta(seconds=200)),
                               (start + timedelta(seconds=260), start + timedelta(seconds=599))])
    recs = FitRecords(_records(start), active_time_mapper=mapper)
    tm = TelemetryDataManager()
    assert tm.load_fit(tmp_path / "v.mp4", start + timedelta(seconds=10), manual_path=fit, preparsed=recs)
    return tm


def _hr_at(tm, dt):
    for t, v in tm.fit_data["heart_rate"]:
        if t == dt:
            return v
    return None


def test_offset_shifts_activity_once_and_resets(tmp_path):
    start = datetime(2026, 10, 5, 4, 29, 0)
    tm = _loaded_manager(tmp_path, start)
    probe = start + timedelta(seconds=100)
    original = _hr_at(tm, probe)
    tm.set_telemetry_sync(2.0)
    # telemetry_time = video_time + 2  =>  the sample recorded at probe+2 is shown at probe
    assert _hr_at(tm, probe) == 100 + 102 % 50
    tm.set_telemetry_sync(2.0)          # idempotent: never added twice
    assert _hr_at(tm, probe) == 100 + 102 % 50
    tm.set_telemetry_sync(0.0)
    assert _hr_at(tm, probe) == original
    assert tm.fit_gps_track[0][0] == start


def test_pause_mapper_moves_with_samples(tmp_path):
    start = datetime(2026, 10, 5, 4, 29, 0)
    tm = _loaded_manager(tmp_path, start)
    m0 = tm.fit_data.active_time_mapper
    tm.set_telemetry_sync(5.0)
    m1 = tm.fit_data.active_time_mapper
    assert m1.pause_intervals[0][0] == m0.pause_intervals[0][0] - timedelta(seconds=5)


def test_per_clip_offsets_piecewise():
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    items = [(t0 + timedelta(seconds=i), i) for i in range(0, 400)]
    windows = [(t0, t0 + timedelta(seconds=100)), (t0 + timedelta(seconds=200), t0 + timedelta(seconds=300))]
    out = shift_timestamps(items, lambda x: x[0], lambda x, ts: (ts, x[1]), 1.0, windows, {1: 9.0})
    shown = {ts: v for ts, v in out}
    assert shown[t0 + timedelta(seconds=50)] == 51        # clip 1: +1 s
    assert shown[t0 + timedelta(seconds=250)] == 260      # clip 2: +1 + 9 s
    assert [ts for ts, _ in out] == sorted(ts for ts, _ in out)


def test_cache_key_depends_on_sync():
    from src.render_preparation import RenderPreparationService as R
    kw = dict(video_paths=[], total_frames=10, target_fps=30.0, start_dt_utc=datetime(2026, 1, 1))
    k0 = R.compute_cache_key(sync_offset_s=0.0, layout={}, **kw)
    k1 = R.compute_cache_key(sync_offset_s=0.1, layout={}, **kw)
    k2 = R.compute_cache_key(sync_offset_s=0.1, layout={"telemetry_sync_clip_offsets_s": {"1": 0.5}}, **kw)
    assert len({k0, k1, k2}) == 3


def _clip(offset, level="high", status="OK", conf=0.8):
    return {"status": status, "offset_s": offset, "confidence": conf, "confidence_level": level, "events": 5}


def test_multiclip_agreeing_clips_use_one_offset():      # J
    from src.gui.qt._mixins.sync_mixin import SyncMixin
    r = SyncMixin._combine_clip_results(object(), [_clip(2.0), _clip(2.1), _clip(1.95)], "fit", "")
    assert r["status"] == "OK" and r["offset_s"] == pytest.approx(2.0) and r["clip_offsets_s"] == {}


def test_multiclip_different_clocks_get_per_clip_offsets():   # J
    from src.gui.qt._mixins.sync_mixin import SyncMixin
    r = SyncMixin._combine_clip_results(object(), [_clip(2.0), _clip(7.5), _clip(2.1)], "fit", "")
    assert r["status"] == "OK"
    eff = {i: r["offset_s"] + r["clip_offsets_s"].get(i, 0.0) for i in range(3)}
    assert eff[0] == pytest.approx(2.0) and eff[1] == pytest.approx(7.5) and eff[2] == pytest.approx(2.1)


def test_multiclip_unreliable_clip_keeps_global():       # J
    from src.gui.qt._mixins.sync_mixin import SyncMixin
    r = SyncMixin._combine_clip_results(
        object(), [_clip(2.0), _clip(40.0, level="medium", status="AMBIGUOUS"), _clip(2.2)], "fit", "")
    assert r["status"] == "OK" and 1 not in r["clip_offsets_s"]


def test_multiclip_nothing_reliable_is_only_a_proposal():
    from src.gui.qt._mixins.sync_mixin import SyncMixin
    r = SyncMixin._combine_clip_results(
        object(), [_clip(3.0, "medium", "AMBIGUOUS"), _clip(9.0, "low", "AMBIGUOUS")], "fit", "")
    assert r["status"] == "AMBIGUOUS"


def test_gopro_gps_method_recovers_offset():             # K
    from src.gui.qt._mixins.sync_mixin import SyncMixin

    class _TM:
        pass
    start = datetime(2026, 10, 15, 13, 0, 0)
    recs = [{"timestamp": start + timedelta(seconds=i), "lat": 54.36 + 0.0001 * i + 0.00005 * ((i // 20) % 2),
             "lon": 18.62 + 0.00015 * (i % 40)} for i in range(600)]
    tm = _TM()
    tm._fit_base = {"records": recs}
    true_sync = 3.0   # camera position at video time t equals FIT position at t + 3 s
    track = [(r["timestamp"] - timedelta(seconds=true_sync), r["lat"], r["lon"]) for r in recs[100:250]]
    res = SyncMixin._smartsync_gps(object(), tm, track)
    assert res["status"] == "OK"
    assert res["offset_s"] == pytest.approx(true_sync, abs=0.15)


def test_persistence_roundtrip(tmp_path):
    v = tmp_path / "DJI_0001.MP4"
    v.write_bytes(b"x")
    f = tmp_path / "a.fit"
    f.write_bytes(b"y")
    store = tmp_path / "sync.json"
    key = material_key([v], f)
    st = TelemetrySyncState(offset_s=-3.21, clip_offsets_s={1: 0.4}, method="smartsync_imu",
                            confidence=0.8, confidence_level="high")
    save_sync_state(key, st, store_path=store)
    back = load_sync_state(key, store_path=store)
    assert back.offset_s == pytest.approx(-3.21) and back.clip_offsets_s == {1: 0.4}
    assert back.method == "smartsync_imu"
    save_sync_state(key, None, store_path=store)
    assert load_sync_state(key, store_path=store) is None
