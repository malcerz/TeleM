"""Verify real hardware orientation execution and override handling."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime_paths import get_ffmpeg_exe
from src.video_helpers import find_executable
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.telemetry_extract import get_container_rotation


def main():
    clip_180 = r"D:\GoPro\TEST\GX010305.MP4"
    clip_0 = r"D:\GoPro\20261002-0625.mp4"

    ffmpeg_exe = str(get_ffmpeg_exe())
    scratch_dir = PROJECT_ROOT / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    print("==================================================", flush=True)
    print("1. PROBE TEST: get_container_rotation", flush=True)
    print("==================================================", flush=True)
    rot_180 = get_container_rotation(ffmpeg_exe, clip_180)
    print(f"clip_180 probed container rotation: {rot_180}° (expected 180°)", flush=True)
    assert rot_180 == 180, f"Expected 180, got {rot_180}"

    rot_0 = get_container_rotation(ffmpeg_exe, clip_0)
    print(f"clip_0 probed container rotation: {rot_0}° (expected 0°)", flush=True)
    assert rot_0 == 0, f"Expected 0, got {rot_0}"

    os.environ["TELEM_MAX_FRAMES"] = "15"

    test_cases = [
        ("AUTO_180", clip_180, 180, 180, None),
        ("MANUAL_0", clip_180, 0, 0, 0),
        ("MANUAL_90", clip_180, 90, 90, 90),
        ("MANUAL_180", clip_180, 180, 180, 180),
        ("MANUAL_270", clip_180, 270, 270, 270),
        ("AUTO_0", clip_0, 0, 0, None),
    ]

    for label, clip, rot_deg, cont_rot, rot_over in test_cases:
        out_file = scratch_dir / f"orient_{label.lower()}.mp4"
        if out_file.exists():
            out_file.unlink()

        print(f"\n--- Testing {label} on {Path(clip).name} (override={rot_over}) ---", flush=True)
        res = stream_overlay_to_ffmpeg(
            ffmpeg_exe=ffmpeg_exe,
            input_files=[clip],
            output_file=str(out_file),
            duration_s=0.5,
            start_dt_utc=None,
            tz_offset_hours=2,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            font_path=None,
            layout={"indicators": {}},
            field_samples={},
            target_fps=29.97,
            update_rate_step=1,
            max_distance_m=0,
            workers=4,
            encoder="amd",
            gpu=0,
            resolution_name="source",
            video_bitrate="40M",
            rotation_degrees=rot_deg,
            container_rotation=cont_rot,
            rotation_override=rot_over,
            overlay_w=3840,
            overlay_h=2160,
            render_w=3840,
            render_h=2160,
            codec="hevc",
            encoder_profile="speed",
        )
        assert res > 0, f"{label} returned {res} frames"
        assert out_file.exists() and out_file.stat().st_size > 0, f"{label} output missing"
        print(f"{label}: SUCCESS ({res} frames, size={out_file.stat().st_size} bytes)", flush=True)

    print("\n==================================================", flush=True)
    print("ALL REAL HARDWARE ORIENTATION TESTS PASSED!", flush=True)
    print("==================================================", flush=True)


if __name__ == "__main__":
    main()
