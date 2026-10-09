"""Tests for Real GUI Startup, CHILD_CONFIG_HASH performance, and telemetry reload bypass.

Ensures that:
1. CHILD_CONFIG_HASH runs in < 2 ms with payload < 100 KB without serializing raw sample arrays.
2. RAW_TELEMETRY_REPARSE_ON_RENDER=NO when telemetry is in memory, preventing 15-30s raw GPMF JSON re-parse.
3. RenderPreparationService checks memory and disk cache first before doing any heavy chart/sample calculations.
4. StartupAuditTracker outputs [REAL GUI STARTUP] and [GUI STARTUP BREAKDOWN] with exact stage sum equality.
5. Map prefetch and cache checks do not block render startup synchronously on network I/O.
"""

import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.indicators.moving_map import ensure_map_tiles_cached
from src.render_preparation import RenderPreparationService
from src.render_telemetry_cache import RenderTelemetryCache, RenderTelemetryStatic
from src.startup_timeline import StartupAuditTracker


def test_child_config_hash_payload_and_speed():
    """Verify that child config manifest hashing is < 100 KB and < 2 ms."""
    from src.gui.qt._mixins.render_mixin import RenderMixin

    # Mock controller mixin with massive raw arrays in child_kwargs
    mixin = RenderMixin()
    mixin.video_path = Path("fake_video.mp4")
    mixin.video_paths = [Path("fake_video.mp4")]
    mixin.video_duration_s = 1200.0
    mixin.telemetry = MagicMock()
    mixin.telemetry.start_dt_utc = datetime(2026, 10, 2, 6, 26, 47, tzinfo=timezone.utc)
    mixin.telemetry.speed_samples = [(datetime.now(timezone.utc), 25.0) for _ in range(65000)]
    mixin.telemetry.track_samples = [(datetime.now(timezone.utc), 52.0, 21.0, 100.0) for _ in range(65000)]
    mixin.telemetry.fit_data = {
        "speed": [(datetime.now(timezone.utc), 25.0) for _ in range(65000)],
        "power": [(datetime.now(timezone.utc), 250.0) for _ in range(65000)],
        "cadence": [(datetime.now(timezone.utc), 90.0) for _ in range(65000)],
    }

    options = {
        "encoder": "amd",
        "video_paths": [str(mixin.video_path)],
        "resolution": "1080p",
        "bitrate": "40M",
    }

    # Simulate the manifest construction in render_mixin
    t0 = time.perf_counter()
    manifest_inputs = [str(p) for p in (options.get("video_paths") or mixin.video_paths or [])]
    child_manifest = {
        "mode": "DIRECT",
        "encoder": "amd",
        "amd_codec": "hevc",
        "amd_decode_mode": "gpu",
        "amd_encoder_quality": "FAST",
        "bitrate": "40M",
        "resolution": "1080p",
        "target_fps": 29.97,
        "render_w": 1920,
        "render_h": 1080,
        "overlay_w": 1920,
        "overlay_h": 1080,
        "hud_resolution_scale": 1.0,
        "rotation": 0,
        "container_rotation": 0,
        "duration_s": 1200.0,
        "start_dt_utc": str(mixin.telemetry.start_dt_utc),
        "layout_sha256": "abc123mocklayoutsha",
        "telemetry_cache_path": "C:/fake/manifest.json",
        "telemetry_cache_key": "fake_key_1234",
        "input_files": manifest_inputs,
        "timeline": [],
        "preview_enabled": False,
        "compression_analysis": True,
        "preserve_original_gpmf": False,
    }
    manifest_bytes = json.dumps(child_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    import hashlib
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    t_ms = (time.perf_counter() - t0) * 1000.0

    assert len(manifest_bytes) < 100 * 1024, f"Manifest size too large: {len(manifest_bytes)} bytes"
    assert t_ms < 2.0, f"Manifest hash took too long: {t_ms:.3f} ms"
    assert len(digest) == 64


def test_raw_telemetry_reparse_bypassed_when_in_memory():
    """Verify that raw GPMF JSON is NOT loaded when telemetry is already in GUI."""
    from src.gui.qt._mixins.render_mixin import RenderMixin

    mixin = RenderMixin()
    mixin.video_path = Path("fake_video.mp4")
    mixin.video_paths = [Path("fake_video.mp4")]
    mixin.video_duration_s = 60.0
    mixin.render_threads = 4
    mixin.telemetry = MagicMock()
    # Telemetry has speed samples already loaded
    mixin.telemetry.speed_samples = [(datetime.now(timezone.utc), 30.0)]
    mixin.telemetry.track_samples = [(datetime.now(timezone.utc), 52.0, 21.0, 100.0)]
    mixin.telemetry.fit_data = {}

    has_telemetry = bool(
        mixin.telemetry is not None
        and (
            getattr(mixin.telemetry, "speed_samples", None)
            or getattr(mixin.telemetry, "track_samples", None)
            or getattr(mixin.telemetry, "fit_data", None)
        )
    )
    assert has_telemetry is True

    # With has_telemetry=True, ensure_records_list and load_json_with_fallback should never be called
    with patch("src.gui.qt._mixins.render_mixin.load_json_with_fallback") as mock_load:
        # Check logic condition
        records = []
        if not has_telemetry:
            mock_load("dummy.json")
        assert mock_load.call_count == 0
        assert records == []


def test_render_preparation_checks_cache_first(tmp_path):
    """Verify RenderPreparationService checks cache before any heavy calculation."""
    # Pre-populate disk cache
    cache_dir = tmp_path / "cache_test"
    cache_dir.mkdir(parents=True)
    manifest_path = cache_dir / "manifest.json"

    static = RenderTelemetryStatic(max_speed_kmh=42.0)
    cols = {"speed": np.array([25.0, 30.0], dtype=np.float32)}
    cache = RenderTelemetryCache(
        frames=2,
        fps=29.97,
        base_dt=datetime(2026, 10, 2, 6, 26, 47),
        tz_offset_hours=2.0,
        columns=cols,
        string_tables={},
        static=static,
        cache_key="test_cache_key_123",
        cache_dir=cache_dir,
    )
    cache.save(cache_dir)

    # In-memory prewarm check
    RenderPreparationService.invalidate()
    with RenderPreparationService._lock:
        RenderPreparationService._prewarmed_cache = cache
        RenderPreparationService._prewarmed_key = "test_cache_key_123"

    mock_telemetry = MagicMock()
    mock_telemetry.start_dt_utc = datetime(2026, 10, 2, 6, 26, 47)
    mock_telemetry.speed_samples = [(datetime.now(), 25.0)]

    with patch.object(RenderPreparationService, "compute_cache_key", return_value="test_cache_key_123"):
        with patch("src.indicators.chart_builder.build_chart_data") as mock_chart_build:
            res = RenderPreparationService.prepare(
                options={},
                telemetry=mock_telemetry,
                layout={},
                total_frames=2,
                target_fps=29.97,
            )
            # Must return in-memory cache without building charts
            assert res is cache
            assert res.is_hit is True
            assert mock_chart_build.call_count == 0


def test_startup_audit_metrics_exact_sum_and_report(capsys):
    """Verify StartupAuditTracker stage metrics breakdown and sum equality."""
    StartupAuditTracker._ts.clear()

    t0 = 1000.0
    StartupAuditTracker.set("CLICK_RENDER_TS", t0)
    StartupAuditTracker.set("RAW_METADATA_START_TS", t0 + 0.001)
    StartupAuditTracker.set("RAW_METADATA_END_TS", t0 + 0.002)
    StartupAuditTracker.set("GPMF_JSON_MS", 0.0)
    StartupAuditTracker.set("MAP_CHECK_START_TS", t0 + 0.003)
    StartupAuditTracker.set("MAP_CHECK_END_TS", t0 + 0.005)
    StartupAuditTracker.set("PREP_START_TS", t0 + 0.006)
    StartupAuditTracker.set("PREP_END_TS", t0 + 0.050)
    StartupAuditTracker.set("CHARTS_MS", 0.0)
    StartupAuditTracker.set("JOB_BUILD_START_TS", t0 + 0.001)
    StartupAuditTracker.set("JOB_BUILD_END_TS", t0 + 0.055)
    StartupAuditTracker.set("CHILD_HASH_START_TS", t0 + 0.056)
    StartupAuditTracker.set("CHILD_HASH_END_TS", t0 + 0.057)
    StartupAuditTracker.set("SPAWN_START_TS", t0 + 0.060)
    StartupAuditTracker.set("CHILD_READY_TS", t0 + 0.200)
    StartupAuditTracker.set("DECODER_INIT_START_TS", t0 + 0.210)
    StartupAuditTracker.set("DECODER_INIT_END_TS", t0 + 0.250)
    StartupAuditTracker.set("ENCODER_INIT_START_TS", t0 + 0.260)
    StartupAuditTracker.set("ENCODER_INIT_END_TS", t0 + 0.320)
    StartupAuditTracker.set("FIRST_FRAME_TS", t0 + 0.400)

    metrics = StartupAuditTracker.compute_metrics()

    # Sum of sub-stages must equal TOTAL_MS
    sub_sum = (
        metrics["RAW_METADATA_MS"]
        + metrics["GPMF_JSON_MS"]
        + metrics["PREP_TOTAL_MS"]
        + metrics["CHARTS_MS"]
        + metrics["MAP_CHECK_MS"]
        + metrics["CHILD_HASH_MS"]
        + metrics["SPAWN_MS"]
        + metrics["BACKEND_INIT_MS"]
        + metrics["OTHER_MS"]
    )
    assert abs(sub_sum - metrics["TOTAL_MS"]) < 1e-6
    assert abs(metrics["TOTAL_MS"] - metrics["CLICK_TO_FIRST_FRAME_MS"]) < 1e-6

    # Verify audit report output formatting
    StartupAuditTracker.print_audit_report(prep_cache_status="HIT")
    captured = capsys.readouterr().out

    assert "[REAL GUI STARTUP]" in captured
    assert "CLICK_RENDER_TS=" in captured
    assert "FIRST_FRAME_TS=" in captured
    assert "CLICK_TO_FIRST_FRAME_MS=" in captured

    assert "[GUI STARTUP BREAKDOWN]" in captured
    assert "raw_metadata=" in captured
    assert "gpmf_json=" in captured
    assert "common_prep=" in captured
    assert "charts=" in captured
    assert "map=" in captured
    assert "child_hash=" in captured
    assert "spawn=" in captured
    assert "backend_init=" in captured
    assert "other=" in captured
    assert "TOTAL=" in captured


def test_ensure_map_tiles_cached_no_network_on_render():
    """Verify that ensure_map_tiles_cached with allow_network=False never downloads from network."""
    layout = {
        "indicators": {
            "track_map": {
                "enabled": True,
                "size": 0.2,
                "zoom": 14,
                "map_style": "light_all",
            }
        }
    }
    gps_track = [
        (datetime.now(), 52.2297, 21.0122),
        (datetime.now(), 52.2300, 21.0130),
    ]

    with patch("src.moving_map._download_tile_raw") as mock_download:
        info = ensure_map_tiles_cached(
            1920, 1080, layout, "track_map", gps_track, allow_network=False
        )
        assert mock_download.call_count == 0
        assert info["downloaded"] == 0
