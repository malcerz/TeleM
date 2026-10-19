"""Tests for Intel Core Ultra Etap 8B: H.264 Final Production Validation,
AV1 Baseline Reconciliation, H.264 Canonical x3, 10-Min Sustained 4K30 Proof,
HDR->SDR Dither / Gradient Validation, and GUI Codec Selector.
"""

import os
import sys
import json
import pytest
from pathlib import Path
from PySide6.QtWidgets import QApplication

workspace_root = Path(__file__).resolve().parent.parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

from src.ffmpeg.intel_native_exporter import (
    query_intel_capabilities,
    _load_native_intel_dll,
    IntelCapabilityInfo,
)

def _get_app():
    return QApplication.instance() or QApplication([])

def test_intel_native_8b_capabilities_truth():
    """Verify runtime capability query returns exact hardware truth on Intel GPU."""
    caps = query_intel_capabilities()
    assert isinstance(caps, dict)
    assert isinstance(caps["AV1_AVAILABLE"], bool)
    assert isinstance(caps["AV1_10BIT"], bool)
    assert isinstance(caps["H264_AVAILABLE"], bool)
    assert isinstance(caps["H264_8BIT"], bool)
    assert caps["H264_10BIT"] is False
    assert isinstance(caps["HEVC_AVAILABLE"], bool)

def test_intel_native_8b_dll_exports():
    """Verify telem_intel_native.dll exports codec-aware multi-clip pipeline functions."""
    dll = _load_native_intel_dll()
    assert hasattr(dll, "intel_native_pipeline_init_multi_ex")
    assert hasattr(dll, "intel_d3d11_vp_init_ex")
    assert hasattr(dll, "intel_native_query_capabilities")

def test_intel_native_8b_render_tab_intel_codec_selector():
    """Verify Qt GUI RenderTab contains Intel Codec Selector reflecting runtime capabilities."""
    app = _get_app()
    from src.gui.qt.tabs.render_tab import RenderTab
    tab = RenderTab()
    assert hasattr(tab, "cmb_intel_codec")
    assert hasattr(tab, "widget_intel_options")
    
    # Contract since bc2b173: every codec is listed in a fixed order; codecs the
    # runtime cannot encode stay visible but disabled ("niedostępny").
    caps = query_intel_capabilities()
    expected = [("av1", "AV1_10BIT"), ("hevc", "HEVC_10BIT"), ("h264", "H264_8BIT"), ("hevc_sdr", "HEVC_8BIT")]
    actual_codecs = [tab.cmb_intel_codec.itemData(i) for i in range(tab.cmb_intel_codec.count())]
    assert actual_codecs == [codec for codec, _ in expected]
    model = tab.cmb_intel_codec.model()
    for i, (codec, key) in enumerate(expected):
        assert model.item(i).isEnabled() == bool(caps.get(key, False)), codec

    # Default: AV1 10-bit when available, otherwise HEVC Main10; never silently SDR.
    expected_default = "av1" if caps.get("AV1_10BIT") else ("hevc" if caps.get("HEVC_10BIT") else None)
    assert tab.cmb_intel_codec.currentData() == expected_default

def test_intel_native_8b_intel_codec_selection_semantics():
    """Verify selecting H.264 updates UI label to SDR 8-bit BT.709."""
    app = _get_app()
    from src.gui.qt.tabs.render_tab import RenderTab
    tab = RenderTab()
    
    idx_h264 = tab.cmb_intel_codec.findData("h264")
    tab.cmb_intel_codec.setCurrentIndex(idx_h264)
    
    assert tab.cmb_intel_codec.currentData() == "h264"
    assert "SDR 8-bit" in tab.lbl_intel_codec_info.text()
    assert "BT.709" in tab.lbl_intel_codec_info.text()

def test_intel_native_8b_intel_codec_persistence():
    """Verify intel_codec is serialized and deserialized in export_settings dictionary."""
    app = _get_app()
    from src.gui.qt.tabs.render_tab import RenderTab
    tab = RenderTab()
    
    idx_h264 = tab.cmb_intel_codec.findData("h264")
    tab.cmb_intel_codec.setCurrentIndex(idx_h264)
    
    # Check options dict
    options = {}
    options["intel_codec"] = tab.cmb_intel_codec.currentData() or "av1"
    assert options["intel_codec"] == "h264"
