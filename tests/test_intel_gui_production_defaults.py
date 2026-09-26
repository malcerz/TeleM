"""Unit tests for Intel production configuration defaults and override semantics."""
import os
import pytest

from src.ffmpeg.intel_config import (
    DEFAULT_INTEL_HUD_MULTIRECT,
    DEFAULT_INTEL_HUD_WORKERS,
    DEFAULT_INTEL_HUD_PREFETCH,
    DEFAULT_INTEL_HUD_TEXTURE_RING,
    DEFAULT_INTEL_VP_RING,
    DEFAULT_INTEL_ENCODE_ASYNC,
    get_intel_hud_multirect,
    get_intel_hud_workers,
    get_intel_hud_prefetch,
    get_intel_hud_texture_ring,
    get_intel_vp_ring,
    get_intel_encode_async,
    get_intel_hw_decode,
    resolve_intel_production_config,
)


def test_intel_production_constants():
    assert DEFAULT_INTEL_HUD_MULTIRECT is True
    assert DEFAULT_INTEL_HUD_WORKERS == 4
    assert DEFAULT_INTEL_HUD_PREFETCH == 8
    assert DEFAULT_INTEL_HUD_TEXTURE_RING == 1
    assert DEFAULT_INTEL_VP_RING == 8
    assert DEFAULT_INTEL_ENCODE_ASYNC == 8


def test_intel_production_defaults_unset(monkeypatch):
    for k in (
        "TELEM_INTEL_HUD_MULTIRECT",
        "TELEM_INTEL_HUD_WORKERS",
        "TELEM_INTEL_HUD_PREFETCH",
        "TELEM_INTEL_HUD_TEXTURE_RING",
        "TELEM_INTEL_VP_RING_DEPTH",
        "TELEM_INTEL_MFX_ASYNC_DEPTH",
        "TELEM_INTEL_HEVC_HW_DECODE",
    ):
        monkeypatch.delenv(k, raising=False)

    cfg = resolve_intel_production_config(preview=False)
    assert cfg.multirect is True
    assert cfg.hud_workers == 4
    assert cfg.hud_prefetch == 8
    assert cfg.hud_texture_ring == 1
    assert cfg.vp_ring == 8
    assert cfg.encode_async == 8
    assert cfg.hw_decode is True
    assert cfg.preview is False

    log = cfg.format_log()
    assert "INTEL_PRODUCTION_CONFIG:" in log
    assert "multirect=TRUE" in log
    assert "hud_workers=4" in log
    assert "hud_prefetch=8" in log
    assert "hud_texture_ring=1" in log
    assert "vp_ring=8" in log
    assert "encode_async=8" in log
    assert "hw_decode=TRUE" in log
    assert "preview=FALSE" in log


def test_intel_production_explicit_overrides(monkeypatch):
    monkeypatch.setenv("TELEM_INTEL_HUD_MULTIRECT", "0")
    assert get_intel_hud_multirect() is False

    monkeypatch.setenv("TELEM_INTEL_HUD_MULTIRECT", "1")
    assert get_intel_hud_multirect() is True

    monkeypatch.setenv("TELEM_INTEL_HUD_WORKERS", "2")
    assert get_intel_hud_workers() == 2

    monkeypatch.setenv("TELEM_INTEL_HUD_WORKERS", "invalid")
    assert get_intel_hud_workers() == 4

    monkeypatch.setenv("TELEM_INTEL_HUD_PREFETCH", "16")
    assert get_intel_hud_prefetch() == 16

    monkeypatch.setenv("TELEM_INTEL_VP_RING_DEPTH", "4")
    assert get_intel_vp_ring() == 4

    monkeypatch.setenv("TELEM_INTEL_MFX_ASYNC_DEPTH", "4")
    assert get_intel_encode_async() == 4

    monkeypatch.setenv("TELEM_INTEL_HEVC_HW_DECODE", "0")
    assert get_intel_hw_decode() is False
