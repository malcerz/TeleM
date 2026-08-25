"""Tests for the isolated Intel backend (ETAP 1) — INTEL_FORCE.

Covers:
- D3D11/DXGI adapter enumeration diagnostics contract (pure data via injectable
  adapter lists).
- Intel adapter selection by Vendor ID (0x8086), independent of adapter index.
- INTEL_FORCE success and controlled failure (no cross-GPU fallback).
- QSV probing: FFmpeg-encoder presence vs usable hardware separation.
- No accidental NVIDIA/AMD/CUDA/NVENC/AMF dispatch under INTEL_FORCE.
"""

from __future__ import annotations

import pytest

from src.ffmpeg.intel_backend import (
    BACKEND_INTEL,
    VENDOR_ID_AMD,
    VENDOR_ID_INTEL,
    VENDOR_ID_NVIDIA,
    IntelBackendError,
    intel_device_selection,
    intel_ffmpeg_device_args,
    find_intel_adapter,
    normalize_backend,
    resolve_intel_force,
)


def _adapter(
    index: int,
    vendor_id: int,
    name: str = "GPU",
    device_ok: bool = True,
) -> dict:
    return {
        "index": index,
        "name": name,
        "vendor_id": vendor_id,
        "device_id": 0,
        "vendor_code": "unknown",
        "dedicated_vram_mb": 0,
        "d3d11_device_ok": device_ok,
    }


_INTEL_A = _adapter(1, VENDOR_ID_INTEL, "Intel UHD Graphics")
_NVIDIA_A = _adapter(0, VENDOR_ID_NVIDIA, "NVIDIA Quadro P400")
_AMD_A = _adapter(0, VENDOR_ID_AMD, "AMD Radeon Graphics")


# ── Adapter selection: Vendor ID, not index ──────────────────────────────

def test_find_intel_adapter_quadro_first() -> None:
    """adapter 0 = NVIDIA, adapter 1 = Intel → INTEL_FORCE selects adapter 1."""
    adapters = [_NVIDIA_A, _INTEL_A]
    result = find_intel_adapter(adapters)
    assert result is not None
    assert result["index"] == 1
    assert result["vendor_id"] == VENDOR_ID_INTEL
    assert result["name"] == "Intel UHD Graphics"


def test_find_intel_adapter_intel_first() -> None:
    """adapter 0 = Intel, adapter 1 = NVIDIA → INTEL_FORCE selects adapter 0."""
    intel_first = _adapter(0, VENDOR_ID_INTEL, "Intel UHD Graphics")
    adapters = [intel_first, _NVIDIA_A]
    result = find_intel_adapter(adapters)
    assert result is not None
    assert result["index"] == 0
    assert result["vendor_id"] == VENDOR_ID_INTEL


def test_find_intel_adapter_none() -> None:
    """No Intel adapter → returns None (no accidental selection)."""
    assert find_intel_adapter([_NVIDIA_A, _AMD_A]) is None
    assert find_intel_adapter([]) is None


# ── INTEL_FORCE resolution ───────────────────────────────────────────────

def test_resolve_intel_force_success() -> None:
    """Intel adapter present + usable QSV → resolution succeeds."""
    log_lines: list[str] = []
    res = resolve_intel_force(
        adapters=[_NVIDIA_A, _INTEL_A],
        qsv_hw_usable=True,
        ffmpeg_qsv_info={"ffmpeg_has_qsv": True, "hevc_qsv": True, "h264_qsv": False},
        log=log_lines.append,
    )
    assert res.adapter_found is True
    assert res.adapter_name == "Intel UHD Graphics"
    assert res.vendor_id == VENDOR_ID_INTEL
    assert res.qsv_available is True
    assert res.hevc_qsv is True
    assert res.encode_path == "QSV-HEVC"
    joined = "\n".join(log_lines)
    assert "[GPU] Requested backend: INTEL_FORCE" in joined
    assert "[GPU] D3D11 adapters discovered:" in joined
    assert "[GPU] 0: NVIDIA Quadro P400" in joined
    assert "[GPU]    vendor=0x10DE" in joined
    assert "[INTEL] Selected adapter: Intel UHD Graphics" in joined
    assert "[NVIDIA] Adapter ignored: INTEL_FORCE active" in joined
    assert "[INTEL] INTEL_CROSS_GPU_FALLBACK: DISABLED" in joined


def test_resolve_intel_force_no_intel_adapter_raises() -> None:
    """No Intel GPU on an AMD-only machine → controlled INTEL_FORCE_FAILED.

    This is the expected correct result on the current Ryzen 5 5500U test box.
    """
    log_lines: list[str] = []
    with pytest.raises(IntelBackendError) as exc:
        resolve_intel_force(
            adapters=[_AMD_A],
            qsv_hw_usable=True,  # never reached — adapter check fails first
            log=log_lines.append,
        )
    assert "INTEL_FORCE_FAILED" in str(exc.value)
    assert "No usable Intel GPU/QSV device available" in str(exc.value)
    assert "cross-GPU fallback disabled" in str(exc.value)
    joined = "\n".join(log_lines)
    assert "[GPU] 0: AMD Radeon Graphics" in joined
    assert "[GPU]    vendor=0x1002" in joined
    assert "[INTEL] Intel adapter: NOT FOUND" in joined
    assert "[INTEL] INTEL_FORCE_FAILED" in joined
    assert "[INTEL] Cross-GPU fallback: DISABLED" in joined


def test_resolve_intel_force_no_qsv_raises() -> None:
    """Intel adapter exists but QSV is not usable → controlled failure.

    Separates 'FFmpeg contains QSV encoder' from 'usable Intel hardware'.
    """
    log_lines: list[str] = []
    with pytest.raises(IntelBackendError) as exc:
        resolve_intel_force(
            adapters=[_INTEL_A],
            qsv_hw_usable=False,
            ffmpeg_qsv_info={"ffmpeg_has_qsv": True, "hevc_qsv": True, "h264_qsv": False},
            log=log_lines.append,
        )
    assert "INTEL_FORCE_FAILED" in str(exc.value)
    assert "QSV encode is not usable" in str(exc.value)
    joined = "\n".join(log_lines)
    assert "[INTEL] INTEL_QSV_AVAILABLE: NO" in joined
    assert "[INTEL] INTEL_H264_QSV: NO" in joined
    assert "[INTEL] INTEL_HEVC_QSV: YES" in joined
    assert "[INTEL] INTEL_DECODE_PATH: QSV/D3D11VA" in joined
    assert "[INTEL] INTEL_ENCODE_PATH: NONE" in joined


def test_resolve_intel_force_no_cross_gpu_probe() -> None:
    """When the Intel adapter is missing, no QSV/encoder probing is attempted.

    The resolution raises before any FFmpeg/encoder call, so it cannot dispatch
    to NVENC/AMF/CUDA/AMD/NVIDIA.  Passing an invalid ffmpeg_exe would blow up
    only if a probe were attempted — it must not be.
    """
    log_lines: list[str] = []
    with pytest.raises(IntelBackendError):
        resolve_intel_force(
            adapters=[_NVIDIA_A, _AMD_A],
            ffmpeg_exe="definitely_missing_ffmpeg_binary_xyz",
            log=log_lines.append,
        )
    joined = "\n".join(log_lines)
    assert "INTEL_FORCE_FAILED" in joined
    assert "Intel adapter: NOT FOUND" in joined
    # No AMD/NVIDIA backend was selected, and no QSV/FFmpeg probe ran.
    assert "[INTEL] Selected adapter" not in joined
    assert "INTEL_QSV_AVAILABLE" not in joined


def test_resolve_intel_force_ffmpeg_missing_qsv() -> None:
    """Intel adapter present but FFmpeg has no QSV encoder → controlled failure."""
    log_lines: list[str] = []
    with pytest.raises(IntelBackendError):
        resolve_intel_force(
            adapters=[_INTEL_A],
            qsv_hw_usable=False,
            ffmpeg_qsv_info={"ffmpeg_has_qsv": False, "hevc_qsv": False, "h264_qsv": False},
            log=log_lines.append,
        )
    joined = "\n".join(log_lines)
    assert "FFmpeg does not expose a usable QSV encoder." in joined
    assert "[INTEL] INTEL_ENCODE_PATH: NONE" in joined


def test_resolve_intel_force_empty_adapter_list() -> None:
    """Empty adapter list (no DXGI result) → controlled failure."""
    with pytest.raises(IntelBackendError):
        resolve_intel_force(
            adapters=[],
            log=lambda _msg: None,
        )


# ── Pipeline enforcement (stream_overlay_to_ffmpeg) ──────────────────────

def test_stream_pipeline_enforces_intel_force(monkeypatch) -> None:
    """stream_overlay_to_ffmpeg with encoder='intel' must enforce INTEL_FORCE.

    When the Intel resolution fails, the pipeline must abort with the
    controlled error BEFORE any video/file processing — never silently fall
    back to NVIDIA/AMD/CPU.
    """
    from src.ffmpeg import streaming

    def _boom(**_kw):
        raise IntelBackendError(
            "INTEL_FORCE_FAILED: No usable Intel GPU/QSV device available. "
            "Automatic cross-GPU fallback disabled."
        )

    monkeypatch.setattr(streaming, "resolve_intel_force", _boom)

    with pytest.raises(IntelBackendError) as exc:
        streaming.stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg",
            input_files=["dummy.mp4"],
            output_file="out.mp4",
            duration_s=1.0,
            start_dt_utc=None,
            tz_offset_hours=2,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            font_path="",
            layout={},
            field_samples={},
            max_distance_m=None,
            encoder="intel",
        )
    assert "INTEL_FORCE_FAILED" in str(exc.value)


# ── normalize_backend ────────────────────────────────────────────────────

def test_normalize_backend() -> None:
    assert normalize_backend("auto") == "auto"
    assert normalize_backend("CPU") == "cpu"
    assert normalize_backend("nvidia") == "nv"
    assert normalize_backend("NVEN C") != "nv"
    assert normalize_backend("amf") == "amd"
    assert normalize_backend("qsv") == "intel"
    assert normalize_backend("intel_force") == "intel"
    assert normalize_backend(" INTEL ") == "intel"
    assert normalize_backend("software") == "cpu"
    assert normalize_backend("bogus") == "bogus"


def test_intel_ffmpeg_device_args_use_dynamic_adapter_index() -> None:
    res = resolve_intel_force(
        adapters=[_NVIDIA_A, _INTEL_A],
        qsv_hw_usable=True,
        ffmpeg_qsv_info={"ffmpeg_has_qsv": True, "hevc_qsv": True, "h264_qsv": True},
        log=lambda _: None,
    )
    args = intel_ffmpeg_device_args(intel_device_selection(res))
    assert "child_device=1" in args[1]
    assert args[args.index("-hwaccel_device") + 1] == "intel_qsv"
    assert "cuda" not in args


def test_intel_ffmpeg_device_args_follow_intel_adapter_zero() -> None:
    intel = _adapter(0, VENDOR_ID_INTEL, "Intel UHD Graphics")
    res = resolve_intel_force(
        adapters=[intel, _NVIDIA_A],
        qsv_hw_usable=True,
        ffmpeg_qsv_info={"ffmpeg_has_qsv": True, "hevc_qsv": True, "h264_qsv": True},
        log=lambda _: None,
    )
    args = intel_ffmpeg_device_args(intel_device_selection(res))
    assert "child_device=0" in args[1]


def test_intel_ffmpeg_device_args_reject_foreign_vendor() -> None:
    from src.ffmpeg.intel_backend import IntelDeviceSelection

    with pytest.raises(IntelBackendError):
        intel_ffmpeg_device_args(IntelDeviceSelection(0, "Quadro", VENDOR_ID_NVIDIA))
