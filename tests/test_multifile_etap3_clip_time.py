"""ETAP MULTIFILE 3 — per-clip absolute timestamp / GPMF resolver.

Wymagane testy (TEST 1..9 z zadania) + testy jednostkowe resolvera GPMF:
- TEST 1  jeden plik (single-file compat)
- TEST 2  dwa ciągłe chaptery
- TEST 3  dwa osobne nagrania z przerwą
- TEST 4  jedna aktywność FIT, trzy nagrania
- TEST 5  pierwsza próbka GPS po starcie pliku (korekta local offset)
- TEST 6  creation_time vs GPMF -> preferuje GPMF
- TEST 7  brak GPMF, jest creation_time
- TEST 8  brak GPMF i creation_time (kontrolowany fallback + oznaczenie)
- TEST 9  kolejność użytkownika zachowana

Testy resolvera operują na syntetycznym płaskim parse GPMF (bez ffmpeg).
"""

from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.multifile import (
    TIMESTAMP_SOURCE_CONTINUOUS_FALLBACK,
    TIMESTAMP_SOURCE_CREATION_TIME,
    TIMESTAMP_SOURCE_GPMF_GPS9,
    TIMESTAMP_SOURCE_GPMF_GPSU,
    ClipTimestampResolution,
    VideoClip,
    VideoTimeline,
    _first_absolute_time_from_parsed,
    build_timeline_from_paths,
    clear_time_resolution_cache,
    resolve_clip_timestamp,
)

GPS_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)
_SCAL = (10000000, 10000000, 1000, 1000, 100, 1, 1000, 100, 1)


def _dt(hms: str) -> datetime:
    h, m, s = hms.split(":")
    return datetime(2026, 8, 23, int(h), int(m)) + timedelta(seconds=float(s))


def _to_gps(dt: datetime) -> tuple[float, float]:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = dt - GPS_EPOCH
    return float(diff.days), float(diff.seconds) + diff.microseconds / 1e6


def _gps9_payload(samples: list[tuple[datetime, float, float]]) -> bytes:
    """Build a GPS9 'lllllllSS' payload from [(abs_dt, lat, lon), ...]."""
    out = b""
    for dt, lat, lon in samples:
        days, secs = _to_gps(dt)
        out += struct.pack(
            ">iiiiiiiHH",
            int(lat * 1e7), int(lon * 1e7), int(10.0 * 1000),  # alt=10m
            int(5.0 * 1000), int(5.0 * 100),                    # s2d, s3d
            int(days), int(secs * 1000),
            int(2.0 * 100), int(3),                              # dop, fix
        )
    return out


def _parsed_gps9(
    abs_times: list[datetime],
    stmp=None, tsmp=None,
    duration_s=None,
) -> list:
    """Flat GPMF parse list with one GPS9 block (10 Hz samples)."""
    lat = 54.36 + 0.001 * len(abs_times)
    payload = _gps9_payload([(dt, lat, 18.60 + i * 1e-5) for i, dt in enumerate(abs_times)])
    out = []
    if stmp is not None:
        out.append(("STMP", stmp))
    if tsmp is not None:
        out.append(("TSMP", tsmp))
    out += [("STNM", "GPS (Lat., Long., Alt., 2D, 3D, days, secs, DOP, fix)"),
            ("TYPE", b"lllllllSS"),
            ("SCAL", _SCAL),
            ("GPS9", payload)]
    return out


# ── TEST 5/6: pierwsza próbka GPS po starcie pliku + STMP file-local ──────

class TestFirstGpsSampleOffset:
    def test_local_offset_correction(self):
        # local sample time = 0.8 s, GPS abs = 10:35:00.800
        # -> clip start ~= 10:35:00.000 (NOT 10:35:00.800)
        abs_t = datetime(2026, 8, 23, 10, 35, 0, 800000)
        parsed = _parsed_gps9([abs_t], stmp=800000, tsmp=8, duration_s=60.0)
        res = _first_absolute_time_from_parsed(parsed, duration_s=60.0)
        assert res.timestamp_source == TIMESTAMP_SOURCE_GPMF_GPS9
        assert res.timestamp_reliable is True
        assert res.absolute_start_dt == datetime(2026, 8, 23, 10, 35, 0, 0)

    def test_stmp_not_file_local_uses_gps_sample_time(self):
        # STMP=1665779072 (session-relative, exceeds 37.7 s duration)
        # -> local offset unknowable -> clip start = GPS sample time
        abs_t = datetime(2026, 8, 23, 10, 35, 0, 800000)
        parsed = _parsed_gps9([abs_t], stmp=1665779072, tsmp=16661, duration_s=37.7)
        res = _first_absolute_time_from_parsed(parsed, duration_s=37.7)
        assert res.timestamp_source == TIMESTAMP_SOURCE_GPMF_GPS9
        assert res.absolute_start_dt == datetime(2026, 8, 23, 10, 35, 0, 800000)
        assert "not_file_local" in res.timestamp_detail

    def test_no_stmp_uses_gps_sample_time(self):
        abs_t = datetime(2026, 8, 23, 10, 35, 0, 800000)
        parsed = _parsed_gps9([abs_t], stmp=None, tsmp=None, duration_s=60.0)
        res = _first_absolute_time_from_parsed(parsed, duration_s=60.0)
        assert res.absolute_start_dt == datetime(2026, 8, 23, 10, 35, 0, 800000)

    def test_second_sample_within_block(self):
        # block has 10 samples at 10 Hz; first sample invalid (0,0) -> skip
        abs0 = datetime(2026, 8, 23, 10, 35, 0, 0)
        lat = 54.36
        payload = b""
        for i in range(10):
            if i == 0:
                latv, lonv = 0.0, 0.0
            else:
                latv, lonv = lat, 18.60 + i * 1e-5
            days, secs = _to_gps(abs0 + timedelta(seconds=i * 0.1))
            payload += struct.pack(
                ">iiiiiiiHH",
                int(latv * 1e7), int(lonv * 1e7), int(10 * 1000),
                int(5 * 1000), int(5 * 100), int(days), int(secs * 1000),
                int(200), 3,
            )
        parsed = [("STMP", 1000000), ("TSMP", 10), ("TYPE", b"lllllllSS"),
                  ("SCAL", _SCAL), ("GPS9", payload)]
        res = _first_absolute_time_from_parsed(parsed, duration_s=60.0)
        # first valid sample = i=1 -> local = 1.0 + 0.1 = 1.1 s
        expected = datetime(2026, 8, 23, 10, 35, 0, 100000) - timedelta(seconds=1.1)
        assert res.absolute_start_dt == expected


# ── TEST 8 (ETAP 4A): timestamp quality exact/estimated/fallback ──────────

class TestTimestampQuality:
    def test_gps9_file_local_stmp_is_exact(self):
        abs_t = datetime(2026, 8, 23, 10, 35, 0, 800000)
        parsed = _parsed_gps9([abs_t], stmp=800000, tsmp=8, duration_s=60.0)
        res = _first_absolute_time_from_parsed(parsed, duration_s=60.0)
        assert res.timestamp_quality == "exact"
        assert res.timestamp_reliable is True
        assert res.timestamp_source == TIMESTAMP_SOURCE_GPMF_GPS9

    def test_gps9_session_stmp_is_estimated(self):
        abs_t = datetime(2026, 8, 23, 10, 35, 0, 800000)
        parsed = _parsed_gps9([abs_t], stmp=1665779072, tsmp=16661, duration_s=37.7)
        res = _first_absolute_time_from_parsed(parsed, duration_s=37.7)
        assert res.timestamp_quality == "estimated"
        assert res.timestamp_reliable is True  # still GPS-based, approximate start
        assert "not_file_local" in res.timestamp_detail

    def test_gpsu_is_estimated(self):
        res = _first_absolute_time_from_parsed([("GPSU", (2026, 8, 23, 10, 35, 0, 0))])
        assert res.timestamp_quality == "estimated"
        assert res.timestamp_source == TIMESTAMP_SOURCE_GPMF_GPSU

    def test_creation_time_is_estimated(self, monkeypatch):
        no_gps = ClipTimestampResolution(
            absolute_start_dt=None, timestamp_source="no_gps_time",
            timestamp_reliable=False, timestamp_detail="no gps",
        )
        monkeypatch.setattr("src.multifile._resolve_from_gpmf", lambda *a, **k: no_gps)
        monkeypatch.setattr("src.multifile.resolve_clip_absolute_start",
                            lambda *a, **k: datetime(2026, 8, 23, 10, 35, 1))
        res = resolve_clip_timestamp("C:/videos/q.MP4", use_cache=False, duration_s=60.0)
        assert res.timestamp_quality == "estimated"
        assert res.timestamp_source == TIMESTAMP_SOURCE_CREATION_TIME

    def test_continuous_fallback_is_fallback(self):
        clip0 = VideoClip(path=Path("C:/videos/a.MP4"), duration_s=60.0,
                          absolute_start_dt=datetime(2026, 8, 23, 10, 0, 0),
                          timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9,
                          timestamp_reliable=True, timestamp_quality="exact")
        clip1 = VideoClip(path=Path("C:/videos/b.MP4"), duration_s=60.0,
                          absolute_start_dt=None, timestamp_source="unknown",
                          timestamp_reliable=False)
        tl = VideoTimeline.from_clips([clip0, clip1],
                                      base_dt=datetime(2026, 8, 23, 10, 0, 0))
        assert tl.clips[1].timestamp_quality == "fallback"
        assert tl.clips[1].timestamp_source == TIMESTAMP_SOURCE_CONTINUOUS_FALLBACK


# ── GPSU / brak GPS ────────────────────────────────────────────────────────

class TestGpsuAndNoGps:
    def test_gpsu_source(self):
        parsed = [("GPSU", (2026, 8, 23, 10, 35, 0, 0))]
        res = _first_absolute_time_from_parsed(parsed)
        assert res.timestamp_source == TIMESTAMP_SOURCE_GPMF_GPSU
        assert res.absolute_start_dt == datetime(2026, 8, 23, 10, 35, 0)

    def test_no_gps_time(self):
        res = _first_absolute_time_from_parsed([("STNM", "Accelerometer"), ("ACCL", b"")])
        assert res.timestamp_source == "no_gps_time"
        assert res.absolute_start_dt is None
        assert res.timestamp_reliable is False


# ── TEST 6/7/8: priority chain in resolve_clip_timestamp ───────────────────

class TestResolverPriority:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_time_resolution_cache()
        yield
        clear_time_resolution_cache()

    def test_gpmf_preferred_over_creation_time(self, monkeypatch):
        gpmf_res = ClipTimestampResolution(
            absolute_start_dt=datetime(2026, 8, 23, 10, 35, 0, 120000),
            timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True,
            timestamp_detail="gps9",
        )
        monkeypatch.setattr("src.multifile._resolve_from_gpmf",
                            lambda *a, **k: gpmf_res)
        monkeypatch.setattr("src.multifile.resolve_clip_absolute_start",
                            lambda *a, **k: datetime(2026, 8, 23, 10, 35, 1))
        res = resolve_clip_timestamp("C:/videos/t6.MP4", use_cache=False,
                                     duration_s=60.0)
        assert res.timestamp_source == TIMESTAMP_SOURCE_GPMF_GPS9
        assert res.absolute_start_dt == datetime(2026, 8, 23, 10, 35, 0, 120000)

    def test_creation_time_when_no_gpmf(self, monkeypatch):
        no_gps = ClipTimestampResolution(
            absolute_start_dt=None, timestamp_source="no_gps_time",
            timestamp_reliable=False, timestamp_detail="no gps",
        )
        monkeypatch.setattr("src.multifile._resolve_from_gpmf",
                            lambda *a, **k: no_gps)
        monkeypatch.setattr("src.multifile.resolve_clip_absolute_start",
                            lambda *a, **k: datetime(2026, 8, 23, 10, 35, 1))
        res = resolve_clip_timestamp("C:/videos/t7.MP4", use_cache=False,
                                     duration_s=60.0)
        assert res.timestamp_source == TIMESTAMP_SOURCE_CREATION_TIME
        assert res.timestamp_reliable is True
        assert res.absolute_start_dt == datetime(2026, 8, 23, 10, 35, 1)

    def test_no_gpmf_no_creation_time_is_controlled(self, monkeypatch):
        no_gps = ClipTimestampResolution(
            absolute_start_dt=None, timestamp_source="no_gps_time",
            timestamp_reliable=False, timestamp_detail="no gps",
        )
        monkeypatch.setattr("src.multifile._resolve_from_gpmf",
                            lambda *a, **k: no_gps)
        monkeypatch.setattr("src.multifile.resolve_clip_absolute_start",
                            lambda *a, **k: None)
        # must not crash
        res = resolve_clip_timestamp("C:/videos/t8.MP4", use_cache=False,
                                     duration_s=60.0)
        assert res.absolute_start_dt is None
        assert res.timestamp_reliable is False

    def test_unreliable_clip_marked_continuous_fallback_in_timeline(self):
        # clip0 is always re-anchored to base_dt; clip1 (no reliable start)
        # must be explicitly marked continuous_fallback.
        clip0 = VideoClip(path="C:/videos/a.MP4", duration_s=60.0,
                          absolute_start_dt=datetime(2026, 8, 23, 10, 0, 0),
                          timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9,
                          timestamp_reliable=True)
        clip1 = VideoClip(path="C:/videos/b.MP4", duration_s=60.0,
                          absolute_start_dt=None,
                          timestamp_source="unknown", timestamp_reliable=False)
        tl = VideoTimeline.from_clips([clip0, clip1],
                                      base_dt=datetime(2026, 8, 23, 10, 0, 0))
        assert tl.clips[1].timestamp_source == TIMESTAMP_SOURCE_CONTINUOUS_FALLBACK
        assert tl.clips[1].timestamp_reliable is False
        assert tl.clips[1].absolute_start_dt is None
        # mapping still works via the explicit degraded fallback
        # global 90 -> clip1 local 30 -> base + 60 + 30 = 10:01:30
        assert tl.global_to_absolute(90.0) == datetime(2026, 8, 23, 10, 1, 30)


# ── TEST 1..4, 9: timeline mapping invariant ───────────────────────────────

class TestTimelineInvariants:
    def test_single_file(self):
        # TEST 1: clip absolute start = 10:00:00, duration 60
        tl = VideoTimeline.from_clips([VideoClip(
            path="C:/videos/a.MP4", duration_s=60.0,
            absolute_start_dt=_dt("10:00:00"),
            timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True,
        )], base_dt=_dt("10:00:00"))
        assert tl.project_duration_s == pytest.approx(60.0)
        assert tl.global_to_absolute(30.0) == _dt("10:00:30")
        assert tl.global_to_absolute(0.0) == _dt("10:00:00")

    def test_two_contiguous_chapters(self):
        # TEST 2: 10:00-10:10 + 10:10-10:20 -> global 15:00 -> 10:15:00
        tl = VideoTimeline.from_clips([
            VideoClip(path="C:/videos/a.MP4", duration_s=600.0,
                      absolute_start_dt=_dt("10:00:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
            VideoClip(path="C:/videos/b.MP4", duration_s=600.0,
                      absolute_start_dt=_dt("10:10:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
        ], base_dt=_dt("10:00:00"))
        assert tl.project_duration_s == pytest.approx(1200.0)
        idx, local = tl.global_to_clip(900.0)
        assert idx == 1 and local == pytest.approx(300.0)
        assert tl.global_to_absolute(900.0) == _dt("10:15:00")

    def test_two_separate_recordings_with_gap(self):
        # TEST 3: 10:00-10:10 + 10:30-10:40 -> global 15:00 -> clip2 local 5:00 -> 10:35
        tl = VideoTimeline.from_clips([
            VideoClip(path="C:/videos/a.MP4", duration_s=600.0,
                      absolute_start_dt=_dt("10:00:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
            VideoClip(path="C:/videos/b.MP4", duration_s=600.0,
                      absolute_start_dt=_dt("10:30:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
        ], base_dt=_dt("10:00:00"))
        assert tl.project_duration_s == pytest.approx(1200.0)
        idx, local = tl.global_to_clip(900.0)
        assert idx == 1 and local == pytest.approx(300.0)
        assert tl.global_to_absolute(900.0) == _dt("10:35:00")

    def test_one_fit_activity_three_recordings(self):
        # TEST 4: FIT 10:00-12:00; clip1 10:05-10:15, clip2 10:35-10:50,
        # clip3 11:20-11:30 -> project_duration 35 min
        tl = VideoTimeline.from_clips([
            VideoClip(path="C:/videos/f1.MP4", duration_s=600.0,
                      absolute_start_dt=_dt("10:05:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
            VideoClip(path="C:/videos/f2.MP4", duration_s=900.0,
                      absolute_start_dt=_dt("10:35:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
            VideoClip(path="C:/videos/f3.MP4", duration_s=600.0,
                      absolute_start_dt=_dt("11:20:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
        ], base_dt=_dt("10:05:00"))
        assert tl.project_duration_s == pytest.approx(35 * 60.0)
        cases = {
            0.0: "10:05:00",
            300.0: "10:10:00",
            600.0: "10:35:00",
            1200.0: "10:45:00",
            1500.0: "11:20:00",
            1800.0: "11:25:00",
        }
        for g, expected in cases.items():
            assert tl.global_to_absolute(g) == _dt(expected), f"global={g}"

    def test_user_order_preserved(self):
        # TEST 9: user gives clipB, clipA, clipC -> order kept; abs from own data
        tl = VideoTimeline.from_clips([
            VideoClip(path=Path("C:/videos/B.MP4"), duration_s=300.0,
                      absolute_start_dt=_dt("11:00:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
            VideoClip(path=Path("C:/videos/A.MP4"), duration_s=300.0,
                      absolute_start_dt=_dt("09:00:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
            VideoClip(path=Path("C:/videos/C.MP4"), duration_s=300.0,
                      absolute_start_dt=_dt("12:00:00"),
                      timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9, timestamp_reliable=True),
        ], base_dt=_dt("11:00:00"))
        assert [c.path.name for c in tl.clips] == ["B.MP4", "A.MP4", "C.MP4"]
        assert tl.global_to_absolute(0.0) == _dt("11:00:00")
        assert tl.global_to_absolute(300.0) == _dt("09:00:00")
        assert tl.global_to_absolute(600.0) == _dt("12:00:00")


# ── build_timeline_from_paths przekazuje duration do resolvera ─────────────

class TestBuildPassesDuration:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_time_resolution_cache()
        yield
        clear_time_resolution_cache()

    def test_build_passes_duration_to_resolver(self, monkeypatch):
        captured = {}

        def fake_probe(ffprobe_exe, path, default_fps=30.0):
            return {"duration_s": 60.0, "fps": 30.0, "width": 1920, "height": 1080}

        def fake_resolve(path, ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
                         use_cache=True, duration_s=None):
            captured["duration_s"] = duration_s
            return ClipTimestampResolution(
                absolute_start_dt=_dt("10:00:00"),
                timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9,
                timestamp_reliable=True, timestamp_detail="fake",
            )

        monkeypatch.setattr("src.multifile.probe_video_info", fake_probe)
        monkeypatch.setattr("src.multifile.resolve_clip_timestamp", fake_resolve)
        # Without base_dt -> resolver is called and receives the clip duration.
        tl = build_timeline_from_paths(
            ["C:/videos/x.MP4"], ffprobe_exe="ffprobe",
            base_dt=None, default_fps=30.0,
        )
        assert captured.get("duration_s") == pytest.approx(60.0)
        assert tl.clips[0].timestamp_source == TIMESTAMP_SOURCE_GPMF_GPS9

    def test_build_clip0_uses_project_start_fast_path(self, monkeypatch):
        # With base_dt, clip 0 must NOT re-extract GPMF (it is re-anchored to
        # the project start_dt_utc) -> resolver is skipped.
        captured = {"calls": 0}

        def fake_probe(ffprobe_exe, path, default_fps=30.0):
            return {"duration_s": 60.0, "fps": 30.0, "width": 1920, "height": 1080}

        def fake_resolve(path, ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
                         use_cache=True, duration_s=None):
            captured["calls"] += 1
            return ClipTimestampResolution(
                absolute_start_dt=_dt("10:00:00"),
                timestamp_source=TIMESTAMP_SOURCE_GPMF_GPS9,
                timestamp_reliable=True, timestamp_detail="fake",
            )

        monkeypatch.setattr("src.multifile.probe_video_info", fake_probe)
        monkeypatch.setattr("src.multifile.resolve_clip_timestamp", fake_resolve)
        tl = build_timeline_from_paths(
            ["C:/videos/x.MP4"], ffprobe_exe="ffprobe",
            base_dt=_dt("10:00:00"), default_fps=30.0,
        )
        assert captured["calls"] == 0
        assert tl.clips[0].timestamp_source == "project_start_anchor"
        assert tl.clips[0].absolute_start_dt == _dt("10:00:00")
        assert tl.global_to_absolute(0.0) == _dt("10:00:00")

    def test_duration_in_cache_key(self):
        # The cache key must distinguish durations (STMP file-local decision
        # depends on it), so a 60 s clip and a 1800 s clip of the same path
        # never share a cached resolution.
        from src.multifile import _TIME_RESOLUTION_CACHE, _resolution_cache_key
        path = "C:/videos/dur.MP4"
        clear_time_resolution_cache()
        first = ClipTimestampResolution(
            absolute_start_dt=_dt("10:00:00"), timestamp_source="gpmf_gps9",
            timestamp_reliable=True, timestamp_detail="dur=60",
        )
        second = ClipTimestampResolution(
            absolute_start_dt=_dt("10:30:00"), timestamp_source="gpmf_gps9",
            timestamp_reliable=True, timestamp_detail="dur=1800",
        )
        k60 = _resolution_cache_key(path, 60.0)
        k1800 = _resolution_cache_key(path, 1800.0)
        assert k60 != k1800
        _TIME_RESOLUTION_CACHE[k60] = first
        _TIME_RESOLUTION_CACHE[k1800] = second
        assert resolve_clip_timestamp(path, use_cache=True, duration_s=60.0) is first
        assert resolve_clip_timestamp(path, use_cache=True, duration_s=1800.0) is second
