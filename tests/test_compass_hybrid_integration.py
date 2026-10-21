from datetime import datetime, timedelta
from types import SimpleNamespace
import threading

import numpy as np
import pytest

from src.ffmpeg.amd_native_exporter import _amd_compass_samples
from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value
from src.gui.telemetry_manager import TelemetryDataManager
from src.render_preparation import RenderPreparationService
from src.render_telemetry_cache import RenderTelemetryCache
from src.telemetry_compass_hybrid import DEFAULTS, HybridResult, parameters, prepare_manager_compass, wrap180
from src.gui.qt.models import compass_indicator_fields, get_schema_for_indicator
from tests.test_compass_hybrid_calibration import _q


def _cfg(**overrides):
    return dict(DEFAULTS, compass_heading_mode="gps_imu", enabled=True, form="gauge",
                gauge_style="compass", x=50, y=50, size=10, **overrides)


def test_shared_precomputed_axis_preview_worker_final_and_disk_parity(tmp_path):
    base = datetime(2026, 10, 16)
    start = base.replace(tzinfo=__import__('datetime').timezone.utc).timestamp()
    axis = np.array([[start, 359.], [start+1, 1.], [start+2, np.nan], [start+3, 120.]])
    result = HybridResult(axis)
    cfg = _cfg()
    layout = {"indicators": {"compass": cfg}}
    tm = TelemetryDataManager()
    tm._compass_cfg = cfg
    tm._compass_token = (tm._compass_generation, tuple(sorted(parameters(cfg).items())))
    tm._compass_result = result
    fields = {"compass_hybrid_samples": result.samples, "heading_samples": [(base, 270.)]}
    assert _amd_compass_samples(layout, fields, {"heading": [(base, 180.)]}) is fields["compass_hybrid_samples"]
    init_worker(640, 360, "", layout, fields)
    cache = RenderPreparationService.build_telemetry_cache_vectorized(
        layout=layout, base_dt=base, start_dt_utc=base, target_fps=30, total_frames=91,
        field_samples=fields, fit_data={"heading": [(base, 180.)]},
    )
    cache.save(tmp_path)
    loaded = RenderTelemetryCache.load(tmp_path / "manifest.json")
    for i in range(91):
        dt = base+timedelta(seconds=i/30)
        preview = tm.resolve_value("heading", dt, indicator_key="compass", indicator_config=cfg)
        final = cache.lookup(i)["extra_indicators"]["compass"][0]
        assert preview == final == _resolve_cache_value("heading", "fit", dt, "compass")
        assert loaded.lookup(i)["extra_indicators"]["compass"][0] == final


def test_no_prepared_axis_does_not_silently_use_either_gps_source():
    base = datetime(2026, 10, 16)
    cfg = _cfg()
    layout = {"indicators": {"compass": cfg}}
    fields = {"heading_samples": [(base, 90.)]}
    init_worker(640, 360, "", layout, fields, fit_data={"heading": [(base, 180.)]})
    assert _amd_compass_samples(layout, fields, {"heading": [(base, 180.)]}) == []
    assert _resolve_cache_value("heading", "gpmf", base, "compass") is None
    cache = RenderPreparationService.build_telemetry_cache_vectorized(
        layout=layout, base_dt=base, total_frames=3, field_samples=fields,
    )
    assert cache.lookup(0)["extra_indicators"]["compass"][0] is None


@pytest.mark.parametrize("field,value", [
    ("compass_reference_source", "fit"), ("gps_stabilization_seconds", 31),
    ("min_calibration_seconds", 60), ("max_calibration_seconds", 240),
    ("min_calibration_speed_kmh", 10), ("compass_imu_method", "gyro"),
    ("compass_drift_correction", False), ("compass_mount_offset_deg", 15),
])
def test_every_semantic_parameter_invalidates_render_cache(field, value):
    cfg = _cfg()
    def key(config):
        return RenderPreparationService.compute_cache_key(video_paths=[], total_frames=10, target_fps=30,
                                                           layout={"indicators": {"compass": config}})
    assert key(dict(cfg, **{field: value})) != key(cfg)
    assert key(dict(cfg, compass_needle_color="#ABCDEF")) == key(cfg)


def test_standard_mode_signature_is_unchanged_and_controls_are_conditional():
    plain = {"indicators": {"compass": {"source": "gpmf"}}}
    explicit = {"indicators": {"compass": {"source": "gpmf", "compass_heading_mode": "standard"}}}
    assert RenderPreparationService.extract_semantic_data_signature(plain) == RenderPreparationService.extract_semantic_data_signature(explicit)
    fields = {f.name: f for f in compass_indicator_fields()}
    assert fields["compass_heading_mode"].default == "standard"
    assert "compass_reference_source" not in fields
    fields = {f.name: f for f in get_schema_for_indicator("compass", "gauge", cfg=_cfg())}
    assert fields["compass_reference_source"].choices == [("gpmf", "GPS GoPro"), ("fit", "FIT / Garmin")]
    assert fields["gps_stabilization_seconds"].default == 30


def _realistic_fixture(tmp_path, monkeypatch, second_clip=False):
    from src import telemetry_compass_orientation as reader
    from src.telemetry_compass_hybrid import multiply, rotate
    base = datetime(2026, 10, 16)
    start = base.replace(tzinfo=__import__('datetime').timezone.utc).timestamp()
    calls = []
    t = np.arange(0, 200, .1)
    heading = 20+15*np.sin(t/20)
    radians = np.deg2rad(heading)
    q = np.array([multiply(_q([0, 0, 1], -h), _q([1, 0, 0], -np.pi/2)) for h in radians])
    g = rotate(q*[1, -1, -1, -1], np.tile([0., 0., 1.], (len(q), 1)))
    def read(path, base_ts):
        calls.append((path, base_ts))
        return {"CORI": np.column_stack((base_ts+t, q)), "GRAV": np.column_stack((base_ts+t, g))}, {"cache_hit": False}
    monkeypatch.setattr(reader, "read_orientation", read)
    tm = TelemetryDataManager()
    clips = []
    all_track = []
    all_fit = []
    for i in range(2 if second_clip else 1):
        path = tmp_path / f"clip{i}.mp4"
        path.write_bytes(b"test source fingerprint")
        bt = start+i*210
        clips.append(SimpleNamespace(path=path, absolute_start_dt=base+timedelta(seconds=i*210),
                                     source_duration_s=200., duration_s=200., local_start_s=0.))
        dt = .1
        north = np.cumsum(np.cos(radians)*20/3.6*dt)
        east = np.cumsum(np.sin(radians)*20/3.6*dt)
        all_track.extend((datetime.fromtimestamp(bt+tt, __import__('datetime').timezone.utc).replace(tzinfo=None),
                          54+n/111195, 18+e/(111195*np.cos(np.deg2rad(54)))) for tt, n, e in zip(t, north, east))
        # Same motion rotated 90 degrees: explicit source selection must change
        # the absolute anchor, not choose the other source's data implicitly.
        all_fit.extend((datetime.fromtimestamp(bt+tt, __import__('datetime').timezone.utc).replace(tzinfo=None),
                        54-e/111195, 18+n/(111195*np.cos(np.deg2rad(54)))) for tt, n, e in zip(t, north, east))
    tm.timeline = SimpleNamespace(clips=clips)
    tm.gps_track = all_track
    tm.fit_gps_track = all_fit
    return tm, calls, start


def test_hybrid_cache_hit_source_switch_and_full_source_in_out(tmp_path, monkeypatch):
    tm, calls, start = _realistic_fixture(tmp_path, monkeypatch)
    cfg = _cfg()
    cache = tmp_path / "cache"
    first = prepare_manager_compass(tm, cfg, cache_dir=cache)
    assert first.diagnostics["status"] == "ok"
    assert first.diagnostics["clips"][0]["method"] == "CORI+GRAV"
    assert first.lookup(start) is not None
    count = len(calls)
    hit = prepare_manager_compass(tm, cfg, cache_dir=cache)
    assert len(calls) == count
    assert hit.diagnostics["clips"][0]["cache_hit"]
    assert np.array_equal(first.axis, hit.axis, equal_nan=True)
    clip = tm.timeline.clips[0]
    clip.absolute_start_dt += timedelta(seconds=10)
    clip.local_start_s = 10
    clip.duration_s = 5
    cut = prepare_manager_compass(tm, cfg, cache_dir=cache)
    assert cut.diagnostics["clips"][0]["cache_hit"]
    assert np.array_equal(first.axis, cut.axis, equal_nan=True)
    fit = prepare_manager_compass(tm, dict(cfg, compass_reference_source="fit"), cache_dir=cache)
    assert fit.diagnostics["reference_source"] == "fit"
    assert not fit.diagnostics["clips"][0]["cache_hit"]
    assert abs(float(wrap180(fit.lookup(start)-first.lookup(start)))-90) < 1


def test_independent_files_do_not_share_calibration_across_gap(tmp_path, monkeypatch):
    tm, calls, start = _realistic_fixture(tmp_path, monkeypatch, second_clip=True)
    tm.gps_track = [(t, a, b) for t, a, b in tm.gps_track if t >= datetime(2026, 10, 16)+timedelta(seconds=210)]
    r = prepare_manager_compass(tm, _cfg(), cache_dir=tmp_path / "cache")
    assert r.lookup(start+50) is None
    assert r.lookup(start+205) is None
    assert r.lookup(start+220) is not None
    assert len(calls) == 2


def test_missing_selected_fit_has_no_fallback_to_good_gopro(tmp_path, monkeypatch):
    tm, calls, _start = _realistic_fixture(tmp_path, monkeypatch)
    tm.fit_gps_track = []
    r = prepare_manager_compass(tm, _cfg(compass_reference_source="fit"), cache_dir=tmp_path / "cache")
    assert r.diagnostics["status"] == "unavailable"
    assert "no fallback" in r.diagnostics["reason"]
    assert calls == []


def test_late_background_project_result_cannot_replace_new_project(monkeypatch):
    from src import telemetry_compass_hybrid as module
    tm = TelemetryDataManager()
    entered = threading.Event()
    release = threading.Event()
    ready = threading.Event()
    def build(_snapshot, cfg):
        entered.set()
        assert release.wait(5)
        return HybridResult(np.array([[0., 123.]]), {"status": "ok"})
    monkeypatch.setattr(module, "snapshot_manager", lambda _tm: object())
    monkeypatch.setattr(module, "prepare_manager_compass", build)
    tm.request_compass_preparation(_cfg(), lambda _token: ready.set())
    assert entered.wait(5)
    tm.invalidate_compass()
    release.set()
    assert ready.wait(5)
    assert tm._compass_result is None
