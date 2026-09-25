"""Capability policy tests independent of real GPU/driver state."""

from __future__ import annotations

import json

from src.ffmpeg import amd_capabilities as caps_mod
from src.ffmpeg import detection


def _caps(**overrides):
    data = dict(
        status="OK",
        vendor="AMD",
        adapter_name="AMD Radeon Test",
        vendor_id="0x1002",
        device_id="0x15e7",
        adapter_luid="0x0:0x1",
        driver_version="1.0.0",
        hardware_encoder="AMF",
        selected_codec="HEVC",
        hevc_encode_available=True,
        hevc_main10_available=True,
        max_encode_width=4096,
        max_encode_height=4096,
        hardware_decode_available=True,
        hevc_main10_decode_available=True,
        capability_source="AMFIOCaps",
    )
    data.update(overrides)
    return caps_mod.GpuCapabilities(**data)


def test_amd_capability_4096_gate(monkeypatch):
    monkeypatch.setattr(caps_mod, "get_gpu_capabilities", lambda: _caps())
    ok, _, limit = detection.is_resolution_supported_by_encoder("4k", "amd")
    blocked, message, blocked_limit = detection.is_resolution_supported_by_encoder("5.3k", "amd")
    assert ok is True
    assert limit == (4096, 4096)
    assert blocked is False
    assert blocked_limit == (4096, 4096)
    assert "4096x4096" in message


def test_amd_capability_8192_gate(monkeypatch):
    monkeypatch.setattr(
        caps_mod,
        "get_gpu_capabilities",
        lambda: _caps(max_encode_width=8192, max_encode_height=8192),
    )
    for resolution in ("5.3k", "8k"):
        ok, _, limit = detection.is_resolution_supported_by_encoder(resolution, "amd")
        assert ok is True
        assert limit == (8192, 8192)


def test_source_8k_encode_4k_allowed(monkeypatch):
    monkeypatch.setattr(caps_mod, "get_gpu_capabilities", lambda: _caps())
    ok, _, _ = detection.is_resolution_supported_by_encoder(
        "4k", "amd", source_dimensions=(7680, 4320)
    )
    assert ok is True


def test_source_8k_source_output_blocked_on_4096(monkeypatch):
    monkeypatch.setattr(caps_mod, "get_gpu_capabilities", lambda: _caps())
    ok, _, limit = detection.is_resolution_supported_by_encoder(
        "source", "amd", source_dimensions=(7680, 4320)
    )
    assert ok is False
    assert limit == (4096, 4096)


def test_source_4k_source_output_allowed_on_4096(monkeypatch):
    monkeypatch.setattr(caps_mod, "get_gpu_capabilities", lambda: _caps())
    ok, _, _ = detection.is_resolution_supported_by_encoder(
        "source", "amd", source_dimensions=(3840, 2160)
    )
    assert ok is True


def test_unknown_capability_no_vendor_hardcode(monkeypatch):
    unknown = _caps(
        status="UNKNOWN",
        hevc_encode_available=None,
        max_encode_width=None,
        max_encode_height=None,
    )
    monkeypatch.setattr(caps_mod, "get_gpu_capabilities", lambda: unknown)
    monkeypatch.setattr(caps_mod, "probe_amd_encode_resolution", lambda *args, **kwargs: False)
    ok, message, limit = detection.is_resolution_supported_by_encoder("8k", "amd")
    assert ok is False
    assert limit is None
    assert "UNKNOWN" in message
    assert "4096" not in message


def test_capability_cache_hit_and_driver_invalidation(tmp_path, monkeypatch):
    cache_path = tmp_path / "gpu_capabilities.json"
    monkeypatch.setattr(caps_mod, "get_capabilities_cache_path", lambda: cache_path)
    caps_mod.reset_capabilities_cache()
    calls = []
    current_driver = ["1.0.0"]

    def fake_query(*, identity_only=False):
        calls.append(identity_only)
        payload = _caps(driver_version=current_driver[0]).to_dict()
        if identity_only:
            return {
                "status": "OK",
                "vendor": "AMD",
                "adapter_name": "AMD Radeon Test",
                "vendor_id": "0x1002",
                "device_id": "0x15e7",
                "adapter_luid": "0x0:0x1",
                "driver_version": current_driver[0],
                "schema_version": caps_mod.SCHEMA_VERSION,
            }
        return payload

    monkeypatch.setattr(caps_mod, "query_native_amf_capabilities", fake_query)
    first = caps_mod.get_gpu_capabilities(force_refresh=True)
    assert first.cache_hit is False
    assert cache_path.exists()

    caps_mod.reset_capabilities_cache()
    second = caps_mod.get_gpu_capabilities()
    assert second.cache_hit is True
    assert calls[-1] is True

    current_driver[0] = "2.0.0"
    caps_mod.reset_capabilities_cache()
    third = caps_mod.get_gpu_capabilities()
    assert third.cache_hit is False
    assert calls[-1] is False


def test_render_preflight_blocks_unsupported_resolution(monkeypatch):
    monkeypatch.setattr(caps_mod, "get_gpu_capabilities", lambda: _caps())
    ok, message, _ = caps_mod.check_amd_encode_resolution(7680, 4320)
    assert ok is False
    assert "4096x4096" in message


def test_no_cpu_x265_auto_fallback(monkeypatch):
    monkeypatch.setattr(caps_mod, "get_gpu_capabilities", lambda: _caps())
    ok, message, _ = detection.is_resolution_supported_by_encoder("8k", "amd")
    assert ok is False
    assert "automatycznego CPU x265" in message
