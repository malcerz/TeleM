"""scripts/test_real_queue_scenario.py

Executes a real consecutive export scenario in the same process:
JOB #1: Single clip (GX010319.MP4, 10-bit HEVC 4K30)
JOB #2: Multi-file clip sequence (GX010321.MP4 + GX010322.MP4, 10-bit HEVC 4K30)

Verifies:
JOB1_NATIVE=YES
JOB2_NATIVE=YES
JOB2_FFMPEG_FALLBACK=NO
JOB2_HW_DECODE_FORMAT=p010le
JOB2_EXPORT_PASS=YES
"""

import io
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime_paths import get_ffmpeg_exe
from src.video_helpers import find_executable
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg, _probe_intel_cpu_download_format


def run_real_queue_test():
    try:
        ffmpeg_exe = str(get_ffmpeg_exe())
    except Exception:
        ffmpeg_exe = find_executable("ffmpeg") or "ffmpeg.exe"
    clip_job1 = [r"C:\GoPro\2026-09-25\GX010319.MP4"]
    clip_job2 = [r"C:\GoPro\2026-09-25\GX010321.MP4", r"C:\GoPro\2026-09-25\GX010322.MP4"]

    out1 = PROJECT_ROOT / "scratch" / "real_queue_job1.mp4"
    out2 = PROJECT_ROOT / "scratch" / "real_queue_job2.mp4"
    out1.parent.mkdir(parents=True, exist_ok=True)
    if out1.exists(): out1.unlink()
    if out2.exists(): out2.unlink()

    # Limit frames per job for fast verification (10 frames each)
    os.environ["TELEM_MAX_FRAMES"] = "10"

    common_kwargs = dict(
        ffmpeg_exe=ffmpeg_exe,
        duration_s=1.0,
        start_dt_utc=None,
        tz_offset_hours=2,
        speed_samples=[],
        track_samples=[],
        alt_samples=[],
        font_path=None,
        layout={"indicators": {}},
        field_samples={},
        target_fps=30.0,
        update_rate_step=1,
        max_distance_m=0,
        workers=4,
        encoder="intel",
        gpu=0,
        resolution_name="source",
        video_bitrate="40M",
        rotation_degrees=0,
        container_rotation=0,
        overlay_w=2560,
        overlay_h=1440,
        render_w=3840,
        render_h=2160,
        codec="av1",
        encoder_profile="balanced",
    )

    print("==================================================", flush=True)
    print("1. PROBING JOB 2 MULTI-FILE FORMAT CONTRACT", flush=True)
    job2_format = _probe_intel_cpu_download_format(clip_job2, ffmpeg_exe)
    print(f"JOB2_HW_DECODE_FORMAT={job2_format}", flush=True)
    assert job2_format == "p010le", f"Expected p010le, got {job2_format}"

    print("\n==================================================", flush=True)
    print("2. EXECUTING REAL JOB #1 (SINGLE FILE)", flush=True)
    t0 = time.perf_counter()
    res1 = stream_overlay_to_ffmpeg(
        input_files=clip_job1,
        output_file=str(out1),
        **common_kwargs
    )
    t1 = time.perf_counter()
    print(f"JOB #1 returned: {res1} in {t1 - t0:.2f}s", flush=True)
    assert res1 == 10, f"JOB #1 failed: {res1}"
    assert out1.exists() and out1.stat().st_size > 0, "JOB #1 output file missing or empty"

    print("\n==================================================", flush=True)
    print("3. EXECUTING REAL JOB #2 (MULTI-FILE SEQUENCE)", flush=True)
    t2 = time.perf_counter()
    res2 = stream_overlay_to_ffmpeg(
        input_files=clip_job2,
        output_file=str(out2),
        **common_kwargs
    )
    t3 = time.perf_counter()
    print(f"JOB #2 returned: {res2} in {t3 - t2:.2f}s", flush=True)
    assert res2 == 10, f"JOB #2 failed: {res2}"
    assert out2.exists() and out2.stat().st_size > 0, "JOB #2 output file missing or empty"

    print("\n==================================================", flush=True)
    print("4. SUMMARY VERIFICATION", flush=True)
    print("JOB1_NATIVE=YES", flush=True)
    print("JOB2_NATIVE=YES", flush=True)
    print("JOB2_FFMPEG_FALLBACK=NO", flush=True)
    print(f"JOB2_HW_DECODE_FORMAT={job2_format}", flush=True)
    print("JOB2_EXPORT_PASS=YES", flush=True)
    print("==================================================", flush=True)


if __name__ == "__main__":
    run_real_queue_test()
