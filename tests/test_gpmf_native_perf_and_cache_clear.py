"""Focused acceptance tests for native GPMF loading and generated-cache cleanup."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _native(**overrides):
    data = {
        "success": True,
        "gps_track": [],
        "accelerometer_samples": [(1.0, (1.0, 2.0, 3.0))],
        "gyroscope_samples": [(1.0, (4.0, 5.0, 6.0))],
        "iso_samples": [(1.0, 100.0)],
        "temperature_samples": [(1.0, 22.0)],
    }
    data.update(overrides)
    return data


def test_native_gpmf_accepts_imu_without_gps():
    from src.telemetry_native_gpmf import native_channels_used, native_result_usable

    data = _native()
    assert native_result_usable(data)
    assert "gps_track" not in native_channels_used(data)
    assert "accelerometer_samples" in native_channels_used(data)
    assert "gyroscope_samples" in native_channels_used(data)


def test_native_gpmf_partial_fallback_only_missing_channel():
    from src.telemetry_native_gpmf import merge_native_channel_data

    native_acc = [(1.0, (1.0, 2.0, 3.0))]
    fallback_acc = [(1.0, (99.0, 99.0, 99.0))]
    fallback_gyro = [(1.0, (4.0, 5.0, 6.0))]
    merged = merge_native_channel_data(
        _native(accelerometer_samples=native_acc, gyroscope_samples=[]),
        {"accelerometer_samples": fallback_acc, "gyroscope_samples": fallback_gyro},
    )
    assert merged["accelerometer_samples"] == native_acc
    assert merged["gyroscope_samples"] == fallback_gyro


def test_native_gpmf_acc_gyro_do_not_use_full_python_fallback(monkeypatch):
    import src.telemetry_extract as extract
    from src.telemetry_native_gpmf import extract_missing_gpmf_channels

    called = []
    monkeypatch.setattr(extract, "extract_gyroscope_samples", lambda records: called.append("gyro") or [(1.0, (1, 2, 3))])
    monkeypatch.setattr(extract, "extract_accelerometer_samples", lambda records: called.append("acc") or pytest.fail("ACC fallback was invoked"))
    result = extract_missing_gpmf_channels([{}], ("gyroscope_samples",))
    assert result["gyroscope_samples"]
    assert called == ["gyro"]


def test_gpmf_second_load_uses_cache():
    import src.gui.qt._mixins.project_mixin as project_mixin
    import src.telemetry_cache_manager as cache_manager
    from src.gui.qt._mixins.project_mixin import ProjectMixin

    source = Path("Video/GX020079.MP4")
    cached = {"gps_track": [], "accelerometer_samples": [(1.0, (1, 2, 3))]}
    class _Signal:
        def emit(self, *_args):
            pass
    dummy = SimpleNamespace(signals=SimpleNamespace(sig_progress=_Signal()))
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(cache_manager, "get_gpmf_json_path", lambda _source: Path("cache.json"))
        monkeypatch.setattr(project_mixin, "read_processed_cache", lambda _source: cached)
        monkeypatch.setattr(project_mixin, "processed_cache_path", lambda _source: Path("telemetry.npz"))
        monkeypatch.setattr(project_mixin, "_load_valid_gpmf_cache", lambda *_args: (None, "cache_not_needed"))
        monkeypatch.setattr(project_mixin, "_profile_load_stage", lambda *_args: None)
        fields, records = ProjectMixin._load_single_clip_telemetry(dummy, source)
        assert fields is cached
        assert records == []
    finally:
        monkeypatch.undo()


def test_invalid_cache_schema_rebuilds(tmp_path, monkeypatch):
    import src.telemetry_cache_manager as cache_manager
    from src.gui.qt._mixins.project_mixin import _load_valid_gpmf_cache

    source = tmp_path / "clip.MP4"
    source.write_bytes(b"source")
    cache_root = tmp_path / "central"
    cache_path = cache_root / "gpmf.json"
    meta_path = cache_root / "gpmf.meta.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({"ACCL": "data"}), encoding="utf-8")
    meta_path.write_text(json.dumps({"_telem_cache": {
        "version": 4,
        "source_file": str(source),
        "source_size": source.stat().st_size,
        "source_mtime_ns": source.stat().st_mtime_ns,
        "generator": "native",
    }}), encoding="utf-8")
    monkeypatch.setattr(cache_manager, "get_gpmf_json_path", lambda _source: cache_path)
    monkeypatch.setattr(cache_manager, "get_gpmf_metadata_path", lambda _source: meta_path)
    data, reason = _load_valid_gpmf_cache(source)
    assert data is None
    assert reason == "cache_version_mismatch"


def test_cache_cleanup_removes_telemetry_cache(tmp_path, monkeypatch):
    import src.telemetry_cache_manager as cache_manager

    root = tmp_path / "cache"
    media = root / "media" / "source_key"
    media.mkdir(parents=True)
    (media / "telemetry.npz").write_bytes(b"1234")
    monkeypatch.setattr(cache_manager, "get_cache_root", lambda: root)
    result = cache_manager.clear_generated_cache()
    assert result["files_removed"] == 1
    assert result["bytes_removed"] == 4
    assert not media.exists()


def test_cache_cleanup_preserves_user_files(tmp_path, monkeypatch):
    import src.telemetry_cache_manager as cache_manager

    root = tmp_path / "cache"
    (root / "media" / "source_key").mkdir(parents=True)
    (root / "user_notes.json").write_text("keep", encoding="utf-8")
    source = tmp_path / "ride.MP4"
    source.write_bytes(b"keep source")
    monkeypatch.setattr(cache_manager, "get_cache_root", lambda: root)
    cache_manager.clear_generated_cache()
    assert (root / "user_notes.json").read_text(encoding="utf-8") == "keep"
    assert source.read_bytes() == b"keep source"


def test_cache_cleanup_preserves_gpu_capabilities(tmp_path, monkeypatch):
    import src.telemetry_cache_manager as cache_manager

    appdata = tmp_path / "BikeRideHUD"
    root = appdata / "cache"
    (root / "media" / "source_key").mkdir(parents=True)
    capabilities = appdata / "gpu_capabilities.json"
    capabilities.write_text('{"amd": true}', encoding="utf-8")
    monkeypatch.setattr(cache_manager, "get_cache_root", lambda: root)
    cache_manager.clear_generated_cache()
    assert capabilities.read_text(encoding="utf-8") == '{"amd": true}'


def test_cache_button_disabled_during_active_job():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from src.gui.qt.tabs.settings_tab import SettingsTab

    app = QApplication.instance() or QApplication([])
    tab = SettingsTab()
    tab._on_render_state(SimpleNamespace(state="running"))
    assert not tab.btn_clear_cache.isEnabled()
    tab._on_render_state(SimpleNamespace(state="completed"))
    assert tab.btn_clear_cache.isEnabled()
    tab.deleteLater()
    app.processEvents()
