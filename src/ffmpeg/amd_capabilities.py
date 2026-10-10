"""Runtime GPU capability model, AMF probe, and validated persistent cache.

The service deliberately separates source/decode capability from encode
capability.  In particular, an AMD adapter may decode an 8K source while its
AMF HEVC encoder is limited to 4096x4096; that is a valid 8K-input/4K-output
configuration and must not be rejected at file-open time.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping


SCHEMA_VERSION = 2
AMD_VENDOR_ID = "0x1002"


def _nt_startupinfo() -> Any:
    if os.name != "nt":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "pass", "available"}:
        return True
    if text in {"0", "false", "no", "off", "fail", "unavailable"}:
        return False
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class GpuCapabilities:
    """Backend-neutral capability snapshot for the active adapter."""

    status: str = "UNKNOWN"
    vendor: str = "UNKNOWN"
    adapter_name: str = "Unknown"
    vendor_id: str = "0x0000"
    device_id: str = "0x0000"
    adapter_luid: str = "0x0:0x0"
    driver_version: str = "Unknown"
    hardware_encoder: str | None = None
    selected_codec: str | None = None
    h264_encode_available: bool | None = None
    h264_8bit_available: bool | None = None
    hevc_encode_available: bool | None = None
    hevc_main10_available: bool | None = None
    av1_encode_available: bool | None = None
    av1_8bit_available: bool | None = None
    av1_10bit_available: bool | None = None
    max_encode_width: int | None = None
    max_encode_height: int | None = None
    hardware_decode_available: bool | None = None
    hevc_main10_decode_available: bool | None = None
    capability_source: str = "NONE"
    probe_timestamp: str = ""
    schema_version: int = SCHEMA_VERSION
    cache_hit: bool = False
    probe_cold_ms: float | None = None
    cache_warm_ms: float | None = None
    error: str | None = None

    @property
    def is_amd(self) -> bool:
        return self.vendor_id.lower() == AMD_VENDOR_ID

    def supports_encode(self, width: int, height: int) -> bool | None:
        """Return True/False when known, otherwise None for UNKNOWN."""
        if self.hevc_encode_available is False:
            return False
        if self.max_encode_width is None or self.max_encode_height is None:
            return None
        return int(width) <= self.max_encode_width and int(height) <= self.max_encode_height

    def cache_identity(self) -> dict[str, str | int]:
        return {
            "schema_version": self.schema_version,
            "adapter_luid": self.adapter_luid,
            "vendor_id": self.vendor_id,
            "device_id": self.device_id,
            "driver_version": self.driver_version,
        }

    def to_dict(self) -> dict[str, Any]:
        data = {
            "status": self.status,
            "vendor": self.vendor,
            "adapter_name": self.adapter_name,
            "vendor_id": self.vendor_id,
            "device_id": self.device_id,
            "adapter_luid": self.adapter_luid,
            "driver_version": self.driver_version,
            "hardware_encoder": self.hardware_encoder,
            "selected_codec": self.selected_codec,
            "h264_encode_available": self.h264_encode_available,
            "h264_8bit_available": self.h264_8bit_available,
            "hevc_encode_available": self.hevc_encode_available,
            "hevc_main10_available": self.hevc_main10_available,
            "av1_encode_available": self.av1_encode_available,
            "av1_8bit_available": self.av1_8bit_available,
            "av1_10bit_available": self.av1_10bit_available,
            "max_encode_width": self.max_encode_width,
            "max_encode_height": self.max_encode_height,
            "hardware_decode_available": self.hardware_decode_available,
            "hevc_main10_decode_available": self.hevc_main10_decode_available,
            "capability_source": self.capability_source,
            "probe_timestamp": self.probe_timestamp,
            "schema_version": self.schema_version,
            "cache_hit": self.cache_hit,
            "probe_cold_ms": self.probe_cold_ms,
            "cache_warm_ms": self.cache_warm_ms,
            "error": self.error,
        }
        # Compatibility aliases used by the existing GUI/detection callers.
        data.update(
            gpu_name=self.adapter_name,
            gpu_vendor=self.vendor_id,
            gpu_device_id=self.device_id,
            hevc_max_width=self.max_encode_width,
            hevc_max_height=self.max_encode_height,
        )
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GpuCapabilities":
        return cls(
            status=str(data.get("status", "UNKNOWN")),
            vendor=str(data.get("vendor", "UNKNOWN")),
            adapter_name=str(data.get("adapter_name", data.get("gpu_name", "Unknown"))),
            vendor_id=str(data.get("vendor_id", data.get("gpu_vendor", "0x0000"))),
            device_id=str(data.get("device_id", data.get("gpu_device_id", "0x0000"))),
            adapter_luid=str(data.get("adapter_luid", "0x0:0x0")),
            driver_version=str(data.get("driver_version", "Unknown")),
            hardware_encoder=data.get("hardware_encoder"),
            selected_codec=data.get("selected_codec"),
            h264_encode_available=_as_bool(data.get("h264_encode_available")),
            h264_8bit_available=_as_bool(data.get("h264_8bit_available")),
            hevc_encode_available=_as_bool(data.get("hevc_encode_available")),
            hevc_main10_available=_as_bool(data.get("hevc_main10_available")),
            av1_encode_available=_as_bool(data.get("av1_encode_available")),
            av1_8bit_available=_as_bool(data.get("av1_8bit_available")),
            av1_10bit_available=_as_bool(data.get("av1_10bit_available")),
            max_encode_width=_as_int(data.get("max_encode_width", data.get("hevc_max_width"))),
            max_encode_height=_as_int(data.get("max_encode_height", data.get("hevc_max_height"))),
            hardware_decode_available=_as_bool(data.get("hardware_decode_available")),
            hevc_main10_decode_available=_as_bool(data.get("hevc_main10_decode_available")),
            capability_source=str(data.get("capability_source", "NONE")),
            probe_timestamp=str(data.get("probe_timestamp", "")),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            cache_hit=bool(data.get("cache_hit", False)),
            probe_cold_ms=data.get("probe_cold_ms"),
            cache_warm_ms=data.get("cache_warm_ms"),
            error=data.get("error"),
        )


def get_capabilities_cache_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base_dir = Path(local_app_data) / "SportCamHUD" if local_app_data else Path.home() / ".bikeridehud"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "gpu_capabilities.json"


def _query_binary() -> Path | None:
    repo_root = Path(__file__).resolve().parents[2]
    candidates = (
        repo_root / "native" / "d3d11_amf_pipeline" / "bin" / "query_amf_caps.exe",
        repo_root / "scratch" / "query_amf_caps.exe",
    )
    return next((p for p in candidates if p.exists()), None)


def _parse_probe_output(stdout: str, *, identity_only: bool = False) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw[key.strip()] = value.strip()

    vendor_id = str(raw.get("GPU_VENDOR", "0x0000")).lower()
    if not vendor_id.startswith("0x"):
        vendor_id = f"0x{vendor_id}"
    device_id = str(raw.get("GPU_DEVICE_ID", "0x0000")).lower()
    if not device_id.startswith("0x"):
        device_id = f"0x{device_id}"
    vendor = {
        AMD_VENDOR_ID: "AMD",
        "0x10de": "NVIDIA",
        "0x8086": "Intel",
    }.get(vendor_id, "UNKNOWN")
    max_w = _as_int(raw.get("AMF_MAX_WIDTH", raw.get("HEVC_MAX_WIDTH")))
    max_h = _as_int(raw.get("AMF_MAX_HEIGHT", raw.get("HEVC_MAX_HEIGHT")))
    is_amd = vendor_id == AMD_VENDOR_ID
    amf_hevc_available = _as_bool(raw.get("AMF_HEVC_AVAILABLE"))
    has_encoder_result = (
        amf_hevc_available
        if amf_hevc_available is not None
        else max_w is not None and max_h is not None and max_w > 0 and max_h > 0
    )
    if has_encoder_result and not (max_w and max_h):
        has_encoder_result = False
    hevc_main10 = _as_bool(raw.get("AMF_HEVC_MAIN10_AVAILABLE"))
    if hevc_main10 is None:
        hevc_main10 = _as_bool(raw.get("HEVC_MAIN10_AVAILABLE"))
    identity_probe_ok = bool(raw.get("GPU_VENDOR"))
    return {
        "status": "OK" if (
            identity_probe_ok if identity_only else (has_encoder_result if is_amd else identity_probe_ok)
        ) else "UNKNOWN",
        "vendor": vendor,
        "adapter_name": raw.get("GPU_NAME", "Unknown"),
        "vendor_id": vendor_id,
        "device_id": device_id,
        "adapter_luid": raw.get("ADAPTER_LUID", "0x0:0x0"),
        "driver_version": raw.get("DRIVER_VERSION", "Unknown"),
        "hardware_encoder": "AMF" if has_encoder_result and is_amd else None,
        "selected_codec": "HEVC" if has_encoder_result and is_amd else None,
        "hevc_encode_available": has_encoder_result if is_amd else None,
        "hevc_main10_available": hevc_main10,
        "max_encode_width": max_w if is_amd else None,
        "max_encode_height": max_h if is_amd else None,
        "hardware_decode_available": _as_bool(raw.get("D3D11_HARDWARE_DECODE_AVAILABLE")),
        "hevc_main10_decode_available": _as_bool(raw.get("D3D11_HEVC_MAIN10_DECODE_AVAILABLE")),
        "capability_source": "DXGIIdentity" if identity_only else raw.get("CAPABILITY_SOURCE", "AMFIOCaps"),
        "probe_timestamp": _now_iso(),
        "schema_version": SCHEMA_VERSION,
    }


def _get_matching_driver_version(device_id_hex: str) -> str:
    clean_dev = device_id_hex.lower().replace("0x", "")
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        )
        for i in range(winreg.QueryInfoKey(key)[0]):
            sub_name = winreg.EnumKey(key, i)
            if sub_name.isdigit():
                sub = winreg.OpenKey(key, sub_name)
                try:
                    pnp, _ = winreg.QueryValueEx(sub, "MatchingDeviceId")
                    if clean_dev in str(pnp).lower():
                        ver, _ = winreg.QueryValueEx(sub, "DriverVersion")
                        return str(ver)
                except OSError:
                    pass
    except Exception:
        pass
    return "Unknown"


def _probe_dxgi_identity() -> dict[str, Any] | None:
    """Direct DXGI hardware probe via D3D11 without requiring external exe."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DXGI_ADAPTER_DESC1(ctypes.Structure):
            _fields_ = [
                ("Description", wintypes.WCHAR * 128),
                ("VendorId", wintypes.UINT),
                ("DeviceId", wintypes.UINT),
                ("SubSysId", wintypes.UINT),
                ("Revision", wintypes.UINT),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid_LowPart", wintypes.DWORD),
                ("AdapterLuid_HighPart", wintypes.LONG),
                ("Flags", wintypes.UINT),
            ]

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        d3d11 = ctypes.windll.d3d11
        pDevice = ctypes.c_void_p()
        pContext = ctypes.c_void_p()
        lvl = ctypes.c_uint()
        hr = d3d11.D3D11CreateDevice(
            None, 1, None, 0, None, 0, 7,
            ctypes.byref(pDevice), ctypes.byref(lvl), ctypes.byref(pContext)
        )
        if hr != 0 or not pDevice.value:
            return None

        iid_dxgi_dev = GUID(0x54ec77fa, 0x1377, 0x44e6, (ctypes.c_ubyte*8)(0x8c, 0x32, 0x88, 0xfd, 0x5f, 0x44, 0xc8, 0x4c))
        vtable = ctypes.cast(ctypes.cast(pDevice, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
        QI = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(vtable[0])
        pDXGIDevice = ctypes.c_void_p()
        QI(pDevice, ctypes.byref(iid_dxgi_dev), ctypes.byref(pDXGIDevice))

        dxgi_vtable = ctypes.cast(ctypes.cast(pDXGIDevice, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
        GetAdapter = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(dxgi_vtable[7])
        pAdapter = ctypes.c_void_p()
        GetAdapter(pDXGIDevice, ctypes.byref(pAdapter))

        iid_adapter1 = GUID(0x29038f61, 0x3839, 0x4626, (ctypes.c_ubyte*8)(0x91, 0xfd, 0x08, 0x68, 0x79, 0x01, 0x1a, 0x05))
        pAdapter1 = ctypes.c_void_p()
        adapter_vtable = ctypes.cast(ctypes.cast(pAdapter, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
        AdapterQI = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(adapter_vtable[0])
        AdapterQI(pAdapter, ctypes.byref(iid_adapter1), ctypes.byref(pAdapter1))

        adapter1_vtable = ctypes.cast(ctypes.cast(pAdapter1, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
        GetDesc1 = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC1))(adapter1_vtable[10])
        desc = DXGI_ADAPTER_DESC1()
        GetDesc1(pAdapter1, ctypes.byref(desc))

        ReleaseDXGI = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(adapter_vtable[2])
        ReleaseDXGI(pAdapter1)
        ReleaseDXGI(pAdapter)
        ReleaseDXGI(pDXGIDevice)
        ReleaseDev = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable[2])
        ReleaseDev(pDevice)
        if pContext.value:
            ctx_vtable = ctypes.cast(ctypes.cast(pContext, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
            ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(ctx_vtable[2])(pContext)

        vendor_id_hex = f"0x{desc.VendorId:04x}".lower()
        device_id_hex = f"0x{desc.DeviceId:04x}".lower()
        luid_str = f"0x{desc.AdapterLuid_HighPart:x}:0x{desc.AdapterLuid_LowPart:x}"
        driver_ver = _get_matching_driver_version(device_id_hex)
        vendor_name = {
            AMD_VENDOR_ID: "AMD",
            "0x10de": "NVIDIA",
            "0x8086": "Intel",
        }.get(vendor_id_hex, "UNKNOWN")

        return {
            "vendor_id": vendor_id_hex,
            "device_id": device_id_hex,
            "adapter_name": str(desc.Description),
            "vendor": vendor_name,
            "adapter_luid": luid_str,
            "driver_version": driver_ver,
        }
    except Exception:
        return None


def _probe_via_native_dll() -> dict[str, Any] | None:
    """Probe hardware capabilities directly via telem_amd_native.dll."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        repo_root = Path(__file__).resolve().parents[2]
        candidates = [
            repo_root / "native" / "d3d11_amf_pipeline" / "bin" / "telem_amd_native.dll",
            repo_root / "runtime" / "amd" / "bin" / "telem_amd_native.dll",
        ]
        dll_path = next((p for p in candidates if p.exists()), None)
        if not dll_path:
            return None

        dll = ctypes.CDLL(str(dll_path))
        if not hasattr(dll, "telem_amd_probe_capabilities"):
            return None

        buf = (ctypes.c_int * 9)()
        res = dll.telem_amd_probe_capabilities(ctypes.cast(buf, ctypes.c_void_p))
        if res != 1:
            return None

        return {
            "h264_encode_available": bool(buf[0]),
            "h264_8bit_available": bool(buf[1]),
            "hevc_encode_available": bool(buf[2]),
            "hevc_main10_available": bool(buf[3]),
            "av1_encode_available": bool(buf[4]),
            "av1_8bit_available": bool(buf[5]),
            "av1_10bit_available": bool(buf[6]),
            "max_encode_width": int(buf[7]),
            "max_encode_height": int(buf[8]),
        }
    except Exception:
        return None


def query_native_amf_capabilities(*, identity_only: bool = False) -> dict[str, Any]:
    """Query active DXGI adapter and AMF capabilities."""
    # 0. Check for developer mock override
    mock_env = os.environ.get("TELEM_AMD_MOCK_CAPS", "").strip().lower()
    if mock_env in ("1", "true", "rdna3", "av1_rdna3", "av1"):
        return {
            "status": "OK",
            "vendor": "AMD",
            "adapter_name": "AMD Radeon RX 7900 XTX (Mock RDNA3)",
            "vendor_id": AMD_VENDOR_ID,
            "device_id": "0x744c",
            "adapter_luid": "0x0:0x1234",
            "driver_version": "31.0.21925.1001",
            "hardware_encoder": "AMF",
            "selected_codec": "HEVC",
            "h264_encode_available": True,
            "h264_8bit_available": True,
            "hevc_encode_available": True,
            "hevc_main10_available": True,
            "av1_encode_available": True,
            "av1_8bit_available": True,
            "av1_10bit_available": True,
            "max_encode_width": 7680,
            "max_encode_height": 4320,
            "hardware_decode_available": True,
            "hevc_main10_decode_available": True,
            "capability_source": "MockRDNA3",
            "probe_timestamp": _now_iso(),
            "schema_version": SCHEMA_VERSION,
        }

    # 1. First attempt: Direct DXGI / DLL probe (in-process, fast, 100% reliable)
    dxgi_id = _probe_dxgi_identity()
    if dxgi_id is not None:
        if identity_only:
            return {
                "status": "OK",
                "vendor": dxgi_id["vendor"],
                "adapter_name": dxgi_id["adapter_name"],
                "vendor_id": dxgi_id["vendor_id"],
                "device_id": dxgi_id["device_id"],
                "adapter_luid": dxgi_id["adapter_luid"],
                "driver_version": dxgi_id["driver_version"],
                "capability_source": "DirectDXGI",
                "probe_timestamp": _now_iso(),
                "schema_version": SCHEMA_VERSION,
            }

        dll_caps = _probe_via_native_dll()
        if dll_caps is not None:
            is_amd = dxgi_id["vendor_id"] == AMD_VENDOR_ID
            has_enc = is_amd and (dll_caps["hevc_encode_available"] or dll_caps["h264_encode_available"])
            return {
                "status": "OK",
                "vendor": dxgi_id["vendor"],
                "adapter_name": dxgi_id["adapter_name"],
                "vendor_id": dxgi_id["vendor_id"],
                "device_id": dxgi_id["device_id"],
                "adapter_luid": dxgi_id["adapter_luid"],
                "driver_version": dxgi_id["driver_version"],
                "hardware_encoder": "AMF" if has_enc else None,
                "selected_codec": "HEVC" if has_enc else None,
                "h264_encode_available": dll_caps["h264_encode_available"] if is_amd else None,
                "h264_8bit_available": dll_caps["h264_8bit_available"] if is_amd else None,
                "hevc_encode_available": dll_caps["hevc_encode_available"] if is_amd else None,
                "hevc_main10_available": dll_caps["hevc_main10_available"] if is_amd else None,
                "av1_encode_available": dll_caps["av1_encode_available"] if is_amd else None,
                "av1_8bit_available": dll_caps["av1_8bit_available"] if is_amd else None,
                "av1_10bit_available": dll_caps["av1_10bit_available"] if is_amd else None,
                "max_encode_width": dll_caps["max_encode_width"] if is_amd else None,
                "max_encode_height": dll_caps["max_encode_height"] if is_amd else None,
                "hardware_decode_available": True,
                "hevc_main10_decode_available": True,
                "capability_source": "NativeDLLProbe",
                "probe_timestamp": _now_iso(),
                "schema_version": SCHEMA_VERSION,
            }

    # 2. Fallback attempt: query_amf_caps.exe if present
    query_bin = _query_binary()
    if query_bin is not None:
        try:
            args = [str(query_bin)] + (["--identity-only"] if identity_only else [])
            probe_env = os.environ.copy()
            probe_dirs = [str(query_bin.parent)]
            mingw_bin = Path("C:/tools/mingw64/bin")
            if mingw_bin.exists():
                probe_dirs.append(str(mingw_bin))
            probe_env["PATH"] = os.pathsep.join(probe_dirs + [probe_env.get("PATH", "")])
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=5,
                env=probe_env,
                **({"startupinfo": _nt_startupinfo()} if os.name == "nt" else {}),
            )
            if result.returncode == 0:
                return _parse_probe_output(result.stdout, identity_only=identity_only)
        except Exception:
            pass

    return {"status": "UNKNOWN", "capability_source": "NONE", "error": "Unable to probe adapter"}


def _same_cache_identity(cached: Mapping[str, Any], identity: Mapping[str, Any]) -> bool:
    fields = ("schema_version", "adapter_luid", "vendor_id", "device_id", "driver_version")
    return all(str(cached.get(field, "")) == str(identity.get(field, "")) for field in fields)


_MEMORY_CAPS_CACHE: GpuCapabilities | None = None


def reset_capabilities_cache() -> None:
    global _MEMORY_CAPS_CACHE
    _MEMORY_CAPS_CACHE = None


def get_gpu_capabilities(force_refresh: bool = False) -> GpuCapabilities:
    """Return the active adapter snapshot, using only identity-matching cache."""
    global _MEMORY_CAPS_CACHE
    if _MEMORY_CAPS_CACHE is not None and not force_refresh:
        return replace(_MEMORY_CAPS_CACHE, cache_hit=True)

    cache_path = get_capabilities_cache_path()
    warm_start = time.perf_counter()
    identity = query_native_amf_capabilities(identity_only=True)
    if not force_refresh and identity.get("status") == "OK" and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                cached.get("schema_version") == SCHEMA_VERSION
                and cached.get("status") == "OK"
                and _same_cache_identity(cached, identity)
            ):
                warm_ms = (time.perf_counter() - warm_start) * 1000.0
                model = GpuCapabilities.from_dict(cached)
                model = replace(model, cache_hit=True, cache_warm_ms=warm_ms)
                _MEMORY_CAPS_CACHE = model
                return model
        except (OSError, ValueError, TypeError):
            pass

    cold_start = time.perf_counter()
    payload = query_native_amf_capabilities(identity_only=False)
    cold_ms = (time.perf_counter() - cold_start) * 1000.0
    payload["cache_hit"] = False
    payload["probe_cold_ms"] = cold_ms
    model = GpuCapabilities.from_dict(payload)
    if model.status == "OK":
        try:
            cache_path.write_text(json.dumps(model.to_dict(), indent=2), encoding="utf-8")
        except OSError:
            pass
    _MEMORY_CAPS_CACHE = model
    return model


def get_amd_gpu_capabilities(force_refresh: bool = False) -> dict[str, Any]:
    """Compatibility mapping for existing callers; model remains canonical."""
    return get_gpu_capabilities(force_refresh=force_refresh).to_dict()


def probe_amd_encode_resolution(width: int, height: int, ffmpeg_exe: str = "ffmpeg") -> bool:
    """One-frame AMF capability preflight used only when AMFIOCaps is UNKNOWN."""
    try:
        result = subprocess.run(
            [
                ffmpeg_exe, "-hide_banner", "-f", "lavfi",
                "-i", f"color=c=black:s={int(width)}x{int(height)}:d=0.03",
                "-frames:v", "1", "-c:v", "hevc_amf", "-f", "null", "-",
            ],
            capture_output=True,
            timeout=10,
            **({"startupinfo": _nt_startupinfo()} if os.name == "nt" else {}),
        )
        return result.returncode == 0
    except Exception:
        return False


def check_amd_encode_resolution(
    width: int,
    height: int,
    *,
    ffmpeg_exe: str = "ffmpeg",
) -> tuple[bool, str, GpuCapabilities]:
    caps = get_gpu_capabilities()
    supported = caps.supports_encode(width, height)
    if supported is True:
        return True, f"AMF HEVC max {caps.max_encode_width}x{caps.max_encode_height}", caps
    if supported is False:
        return False, (
            f"AMF HEVC na aktywnym GPU obsługuje maksymalnie "
            f"{caps.max_encode_width}x{caps.max_encode_height}; żądano {width}x{height}."
        ), caps

    # Unknown is not converted into an AMD-specific 4096 limit.
    if probe_amd_encode_resolution(width, height, ffmpeg_exe):
        return True, "AMF capability UNKNOWN; one-frame hardware preflight PASS", caps
    return False, (
        f"AMF capability UNKNOWN; one-frame hardware preflight FAILED for {width}x{height}. "
        "Render blocked until capability is confirmed."
    ), caps


def is_amd_hevc_resolution_supported(width: int, height: int) -> tuple[bool, str]:
    ok, reason, _ = check_amd_encode_resolution(width, height)
    return ok, reason


def format_startup_capabilities(caps: GpuCapabilities) -> str:
    max_text = (
        f"{caps.max_encode_width}x{caps.max_encode_height}"
        if caps.max_encode_width and caps.max_encode_height else "UNKNOWN"
    )
    cache_text = "HIT" if caps.cache_hit else "MISS"
    probe_ms = caps.cache_warm_ms if caps.cache_hit else caps.probe_cold_ms
    probe_text = f"{probe_ms:.2f} ms" if probe_ms is not None else "UNKNOWN"
    return (
        "[GPU CAPABILITIES]\n"
        f"Adapter: {caps.adapter_name}\n"
        f"Vendor: {caps.vendor}\n"
        f"DeviceId: {caps.device_id}\n"
        f"Driver: {caps.driver_version}\n"
        f"Encoder: {caps.hardware_encoder or 'UNKNOWN'} {caps.selected_codec or ''}\n"
        f"HEVC Main10: {'YES' if caps.hevc_main10_available is True else 'NO' if caps.hevc_main10_available is False else 'UNKNOWN'}\n"
        f"Max encode: {max_text}\n"
        f"Cache: {cache_text}\n"
        f"Probe: {probe_text}"
    )
