"""BikeRideHUD Central Runtime Path and Vendor Isolation Resolver.

Provides canonical, isolated runtime path resolution for:
- Common runtime (FFmpeg, telemetry parsers, shared licenses)
- AMD runtime (AMF native pipeline, AMD-specific dependencies)
- Intel runtime (Intel D3D11/oneVPL native pipeline, FFmpeg shared runtime dependencies)
- NVIDIA runtime (NVENC native pipeline, NVIDIA-specific dependencies)

Enforces strict vendor isolation:
- No cross-vendor DLL directory additions.
- No cross-vendor runtime binary loading.
- No lookups in legacy source build directories or external checkouts.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any, List, Optional


_APP_ROOT: Optional[Path] = None
_ACTIVE_DLL_DIRS: dict[str, list[Any]] = {}


def get_app_root() -> Path:
    """Return the canonical application root directory."""
    global _APP_ROOT
    if _APP_ROOT is None:
        _APP_ROOT = Path(__file__).resolve().parent.parent
    return _APP_ROOT


def set_app_root(root: Path | str) -> None:
    """Set or override application root (primarily for testing/harness)."""
    global _APP_ROOT
    _APP_ROOT = Path(root).resolve()


def get_runtime_dir() -> Path:
    """Return the base runtime directory (<app_root>/runtime)."""
    return get_app_root() / "runtime"


def get_common_runtime_dir() -> Path:
    """Return the common runtime directory (<app_root>/runtime/common)."""
    return get_runtime_dir() / "common"


def get_amd_runtime_dir() -> Path:
    """Return the AMD-specific runtime directory (<app_root>/runtime/amd)."""
    return get_runtime_dir() / "amd"


def get_intel_runtime_dir() -> Path:
    """Return the Intel-specific runtime directory (<app_root>/runtime/intel)."""
    return get_runtime_dir() / "intel"


def get_nvidia_runtime_dir() -> Path:
    """Return the NVIDIA-specific runtime directory (<app_root>/runtime/nvidia)."""
    return get_runtime_dir() / "nvidia"


def get_amd_native_dll() -> Path:
    """Return canonical path to telem_amd_native.dll."""
    override = os.environ.get("TELEM_AMD_NATIVE_DLL", "").strip()
    if override:
        return Path(override).resolve()
    return get_amd_runtime_dir() / "bin" / "telem_amd_native.dll"


def get_intel_native_dll() -> Path:
    """Return canonical path to telem_intel_native.dll."""
    override = os.environ.get("TELEM_INTEL_NATIVE_DLL", "").strip()
    if override:
        return Path(override).resolve()
    return get_intel_runtime_dir() / "bin" / "telem_intel_native.dll"


def get_nvidia_native_dll() -> Path:
    """Return canonical path to telem_nvenc_native.dll (if present)."""
    override = os.environ.get("TELEM_NVENC_DLL_OVERRIDE", "").strip()
    if override:
        return Path(override).resolve()
    return get_nvidia_runtime_dir() / "bin" / "telem_nvenc_native.dll"


def get_common_ffmpeg_exe() -> Path:
    """Return canonical path to common ffmpeg.exe (Intel, AMD, CPU)."""
    common_exe = get_common_runtime_dir() / "ffmpeg" / "ffmpeg.exe"
    if common_exe.exists():
        return common_exe
    root_exe = get_app_root() / "ffmpeg.exe"
    if root_exe.exists():
        return root_exe
    return common_exe


def get_common_ffprobe_exe() -> Path:
    """Return canonical path to common ffprobe.exe (Intel, AMD, CPU)."""
    common_exe = get_common_runtime_dir() / "ffmpeg" / "ffprobe.exe"
    if common_exe.exists():
        return common_exe
    root_exe = get_app_root() / "ffprobe.exe"
    if root_exe.exists():
        return root_exe
    return common_exe


def get_nvidia_ffmpeg_exe() -> Path:
    """Return canonical path to NVIDIA vendor-isolated ffmpeg.exe (falling back to common if absent)."""
    override = os.environ.get("TELEM_NVIDIA_FFMPEG_EXE", "").strip()
    if override:
        return Path(override).resolve()
    nv_exe = get_nvidia_runtime_dir() / "ffmpeg" / "ffmpeg.exe"
    if nv_exe.exists():
        return nv_exe
    return get_common_ffmpeg_exe()


def get_nvidia_ffprobe_exe() -> Path:
    """Return canonical path to NVIDIA vendor-isolated ffprobe.exe (falling back to common if absent)."""
    override = os.environ.get("TELEM_NVIDIA_FFPROBE_EXE", "").strip()
    if override:
        return Path(override).resolve()
    nv_probe = get_nvidia_runtime_dir() / "ffmpeg" / "ffprobe.exe"
    if nv_probe.exists():
        return nv_probe
    return get_common_ffprobe_exe()


def get_ffmpeg_exe(vendor: Optional[str] = None) -> Path:
    """Return canonical path to ffmpeg.exe, routing to vendor-specific binary if requested."""
    if vendor and str(vendor).strip().lower() in ("nv", "nvidia"):
        return get_nvidia_ffmpeg_exe()
    return get_common_ffmpeg_exe()


def get_ffprobe_exe(vendor: Optional[str] = None) -> Path:
    """Return canonical path to ffprobe.exe, routing to vendor-specific binary if requested."""
    if vendor and str(vendor).strip().lower() in ("nv", "nvidia"):
        return get_nvidia_ffprobe_exe()
    return get_common_ffprobe_exe()


def get_telemetry_parser_dir() -> Path:
    """Return canonical directory containing the DJI telemetry parser runtime."""
    return get_common_runtime_dir() / "telemetry" / "telemetry_parser"


def get_native_source_dir(vendor: str) -> Path:
    """Return canonical source directory for a vendor native pipeline."""
    v = vendor.lower()
    return get_app_root() / "src" / "native" / v


def compute_file_sha256(file_path: Path | str) -> str:
    """Compute and return hexadecimal SHA256 of a file."""
    p = Path(file_path)
    if not p.is_file():
        return "missing"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest()


def activate_vendor_dll_directory(vendor: str) -> list[Any]:
    """Add ONLY the selected vendor and common directories to Windows DLL search path.

    Strictly forbids loading foreign vendor directories (e.g. AMD when Intel is active).
    Returns list of directory handles added.
    """
    v = vendor.lower()
    if v not in {"amd", "intel", "nvidia", "common"}:
        raise ValueError(f"Unknown vendor for DLL isolation: {vendor}")

    if not hasattr(os, "add_dll_directory"):
        return []

    if v in _ACTIVE_DLL_DIRS and _ACTIVE_DLL_DIRS[v]:
        return _ACTIVE_DLL_DIRS[v]

    handles: list[Any] = []

    # 1. Common runtime directories (FFmpeg / telemetry) if relevant
    common_bin = get_common_runtime_dir() / "ffmpeg"
    if common_bin.exists():
        try:
            handles.append(os.add_dll_directory(str(common_bin.resolve())))
        except Exception:
            pass

    # 2. Selected vendor bin directory ONLY
    if v == "amd":
        vendor_bin = get_amd_runtime_dir() / "bin"
    elif v == "intel":
        vendor_bin = get_intel_runtime_dir() / "bin"
    elif v == "nvidia":
        vendor_bin = get_nvidia_runtime_dir() / "bin"
    else:
        vendor_bin = None

    if vendor_bin is not None and vendor_bin.exists():
        try:
            handles.append(os.add_dll_directory(str(vendor_bin.resolve())))
        except Exception:
            pass

    _ACTIVE_DLL_DIRS[v] = handles
    return handles


def log_runtime_diagnostic(backend: str, native_dll: Optional[Path | str] = None) -> None:
    """Print standard runtime isolation diagnostic block."""
    b = backend.lower()
    if b == "amd":
        runtime_dir = get_amd_runtime_dir()
        dll = Path(native_dll) if native_dll else get_amd_native_dll()
    elif b == "intel":
        runtime_dir = get_intel_runtime_dir()
        dll = Path(native_dll) if native_dll else get_intel_native_dll()
    elif b == "nvidia":
        runtime_dir = get_nvidia_runtime_dir()
        dll = Path(native_dll) if native_dll else get_nvidia_native_dll()
    else:
        runtime_dir = get_common_runtime_dir()
        dll = Path(native_dll) if native_dll else Path("")

    sha = compute_file_sha256(dll) if dll and dll.exists() else "not_found"

    print("[Runtime]", flush=True)
    print(f"backend={b}", flush=True)
    print(f"runtime_dir={runtime_dir}", flush=True)
    print(f"native_dll={dll}", flush=True)
    print(f"sha256={sha}", flush=True)
