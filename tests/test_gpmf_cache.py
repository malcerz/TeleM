"""Regression tests for the GPMF JSON cache contract."""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.gui.qt._mixins.project_mixin import (
    GPMF_CACHE_VERSION,
    ProjectMixin,
    _gpmf_cache_metadata_path,
    _load_valid_gpmf_cache,
    _write_gpmf_cache,
)


def test_legacy_cache_is_invalid_and_reopen_is_hit(tmp_path, monkeypatch) -> None:
    source = tmp_path / "GX020079.mp4"
    cache = source.with_suffix(".json")
    source.write_bytes(b"mp4")
    cache.write_text(
        json.dumps({"Doc1:GPSDateTime": "2026:08:05 04:28:04.000"}),
        encoding="utf-8",
    )

    data, reason = _load_valid_gpmf_cache(source, cache)
    assert data is None
    assert reason == "legacy_cache_no_version"

    calls = {"count": 0}

    def fake_extract(*_args):
        calls["count"] += 1
        return [{
            "Doc1:GPSDateTime": "2026:08:05 04:55:50.800",
            "Doc378:GPSDateTime": "2026:08:05 04:56:28.500",
        }]

    class Signal:
        def emit(self, *_args):
            pass

    class Signals:
        sig_progress = Signal()

    class Telemetry:
        def __init__(self):
            self.records = []
            self.start_dt_utc = None

        def load_gpmf_from_exiftool(self, *_args, **_kwargs):
            pass

        def load_gpmf_records(self, records):
            self.records = records

        def load_gps_track(self, *_args):
            pass

    app = ProjectMixin()
    app.video_path = source
    app.video_paths = [source]
    app.ffmpeg_exe = "ffmpeg"
    app.ffprobe_exe = "ffprobe"
    app.base_dir = tmp_path
    app.exiftool_path = "exiftool"
    app.signals = Signals()
    app.telemetry = Telemetry()

    monkeypatch.setattr(
        "src.gui.qt._mixins.project_mixin._GPMF_AVAILABLE", True,
    )
    monkeypatch.setattr(
        "src.gui.qt._mixins.project_mixin.gpmf_to_exiftool_json",
        fake_extract,
    )

    app._load_or_generate_telemetry()
    assert calls["count"] == 1
    assert _gpmf_cache_metadata_path(cache).exists()

    app._load_or_generate_telemetry()
    assert calls["count"] == 1
    assert app.telemetry.records[0]["Doc1:GPSDateTime"].endswith("50.800")


def test_cache_fingerprint_and_version_invalidate(tmp_path) -> None:
    source = tmp_path / "video.mp4"
    cache = source.with_suffix(".json")
    source.write_bytes(b"source")
    _write_gpmf_cache(cache, source, {"Doc1:GPSDateTime": "ok"}, "gpmf")

    data, reason = _load_valid_gpmf_cache(source, cache)
    assert data is not None
    assert reason is None

    source.write_bytes(b"source changed")
    data, reason = _load_valid_gpmf_cache(source, cache)
    assert data is None
    assert reason == "source_size_changed"

    source.write_bytes(b"source")
    metadata_path = _gpmf_cache_metadata_path(cache)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["_telem_cache"]["version"] = GPMF_CACHE_VERSION - 1
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    data, reason = _load_valid_gpmf_cache(source, cache)
    assert data is None
    assert reason == "cache_version_mismatch"


def test_cache_mtime_and_corrupted_json_invalidate(tmp_path) -> None:
    source = tmp_path / "video.mp4"
    cache = source.with_suffix(".json")
    source.write_bytes(b"source")
    _write_gpmf_cache(cache, source, {"Doc1:GPSDateTime": "ok"}, "gpmf")

    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    data, reason = _load_valid_gpmf_cache(source, cache)
    assert data is None
    assert reason == "source_mtime_changed"

    _write_gpmf_cache(cache, source, {"Doc1:GPSDateTime": "ok"}, "gpmf")
    cache.write_text("{broken", encoding="utf-8")
    data, reason = _load_valid_gpmf_cache(source, cache)
    assert data is None
    assert reason == "invalid_json"
