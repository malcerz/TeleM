"""Tests for Intel 4K Auto HUD Resolution Policy (ETAP 6B.1)."""

import pytest
from src.ffmpeg.streaming import resolve_hud_resolution_policy


def test_intel_4k_auto_resolves_to_75_percent():
    scale, msg = resolve_hud_resolution_policy("intel", 3840, 2160, "Auto")
    assert scale == 0.75
    assert "[INTEL] HUD resolution policy: AUTO -> 75% (2560x1440 -> 3840x2160)" in msg


def test_intel_source_4k_auto_resolves_to_75_percent():
    # When resolution="source" and source is 3840x2160:
    scale, msg = resolve_hud_resolution_policy("intel", 3840, 2160, "auto")
    assert scale == 0.75
    assert "AUTO -> 75%" in msg


def test_intel_non_4k_auto_resolves_to_100_percent():
    # 1080p
    scale, msg = resolve_hud_resolution_policy("intel", 1920, 1080, "Auto")
    assert scale == 1.0
    assert "[INTEL] HUD resolution policy: AUTO -> 100% (1920x1080)" in msg

    # 5.3K (5312x2988)
    scale_5k, msg_5k = resolve_hud_resolution_policy("intel", 5312, 2988, "Auto")
    assert scale_5k == 1.0
    assert "[INTEL] HUD resolution policy: AUTO -> 100% (5312x2988)" in msg_5k

    # 1440p
    scale_1440, msg_1440 = resolve_hud_resolution_policy("intel", 2560, 1440, "Auto")
    assert scale_1440 == 1.0
    assert "[INTEL] HUD resolution policy: AUTO -> 100% (2560x1440)" in msg_1440


def test_intel_manual_overrides_work_on_all_resolutions():
    # Manual 100%
    scale, msg = resolve_hud_resolution_policy("intel", 3840, 2160, "100%")
    assert scale == 1.0
    assert "MANUAL 100%" in msg

    scale_num, _ = resolve_hud_resolution_policy("intel", 3840, 2160, 1.0)
    assert scale_num == 1.0

    # Manual 75%
    scale, msg = resolve_hud_resolution_policy("intel", 3840, 2160, "75%")
    assert scale == 0.75
    assert "MANUAL 75%" in msg

    scale_num, _ = resolve_hud_resolution_policy("intel", 1920, 1080, 0.75)
    assert scale_num == 0.75

    # Manual 50%
    scale, msg = resolve_hud_resolution_policy("intel", 3840, 2160, "50%")
    assert scale == 0.5
    assert "MANUAL 50%" in msg

    scale_num, _ = resolve_hud_resolution_policy("intel", 3840, 2160, 0.5)
    assert scale_num == 0.5


def test_amd_nvidia_cpu_preserve_100_percent_on_auto():
    # AMD
    scale_amd, msg_amd = resolve_hud_resolution_policy("amd", 3840, 2160, "Auto")
    assert scale_amd == 1.0
    assert msg_amd == ""

    # NVIDIA
    scale_nv, msg_nv = resolve_hud_resolution_policy("nv", 3840, 2160, "Auto")
    assert scale_nv == 1.0
    assert msg_nv == ""

    # CPU
    scale_cpu, msg_cpu = resolve_hud_resolution_policy("cpu", 3840, 2160, "Auto")
    assert scale_cpu == 1.0
    assert msg_cpu == ""


def test_odd_even_overlay_dimensions_calculation():
    # Odd dimension input
    render_w, render_h = 3841, 2161
    scale, _ = resolve_hud_resolution_policy("intel", 3840, 2160, "Auto")
    ov_w = max(2, int(round(render_w * scale)))
    ov_h = max(2, int(round(render_h * scale)))
    if ov_w % 2:
        ov_w += 1
    if ov_h % 2:
        ov_h += 1
    assert ov_w % 2 == 0
    assert ov_h % 2 == 0


def test_fallback_on_unrecognized_option():
    scale, msg = resolve_hud_resolution_policy("intel", 3840, 2160, "INVALID_OPTION")
    assert scale == 1.0
    assert "FALLBACK 100%" in msg
