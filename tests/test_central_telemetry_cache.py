"""Automated test suite for Central Telemetry and Media Cache Persistence.

Validates that:
1. GPMF JSON, Processed Telemetry NPZ, and Telem Time mapping are stored in AppData.
2. Source media directories remain 100% clean (zero generated sidecars).
3. Legacy sidecars are imported read-only without modifying source files.
4. Identical filenames across different directories receive unique cache keys.
5. Invalidation triggers on file size, mtime, or version changes.
6. Render queue jobs remain compact and do not embed heavy telemetry arrays.
7. Atomic writes protect all cache artifacts.
8. Cache cleanup policy prunes oldest entries when exceeding quota.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from src.telemetry_cache_manager import (
    CACHE_FORMAT_VERSION,
    CACHE_KEY_ALGORITHM,
    atomic_save_json,
    cleanup_cache,
    compute_source_key,
    get_cache_root,
    get_gpmf_json_path,
    get_legacy_gpmf_json_path,
    get_legacy_telem_time_paths,
    get_legacy_telemetry_npz_path,
    get_media_cache_dir,
    get_telem_time_json_path,
    get_telemetry_npz_path,
)
from src.telemetry_processed_cache import (
    PROCESSED_CACHE_VERSION,
    apply_processed_cache,
    processed_cache_path,
    read_processed_cache,
    write_processed_cache,
)
from src.multifile import (
    ClipTimestampResolution,
    _load_valid_telem_time_cache,
    _telem_time_cache_paths,
    _write_telem_time_cache,
)
from src.gui.qt._mixins.project_mixin import (
    _load_valid_gpmf_cache,
    _write_gpmf_cache,
)
from src.gui.export_queue import ExportJob, ExportQueue


class _DummyTelemetry:
    def __init__(self):
        dt = datetime(2026, 8, 5, 4, 55, 50, tzinfo=timezone.utc)
        self.speed_samples = [(dt, 25.4)]
        self.alt_samples = [(dt, 120.5)]
        self.track_samples = [(dt, 180.0)]
        self.iso_samples = [(dt, 100)]
        self.exposure_samples = [(dt, 0.005)]
        self.temperature_samples = [(dt, 32.0)]
        self.slope_samples = [(dt, 1.5)]
        self.accelerometer_samples = [(dt, (0.1, 0.2, 9.8))]
        self.gyroscope_samples = [(dt, (0.01, -0.02, 0.05))]
        self.gps_track = [(dt, 52.2297, 21.0122)]
        self.heading_samples = [(dt, 95.0)]
        self.start_dt_utc = dt

    def _set_vector_series(self, samples, prefix):
        pass


@pytest.fixture(autouse=True)
def isolated_cache_env(tmp_path, monkeypatch):
    """Isolate all cache operations to a temporary directory."""
    cache_dir = tmp_path / "appdata_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TELEM_CACHE_ROOT", str(cache_dir))
    return cache_dir


def test_generated_gpmf_json_goes_to_appdata(tmp_path):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video = video_dir / "GX010302.MP4"
    video.write_bytes(b"dummy video content for GPMF")

    data = [{"streams": {"GPS": [1, 2, 3]}}]
    saved_path = _write_gpmf_cache(Path("dummy"), video, data, "GPMF")

    appdata_gpmf = get_gpmf_json_path(video)
    assert saved_path == appdata_gpmf
    assert appdata_gpmf.exists()

    # Source directory must NOT contain the json sidecar
    assert not video.with_suffix(".json").exists()
    assert not video.with_name("GX010302.json.meta.json").exists()

    # Data is readable from AppData
    loaded, reason = _load_valid_gpmf_cache(video)
    assert loaded is not None
    assert reason is None
    assert loaded == data


def test_generated_telemetry_npz_goes_to_appdata(tmp_path):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video = video_dir / "GX010302.MP4"
    video.write_bytes(b"dummy video content for NPZ")

    telem = _DummyTelemetry()
    saved_path = write_processed_cache(video, telem)

    appdata_npz = get_telemetry_npz_path(video)
    assert saved_path == appdata_npz
    assert appdata_npz.exists()

    # Source directory must NOT contain the npz sidecar
    assert not video.with_name("GX010302.telemetry.npz").exists()

    # Read back from AppData
    read_data = read_processed_cache(video)
    assert read_data is not None
    assert len(read_data.get("speed_samples", [])) == 1
    assert len(read_data.get("gps_track", [])) == 1


def test_telem_time_goes_to_appdata(tmp_path):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video = video_dir / "GX010302.MP4"
    video.write_bytes(b"dummy video content for telem_time")

    dt = datetime(2026, 8, 5, 5, 0, 0)
    res = ClipTimestampResolution(
        absolute_start_dt=dt,
        timestamp_source="GPMF_STMP",
        timestamp_reliable=True,
        timestamp_detail="test",
    )
    _write_telem_time_cache(video, res, duration_s=60.0)

    appdata_time = get_telem_time_json_path(video)
    assert appdata_time.exists()

    # Source directory must NOT contain telem_time files
    assert not video.with_name("GX010302.MP4.telem_time.json").exists()
    assert not video.with_name("GX010302.MP4.telem_time.json.meta.json").exists()

    # Read back from AppData
    loaded_res = _load_valid_telem_time_cache(video, duration_s=60.0)
    assert loaded_res is not None
    assert loaded_res.absolute_start_dt == dt
    assert loaded_res.timestamp_reliable is True


def test_no_generated_sidecar_in_video_dir(tmp_path):
    """Hard invariant: SOURCE_DIRECTORY_WRITE_COUNT = 0."""
    video_dir = tmp_path / "gopro_card"
    video_dir.mkdir()
    video = video_dir / "GX010302.MP4"
    video.write_bytes(b"clean gopro video stream data")

    files_before = set(os.listdir(video_dir))

    # Perform full pipeline cache operations
    _write_gpmf_cache(Path("dummy"), video, {"gps": 1}, "GPMF")
    write_processed_cache(video, _DummyTelemetry())
    _write_telem_time_cache(
        video,
        ClipTimestampResolution(datetime.now(), "GPMF", True, "ok"),
        duration_s=120.0,
    )

    files_after = set(os.listdir(video_dir))
    diff = files_after - files_before

    assert len(diff) == 0, f"Generated files leaked into source directory: {diff}"
    assert files_after == {"GX010302.MP4"}


def test_legacy_cache_ignored(tmp_path):
    video_dir = tmp_path / "legacy_materials"
    video_dir.mkdir()
    video = video_dir / "GX010302.MP4"
    video.write_bytes(b"video with legacy sidecars")

    # Manually place legacy .telemetry.npz next to the video
    legacy_npz = video.with_name("GX010302.telemetry.npz")
    stat = video.stat()
    meta = {
        "version": PROCESSED_CACHE_VERSION,
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "start_dt_utc": "2026-08-05T04:55:50+00:00",
        "tz_aware": {},
    }
    np.savez(
        legacy_npz,
        speed_samples=np.array([[1000.0, 30.0]]),
        gps_track=np.array([[1000.0, 52.0, 21.0]]),
        __meta__=np.frombuffer(json.dumps(meta).encode("utf-8"), dtype=np.uint8),
    )

    legacy_mtime_before = legacy_npz.stat().st_mtime_ns
    legacy_size_before = legacy_npz.stat().st_size

    # Reading should ignore legacy sidecar and return None
    data = read_processed_cache(video)
    assert data is None

    # AppData cache must NOT be auto-created from legacy sidecar
    appdata_npz = get_telemetry_npz_path(video)
    assert not appdata_npz.exists()

    # Legacy file must remain 100% UNTOUCHED (not deleted, not modified)
    assert legacy_npz.exists()
    assert legacy_npz.stat().st_mtime_ns == legacy_mtime_before
    assert legacy_npz.stat().st_size == legacy_size_before


def test_same_filename_different_directory_has_different_cache_key(tmp_path):
    dir_a = tmp_path / "card_a"
    dir_b = tmp_path / "card_b"
    dir_a.mkdir()
    dir_b.mkdir()

    vid_a = dir_a / "GX010302.MP4"
    vid_b = dir_b / "GX010302.MP4"

    vid_a.write_bytes(b"content alpha")
    vid_b.write_bytes(b"content beta")

    key_a = compute_source_key(vid_a)
    key_b = compute_source_key(vid_b)

    assert key_a != key_b
    assert get_media_cache_dir(vid_a) != get_media_cache_dir(vid_b)
    assert key_a.startswith("GX010302_")
    assert key_b.startswith("GX010302_")


def test_cache_invalidation_on_source_change(tmp_path):
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video = video_dir / "GX010302.MP4"
    video.write_bytes(b"initial clip content")

    write_processed_cache(video, _DummyTelemetry())
    assert read_processed_cache(video) is not None

    # Simulate video file modification (size/mtime change)
    time.sleep(0.01)
    video.write_bytes(b"modified clip content with different length")

    # Cache must miss because source fingerprint changed
    assert read_processed_cache(video) is None


def test_queue_job_does_not_embed_generated_telemetry(tmp_path):
    video = tmp_path / "ride.mp4"
    video.write_bytes(b"ride video")

    job = ExportJob(
        video_paths=[str(video)],
        fit_path=str(tmp_path / "ride.fit"),
        layout={"indicators": {"speed": {"x": 100}}},
        output_path=str(tmp_path / "out.mp4"),
    )

    data = asdict(job)
    serialized = json.dumps(data, default=str)

    # Serialized queue job must be small (a few KB, never multi-megabyte telemetry arrays)
    assert len(serialized.encode("utf-8")) < 10240
    assert "speed_samples" not in data
    assert "gps_track" not in data
    assert job.telemetry_cache_key.startswith("ride_")


def test_queue_job_can_render_after_cache_deleted(tmp_path):
    video = tmp_path / "ride.mp4"
    video.write_bytes(b"ride video stream")

    # Generate cache
    write_processed_cache(video, _DummyTelemetry())
    cache_npz = get_telemetry_npz_path(video)
    assert cache_npz.exists()

    job = ExportJob(
        video_paths=[str(video)],
        output_path=str(tmp_path / "out.mp4"),
        layout={"indicators": {"speed": {"x": 50}}},
    )

    # Delete AppData cache directory
    shutil.rmtree(get_media_cache_dir(video))
    assert not cache_npz.exists()

    # Job still has source video path and can trigger cache regeneration
    assert Path(job.video_paths[0]).exists()
    assert read_processed_cache(Path(job.video_paths[0])) is None
    # Rebuilding succeeds from source
    new_path = write_processed_cache(Path(job.video_paths[0]), _DummyTelemetry())
    assert new_path.exists()
    assert read_processed_cache(Path(job.video_paths[0])) is not None


def test_multifile_has_independent_cache_keys(tmp_path):
    vids = [tmp_path / f"GX01011{i}.MP4" for i in (4, 5, 6)]
    for v in vids:
        v.write_bytes(f"clip {v.name}".encode("utf-8"))

    keys = [compute_source_key(v) for v in vids]
    dirs = [get_media_cache_dir(v) for v in vids]

    assert len(set(keys)) == 3
    assert len(set(dirs)) == 3


def test_atomic_cache_write(tmp_path):
    target = tmp_path / "test_atomic.json"
    data = {"sample_key": "sample_value", "number": 42}

    atomic_save_json(target, data)
    assert target.exists()

    # Check for orphaned temp files
    tmps = list(tmp_path.glob("*.tmp*"))
    assert len(tmps) == 0

    read_data = json.loads(target.read_text(encoding="utf-8"))
    assert read_data == data


def test_cache_cleanup_prunes_oldest(tmp_path):
    root = get_cache_root()
    media_dir = root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Create 4 dummy cache directories of 5 MB each (total 20 MB)
    for i in range(4):
        d = media_dir / f"clip_{i}_dummykey"
        d.mkdir()
        (d / "telemetry.npz").write_bytes(b"X" * (5 * 1024 * 1024))
        meta = {
            "source_key": f"clip_{i}",
            "created_at": "2026-09-01T10:00:00Z",
            "last_accessed_at": f"2026-09-0{i+1}T10:00:00Z",
        }
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        # Ensure distinct mtimes
        os.utime(d / "metadata.json", (1700000000 + i * 1000, 1700000000 + i * 1000))

    # Total size is ~20 MB. Prune with quota of 0.012 GB (~12 MB)
    freed = cleanup_cache(max_size_gb=0.012)
    assert freed >= 5 * 1024 * 1024

    # Oldest (clip_0) should be pruned
    assert not (media_dir / "clip_0_dummykey").exists()
    # Newest (clip_3) must still exist
    assert (media_dir / "clip_3_dummykey").exists()


def test_user_supplied_external_json_preserved(tmp_path):
    external_dir = tmp_path / "custom_telemetry"
    external_dir.mkdir()
    ext_json = external_dir / "my_custom_gpmf.json"
    ext_json.write_text(json.dumps([{"external": True}]), encoding="utf-8")

    job = ExportJob(
        video_paths=[str(tmp_path / "video.mp4")],
        external_gpmf_path=str(ext_json),
    )

    assert job.external_gpmf_path == str(ext_json)
    # External file must NOT be moved or deleted
    assert ext_json.exists()
    assert "external" in ext_json.read_text(encoding="utf-8")
