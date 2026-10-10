import unittest
from pathlib import Path
from src.render_preparation import RenderPreparationService
from src.gui.telemetry_manager import TelemetryDataManager

class TestCacheKeyFitContract(unittest.TestCase):
    def test_telemetry_fit_path_none_with_explicit_path(self):
        telem = TelemetryDataManager()
        
        # Scenario: telemetry has no fit_path, but explicitly passed
        kw_fit = Path("explicit_test.fit")
        key = RenderPreparationService.compute_cache_key(
            video_paths=["video.mp4"],
            total_frames=100,
            target_fps=30.0,
            fit_path=kw_fit,
        )
        # Should not throw exception, and should use explicit path.
        self.assertIsNotNone(key)
        
        # Contrast with no fit path
        key_none = RenderPreparationService.compute_cache_key(
            video_paths=["video.mp4"],
            total_frames=100,
            target_fps=30.0,
            fit_path=None,
        )
        self.assertNotEqual(key, key_none, "Explicit fit_path must change cache key")

    def test_fit_switch_invalidates_cache(self):
        key1 = RenderPreparationService.compute_cache_key(
            video_paths=["video.mp4"],
            total_frames=100,
            target_fps=30.0,
            fit_path=Path("fit1.fit")
        )
        key2 = RenderPreparationService.compute_cache_key(
            video_paths=["video.mp4"],
            total_frames=100,
            target_fps=30.0,
            fit_path=Path("fit2.fit")
        )
        self.assertNotEqual(key1, key2, "FIT_SWITCH_INVALIDATES_CACHE failed")

if __name__ == "__main__":
    unittest.main()

