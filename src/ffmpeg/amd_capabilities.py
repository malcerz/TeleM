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
    hevc_encode_available: bool | None = None
    hevc_main10_available: bool | None = None
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
            "hevc_encode_available": self.hevc_encode_available,
            "hevc_main10_available": self.hevc_main10_available,
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
            hevc_encode_available=_as_bool(data.get("hevc_encode_available")),
            hevc_main10_available=_as_bool(data.get("hevc_main10_available")),
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
    base_dir = Path(local_app_data) / "BikeRideHUD" if local_app_data else Path.home() / ".bikeridehud"
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


def query_native_amf_capabilities(*, identity_only: bool = False) -> dict[str, Any]:
    """Query active DXGI adapter and, unless requested, AMFIOCaps."""
    query_bin = _query_binary()
    if query_bin is None:
        return {"status": "UNKNOWN", "capability_source": "NONE", "error": "query_amf_caps.exe not found"}
    try:
        args = [str(query_bin)] + (["--identity-only"] if identity_only else [])
        probe_env = os.environ.copy()
        probe_dirs = [str(query_bin.parent)]
        # Developer/portable MinGW builds may use the runtime DLLs beside the
        # toolchain.  Production installs normally place them beside the exe;
        # adding an existing toolchain directory is harmless and keeps startup
        # probing independent of the shell that launched the GUI.
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
    except Exception as exc:
        return {"status": "UNKNOWN", "capability_source": "NONE", "error": str(exc)}
    if result.returncode != 0:
        return {
            "status": "UNKNOWN",
            "capability_source": "NONE",
            "error": f"query_amf_caps exited with code {result.returncode}: {result.stderr.strip()}",
        }
    return _parse_probe_output(result.stdout, identity_only=identity_only)


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
