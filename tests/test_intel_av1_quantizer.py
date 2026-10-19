"""Intel QP/quantizer diagnostics are removed from production (commit 98848d7).

These tests pin the post-removal contract: legacy QP fields and arguments are
still accepted for queue-file/API compatibility, but nothing collects, stores
or displays them. They replace tests of the removed IntelCompressionTracker.
"""
import ctypes
from unittest.mock import MagicMock

import src.ffmpeg.intel_native_exporter as intel_exporter
from src.ffmpeg.intel_native_exporter import IntelNativePipelineStats
from src.gui.export_queue import ExportJob, ExportQueue
from src.gui.qt.tabs.render_tab import RenderTab


def test_compression_tracker_is_not_part_of_production_exporter():
    assert not hasattr(intel_exporter, "IntelCompressionTracker")


def test_stats_abi_keeps_reserved_quant_slots():
    # Public stats layout is unchanged (752 B); former QP slots are reserved only.
    assert ctypes.sizeof(IntelNativePipelineStats) == 752
    names = [name for name, _ in IntelNativePipelineStats._fields_]
    assert "reserved_quant_avg" in names
    assert not any(n.startswith("quant_") for n in names)


def _card_text(job):
    mock_self = MagicMock()
    mock_self._fmt_time.return_value = "00:04"
    return RenderTab._queue_job_text(mock_self, job)


def test_queue_card_never_shows_qp_or_quantizer_even_for_legacy_fields():
    for codec in ("av1", "hevc", "h264"):
        job = ExportJob(
            job_id=f"legacy_{codec}", video_paths=["v.mp4"], output_path="o.mp4",
            render_status="done", is_expanded=True, codec=codec,
            average_qp=28.4, quant_metric="base_q_idx", quant_avg=45.7,
            quant_min=32, quant_max=71, quant_samples=60,
        )
        text = _card_text(job)
        assert "QP" not in text
        assert "Quantizer" not in text


def test_notify_render_done_accepts_but_does_not_store_quant_args(tmp_path):
    q = ExportQueue(appdata_dir=tmp_path)
    job = ExportJob(job_id="job_compat", video_paths=["v.mp4"], output_path="o.mp4")
    q.add_job(job)
    q.notify_render_done(
        job.job_id, success=True, output_path="o.mp4", elapsed_s=10.0, average_fps=30.0,
        average_qp=44.1, codec="av1", quant_metric="base_q_idx", quant_avg=44.1,
        quant_min=28, quant_max=65, quant_samples=120,
    )
    j = q.get_jobs()[0]
    assert j.render_status == "done"
    assert j.average_fps == 30.0
    assert j.codec == "av1"
    assert j.average_qp is None
    assert j.quant_avg is None and j.quant_samples is None


def test_cancel_with_legacy_quant_args(tmp_path):
    q = ExportQueue(appdata_dir=tmp_path)
    job = ExportJob(job_id="job_cancel", video_paths=["v.mp4"], output_path="o.mp4")
    q.add_job(job)
    q.notify_render_done(
        job.job_id, success=False, cancelled=True, output_path="o.mp4", elapsed_s=2.5,
        average_fps=20.0, codec="av1", quant_avg=50.0, quant_samples=50,
    )
    j = q.get_jobs()[0]
    assert j.render_status == "cancelled"
    assert j.quant_avg is None


def test_queue_file_with_legacy_quant_fields_still_loads(tmp_path):
    q = ExportQueue(appdata_dir=tmp_path)
    job = ExportJob(
        job_id="job_legacy_file", video_paths=["v.mp4"], output_path="o.mp4",
        codec="hevc", average_qp=30.0, quant_metric="QP", quant_avg=30.0,
        quant_min=25, quant_max=35, quant_samples=10,
    )
    q.add_job(job)
    q2 = ExportQueue(appdata_dir=tmp_path)
    loaded = q2.get_jobs()
    assert len(loaded) == 1
    assert loaded[0].job_id == "job_legacy_file"
    assert "QP" not in _card_text(loaded[0])
