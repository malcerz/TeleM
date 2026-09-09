from __future__ import annotations

import threading
import time
from pathlib import Path

from src.ffmpeg.amd_pipeline_watchdog import (
    AMDRenderWatchdog,
    NonBlockingProgressDispatcher,
)


def _snapshot() -> dict:
    return {
        "native_frame": 7,
        "native_stage": 6,
        "native_stage_age_s": 0.2,
        "decoded": 8,
        "produced": 9,
        "composed": 8,
        "submitted": 8,
        "encoded": 7,
        "written": 7,
        "producer_q": 1,
        "encoder_q": 1,
        "ffmpeg_alive": True,
        "render_thread_alive": True,
        "workers": {"producer": True, "mux_pump": True},
        "processes": {"mux": {"pid": 123, "returncode": None}},
        "stdout_tail": [],
        "stderr_tail": [b"mux diagnostic\n"],
    }


def test_watchdog_reports_stalled_packet_write_and_thread_dump(tmp_path, capsys):
    dump_path = tmp_path / "threads.log"
    watchdog = AMDRenderWatchdog(
        _snapshot,
        cancel_event=threading.Event(),
        dump_path=dump_path,
        heartbeat_s=0.05,
        freeze_s=0.12,
    )
    watchdog.start()
    time.sleep(0.3)
    watchdog.stop()

    output = capsys.readouterr().out
    assert "[AMD HEARTBEAT]" in output
    assert "[AMD FREEZE DETECTED]" in output
    assert "native_stage=packet_write" in output
    assert "mux diagnostic" in output
    assert watchdog.freeze_reported
    assert "TeleM-AMD-Watchdog" in dump_path.read_text(encoding="utf-8")


def test_watchdog_ignores_cancelled_render(tmp_path, capsys):
    cancel = threading.Event()
    cancel.set()
    watchdog = AMDRenderWatchdog(
        _snapshot,
        cancel_event=cancel,
        dump_path=tmp_path / "cancelled.log",
        heartbeat_s=0.05,
        freeze_s=0.1,
    )
    watchdog.start()
    time.sleep(0.2)
    watchdog.stop()

    assert not watchdog.freeze_reported
    assert "[AMD FREEZE DETECTED]" not in capsys.readouterr().out
    assert not (tmp_path / "cancelled.log").exists()


def test_progress_callback_cannot_block_render_caller():
    entered = threading.Event()
    release = threading.Event()

    def blocked_callback(_value):
        entered.set()
        release.wait(2.0)

    dispatcher = NonBlockingProgressDispatcher(capacity=4)
    started = time.perf_counter()
    for value in range(1000):
        dispatcher.submit(blocked_callback, value)
    submit_elapsed = time.perf_counter() - started

    assert entered.wait(0.5)
    assert submit_elapsed < 0.2
    dispatcher.stop(timeout=0.01)
    assert dispatcher.thread.is_alive()
    release.set()
    dispatcher.stop(timeout=1.0)
    assert not dispatcher.thread.is_alive()


def test_native_live_mux_write_is_overlapped_bounded_and_checked():
    source = Path(
        "native/d3d11_amf_pipeline/src/telem_amd_native.cpp"
    ).read_text(encoding="utf-8")
    assert "FILE_FLAG_OVERLAPPED" in source
    assert "WaitForSingleObject(ctx->h265PipeEvent, 15000)" in source
    assert "CancelIoEx(ctx->h265Pipe, &ov)" in source
    assert "if (!pktData.empty() && !WriteEncodedPacket" in source
    assert "if (!bpPacket.empty() && !WriteEncodedPacket" in source


def test_profiling_gpu_queries_have_a_deadline():
    source = Path(
        "native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp"
    ).read_text(encoding="utf-8")
    assert "std::chrono::seconds(15)" in source
    assert "while (m_context->GetData" not in source

