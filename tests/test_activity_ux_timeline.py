#!/usr/bin/env python3
"""Unit tests for the 6 usability timeline/activity features in TeleM.

Features:
1. MAP Rotation Smoothing (circular angular wrap 0/360)
2. LEAN Motion Smoothing (time-based precompute)
3. FIT Active Average Speed (active timer time, pauses excluded)
4. Global charts_skip_pauses (X-axis collapse of pauses)
5. Auto-FIT directory scanning and scoring
6. Auto export filename (5-minute rounding and collision handling)
"""

import math
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.telemetry_heading import smooth_heading_samples
from src.telemetry_imu import smooth_roll_samples
from src.telemetry_active_time import ActiveTimeMapper, build_active_time_mapper_from_events
from src.indicators.chart_builder import build_chart_data, ChartHistory, clip_chart_data_for_target
from src.video_helpers import round_dt_to_nearest_5min, generate_auto_export_filename
from telemetry_fit import probe_fit_time_range, find_best_fit_match


class TestMapHeadingSmoothing(unittest.TestCase):
    def test_circular_wrap_no_180_jump(self):
        """Heading 358, 359, 0, 1, 2 must smoothly transition across north without jumping to 180."""
        base_dt = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)
        headings = [358.0, 359.0, 0.0, 1.0, 2.0]
        samples = [(base_dt + timedelta(seconds=i), h) for i, h in enumerate(headings)]

        # smoothing = 0 -> exact legacy behavior
        unsmoothed = smooth_heading_samples(samples, 0.0)
        self.assertEqual(len(unsmoothed), 5)
        for orig, res in zip(samples, unsmoothed):
            self.assertEqual(orig[0], res[0])
            self.assertAlmostEqual(orig[1], res[1], places=5)

        # smoothing > 0 -> smooth transition near 0/360, no jump to ~180
        smoothed = smooth_heading_samples(samples, 2.0)
        self.assertEqual(len(smoothed), 5)
        for dt, val in smoothed:
            # All values should be near North: either in [355, 360] or [0, 5]
            is_near_north = (val >= 355.0) or (val <= 5.0)
            self.assertTrue(is_near_north, f"Smoothed value {val} erroneously jumped away from North!")
            # Ensure none are near 180
            self.assertFalse(160.0 <= val <= 200.0, f"Value {val} showed 180-deg inversion!")


class TestLeanMotionSmoothing(unittest.TestCase):
    def test_lean_jump_attenuated(self):
        """Syntetyczny skok 0 -> 30 -> 0 musi być łagodniejszy przy smoothing > 0."""
        base_dt = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)
        rolls = [0.0, 0.0, 30.0, 0.0, 0.0]
        samples = [(base_dt + timedelta(seconds=i * 0.1), r) for i, r in enumerate(rolls)]

        # smoothing = 0 -> exact legacy behavior
        unsmoothed = smooth_roll_samples(samples, 0.0)
        self.assertEqual(len(unsmoothed), 5)
        self.assertAlmostEqual(unsmoothed[2][1], 30.0, places=5)

        # smoothing > 0 -> peak is attenuated
        smoothed = smooth_roll_samples(samples, 0.3)
        self.assertEqual(len(smoothed), 5)
        peak = smoothed[2][1]
        self.assertLess(peak, 30.0, "Smoothing did not attenuate the sudden peak")
        self.assertGreater(peak, 0.0, "Smoothing completely eliminated the signal")


class TestFitActiveTimeClockAndAverageSpeed(unittest.TestCase):
    def setUp(self):
        # 10:00 start, ride 10 min, pause 5 min (10:10..10:15), ride 10 min (10:15..10:25)
        self.t0 = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)
        self.t_pause_start = self.t0 + timedelta(minutes=10)
        self.t_pause_end = self.t0 + timedelta(minutes=15)
        self.t_end = self.t0 + timedelta(minutes=25)

        events = [
            {"event": "timer", "event_type": "start", "timestamp": self.t0},
            {"event": "timer", "event_type": "stop_all", "timestamp": self.t_pause_start},
            {"event": "timer", "event_type": "start", "timestamp": self.t_pause_end},
            {"event": "timer", "event_type": "stop_all", "timestamp": self.t_end},
        ]
        self.mapper = build_active_time_mapper_from_events(events)

    def test_active_vs_wall_time(self):
        """Wall elapsed = 25 min, active elapsed = 20 min."""
        wall_elapsed_s = (self.t_end - self.t0).total_seconds()
        self.assertEqual(wall_elapsed_s, 25 * 60)

        active_elapsed_s = self.mapper.cumulative_active_time(self.t_end)
        self.assertEqual(active_elapsed_s, 20 * 60)
        self.assertEqual(self.mapper.wall_to_active_seconds(self.t_end), 20 * 60)

    def test_pause_freeze(self):
        """Active time must remain frozen during pause."""
        t_mid_pause = self.t0 + timedelta(minutes=12)
        self.assertTrue(self.mapper.is_paused(t_mid_pause))
        self.assertEqual(self.mapper.wall_to_active_seconds(t_mid_pause), 10 * 60)

        t_resumed = self.t0 + timedelta(minutes=16)
        self.assertFalse(self.mapper.is_paused(t_resumed))
        self.assertEqual(self.mapper.wall_to_active_seconds(t_resumed), 11 * 60)

    def test_dynamic_avg_speed(self):
        """Distance 10 km, active time 20 min -> 30 km/h (not 24 km/h)."""
        dist_m = 10000.0
        active_time_s = self.mapper.wall_to_active_seconds(self.t_end)
        wall_time_s = (self.t_end - self.t0).total_seconds()

        avg_speed_active = (dist_m / active_time_s) * 3.6
        avg_speed_wall = (dist_m / wall_time_s) * 3.6

        self.assertAlmostEqual(avg_speed_active, 30.0, places=2)
        self.assertAlmostEqual(avg_speed_wall, 24.0, places=2)


class TestChartsSkipPauses(unittest.TestCase):
    def test_pause_collapsed_from_axis(self):
        """With charts_skip_pauses=True, the pause is excised from X-axis and duration equals active time."""
        t0 = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            {"event": "timer", "event_type": "start", "timestamp": t0},
            {"event": "timer", "event_type": "stop_all", "timestamp": t0 + timedelta(minutes=10)},
            {"event": "timer", "event_type": "start", "timestamp": t0 + timedelta(minutes=15)},
            {"event": "timer", "event_type": "stop_all", "timestamp": t0 + timedelta(minutes=25)},
        ]
        mapper = build_active_time_mapper_from_events(events)

        # Create 1 sample per minute
        samples = []
        for m in range(26):
            dt = t0 + timedelta(minutes=m)
            samples.append((dt, float(m * 10)))

        layout_off = {
            "charts_skip_pauses": False,
            "indicators": {
                "fit_power_text": {
                    "form": "chart", "enabled": True, "source": "fit", "chart_time_scope": "activity"
                }
            }
        }
        layout_on = {
            "charts_skip_pauses": True,
            "indicators": {
                "fit_power_text": {
                    "form": "chart", "enabled": True, "source": "fit", "chart_time_scope": "activity"
                }
            }
        }

        # OFF
        data_off = build_chart_data(
            layout_off,
            lambda src: ([], [], []),
            lambda f, s, k=None: list(samples),
            active_time_mapper=mapper,
        )
        hist_off = data_off["fit_power_text"]
        dur_off = (hist_off.chart_end_dt - hist_off.chart_start_dt).total_seconds()
        self.assertEqual(dur_off, 25 * 60)

        # ON
        data_on = build_chart_data(
            layout_on,
            lambda src: ([], [], []),
            lambda f, s, k=None: list(samples),
            active_time_mapper=mapper,
        )
        hist_on = data_on["fit_power_text"]
        dur_on = (hist_on.chart_end_dt - hist_on.chart_start_dt).total_seconds()
        self.assertEqual(dur_on, 20 * 60)
        self.assertTrue(hist_on.skip_pauses)

        # Check that consecutive samples across the pause touch seamlessly
        # (at minute 10 and minute 15 in wall time, mapped to minute 10 in active time)
        timestamps = list(hist_on.timestamps)
        deltas = [(r - l).total_seconds() for l, r in zip(timestamps, timestamps[1:])]
        max_delta = max(deltas)
        self.assertLessEqual(max_delta, 60.0, "Gap across pause was not collapsed on active axis")


class TestAutoFitMatching(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_mock_fit(self, filename: str, start_dt: datetime, duration_s: float):
        # Create a valid FIT binary header + definition + session message
        import struct
        path = self.temp_dir / filename
        data_records = bytearray()
        
        # Def 0: session (global msg 18)
        # Architecture 0 (LE), global_msg=18, 3 fields:
        # field 2: start_time (uint32, sz 4, base 140)
        # field 253: timestamp (uint32, sz 4, base 140)
        # field 7: total_elapsed_time (uint32, sz 4, base 140)
        def_bytes = struct.pack("<BBHB", 0, 0, 18, 3)
        field_defs = bytearray([
            2, 4, 140,
            253, 4, 140,
            7, 4, 140,
        ])
        data_records.append(0x40) # def msg, local 0
        data_records.extend(def_bytes)
        data_records.extend(field_defs)

        # Data msg 0
        start_fit_epoch = int(start_dt.timestamp() - 631065600)
        end_dt = start_dt + timedelta(seconds=duration_s)
        end_fit_epoch = int(end_dt.timestamp() - 631065600)
        elapsed_scaled = int(duration_s * 1000)

        data_records.append(0x00) # data msg, local 0
        data_records.extend(struct.pack("<III", start_fit_epoch, end_fit_epoch, elapsed_scaled))

        # Header 14 bytes
        header = struct.pack("<BBHI4sH", 14, 32, 2100, len(data_records), b".FIT", 0)
        with open(path, "wb") as f:
            f.write(header)
            f.write(data_records)
        return path

    def test_single_match(self):
        """1 temporal match among 3 FITs must be selected."""
        t_base = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)
        self._create_mock_fit("yesterday.fit", t_base - timedelta(days=1), 3600)
        match_fit = self._create_mock_fit("correct_ride.fit", t_base, 3600)
        self._create_mock_fit("tomorrow.fit", t_base + timedelta(days=1), 3600)

        mp4_intervals = [(t_base + timedelta(minutes=5), t_base + timedelta(minutes=20))]
        matched, diag = find_best_fit_match(mp4_intervals, self.temp_dir)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.name, "correct_ride.fit")
        self.assertEqual(diag["overlap"], 15 * 60)

    def test_ambiguous_tie_rejected(self):
        """2 equally matching FITs must result in NO arbitrary match."""
        t_base = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)
        self._create_mock_fit("ride_a.fit", t_base, 3600)
        self._create_mock_fit("ride_b.fit", t_base, 3600)

        mp4_intervals = [(t_base + timedelta(minutes=5), t_base + timedelta(minutes=20))]
        matched, diag = find_best_fit_match(mp4_intervals, self.temp_dir)
        self.assertIsNone(matched, "Ambiguous match must not arbitrarily choose one candidate")
        self.assertEqual(diag.get("status"), "ambiguous")


    def test_multi_clip_real_duration_and_gap_isolation(self):
        """Test multi-clip scoring: overlap is sum of clip overlaps, gap is ignored, coverage is total_overlap / sum(durations)."""
        t_base = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)
        # FIT spans 10:00:00 to 11:00:00 (3600s)
        fit_path = self._create_mock_fit("long_ride.fit", t_base, 3600.0)

        # Clip 1: 10:05:00 to 10:08:00 (180s)
        # Gap: 10:08:00 to 10:30:00 (22 min gap - no recording!)
        # Clip 2: 10:30:00 to 10:55:00 (1500s)
        c1_start = t_base + timedelta(minutes=5)
        c1_end = c1_start + timedelta(seconds=180)
        c2_start = t_base + timedelta(minutes=30)
        c2_end = c2_start + timedelta(seconds=1500)

        intervals = [(c1_start, c1_end, 180.0, "exact"), (c2_start, c2_end, 1500.0, "exact")]
        matched, diag = find_best_fit_match(intervals, self.temp_dir)

        self.assertEqual(matched, fit_path)
        self.assertEqual(diag.get("overlap"), 1680.0)  # 180 + 1500
        self.assertAlmostEqual(diag.get("coverage"), 1.0, places=5)
        self.assertEqual(diag.get("confidence"), "exact")

    def test_degraded_fallback_flag(self):
        """When duration falls back to 600s, confidence must be 'degraded'."""
        t_base = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)
        fit_path = self._create_mock_fit("ride.fit", t_base, 3600.0)
        # Missing end_dt triggers 600s degraded fallback
        intervals = [(t_base + timedelta(minutes=5), None)]
        matched, diag = find_best_fit_match(intervals, self.temp_dir)
        self.assertEqual(matched, fit_path)
        self.assertEqual(diag.get("confidence"), "degraded")


class TestAutoExportFilename(unittest.TestCase):
    def test_5min_rounding(self):
        cases = [
            (datetime(2026, 9, 5, 19, 7, 0), "20260905-1905"),
            (datetime(2026, 9, 5, 19, 8, 0), "20260905-1910"),
            (datetime(2026, 9, 5, 19, 12, 0), "20260905-1910"),
            (datetime(2026, 9, 5, 19, 13, 0), "20260905-1915"),
            (datetime(2026, 9, 5, 23, 58, 0), "20260906-0000"),
        ]
        for dt, expected in cases:
            rd = round_dt_to_nearest_5min(dt)
            self.assertEqual(rd.strftime("%Y%m%d-%H%M"), expected)

    def test_summer_and_winter_dst_local_time(self):
        """Verify that UTC is converted to local time and DST is NOT hardcoded to UTC+2."""
        from src.video_helpers import resolve_local_datetime
        # Summer date (August): Europe/Warsaw is UTC+2
        dt_summer_utc = datetime(2026, 8, 31, 13, 3, 35, 299000)
        loc_summer, reason_s = resolve_local_datetime(dt_summer_utc)
        filename_summer = generate_auto_export_filename(dt_summer_utc)
        self.assertEqual(loc_summer.hour, 15)
        self.assertEqual(loc_summer.minute, 3)
        self.assertEqual(filename_summer, "20260831-1505.mp4")

        # Winter date (January): Europe/Warsaw is UTC+1 (NOT UTC+2!)
        dt_winter_utc = datetime(2026, 1, 15, 13, 3, 35, 299000)
        loc_winter, reason_w = resolve_local_datetime(dt_winter_utc)
        filename_winter = generate_auto_export_filename(dt_winter_utc)
        self.assertEqual(loc_winter.hour, 14)
        self.assertEqual(loc_winter.minute, 3)
        self.assertEqual(filename_winter, "20260115-1405.mp4")

    def test_fit_activity_timezone_offset_priority(self):
        """FIT activity offset takes precedence over system default."""
        dt_utc = datetime(2026, 8, 31, 13, 3, 35)
        class MockFit:
            timezone_offset_hours = 3.0  # e.g. UTC+3

        fn = generate_auto_export_filename(dt_utc, fit_data=MockFit())
        # 13:03 + 3h = 16:03 -> rounded to 16:05
        self.assertEqual(fn, "20260831-1605.mp4")

    def test_project_timezone_offset_priority(self):
        """Explicit tz_offset_hours takes precedence over system default."""
        dt_utc = datetime(2026, 8, 31, 13, 3, 35)
        fn = generate_auto_export_filename(dt_utc, tz_offset_hours=1.0)
        # 13:03 + 1h = 14:03 -> rounded to 14:05
        self.assertEqual(fn, "20260831-1405.mp4")

    def test_collision_handling(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Using tz_offset_hours=0 for predictable stem
            dt = datetime(2026, 9, 5, 19, 7, 0)
            # 1st call -> 20260905-1905.mp4
            name1 = generate_auto_export_filename(dt, target_dir=temp_dir, tz_offset_hours=0.0)
            self.assertEqual(name1, "20260905-1905.mp4")
            (temp_dir / name1).touch()

            # 2nd call -> 20260905-1905-01.mp4
            name2 = generate_auto_export_filename(dt, target_dir=temp_dir, tz_offset_hours=0.0)
            self.assertEqual(name2, "20260905-1905-01.mp4")
            (temp_dir / name2).touch()

            # 3rd call -> 20260905-1905-02.mp4
            name3 = generate_auto_export_filename(dt, target_dir=temp_dir, tz_offset_hours=0.0)
            self.assertEqual(name3, "20260905-1905-02.mp4")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestProjectMixinFitResolution(unittest.TestCase):
    def test_effective_fit_path_precedence_and_safety(self):
        """Test the priority rule: manual FIT/GPX passed -> use it; neither -> AutoFIT scan; no crash."""
        # 1. Manual fit absent, manual gpx absent -> AutoFIT scan matches
        def simulate_resolution(in_fit, in_gpx, auto_matched):
            effective_fit_path = in_fit
            effective_gpx_path = in_gpx
            if not effective_fit_path and not effective_gpx_path:
                if auto_matched:
                    effective_fit_path = auto_matched
            return effective_fit_path, effective_gpx_path

        # Case A: AutoFIT finds one FIT -> matched FIT is used downstream
        eff_fit, eff_gpx = simulate_resolution("", "", "matched.fit")
        self.assertEqual(eff_fit, "matched.fit")

        # Case B: Manual FIT provided -> AutoFIT does not replace it
        eff_fit, eff_gpx = simulate_resolution("manual.fit", "", "matched.fit")
        self.assertEqual(eff_fit, "manual.fit")

        # Case C: Manual GPX provided -> AutoFIT does not run
        eff_fit, eff_gpx = simulate_resolution("", "track.gpx", "matched.fit")
        self.assertEqual(eff_fit, "")
        self.assertEqual(eff_gpx, "track.gpx")

        # Case D: No FIT found -> load continues without crash
        eff_fit, eff_gpx = simulate_resolution("", "", None)
        self.assertEqual(eff_fit, "")
        self.assertEqual(eff_gpx, "")

    def test_project_mixin_bg_load_has_no_unbound_local(self):
        """Bytecode verification: fit_path must not be in co_varnames of bg_load."""
        from src.gui.qt._mixins.project_mixin import ProjectMixin
        import threading

        class DummySignals:
            class DummySignal:
                def emit(self, *args, **kwargs): pass
            sig_progress = DummySignal()
            sig_error = DummySignal()
            sig_video_info_ready = DummySignal()
            sig_video_duration_ready = DummySignal()
            sig_data_streams_ready = DummySignal()
            sig_default_export_name_ready = DummySignal()
            sig_schedule_mpv_hwdec_check = DummySignal()

        class DummyController(ProjectMixin):
            def __init__(self):
                self.signals = DummySignals()
                self.video_paths = []
                self.ffprobe_path = "ffprobe"
                self.base_dir = Path(".")
                self.fps = 30.0
                self.layout = {}
                self._startup_preset_path = None
                self.fit_path = None
                self.gpx_path = None
            def _clear_caches(self): pass
            def is_using_mpv(self): return False

        ctrl = DummyController()
        executed_threads = []
        orig_start = threading.Thread.start
        threading.Thread.start = lambda t: executed_threads.append(t)
        try:
            ctrl._on_files_selected(["dummy.mp4"], "", "")
            self.assertEqual(len(executed_threads), 1)
            target_fn = executed_threads[0]._target
            # Python's symbol table: local variable assignment creates a slot in co_varnames.
            # If fit_path was assigned, it would be in co_varnames, triggering UnboundLocalError
            # when read before assignment.
            self.assertNotIn("fit_path", target_fn.__code__.co_varnames,
                             "fit_path must NOT be in bg_load.co_varnames (would trigger UnboundLocalError)")
            self.assertIn("effective_fit_path", target_fn.__code__.co_varnames,
                          "effective_fit_path must be the local variable in bg_load")
            self.assertIn("effective_gpx_path", target_fn.__code__.co_varnames,
                          "effective_gpx_path must be the local variable in bg_load")
        finally:
            threading.Thread.start = orig_start



class TestElapsedSecondsSingleSourceAndParity(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 9, 1, 4, 24, 36, tzinfo=timezone.utc)
        self.target_t = datetime(2026, 9, 1, 4, 24, 48, 795271, tzinfo=timezone.utc)
        # 12.795271s after activity start

    def test_fit_with_active_mapper(self):
        """Hierarchy #1: FIT + valid ActiveTimeMapper -> active elapsed from activity start."""
        from src.indicators.frame_data import prepare_overlay_frame_data
        events = [
            {"event": "timer", "event_type": "start", "timestamp": self.t0},
            {"event": "timer", "event_type": "stop_all", "timestamp": self.t0 + timedelta(hours=1)},
        ]
        mapper = build_active_time_mapper_from_events(events)
        fit_data = {"active_time_mapper": mapper}

        data = prepare_overlay_frame_data(
            layout={},
            target_dt=self.target_t,
            start_dt_utc=self.target_t,  # video starts at 04:24:48
            fit_data=fit_data,
            speed_samples=[], track_samples=[], alt_samples=[], tz_offset_hours=2.0,
        )
        self.assertAlmostEqual(data["elapsed_seconds"], 12.795271, places=5)
        self.assertAlmostEqual(data["avg_speed_kmh"], 0.0)

    def test_pause_freezes_elapsed_seconds(self):
        """Active elapsed seconds must stay frozen while in pause."""
        from src.indicators.frame_data import prepare_overlay_frame_data
        t_pause_start = self.t0 + timedelta(minutes=10)
        t_pause_end = self.t0 + timedelta(minutes=15)
        events = [
            {"event": "timer", "event_type": "start", "timestamp": self.t0},
            {"event": "timer", "event_type": "stop_all", "timestamp": t_pause_start},
            {"event": "timer", "event_type": "start", "timestamp": t_pause_end},
            {"event": "timer", "event_type": "stop_all", "timestamp": self.t0 + timedelta(hours=1)},
        ]
        mapper = build_active_time_mapper_from_events(events)
        fit_data = {"active_time_mapper": mapper}

        # During pause at minute 12
        t_mid_pause = self.t0 + timedelta(minutes=12)
        data = prepare_overlay_frame_data(
            layout={},
            target_dt=t_mid_pause,
            start_dt_utc=self.t0,
            fit_data=fit_data,
            speed_samples=[], track_samples=[], alt_samples=[], tz_offset_hours=2.0,
        )
        # Should freeze at 10 minutes (600s)
        self.assertEqual(data["elapsed_seconds"], 600.0)

    def test_fit_without_mapper_fallback(self):
        """Hierarchy #2: FIT without active mapper -> target_dt - fit_activity_start."""
        from src.indicators.frame_data import prepare_overlay_frame_data
        fit_data = {"track": [(self.t0, 50.0, 20.0)]}
        data = prepare_overlay_frame_data(
            layout={},
            target_dt=self.target_t,
            start_dt_utc=self.target_t,
            fit_data=fit_data,
            speed_samples=[], track_samples=[], alt_samples=[], tz_offset_hours=2.0,
        )
        self.assertAlmostEqual(data["elapsed_seconds"], 12.795271, places=5)

    def test_no_fit_project_elapsed(self):
        """Hierarchy #3: No FIT -> project_elapsed_s."""
        from src.indicators.frame_data import prepare_overlay_frame_data
        data = prepare_overlay_frame_data(
            layout={},
            target_dt=self.target_t,
            start_dt_utc=self.target_t,
            project_elapsed_s=42.5,
            speed_samples=[], track_samples=[], alt_samples=[], tz_offset_hours=2.0,
        )
        self.assertEqual(data["elapsed_seconds"], 42.5)

    def test_sanity_check_prevents_48100h(self):
        """Sanity check: camera default clock (2021-03-07) with 2026 video must never output 48100h."""
        from src.indicators.frame_data import prepare_overlay_frame_data
        bad_start_dt = datetime(2021, 3, 7, 0, 0, 5, tzinfo=timezone.utc)
        data = prepare_overlay_frame_data(
            layout={},
            target_dt=self.target_t,
            start_dt_utc=bad_start_dt,
            speed_samples=[], track_samples=[], alt_samples=[], tz_offset_hours=2.0,
        )
        # Absurd interval of 5.5 years must be clamped/sanitized to 0.0, never 48100h
        self.assertEqual(data["elapsed_seconds"], 0.0)

    def test_sanity_check_active_exceeding_wall(self):
        """Sanity check: buggy mapper returning active > wall + tolerance falls back cleanly."""
        from src.indicators.frame_data import prepare_overlay_frame_data
        class BuggyMapper:
            start_dt = datetime(2026, 9, 1, 4, 24, 36)
            def wall_to_active_seconds(self, dt):
                return 999999.0  # Absurd
        data = prepare_overlay_frame_data(
            layout={},
            target_dt=self.target_t,
            start_dt_utc=self.target_t,
            fit_data={"active_time_mapper": BuggyMapper()},
            speed_samples=[], track_samples=[], alt_samples=[], tz_offset_hours=2.0,
        )
        # Should fall back cleanly to wall_elapsed (12.795271s)
        self.assertAlmostEqual(data["elapsed_seconds"], 12.795271, places=5)

    def test_preview_render_precompute_parity(self):
        """Preview, Reference render, and Precomputed frame cache must have identical elapsed_seconds."""
        from src.indicators.frame_data import prepare_overlay_frame_data
        from src.telemetry_precompute import build_telemetry_cache
        from src.telemetry_active_time import build_active_time_mapper_from_events

        events = [
            {"event": "timer", "event_type": "start", "timestamp": self.t0},
            {"event": "timer", "event_type": "stop_all", "timestamp": self.t0 + timedelta(hours=1)},
        ]
        mapper = build_active_time_mapper_from_events(events)
        fit_data = {"active_time_mapper": mapper}

        # Preview call
        prev_data = prepare_overlay_frame_data(
            layout={}, target_dt=self.target_t, start_dt_utc=self.target_t, tz_offset_hours=2.0,
            fit_data=fit_data, project_elapsed_s=0.0,
            speed_samples=[], track_samples=[], alt_samples=[],
        )

        # Reference render call
        ref_data = prepare_overlay_frame_data(
            layout={}, target_dt=self.target_t, start_dt_utc=self.target_t, tz_offset_hours=2.0,
            fit_data=fit_data, project_elapsed_s=0.0,
            speed_samples=[], track_samples=[], alt_samples=[],
        )

        # Precompute call
        cache = build_telemetry_cache(
            layout={},
            base_dt=self.target_t,
            start_dt_utc=self.target_t,
            tz_offset_hours=2.0,
            total_frames=5,
            target_fps=30.0,
            fit_data=fit_data,
            speed_samples=[], track_samples=[], alt_samples=[],
        )
        pre_data = cache.lookup(0)

        self.assertAlmostEqual(prev_data["elapsed_seconds"], 12.795271, places=5)
        self.assertAlmostEqual(prev_data["elapsed_seconds"], ref_data["elapsed_seconds"], places=5)
        self.assertAlmostEqual(ref_data["elapsed_seconds"], pre_data["elapsed_seconds"], places=5)


class TestAvgSpeedPreviewPrecomputeParity(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 9, 1, 4, 24, 36, tzinfo=timezone.utc)
        self.target_dt = self.t0 + timedelta(seconds=1868)
        events = [
            {"event": "timer", "event_type": "start", "timestamp": self.t0},
            {"event": "timer", "event_type": "stop_all", "timestamp": self.t0 + timedelta(hours=1)},
        ]
        self.mapper = build_active_time_mapper_from_events(events)
        self.fit_data = {
            "active_time_mapper": self.mapper,
            "distance": [
                (self.t0, 0.0),
                (self.target_dt, 10247.76),
                (self.t0 + timedelta(hours=1), 20000.0),
            ],
            "speed": [
                (self.t0, 5.0),
                (self.target_dt, 6.0),
            ],
        }

    def test_preview_precompute_avg_speed_parity(self):
        from src.indicators.frame_data import prepare_overlay_frame_data
        from src.telemetry_precompute import build_telemetry_cache

        prev_data = prepare_overlay_frame_data(
            layout={},
            target_dt=self.target_dt,
            start_dt_utc=self.t0,
            tz_offset_hours=2.0,
            fit_data=self.fit_data,
            project_elapsed_s=1868.0,
            speed_samples=[], track_samples=[], alt_samples=[],
        )

        cache = build_telemetry_cache(
            layout={},
            base_dt=self.target_dt,
            start_dt_utc=self.t0,
            tz_offset_hours=2.0,
            total_frames=1,
            target_fps=1.0,
            fit_data=self.fit_data,
            speed_samples=[], track_samples=[], alt_samples=[],
        )
        pre_data = cache.lookup(0)

        expected_avg = (10247.76 / 1868.0) * 3.6  # ~19.749 km/h
        self.assertAlmostEqual(prev_data["elapsed_seconds"], 1868.0, places=3)
        self.assertAlmostEqual(pre_data["elapsed_seconds"], 1868.0, places=3)
        self.assertAlmostEqual(prev_data["avg_speed_kmh"], expected_avg, places=4)
        self.assertAlmostEqual(pre_data["avg_speed_kmh"], expected_avg, places=4)
        self.assertAlmostEqual(prev_data["avg_speed_kmh"], pre_data["avg_speed_kmh"], places=6)
        # Verify it is NEVER in the order of 16000 km/h
        self.assertLess(prev_data["avg_speed_kmh"], 100.0)

    def test_distance_source_independence(self):
        from src.indicators.frame_data import prepare_overlay_frame_data
        from src.telemetry_precompute import build_telemetry_cache

        bogus_gpmf_track = [
            (self.t0, 0.0),
            (self.t0 + timedelta(seconds=1), 8356251.84),
            (self.target_dt, 8366499.60),
        ]

        # Case 1: GPMF source
        layout_gpmf = {
            "indicators": {
                "dist_visual": {"enabled": True, "source": "gpmf"},
                "dist_text": {"enabled": True, "source": "gpmf"},
            }
        }
        prev_gpmf = prepare_overlay_frame_data(
            layout=layout_gpmf, target_dt=self.target_dt, start_dt_utc=self.t0,
            tz_offset_hours=2.0, fit_data=self.fit_data, project_elapsed_s=1868.0,
            speed_samples=[], track_samples=bogus_gpmf_track, alt_samples=[],
        )
        cache_gpmf = build_telemetry_cache(
            layout=layout_gpmf, base_dt=self.target_dt, start_dt_utc=self.t0,
            tz_offset_hours=2.0, total_frames=1, target_fps=1.0,
            fit_data=self.fit_data, speed_samples=[], track_samples=bogus_gpmf_track, alt_samples=[],
        )
        pre_gpmf = cache_gpmf.lookup(0)

        # Case 2: FIT source
        layout_fit = {
            "indicators": {
                "dist_visual": {"enabled": True, "source": "fit"},
                "dist_text": {"enabled": True, "source": "fit"},
            }
        }
        prev_fit = prepare_overlay_frame_data(
            layout=layout_fit, target_dt=self.target_dt, start_dt_utc=self.t0,
            tz_offset_hours=2.0, fit_data=self.fit_data, project_elapsed_s=1868.0,
            speed_samples=[], track_samples=bogus_gpmf_track, alt_samples=[],
        )
        cache_fit = build_telemetry_cache(
            layout=layout_fit, base_dt=self.target_dt, start_dt_utc=self.t0,
            tz_offset_hours=2.0, total_frames=1, target_fps=1.0,
            fit_data=self.fit_data, speed_samples=[], track_samples=bogus_gpmf_track, alt_samples=[],
        )
        pre_fit = cache_fit.lookup(0)

        # Case 3: Disabled
        layout_dis = {
            "indicators": {
                "dist_visual": {"enabled": False},
                "dist_text": {"enabled": False},
            }
        }
        prev_dis = prepare_overlay_frame_data(
            layout=layout_dis, target_dt=self.target_dt, start_dt_utc=self.t0,
            tz_offset_hours=2.0, fit_data=self.fit_data, project_elapsed_s=1868.0,
            speed_samples=[], track_samples=bogus_gpmf_track, alt_samples=[],
        )
        cache_dis = build_telemetry_cache(
            layout=layout_dis, base_dt=self.target_dt, start_dt_utc=self.t0,
            tz_offset_hours=2.0, total_frames=1, target_fps=1.0,
            fit_data=self.fit_data, speed_samples=[], track_samples=bogus_gpmf_track, alt_samples=[],
        )
        pre_dis = cache_dis.lookup(0)

        # In GPMF case, displayed distance comes from GPMF (~8366 km)
        self.assertGreater(prev_gpmf["distance_m"], 8000000.0)
        self.assertGreater(pre_gpmf["distance_m"], 8000000.0)

        # In FIT case, displayed distance comes from FIT (~10.2 km)
        self.assertAlmostEqual(prev_fit["distance_m"], 10247.76, delta=1.0)
        self.assertAlmostEqual(pre_fit["distance_m"], 10247.76, delta=1.0)

        # But average speed in ALL cases MUST be ~19.75 km/h and NOT 16000 km/h!
        expected_avg = (10247.76 / 1868.0) * 3.6
        for p, name in [
            (prev_gpmf, "prev_gpmf"), (pre_gpmf, "pre_gpmf"),
            (prev_fit, "prev_fit"), (pre_fit, "pre_fit"),
            (prev_dis, "prev_dis"), (pre_dis, "pre_dis"),
        ]:
            self.assertAlmostEqual(p["avg_speed_kmh"], expected_avg, places=4, msg=f"{name} avg_speed failed")


if __name__ == "__main__":
    unittest.main()



