from datetime import datetime, timezone

from src.telemetry_processed_cache import (
    PROCESSED_CACHE_VERSION,
    apply_processed_cache,
    processed_cache_path,
    read_processed_cache,
    write_processed_cache,
)


class _Telemetry:
    def __init__(self):
        dt = datetime(2026, 8, 5, 4, 55, 50, tzinfo=timezone.utc)
        self.speed_samples = [(dt, 12.5)]
        self.alt_samples = [(dt, 123.0)]
        self.track_samples = [(dt, 42.0)]
        self.iso_samples = [(dt, 100)]
        self.exposure_samples = [(dt, 0.01)]
        self.temperature_samples = [(dt, 30)]
        self.slope_samples = [(dt, 2.0)]
        self.accelerometer_samples = [(dt, (1.0, 2.0, 3.0))]
        self.gyroscope_samples = [(dt, (4.0, 5.0, 6.0))]
        self.gps_track = [(dt, 52.0, 21.0)]
        self.heading_samples = [(dt, 90.0)]
        self.start_dt_utc = dt

    def _set_vector_series(self, samples, prefix):
        setattr(self, f"{prefix}_x_samples", [(dt, v[0]) for dt, v in samples])
        setattr(self, f"{prefix}_y_samples", [(dt, v[1]) for dt, v in samples])
        setattr(self, f"{prefix}_z_samples", [(dt, v[2]) for dt, v in samples])
        setattr(self, f"{prefix}_magnitude_samples", [])


def test_processed_cache_round_trip_and_parity(tmp_path):
    source = tmp_path / "GX010099.MP4"
    source.write_bytes(b"source")
    original = _Telemetry()
    path = write_processed_cache(source, original)
    assert path == processed_cache_path(source)
    fields = read_processed_cache(source)
    assert fields is not None

    restored = _Telemetry()
    restored.speed_samples = []
    restored.gps_track = []
    apply_processed_cache(restored, fields)
    assert restored.speed_samples == original.speed_samples
    assert restored.gps_track == original.gps_track
    assert restored.accelerometer_samples == original.accelerometer_samples
    assert restored.start_dt_utc == original.start_dt_utc


def test_processed_cache_invalidates_on_source_change_and_version(tmp_path):
    source = tmp_path / "GX010099.MP4"
    source.write_bytes(b"source")
    write_processed_cache(source, _Telemetry())
    assert read_processed_cache(source) is not None
    source.write_bytes(b"changed")
    assert read_processed_cache(source) is None

    source.write_bytes(b"source")
    write_processed_cache(source, _Telemetry())
    import gzip
    import json
    path = processed_cache_path(source)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["_telem_processed_cache"]["version"] = PROCESSED_CACHE_VERSION - 1
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    assert read_processed_cache(source) is None
