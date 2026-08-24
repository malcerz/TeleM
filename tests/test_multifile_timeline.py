"""ETAP MULTIFILE — testy modelu VideoClip + globalnej timeline.

Pokrycie (zgodnie z wymaganiami zadania):
  1. Jeden plik:  clip1 = 60 s, project_duration = 60 s.
  2. Dwa ciągłe pliki: clip1 abs 10:00-10:10, clip2 abs 10:10-10:20.
  3. Dwa pliki z przerwą: clip1 abs 10:00-10:10, clip2 abs 10:30-10:40.
  4. Kilka osobnych nagrań jednej aktywności FIT (35 min globalnie).
  5. Granice clipów: ostatnia klatka clip 1 / pierwsza klatka clip 2.
  6. Budowa timeline z paths (build_timeline_from_paths) z zamockowanym ffprobe.

Kluczowe invariants:
  GLOBAL VIDEO TIME != ABSOLUTE TELEMETRY TIME
  global_time -> clip -> local_time -> absolute_timestamp -> telemetry
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.multifile import (
    ClipTimestampResolution,
    VideoClip,
    VideoTimeline,
    build_timeline_from_paths,
    probe_video_info,
    resolve_clip_absolute_start,
)


def _dt(hms: str) -> datetime:
    """Parse 'HH:MM:SS[.fraction]' into a naive-UTC datetime (fixed day)."""
    h, m, s = hms.split(":")
    return datetime(2026, 8, 23, int(h), int(m)) + timedelta(seconds=float(s))


def _clip(duration_s: float, abs_start: datetime | None, name: str = "clip") -> VideoClip:
    return VideoClip(
        path=Path(f"C:/videos/{name}.MP4"),
        duration_s=duration_s,
        fps=30.0,
        width=1920,
        height=1080,
        absolute_start_dt=abs_start,
    )


# ── 1. Jeden plik ──────────────────────────────────────────────────────────

class TestSingleFile:
    def test_project_duration_equals_clip_duration(self):
        tl = VideoTimeline.from_clips([_clip(60.0, _dt("10:00:00"))], base_dt=_dt("10:00:00"))
        assert tl.project_duration_s == pytest.approx(60.0)
        assert tl.clip_count == 1
        assert tl.is_single_file is True

    def test_global_maps_to_local_within_clip(self):
        tl = VideoTimeline.from_clips([_clip(60.0, _dt("10:00:00"))], base_dt=_dt("10:00:00"))
        idx, local = tl.global_to_clip(30.0)
        assert idx == 0
        assert local == pytest.approx(30.0)

    def test_global_to_absolute_is_base_plus_time(self):
        tl = VideoTimeline.from_clips([_clip(60.0, None)], base_dt=_dt("10:00:00"))
        assert tl.global_to_absolute(0.0) == _dt("10:00:00")
        assert tl.global_to_absolute(30.0) == _dt("10:00:30")
        assert tl.global_to_absolute(60.0) == _dt("10:01:00")

    def test_single_file_clip0_reanchored_to_base_dt(self):
        # Even when clip0 has its own (creation_time) start, base_dt wins —
        # this guarantees exact single-file compatibility with today's code.
        tl = VideoTimeline.from_clips(
            [_clip(60.0, _dt("09:59:00"))], base_dt=_dt("10:00:00")
        )
        assert tl.global_to_absolute(0.0) == _dt("10:00:00")
        assert tl.global_to_absolute(10.0) == _dt("10:00:10")

    def test_out_of_range_clamps(self):
        tl = VideoTimeline.from_clips([_clip(60.0, None)], base_dt=_dt("10:00:00"))
        assert tl.global_to_clip(-5.0) == (0, 0.0)
        assert tl.global_to_absolute(-5.0) == _dt("10:00:00")
        assert tl.global_to_absolute(999.0) == _dt("10:01:00")


# ── 2. Dwa ciągłe pliki ────────────────────────────────────────────────────

class TestTwoContiguousClips:
    def _timeline(self) -> VideoTimeline:
        return VideoTimeline.from_clips(
            [
                _clip(600.0, _dt("10:00:00"), name="a"),
                _clip(600.0, _dt("10:10:00"), name="b"),
            ],
            base_dt=_dt("10:00:00"),
        )

    def test_global_duration_is_sum(self):
        tl = self._timeline()
        assert tl.project_duration_s == pytest.approx(1200.0)

    def test_global_boundaries(self):
        tl = self._timeline()
        assert tl.clips[0].global_start_s == pytest.approx(0.0)
        assert tl.clips[0].global_end_s == pytest.approx(600.0)
        assert tl.clips[1].global_start_s == pytest.approx(600.0)
        assert tl.clips[1].global_end_s == pytest.approx(1200.0)

    def test_global_maps_to_correct_clip_and_local(self):
        tl = self._timeline()
        idx, local = tl.global_to_clip(300.0)
        assert idx == 0 and local == pytest.approx(300.0)
        idx, local = tl.global_to_clip(900.0)
        assert idx == 1 and local == pytest.approx(300.0)

    def test_global_to_absolute(self):
        tl = self._timeline()
        assert tl.global_to_absolute(300.0) == _dt("10:05:00")
        assert tl.global_to_absolute(900.0) == _dt("10:15:00")

    def test_boundary_belongs_to_next_clip(self):
        tl = self._timeline()
        idx, local = tl.global_to_clip(600.0)
        assert idx == 1 and local == pytest.approx(0.0)
        assert tl.global_to_absolute(600.0) == _dt("10:10:00")

    def test_absolute_to_global(self):
        tl = self._timeline()
        assert tl.absolute_to_global(_dt("10:05:00")) == pytest.approx(300.0)
        assert tl.absolute_to_global(_dt("10:15:00")) == pytest.approx(900.0)


# ── 3. Dwa pliki z przerwą ─────────────────────────────────────────────────

class TestTwoClipsWithGap:
    def _timeline(self) -> VideoTimeline:
        return VideoTimeline.from_clips(
            [
                _clip(600.0, _dt("10:00:00"), name="a"),
                _clip(600.0, _dt("10:30:00"), name="b"),
            ],
            base_dt=_dt("10:00:00"),
        )

    def test_project_duration_ignores_gap(self):
        tl = self._timeline()
        # 20 min real gap is REMOVED from the final movie.
        assert tl.project_duration_s == pytest.approx(1200.0)
        assert tl.project_duration_s != pytest.approx(2400.0)

    def test_global_15min_maps_to_clip2_local_5min_abs_10_35(self):
        tl = self._timeline()
        # global 15:00 (900 s) -> clip2 (idx 1), local 5:00 (300 s) -> 10:35:00
        idx, local = tl.global_to_clip(900.0)
        assert idx == 1
        assert local == pytest.approx(300.0)
        assert tl.global_to_absolute(900.0) == _dt("10:35:00")

    def test_global_mid_clip1(self):
        tl = self._timeline()
        assert tl.global_to_absolute(300.0) == _dt("10:05:00")

    def test_gap_has_no_global_representation(self):
        tl = self._timeline()
        # Absolute times inside the 20-min gap map to NO clip.
        assert tl.absolute_to_global(_dt("10:25:00")) is None

    def test_reverse_mapping_across_gap(self):
        tl = self._timeline()
        assert tl.absolute_to_global(_dt("10:05:00")) == pytest.approx(300.0)
        assert tl.absolute_to_global(_dt("10:35:00")) == pytest.approx(900.0)
        # 10:39:30 - 10:30:00 = 570 s local -> global 600 + 570 = 1170
        assert tl.absolute_to_global(_dt("10:39:30")) == pytest.approx(1170.0)


# ── 4. Kilka osobnych nagrań jednej aktywności FIT ─────────────────────────

class TestMultipleClipsOneFitActivity:
    def _timeline(self) -> VideoTimeline:
        # FIT covers 10:00-12:00; videos cover selected fragments:
        #   10:05-10:15 (600s), 10:35-10:50 (900s), 11:20-11:30 (600s)
        return VideoTimeline.from_clips(
            [
                _clip(600.0, _dt("10:05:00"), name="f1"),
                _clip(900.0, _dt("10:35:00"), name="f2"),
                _clip(600.0, _dt("11:20:00"), name="f3"),
            ],
            base_dt=_dt("10:05:00"),
        )

    def test_global_duration_is_35_min(self):
        tl = self._timeline()
        assert tl.project_duration_s == pytest.approx(35 * 60.0)

    def test_global_boundaries(self):
        tl = self._timeline()
        assert [(c.global_start_s, c.global_end_s) for c in tl.clips] == [
            (0.0, 600.0),
            (600.0, 1500.0),
            (1500.0, 2100.0),
        ]

    def test_telemetry_timestamps_per_clip(self):
        tl = self._timeline()
        cases = [
            # (global, expected absolute)
            (0.0, _dt("10:05:00")),        # clip1 start
            (300.0, _dt("10:10:00")),      # clip1 middle
            (599.9, _dt("10:14:59.9")),    # clip1 end (approx)
            (600.0, _dt("10:35:00")),      # clip2 start
            (1050.0, _dt("10:42:30")),     # clip2 middle (450s local)
            (1499.9, _dt("10:49:59.9")),   # clip2 end
            (1500.0, _dt("11:20:00")),     # clip3 start
            (1800.0, _dt("11:25:00")),     # clip3 middle
            (2100.0, _dt("11:30:00")),     # clip3 end
        ]
        for global_t, expected in cases:
            got = tl.global_to_absolute(global_t)
            assert got is not None, f"global={global_t}"
            delta = (got - expected).total_seconds()
            assert abs(delta) < 0.11, f"global={global_t}: {got} != {expected}"


# ── 5. Granice clipów ──────────────────────────────────────────────────────

class TestClipBoundaries:
    def test_last_frame_of_clip1_and_first_frame_of_clip2(self):
        tl = VideoTimeline.from_clips(
            [
                _clip(600.0, _dt("10:00:00"), name="a"),
                _clip(600.0, _dt("10:30:00"), name="b"),
            ],
            base_dt=_dt("10:00:00"),
        )
        fps = 30.0
        last_frame_global = 600.0 - 1.0 / fps
        first_frame_global = 600.0

        idx_last, _ = tl.global_to_clip(last_frame_global)
        idx_first, _ = tl.global_to_clip(first_frame_global)
        assert idx_last == 0
        assert idx_first == 1

        abs_last = tl.global_to_absolute(last_frame_global)
        abs_first = tl.global_to_absolute(first_frame_global)
        # No duplicate / no missing timestamp jump: they are adjacent clips
        # with the real 20-min gap represented in absolute time.
        assert abs_last is not None and abs_first is not None
        assert (abs_last - _dt("10:00:00")).total_seconds() == pytest.approx(
            last_frame_global
        )
        assert abs_first == _dt("10:30:00")

    def test_frame_to_absolute_grid(self):
        tl = VideoTimeline.from_clips(
            [
                _clip(600.0, _dt("10:00:00"), name="a"),
                _clip(600.0, _dt("10:30:00"), name="b"),
            ],
            base_dt=_dt("10:00:00"),
        )
        # frame index 30 at 30 fps -> global 1.0 s -> clip0 local 1.0
        assert tl.frame_to_absolute(30, 30.0) == _dt("10:00:01")
        # frame index 18000 at 30 fps -> global 600.0 s -> clip1 start
        assert tl.frame_to_absolute(18000, 30.0) == _dt("10:30:00")
        # update_rate_step=2 -> frame 15 covers global 1.0 s
        assert tl.frame_to_absolute(15, 30.0, update_rate_step=2) == _dt("10:00:01")


# ── 6. Budowa z paths (zamockowane ffprobe) ────────────────────────────────

class TestBuildFromPaths:
    def test_build_timeline_from_paths(self, monkeypatch):
        paths = [f"C:/videos/{n}.MP4" for n in ("GX010001", "GX020001", "GX030001")]

        def fake_probe(ffprobe_exe, path, default_fps=30.0):
            idx = int(Path(path).stem[-6:])  # 010001 / 020001 / 030001
            dur = {10001: 600.0, 20001: 900.0, 30001: 600.0}[idx]
            return {"duration_s": dur, "fps": 30.0, "width": 1920, "height": 1080}

        def fake_resolve(path, ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe", use_cache=True, duration_s=None):
            idx = int(Path(path).stem[-6:])
            starts = {10001: _dt("10:05:00"), 20001: _dt("10:35:00"), 30001: _dt("11:20:00")}
            return ClipTimestampResolution(starts[idx], None, "gpmf_gps9", True, "fake")

        monkeypatch.setattr("src.multifile.probe_video_info", fake_probe)
        monkeypatch.setattr("src.multifile.resolve_clip_timestamp", fake_resolve)

        tl = build_timeline_from_paths(
            paths, ffprobe_exe="ffprobe", base_dt=_dt("10:05:00"), default_fps=30.0
        )
        assert tl.clip_count == 3
        assert tl.project_duration_s == pytest.approx(35 * 60.0)
        # Order preserved (never sorted by timestamp).
        assert [c.path.name for c in tl.clips] == ["GX010001.MP4", "GX020001.MP4", "GX030001.MP4"]
        # clip0 re-anchored to base_dt.
        assert tl.global_to_absolute(0.0) == _dt("10:05:00")
        assert tl.global_to_absolute(600.0) == _dt("10:35:00")
        assert tl.global_to_absolute(1500.0) == _dt("11:20:00")
        # gap between clip1 and clip2 is removed from global axis.
        # global 1200 -> clip2 (start 600), local 600 s -> 10:35 + 10 min
        assert tl.global_to_absolute(1200.0) == _dt("10:45:00")

    def test_build_with_absolute_start_fn(self, monkeypatch):
        def fake_probe(ffprobe_exe, path, default_fps=30.0):
            return {"duration_s": 60.0, "fps": 30.0, "width": 1280, "height": 720}

        monkeypatch.setattr("src.multifile.probe_video_info", fake_probe)

        tl = build_timeline_from_paths(
            ["C:/videos/x.MP4"],
            ffprobe_exe="ffprobe",
            base_dt=_dt("10:00:00"),
            absolute_start_fn=lambda p: _dt("09:59:30"),
        )
        # Custom resolver ignored for clip0 (base_dt re-anchors it).
        assert tl.global_to_absolute(0.0) == _dt("10:00:00")

    def test_probe_video_info_failure_is_safe(self, monkeypatch):
        # A failing ffprobe returns zeros + default_fps instead of raising.
        def fake_run(cmd, **kwargs):
            class _P:
                returncode = 1
                stdout = ""
            return _P()

        monkeypatch.setattr("src.multifile.subprocess.run", fake_run)
        info = probe_video_info("ffprobe", "C:/videos/nope.MP4")
        assert info["duration_s"] == 0.0
        assert info["fps"] == 30.0

    def test_resolve_clip_absolute_start_failure_is_safe(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            class _P:
                returncode = 1
                stdout = ""
            return _P()

        monkeypatch.setattr("src.multifile.subprocess.run", fake_run)
        assert resolve_clip_absolute_start("C:/videos/nope.MP4") is None


# ── 7. Zachowanie kolejności i kompatybilność jedno-plikowa ────────────────

class TestOrderingAndCompat:
    def test_user_order_is_preserved(self):
        # Even if clip1 has an earlier absolute time than clip0, order is kept.
        tl = VideoTimeline.from_clips(
            [
                _clip(300.0, _dt("11:00:00"), name="later"),
                _clip(300.0, _dt("09:00:00"), name="earlier"),
            ],
            base_dt=_dt("11:00:00"),
        )
        assert [c.path.name for c in tl.clips] == ["later.MP4", "earlier.MP4"]
        assert tl.global_to_absolute(0.0) == _dt("11:00:00")
        assert tl.global_to_absolute(300.0) == _dt("09:00:00")

    def test_set_base_dt_reanchors_clip0(self):
        tl = VideoTimeline.from_clips([_clip(60.0, _dt("09:59:00"), name="a")])
        assert tl.global_to_absolute(0.0) == _dt("09:59:00")
        tl.set_base_dt(_dt("10:00:00"))
        assert tl.global_to_absolute(0.0) == _dt("10:00:00")
        assert tl.global_to_absolute(60.0) == _dt("10:01:00")

    def test_empty_timeline(self):
        tl = VideoTimeline.from_clips([])
        assert tl.project_duration_s == 0.0
        assert tl.clip_count == 0
        assert tl.is_single_file is False
        assert tl.global_to_absolute(0.0) is None
        assert tl.global_to_clip(0.0) == (None, 0.0)
