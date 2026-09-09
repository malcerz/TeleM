from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from PIL import Image

from src.ffmpeg import worker_cache
from src.ffmpeg.frame_renderer import render_overlay_frame
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import interpolate_gpmf_step


BASE = datetime(2026, 9, 2, 4, 0, tzinfo=timezone.utc)


def _scalar(start_s: float, values: list[float]):
    return [(BASE + timedelta(seconds=start_s + i), value) for i, value in enumerate(values)]


def _manager_with_synthetic_streams() -> TelemetryDataManager:
    manager = TelemetryDataManager()
    manager.iso_samples = _scalar(5.0, [100, 200])
    manager.exposure_samples = _scalar(5.0, [1, 2])
    manager.temperature_samples = _scalar(10.0, [20, 21])
    accel = [(BASE + timedelta(seconds=15 + i), (0.0, 0.0, -9.8)) for i in range(2)]
    gyro = [(BASE + timedelta(seconds=15 + i), (0.0, 0.0, 0.0)) for i in range(2)]
    manager.accelerometer_samples = accel
    manager.gyroscope_samples = gyro
    manager._set_vector_series(accel, "accel")
    manager._set_vector_series(gyro, "gyro")
    return manager


def test_controlled_per_stream_availability_and_last_hold():
    manager = _manager_with_synthetic_streams()
    at = lambda seconds: BASE + timedelta(seconds=seconds)

    # Before the first real sample, every dynamic stream is unavailable.
    assert manager.resolve_value("iso", at(0), source="gpmf") is None
    assert manager.resolve_value("exposure", at(0), source="gpmf") is None
    assert manager.resolve_value("temperature", at(6), source="gpmf") is None
    assert manager.resolve_value("lean_roll_x", at(6), source="gpmf") is None

    # Each stream starts independently; GPS is not involved in this contract.
    assert manager.resolve_value("iso", at(5.5), source="gpmf") == 100
    assert manager.resolve_value("temperature", at(11), source="gpmf") == 21
    assert manager.resolve_value("lean_roll_x", at(16), source="gpmf") is not None

    # Existing endpoint hold remains unchanged after the final sample.
    assert manager.resolve_value("iso", at(99), source="gpmf") == 200
    assert manager.resolve_value("temperature", at(99), source="gpmf") == 21


def test_preview_and_final_worker_share_gpmf_boundary_semantics():
    manager = _manager_with_synthetic_streams()
    fields = {
        "iso_samples": manager.iso_samples,
        "exposure_samples": manager.exposure_samples,
        "temperature_samples": manager.temperature_samples,
        "accel_x_samples": manager.accel_x_samples,
        "accel_y_samples": manager.accel_y_samples,
        "accel_z_samples": manager.accel_z_samples,
        "gyro_x_samples": manager.gyro_x_samples,
        "gyro_y_samples": manager.gyro_y_samples,
        "gyro_z_samples": manager.gyro_z_samples,
    }
    worker_cache.init_worker(1920, 1080, "Arial", {"indicators": {}}, fields)

    for seconds in (0, 6, 11, 16):
        target = BASE + timedelta(seconds=seconds)
        for field in ("iso", "temperature"):
            preview_value = manager.resolve_value(field, target, source="gpmf")
            final_value = worker_cache._resolve_cache_value(field, "gpmf", target)
            assert final_value == preview_value
        preview_lean = manager.resolve_value("lean_roll_x", target, source="gpmf")
        final_lean = worker_cache._resolve_cache_value("lean_roll_x", "gpmf", target)
        assert (final_lean is None) == (preview_lean is None)


def test_gpmf_step_never_backfills_future_sample():
    samples = _scalar(5.0, [10, 20])
    assert interpolate_gpmf_step(samples, BASE + timedelta(seconds=4.999)) is None
    assert interpolate_gpmf_step(samples, BASE + timedelta(seconds=5.0)) == 10
    assert interpolate_gpmf_step(samples, BASE + timedelta(seconds=99)) == 20


def test_final_frame_renderer_honours_first_sample_boundary():
    iso = _scalar(5.0, [100, 200])
    exposure = _scalar(5.0, [1, 2])
    temperature = _scalar(10.0, [20, 21])
    fields = {"indicators": {}}
    worker_cache.init_worker(
        320, 180, "Arial", fields, {}, start_dt_utc=BASE,
        target_fps=1.0, total_overlay_frames=20,
        iso_samples=iso, exposure_samples=exposure,
        temperature_samples=temperature,
    )
    captured = []

    def fake_compose(*args, **kwargs):
        # Positional contract: iso/exposure/temp are args 12/13/14.
        captured.append((args[12], args[13], args[14]))
        return Image.new("RGBA", (320, 180), (0, 0, 0, 0))

    with patch("src.ffmpeg.frame_renderer.compose_overlay", side_effect=fake_compose):
        for frame_index in (0, 6, 11, 16):
            render_overlay_frame(frame_index, BASE, 0.0, [], [], [], 1.0)

    assert captured == [
        (None, None, None),
        (200, 2, None),
        (200, 2, 21),
        (200, 2, 21),
    ]
