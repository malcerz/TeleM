"""Canonical backend capability source of truth for BikeRideHUD / TeleM.

Provides a unified runtime capability object (BackendCapabilities) consumed by:
1. Hardware Capabilities panel (src/gui/qt/hardware_info.py)
2. Rendering encoder dropdown (src/gui/qt/tabs/render_tab.py)
3. Export safety gate & queue validation (src/gui/qt/_mixins/render_mixin.py, src/gui/export_queue.py)

Enforces:
- HARDWARE_PANEL_RENDER_GUI_PARITY=YES
- SILENT_CROSS_VENDOR_FALLBACK=NO
- QUEUE_CROSS_VENDOR_SILENT_FALLBACK=NO
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BackendCapabilities:
    """Canonical representation of host encoding backends."""

    amd_available: bool = False
    amd_reason: str = ""

    nvidia_available: bool = False
    nvidia_reason: str = ""

    intel_available: bool = False
    intel_reason: str = ""

    cpu_available: bool = True
    cpu_reason: str = ""

    # Detailed NVIDIA telemetry
    nvidia_gpu_present: bool = False
    nvidia_driver_present: bool = False
    nvidia_driver_version: str = ""
    nvidia_h264_nvenc: bool = False
    nvidia_hevc_nvenc: bool = False
    nvidia_av1_nvenc: bool = False
    nvidia_legacy_cuda: bool = False
    nvidia_native_d3d11: bool = False
    nvidia_codecs: list[str] = field(default_factory=list)

    # Detailed Intel telemetry
    intel_caps: dict[str, Any] = field(default_factory=dict)

    # Detailed CPU telemetry
    cpu_codecs: list[str] = field(default_factory=list)


_CACHED_BACKEND_CAPS: Optional[BackendCapabilities] = None


def invalidate_backend_capabilities_cache() -> None:
    """Invalidate backend capabilities cache."""
    global _CACHED_BACKEND_CAPS
    _CACHED_BACKEND_CAPS = None


def _get_ffmpeg_executable() -> str:
    try:
        from src.runtime_paths import get_ffmpeg_exe
        return str(get_ffmpeg_exe())
    except Exception:
        return "ffmpeg"


def _probe_nvidia_environment(ffmpeg_exe: str) -> tuple[bool, bool, str, bool, bool, bool, bool, bool, list[str], str]:
    """Probe NVIDIA GPU, driver, NVENC codecs, and backend support."""
    gpu_present = False
    driver_present = False
    driver_version = ""
    h264_ok = False
    hevc_ok = False
    av1_ok = False
    legacy_cuda_ok = False
    native_d3d11_ok = False
    codecs: list[str] = []
    reason = ""

    # Check GPU presence via WMI / PowerShell or nvidia-smi
    try:
        from src.gui.qt.hardware_info import _get_gpus
        gpus = _get_gpus()
        gpu_present = any("nvidia" in g.lower() or "geforce" in g.lower() or "quadro" in g.lower() for g in gpus)
    except Exception:
        pass

    try:
        si = None
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        r = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=5,
            startupinfo=si,
        )
        if r.returncode == 0:
            gpu_present = True
            driver_present = True
            # Extract driver version
            for line in r.stdout.splitlines():
                if "Driver Version:" in line:
                    parts = line.split("Driver Version:")
                    if len(parts) > 1:
                        driver_version = parts[1].split()[0].strip()
                        break
    except Exception:
        pass

    if not gpu_present:
        return False, False, "", False, False, False, False, False, [], "Brak karty graficznej NVIDIA"

    if not driver_present:
        return True, False, "", False, False, False, False, False, [], "Brak sterownika NVIDIA (nvidia-smi nie odpowiada)"

    # Probe NVENC codecs via FFmpeg
    from src.ffmpeg.detection import _test_encoder
    h264_ok = _test_encoder("h264_nvenc", ffmpeg_exe)
    hevc_ok = _test_encoder("hevc_nvenc", ffmpeg_exe)
    av1_ok = _test_encoder("av1_nvenc", ffmpeg_exe)

    if h264_ok:
        codecs.append("H.264")
    if hevc_ok:
        codecs.append("H.265")
    if av1_ok:
        codecs.append("AV1")

    legacy_cuda_ok = (h264_ok or hevc_ok or av1_ok)

    # Probe Native D3D11 backend
    try:
        from src.ffmpeg.nvidia_config import is_nvidia_native_available
        native_d3d11_ok, native_msg = is_nvidia_native_available()
    except Exception:
        native_d3d11_ok = False
        native_msg = "Wyjątek podczas sondowania native D3D11"

    nv_available = legacy_cuda_ok or native_d3d11_ok

    if not nv_available:
        # Build precise diagnostic reason
        if driver_version:
            reason = f"Sterownik NVIDIA {driver_version} nie obsługuje NVENC w tej wersji FFmpeg (wymagany nowszy sterownik)"
        else:
            reason = "Brak obsługi sprzętowego NVENC w sterowniku / FFmpeg"
    else:
        reason = f"Dostępny (NVENC: {' / '.join(codecs)})"

    return (
        gpu_present,
        driver_present,
        driver_version,
        h264_ok,
        hevc_ok,
        av1_ok,
        legacy_cuda_ok,
        native_d3d11_ok,
        codecs,
        reason,
    )


def _probe_amd_environment(ffmpeg_exe: str) -> tuple[bool, str]:
    """Probe AMD GPU, drivers, and AMF encoder capability."""
    gpu_present = False
    try:
        from src.gui.qt.hardware_info import _get_gpus
        gpus = _get_gpus()
        gpu_present = any("amd" in g.lower() or "radeon" in g.lower() for g in gpus)
    except Exception:
        pass

    if not gpu_present:
        return False, "Brak karty graficznej AMD / Radeon"

    from src.ffmpeg.detection import _test_encoder
    has_amf = _test_encoder("hevc_amf", ffmpeg_exe) or _test_encoder("h264_amf", ffmpeg_exe)

    # Check DLL
    try:
        from src.runtime_paths import get_amd_native_dll
        dll_path = get_amd_native_dll()
        dll_exists = dll_path.is_file()
    except Exception:
        dll_exists = False

    if has_amf and dll_exists:
        return True, "Dostępny (AMF)"
    elif has_amf:
        return True, "Dostępny (AMF FFmpeg)"
    else:
        return False, "Sterownik AMD nie obsługuje kodowania AMF w bieżącym runtime"


def query_backend_capabilities(force_refresh: bool = False) -> BackendCapabilities:
    """Query canonical backend capabilities of the host system.
    
    Results are cached until force_refresh is requested or invalidate_backend_capabilities_cache() is called.
    """
    global _CACHED_BACKEND_CAPS
    if _CACHED_BACKEND_CAPS is not None and not force_refresh:
        return _CACHED_BACKEND_CAPS

    ffmpeg_exe = _get_ffmpeg_executable()

    # 1. AMD Probe
    amd_ok, amd_reason = _probe_amd_environment(ffmpeg_exe)

    # 2. NVIDIA Probe
    (
        nv_gpu,
        nv_driver,
        nv_driver_ver,
        nv_h264,
        nv_hevc,
        nv_av1,
        nv_legacy_cuda,
        nv_native_d3d11,
        nv_codecs,
        nv_reason,
    ) = _probe_nvidia_environment(ffmpeg_exe)
    nv_ok = nv_legacy_cuda or nv_native_d3d11

    # 3. Intel Probe (reuse Phase 1-13 canonical probe)
    try:
        from src.ffmpeg.intel_native_exporter import query_intel_capabilities
        intel_caps = query_intel_capabilities(force_refresh=force_refresh)
        intel_codecs = []
        if intel_caps.get("AV1_AVAILABLE") and intel_caps.get("AV1_10BIT"):
            intel_codecs.append("AV1")
        if intel_caps.get("HEVC_AVAILABLE") and intel_caps.get("HEVC_10BIT"):
            intel_codecs.append("HEVC")
        if intel_caps.get("H264_AVAILABLE") and intel_caps.get("H264_8BIT"):
            intel_codecs.append("H.264")

        intel_ok = bool(intel_codecs)
        intel_reason = f"Dostępne (QSV: {' / '.join(intel_codecs)})" if intel_ok else "Brak obsługi QSV"
    except Exception as exc:
        intel_caps = {}
        intel_ok = False
        intel_reason = f"Błąd sondowania Intel: {exc}"

    # 4. CPU Probe
    from src.ffmpeg.detection import _test_encoder
    cpu_codecs = []
    if _test_encoder("libx265", ffmpeg_exe):
        cpu_codecs.append("libx265")
    if _test_encoder("libx264", ffmpeg_exe):
        cpu_codecs.append("libx264")
    cpu_ok = bool(cpu_codecs)
    cpu_reason = f"Dostępne ({' / '.join(cpu_codecs)})" if cpu_ok else "Brak koderów software x264/x265"

    caps = BackendCapabilities(
        amd_available=amd_ok,
        amd_reason=amd_reason,
        nvidia_available=nv_ok,
        nvidia_reason=nv_reason,
        intel_available=intel_ok,
        intel_reason=intel_reason,
        cpu_available=cpu_ok,
        cpu_reason=cpu_reason,
        nvidia_gpu_present=nv_gpu,
        nvidia_driver_present=nv_driver,
        nvidia_driver_version=nv_driver_ver,
        nvidia_h264_nvenc=nv_h264,
        nvidia_hevc_nvenc=nv_hevc,
        nvidia_av1_nvenc=nv_av1,
        nvidia_legacy_cuda=nv_legacy_cuda,
        nvidia_native_d3d11=nv_native_d3d11,
        nvidia_codecs=nv_codecs,
        intel_caps=intel_caps,
        cpu_codecs=cpu_codecs,
    )

    _CACHED_BACKEND_CAPS = caps
    return caps


def get_available_backends(caps: Optional[BackendCapabilities] = None) -> list[str]:
    """Return ordered list of available backend identifiers for the GUI dropdown.
    
    Order: auto, amd, nv, intel, cpu (omitting unavailable backends).
    """
    if caps is None:
        caps = query_backend_capabilities()

    backends = ["auto"]
    if caps.amd_available:
        backends.append("amd")
    if caps.nvidia_available:
        backends.append("nv")
    if caps.intel_available:
        backends.append("intel")
    if caps.cpu_available:
        backends.append("cpu")
    return backends


def resolve_auto_backend(caps: Optional[BackendCapabilities] = None) -> str:
    """Resolve 'auto' selection strictly among genuinely available backends.
    
    Priority: nv -> amd -> intel -> cpu.
    Logs structured auto selection:
    [AUTO ENCODER]
    available=[...]
    selected=<backend>
    """
    if caps is None:
        caps = query_backend_capabilities()

    available_concrete = []
    if caps.nvidia_available:
        available_concrete.append("nv")
    if caps.amd_available:
        available_concrete.append("amd")
    if caps.intel_available:
        available_concrete.append("intel")
    if caps.cpu_available:
        available_concrete.append("cpu")

    if not available_concrete:
        selected = "cpu"
    else:
        selected = available_concrete[0]

    print(
        f"[AUTO ENCODER]\n"
        f"available={available_concrete}\n"
        f"selected={selected}",
        flush=True,
    )
    return selected


def resolve_supported_backend(
    requested: Optional[str] = None,
    caps: Optional[BackendCapabilities] = None,
) -> str:
    """Resolve requested backend against host capability truth.
    
    If requested backend is unavailable, visibly resolves to the best available backend
    and logs structured fallback:
    [ENCODER FALLBACK]
    requested=<requested>
    available=0
    resolved=<resolved>
    reason=hardware_capability
    """
    if caps is None:
        caps = query_backend_capabilities()

    req_norm = (requested or "").strip().lower()
    if req_norm == "nvidia":
        req_norm = "nv"

    if req_norm in ("auto", ""):
        return resolve_auto_backend(caps)

    valid_backends = {
        "amd": caps.amd_available,
        "nv": caps.nvidia_available,
        "intel": caps.intel_available,
        "cpu": caps.cpu_available,
    }

    if valid_backends.get(req_norm, False):
        return req_norm

    # Fallback required
    resolved = resolve_auto_backend(caps)
    print(
        f"[ENCODER FALLBACK]\n"
        f"requested={requested}\n"
        f"available=0\n"
        f"resolved={resolved}\n"
        f"reason=hardware_capability",
        flush=True,
    )
    return resolved


def validate_backend_available(
    requested: str,
    caps: Optional[BackendCapabilities] = None,
) -> tuple[bool, str]:
    """Validate whether requested backend is available on this system.
    
    Returns (True, "") or (False, reason).
    """
    if caps is None:
        caps = query_backend_capabilities()

    req_norm = requested.strip().lower()
    if req_norm == "nvidia":
        req_norm = "nv"

    if req_norm == "auto":
        # Auto is available as long as at least one backend is available
        if caps.nvidia_available or caps.amd_available or caps.intel_available or caps.cpu_available:
            return True, ""
        return False, "Brak dostępnego jakiegokolwiek kodera sprzętowego lub programowego."

    if req_norm == "amd":
        if caps.amd_available:
            return True, ""
        return False, f"AMD backend niedostępny: {caps.amd_reason}"

    if req_norm == "nv":
        if caps.nvidia_available:
            return True, ""
        return False, f"NVIDIA backend niedostępny: {caps.nvidia_reason}"

    if req_norm == "intel":
        if caps.intel_available:
            return True, ""
        return False, f"Intel backend niedostępny: {caps.intel_reason}"

    if req_norm == "cpu":
        if caps.cpu_available:
            return True, ""
        return False, f"CPU backend niedostępny: {caps.cpu_reason}"

    return False, f"Nieznany backend: {requested}"
