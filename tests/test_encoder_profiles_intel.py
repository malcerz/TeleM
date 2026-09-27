"""Focused unit tests for shared encoder quality-profile model and Intel resolver."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from src.ffmpeg.encoder_profile import (
    EncoderProfile,
    DEFAULT_ENCODER_PROFILE,
    LEGACY_DEFAULT_ENCODER_PROFILE,
    resolve_encoder_profile,
)
from src.ffmpeg.intel_config import (
    MFX_TARGETUSAGE_BEST_SPEED,
    MFX_TARGETUSAGE_BALANCED,
    MFX_TARGETUSAGE_BEST_QUALITY,
    CURRENT_H264_TARGET_USAGE,
    CURRENT_HEVC_TARGET_USAGE,
    CURRENT_AV1_TARGET_USAGE,
    resolve_intel_target_usage,
    resolve_intel_encoder_config,
)


def test_encoder_profile_enum_values():
    """Verify internal stable string values and defaults."""
    assert EncoderProfile.FAST.value == "fast"
    assert EncoderProfile.BALANCED.value == "balanced"
    assert EncoderProfile.QUALITY.value == "quality"
    assert DEFAULT_ENCODER_PROFILE == EncoderProfile.BALANCED
    assert LEGACY_DEFAULT_ENCODER_PROFILE == EncoderProfile.FAST


def test_encoder_profile_polish_labels():
    """Verify Polish display names and choices helper."""
    assert EncoderProfile.FAST.display_name == "Szybki"
    assert EncoderProfile.BALANCED.display_name == "Zbalansowany"
    assert EncoderProfile.QUALITY.display_name == "Jakość"

    choices = EncoderProfile.choices()
    assert len(choices) == 3
    assert ("fast", "Szybki") in choices
    assert ("balanced", "Zbalansowany") in choices
    assert ("quality", "Jakość") in choices


def test_encoder_profile_parser_and_legacy_fallback():
    """Verify parser robustness against case, Polish labels, and legacy defaults."""
    # Exact and case-insensitive
    assert EncoderProfile.from_str("fast") == EncoderProfile.FAST
    assert EncoderProfile.from_str("FAST") == EncoderProfile.FAST
    assert EncoderProfile.from_str("balanced") == EncoderProfile.BALANCED
    assert EncoderProfile.from_str("quality") == EncoderProfile.QUALITY

    # Polish labels
    assert EncoderProfile.from_str("Szybki") == EncoderProfile.FAST
    assert EncoderProfile.from_str("Zbalansowany") == EncoderProfile.BALANCED
    assert EncoderProfile.from_str("Jakość") == EncoderProfile.QUALITY
    assert EncoderProfile.from_str("jakosc") == EncoderProfile.QUALITY

    # Legacy / unknown fallback
    assert EncoderProfile.from_str(None, default=EncoderProfile.BALANCED) == EncoderProfile.BALANCED
    assert EncoderProfile.from_str(None, default=EncoderProfile.FAST) == EncoderProfile.FAST
    assert EncoderProfile.from_str("invalid_val", default=EncoderProfile.BALANCED) == EncoderProfile.BALANCED
    assert EncoderProfile.from_str("invalid_val", default=EncoderProfile.FAST) == EncoderProfile.FAST


def test_intel_production_baseline_parity():
    """Verify historical Intel production baseline (TU=7) is preserved for legacy projects."""
    assert CURRENT_H264_TARGET_USAGE == 7
    assert CURRENT_HEVC_TARGET_USAGE == 7
    assert CURRENT_AV1_TARGET_USAGE == 7

    # When legacy fallback is used (FAST), TargetUsage is exactly 7 (historical baseline)
    assert resolve_intel_target_usage("h264", LEGACY_DEFAULT_ENCODER_PROFILE) == 7
    assert resolve_intel_target_usage("hevc", LEGACY_DEFAULT_ENCODER_PROFILE) == 7
    assert resolve_intel_target_usage("av1", LEGACY_DEFAULT_ENCODER_PROFILE) == 7


def test_intel_codec_profile_mapping():
    """Verify semantic mapping: FAST=7 (speed), BALANCED=4 (balanced), QUALITY=1 (quality)."""
    codecs = ["h264", "hevc", "av1"]
    for c in codecs:
        assert resolve_intel_target_usage(c, EncoderProfile.FAST) == 7
        assert resolve_intel_target_usage(c, EncoderProfile.BALANCED) == 4
        assert resolve_intel_target_usage(c, EncoderProfile.QUALITY) == 1

        # Check symbolic constants
        assert resolve_intel_target_usage(c, EncoderProfile.FAST) == MFX_TARGETUSAGE_BEST_SPEED
        assert resolve_intel_target_usage(c, EncoderProfile.BALANCED) == MFX_TARGETUSAGE_BALANCED
        assert resolve_intel_target_usage(c, EncoderProfile.QUALITY) == MFX_TARGETUSAGE_BEST_QUALITY


def test_intel_effective_config_and_startup_log():
    """Verify effective config resolver and INTEL_ENCODER_PROFILE log formatting."""
    cfg_fast = resolve_intel_encoder_config("hevc", EncoderProfile.FAST, "40M", 3840, 2160)
    assert cfg_fast.target_usage == 7
    assert cfg_fast.target_usage_name == "BEST_SPEED"
    log_fast = cfg_fast.format_log()
    assert "INTEL_ENCODER_PROFILE:" in log_fast
    assert "profile=fast" in log_fast
    assert "target_usage=7 (BEST_SPEED)" in log_fast
    assert "bitrate=40M" in log_fast
    assert "resolution=3840x2160" in log_fast
    assert "bit_depth=10" in log_fast
    assert "hdr=YES" in log_fast

    cfg_bal = resolve_intel_encoder_config("hevc", EncoderProfile.BALANCED, "40M", 3840, 2160)
    assert cfg_bal.target_usage == 4
    assert cfg_bal.target_usage_name == "BALANCED"

    cfg_qual = resolve_intel_encoder_config("hevc", EncoderProfile.QUALITY, "40M", 3840, 2160)
    assert cfg_qual.target_usage == 1
    assert cfg_qual.target_usage_name == "BEST_QUALITY"


def test_gui_render_tab_apply_and_persistence():
    """Verify RenderTab apply_export_settings for new and legacy projects."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from src.gui.qt.tabs.render_tab import RenderTab

    rt = RenderTab()
    # New project default
    assert rt.get_encoder_profile() == EncoderProfile.BALANCED

    # Apply project with explicit FAST
    rt.apply_export_settings({"encoder_profile": "fast"})
    assert rt.get_encoder_profile() == EncoderProfile.FAST

    # Apply project with explicit QUALITY
    rt.apply_export_settings({"encoder_profile": "quality"})
    assert rt.get_encoder_profile() == EncoderProfile.QUALITY

    # Apply legacy project without 'encoder_profile' field -> MUST default to FAST (TU=7)
    rt.apply_export_settings({"target_codec": "HEVC", "target_bitrate_mbps": 40})
    assert rt.get_encoder_profile() == EncoderProfile.FAST
