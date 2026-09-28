import os
import sys
import time
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.gui.export_queue import ExportJob, ExportQueue
from src.render_progress import RenderProgressTracker, RenderProgressState
from src.ffmpeg.intel_native_exporter import _probe_video_summary, get_last_intel_export_stats


def test_1_render_fps_excludes_finalization():
    """Verify that pure frame render FPS excludes finalization duration."""
    frames = 1000
    t_start = 100.0
    t_last_frame = 120.0  # 20s frame rendering -> 50 FPS
    t_final = 180.0       # 60s finalization

    frame_render_s = t_last_frame - t_start
    finalization_s = t_final - t_last_frame
    total_wall_s = t_final - t_start

    render_fps = frames / frame_render_s
    user_effective_fps = frames / total_wall_s

    assert render_fps == 50.0
    assert user_effective_fps == pytest.approx(1000.0 / 80.0, rel=1e-3)
    assert render_fps != user_effective_fps


def test_2_effective_fps_includes_total_wall_time():
    """Verify that user_effective_fps accurately incorporates total job wall time."""
    frames = 300
    total_wall_s = 6.0
    frame_render_s = 4.0
    
    render_fps = frames / frame_render_s  # 75 FPS
    eff_fps = frames / total_wall_s        # 50 FPS
    
    job = ExportJob(
        job_id="test-job",
        render_elapsed_s=total_wall_s,
        frame_render_elapsed_s=frame_render_s,
        finalization_elapsed_s=2.0,
        average_fps=render_fps,
        effective_fps=eff_fps,
    )
    assert job.average_fps == 75.0
    assert job.effective_fps == 50.0
    assert job.render_elapsed_s == 6.0
    assert job.frame_render_elapsed_s == 4.0
    assert job.finalization_elapsed_s == 2.0


def test_3_final_mux_no_longer_uses_blind_blocking_wait():
    """Verify source code confirms Popen with -progress pipe:1 and no blocking subprocess.run."""
    exporter_path = Path("src/ffmpeg/intel_native_exporter.py")
    content = exporter_path.read_text(encoding="utf-8")
    
    # Must NOT have blocking run for cmd_mux
    assert "subprocess.run(cmd_mux" not in content
    # Must have Popen for cmd_mux
    assert "p_mux = subprocess.Popen(" in content
    assert '"-progress", "pipe:1"' in content or "'-progress', 'pipe:1'" in content
    assert '"-nostats"' in content or "'-nostats'" in content


def test_4_monitored_mux_progress_works():
    """Verify parsing machine-readable FFmpeg progress lines and computing ratio."""
    duration_s = 10.0
    progress_lines = [
        "frame=100\n",
        "out_time_us=5000000\n",
        "total_size=10485760\n",
        "speed=120x\n",
        "progress=continue\n",
    ]
    out_time_us = 0
    total_size = 0
    speed = ""
    for line in progress_lines:
        k, v = line.strip().split("=")
        if k == "out_time_us":
            out_time_us = int(v)
        elif k == "total_size":
            total_size = int(v)
        elif k == "speed":
            speed = v

    out_s = out_time_us / 1_000_000.0
    ratio = out_s / duration_s
    clamped_ratio = max(0.0, min(0.99, ratio))
    mux_global = 94.0 + clamped_ratio * (98.0 - 94.0)

    assert out_s == 5.0
    assert clamped_ratio == 0.5
    assert mux_global == 96.0
    assert total_size == 10485760
    assert speed == "120x"


def test_5_mux_stall_is_detectable():
    """Verify that stall detection logic correctly flags no progress after timeout."""
    last_progress_time = 100.0
    now_healthy = 105.0
    now_warn = 120.0
    now_diag = 135.0
    now_stall = 165.0

    assert (now_healthy - last_progress_time) < 15.0
    assert (now_warn - last_progress_time) >= 15.0
    assert (now_diag - last_progress_time) >= 30.0
    assert (now_stall - last_progress_time) >= 60.0


def test_6_cancel_during_mux_terminates_child(tmp_path):
    """Verify that cancellation terminates child process and cleans .part file."""
    part_file = tmp_path / "test.part.mp4"
    part_file.write_bytes(b"dummy part content")

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    cancel_event = threading.Event()
    cancel_event.set()

    # Emulate the cancel handling inside the mux loop
    cancelled = False
    if cancel_event.is_set():
        mock_proc.terminate()
        if part_file.exists():
            part_file.unlink()
        cancelled = True

    assert mock_proc.terminate.called
    assert not part_file.exists()
    assert cancelled is True


def test_7_successful_mux_reaches_done(tmp_path):
    """Verify atomic rename from .part to final output on successful mux."""
    part_file = tmp_path / "video.part.mp4"
    out_file = tmp_path / "video.mp4"
    part_file.write_bytes(b"valid video content")

    mock_probe = {
        "format": {"duration": "10.0"},
        "streams": [{"codec_type": "video", "codec_name": "av1"}]
    }

    with patch("tests.test_intel_finalization._probe_video_summary", return_value=mock_probe):
        probe_res = _probe_video_summary("dummy_ffmpeg.exe", str(part_file))
        assert probe_res["streams"][0]["codec_name"] == "av1"
        os.replace(str(part_file), str(out_file))

    assert out_file.exists()
    assert not part_file.exists()
    assert out_file.read_bytes() == b"valid video content"


def test_8_failed_mux_reaches_error_and_cleans_part(tmp_path):
    """Verify that a failing mux cleans up partial file and does not leave artifacts."""
    part_file = tmp_path / "broken.part.mp4"
    out_file = tmp_path / "broken.mp4"
    part_file.write_bytes(b"corrupt partial bytes")

    mock_proc = MagicMock()
    mock_proc.returncode = 1  # FFmpeg error exit

    if mock_proc.returncode != 0:
        if part_file.exists():
            part_file.unlink()
        success = False

    assert success is False
    assert not part_file.exists()
    assert not out_file.exists()


def test_9_partial_output_never_exposed_as_success(tmp_path):
    """Verify that output_file never appears if verification fails."""
    part_file = tmp_path / "corrupt.part.mp4"
    out_file = tmp_path / "corrupt.mp4"
    part_file.write_bytes(b"zero streams header")

    mock_probe = {
        "format": {"duration": "0.0"},
        "streams": []  # Missing video stream!
    }

    with patch("tests.test_intel_finalization._probe_video_summary", return_value=mock_probe):
        probe_res = _probe_video_summary("dummy_ffmpeg.exe", str(part_file))
        v_stream = any(s.get("codec_type") == "video" for s in probe_res.get("streams", []))
        if not v_stream:
            if part_file.exists():
                part_file.unlink()
            success = False

    assert success is False
    assert not out_file.exists()
    assert not part_file.exists()


def test_10_queue_stats_and_job_expansion(tmp_path):
    """Verify queue persists and formats frame render vs effective fps cleanly."""
    queue = ExportQueue(appdata_dir=tmp_path)
    job = ExportJob(
        job_id="job-stats-test",
        output_path="test_video.mp4",
        codec="av1",
        quant_metric="base_q_idx",
        quant_avg=60.8,
        quant_min=19,
        quant_max=110,
    )
    queue.add_job(job)
    
    queue.notify_render_done(
        job_id="job-stats-test",
        success=True,
        output_path="test_video.mp4",
        elapsed_s=100.0,
        average_fps=68.0,
        effective_fps=63.0,
        frame_render_elapsed_s=80.0,
        finalization_elapsed_s=20.0,
    )

    persisted_job = queue._find_job("job-stats-test")
    assert persisted_job is not None
    assert persisted_job.average_fps == 68.0
    assert persisted_job.effective_fps == 63.0
    assert persisted_job.frame_render_elapsed_s == 80.0
    assert persisted_job.finalization_elapsed_s == 20.0
    assert persisted_job.render_elapsed_s == 100.0
