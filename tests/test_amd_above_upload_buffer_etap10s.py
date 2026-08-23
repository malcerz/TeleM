"""ETAP 10S: AMD ABOVE upload buffer — from_buffer_copy reduction tests.

Targeted tests for the ``AMD_ABOVE_UPLOAD_BUFFER_MODE`` (COPY | DIRECT):
- mode parsing / unknown fallback,
- DIRECT pointer byte integrity (byte-for-byte, embedded NUL bytes, first/last),
- pointer lifetime stress (immutable PyBytes referenced during native call),
- COPY and DIRECT pointers expose identical content.

The real GPU parity (COPY vs DIRECT, 120 frames) is covered by the end-to-end
benchmark reported in Raporty/RAPORT_INDICATORS_ETAP_10S_AMD_UPLOAD_BUFFER.md.
"""

from __future__ import annotations

import ctypes
import gc

from src.ffmpeg.amd_native_exporter import (
    _ABOVE_UPLOAD_BUFFER_MODE_DEFAULT,
    _above_region_pointer,
    _resolve_above_upload_buffer_mode,
)


def test_default_mode_is_direct_after_gpu_parity_validated(monkeypatch) -> None:
    monkeypatch.delenv("AMD_ABOVE_UPLOAD_BUFFER_MODE", raising=False)
    # ETAP 10U validated DIRECT on the GPU (120-frame COPY vs DIRECT byte-identical
    # parity, runtime byte-integrity 120/120, region geometry parity, ghosting,
    # frame accounting, SCAN+DIRECT smoke), so the production default is DIRECT
    # (zero-copy); COPY remains the env-forced fallback.
    assert _ABOVE_UPLOAD_BUFFER_MODE_DEFAULT == "DIRECT"
    assert _resolve_above_upload_buffer_mode() == "DIRECT"


def test_copy_and_direct_modes_accepted(monkeypatch) -> None:
    monkeypatch.setenv("AMD_ABOVE_UPLOAD_BUFFER_MODE", "copy")
    assert _resolve_above_upload_buffer_mode() == "COPY"
    monkeypatch.setenv("AMD_ABOVE_UPLOAD_BUFFER_MODE", "Direct")
    assert _resolve_above_upload_buffer_mode() == "DIRECT"


def test_unknown_mode_falls_back_to_copy(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AMD_ABOVE_UPLOAD_BUFFER_MODE", "XYZ")
    assert _resolve_above_upload_buffer_mode() == "COPY"
    out = capsys.readouterr().out
    assert "unknown AMD_ABOVE_UPLOAD_BUFFER_MODE" in out


def test_direct_pointer_byte_integrity_with_embedded_zeros() -> None:
    # RGBA-like data with many 0x00 (zero-alpha pixels) and arbitrary RGB.
    pattern = bytes([0xAB, 0x00, 0xCD, 0xFF, 0x00, 0x00, 0x80, 0x7F, 0x00, 0x11])
    data = pattern * 300_000  # ~3 MB, embedded zeros throughout
    ptr = _above_region_pointer(data, "DIRECT")
    assert isinstance(ptr, ctypes.POINTER(ctypes.c_uint8))
    readback = ctypes.string_at(ptr, len(data))
    assert len(readback) == len(data)
    assert readback == data, "DIRECT pointer must expose byte-identical content"
    assert readback[:10] == pattern
    assert readback[-10:] == pattern


def test_copy_and_direct_pointers_identical_content() -> None:
    data = bytes(bytearray([0x00, 0x12, 0x34, 0xAB]) * 250_000)
    cp = _above_region_pointer(data, "COPY")
    dp = _above_region_pointer(data, "DIRECT")
    assert ctypes.string_at(cp, len(data)) == data
    assert ctypes.string_at(dp, len(data)) == data
    assert ctypes.string_at(cp, len(data)) == ctypes.string_at(dp, len(data))


def test_pointer_lifetime_stress_immutable_bytes() -> None:
    # Hold a strong reference to the bytes while the native-like call reads the
    # pointer (the loop-variable pattern used by the upload consumer).  GC must
    # not invalidate the buffer.
    for _ in range(2000):
        r_bytes = bytes(bytearray(4096))
        ptr = _above_region_pointer(r_bytes, "DIRECT")
        # "native call": read through the pointer while r_bytes is referenced
        assert len(ctypes.string_at(ptr, 4096)) == 4096
        # r_bytes goes out of scope after the iteration; GC stress
        if _ % 64 == 0:
            gc.collect()
    gc.collect()


def test_direct_pointer_points_into_bytes_payload() -> None:
    # The DIRECT pointer must point into the actual bytes buffer (zero-copy),
    # not a copy: mutating is impossible (immutable), so verify by checking the
    # pointer address is stable and content matches exactly for a large buffer.
    data = bytes(bytearray([0x00, 0xFF]) * 1_000_000)
    p1 = _above_region_pointer(data, "DIRECT")
    p2 = _above_region_pointer(data, "DIRECT")
    assert ctypes.addressof(p1.contents) == ctypes.addressof(p2.contents)
    assert ctypes.string_at(p1, len(data)) == data
