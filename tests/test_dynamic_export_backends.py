"""Deterministic test suite for dynamic export backends and capability-driven NVIDIA UI.

Covers:
- Case A: AMD=False, NVIDIA=False, Intel=True, CPU=True -> ['auto', 'intel', 'cpu']
- Case B: AMD=True, NVIDIA=False, Intel=False, CPU=True -> ['auto', 'amd', 'cpu']
- Case C: AMD=False, NVIDIA=True, Intel=True, CPU=True -> ['auto', 'nv', 'intel', 'cpu']
- Case D: All GPU vendors available -> ['auto', 'amd', 'nv', 'intel', 'cpu']
- Case E: Saved encoder=nv on machine without NVIDIA -> visibly resolves to best available (intel)
- Case F: Forced unavailable nv reaches export safety gate -> BLOCKED (RuntimeError)
- Case G: NVIDIA H264+HEVC available, AV1 unavailable -> H264, HEVC (AV1 hidden)
- Case H: NVIDIA all codecs available -> H264, HEVC, AV1
- Parity: Hardware panel and RenderTab dropdown parity
- Strict Contract: SILENT_CROSS_VENDOR_FALLBACK=NO
- Queue Safety: QUEUE_CROSS_VENDOR_SILENT_FALLBACK=NO
- Widget Verification: DiscreteSlider for NVIDIA codec and quality
- Real Host Verification: i5-12400 / UHD 730 / Quadro P400 runtime truth
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
import pytest
from PySide6.QtWidgets import QApplication

workspace_root = Path(__file__).resolve().parent.parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

from src.ffmpeg.backend_capabilities import (
    BackendCapabilities,
    query_backend_capabilities,
    get_available_backends,
    resolve_auto_backend,
    resolve_supported_backend,
    validate_backend_available,
    invalidate_backend_capabilities_cache,
)
from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt.hardware_info import get_hardware_info
from src.gui.qt.widgets.discrete_slider import DiscreteSlider
from src.gui.export_queue import ExportJob
from src.gui.qt._mixins.render_mixin import RenderMixin


def _get_app() -> QApplication:
    return QApplication.instance() or QApplication([])


# =========================================================================
# CASE A: AMD=False, NVIDIA=False, Intel=True, CPU=True
# Expected: ['auto', 'intel', 'cpu'], Default auto: intel
# =========================================================================
def test_case_a_intel_and_cpu_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        amd_available=False,
        amd_reason="No AMD GPU",
        nvidia_available=False,
        nvidia_reason="Driver too old",
        intel_available=True,
        intel_reason="Intel UHD 730 (QSV: HEVC / H.264)",
        cpu_available=True,
        cpu_reason="Available",
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    backends = get_available_backends(mock_caps)
    assert backends == ["auto", "intel", "cpu"]

    tab = RenderTab()
    tab._populate_encoders(preserve_selection=False)

    visible = [tab.cmb_encoder.itemText(i) for i in range(tab.cmb_encoder.count())]
    assert visible == ["auto", "intel", "cpu"]
    assert "amd" not in visible
    assert "nv" not in visible

    assert resolve_auto_backend(mock_caps) == "intel"


# =========================================================================
# CASE B: AMD=True, NVIDIA=False, Intel=False, CPU=True
# Expected: ['auto', 'amd', 'cpu'], Default auto: amd
# =========================================================================
def test_case_b_amd_and_cpu_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        amd_available=True,
        amd_reason="AMF available",
        nvidia_available=False,
        nvidia_reason="No NVIDIA GPU",
        intel_available=False,
        intel_reason="No Intel GPU",
        cpu_available=True,
        cpu_reason="Available",
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    backends = get_available_backends(mock_caps)
    assert backends == ["auto", "amd", "cpu"]

    tab = RenderTab()
    tab._populate_encoders(preserve_selection=False)

    visible = [tab.cmb_encoder.itemText(i) for i in range(tab.cmb_encoder.count())]
    assert visible == ["auto", "amd", "cpu"]
    assert "nv" not in visible
    assert "intel" not in visible

    assert resolve_auto_backend(mock_caps) == "amd"


# =========================================================================
# CASE C: AMD=False, NVIDIA=True, Intel=True, CPU=True
# Expected: ['auto', 'nv', 'intel', 'cpu']
# =========================================================================
def test_case_c_nvidia_intel_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        amd_available=False,
        amd_reason="No AMD GPU",
        nvidia_available=True,
        nvidia_reason="NVENC available",
        intel_available=True,
        intel_reason="Intel QSV available",
        cpu_available=True,
        cpu_reason="Available",
        nvidia_h264_nvenc=True,
        nvidia_hevc_nvenc=True,
        nvidia_codecs=["H.264", "H.265"],
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    backends = get_available_backends(mock_caps)
    assert backends == ["auto", "nv", "intel", "cpu"]

    tab = RenderTab()
    tab._populate_encoders(preserve_selection=False)

    visible = [tab.cmb_encoder.itemText(i) for i in range(tab.cmb_encoder.count())]
    assert visible == ["auto", "nv", "intel", "cpu"]
    assert "amd" not in visible

    assert resolve_auto_backend(mock_caps) == "nv"


# =========================================================================
# CASE D: All GPU vendors available
# Expected: ['auto', 'amd', 'nv', 'intel', 'cpu']
# =========================================================================
def test_case_d_all_vendors_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        amd_available=True,
        amd_reason="AMF available",
        nvidia_available=True,
        nvidia_reason="NVENC available",
        intel_available=True,
        intel_reason="QSV available",
        cpu_available=True,
        cpu_reason="Available",
        nvidia_h264_nvenc=True,
        nvidia_hevc_nvenc=True,
        nvidia_codecs=["H.264", "H.265"],
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    backends = get_available_backends(mock_caps)
    assert backends == ["auto", "amd", "nv", "intel", "cpu"]

    tab = RenderTab()
    tab._populate_encoders(preserve_selection=False)

    visible = [tab.cmb_encoder.itemText(i) for i in range(tab.cmb_encoder.count())]
    assert visible == ["auto", "amd", "nv", "intel", "cpu"]


# =========================================================================
# CASE E: Saved encoder=nv, NVIDIA unavailable, Intel available
# Expected GUI: intel before render, logged structured fallback
# =========================================================================
def test_case_e_saved_stale_encoder_fallback(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        amd_available=False,
        amd_reason="No AMD GPU",
        nvidia_available=False,
        nvidia_reason="Driver 582.78 incompatible with FFmpeg NVENC",
        intel_available=True,
        intel_reason="Intel UHD 730 (QSV: HEVC / H.264)",
        cpu_available=True,
        cpu_reason="Available",
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    tab = RenderTab()
    tab.apply_export_settings({"encoder": "nv"})

    assert tab.cmb_encoder.currentText() == "intel"
    captured = capsys.readouterr().out
    assert "[ENCODER FALLBACK]" in captured
    assert "requested=nv" in captured
    assert "resolved=intel" in captured
    assert "reason=hardware_capability" in captured


# =========================================================================
# CASE F: Forced unavailable nv reaches export safety gate
# Expected: BLOCKED (RuntimeError) and SILENT_CROSS_VENDOR_FALLBACK=NO
# =========================================================================
def test_case_f_export_safety_gate_blocks_unavailable_nv(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_caps = BackendCapabilities(
        amd_available=False,
        amd_reason="No AMD GPU",
        nvidia_available=False,
        nvidia_reason="Driver too old",
        intel_available=True,
        intel_reason="Intel QSV available",
        cpu_available=True,
        cpu_reason="Available",
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    class MockRenderer(RenderMixin):
        def __init__(self):
            self.video_path = None

    renderer = MockRenderer()
    with pytest.raises(RuntimeError) as exc_info:
        renderer._render_pipeline({"encoder": "nv"})

    err = str(exc_info.value)
    assert "UNSUPPORTED_BACKEND_RENDER_START=BLOCKED" in err
    assert "SILENT_CROSS_VENDOR_FALLBACK=NO" in err
    assert "nv" in err


# =========================================================================
# CASE G: NVIDIA H264+HEVC available, AV1 unavailable
# Expected NVIDIA codecs: H264, HEVC; AV1 hidden
# =========================================================================
def test_case_g_nvidia_codecs_h264_hevc_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        nvidia_available=True,
        nvidia_reason="Available",
        nvidia_h264_nvenc=True,
        nvidia_hevc_nvenc=True,
        nvidia_av1_nvenc=False,
        nvidia_codecs=["H.264", "H.265"],
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    tab = RenderTab()
    assert isinstance(tab.cmb_nvidia_codec, DiscreteSlider)
    tab._populate_nvidia_codecs(preserve_selection=False)

    visible_labels = [item[0] for item in tab.cmb_nvidia_codec._items]
    assert "H.264" in visible_labels
    assert "H.265" in visible_labels
    assert "AV1" not in visible_labels


# =========================================================================
# CASE H: NVIDIA all codecs available (H264, HEVC, AV1)
# Expected: H264, HEVC, AV1 all visible
# =========================================================================
def test_case_h_nvidia_all_codecs_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        nvidia_available=True,
        nvidia_reason="Available",
        nvidia_h264_nvenc=True,
        nvidia_hevc_nvenc=True,
        nvidia_av1_nvenc=True,
        nvidia_codecs=["H.264", "H.265", "AV1"],
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    tab = RenderTab()
    tab._populate_nvidia_codecs(preserve_selection=False)

    visible_labels = [item[0] for item in tab.cmb_nvidia_codec._items]
    assert visible_labels == ["H.264", "H.265", "AV1"]


# =========================================================================
# NVIDIA Widgets Visual Consistency: DiscreteSlider for Codec & Quality
# =========================================================================
def test_nvidia_widgets_are_discrete_sliders() -> None:
    _get_app()
    tab = RenderTab()
    assert isinstance(tab.cmb_nvidia_codec, DiscreteSlider)
    assert isinstance(tab.cmb_nvidia_quality, DiscreteSlider)

    # Check quality items
    quality_labels = [item[0] for item in tab.cmb_nvidia_quality._items]
    assert quality_labels == ["Fast", "Quality", "Max Quality"]


# =========================================================================
# Queue Cross-Vendor Fallback Protection: QUEUE_CROSS_VENDOR_SILENT_FALLBACK=NO
# =========================================================================
def test_queue_cross_vendor_silent_fallback_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        amd_available=False,
        amd_reason="No AMD GPU",
        nvidia_available=False,
        nvidia_reason="Incompatible driver",
        intel_available=True,
        intel_reason="Intel QSV available",
        cpu_available=True,
        cpu_reason="Available",
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    tab = RenderTab()

    # Create dummy existing video file for snapshot validation
    video_file = tmp_path / "dummy_valid.mp4"
    video_file.write_bytes(b"dummy")

    job = ExportJob(
        job_id="test-queue-safety",
        video_paths=[str(video_file)],
        output_path=str(tmp_path / "out.mp4"),
        layout={"indicators": {}},
        options={"encoder": "nv"},
    )

    tab._dispatch_queue_job_render(job)
    assert job.render_status == "error"
    assert "UNSUPPORTED_BACKEND_QUEUE_START=BLOCKED" in job.render_error
    assert "QUEUE_CROSS_VENDOR_SILENT_FALLBACK=NO" in job.render_error


# =========================================================================
# Hardware Panel & RenderTab Parity
# =========================================================================
def test_hardware_panel_and_rendertab_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        amd_available=False,
        amd_reason="No AMD",
        nvidia_available=False,
        nvidia_reason="No NV",
        intel_available=True,
        intel_reason="Dostępne (QSV: HEVC / H.264)",
        cpu_available=True,
        cpu_reason="Dostępne (libx265 / libx264)",
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    hw = get_hardware_info(force_refresh=True)
    tab = RenderTab()
    tab._populate_encoders(preserve_selection=False)

    visible_encoders = [tab.cmb_encoder.itemText(i) for i in range(tab.cmb_encoder.count())]

    # Panel check
    assert hw.enc_amd == "Niedostępne"
    assert "amd" not in visible_encoders

    assert hw.enc_nvidia == "Niedostępne"
    assert "nv" not in visible_encoders

    assert "Dostępne" in hw.enc_intel
    assert "intel" in visible_encoders

    assert "Dostępne" in hw.enc_cpu
    assert "cpu" in visible_encoders


# =========================================================================
# Real Host Probe on current i5-12400 / UHD 730 / Quadro P400
# =========================================================================
def test_real_host_probe_truth() -> None:
    _get_app()
    invalidate_backend_capabilities_cache()
    caps = query_backend_capabilities(force_refresh=True)

    # 1. AMD truth: No AMD GPU on this host
    assert caps.amd_available is False
    assert "AMD" in caps.amd_reason or "Radeon" in caps.amd_reason

    # 2. NVIDIA truth: Quadro P400 is physically present with driver 582.78,
    # and working via vendor-isolated FFmpeg 8.1 with NVENC SDK 13.0
    assert caps.nvidia_gpu_present is True
    assert caps.nvidia_driver_present is True
    assert caps.nvidia_available is True
    assert "H.265" in caps.nvidia_codecs
    assert "H.264" in caps.nvidia_codecs
    assert "AV1" not in caps.nvidia_codecs

    # 3. Intel truth: UHD 730 is available with QSV
    assert caps.intel_available is True
    assert caps.intel_caps.get("HEVC_AVAILABLE") is True
    assert caps.intel_caps.get("H264_AVAILABLE") is True
    assert caps.intel_caps.get("AV1_AVAILABLE") is False

    # 4. CPU truth: Software encoders available
    assert caps.cpu_available is True

    # 5. GUI Dropdown truth on this host: auto, nv, intel, cpu (AMD absent)
    tab = RenderTab()
    visible_codecs = [tab.cmb_encoder.itemText(i) for i in range(tab.cmb_encoder.count())]
    assert visible_codecs == ["auto", "nv", "intel", "cpu"]
    assert tab.cmb_encoder.currentText() == "auto"


# =========================================================================
# EDGE CASE 1: No GPU + No CPU encoder => No fake backend (none)
# =========================================================================
def test_no_gpu_no_cpu_encoder_no_fake_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = BackendCapabilities(
        amd_available=False,
        amd_reason="No AMD GPU",
        nvidia_available=False,
        nvidia_reason="No NVIDIA GPU",
        intel_available=False,
        intel_reason="No Intel GPU",
        cpu_available=False,
        cpu_reason="No software encoders found",
    )
    monkeypatch.setattr("src.ffmpeg.backend_capabilities.query_backend_capabilities", lambda *a, **k: mock_caps)

    # 1. resolve_auto_backend must return "none" - NO_BACKEND_FALSE_CPU_FALLBACK=NO
    resolved_auto = resolve_auto_backend(mock_caps)
    assert resolved_auto == "none"
    assert resolved_auto != "cpu"

    # 2. get_available_backends must be empty
    backends = get_available_backends(mock_caps)
    assert backends == []
    assert "cpu" not in backends
    assert "auto" not in backends

    # 3. GUI shows 'none' and never a fake CPU backend
    tab = RenderTab()
    tab._populate_encoders(preserve_selection=False)
    visible = [tab.cmb_encoder.itemText(i) for i in range(tab.cmb_encoder.count())]
    assert visible == ["none"]
    assert "cpu" not in visible

    # 4. Export safety gate blocks render start cleanly
    class MockRenderer(RenderMixin):
        def __init__(self):
            self.video_path = None

    renderer = MockRenderer()
    with pytest.raises(RuntimeError) as exc_info:
        renderer._render_pipeline({"encoder": "auto"})

    err = str(exc_info.value)
    assert "UNSUPPORTED_BACKEND_RENDER_START=BLOCKED" in err
    assert "NO_BACKEND_FALSE_CPU_FALLBACK=NO" in err or "none" in err


# =========================================================================
# EDGE CASE 2: AMD AMF present + native DLL missing => AMD unavailable
# =========================================================================
def test_amd_amf_present_native_dll_missing_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.ffmpeg.backend_capabilities import _probe_amd_environment

    # Simulate AMD GPU present in system
    monkeypatch.setattr("src.gui.qt.hardware_info._get_gpus", lambda: ["AMD Radeon RX 6700 XT"])

    # Simulate AMF available in FFmpeg
    monkeypatch.setattr("src.ffmpeg.detection._test_encoder", lambda enc, ffmpeg: True)

    # Simulate telem_amd_native.dll MISSING
    missing_dll = tmp_path / "nonexistent" / "telem_amd_native.dll"
    monkeypatch.setattr("src.runtime_paths.get_amd_native_dll", lambda: missing_dll)

    amd_ok, reason = _probe_amd_environment("dummy_ffmpeg")
    assert amd_ok is False
    assert "telem_amd_native.dll" in reason


# =========================================================================
# EDGE CASE 3: AMD AMF + native DLL + deps present => AMD available
# =========================================================================
def test_amd_amf_present_native_dll_and_deps_present_available(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.ffmpeg.backend_capabilities import _probe_amd_environment

    # Simulate AMD GPU present
    monkeypatch.setattr("src.gui.qt.hardware_info._get_gpus", lambda: ["AMD Radeon RX 6700 XT"])

    # Simulate AMF available in FFmpeg
    monkeypatch.setattr("src.ffmpeg.detection._test_encoder", lambda enc, ffmpeg: True)

    # Create dummy DLL file
    dummy_dll = tmp_path / "telem_amd_native.dll"
    dummy_dll.write_bytes(b"dummy_dll_binary")
    monkeypatch.setattr("src.runtime_paths.get_amd_native_dll", lambda: dummy_dll)

    # Mock successful DLL loading and ABI check
    class MockAmdDll:
        def __init__(self):
            self.telem_amd_get_abi_version = lambda: 1

    monkeypatch.setattr("ctypes.CDLL", lambda *a, **k: MockAmdDll())

    amd_ok, reason = _probe_amd_environment("dummy_ffmpeg")
    assert amd_ok is True
    assert "AMF" in reason
