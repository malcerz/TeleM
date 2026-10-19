"""HUD worker initargs travel through one shared memory blob (Intel native export)."""
import ctypes
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ffmpeg import shared_memory as shm_mod
from src.ffmpeg.shared_memory import WorkerInitBlob, _init_worker_with_shm_blob


def _sample_init_args():
    return (
        2560, 1440, "font.ttf", {"indicators": {"speed_text": {"enabled": True, "x": 0.5}}},
        {"speed": [(0.0, 1.5), (1.0, 2.25)]}, 1234.5,
        None, [], [(0.5, 100)],
        datetime(2026, 10, 16, 9, 6, 9, tzinfo=timezone.utc), 2.0,
        list(range(5000)),
    )


def test_blob_roundtrip_passes_identical_args(monkeypatch):
    args = _sample_init_args()
    captured = {}

    def fake_init(shm_names, frame_size, *init_worker_args):
        captured["shm_names"] = shm_names
        captured["frame_size"] = frame_size
        captured["args"] = init_worker_args

    monkeypatch.setattr(shm_mod, "_init_worker_with_shm", fake_init)
    blob = WorkerInitBlob(args)
    try:
        _init_worker_with_shm_blob(blob.name, blob.size, ["a", "b"], 42)
    finally:
        blob.close()
    assert captured["shm_names"] == ["a", "b"]
    assert captured["frame_size"] == 42
    assert captured["args"] == args


def test_blob_close_is_idempotent():
    blob = WorkerInitBlob(_sample_init_args())
    blob.close()
    blob.close()


def test_stage_timing_struct_matches_native_export():
    from src.ffmpeg.intel_native_exporter import IntelStageTiming
    # C layout: int struct_size, int frames, double slot_wait/surface_acquire/bitstream_write.
    assert ctypes.sizeof(IntelStageTiming) == 32
    dll = Path(__file__).resolve().parents[1] / "runtime/intel/bin/telem_intel_native.dll"
    if not dll.exists():
        pytest.skip("Intel native runtime not present")
    try:
        lib = ctypes.CDLL(str(dll))
    except OSError as exc:
        pytest.skip(f"Intel native runtime not loadable here: {exc}")
    fn = lib.intel_native_pipeline_get_stage_timing
    fn.argtypes = [ctypes.POINTER(IntelStageTiming), ctypes.c_int]
    out = IntelStageTiming()
    assert fn(ctypes.byref(out), ctypes.sizeof(out)) == 0
    assert out.struct_size == ctypes.sizeof(IntelStageTiming)
    assert fn(ctypes.byref(out), ctypes.sizeof(out) - 8) == -1
