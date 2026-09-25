from dataclasses import dataclass
from datetime import datetime, timezone
import multiprocessing as mp
import pickle

import numpy as np

from src.telemetry_processed_cache import (
    PROCESSED_CACHE_VERSION,
    LazySampleList,
    apply_processed_cache,
    processed_cache_path,
    read_processed_cache,
    write_processed_cache,
)


@dataclass
class _SpawnJob:
    samples: LazySampleList


def _spawn_lazy_sample_consumer(job, result_queue):
    samples = job.samples
    state_before_access = samples._materialized
    values = list(samples)
    result_queue.put((state_before_access, samples._materialized, values))


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
    import json
    import numpy as np
    path = processed_cache_path(source)
    data = dict(np.load(path))
    meta = json.loads(data["__meta__"].tobytes().decode("utf-8"))
    meta["version"] = PROCESSED_CACHE_VERSION - 1
    data["__meta__"] = np.frombuffer(json.dumps(meta).encode("utf-8"), dtype=np.uint8)
    np.savez(path, **data)
    assert read_processed_cache(source) is None

    # Corrupted / invalid cache content returns None
    path.write_bytes(b"corrupted binary content")
    assert read_processed_cache(source) is None


def _vector_lazy(count=3, *, tz_aware=True):
    base = datetime(2026, 8, 5, 4, 55, 50, tzinfo=timezone.utc).timestamp()
    arr = np.array(
        [[base + i, i + 1.0, i + 2.0, i + 3.0] for i in range(count)],
        dtype=np.float64,
    ).reshape((count, 4))
    return LazySampleList(arr, is_vector=True, tz_aware=tz_aware)


def test_lazy_sample_list_pickle_preserves_lazy_and_materialized_contracts():
    lazy = _vector_lazy()
    payload = pickle.dumps(lazy, protocol=pickle.HIGHEST_PROTOCOL)
    assert lazy._materialized is False

    restored_lazy = pickle.loads(payload)
    assert restored_lazy._materialized is False
    assert restored_lazy._is_vector is True
    assert restored_lazy._tz_aware is True
    assert np.array_equal(restored_lazy._arr, lazy._arr)
    assert list(restored_lazy) == list(lazy)

    materialized = _vector_lazy()
    materialized.append((datetime(2026, 8, 5, tzinfo=timezone.utc), (9.0, 8.0, 7.0)))
    expected = list(materialized)
    restored_materialized = pickle.loads(pickle.dumps(materialized))
    assert restored_materialized._materialized is True
    assert restored_materialized._arr is None
    assert list(restored_materialized) == expected


def test_lazy_sample_list_pickle_empty_and_naive_timestamp_states():
    empty = _vector_lazy(0)
    restored_empty = pickle.loads(pickle.dumps(empty))
    assert restored_empty._materialized is False
    assert len(restored_empty) == 0
    assert list(restored_empty) == []

    naive = _vector_lazy(tz_aware=False)
    restored_naive = pickle.loads(pickle.dumps(naive))
    assert restored_naive._materialized is False
    assert all(sample[0].tzinfo is None for sample in restored_naive)


def test_lazy_sample_list_timestamp_sort_stays_array_backed():
    lazy = _vector_lazy()
    lazy._arr = lazy._arr[[2, 0, 1]]

    lazy.sort_by_timestamp()

    assert lazy._materialized is False
    assert np.all(np.diff(lazy._arr[:, 0]) >= 0.0)


def test_lazy_sample_list_all_mutators_operate_on_logical_values():
    first = list(_vector_lazy())
    extra = (datetime(2026, 8, 6, tzinfo=timezone.utc), (7.0, 8.0, 9.0))

    value = _vector_lazy()
    value.append(extra)
    assert list(value) == first + [extra]

    value = _vector_lazy()
    value.extend([extra])
    assert list(value) == first + [extra]

    value = _vector_lazy()
    value.insert(1, extra)
    assert list(value) == first[:1] + [extra] + first[1:]

    value = _vector_lazy()
    value[1] = extra
    assert value[1] == extra
    del value[1]
    assert list(value) == [first[0], first[2]]

    value = _vector_lazy()
    assert value.pop() == first[-1]
    value.remove(first[0])
    assert list(value) == [first[1]]
    value.clear()
    assert value == []

    value = _vector_lazy()
    value += [extra]
    assert list(value) == first + [extra]
    value *= 2
    assert list(value) == (first + [extra]) * 2
    value.reverse()
    assert list(value) == list(reversed((first + [extra]) * 2))


def test_lazy_sample_list_real_windows_spawn_round_trip():
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    process = ctx.Process(
        target=_spawn_lazy_sample_consumer,
        args=(_SpawnJob(_vector_lazy()), result_queue),
    )
    process.start()
    process.join(timeout=15.0)
    try:
        assert process.exitcode == 0
        state_before, state_after, values = result_queue.get(timeout=2.0)
        assert state_before is False
        assert state_after is True
        assert values == list(_vector_lazy())
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=2.0)
        result_queue.close()
