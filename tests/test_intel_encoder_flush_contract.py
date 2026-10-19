"""Intel native encoder flush/finalization contract (last-frame loss fix).

The flush loop must retry MFX_WRN_DEVICE_BUSY instead of stopping, end on
MFX_ERR_MORE_DATA, stay time-bounded, and report real failures; the exporter
must turn a failed finalization into an error instead of a silent success.
"""
import ctypes
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "src/native/intel/d3d11_intel_pipeline/telem_intel_native.c").read_text(encoding="utf-8", errors="replace")


def _function_body(name: str) -> str:
    start = SRC.index(f"__declspec(dllexport) int {name}(")
    end = SRC.index("\n}\n", start)
    return SRC[start:end]


def test_flush_retries_device_busy_and_ends_on_more_data():
    body = _function_body("intel_native_pipeline_finish")
    flush = body[body.index("// 2. Flush the encoder"):body.index("// 3. Signal Drain Thread")]
    assert "sts == MFX_WRN_DEVICE_BUSY" in flush
    assert "continue;" in flush.split("sts == MFX_WRN_DEVICE_BUSY", 1)[1].split("}", 1)[0]
    assert "flush_deadline" in flush  # bounded, never an infinite loop
    assert "MFX_ERR_MORE_DATA" in flush
    assert "Sleep(1000)" not in body


def test_finish_reports_missing_outputs_and_drain_timeout():
    body = _function_body("intel_native_pipeline_finish")
    assert "encoded_frames != g_pipe.stage.accepted_inputs" in body
    assert "drain_timeout" in body
    assert "return finish_rc;" in body


def test_step_never_drops_a_rejected_frame_silently():
    body = _function_body("intel_native_pipeline_step_regions")
    assert "busy_deadline" in body
    assert "EncodeFrameAsync rejected frame" in body
    assert "return -6;" in body


def test_sync_operation_status_is_checked():
    assert SRC.count("mfxStatus sync_sts = ctx->pMFXVideoCORE_SyncOperation(") == 2
    assert SRC.count("ctx->stage.sync_errors++;") == 2


def test_exporter_turns_failed_finalization_into_error():
    py = (ROOT / "src/ffmpeg/intel_native_exporter.py").read_text(encoding="utf-8")
    assert "finish_rc = native_lib.intel_native_pipeline_finish()" in py
    block = py[py.index("if finish_rc != 0 and not export_cancelled:"):]
    assert block.index("raise IntelNativeFinalizationError(") < 600


def test_installed_dll_finish_without_pipeline_is_noop():
    dll = ROOT / "runtime/intel/bin/telem_intel_native.dll"
    if not dll.exists():
        pytest.skip("Intel native runtime not present")
    try:
        lib = ctypes.CDLL(str(dll))
    except OSError as exc:
        pytest.skip(f"Intel native runtime not loadable here: {exc}")
    lib.intel_native_pipeline_finish.restype = ctypes.c_int
    assert lib.intel_native_pipeline_finish() == 0
