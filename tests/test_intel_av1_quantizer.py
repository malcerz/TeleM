import json
import ctypes
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.render_progress import RenderProgressState
from src.gui.export_queue import ExportJob, ExportQueue
from src.ffmpeg.intel_native_exporter import (
    IntelNativePipelineStats,
    IntelCompressionTracker,
    get_last_intel_export_stats,
)
from src.gui.qt.tabs.render_tab import RenderTab


class MockNativeLib:
    """Mock for ctypes native DLL returning IntelNativePipelineStats."""
    def __init__(self, samples=0, cur=0, qmin=0, qmax=0, qavg=0.0):
        self._stats = IntelNativePipelineStats()
        self._stats.quant_samples = samples
        self._stats.quant_current = cur
        self._stats.quant_min = qmin
        self._stats.quant_max = qmax
        self._stats.quant_avg = qavg

    def intel_native_pipeline_get_stats(self, out_ptr):
        ctypes.memmove(out_ptr, ctypes.byref(self._stats), ctypes.sizeof(IntelNativePipelineStats))
        return 0


# 1. AV1 quantizer accumulator & 2. min/max/avg/sample count
def test_av1_quantizer_accumulator_and_stats():
    lib = MockNativeLib(samples=100, cur=42, qmin=32, qmax=75, qavg=48.7)
    tracker = IntelCompressionTracker(lib, is_av1=True)
    d = tracker.get_hud_state_dict()

    assert d["compression_active"] is True
    assert d["is_av1"] is True
    assert d["quant_metric"] == "base_q_idx"
    assert d["quant_current"] == 42
    assert d["quant_min"] == 32
    assert d["quant_max"] == 75
    assert d["quant_samples"] == 100
    assert abs(d["quant_avg"] - 48.7) < 1e-4
    assert "AV1 Q: 42 | Avg: 48.7 | Min: 32 | Max: 75" in d["compression_text"]


# 3. empty/no-stat behavior
def test_empty_no_stat_behavior():
    lib = MockNativeLib(samples=0, cur=0, qmin=0, qmax=0, qavg=0.0)
    tracker = IntelCompressionTracker(lib, is_av1=True)
    d = tracker.get_hud_state_dict()

    assert d["compression_active"] is False
    assert d["is_av1"] is True
    assert "quant_current" not in d


# 4. GUI formatting uses Quantizer/Q for AV1
def test_gui_formatting_uses_q_for_av1():
    # Progress state snapshot with AV1
    snap = RenderProgressState(
        generation_id=1,
        state="rendering",
        frame=50,
        total_frames=100,
        fps=25.0,
        qp=45.2,
        is_av1=True,
        quant_metric="base_q_idx",
        compression_text="AV1 Q: 42 | Avg: 45.2 | Min: 32 | Max: 71",
    )
    assert snap.is_av1 is True
    assert snap.quant_metric == "base_q_idx"

    # Test Queue formatting for completed AV1 job
    job = ExportJob(
        job_id="test_av1_job",
        video_paths=["test.mp4"],
        output_path="out.mp4",
        render_status="done",
        is_expanded=True,
        codec="av1",
        quant_metric="base_q_idx",
        quant_avg=45.7,
        quant_min=32,
        quant_max=71,
        quant_samples=60,
    )
    mock_self = MagicMock()
    mock_self._fmt_time.return_value = "00:04"
    card_txt = RenderTab._queue_job_text(mock_self, job)
    assert "Średni Quantizer: 45.7" in card_txt
    assert "Zakres Quantizer: 32–71" in card_txt
    assert "Średnie QP" not in card_txt


# 5. GUI formatting retains QP for HEVC/H264
def test_gui_formatting_retains_qp_for_hevc():
    job = ExportJob(
        job_id="test_hevc_job",
        video_paths=["test.mp4"],
        output_path="out.mp4",
        render_status="done",
        is_expanded=True,
        codec="hevc",
        average_qp=28.4,
    )
    mock_self = MagicMock()
    mock_self._fmt_time.return_value = "00:04"
    card_txt = RenderTab._queue_job_text(mock_self, job)
    assert "Średnie QP: 28.4" in card_txt
    assert "Quantizer" not in card_txt


# 6. queue persistence of AV1 quant stats (roundtrip JSON)
def test_queue_persistence_roundtrip(tmp_path):
    q = ExportQueue(appdata_dir=tmp_path)
    job = ExportJob(
        job_id="job_persist_test",
        video_paths=["video.mp4"],
        output_path="out.mp4",
        options={"codec": "av1"},
    )
    q.add_job(job)
    q.notify_render_done(
        job.job_id,
        success=True,
        output_path="out.mp4",
        elapsed_s=10.0,
        average_fps=30.0,
        codec="av1",
        quant_metric="base_q_idx",
        quant_avg=47.3,
        quant_min=30,
        quant_max=70,
        quant_samples=300,
    )

    # Reload from disk
    q2 = ExportQueue(appdata_dir=tmp_path)
    loaded_jobs = q2.get_jobs()
    assert len(loaded_jobs) == 1
    j = loaded_jobs[0]
    assert j.codec == "av1"
    assert j.quant_metric == "base_q_idx"
    assert j.quant_avg == 47.3
    assert j.quant_min == 30
    assert j.quant_max == 70
    assert j.quant_samples == 300


# 7. direct/queue stats transfer
def test_direct_queue_stats_transfer(tmp_path):
    stats = {
        "codec": "av1",
        "quant_metric": "base_q_idx",
        "quant_current": 38,
        "quant_avg": 44.1,
        "quant_min": 28,
        "quant_max": 65,
        "quant_samples": 120,
        "avg_qp": 44.1,
        "render_fps": 26.5,
    }

    q = ExportQueue(appdata_dir=tmp_path)
    job = ExportJob(job_id="job_transfer", video_paths=["v.mp4"], output_path="o.mp4")
    q.add_job(job)
    q.notify_render_done(
        job.job_id,
        success=True,
        output_path="o.mp4",
        average_fps=stats["render_fps"],
        average_qp=stats["avg_qp"],
        codec=stats["codec"],
        quant_metric=stats["quant_metric"],
        quant_avg=stats["quant_avg"],
        quant_min=stats["quant_min"],
        quant_max=stats["quant_max"],
        quant_samples=stats["quant_samples"],
    )

    j = q.get_jobs()[0]
    assert j.quant_avg == 44.1
    assert j.quant_samples == 120
    assert j.average_qp == 44.1


# 8. cancel resets/finalizes stats correctly
def test_cancel_finalizes_stats(tmp_path):
    q = ExportQueue(appdata_dir=tmp_path)
    job = ExportJob(job_id="job_cancel", video_paths=["v.mp4"], output_path="o.mp4")
    q.add_job(job)
    q.notify_render_done(
        job.job_id,
        success=False,
        cancelled=True,
        output_path="o.mp4",
        elapsed_s=2.5,
        average_fps=20.0,
        codec="av1",
        quant_metric="base_q_idx",
        quant_avg=50.0,
        quant_min=45,
        quant_max=55,
        quant_samples=50,
    )

    j = q.get_jobs()[0]
    assert j.render_status == "cancelled"
    assert j.quant_avg == 50.0
    assert j.quant_samples == 50


# 9. new render resets previous quantizer state
def test_new_render_resets_previous_state():
    lib1 = MockNativeLib(samples=50, cur=40, qmin=30, qmax=60, qavg=45.0)
    tracker1 = IntelCompressionTracker(lib1, is_av1=True)
    d1 = tracker1.get_hud_state_dict()
    assert d1["quant_samples"] == 50

    lib2 = MockNativeLib(samples=0, cur=0, qmin=0, qmax=0, qavg=0.0)
    tracker2 = IntelCompressionTracker(lib2, is_av1=True)
    d2 = tracker2.get_hud_state_dict()
    assert d2["compression_active"] is False


# 10. backend isolation
def test_backend_isolation():
    # Non-AV1 tracker behaves with QP semantics
    lib = MockNativeLib(samples=10, cur=28, qmin=25, qmax=32, qavg=28.2)
    tracker = IntelCompressionTracker(lib, is_av1=False)
    d = tracker.get_hud_state_dict()
    assert d["quant_metric"] == "QP"
    assert "QP: 28 | Avg: 28.2 | Min: 25 | Max: 32" in d["compression_text"]
    assert "AV1" not in d["compression_text"]
