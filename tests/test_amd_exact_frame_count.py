"""
Regression test for TeleM AMD exact frame-count contract.
Verifies that floating point durations (e.g. 1000 / 29.97) do not suffer
from IEEE-754 math.ceil off-by-one issues and produce exact integer frame counts.
"""
import math
import pytest
from pathlib import Path
from src.multifile import VideoClip, VideoTimeline


@pytest.mark.parametrize("n_frames", [1, 2, 10, 100, 125, 250, 500, 1000])
@pytest.mark.parametrize("target_fps", [29.97, 30000 / 1001.0, 30.0, 59.94, 60.0])
def test_exact_frame_count_math(n_frames, target_fps):
    """Ensure duration_s = n_frames / target_fps rounds exactly back to n_frames."""
    duration_s = n_frames / target_fps
    calc_frames = max(1, int(round(duration_s * target_fps)))
    assert calc_frames == n_frames, f"Expected {n_frames}, got {calc_frames} for fps={target_fps}"


def test_timeline_output_frame_count_exact():
    """Ensure VideoClip and VideoTimeline maintain exact frame counts."""
    target_fps = 29.97
    clip = VideoClip(Path("dummy.mp4"), duration_s=1000.0 / target_fps, fps=target_fps)
    assert clip.output_frame_count(target_fps) == 1000

    timeline = VideoTimeline([clip])
    assert timeline.output_frame_counts(target_fps) == [1000]
    assert timeline.output_frame_count(target_fps) == 1000


def test_multifile_boundary_exact_count():
    """Ensure multi-clip timelines maintain exact sum of frames."""
    target_fps = 29.97
    c1 = VideoClip(Path("c1.mp4"), duration_s=150.0 / target_fps, fps=target_fps)
    c2 = VideoClip(Path("c2.mp4"), duration_s=150.0 / target_fps, fps=target_fps)
    timeline = VideoTimeline([c1, c2])
    counts = timeline.output_frame_counts(target_fps)
    assert counts == [150, 150]
    assert sum(counts) == 300
