"""Unit and integration tests for Preview vs Final Export Parity with Skip Pauses (charts_skip_pauses).

Verifies:
1. Preview (prepare_overlay_frame_data) vs Vectorized Export Cache (build_telemetry_cache_vectorized)
   have exact 0.000 difference across all fields.
2. With charts_skip_pauses=True:
   - Paused frames clamp speed, cadence, and power to 0.0.
   - current_position maps temporally by active_elapsed / total_active_seconds.
   - elapsed_seconds remains frozen at active elapsed time during pause.
3. With charts_skip_pauses=False:
   - Paused frames do not clamp speed/cadence/power to 0.0 (preserves sensor holds).
   - current_position is linear video progress: frame_idx / (total_frames - 1).
4. Cache key and semantic data signature differentiate charts_skip_pauses=True vs False.
"""

import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.render_preparation import RenderPreparationService
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_active_time import ActiveTimeMapper


class TestSkipPausesParity(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 10, 5, 12, 0, 0)
        # Active intervals:
        # [12:00:00 to 12:02:00] (120s active)
        # Pause: [12:02:00 to 12:05:00] (180s pause)
        # [12:05:00 to 12:07:00] (120s active)
        # Total active = 240s, Total elapsed = 420s
        self.intervals = [
            (self.t0, self.t0 + timedelta(seconds=120)),
            (self.t0 + timedelta(seconds=300), self.t0 + timedelta(seconds=420)),
        ]
        self.mapper = ActiveTimeMapper(self.intervals, start_dt=self.t0, end_dt=self.t0 + timedelta(seconds=420))

        # Synthetic FIT data (samples recorded during active intervals)
        times = (
            [self.t0 + timedelta(seconds=s) for s in range(0, 121, 10)]
            + [self.t0 + timedelta(seconds=s) for s in range(300, 421, 10)]
        )
        self.speeds = [(t, 25.0) for t in times]
        self.tracks = [(t, float(i * 70.0)) for i, t in enumerate(times)]
        self.alts = [(t, 100.0 + float(i)) for i, t in enumerate(times)]
        self.cads = [(t, 85.0) for t in times]
        self.powers = [(t, 200.0) for t in times]

        self.fit_data = {
            "speed": self.speeds,
            "track": self.tracks,
            "distance": self.tracks,
            "alt": self.alts,
            "cadence": self.cads,
            "power": self.powers,
            "active_time_mapper": self.mapper,
        }

        self.layout_base = {
            "indicators": {
                "speed_visual": {"enabled": True, "source": "fit", "field": "speed"},
                "dist_visual": {"enabled": True, "source": "fit", "field": "distance"},
                "alt_visual": {"enabled": True, "source": "fit", "field": "alt"},
                "cad_text": {"enabled": True, "source": "fit", "field": "cad"},
                "power_text": {"enabled": True, "source": "fit", "field": "power"},
                "hr_text": {"enabled": True, "source": "fit", "field": "hr"},
                "time_display": {"enabled": True},
            }
        }

    def test_cache_key_and_signature_differentiation(self):
        service = RenderPreparationService()
        layout_on = dict(self.layout_base)
        layout_on["charts_skip_pauses"] = True

        layout_off = dict(self.layout_base)
        layout_off["charts_skip_pauses"] = False

        sig_on = service.extract_semantic_data_signature(layout_on)
        sig_off = service.extract_semantic_data_signature(layout_off)
        self.assertNotEqual(sig_on, sig_off, "Semantic data signature must differentiate charts_skip_pauses")

        key_on = service.compute_cache_key(
            video_paths=["test.mp4"],
            total_frames=100,
            target_fps=30.0,
            layout=layout_on,
        )
        key_off = service.compute_cache_key(
            video_paths=["test.mp4"],
            total_frames=100,
            target_fps=30.0,
            layout=layout_off,
        )
        self.assertNotEqual(key_on, key_off, "Cache key must differentiate charts_skip_pauses")

    def test_skip_pauses_parity_synthetic(self):
        target_fps = 10.0
        # 420 seconds at 10 fps = 4200 frames
        total_frames = 4200
        service = RenderPreparationService()

        from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value

        for skip_pauses in (True, False):
            layout = dict(self.layout_base)
            layout["charts_skip_pauses"] = skip_pauses

            cache = service.build_telemetry_cache_vectorized(
                layout=layout,
                base_dt=self.t0,
                tz_offset_hours=0.0,
                start_dt_utc=self.t0,
                speed_samples=self.speeds,
                track_samples=self.tracks,
                alt_samples=self.alts,
                fit_data=self.fit_data,
                total_frames=total_frames,
                target_fps=target_fps,
            )

            init_worker(
                1920, 1080, "C:/Windows/Fonts/arial.ttf", layout, {},
                fit_data=self.fit_data,
                start_dt_utc=self.t0,
                target_fps=target_fps,
                total_overlay_frames=total_frames,
            )

            # Test frames:
            # frame 500: t=50s (active period 1)
            # frame 1500: t=150s (pause period: 120s to 300s)
            # frame 2000: t=200s (pause period)
            # frame 3500: t=350s (active period 2: 300s to 420s)
            test_frames = [500, 1500, 2000, 3500]

            for f_idx in test_frames:
                t_s = f_idx / target_fps
                target_dt = self.t0 + timedelta(seconds=t_s)
                is_paused = self.mapper.is_paused(target_dt)

                prev = prepare_overlay_frame_data(
                    layout=layout,
                    target_dt=target_dt,
                    tz_offset_hours=0.0,
                    start_dt_utc=self.t0,
                    speed_samples=self.speeds,
                    track_samples=self.tracks,
                    alt_samples=self.alts,
                    fit_data=self.fit_data,
                    total_frames=total_frames,
                    current_index=f_idx,
                    resolve_cache_value=_resolve_cache_value,
                )
                exp = cache.lookup(f_idx)

                # Assert exact parity between preview and export cache
                for field in ("speed_value", "distance_m", "alt_value", "elapsed_seconds", "avg_speed_kmh", "current_position", "cad_value", "power_value"):
                    pv = prev.get(field)
                    ev = exp.get(field)
                    if pv is None and ev is None:
                        continue
                    self.assertIsNotNone(pv, f"Field {field} is None in preview at frame {f_idx}")
                    self.assertIsNotNone(ev, f"Field {field} is None in export at frame {f_idx}")
                    self.assertAlmostEqual(float(pv), float(ev), places=4, msg=f"Parity mismatch on {field} at frame {f_idx} (skip_pauses={skip_pauses})")

                # Verify pause behavior
                if is_paused and skip_pauses:
                    self.assertEqual(prev["speed_value"], 0.0)
                    self.assertEqual(exp["speed_value"], 0.0)
                    self.assertEqual(prev["cad_value"], 0.0)
                    self.assertEqual(exp["cad_value"], 0.0)
                    self.assertEqual(prev["power_value"], 0.0)
                    self.assertEqual(exp["power_value"], 0.0)
                    # elapsed seconds is frozen at 120s
                    self.assertAlmostEqual(prev["elapsed_seconds"], 120.0, places=2)
                    self.assertAlmostEqual(exp["elapsed_seconds"], 120.0, places=2)
                    # current_position is mapped to active time fraction 120 / 240 = 0.5
                    self.assertAlmostEqual(prev["current_position"], 0.5, places=3)
                    self.assertAlmostEqual(exp["current_position"], 0.5, places=3)
                elif is_paused and not skip_pauses:
                    # In skip_pauses=False, speed and cadence are not clamped to 0
                    self.assertGreater(prev["speed_value"], 0.0)
                    self.assertGreater(exp["speed_value"], 0.0)
                    # current_position is linear video progress: f_idx / (total_frames - 1)
                    expected_pos = f_idx / (total_frames - 1)
                    self.assertAlmostEqual(prev["current_position"], expected_pos, places=3)
                    self.assertAlmostEqual(exp["current_position"], expected_pos, places=3)

    def test_real_fit_activity_parity(self):
        fit_path = Path(r"C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24614281884.fit")
        if not fit_path.exists():
            self.skipTest(f"Real FIT file {fit_path} not found on test machine")

        from telemetry_fit import parse_fit, sync_fit_to_video
        from src.ffmpeg.worker_cache import init_worker, _resolve_cache_value

        records = parse_fit(fit_path)
        real_fit_data = sync_fit_to_video(records, None)
        mapper = real_fit_data.get("active_time_mapper")
        self.assertIsNotNone(mapper)

        service = RenderPreparationService()
        base_dt = mapper.start_dt
        target_fps = 30.0
        total_frames = 7500

        for skip_pauses in (True, False):
            layout = dict(self.layout_base)
            layout["charts_skip_pauses"] = skip_pauses

            cache = service.build_telemetry_cache_vectorized(
                layout=layout,
                base_dt=base_dt,
                tz_offset_hours=2.0,
                start_dt_utc=base_dt,
                speed_samples=real_fit_data.get("speed", []),
                track_samples=real_fit_data.get("track", []),
                alt_samples=real_fit_data.get("alt", []),
                fit_data=real_fit_data,
                total_frames=total_frames,
                target_fps=target_fps,
            )

            init_worker(
                1920, 1080, "C:/Windows/Fonts/arial.ttf", layout, {},
                fit_data=real_fit_data,
                start_dt_utc=base_dt,
                target_fps=target_fps,
                total_overlay_frames=total_frames,
            )

            test_frames = [500, 1000, 2500, 5000, 6000, 7000]
            for f_idx in test_frames:
                t_s = f_idx / target_fps
                target_dt = base_dt + timedelta(seconds=t_s)

                prev = prepare_overlay_frame_data(
                    layout=layout,
                    target_dt=target_dt,
                    tz_offset_hours=2.0,
                    start_dt_utc=base_dt,
                    speed_samples=real_fit_data.get("speed", []),
                    track_samples=real_fit_data.get("track", []),
                    alt_samples=real_fit_data.get("alt", []),
                    fit_data=real_fit_data,
                    total_frames=total_frames,
                    current_index=f_idx,
                    resolve_cache_value=_resolve_cache_value,
                )
                exp = cache.lookup(f_idx)

                for field in ("speed_value", "distance_m", "alt_value", "elapsed_seconds", "avg_speed_kmh", "current_position", "cad_value", "hr_value"):
                    pv = prev.get(field)
                    ev = exp.get(field)
                    if pv is None and ev is None:
                        continue
                    self.assertIsNotNone(pv, f"Real FIT {field} is None in preview at frame {f_idx}")
                    self.assertIsNotNone(ev, f"Real FIT {field} is None in export at frame {f_idx}")
                    self.assertAlmostEqual(float(pv), float(ev), places=4, msg=f"Real FIT mismatch on {field} at frame {f_idx}")


if __name__ == "__main__":
    unittest.main()
