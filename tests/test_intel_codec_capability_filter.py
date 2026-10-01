"""Deterministic tests for Intel codec capability-driven GUI filtering and safety gates.

Covers:
- Phase 1 & 2: Capability truth rules (AV1 10-bit, HEVC 10-bit, H.264 8-bit).
- Phase 3: Hidden unsupported items (AV1 hidden when unavailable).
- Phase 4: Dynamic '(Zalecany)' recommendation label.
- Phase 5: Conservative probe failure fallback and logging.
- Phase 6: Saved project/settings fallback (requested=av1 on machine without AV1 -> hevc).
- Phase 7: Encoder change refresh (intel -> cpu -> intel).
- Phase 8: Startup selection resolution.
- Phase 9: Export safety gate (UNSUPPORTED_CODEC_RENDER_START=BLOCKED).
- Phase 10: Hardware panel parity (Możliwości sprzętu vs codec dropdown).
- Phase 11 & 12: Real i5-12400 probe and simulated AV1-capable Core Ultra / Arc.
- Phase 13: Cases A, B, C, D, E deterministic combinations.
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

from src.ffmpeg.intel_native_exporter import (
    query_intel_capabilities,
    resolve_supported_intel_codec,
    invalidate_intel_capabilities_cache,
    export_intel_native_d3d11,
)
from src.gui.qt.tabs.render_tab import RenderTab
from src.gui.qt.hardware_info import get_hardware_info


def _get_app() -> QApplication:
    return QApplication.instance() or QApplication([])


# =========================================================================
# Case A: AV1=True, AV1_10BIT=True, HEVC=True, HEVC_10BIT=True, H264=True
# Expected: AV1, HEVC, H264; Default: AV1
# =========================================================================
def test_case_a_full_av1_capable_system(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = {
        "AV1_AVAILABLE": True,
        "AV1_10BIT": True,
        "HEVC_AVAILABLE": True,
        "HEVC_10BIT": True,
        "H264_AVAILABLE": True,
        "H264_8BIT": True,
        "H264_10BIT": False,
    }
    monkeypatch.setattr("src.ffmpeg.intel_native_exporter.query_intel_capabilities", lambda *a, **k: dict(mock_caps))

    tab = RenderTab()
    tab._populate_intel_codecs(preserve_selection=False)

    visible_codecs = [tab.cmb_intel_codec.itemData(i) for i in range(tab.cmb_intel_codec.count())]
    visible_labels = [tab.cmb_intel_codec.itemText(i) for i in range(tab.cmb_intel_codec.count())]

    assert visible_codecs == ["av1", "hevc", "h264"]
    assert "(Zalecany)" in visible_labels[0]
    assert "AV1" in visible_labels[0]
    assert "(Zalecany)" not in visible_labels[1]
    assert "(Zalecany)" not in visible_labels[2]
    assert tab.cmb_intel_codec.currentData() == "av1"
    assert "HDR 10-bit" in tab.lbl_intel_codec_info.text()


# =========================================================================
# Case B: AV1=False, HEVC=True, HEVC_10BIT=True, H264=True (i5-12400)
# Expected: HEVC, H264; Default: HEVC; AV1 hidden
# =========================================================================
def test_case_b_no_av1_hevc_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = {
        "AV1_AVAILABLE": False,
        "AV1_10BIT": False,
        "HEVC_AVAILABLE": True,
        "HEVC_10BIT": True,
        "H264_AVAILABLE": True,
        "H264_8BIT": True,
        "H264_10BIT": False,
    }
    monkeypatch.setattr("src.ffmpeg.intel_native_exporter.query_intel_capabilities", lambda *a, **k: dict(mock_caps))

    tab = RenderTab()
    tab._populate_intel_codecs(preserve_selection=False)

    visible_codecs = [tab.cmb_intel_codec.itemData(i) for i in range(tab.cmb_intel_codec.count())]
    visible_labels = [tab.cmb_intel_codec.itemText(i) for i in range(tab.cmb_intel_codec.count())]

    assert "av1" not in visible_codecs
    assert visible_codecs == ["hevc", "h264"]
    assert "(Zalecany)" in visible_labels[0]
    assert "H.265" in visible_labels[0]
    assert "(Zalecany)" not in visible_labels[1]
    assert tab.cmb_intel_codec.currentData() == "hevc"
    assert "HDR 10-bit" in tab.lbl_intel_codec_info.text()


# =========================================================================
# Case C: AV1=False, HEVC=False, H264=True
# Expected: H264 only; Default: H264
# =========================================================================
def test_case_c_h264_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = {
        "AV1_AVAILABLE": False,
        "AV1_10BIT": False,
        "HEVC_AVAILABLE": False,
        "HEVC_10BIT": False,
        "H264_AVAILABLE": True,
        "H264_8BIT": True,
        "H264_10BIT": False,
    }
    monkeypatch.setattr("src.ffmpeg.intel_native_exporter.query_intel_capabilities", lambda *a, **k: dict(mock_caps))

    tab = RenderTab()
    tab._populate_intel_codecs(preserve_selection=False)

    visible_codecs = [tab.cmb_intel_codec.itemData(i) for i in range(tab.cmb_intel_codec.count())]
    visible_labels = [tab.cmb_intel_codec.itemText(i) for i in range(tab.cmb_intel_codec.count())]

    assert visible_codecs == ["h264"]
    assert "(Zalecany)" in visible_labels[0]
    assert "H.264" in visible_labels[0]
    assert tab.cmb_intel_codec.currentData() == "h264"
    assert "SDR 8-bit" in tab.lbl_intel_codec_info.text()


# =========================================================================
# Case D: All hardware Intel codecs unavailable
# Expected: No invalid Intel hardware codec selected, placeholder disabled
# =========================================================================
def test_case_d_all_codecs_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    mock_caps = {
        "AV1_AVAILABLE": False,
        "AV1_10BIT": False,
        "HEVC_AVAILABLE": False,
        "HEVC_10BIT": False,
        "H264_AVAILABLE": False,
        "H264_8BIT": False,
        "H264_10BIT": False,
    }
    monkeypatch.setattr("src.ffmpeg.intel_native_exporter.query_intel_capabilities", lambda *a, **k: dict(mock_caps))

    tab = RenderTab()
    tab._populate_intel_codecs(preserve_selection=False)

    visible_codecs = [tab.cmb_intel_codec.itemData(i) for i in range(tab.cmb_intel_codec.count())]
    assert visible_codecs == ["none"]
    assert tab.cmb_intel_codec.currentData() == "none"

    model = tab.cmb_intel_codec.model()
    item = model.item(0)
    assert item is not None
    assert not item.isEnabled()
    assert "Brak" in tab.lbl_intel_codec_info.text()


# =========================================================================
# Case E: Saved av1 setting + machine without AV1 -> fallback to hevc
# =========================================================================
def test_case_e_saved_av1_setting_fallback(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    _get_app()
    mock_caps = {
        "AV1_AVAILABLE": False,
        "AV1_10BIT": False,
        "HEVC_AVAILABLE": True,
        "HEVC_10BIT": True,
        "H264_AVAILABLE": True,
        "H264_8BIT": True,
        "H264_10BIT": False,
    }
    monkeypatch.setattr("src.ffmpeg.intel_native_exporter.query_intel_capabilities", lambda *a, **k: dict(mock_caps))

    tab = RenderTab()
    # Apply settings loaded from project saved on Core Ultra with intel_codec="av1"
    tab.apply_export_settings({"intel_codec": "av1"})

    assert tab.cmb_intel_codec.currentData() == "hevc"
    assert "H.265" in tab.cmb_intel_codec.currentText()

    captured = capsys.readouterr().out
    assert "[INTEL CODEC FALLBACK]" in captured
    assert "requested=av1" in captured
    assert "available=0" in captured
    assert "resolved=hevc" in captured
    assert "reason=hardware_capability" in captured


# =========================================================================
# Export Safety Gate: Attempts to render unsupported AV1 must be blocked
# =========================================================================
def test_export_safety_gate_blocks_unsupported_av1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    mock_caps = {
        "AV1_AVAILABLE": False,
        "AV1_10BIT": False,
        "HEVC_AVAILABLE": True,
        "HEVC_10BIT": True,
        "H264_AVAILABLE": True,
        "H264_8BIT": True,
        "H264_10BIT": False,
    }
    monkeypatch.setattr("src.ffmpeg.intel_native_exporter.query_intel_capabilities", lambda *a, **k: dict(mock_caps))

    with pytest.raises(RuntimeError) as exc_info:
        export_intel_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=["dummy.mp4"],
            output_file="out.mp4",
            duration_s=1.0,
            video_width=1920,
            video_height=1080,
            start_dt_utc=None,
            tz_offset_hours=0,
            speed_samples=[],
            track_samples=[],
            alt_samples=[],
            font_path="",
            layout={},
            field_samples={},
            codec="av1",
        )

    assert "UNSUPPORTED_CODEC_RENDER_START=BLOCKED" in str(exc_info.value)
    captured = capsys.readouterr().out
    assert "UNSUPPORTED_CODEC_RENDER_START=BLOCKED" in captured


# =========================================================================
# Hardware Panel Parity: Możliwości sprzętu vs codec dropdown
# =========================================================================
def test_hardware_panel_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_caps = {
        "AV1_AVAILABLE": False,
        "AV1_10BIT": False,
        "HEVC_AVAILABLE": True,
        "HEVC_10BIT": True,
        "H264_AVAILABLE": True,
        "H264_8BIT": True,
        "H264_10BIT": False,
    }
    monkeypatch.setattr("src.ffmpeg.intel_native_exporter.query_intel_capabilities", lambda *a, **k: dict(mock_caps))

    info = get_hardware_info(force_refresh=True)
    assert "AV1" not in info.enc_intel
    assert "HEVC" in info.enc_intel
    assert "H.264" in info.enc_intel


# =========================================================================
# Phase 7: Dynamic refresh on encoder switch (intel -> cpu -> intel)
# =========================================================================
def test_encoder_change_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    _get_app()
    caps_state = {
        "AV1_AVAILABLE": False,
        "AV1_10BIT": False,
        "HEVC_AVAILABLE": True,
        "HEVC_10BIT": True,
        "H264_AVAILABLE": True,
        "H264_8BIT": True,
        "H264_10BIT": False,
    }
    monkeypatch.setattr("src.ffmpeg.intel_native_exporter.query_intel_capabilities", lambda *a, **k: dict(caps_state))

    tab = RenderTab()
    assert [tab.cmb_intel_codec.itemData(i) for i in range(tab.cmb_intel_codec.count())] == ["hevc", "h264"]

    # Switch to CPU
    idx_cpu = tab.cmb_encoder.findText("cpu")
    tab.cmb_encoder.setCurrentIndex(idx_cpu)
    assert not tab.widget_cpu_options.isHidden()
    assert tab.widget_intel_options.isHidden()

    # Simulate dynamic capability update (e.g. driver update allows AV1)
    caps_state["AV1_AVAILABLE"] = True
    caps_state["AV1_10BIT"] = True

    # Switch back to Intel
    idx_intel = tab.cmb_encoder.findText("intel")
    tab.cmb_encoder.setCurrentIndex(idx_intel)
    assert not tab.widget_intel_options.isHidden()

    # Codecs must refresh without restarting application
    assert [tab.cmb_intel_codec.itemData(i) for i in range(tab.cmb_intel_codec.count())] == ["av1", "hevc", "h264"]
    assert tab.cmb_intel_codec.currentData() == "hevc"  # preserved prior valid selection


# =========================================================================
# Phase 11: Real verification on current host machine (Core i5-12400)
# =========================================================================
def test_real_machine_i5_12400_runtime_truth() -> None:
    _get_app()
    invalidate_intel_capabilities_cache()
    caps = query_intel_capabilities(force_refresh=True)

    # Machine truth on i5-12400 UHD 730
    assert caps["AV1_AVAILABLE"] is False
    assert caps["AV1_10BIT"] is False
    assert caps["H264_AVAILABLE"] is True
    assert caps["H264_8BIT"] is True
    assert caps["HEVC_AVAILABLE"] is True
    assert caps["HEVC_10BIT"] is True

    tab = RenderTab()
    visible_codecs = [tab.cmb_intel_codec.itemData(i) for i in range(tab.cmb_intel_codec.count())]
    assert "av1" not in visible_codecs
    assert "hevc" in visible_codecs
    assert "h264" in visible_codecs
    assert tab.cmb_intel_codec.currentData() == "hevc"
    assert "Zalecany" in tab.cmb_intel_codec.currentText()
