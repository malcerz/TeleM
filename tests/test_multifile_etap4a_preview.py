"""ETAP MULTIFILE 4A — global preview of multiple clips.

Testuje czystą logikę resolwera czasu preview (bez realnego odtwarzania):
  GLOBAL  — pozycja na osi projektu (seek bar),
  LOCAL   — pozycja wewnątrz aktywnego MP4 (decoder),
  ABSOLUTE— prawdziwy timestamp telemetrii.

Wymagane testy (TEST 1..8 z zadania):
  1. resolve preview time (global -> clip/local/absolute)
  2. dokładna granica (last frame clip1 / first frame clip2)
  3. global position z lokalnej pozycji playera
  4. single-file (global == local, brak switcha źródła)
  5. gap absolutny (bez pustej przerwy na osi globalnej)
  6. player source switch (tylko przy zmianie clipu)
  7. lokalny seek (player dostaje local, nie global)
  8. timestamp quality (pokryte w test_multifile_etap3_clip_time.py)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.gui.qt._mixins.preview_mixin import PreviewMixin
from src.multifile import (
    TIMESTAMP_SOURCE_GPMF_GPS9,
    VideoClip,
    VideoTimeline,
)


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


class _FakePlayer:
    def __init__(self):
        self.sources: list[str] = []
        self.positions: list[int] = []
        self.played = False

    def setSource(self, url) -> None:
        try:
            self.sources.append(url.toLocalFile())
        except Exception:
            self.sources.append(str(url))

    def setPosition(self, ms) -> None:
        self.positions.append(int(ms))

    def play(self) -> None:
        self.played = True

    def pause(self) -> None:
        pass


def _make_preview(
    timeline: VideoTimeline,
    start_dt: datetime,
    active: int | None = 0,
    mpv: bool = False,
    player: _FakePlayer | None = None,
) -> PreviewMixin:
    obj = PreviewMixin.__new__(PreviewMixin)
    obj.video_timeline = timeline
    obj.telemetry = type("T", (), {"start_dt_utc": start_dt})()
    obj.video_paths = [c.path for c in timeline.clips]
    obj.video_path = obj.video_paths[0] if obj.video_paths else None
    obj.video_duration_s = timeline.project_duration_s
    obj._active_preview_clip_index = active
    obj._pending_seek_ms = None
    obj._seek_pending = False
    obj._playback_pos = 0.0
    obj.last_preview_ts = 0.0
    obj._preview_target_w = 960
    obj.is_using_mpv = lambda: mpv
    obj.mpv_player = None
    obj.media_player = player if player is not None else _FakePlayer()
    return obj


# ── TEST 1: resolve preview time ───────────────────────────────────────────

class TestResolvePreviewTime:
    def _timeline(self) -> VideoTimeline:
        return VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:05:00")),   # global 0-600
            _clip("b", 900.0, _dt("10:35:00")),   # global 600-1500
        ], base_dt=_dt("10:05:00"))

    def test_global_100(self):
        pv = _make_preview(self._timeline(), _dt("10:05:00"), active=0)
        res = pv._resolve_preview_time(100.0)
        assert res["clip_index"] == 0
        assert res["local_time"] == pytest.approx(100.0)
        assert res["absolute_dt"] == _dt("10:06:40")

    def test_global_700(self):
        pv = _make_preview(self._timeline(), _dt("10:05:00"), active=1)
        res = pv._resolve_preview_time(700.0)
        assert res["clip_index"] == 1
        assert res["local_time"] == pytest.approx(100.0)
        assert res["absolute_dt"] == _dt("10:36:40")


# ── TEST 2: dokładna granica ───────────────────────────────────────────────

class TestBoundary:
    def _timeline(self) -> VideoTimeline:
        return VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:05:00")),
            _clip("b", 900.0, _dt("10:35:00")),
        ], base_dt=_dt("10:05:00"))

    def test_last_frame_clip1(self):
        pv = _make_preview(self._timeline(), _dt("10:05:00"), active=0)
        res = pv._resolve_preview_time(599.999)
        assert res["clip_index"] == 0
        assert res["absolute_dt"] == _dt("10:14:59.999")

    def test_first_frame_clip2(self):
        pv = _make_preview(self._timeline(), _dt("10:05:00"), active=1)
        res = pv._resolve_preview_time(600.0)
        assert res["clip_index"] == 1
        assert res["local_time"] == pytest.approx(0.0)
        assert res["absolute_dt"] == _dt("10:35:00")


# ── TEST 3: global position z lokalnej pozycji playera ─────────────────────

class TestLocalToGlobal:
    def test_clip2_local_123(self):
        timeline = VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:05:00")),
            _clip("b", 900.0, _dt("10:35:00")),
        ], base_dt=_dt("10:05:00"))
        pv = _make_preview(timeline, _dt("10:05:00"), active=1)
        assert pv._local_to_global(123.0) == pytest.approx(723.0)

    def test_single_file_identity(self):
        timeline = VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:00:00")),
        ], base_dt=_dt("10:00:00"))
        pv = _make_preview(timeline, _dt("10:00:00"), active=0)
        assert pv._local_to_global(321.0) == pytest.approx(321.0)


# ── TEST 4: single-file kompatybilność ─────────────────────────────────────

class TestSingleFile:
    def test_global_equals_local_and_absolute(self):
        timeline = VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:00:00")),
        ], base_dt=_dt("10:00:00"))
        pv = _make_preview(timeline, _dt("10:00:00"), active=0)
        res = pv._resolve_preview_time(300.0)
        assert res["clip_index"] == 0
        assert res["local_time"] == pytest.approx(300.0)
        assert res["absolute_dt"] == _dt("10:00:00") + timedelta(seconds=300)

    def test_no_source_switch_in_single_file(self):
        timeline = VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:00:00")),
        ], base_dt=_dt("10:00:00"))
        player = _FakePlayer()
        pv = _make_preview(timeline, _dt("10:00:00"), active=0, player=player)
        switched = pv._preview_ensure_active_clip(0, timeline.clips[0], 300.0, 300.0)
        assert switched is False
        assert player.sources == []


# ── TEST 5: gap absolutny ──────────────────────────────────────────────────

class TestAbsoluteGap:
    def test_no_empty_gap_on_global_axis(self):
        # clip1 ends 10:15, clip2 starts 10:35 (real 20-min gap).
        timeline = VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:05:00")),
            _clip("b", 900.0, _dt("10:35:00")),
        ], base_dt=_dt("10:05:00"))
        pv = _make_preview(timeline, _dt("10:05:00"), active=0)
        assert pv._resolve_preview_time(599.999)["absolute_dt"] == _dt("10:14:59.999")
        assert pv._resolve_preview_time(600.0)["absolute_dt"] == _dt("10:35:00")
        # The compressed global axis has no 20-minute hole.
        assert timeline.project_duration_s == pytest.approx(1500.0)


# ── TEST 6: player source switch ───────────────────────────────────────────

class TestSourceSwitch:
    def _timeline(self) -> VideoTimeline:
        return VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:05:00")),
            _clip("b", 900.0, _dt("10:35:00")),
        ], base_dt=_dt("10:05:00"))

    def test_no_set_source_within_same_clip(self):
        player = _FakePlayer()
        pv = _make_preview(self._timeline(), _dt("10:05:00"), active=0, player=player)
        for g in (100.0, 200.0, 300.0):
            pv._preview_ensure_active_clip(0, pv.video_timeline.clips[0], g, g)
        assert player.sources == []

    def test_one_set_source_when_clip_changes(self):
        player = _FakePlayer()
        pv = _make_preview(self._timeline(), _dt("10:05:00"), active=0, player=player)
        # seek inside clip1 -> no switch
        pv._preview_ensure_active_clip(0, pv.video_timeline.clips[0], 100.0, 100.0)
        assert player.sources == []
        # seek to clip2 -> exactly one source switch
        switched = pv._preview_ensure_active_clip(
            1, pv.video_timeline.clips[1], 100.0, 700.0
        )
        assert switched is True
        assert player.sources == ["C:/videos/b.MP4"]
        # subsequent seek in clip2 -> no new switch
        pv._preview_ensure_active_clip(1, pv.video_timeline.clips[1], 200.0, 800.0)
        assert len(player.sources) == 1

    def test_pending_seek_set_on_switch(self):
        player = _FakePlayer()
        pv = _make_preview(self._timeline(), _dt("10:05:00"), active=0, player=player)
        pv._preview_ensure_active_clip(1, pv.video_timeline.clips[1], 120.0, 720.0)
        # QMediaPlayer path defers the seek until the source is loaded.
        assert pv._pending_seek_ms == 120000


# ── TEST 7: lokalny seek ───────────────────────────────────────────────────

class TestLocalSeek:
    def test_player_receives_local_not_global(self):
        timeline = VideoTimeline.from_clips([
            _clip("a", 600.0, _dt("10:05:00")),
            _clip("b", 900.0, _dt("10:35:00")),
        ], base_dt=_dt("10:05:00"))
        pv = _make_preview(timeline, _dt("10:05:00"), active=1)
        res = pv._resolve_preview_time(720.0)  # global=720, clip2 start=600
        assert res["clip_index"] == 1
        assert res["local_time"] == pytest.approx(120.0)
        assert res["local_time"] != pytest.approx(720.0)
