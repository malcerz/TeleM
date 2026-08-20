from __future__ import annotations

import json

from src.ffmpeg.pipeline_audit import PipelineAuditRecorder, env_enabled


def _complete_frame(audit: PipelineAuditRecorder, index: int, base: int) -> None:
    audit.frame(index)
    for offset, name in enumerate((
        "frame_scheduled_ns", "slot_acquired_ns", "submit_started_ns", "job_submitted_ns",
        "worker_started_ns", "worker_render_started_ns", "worker_render_finished_ns",
        "shm_copy_finished_ns", "worker_done_ns", "future_completed_ns", "result_observed_ns",
        "ordered_output_ns", "shm_view_ready_ns", "queue_put_started_ns", "queue_put_finished_ns",
        "ffmpeg_write_started_ns", "ffmpeg_write_finished_ns", "shm_released_ns",
    )):
        audit.mark(index, name, base + offset * 1_000_000)
    audit.mark(index, "worker_pid", 100 + index % 2)


def test_pipeline_audit_writes_lifecycle_and_aggregates(tmp_path):
    audit = PipelineAuditRecorder(str(tmp_path / "audit.json"))
    audit.start(1_000_000_000)
    _complete_frame(audit, 0, 1_000_000_000)
    _complete_frame(audit, 1, 1_100_000_000)
    result = audit.finalize({"frame_size_bytes": 100, "workers": 2, "max_in_flight": 8})

    assert result["frames"] == 2
    assert result["phases_ms"]["worker_compute"]["median"] > 0
    assert "main_shm_view" in result["phases_ms"]
    assert result["pipe_bandwidth"]["bytes_per_frame"] == 100
    assert len(result["lifecycle_ms_from_run_start"]) == 2
    assert "frame_scheduled_ms" in result["lifecycle_ms_from_run_start"][0]
    assert (tmp_path / "audit.csv").exists()
    json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))


def test_pipeline_audit_is_opt_in(monkeypatch):
    monkeypatch.delenv("TELEM_PIPELINE_AUDIT", raising=False)
    assert env_enabled() is False
    monkeypatch.setenv("TELEM_PIPELINE_AUDIT", "1")
    assert env_enabled() is True
