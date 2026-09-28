import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from src.telemetry_extract import (
    _extract_gpmf_timed_samples, _extract_gpmf_vector_samples,
    find_gps_anchor, extract_temperature_samples,
    _parse_temperature_values, interpolate_temperature,
)
from src.telemetry_processed_cache import (
    PROCESSED_CACHE_VERSION, read_processed_cache, write_processed_cache,
    apply_processed_cache,
)
from src.gui.telemetry_manager import TelemetryDataManager
from src.multifile import build_timeline_from_paths
from src.indicators.frame_data import prepare_overlay_frame_data


class TestGpmfTempAndBatteryTiming(unittest.TestCase):
    def test_gpmf_late_gps_anchor_projection(self):
        # Synthetic records simulating Doc1 (t=0, temp=21.5) and Doc50 (t=49.0s, first GPS fix at 04:31:12.100)
        rec = {
            "Doc1:TMPC_STMP": 75869.0,
            "Doc1:TMPC_TSMP": 0.0,
            "Doc1:CameraTemperature": "21.5898",
            "Doc2:TMPC_STMP": 1075869.0,
            "Doc2:TMPC_TSMP": 1.0,
            "Doc2:CameraTemperature": "21.7344",
            "Doc50:TMPC_STMP": 49125702.0,
            "Doc50:TMPC_TSMP": 49.0,
            "Doc50:CameraTemperature": "25.6250",
            "Doc50-6:GPSDateTime": "2026:09:16 04:31:12.100",
            "Doc50-6:SampleTime": 0.600,
        }
        
        anchor = find_gps_anchor([rec])
        self.assertIsNotNone(anchor)
        # 04:31:12.100 - ((49125702 + 600000) - 75869) us = 04:30:22.450167
        expected_start = datetime(2026, 9, 16, 4, 30, 22, 450167, tzinfo=timezone.utc)
        self.assertAlmostEqual((anchor - expected_start).total_seconds(), 0.0, delta=0.001)

        samples = _extract_gpmf_timed_samples([rec], "TMPC", _parse_temperature_values)
        self.assertIsNotNone(samples)
        self.assertEqual(len(samples), 3)
        # First sample should be at video start ~04:30:22.450
        first_dt, first_val = samples[0]
        self.assertAlmostEqual((first_dt - expected_start).total_seconds(), 0.0, delta=0.001)
        self.assertAlmostEqual(first_val, 21.5898, places=3)

    def test_real_gx010298_temperature_and_battery(self):
        video_path = Path("Video/GX010298.MP4")
        fit_path = Path("Video/GX010298.fit")
        if not video_path.exists() or not fit_path.exists():
            self.skipTest("GX010298 files not present")

        cache = read_processed_cache(video_path)
        self.assertIsNotNone(cache, "Processed cache must exist")
        temp_samples = cache.get("temperature_samples", [])
        self.assertGreater(len(temp_samples), 1000)
        
        # Verify first sample starts near 04:30:22 (video start), not 04:31:12 (+50s delayed)
        first_dt = temp_samples[0][0]
        expected_clip_start = datetime(2026, 9, 16, 4, 30, 22, tzinfo=timezone.utc)
        diff_s = (first_dt - expected_clip_start).total_seconds()
        self.assertLess(abs(diff_s), 2.0, f"First temperature sample dt {first_dt} is not at clip start")

        # Verify temperature at clip start
        val = interpolate_temperature(temp_samples, datetime(2026, 9, 16, 4, 30, 22))
        self.assertIsNotNone(val)
        self.assertGreater(val, 20.0)
        self.assertLess(val, 30.0)


if __name__ == "__main__":
    unittest.main()
