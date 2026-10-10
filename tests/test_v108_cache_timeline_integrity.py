import os
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.multifile import build_timeline_from_paths
from src.render_preparation import RenderPreparationService
from src.ffmpeg.streaming import resolve_amd_gui_range_plan

class TestV108CacheTimelineIntegrity(unittest.TestCase):
    def test_cache_integrity_full_vs_cut(self):
        video_path = r"F:\GoPro\2026-09-25\GX010321.MP4"
        if not os.path.exists(video_path):
            self.skipTest(f"Video {video_path} not found")

        layout = {"indicators": {}}
        target_fps = 29.97
        
        # 2. FULL TIMELINE
        full_timeline = build_timeline_from_paths([video_path])
        full_frames = full_timeline.output_frame_count(target_fps)
        base_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Mock some samples so it has data to compare
        speed_samples = [(base_dt + timedelta(seconds=i), float(i)) for i in range(4000)]
        dist_samples = [(base_dt + timedelta(seconds=i), float(i*10)) for i in range(4000)]
        alt_samples = [(base_dt + timedelta(seconds=i), float(100)) for i in range(4000)]

        full_cache_key = RenderPreparationService.compute_cache_key(
            video_paths=[video_path],
            total_frames=full_frames,
            target_fps=target_fps,
            start_dt_utc=base_dt,
            layout=layout,
            video_timeline=full_timeline
        )
        
        full_cache = RenderPreparationService.get_or_build(
            layout=layout,
            base_dt=base_dt,
            video_paths=[video_path],
            total_frames=full_frames,
            target_fps=target_fps,
            video_timeline=full_timeline,
            cache_key=full_cache_key,
            speed_samples=speed_samples,
            track_samples=dist_samples,  # dist is pulled from track_samples or fit, wait!
            alt_samples=alt_samples,
        )

        # 3. CUT TIMELINE (e.g. 01:00 to 02:00)
        # Using exact logic from GUI/Streaming
        cut_start_s = 60.0
        cut_end_s = 120.0
        
        cut_regions = [(0.0, cut_start_s), (cut_end_s, float(full_timeline.project_duration_s))]
        cut_timeline, cut_frames, _ = resolve_amd_gui_range_plan(
            video_timeline=full_timeline,
            cut_regions=cut_regions,
            target_fps=target_fps,
            fallback_duration_s=full_timeline.project_duration_s
        )
        
        cut_cache_key = RenderPreparationService.compute_cache_key(
            video_paths=[video_path],
            total_frames=cut_frames,
            target_fps=target_fps,
            start_dt_utc=base_dt,
            layout=layout,
            video_timeline=cut_timeline
        )
        
        # Keys MUST be different
        self.assertNotEqual(full_cache_key, cut_cache_key, "Full and Cut timelines must have different cache keys!")
        
        cut_cache = RenderPreparationService.get_or_build(
            layout=layout,
            base_dt=base_dt,
            video_paths=[video_path],
            total_frames=cut_frames,
            target_fps=target_fps,
            video_timeline=cut_timeline,
            cache_key=cut_cache_key,
            speed_samples=speed_samples,
            track_samples=dist_samples,
            alt_samples=alt_samples,
        )

        # 4. PARITY CHECK
        # Output frame 0 of CUT timeline corresponds to local_start_s = 60.0
        # In FULL timeline, 60.0 seconds corresponds to frame: 60.0 * 29.97 = 1798
        frame_offset = int(round(cut_start_s * target_fps))

        for cut_idx in [0, cut_frames // 2, cut_frames - 1]:
            full_idx = frame_offset + cut_idx
            
            # Extract scalars
            cut_speed = cut_cache.get_scalar("speed", cut_idx)
            full_speed = full_cache.get_scalar("speed", full_idx)
            
            cut_dist = cut_cache.get_scalar("dist", cut_idx)
            full_dist = full_cache.get_scalar("dist", full_idx)
            
            cut_alt = cut_cache.get_scalar("alt", cut_idx)
            full_alt = full_cache.get_scalar("alt", full_idx)
            
            self.assertAlmostEqual(cut_speed, full_speed, places=3, msg=f"Speed mismatch at cut_idx={cut_idx}")
            self.assertAlmostEqual(cut_dist, full_dist, places=3, msg=f"Dist mismatch at cut_idx={cut_idx}")
            self.assertAlmostEqual(cut_alt, full_alt, places=3, msg=f"Alt mismatch at cut_idx={cut_idx}")

if __name__ == '__main__':
    unittest.main()
