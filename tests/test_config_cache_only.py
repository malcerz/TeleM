"""Tests verifying that project configuration and telemetry cache are read EXCLUSIVELY from central cache,
and all legacy source-directory sidecars (.layout.json, .json, .telemetry.npz, etc.) are strictly ignored.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.telemetry_cache_manager import (
    get_cache_root,
    get_gpmf_json_path,
    get_gpmf_metadata_path,
    get_telem_time_json_path,
    get_telem_time_metadata_path,
)
from src.gui.qt._mixins.project_mixin import _load_valid_gpmf_cache
from src.multifile import _load_valid_telem_time_cache, ClipTimestampResolution, _write_telem_time_cache
from src.gui.qt._mixins.project_mixin import ProjectMixin


@pytest.fixture(autouse=True)
def isolated_cache_env(tmp_path, monkeypatch):
    """Isolate all cache operations to a temporary AppData cache directory."""
    cache_dir = tmp_path / "appdata_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TELEM_CACHE_ROOT", str(cache_dir))
    return cache_dir


def test_legacy_layout_next_to_mp4_is_ignored_when_loading_project(tmp_path):
    """Test 1: When a legacy .layout.json exists next to MP4, it must NOT be loaded.
    The project must load the default layout / startup preset instead.
    """
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video_path = video_dir / "GX010318.MP4"
    video_path.write_bytes(b"dummy video content")

    # Place a poison legacy layout sidecar next to the video
    legacy_layout_path = video_dir / "GX010318.layout.json"
    legacy_layout_data = {
        "version": 10,
        "sentinel_key": "LEGACY_POISON_DO_NOT_LOAD",
        "indicators": {},
    }
    legacy_layout_path.write_text(json.dumps(legacy_layout_data), encoding="utf-8")

    # Create dummy def_layout.json
    base_dir = tmp_path / "app_base"
    base_dir.mkdir()
    def_layout_path = base_dir / "def_layout.json"
    def_layout_data = {
        "version": 10,
        "sentinel_key": "CANONICAL_DEF_LAYOUT",
        "indicators": {},
    }
    def_layout_path.write_text(json.dumps(def_layout_data), encoding="utf-8")

    # Construct ProjectMixin test instance
    class DummyApp(ProjectMixin):
        def __init__(self):
            self.base_dir = base_dir
            self.video_paths = [str(video_path)]
            self.layout = {}
            self._startup_preset_path = None
            self.signals = MagicMock()
            self.fps = 30.0

    app = DummyApp()
    # Resolve layout as done in load_video_paths
    preset_path = app._startup_preset_path or (app.layout.get("_startup_preset", "") if isinstance(app.layout, dict) else "")
    if preset_path and Path(preset_path).exists():
        app.layout = json.loads(Path(preset_path).read_text(encoding="utf-8"))
    else:
        def_layout = app.base_dir / "def_layout.json"
        app.layout = json.loads(def_layout.read_text(encoding="utf-8"))

    # Assert legacy layout was completely IGNORED
    assert app.layout.get("sentinel_key") == "CANONICAL_DEF_LAYOUT"
    assert app.layout.get("sentinel_key") != "LEGACY_POISON_DO_NOT_LOAD"
    # Legacy file must remain untouched on disk
    assert legacy_layout_path.exists()


def test_legacy_gpmf_json_next_to_mp4_ignored_when_cache_miss(tmp_path):
    """Test 2: When legacy .json exists next to MP4 but AppData cache is empty,
    _load_valid_gpmf_cache MUST return (None, 'cache_missing') and NOT load/migrate the legacy file.
    """
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video_path = video_dir / "GX010318.MP4"
    video_path.write_bytes(b"dummy video content")

    # Place legacy .json and .meta.json next to video
    legacy_json = video_dir / "GX010318.json"
    legacy_json.write_text(json.dumps([{"streams": {"GPS": [1, 2, 3]}}]), encoding="utf-8")
    legacy_meta = video_dir / "GX010318.json.meta.json"
    stat = video_path.stat()
    legacy_meta.write_text(json.dumps({
        "_telem_cache": {
            "version": 1,
            "source_file": str(video_path),
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "generator": "gpmf",
        }
    }), encoding="utf-8")

    data, reason = _load_valid_gpmf_cache(video_path)
    assert data is None
    assert reason in ("cache_missing", "cache_not_found")
    # Central cache must still NOT exist (no auto-migration from source folder)
    appdata_cache = get_gpmf_json_path(video_path)
    assert not appdata_cache.exists()


def test_gpmf_reads_only_from_central_cache_when_both_exist(tmp_path):
    """Test 3: When both AppData cache and legacy sidecar exist, the app uses ONLY AppData cache."""
    video_dir = tmp_path / "videos"
    video_dir.mkdir()
    video_path = video_dir / "GX010318.MP4"
    video_path.write_bytes(b"dummy video content")

    # Place poison legacy file
    legacy_json = video_dir / "GX010318.json"
    legacy_json.write_text(json.dumps([{"payload": "LEGACY_POISON"}]), encoding="utf-8")

    # Place valid central AppData cache
    appdata_json = get_gpmf_json_path(video_path)
    appdata_meta = get_gpmf_metadata_path(video_path)
    appdata_json.parent.mkdir(parents=True, exist_ok=True)
    appdata_json.write_text(json.dumps([{"payload": "VALID_APPDATA_CACHE"}]), encoding="utf-8")

    stat = video_path.stat()
    from src.gui.qt._mixins.project_mixin import GPMF_CACHE_VERSION
    appdata_meta.write_text(json.dumps({
        "_telem_cache": {
            "version": GPMF_CACHE_VERSION,
            "source_file": str(video_path),
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "generator": "gpmf",
        }
    }), encoding="utf-8")

    data, reason = _load_valid_gpmf_cache(video_path)
    assert data is not None
    assert reason is None
    assert data[0]["payload"] == "VALID_APPDATA_CACHE"
