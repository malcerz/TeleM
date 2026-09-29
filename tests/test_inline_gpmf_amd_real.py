"""Opt-in production AMD A/B harness for inline GoPro metadata muxing."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from src.ffmpeg.gpmf_export import prepare_inline_gpmf
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.gui.layout_manager import resolve_font_path
from src.multifile import VideoClip, VideoTimeline


def _probe(ffprobe: str, path: Path) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration:stream=index,codec_type,codec_name,codec_tag_string,duration,nb_frames,sample_rate,channels",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def _data_hash(ffmpeg: str, path: Path, index: int) -> tuple[int, str]:
    payload = subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-i", str(path),
         "-map", f"0:{index}", "-c", "copy", "-f", "data", "-"],
        capture_output=True, check=True,
    ).stdout
    return len(payload), hashlib.sha256(payload).hexdigest()


@pytest.mark.skipif(os.environ.get("TELEM_RUN_AMD_INLINE_E2E") != "1", reason="opt-in AMD hardware workload")
def test_real_amd_inline_gpmf_off_on_same_short_source():
    source = Path(os.environ["TELEM_GPMF_E2E_SOURCE"])
    assert source.is_file()
    ffmpeg = os.environ.get("TELEM_FFMPEG_EXE", r"C:\tools\ffmpeg.exe")
    ffprobe = os.environ.get("TELEM_FFPROBE_EXE", r"C:\tools\ffprobe.exe")
    source_info = _probe(ffprobe, source)
    duration_s = float(source_info["format"]["duration"])
    fps = 30000 / 1001
    frames = int(next(s for s in source_info["streams"] if s["codec_type"] == "video")["nb_frames"])
    started_at = datetime(2026, 9, 16, 4, 30, 22)
    clip = VideoClip(
        path=source, duration_s=duration_s, fps=fps, width=3840, height=2160,
        frame_count=frames, source_duration_s=duration_s,
        absolute_start_dt=started_at,
    )
    timeline = VideoTimeline.from_clips([clip], base_dt=started_at)
    layout = {
        "version": 6,
        "global": {"text_outline": 3},
        "indicators": {},
        "custom_texts": [{
            "enabled": True, "text": "INLINE GPMF AMD", "x": 50.0, "y": 50.0,
            "font_size": 4.0, "color": "#FF8000", "rotation": 0,
        }],
    }
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "scratch" / "inline_gpmf" / f"amd_e2e_{int(time.time())}"
    output_dir.mkdir(parents=True, exist_ok=False)
    outputs = {}
    timings = {}

    for enabled in (False, True):
        label = "on" if enabled else "off"
        output = output_dir / f"amd_{label}.mp4"
        plan = None
        if enabled:
            plan = prepare_inline_gpmf(
                ffmpeg_exe=ffmpeg, ffprobe_exe=ffprobe,
                source_paths=[source], output_path=output,
                video_timeline=timeline, duration_s=duration_s,
            )
            assert plan.enabled and plan.status == "ready_full"
        start = time.perf_counter()
        try:
            result = stream_overlay_to_ffmpeg(
                ffmpeg_exe=ffmpeg,
                input_files=[str(source)], output_file=str(output),
                duration_s=duration_s, start_dt_utc=started_at, tz_offset_hours=2,
                speed_samples=[], track_samples=[], alt_samples=[],
                font_path=resolve_font_path("Arial"), layout=layout,
                field_samples={}, target_fps=fps, update_rate_step=1,
                workers=1, encoder="amd", gpu=0, video_bitrate="25M",
                resolution_name="1080p", render_w=1920, render_h=1080,
                overlay_w=1920, overlay_h=1080,
                rotation_degrees=0, container_rotation=0,
                video_timeline=timeline, inline_gpmf_plan=plan,
            )
        finally:
            if plan is not None:
                plan.cleanup()
        elapsed = time.perf_counter() - start
        assert result == frames
        assert output.is_file()
        info = _probe(ffprobe, output)
        assert any(s["codec_type"] == "video" for s in info["streams"])
        assert any(s["codec_type"] == "audio" for s in info["streams"])
        gpmd = [s for s in info["streams"] if s.get("codec_tag_string") == "gpmd"]
        assert bool(gpmd) == enabled
        assert not list(output_dir.glob("*.gpmf-*.mp4"))
        assert not Path(str(output) + ".part").exists()
        outputs[label] = (output, info, gpmd)
        timings[label] = elapsed
        print(f"AMD_INLINE_{label.upper()}_OUTPUT={output}")
        print(f"AMD_INLINE_{label.upper()}_ELAPSED_S={elapsed:.3f}")
        print(f"AMD_INLINE_{label.upper()}_SIZE={output.stat().st_size}")

    source_data = next(s for s in source_info["streams"] if s.get("codec_tag_string") == "gpmd")
    output_data = outputs["on"][2][0]
    assert source_data["nb_frames"] == output_data["nb_frames"]
    source_payload = _data_hash(ffmpeg, source, source_data["index"])
    output_payload = _data_hash(ffmpeg, outputs["on"][0], output_data["index"])
    assert source_payload == output_payload
    native_dir = os.environ.get("TELEM_GPMF_NATIVE_DIR")
    if native_dir:
        sys.path.insert(0, native_dir)
    from src.telemetry_native_gpmf import extract_gpmf_native, native_channel_counts

    source_native = extract_gpmf_native(source)
    output_native = extract_gpmf_native(outputs["on"][0])
    assert source_native and output_native
    assert source_native["payload_count"] == output_native["payload_count"]
    assert native_channel_counts(source_native) == native_channel_counts(output_native)
    assert any(native_channel_counts(output_native).values())
    print(f"NATIVE_GPMF_CHANNELS={native_channel_counts(output_native)}")
    print(f"SOURCE_GPMF_BYTES={source_payload[0]}")
    print(f"OUTPUT_GPMF_BYTES={output_payload[0]}")
    print(f"SOURCE_GPMF_SHA256={source_payload[1]}")
    print(f"OUTPUT_GPMF_SHA256={output_payload[1]}")

    def audio(info):
        item = next(s for s in info["streams"] if s["codec_type"] == "audio")
        return {k: item.get(k) for k in ("codec_name", "sample_rate", "channels", "duration", "nb_frames")}

    assert audio(outputs["off"][1]) == audio(outputs["on"][1])
    print(f"AUDIO_PARITY={audio(outputs['on'][1])}")
    print(f"AMD_INLINE_AB_ELAPSED_S={timings}")
