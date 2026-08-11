"""Tests for src.gui.qt.mpv_hwdec — per-vendor mpv option builder."""

from __future__ import annotations

import pytest

from src.gui.qt.mpv_hwdec import (
    build_mpv_options,
    vendor_label,
)

# ── build_mpv_options ────────────────────────────────────────────────────

def test_build_mpv_options_cpu() -> None:
    """CPU vendor should disable hwdec and not set GPU context."""
    opts = build_mpv_options("cpu")
    assert opts["hwdec"] == "no"
    assert opts["keep_open"] == "yes"
    # No GPU-specific keys should leak
    assert "gpu_api" not in opts
    assert "gpu_context" not in opts
    assert "d3d11_adapter" not in opts


def test_build_mpv_options_nv() -> None:
    """NVIDIA uses d3d11va → nvdec → cuda → auto chain and d3d11 context."""
    opts = build_mpv_options("nv")
    assert "d3d11va" in opts["hwdec"]
    assert "nvdec" in opts["hwdec"]
    assert "auto" in opts["hwdec"]
    assert opts["gpu_api"] == "d3d11,opengl"
    assert "d3d11" in str(opts["gpu_context"])
    assert opts["keep_open"] == "yes"


def test_build_mpv_options_amd() -> None:
    """AMD uses d3d11va → dxva2 → auto (keep working path)."""
    opts = build_mpv_options("amd")
    assert "d3d11va" in opts["hwdec"]
    assert "dxva2" in opts["hwdec"]
    assert "auto" in opts["hwdec"]
    assert opts["gpu_api"] == "d3d11,opengl"
    assert "d3d11" in str(opts["gpu_context"])
    assert opts["keep_open"] == "yes"


def test_build_mpv_options_intel() -> None:
    """Intel uses same safe chain as AMD."""
    opts = build_mpv_options("intel")
    assert "d3d11va" in opts["hwdec"]
    assert "dxva2" in opts["hwdec"]
    assert "auto" in opts["hwdec"]
    assert opts["gpu_api"] == "d3d11,opengl"
    assert "d3d11" in str(opts["gpu_context"])
    assert opts["keep_open"] == "yes"


def test_build_mpv_options_auto() -> None:
    """Auto uses d3d11 context but lets mpv choose hwdec."""
    opts = build_mpv_options("auto")
    assert opts["hwdec"] == "auto"
    assert opts["gpu_api"] == "d3d11,opengl"
    assert "d3d11" in str(opts["gpu_context"])
    assert opts["keep_open"] == "yes"


def test_build_mpv_options_always_has_keep_open() -> None:
    """Every vendor must include ``keep_open='yes'`` for the preview widget."""
    for vendor in ("nv", "amd", "intel", "cpu", "auto"):
        opts = build_mpv_options(vendor)
        assert opts.get("keep_open") == "yes", f"{vendor}: keep_open missing"


def test_build_mpv_options_struct_can_be_unpacked() -> None:
    """Smoke test: the returned dict can be unpacked into mpv.MPV(...)."""
    for vendor in ("nv", "amd", "intel", "cpu", "auto"):
        opts = build_mpv_options(vendor)
        # Dummy call without real mpv — just verify no kwargs clash
        def dummy_mpv(**kwargs):  # type: ignore
            pass
        dummy_mpv(**opts)


# ── vendor_label ─────────────────────────────────────────────────────────

def test_vendor_label_known() -> None:
    assert vendor_label("nv") == "NVIDIA"
    assert vendor_label("amd") == "AMD"
    assert vendor_label("intel") == "Intel"
    assert vendor_label("cpu") == "CPU (software)"
    assert vendor_label("auto") == "Auto"


def test_vendor_label_unknown() -> None:
    assert vendor_label("foo") == "foo"
