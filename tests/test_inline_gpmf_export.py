"""Inline gpmd selection and final-mux contracts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ffmpeg import gpmf_export


def test_inline_mux_mapping_is_opt_in_and_uses_detected_stream_index(tmp_path):
    assert gpmf_export.inline_gpmf_mux_args(None, 2) == ([], [])
    plan = gpmf_export.InlineGpmfPlan("ready_full", tmp_path / "GoPro source.mp4", 4)
    inputs, maps = gpmf_export.inline_gpmf_mux_args(plan, 2)
    assert inputs == ["-i", str(plan.input_path)]
    assert maps == ["-map", "2:4", "-c:d", "copy", "-copy_unknown", "-tag:d:0", "gpmd"]


def test_single_full_source_is_mapped_directly_without_metadata_copy(monkeypatch, tmp_path):
    source = tmp_path / "GX010305.MP4"
    monkeypatch.setattr(gpmf_export, "detect_gpmf_stream", lambda *_: {"index": 3})
    monkeypatch.setattr(gpmf_export, "_probe_duration", lambda *_: 25.025)
    copied = []
    monkeypatch.setattr(gpmf_export, "_run_metadata_copy", lambda *a, **k: copied.append((a, k)))

    plan = gpmf_export.prepare_inline_gpmf(
        ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
        source_paths=[source], output_path=tmp_path / "out.mp4",
        duration_s=25.025,
    )
    assert plan.status == "ready_full"
    assert plan.input_path == source
    assert plan.stream_index == 3
    assert plan.temporary_dir is None
    assert copied == []


def test_missing_source_gpmf_keeps_export_without_data_mapping(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(gpmf_export, "detect_gpmf_stream", lambda *_: None)
    monkeypatch.setattr(gpmf_export, "_probe_duration", lambda *_: 25.0)
    plan = gpmf_export.prepare_inline_gpmf(
        ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
        source_paths=[tmp_path / "plain.mp4"], output_path=tmp_path / "out.mp4",
        duration_s=25.0,
    )
    assert plan.status == "source_missing"
    assert gpmf_export.inline_gpmf_mux_args(plan, 2) == ([], [])
    assert gpmf_export.GPMF_MISSING_MESSAGE in capsys.readouterr().out


def test_partial_multifile_gpmf_is_disabled_safely(monkeypatch, tmp_path, capsys):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    monkeypatch.setattr(
        gpmf_export, "detect_gpmf_stream",
        lambda _probe, source: {"index": 2} if Path(source) == first else None,
    )
    timeline = SimpleNamespace(clips=[
        SimpleNamespace(path=first, local_start_s=0, duration_s=10, source_duration_s=10),
        SimpleNamespace(path=second, local_start_s=0, duration_s=10, source_duration_s=10),
    ])
    plan = gpmf_export.prepare_inline_gpmf(
        ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
        source_paths=[first, second], output_path=tmp_path / "out.mp4",
        video_timeline=timeline,
    )
    assert plan.status == "partial_multifile_missing"
    assert not plan.enabled
    assert "GPMF: niepełne dane w zestawie wieloplikowym" in capsys.readouterr().out


def test_trimmed_multifile_plan_uses_source_local_bounds_and_exact_concat_durations(monkeypatch, tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    source_indices = {first: 3, second: 5}

    def detect(_probe, source):
        source = Path(source)
        return {"index": source_indices[source]} if source in source_indices else {"index": 0}

    commands = []
    def copy(command, _cancel_event=None):
        commands.append(command)
        Path(command[-1]).write_bytes(b"metadata only")

    monkeypatch.setattr(gpmf_export, "detect_gpmf_stream", detect)
    monkeypatch.setattr(gpmf_export, "_run_metadata_copy", copy)
    timeline = SimpleNamespace(clips=[
        SimpleNamespace(path=first, local_start_s=5.0, duration_s=10.0, source_duration_s=30.0),
        SimpleNamespace(path=second, local_start_s=2.0, duration_s=8.0, source_duration_s=20.0),
    ])
    plan = gpmf_export.prepare_inline_gpmf(
        ffmpeg_exe="ffmpeg", ffprobe_exe="ffprobe",
        source_paths=[first, second], output_path=tmp_path / "out.mp4",
        video_timeline=timeline,
    )
    try:
        assert plan.enabled and plan.status == "ready_metadata_timeline"
        assert len(commands) == 3
        assert commands[0][commands[0].index("-ss") + 1] == "5.000000000"
        assert "0:3" in commands[0]
        assert commands[1][commands[1].index("-ss") + 1] == "2.000000000"
        assert "0:5" in commands[1]
        assert commands[2][commands[2].index("-map") + 1] == "0:0"
        concat_text = (plan.temporary_dir / "segments.ffconcat").read_text(encoding="utf-8")
        assert "duration 10.000000000" in concat_text
        assert "duration 8.000000000" in concat_text
    finally:
        temporary_dir = plan.temporary_dir
        plan.cleanup()
    assert not temporary_dir.exists()


def _real_source() -> tuple[Path, str, str]:
    source_text = os.environ.get("TELEM_GPMF_E2E_SOURCE")
    if not source_text:
        pytest.skip("Set TELEM_GPMF_E2E_SOURCE to a short real GoPro MP4 for payload validation")
    source = Path(source_text)
    if not source.is_file():
        pytest.skip(f"GPMF source unavailable: {source}")
    ffmpeg = shutil.which("ffmpeg") or r"C:\tools\ffmpeg.exe"
    ffprobe = shutil.which("ffprobe") or r"C:\tools\ffprobe.exe"
    return source, ffmpeg, ffprobe


def _probe(ffprobe: str, path: Path) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration:stream=index,codec_type,codec_name,codec_tag_string,nb_frames,duration,sample_rate,channels",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def _raw_data(ffmpeg: str, path: Path, index: int) -> bytes:
    return subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-i", str(path),
         "-map", f"0:{index}", "-c", "copy", "-f", "data", "-"],
        capture_output=True, check=True,
    ).stdout


def test_real_single_mux_preserves_gpmf_payload_and_audio(tmp_path):
    source, ffmpeg, ffprobe = _real_source()
    source_info = _probe(ffprobe, source)
    source_duration = float(source_info["format"]["duration"])
    plan = gpmf_export.prepare_inline_gpmf(
        ffmpeg_exe=ffmpeg, ffprobe_exe=ffprobe,
        source_paths=[source], output_path=tmp_path / "inline.mp4",
        duration_s=source_duration,
    )
    assert plan.status == "ready_full"
    gpmf_inputs, gpmf_maps = gpmf_export.inline_gpmf_mux_args(plan, 1)
    output = tmp_path / "inline.mp4"
    command = [
        ffmpeg, "-hide_banner", "-v", "error", "-y",
        "-i", str(source), *gpmf_inputs,
        "-map", "0:v:0", "-map", "0:a:0?", *gpmf_maps,
        "-c:v", "copy", "-c:a", "copy",
        "-t", f"{source_duration:.6f}", str(output),
    ]
    subprocess.run(command, check=True)
    output_info = _probe(ffprobe, output)
    source_data = next(stream for stream in source_info["streams"] if stream.get("codec_tag_string") == "gpmd")
    output_data = next(stream for stream in output_info["streams"] if stream.get("codec_tag_string") == "gpmd")
    assert source_data["nb_frames"] == output_data["nb_frames"]
    assert hashlib.sha256(_raw_data(ffmpeg, source, source_data["index"])).digest() == hashlib.sha256(
        _raw_data(ffmpeg, output, output_data["index"])
    ).digest()
    source_audio = next(stream for stream in source_info["streams"] if stream["codec_type"] == "audio")
    output_audio = next(stream for stream in output_info["streams"] if stream["codec_type"] == "audio")
    assert {key: source_audio.get(key) for key in ("codec_name", "sample_rate", "channels", "duration")} == {
        key: output_audio.get(key) for key in ("codec_name", "sample_rate", "channels", "duration")
    }


def test_real_trimmed_multifile_metadata_timeline_has_rebased_samples(tmp_path):
    source, ffmpeg, ffprobe = _real_source()
    source_duration = float(_probe(ffprobe, source)["format"]["duration"])
    if source_duration < 25:
        pytest.skip("Needs at least 25 seconds of source GPMF")
    timeline = SimpleNamespace(clips=[
        SimpleNamespace(path=source, local_start_s=5, duration_s=10, source_duration_s=source_duration),
        SimpleNamespace(path=source, local_start_s=15, duration_s=10, source_duration_s=source_duration),
    ])
    plan = gpmf_export.prepare_inline_gpmf(
        ffmpeg_exe=ffmpeg, ffprobe_exe=ffprobe,
        source_paths=[source, source], output_path=tmp_path / "inline.mp4",
        video_timeline=timeline,
    )
    try:
        info = _probe(ffprobe, plan.input_path)
        stream = next(stream for stream in info["streams"] if stream.get("codec_tag_string") == "gpmd")
        assert int(stream["nb_frames"]) == 20
        packets = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", str(stream["index"]),
             "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(plan.input_path)],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        times = [float(item) for item in packets]
        assert times[0] == pytest.approx(0.0, abs=0.001)
        assert times[10] == pytest.approx(10.0, abs=0.001)
        assert times[-1] < 20.0
    finally:
        plan.cleanup()
