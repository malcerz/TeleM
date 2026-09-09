from __future__ import annotations

from pathlib import Path

import pytest

from src.ffmpeg.streaming import resolve_amd_gui_range_plan
from src.multifile import VideoClip, VideoTimeline


FPS = 30.0


def _timeline(*durations: float) -> VideoTimeline:
    clips = [
        VideoClip(
            path=Path(f"clip_{index + 1}.mp4"),
            duration_s=duration,
            source_duration_s=duration,
            fps=FPS,
            frame_count=int(duration * FPS),
        )
        for index, duration in enumerate(durations)
    ]
    return VideoTimeline.from_clips(clips)


@pytest.mark.parametrize(
    ("timeline", "cuts", "expected_frames", "expected_ranges"),
    [
        (
            _timeline(20.0),
            [(0.0, 5.0), (12.0, 20.0)],
            210,
            [("clip_1.mp4", 5.0, 12.0)],
        ),
        (
            _timeline(10.0, 20.0),
            [(0.0, 2.0), (8.0, 30.0)],
            180,
            [("clip_1.mp4", 2.0, 8.0)],
        ),
        (
            _timeline(10.0, 20.0),
            [(0.0, 8.0), (14.0, 30.0)],
            180,
            [("clip_1.mp4", 8.0, 10.0), ("clip_2.mp4", 0.0, 4.0)],
        ),
        (
            _timeline(10.0, 20.0),
            [(0.0, 12.0), (18.0, 30.0)],
            180,
            [("clip_2.mp4", 2.0, 8.0)],
        ),
        (
            _timeline(10.0, 20.0),
            [],
            900,
            [("clip_1.mp4", 0.0, 10.0), ("clip_2.mp4", 0.0, 20.0)],
        ),
    ],
    ids=["single-middle", "clip1-only", "cross-clip", "clip2-only", "whole"],
)
def test_amd_gui_range_has_one_frame_and_source_range_contract(
    timeline, cuts, expected_frames, expected_ranges
):
    effective, requested, duration = resolve_amd_gui_range_plan(
        timeline, cuts, FPS, timeline.project_duration_s
    )

    actual_ranges = [
        (clip.path.name, clip.local_start_s, clip.local_end_s)
        for clip in effective.clips
    ]
    accounting = {
        "requested": requested,
        "decoded": effective.output_frame_count(FPS),
        "native_processed": effective.output_frame_count(FPS),
        "muxed": int(round(duration * FPS)),
    }

    assert actual_ranges == expected_ranges
    assert accounting == {
        "requested": expected_frames,
        "decoded": expected_frames,
        "native_processed": expected_frames,
        "muxed": expected_frames,
    }


def test_amd_gui_range_rejects_a_fully_cut_timeline():
    timeline = _timeline(10.0, 20.0)

    with pytest.raises(ValueError, match="entire video timeline"):
        resolve_amd_gui_range_plan(
            timeline, [(20.0, 40.0), (-5.0, 22.0)], FPS, 30.0
        )

