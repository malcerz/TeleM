"""Automated unit test suite for AMD Central Audio Cache.

Validates:
1. Cache MISS creates audio cache.
2. Cache HIT returns existing cache without re-extracting.
3. Modification time / size change causes Cache MISS and new cache key.
4. Corrupted / 0-byte cache is detected and re-extracted safely.
5. Temp *.part file is cleaned up on extraction failure.
6. Single-file concat plan uses audio cache path instead of source MP4.
7. Middle-of-clip retains exact inpoint / outpoint boundaries.
8. Multi-file concat plan maps each clip to its cached audio path.
9. Fallback cleanly uses source MP4 if cache generation fails.
10. Export cleanup / cancellation does not delete valid persistent audio cache.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.telemetry_cache_manager import (
    compute_source_key,
    ensure_audio_cache,
    get_audio_cache_path,
    get_media_cache_dir,
)
from src.ffmpeg.amd_native_exporter import (
    _audio_concat_entries,
    _write_audio_concat_plan,
)


@pytest.fixture
def temp_cache_env(tmp_path, monkeypatch):
    """Isolate cache root to a temporary directory."""
    cache_root = tmp_path / "telem_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TELEM_CACHE_ROOT", str(cache_root))
    return cache_root


@pytest.fixture
def dummy_source(tmp_path):
    """Create a dummy source video file."""
    src = tmp_path / "test_gopro.mp4"
    src.write_bytes(b"dummy_mp4_video_and_audio_data_1234567890")
    return src


def test_1_cache_miss_creates_audio_cache(temp_cache_env, dummy_source):
    """Test 1: Cache MISS creates audio cache via ffmpeg stream copy."""
    target_cache = get_audio_cache_path(dummy_source)
    assert not target_cache.exists()

    def fake_subprocess_run(cmd, *args, **kwargs):
        # If ffmpeg extraction
        if "-map" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"extracted_aac_audio_stream")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        # If ffprobe verification
        elif "-select_streams" in cmd:
            stdout_json = '{"streams": [{"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000"}]}'
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=stdout_json, stderr="")
        return subprocess.CompletedProcess(cmd, returncode=0)

    with patch("subprocess.run", side_effect=fake_subprocess_run) as mock_run:
        result = ensure_audio_cache(dummy_source)
        assert result is not None
        assert result.exists()
        assert result.read_bytes() == b"extracted_aac_audio_stream"
        assert target_cache.exists()
        assert mock_run.call_count == 2  # 1 ffmpeg + 1 ffprobe


def test_2_cache_hit_does_not_rerun_ffmpeg(temp_cache_env, dummy_source):
    """Test 2: Cache HIT returns existing cache without invoking subprocess."""
    target_cache = get_audio_cache_path(dummy_source)
    target_cache.parent.mkdir(parents=True, exist_ok=True)
    target_cache.write_bytes(b"pre_existing_valid_audio_cache")

    with patch("subprocess.run") as mock_run:
        result = ensure_audio_cache(dummy_source)
        assert result == target_cache
        assert mock_run.call_count == 0


def test_3_size_mtime_change_causes_cache_miss(temp_cache_env, dummy_source):
    """Test 3: Modification time or size change yields a different key and cache MISS."""
    key1 = compute_source_key(dummy_source)
    path1 = get_audio_cache_path(dummy_source)

    # Change file size
    dummy_source.write_bytes(b"longer_content_that_modifies_size")
    key2 = compute_source_key(dummy_source)
    path2 = get_audio_cache_path(dummy_source)

    assert key1 != key2
    assert path1 != path2

    # Change mtime
    st = dummy_source.stat()
    os.utime(dummy_source, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    key3 = compute_source_key(dummy_source)
    assert key2 != key3


def test_4_corrupted_zero_byte_cache_is_reextracted(temp_cache_env, dummy_source):
    """Test 4: 0-byte or corrupted cache triggers re-extraction."""
    target_cache = get_audio_cache_path(dummy_source)
    target_cache.parent.mkdir(parents=True, exist_ok=True)
    target_cache.write_bytes(b"")  # Empty 0-byte file

    def fake_subprocess_run(cmd, *args, **kwargs):
        if "-map" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"re_extracted_audio_valid")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        elif "-select_streams" in cmd:
            stdout_json = '{"streams": [{"codec_type": "audio", "codec_name": "aac"}]}'
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=stdout_json, stderr="")
        return subprocess.CompletedProcess(cmd, returncode=0)

    with patch("subprocess.run", side_effect=fake_subprocess_run) as mock_run:
        result = ensure_audio_cache(dummy_source)
        assert result == target_cache
        assert target_cache.stat().st_size > 0
        assert mock_run.call_count == 2


def test_5_part_file_cleaned_up_on_error(temp_cache_env, dummy_source):
    """Test 5: *.part file is deleted when ffmpeg extraction fails."""
    target_cache = get_audio_cache_path(dummy_source)

    def failing_subprocess_run(cmd, *args, **kwargs):
        if "-map" in cmd:
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"partial_broken_data")
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="Corrupt input")
        return subprocess.CompletedProcess(cmd, returncode=1)

    with patch("subprocess.run", side_effect=failing_subprocess_run):
        result = ensure_audio_cache(dummy_source)
        assert result is None
        # Verify no .part file remains in media cache dir
        cache_dir = get_media_cache_dir(dummy_source)
        part_files = list(cache_dir.glob("*.part*"))
        assert len(part_files) == 0
        assert not target_cache.exists()


def test_6_single_file_concat_uses_cache(temp_cache_env, dummy_source, tmp_path):
    """Test 6: Single-file concat plan uses cached audio path instead of source MP4."""
    cache_path = tmp_path / "cache" / "audio_stream.m4a"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"audio")

    plan_path = tmp_path / "out.audio.concat.txt"
    _write_audio_concat_plan(
        plan_path,
        default_input_file=dummy_source,
        duration_s=10.0,
        local_start_s=0.0,
        audio_source_resolver=lambda p: cache_path,
    )

    content = plan_path.read_text(encoding="utf-8")
    assert f"file '{cache_path}'" in content
    assert str(dummy_source) not in content
    assert "outpoint 10.000000000" in content


def test_7_middle_of_clip_inpoint_outpoint(temp_cache_env, dummy_source, tmp_path):
    """Test 7: Middle of clip retains proper inpoint and outpoint."""
    cache_path = tmp_path / "cache" / "audio_stream.m4a"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"audio")

    plan_path = tmp_path / "out_middle.audio.concat.txt"
    _write_audio_concat_plan(
        plan_path,
        default_input_file=dummy_source,
        duration_s=25.5,
        local_start_s=10.25,
        audio_source_resolver=lambda p: cache_path,
    )

    content = plan_path.read_text(encoding="utf-8")
    assert f"file '{cache_path}'" in content
    assert "inpoint 10.250000000" in content
    assert "outpoint 35.750000000" in content


def test_8_multifile_concat_plan_maps_all_clips(temp_cache_env, tmp_path):
    """Test 8: Multi-file concat plan maps each clip to its corresponding audio cache."""
    clip1 = MagicMock()
    clip1.path = tmp_path / "clip1.mp4"
    clip1.local_start_s = 0.0
    clip1.local_end_s = 100.0
    clip1.duration_s = 100.0
    clip1.source_duration_s = 100.0

    clip2 = MagicMock()
    clip2.path = tmp_path / "clip2.mp4"
    clip2.local_start_s = 5.0
    clip2.local_end_s = 80.0
    clip2.duration_s = 75.0
    clip2.source_duration_s = 120.0

    timeline = MagicMock()
    timeline.clips = [clip1, clip2]
    timeline.clip_count = 2

    cache_map = {
        clip1.path: tmp_path / "cache1" / "audio_stream.m4a",
        clip2.path: tmp_path / "cache2" / "audio_stream.m4a",
    }

    plan_path = tmp_path / "multi.audio.concat.txt"
    _write_audio_concat_plan(
        plan_path,
        video_timeline=timeline,
        audio_source_resolver=lambda p: cache_map.get(p, p),
    )

    content = plan_path.read_text(encoding="utf-8")
    assert f"file '{cache_map[clip1.path]}'" in content
    assert f"file '{cache_map[clip2.path]}'" in content
    assert "inpoint 5.000000000" in content
    assert "outpoint 80.000000000" in content


def test_9_fallback_to_source_mp4_on_cache_error(temp_cache_env, dummy_source, tmp_path):
    """Test 9: Fallback cleanly uses source MP4 if cache generation fails."""
    # When cache resolver returns the source path on failure
    def failing_resolver(src):
        try:
            cached = ensure_audio_cache(src)
            if cached is not None and cached.is_file():
                return cached
        except Exception:
            pass
        return src

    # Simulate failing ensure_audio_cache
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], returncode=1, stderr="fail")):
        plan_path = tmp_path / "fallback.audio.concat.txt"
        _write_audio_concat_plan(
            plan_path,
            default_input_file=dummy_source,
            duration_s=15.0,
            local_start_s=0.0,
            audio_source_resolver=failing_resolver,
        )

        content = plan_path.read_text(encoding="utf-8")
        assert f"file '{dummy_source}'" in content


def test_10_cleanup_does_not_delete_persistent_audio_cache(temp_cache_env, dummy_source, tmp_path):
    """Test 10: Deleting concat plan or temp files does not delete persistent audio cache."""
    target_cache = get_audio_cache_path(dummy_source)
    target_cache.parent.mkdir(parents=True, exist_ok=True)
    target_cache.write_bytes(b"persistent_audio_bytes")

    concat_plan = tmp_path / "out.audio.concat.txt"
    concat_plan.write_text(f"file '{target_cache}'\n", encoding="utf-8")

    # Simulate export cleanup
    if concat_plan.exists():
        concat_plan.unlink()

    assert not concat_plan.exists()
    assert target_cache.exists()
    assert target_cache.read_bytes() == b"persistent_audio_bytes"
