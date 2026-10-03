"""Tests for DJI worker process, GUI responsiveness, cancellation, and error handling."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import telemetry_dji
from src.gui.qt._mixins.project_mixin import ProjectMixin


def test_dji_worker_process_cold_and_warm_parity(tmp_path):
    """Verify worker produces identical results on cold miss and warm cache hit."""
    # Use real small file or mock
    real_small = Path("F:/DJI/DJI_20260928071657_0002_D.MP4")
    if not real_small.is_file():
        pytest.skip("Test file DJI_20260928071657_0002_D.MP4 not found")

    anchor = datetime(2026, 9, 28, 7, 16, 57, tzinfo=timezone.utc)

    # Clear cache
    cp = telemetry_dji._cache_path(real_small)
    if cp.exists():
        cp.unlink()
    telemetry_dji._cleanup_temp_cache(real_small)

    progress_events = []
    def on_progress(stage, elapsed, msg):
        progress_events.append((stage, elapsed, msg))

    # 1. Cold load (cache miss) via worker
    cold = telemetry_dji.load_dji_telemetry(
        real_small,
        anchor,
        progress_cb=on_progress,
        use_worker=True,
    )
    assert cold["cache_hit"] is False
    assert cold["camera"] == "DJI"
    assert cold["model"] == "OsmoAction6"
    assert len(progress_events) >= 1

    # 2. Warm load (cache hit)
    warm = telemetry_dji.load_dji_telemetry(
        real_small,
        anchor,
        progress_cb=on_progress,
        use_worker=True,
    )
    assert warm["cache_hit"] is True
    assert warm["camera"] == cold["camera"]
    assert warm["model"] == cold["model"]
    assert cold["gyroscope_samples"] == warm["gyroscope_samples"]
    assert cold["accelerometer_samples"] == warm["accelerometer_samples"]
    assert cold["quaternion_samples"] == warm["quaternion_samples"]
    assert cold["camera_metadata"] == warm["camera_metadata"]


def test_dji_worker_cancellation(tmp_path):
    """Verify worker cancellation terminates process and cleans temporary cache."""
    real_big = Path("F:/DJI/DJI_20260928064217_0001_D.MP4")
    if not real_big.is_file():
        pytest.skip("Test file DJI_20260928064217_0001_D.MP4 not found")

    cancel_event = threading.Event()
    anchor = datetime(2026, 9, 28, 6, 42, 17, tzinfo=timezone.utc)

    # Clear cache so we test actual worker cancellation on cold parse
    cp = telemetry_dji._cache_path(real_big)
    if cp.exists():
        cp.unlink()
    telemetry_dji._cleanup_temp_cache(real_big)

    # Cancel after worker has started
    def cancel_trigger():
        time.sleep(0.05)
        cancel_event.set()

    threading.Thread(target=cancel_trigger, daemon=True).start()

    with pytest.raises(RuntimeError, match="cancelled by user"):
        telemetry_dji.load_dji_telemetry(
            real_big,
            anchor,
            cancel_event=cancel_event,
            use_worker=True,
        )

    # Verify no .tmp.npz files remain
    parent = telemetry_dji._cache_path(real_big).parent
    if parent.is_dir():
        tmp_files = list(parent.glob("dji_imu_*.tmp.npz"))
        assert not tmp_files, f"Leftover temporary cache files found: {tmp_files}"


def test_dji_worker_error_handling(tmp_path):
    """Verify worker handles invalid file cleanly with non-zero exit code and no corrupt cache."""
    invalid_file = tmp_path / "nonexistent_dji.mp4"
    anchor = datetime(2026, 9, 28, 6, 42, 17, tzinfo=timezone.utc)

    with pytest.raises(RuntimeError, match="failed with exit code"):
        telemetry_dji.load_dji_telemetry(
            invalid_file,
            anchor,
            use_worker=True,
        )


def test_project_mixin_progress_label_dji_not_gpmf(monkeypatch, tmp_path):
    """Verify DJI clip emits 'Analiza DJI', never 'Analiza GPMF'."""
    emitted = []

    class MockSignals:
        class Signal:
            def emit(self, *args):
                emitted.append(args)
        sig_progress = Signal()

    harness = SimpleNamespace(
        signals=MockSignals(),
        ffprobe_exe="ffprobe",
        _load_cancel_event=threading.Event(),
    )

    fake_video = tmp_path / "clip_dji.mp4"
    fake_video.write_bytes(b"dummy")

    # Mock detect to return dji_djmd
    monkeypatch.setattr(telemetry_dji, "detect_camera_telemetry", lambda p, exe: "dji_djmd")

    # Mock ffprobe subprocess
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"format": {"tags": {"creation_time": "2026-09-28T06:42:17Z"}}})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())

    # Mock load_dji_telemetry to verify progress calls
    def fake_load(path, anchor, progress_cb=None, cancel_event=None, use_worker=None):
        if progress_cb:
            progress_cb("parser_init", 0.5, "odczyt telemetrii... 00:00")
            progress_cb("cache_write", 1.0, "zapis cache... 00:01")
        return {
            "gyroscope_samples": [],
            "accelerometer_samples": [],
            "quaternion_samples": [],
            "camera_metadata": {},
            "camera": "DJI",
            "model": "OsmoAction6",
            "cache_hit": False,
        }

    monkeypatch.setattr(telemetry_dji, "load_dji_telemetry", fake_load)

    fields, records = ProjectMixin._load_single_clip_telemetry(harness, fake_video, clip_idx=0, total_clips=1)
    assert fields["_dji"] is True
    assert records == []

    # Verify progress messages: must contain "Analiza DJI", must NOT contain "Analiza GPMF"
    dji_msgs = [args[1] for args in emitted if len(args) > 1 and "Analiza DJI" in str(args[1])]
    gpmf_msgs = [args[1] for args in emitted if len(args) > 1 and "Analiza GPMF" in str(args[1])]

    assert len(dji_msgs) >= 2, f"Expected Analiza DJI messages, got: {emitted}"
    assert len(gpmf_msgs) == 0, f"Found unexpected Analiza GPMF messages: {gpmf_msgs}"


def test_dji_error_does_not_fallback_to_gpmf(monkeypatch, tmp_path):
    """Verify that if DJI telemetry parsing fails, it does NOT fall back to GoPro GPMF."""
    fake_video = tmp_path / "corrupt_dji.mp4"
    fake_video.write_bytes(b"bad")

    harness = SimpleNamespace(
        signals=SimpleNamespace(sig_progress=SimpleNamespace(emit=lambda *a: None)),
        ffprobe_exe="ffprobe",
        _load_cancel_event=threading.Event(),
    )

    monkeypatch.setattr(telemetry_dji, "detect_camera_telemetry", lambda p, exe: "dji_djmd")

    # Mock ffprobe to throw or load_dji_telemetry to fail
    def failing_load(*a, **k):
        raise RuntimeError("DJI parser crashed")

    monkeypatch.setattr(telemetry_dji, "load_dji_telemetry", failing_load)

    # Mock creation_time extraction
    class FakeProc:
        returncode = 0
        stdout = json.dumps({"format": {"tags": {"creation_time": "2026-09-28T06:42:17Z"}}})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())

    # Must raise RuntimeError, must NOT continue to read_processed_cache / GPMF
    with pytest.raises(RuntimeError, match="DJI parser crashed"):
        ProjectMixin._load_single_clip_telemetry(harness, fake_video, clip_idx=0, total_clips=1)
