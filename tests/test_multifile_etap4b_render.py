"""ETAP MULTIFILE 4B — final rendering + telemetry timeline.

Testuje wspólny kontrakt czasu finalnego renderera (taki sam jak preview):

    frame -> global_time -> VideoTimeline -> clip/local -> absolute target_dt

oraz poprawność precompute (brak precomputu przerw absolutnych), cut przez
granicę, progress globalny, fallback timestampów i single-file regression.

TEST 1..12 z zadania.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.multifile import (
    TIMESTAMP_SOURCE_GPMF_GPS9,
    VideoClip,
    VideoTimeline,
    resolve_render_target_dt,
)
from src.telemetry_precompute import build_telemetry_cache


def _dt(hms: str) -> datetime:
    h, m, s = hms.split(":")
    return datetime(2026, 8, 23, int(h), int(m)) + timedelta(seconds=float(s))


def _clip(name: str, dur: float, start: datetime) -> VideoClip:
    return VideoClip(
        path=Path(f"C:/videos/{name}.MP4"),
        duration_s=dur,
        fps=30.0,
        width=1920,
        height=1080,
        absolute_start_dt=start,
        timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9,
        timestamp_reliable=True,
        timestamp_quality="exact",
    )


def _three_clip_timeline() -> VideoTimeline:
    """clip1 10:05-10:15, clip2 10:35-10:50, clip3 11:20-11:30 (global 0-35min)."""
    return VideoTimeline.from_clips([
        _clip("f1", 600.0, _dt("10:05:00")),
        _clip("f2", 900.0, _dt("10:35:00")),
        _clip("f3", 600.0, _dt("11:20:00")),
    ], base_dt=_dt("10:05:00"))


# ── TEST 1: frame -> absolute single-file ──────────────────────────────────

class TestFrameToAbsoluteSingleFile:
    def test_frame_50_at_10fps(self):
        tl = VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:00:00")),
        ], base_dt=_dt("10:00:00"))
        # frame 50 @ 10 fps -> global 5.0 -> start + 5.0
        assert tl.frame_to_absolute(50, 10.0) == _dt("10:00:05")
        assert tl.frame_to_absolute(50, 10.0) == _dt("10:00:00") + timedelta(seconds=5.0)


# ── TEST 2 / 3: granica ────────────────────────────────────────────────────

class TestBoundary:
    def _timeline(self) -> VideoTimeline:
        return VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:05:00")),
            _clip("b", 900.0, _dt("10:35:00")),
        ], base_dt=_dt("10:05:00"))

    def test_frame_before_boundary(self):
        tl = self._timeline()
        # global 599.9 -> abs ~10:14:59.9
        dt = tl.global_to_absolute(599.9)
        assert dt == _dt("10:14:59.9")

    def test_first_frame_clip2_is_real_time(self):
        tl = self._timeline()
        # global 600 -> abs 10:35 (NOT 10:15)
        assert tl.global_to_absolute(600.0) == _dt("10:35:00")
        assert tl.global_to_absolute(600.0) != _dt("10:15:00")


# ── TEST 4: jedna aktywność, trzy nagrania ─────────────────────────────────

class TestThreeClipsOneActivity:
    def test_target_timestamps(self):
        tl = _three_clip_timeline()
        cases = {
            0.0: "10:05:00",
            300.0: "10:10:00",
            600.0: "10:35:00",
            900.0: "10:40:00",
            1500.0: "11:20:00",
            1800.0: "11:25:00",
            2099.0: "11:29:59",
        }
        for g, expected in cases.items():
            assert tl.global_to_absolute(g) == _dt(expected), f"global={g}"
        assert tl.project_duration_s == pytest.approx(2100.0)


# ── TEST 5: telemetry precompute nie generuje przerw ───────────────────────

class TestPrecomputeNoGap:
    def test_grid_skips_absolute_gap(self):
        # clip1 2 s + clip2 2 s (gap 10:05:02 -> 10:35:00); 1 fps -> frames 0..3
        tl = VideoTimeline.from_clips([
            _clip("a", 2.0, _dt("10:05:00")),
            _clip("b", 2.0, _dt("10:35:00")),
        ], base_dt=_dt("10:05:00"))
        cache = build_telemetry_cache(
            layout={"indicators": {}, "width": 1280, "height": 720},
            base_dt=_dt("10:05:00"),
            tz_offset_hours=0,
            start_dt_utc=_dt("10:05:00"),
            speed_samples=[], track_samples=[], alt_samples=[],
            total_frames=4,
            target_fps=1.0,
            video_timeline=tl,
            update_rate_step=1,
        )
        assert cache.frames == 4
        dts = [rec.target_dt for rec in cache.records]
        assert dts == [_dt("10:05:00"), _dt("10:05:01"),
                       _dt("10:35:00"), _dt("10:35:01")]
        # No target falls inside the absolute gap.
        assert all(not (_dt("10:05:02") < dt < _dt("10:35:00")) for dt in dts)


# ── TEST 6: history chart przy granicy ─────────────────────────────────────

class TestHistoryWindow:
    def test_first_frame_clip2_target_is_10_35(self):
        tl = _three_clip_timeline()
        target = tl.global_to_absolute(600.0)
        assert target == _dt("10:35:00")
        # 60 s window -> 10:34:00 - 10:35:00 (NOT 10:14-10:15)
        assert target - timedelta(seconds=60) == _dt("10:34:00")
        assert target - timedelta(seconds=60) != _dt("10:14:00")


# ── TEST 7: mapa / FIT pozycja na granicy ──────────────────────────────────

class TestMapBoundary:
    def test_no_global_interpolation(self):
        tl = VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:05:00")),
            _clip("b", 900.0, _dt("10:35:00")),
        ], base_dt=_dt("10:05:00"))
        # The map/FIT position comes from absolute target_dt, which jumps.
        assert tl.global_to_absolute(599.9) == _dt("10:14:59.9")
        assert tl.global_to_absolute(600.0) == _dt("10:35:00")
        # There is no absolute time between them on the global axis.
        assert tl.absolute_to_global(_dt("10:20:00")) is None


# ── TEST 8: cut przez granicę ──────────────────────────────────────────────

class TestCutAcrossBoundary:
    def test_render_window_550_700(self):
        tl = VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:05:00")),
            _clip("b", 900.0, _dt("10:35:00")),
        ], base_dt=_dt("10:05:00"))
        # global 550-700 -> clip1 local 550-600 + clip2 local 0-100
        assert tl.global_to_clip(550.0) == (0, 550.0)
        assert tl.global_to_clip(599.9) == (0, 599.9)
        assert tl.global_to_clip(600.0) == (1, 0.0)
        assert tl.global_to_clip(700.0) == (1, 100.0)
        # absolute timestamps across the window
        assert tl.global_to_absolute(550.0) == _dt("10:14:10")
        assert tl.global_to_absolute(600.0) == _dt("10:35:00")
        assert tl.global_to_absolute(700.0) == _dt("10:36:40")


# ── TEST 9: progress globalny ──────────────────────────────────────────────

class TestProgress:
    def test_progress_relative_to_project_duration(self):
        tl = _three_clip_timeline()
        assert tl.project_duration_s == pytest.approx(2100.0)
        # global 1260 s (21 min) -> 60%
        progress = 1260.0 / tl.project_duration_s
        assert progress == pytest.approx(0.6)


# ── TEST 10: fallback timestamp — renderuje, jedno ostrzeżenie, brak crasha ─

class TestFallbackTimestamp:
    def test_fallback_clip_renders_via_degraded_contract(self):
        clip0 = _clip("a", 600.0, _dt("10:05:00"))
        clip1 = VideoClip(
            path=Path("C:/videos/b.MP4"), duration_s=900.0,
            absolute_start_dt=None,
            timestamp_source="continuous_fallback", timestamp_reliable=False,
            timestamp_quality="fallback",
        )
        tl = VideoTimeline.from_clips([clip0, clip1], base_dt=_dt("10:05:00"))
        assert tl.clips[1].timestamp_quality == "fallback"
        # Rendering still resolves a target (degraded, but no crash / no None).
        dt = resolve_render_target_dt(tl, _dt("10:05:00"), 700.0)
        assert dt is not None
        assert dt == _dt("10:05:00") + timedelta(seconds=700.0)


# ── TEST 11: single-file legacy == timeline ────────────────────────────────

class TestSingleFileParity:
    def test_timeline_equals_legacy(self):
        start = _dt("10:00:00")
        tl = VideoTimeline.from_clips([_clip("a", 600.0, start)], base_dt=start)
        for g in (0.0, 1.5, 100.0, 599.9):
            legacy = start + timedelta(seconds=g)
            assert tl.global_to_absolute(g) == legacy
            assert resolve_render_target_dt(tl, start, g) == legacy


# ── TEST 12: brak timeline — legacy path działa ────────────────────────────

class TestNoTimeline:
    def test_legacy_path(self):
        start = _dt("10:00:00")
        dt = resolve_render_target_dt(None, start, 42.0)
        assert dt == start + timedelta(seconds=42.0)

    def test_legacy_path_no_base(self):
        dt = resolve_render_target_dt(None, None, 42.0)
        assert dt is None  # no crash
