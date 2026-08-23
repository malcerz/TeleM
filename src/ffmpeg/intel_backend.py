"""Isolated Intel GPU backend for TeleM — ETAP 1 (INTEL_FORCE).

This is NEW, isolated code.  It does NOT modify, refactor or re-dispatch the
existing AMD, NVIDIA or CPU backends.  Its purpose is to prepare a safe Intel
foundation:

- DXGI/D3D11 adapter enumeration with Vendor IDs (index-independent).
- ``INTEL_FORCE`` semantics: ``requested_backend == intel`` means "use ONLY
  the Intel adapter (vendor 0x8086)".
- Controlled failure when no usable Intel GPU/QSV exists.  Cross-GPU fallback
  (NVIDIA / AMD / CUDA / NVENC / AMF) and silent CPU fallback are DISABLED.
- QSV probing that separates "FFmpeg contains a QSV encoder" from "usable
  Intel hardware exists".
- Diagnostics contract described in the ETAP 1 task.

Vendor IDs (diagnostic only; AMD/NVIDIA backend implementations are untouched):
    Intel   0x8086
    AMD     0x1002
    NVIDIA  0x10DE
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import POINTER, WINFUNCTYPE, byref, c_char_p, c_size_t, c_uint, c_ulong, c_ulonglong, c_void_p, c_wchar
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── Backend / vendor identity (adapted to the existing string-code system) ──
BACKEND_AUTO = "auto"
BACKEND_CPU = "cpu"
BACKEND_NVIDIA = "nv"
BACKEND_AMD = "amd"
BACKEND_INTEL = "intel"
BACKEND_CODES = (BACKEND_AUTO, BACKEND_CPU, BACKEND_NVIDIA, BACKEND_AMD, BACKEND_INTEL)

VENDOR_ID_INTEL = 0x8086
VENDOR_ID_AMD = 0x1002
VENDOR_ID_NVIDIA = 0x10DE

VENDOR_CODES: dict[int, str] = {
    VENDOR_ID_INTEL: BACKEND_INTEL,
    VENDOR_ID_AMD: BACKEND_AMD,
    VENDOR_ID_NVIDIA: BACKEND_NVIDIA,
}

# IDXGIFactory1 IID: {770aae78-f26f-4dba-a829-253c83d1b387}
_IDXGIFACTORY1_IID = (
    ctypes.c_ulong(0x770aae78).value,
    ctypes.c_ushort(0xf26f).value,
    ctypes.c_ushort(0x4dba).value,
    (0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87),
)

try:
    _COM_FUNC = ctypes.WINFUNCTYPE
except AttributeError:  # pragma: no cover - non-Windows fallback
    _COM_FUNC = ctypes.CFUNCTYPE

_HRESULT = ctypes.c_long
_ULONG = ctypes.c_ulong
_UINT = ctypes.c_uint


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _factory1_guid() -> _GUID:
    d1, d2, d3, d4 = _IDXGIFACTORY1_IID
    g = _GUID()
    g.Data1 = d1
    g.Data2 = d2
    g.Data3 = d3
    g.Data4 = (ctypes.c_ubyte * 8)(*d4)
    return g


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    """Mirror of the native DXGI_ADAPTER_DESC1 (64-bit layout)."""

    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", ctypes.c_uint),
        ("DeviceId", ctypes.c_uint),
        ("SubSysId", ctypes.c_uint),
        ("Revision", ctypes.c_uint),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", ctypes.c_ulonglong),
        ("Flags", ctypes.c_uint),
    ]


def _default_log(msg: str) -> None:
    print(msg, flush=True)


def _release_com(ptr: Any) -> None:
    """Release an IUnknown COM pointer (vtable slot 2)."""
    if not ptr or not getattr(ptr, "value", None):
        return
    try:
        obj = ptr.value
        vtbl_ptr = ctypes.cast(obj, POINTER(c_void_p))[0]
        vtbl = ctypes.cast(vtbl_ptr, POINTER(c_void_p))
        release = _COM_FUNC(_ULONG, c_void_p)(vtbl[2])
        release(obj)
    except Exception:
        pass


def _create_dxgi_factory1() -> Optional[c_void_p]:
    """Create an IDXGIFactory1* via dxgi.dll, or None on failure."""
    if os.name != "nt":
        return None
    try:
        dxgi = ctypes.WinDLL("dxgi.dll")
        create = dxgi.CreateDXGIFactory1
        create.argtypes = [POINTER(_GUID), POINTER(c_void_p)]
        create.restype = _HRESULT
        factory = c_void_p()
        hr = create(byref(_factory1_guid()), byref(factory))
        if hr < 0 or not factory.value:
            return None
        return factory
    except Exception:
        return None


def _create_d3d11_device_on_adapter(adapter_obj: int) -> bool:
    """Best-effort D3D11CreateDevice on a specific DXGI adapter object.

    ``D3D_DRIVER_TYPE_UNKNOWN`` (0) with a non-NULL pAdapter forces device
    creation on exactly that adapter.  Reports OK/FAILED for diagnostics.
    """
    if os.name != "nt":
        return False
    try:
        d3d11 = ctypes.WinDLL("d3d11.dll")
        create = d3d11.D3D11CreateDevice
        create.argtypes = [
            c_void_p,          # pAdapter
            c_uint,            # DriverType
            c_void_p,          # Software
            c_uint,            # Flags (0x8 = VIDEO_SUPPORT)
            c_void_p,          # pFeatureLevels
            c_uint,            # FeatureLevels
            c_uint,            # SDKVersion
            POINTER(c_void_p),  # ppDevice
            POINTER(c_uint),   # pFeatureLevel
            POINTER(c_void_p),  # ppImmediateContext
        ]
        create.restype = _HRESULT
        p_device = c_void_p()
        p_ctx = c_void_p()
        feature_level = c_uint()
        hr = create(
            adapter_obj, 0, None, 0x8, None, 0, 7,
            byref(p_device), byref(feature_level), byref(p_ctx),
        )
        if hr < 0:
            return False
        # Release the device and immediate context.
        _release_com(p_device)
        _release_com(p_ctx)
        return True
    except Exception:
        return False


def enumerate_d3d11_adapters() -> list[dict[str, Any]]:
    """Enumerate D3D11 adapters via DXGI 1.1 (IDXGIFactory1::EnumAdapters1).

    Returns a list of dicts::

        {index, name, vendor_id, device_id, vendor_code,
         dedicated_vram_mb, d3d11_device_ok}

    Empty list on non-Windows or when DXGI is unavailable.  Every COM pointer
    is released; no assumption is made about ``adapter 0`` being any vendor.
    """
    if os.name != "nt":
        return []

    factory = _create_dxgi_factory1()
    if factory is None:
        return []

    adapters: list[dict[str, Any]] = []
    try:
        fobj = factory.value
        vtbl_ptr = ctypes.cast(fobj, POINTER(c_void_p))[0]
        vtbl = ctypes.cast(vtbl_ptr, POINTER(c_void_p))
        # IDXGIFactory1::EnumAdapters1 is vtable slot 12.
        enum_adapters1 = _COM_FUNC(_HRESULT, c_void_p, _UINT, POINTER(c_void_p))(vtbl[12])

        index = 0
        while True:
            p_adapter = c_void_p()
            hr = enum_adapters1(fobj, index, byref(p_adapter))
            if hr != 0 or not p_adapter.value:  # DXGI_ERROR_NOT_FOUND / end
                break
            try:
                aobj = p_adapter.value
                avtbl_ptr = ctypes.cast(aobj, POINTER(c_void_p))[0]
                avtbl = ctypes.cast(avtbl_ptr, POINTER(c_void_p))
                # IDXGIAdapter1::GetDesc1 is vtable slot 10.
                get_desc1 = _COM_FUNC(_HRESULT, c_void_p, POINTER(DXGI_ADAPTER_DESC1))(avtbl[10])
                desc = DXGI_ADAPTER_DESC1()
                hr2 = get_desc1(aobj, byref(desc))
                if hr2 != 0:
                    index += 1
                    continue
                name = desc.Description.rstrip("\x00")
                vendor_id = int(desc.VendorId)
                adapters.append({
                    "index": index,
                    "name": name,
                    "vendor_id": vendor_id,
                    "device_id": int(desc.DeviceId),
                    "vendor_code": VENDOR_CODES.get(vendor_id, "unknown"),
                    "dedicated_vram_mb": int(desc.DedicatedVideoMemory // (1024 * 1024)),
                    "d3d11_device_ok": _create_d3d11_device_on_adapter(aobj),
                })
            finally:
                _release_com(p_adapter)
            index += 1
    except Exception:
        # Enumeration failure must never crash the pipeline; INTEL_FORCE will
        # report "Intel adapter: NOT FOUND" and fail in a controlled way.
        pass
    finally:
        _release_com(factory)
    return adapters


def find_intel_adapter(adapters: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return the first adapter whose Vendor ID is Intel (0x8086), or None.

    Selection is based on the adapter Vendor ID, NOT on the adapter index.
    """
    for ad in adapters:
        if int(ad.get("vendor_id", 0)) == VENDOR_ID_INTEL:
            return ad
    return None


def vendor_label(vendor_id: int) -> str:
    """Human-readable vendor label for diagnostics."""
    code = VENDOR_CODES.get(vendor_id)
    if code == BACKEND_INTEL:
        return "Intel"
    if code == BACKEND_AMD:
        return "AMD"
    if code == BACKEND_NVIDIA:
        return "NVIDIA"
    return "UNKNOWN"


# ── QSV probing ───────────────────────────────────────────────────────────

def _nt_startupinfo() -> Any:
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def ffmpeg_encoders_have_qsv(ffmpeg_exe: str = "ffmpeg") -> dict[str, bool]:
    """Check whether the FFmpeg binary itself contains QSV encoders.

    Returns ``{ffmpeg_has_qsv, hevc_qsv, h264_qsv}``.  This answers "FFmpeg
    contains a QSV encoder" and is deliberately separate from "usable Intel
    hardware exists" (see :func:`qsv_hardware_usable`).
    """
    result = {"ffmpeg_has_qsv": False, "hevc_qsv": False, "h264_qsv": False}
    try:
        r = subprocess.run(
            [ffmpeg_exe, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        if r.returncode == 0:
            enc = r.stdout
            result["hevc_qsv"] = "hevc_qsv" in enc
            result["h264_qsv"] = "h264_qsv" in enc
            result["ffmpeg_has_qsv"] = result["hevc_qsv"] or result["h264_qsv"]
    except Exception:
        pass
    return result


def qsv_hardware_usable(ffmpeg_exe: str = "ffmpeg") -> bool:
    """Test whether a QSV encode actually works on this hardware.

    Runs a real short encode via the existing ``_test_encoder``.  This is the
    "usable Intel hardware exists" signal and is separate from merely having
    the encoder compiled into FFmpeg.
    """
    from src.ffmpeg.detection import _test_encoder
    if _test_encoder("hevc_qsv", ffmpeg_exe):
        return True
    return _test_encoder("h264_qsv", ffmpeg_exe)


# ── INTEL_FORCE resolution ───────────────────────────────────────────────

@dataclass
class IntelResolution:
    """Result of a successful INTEL_FORCE resolution."""

    requested_backend: str = BACKEND_INTEL
    adapter_found: bool = False
    adapter_name: str = ""
    vendor_id: int = 0
    d3d11_device_ok: bool = False
    ffmpeg_has_qsv: bool = False
    hevc_qsv: bool = False
    h264_qsv: bool = False
    qsv_available: bool = False
    # Planned pipeline (ETAP 2 wiring; not force-enabled in ETAP 1).
    decode_path: str = "QSV/D3D11VA"
    render_path: str = "D3D11"
    encode_path: str = "QSV"
    adapters: list[dict[str, Any]] = field(default_factory=list)


class IntelBackendError(RuntimeError):
    """Controlled INTEL_FORCE failure — no cross-GPU fallback.

    Raised when Intel is explicitly requested but no usable Intel GPU/QSV
    device is available.  TeleM must NOT silently fall back to NVIDIA, AMD,
    CUDA, NVENC, AMF or CPU in this case.
    """


def resolve_intel_force(
    ffmpeg_exe: str = "ffmpeg",
    log: Optional[Callable[[str], None]] = None,
    adapters: Optional[list[dict[str, Any]]] = None,
    qsv_hw_usable: Optional[bool] = None,
    ffmpeg_qsv_info: Optional[dict[str, bool]] = None,
) -> IntelResolution:
    """Resolve INTEL_FORCE.

    Enumerates D3D11 adapters, selects the Intel adapter by Vendor ID 0x8086
    (index-independent), verifies D3D11 device creation on it, probes QSV
    (separating FFmpeg-encoder presence from usable hardware), and emits the
    ETAP 1 diagnostics contract.

    On any failure raises :class:`IntelBackendError`; cross-GPU fallback is
    intentionally disabled.

    *adapters*, *qsv_hw_usable* and *ffmpeg_qsv_info* are injectable so the
    resolution is unit-testable without real Intel hardware or FFmpeg.
    """
    log = log or _default_log
    res = IntelResolution()

    log("[GPU] Requested backend: INTEL_FORCE")
    adapter_list = adapters if adapters is not None else enumerate_d3d11_adapters()
    res.adapters = list(adapter_list)

    log("[GPU] D3D11 adapters discovered:")
    if not adapter_list:
        log("[GPU]   (none)")
    for ad in adapter_list:
        log(f"[GPU] {ad['index']}: {ad['name']}")
        log(f"[GPU]    vendor=0x{int(ad['vendor_id']):04X}")

    intel = find_intel_adapter(adapter_list)
    if intel is None:
        log("[INTEL] Intel adapter: NOT FOUND")
        log("[INTEL] INTEL_FORCE_FAILED")
        log("[INTEL] No usable Intel GPU/QSV device available.")
        log("[INTEL] Cross-GPU fallback: DISABLED")
        raise IntelBackendError(
            "INTEL_FORCE_FAILED: No usable Intel GPU/QSV device available. "
            "Automatic cross-GPU fallback disabled."
        )

    res.adapter_found = True
    res.adapter_name = str(intel.get("name", ""))
    res.vendor_id = int(intel.get("vendor_id", 0))
    res.d3d11_device_ok = bool(intel.get("d3d11_device_ok", False))
    log(f"[INTEL] Selected adapter: {res.adapter_name}")
    log(f"[INTEL] Vendor ID: 0x{res.vendor_id:04X}")

    # Foreign adapters are ignored, never selected, under INTEL_FORCE.
    for ad in adapter_list:
        vid = int(ad.get("vendor_id", 0))
        if vid != VENDOR_ID_INTEL:
            log(f"[{vendor_label(vid).upper()}] Adapter ignored: INTEL_FORCE active")

    # QSV probing: separate FFmpeg-encoder presence from usable hardware.
    if ffmpeg_qsv_info is None:
        ffmpeg_qsv_info = ffmpeg_encoders_have_qsv(ffmpeg_exe)
    res.ffmpeg_has_qsv = bool(ffmpeg_qsv_info.get("ffmpeg_has_qsv", False))
    res.hevc_qsv = bool(ffmpeg_qsv_info.get("hevc_qsv", False))
    res.h264_qsv = bool(ffmpeg_qsv_info.get("h264_qsv", False))

    if qsv_hw_usable is None:
        qsv_hw_usable = qsv_hardware_usable(ffmpeg_exe)
    res.qsv_available = bool(qsv_hw_usable)

    log(f"[INTEL] INTEL_QSV_AVAILABLE: {'YES' if res.qsv_available else 'NO'}")
    log(f"[INTEL] INTEL_H264_QSV: {'YES' if res.h264_qsv else 'NO'}")
    log(f"[INTEL] INTEL_HEVC_QSV: {'YES' if res.hevc_qsv else 'NO'}")
    log(f"[INTEL] INTEL_D3D11_DEVICE: {'OK' if res.d3d11_device_ok else 'FAILED'}")

    res.decode_path = "QSV/D3D11VA"
    res.render_path = "D3D11"
    # INTEL_ENCODE_PATH reflects the *usable* encode path, not merely the
    # encoder's presence in FFmpeg.  When QSV is not usable on this hardware,
    # the encode path is reported as NONE (the controlled-failure state).
    if res.qsv_available:
        if res.hevc_qsv:
            res.encode_path = "QSV-HEVC"
        elif res.h264_qsv:
            res.encode_path = "QSV-H264"
        else:
            res.encode_path = "QSV"
    else:
        res.encode_path = "NONE"
    log(f"[INTEL] INTEL_DECODE_PATH: {res.decode_path}")
    log(f"[INTEL] INTEL_RENDER_PATH: {res.render_path}")
    log(f"[INTEL] INTEL_ENCODE_PATH: {res.encode_path}")
    log("[INTEL] INTEL_CROSS_GPU_FALLBACK: DISABLED")

    if not res.qsv_available:
        log("[INTEL] INTEL_FORCE_FAILED")
        if res.ffmpeg_has_qsv:
            log("[INTEL] QSV encoder present in FFmpeg but no usable Intel hardware.")
        else:
            log("[INTEL] FFmpeg does not expose a usable QSV encoder.")
        log("[INTEL] Cross-GPU fallback: DISABLED")
        raise IntelBackendError(
            "INTEL_FORCE_FAILED: QSV encode is not usable on the selected Intel "
            "adapter. Automatic cross-GPU fallback disabled."
        )

    return res


def normalize_backend(code: str) -> str:
    """Normalize a backend code to the existing lowercase set.

    Accepts ``auto``/``cpu``/``nv``/``amd``/``intel`` (and common aliases such
    as ``nvidia``/``nvenc``, ``amf``, ``qsv``, ``force``).  Unknown values are
    returned lowercased unchanged.
    """
    c = (code or "").strip().lower()
    aliases = {
        "nvidia": BACKEND_NVIDIA,
        "nvenc": BACKEND_NVIDIA,
        "cuda": BACKEND_NVIDIA,
        "amf": BACKEND_AMD,
        "radeon": BACKEND_AMD,
        "qsv": BACKEND_INTEL,
        "intel_force": BACKEND_INTEL,
        "force": BACKEND_INTEL,
        "software": BACKEND_CPU,
    }
    return aliases.get(c, c)
