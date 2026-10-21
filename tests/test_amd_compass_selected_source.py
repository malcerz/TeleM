from datetime import datetime, timedelta

import pytest

from src.ffmpeg.amd_native_exporter import _amd_compass_samples
from src.ffmpeg.worker_cache import init_worker
from src.render_preparation import RenderPreparationService
from src.render_telemetry_cache import RenderTelemetryCache
from src.telemetry_heading import interpolate_heading

pytestmark = pytest.mark.skip(reason="standard compass mode removed 2026-10-21: GPS/FIT + IMU reconstruction is the only mode")


@pytest.mark.parametrize("source", ["fit", "gpmf", "gpx", "auto"])
def test_amd_selected_source_per_frame_and_disk_parity(source, tmp_path):
    base = datetime(2026, 10, 20)
    moving = [(base, 350.0), (base + timedelta(seconds=2), 20.0)]
    constant = [(base, 90.0)]
    layout = {"indicators": {"compass": {"enabled": True, "source": source}}}
    fields = {"heading_samples": constant, "gpx_heading_samples": constant}
    fit = {"heading": moving}
    if source == "gpmf":
        fields["heading_samples"] = moving
    elif source == "gpx":
        fields["gpx_heading_samples"] = moving
    samples = _amd_compass_samples(layout, fields, fit)
    cache = RenderPreparationService.build_telemetry_cache_vectorized(
        layout=layout, base_dt=base, start_dt_utc=base, total_frames=61,
        target_fps=30, fit_data=fit, field_samples=fields,
        compass_heading_samples=samples,
    )
    expected = [interpolate_heading(moving, base + timedelta(seconds=i/30)) for i in range(61)]
    assert [cache.lookup(i)["extra_indicators"]["compass"][0] for i in range(61)] == pytest.approx(expected, abs=2e-5)
    cache.save(tmp_path)
    loaded = RenderTelemetryCache.load(tmp_path / "manifest.json")
    assert [loaded.lookup(i)["extra_indicators"]["compass"][0] for i in range(61)] == pytest.approx(expected, abs=2e-5)


def test_missing_selected_source_does_not_use_previous_project_or_distance():
    base = datetime(2026, 10, 20)
    layout = {"indicators": {"compass": {"enabled": True, "source": "gpmf"}}}
    init_worker(640, 360, "", layout, {"heading_samples": [(base, 123.0)]})
    for explicit in ({"field_samples": {}}, {"compass_heading_samples": []}):
        cache = RenderPreparationService.build_telemetry_cache_vectorized(
            layout=layout, base_dt=base, total_frames=3, target_fps=1,
            fit_data={"heading": [(base, 270.0)]}, track_samples=[(base, 1234.0)],
            **explicit,
        )
        assert [cache.lookup(i)["extra_indicators"]["compass"][0] for i in range(3)] == [None]*3


def test_gpmf_initial_gps_gap_transitions_to_live_heading_like_preview():
    """GX010380 timing: the first valid course is 79.316870 s into the clip."""
    from src.gui.telemetry_manager import TelemetryDataManager

    base = datetime(2026, 10, 16, 4, 22, 16, 182130)
    samples = [(base + timedelta(seconds=30.91787), None),
               (base + timedelta(seconds=79.31687), 113.3695),
               (base + timedelta(seconds=80.31687), 90.0),
               (base + timedelta(seconds=105), 60.0)]
    layout = {"indicators": {"compass": {"source": "gpmf", "enabled": True}}}
    tm = TelemetryDataManager()
    tm.heading_samples = samples
    cache = RenderPreparationService.build_telemetry_cache_vectorized(
        layout=layout, base_dt=base + timedelta(seconds=75),
        start_dt_utc=base + timedelta(seconds=75), total_frames=900, target_fps=30000/1001,
        field_samples={"heading_samples": samples},
    )
    values = []
    for i in range(900):
        frame = cache.lookup(i)
        preview = tm.resolve_value("heading", frame["target_dt"], source="gpmf")
        final = frame["extra_indicators"]["compass"][0]
        if preview is None:
            assert final is None
        else:
            assert final == pytest.approx(preview, abs=2e-5)
        values.append(final)
    assert next(i for i, value in enumerate(values) if value is not None) == 130
    assert values[130] != values[899]
