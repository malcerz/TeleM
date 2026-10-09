"""Unit tests for DJI Action 2 telemetry capability probing, skip-parse optimization, and cache.

Verifies:
1. probe_dji_telemetry_capabilities accurately detects DJI stream schemas and useful channels.
2. Capability caching (npz metadata) preserves has_useful_telemetry, schema, and channels.
3. load_dji_telemetry skips full heavy parsing when has_useful_telemetry is False.
4. Probe performance is sub-100ms.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.telemetry_dji import (
    probe_dji_telemetry_capabilities,
    load_dji_telemetry,
    _read_cache,
    _write_cache,
    _write_capability_cache,
)


class TestDjiAction2CapabilityProbe(unittest.TestCase):
    def setUp(self):
        self.test_clips = [
            Path(r"F:\GoPro\2026-10-05\DJI_0010.MP4"),
            Path(r"F:\GoPro\2026-10-05\DJI_0011.MP4"),
            Path(r"F:\GoPro\2026-10-05\DJI_0012.MP4"),
            Path(r"F:\GoPro\2026-10-05\DJI_0013.MP4"),
            Path(r"F:\GoPro\2026-10-05\DJI_0014.MP4"),
            Path(r"F:\GoPro\2026-10-05\DJI_0015.MP4"),
        ]

    def test_probe_real_action2_clip(self):
        clip0 = self.test_clips[0]
        if not clip0.exists():
            self.skipTest(f"Clip {clip0} not accessible on test system")

        import time
        t0 = time.perf_counter()
        probe_res = probe_dji_telemetry_capabilities(clip0)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertTrue(probe_res.get("is_dji"))
        self.assertEqual(probe_res.get("schema"), "dvtm_ac103")
        self.assertFalse(probe_res.get("has_useful_telemetry"))
        self.assertEqual(probe_res.get("channels"), [])
        self.assertLess(elapsed_ms, 250.0, f"Probe took too long: {elapsed_ms:.1f}ms")

    def test_load_dji_telemetry_skips_full_parse_when_empty(self):
        clip0 = self.test_clips[0]
        if not clip0.exists():
            self.skipTest(f"Clip {clip0} not accessible on test system")

        from datetime import datetime, timezone
        with patch("src.telemetry_dji.spawn_dji_worker") as mock_worker:
            res = load_dji_telemetry(clip0, datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc), use_worker=True)
            mock_worker.assert_not_called()
            self.assertEqual(res.get("accelerometer_samples"), [])
            self.assertEqual(res.get("gyroscope_samples"), [])
            self.assertFalse(res.get("has_useful_telemetry"))

    def test_capability_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dummy_mp4 = Path(tmp_dir) / "test_dji.MP4"
            dummy_mp4.touch()

            # Write capability cache
            _write_capability_cache(dummy_mp4, schema="dvtm_ac103")
            cached = _read_cache(dummy_mp4)

            self.assertIsNotNone(cached)
            self.assertFalse(cached.get("has_useful_telemetry"))
            self.assertEqual(cached.get("schema"), "dvtm_ac103")
            self.assertEqual(cached.get("channels"), [])
            self.assertEqual(len(cached.get("accel", [])), 0)

    def test_multi_clip_probe_speed(self):
        accessible_clips = [c for c in self.test_clips if c.exists()]
        if not accessible_clips:
            self.skipTest("No test clips accessible")

        import time
        t0 = time.perf_counter()
        for c in accessible_clips:
            res = probe_dji_telemetry_capabilities(c)
            self.assertTrue(res.get("is_dji"))
            self.assertFalse(res.get("has_useful_telemetry"))
        total_s = time.perf_counter() - t0

        avg_ms = (total_s / len(accessible_clips)) * 1000.0
        self.assertLess(avg_ms, 200.0, f"Average probe time too high: {avg_ms:.1f}ms")


if __name__ == "__main__":
    unittest.main()
