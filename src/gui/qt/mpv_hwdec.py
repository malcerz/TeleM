"""Hardware-accelerated preview configuration for libmpv.

Detects available GPU adapters on Windows and builds per-vendor
:class:`mpv.MPV` initialisation kwargs with correct ``--hwdec`` chain,
``--gpu-api`` / ``--gpu-context``, and optional ``--d3d11-adapter``
for multi-GPU systems.

Usage::

    from src.gui.qt.mpv_hwdec import detect_preview_vendor, build_mpv_options
    vendor = detect_preview_vendor()
    opts = build_mpv_options(vendor)
    player = mpv.MPV(wid=str(win_id), **opts)
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

# ── GPU adapter detection (Windows) ───────────────────────────────────────

def _run_powershell(script: str) -> str:
    """Run a short PowerShell command and return stdout, stripped."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=10,
            **(dict(startupinfo=_nt_startupinfo()) if os.name == "nt" else {}),
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def _nt_startupinfo() -> Any:
    """Return STARTUPINFO that hides the console window on Windows."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def detect_gpu_adapters() -> list[dict[str, str]]:
    """Return a list of detected GPU adapters with ``vendor`` and ``name`` keys.

    Vendor is one of ``'nv'`` (NVIDIA), ``'amd'`` (AMD), ``'intel'`` (Intel),
    or ``'unknown'``.  The **name** corresponds to the D3D11 adapter description
    substring that mpv's ``--d3d11-adapter`` matches.

    On non-Windows returns an empty list.
    """
    if os.name != "nt":
        return []

    out = _run_powershell(
        r"Get-CimInstance Win32_VideoController | "
        r"Select-Object -ExpandProperty Name"
    )
    if not out:
        return []

    adapters: list[dict[str, str]] = []
    for line in out.splitlines():
        name = line.strip()
        if not name:
            continue
        name_lower = name.lower()
        if "nvidia" in name_lower:
            vendor = "nv"
        elif "amd" in name_lower or "radeon" in name_lower:
            vendor = "amd"
        elif "intel" in name_lower:
            vendor = "intel"
        else:
            vendor = "unknown"
        adapters.append({"vendor": vendor, "name": name})
    return adapters


# ── Preview vendor detection ──────────────────────────────────────────────

def detect_preview_vendor() -> str:
    """Detect the best preview accelerator for the current system.

    Returns ``'nv'``, ``'amd'``, ``'intel'``, or ``'cpu'``.

    Prioritises NVIDIA (nvdec/d3d11va), then AMD, then Intel, then CPU.
    Uses the existing ``detect_best_encoder`` from the ffmpeg pipeline
    as primary detection, with adapter-scan as fallback.
    """
    try:
        from src.ffmpeg_pipeline import detect_best_encoder
        vendor = detect_best_encoder()
        if vendor in ("nv", "amd", "intel"):
            return vendor
    except Exception:
        pass

    # Fallback: scan adapters
    adapters = detect_gpu_adapters()
    vendors_seen: set[str] = set()
    for ad in adapters:
        v = ad["vendor"]
        if v in ("nv", "amd", "intel") and v not in vendors_seen:
            vendors_seen.add(v)
            return v

    # Try nvidia-smi as last resort
    try:
        r = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=5,
            **(dict(startupinfo=_nt_startupinfo()) if os.name == "nt" else {}),
        )
        if r.returncode == 0:
            return "nv"
    except Exception:
        pass

    return "cpu"


def get_available_vendors() -> list[str]:
    """Return sorted list of vendor codes actually detected on this system.

    Always includes ``'cpu'``.  The ``'auto'`` pseudo-vendor is NOT returned
    here (callers add it separately).
    """
    adapters = detect_gpu_adapters()
    vendors: set[str] = set()
    for ad in adapters:
        if ad["vendor"] in ("nv", "amd", "intel"):
            vendors.add(ad["vendor"])

    # If nothing detected via adapters, try nvidia-smi
    if not vendors:
        try:
            r = subprocess.run(
                ["nvidia-smi"], capture_output=True, timeout=5,
                **(dict(startupinfo=_nt_startupinfo()) if os.name == "nt" else {}),
            )
            if r.returncode == 0:
                vendors.add("nv")
        except Exception:
            pass

    vendors.add("cpu")
    return sorted(vendors)


# ── mpv option builders ───────────────────────────────────────────────────

_VENDOR_LABELS: dict[str, str] = {
    "nv": "NVIDIA",
    "amd": "AMD",
    "intel": "Intel",
    "cpu": "CPU (software)",
    "auto": "Auto",
}


def vendor_label(vendor: str) -> str:
    """Human-readable label for a vendor code."""
    return _VENDOR_LABELS.get(vendor, vendor)


def _find_adapter_name(vendor: str) -> str | None:
    """Return the first D3D11 adapter name matching *vendor*, or ``None``."""
    for ad in detect_gpu_adapters():
        if ad["vendor"] == vendor:
            return ad["name"]
    return None


def build_mpv_options(vendor: str) -> dict[str, Any]:
    """Build kwargs for ``mpv.MPV(..., **kwargs)`` based on GPU vendor.

    Parameters
    ----------
    vendor:
        One of ``'nv'``, ``'amd'``, ``'intel'``, ``'cpu'``, ``'auto'``.

    Returns
    -------
    dict
        Keyword arguments that can be unpacked into :class:`mpv.MPV`.
        Always includes ``keep_open='yes'`` (required by the preview widget).
    """
    # Common base for all hardware-accelerated paths:
    # Force D3D11 GPU API + context so that d3d11va/dxva2 hwdec can initialise.
    # (When embedding via `wid=`, the default auto context may pick OpenGL/WGL,
    #  which prevents d3d11va from working → silent software fallback.)
    # The priority list ensures fallback to OpenGL if D3D11 is unavailable.
    base_opts: dict[str, Any] = {
        "keep_open": "yes",
    }

    if vendor == "cpu":
        base_opts["hwdec"] = "no"
        return base_opts

    # Hardware-accelerated paths — all use d3d11 context
    base_opts["gpu_api"] = "d3d11,opengl"
    base_opts["gpu_context"] = "d3d11,win"

    if vendor == "nv":
        adapter = _find_adapter_name("nv")
        base_opts["hwdec"] = "d3d11va,nvdec,cuda,auto"
        if adapter:
            base_opts["d3d11_adapter"] = adapter
        return base_opts

    if vendor == "amd":
        adapter = _find_adapter_name("amd")
        base_opts["hwdec"] = "d3d11va,dxva2,auto"
        if adapter:
            base_opts["d3d11_adapter"] = adapter
        return base_opts

    if vendor == "intel":
        adapter = _find_adapter_name("intel")
        base_opts["hwdec"] = "d3d11va,dxva2,auto"
        if adapter:
            base_opts["d3d11_adapter"] = adapter
        return base_opts

    # "auto" — let mpv choose, but still force d3d11 context
    base_opts["hwdec"] = "auto"
    return base_opts


# ── Runtime diagnostics ───────────────────────────────────────────────────

def get_hwdec_diagnostics(player: Any) -> dict[str, str | None]:
    """Query mpv properties to diagnose hardware decoding state.

    Parameters
    ----------
    player:
        An initialised ``mpv.MPV`` instance with a file loaded.

    Returns
    -------
    dict
        Keys: ``hwdec_current``, ``hwdec_interop``, ``pixelformat``,
        ``video_codec``, ``current_vo``, ``current_gpu_context``.
    """
    props = {
        "hwdec_current": "hwdec-current",
        "hwdec_interop": "hwdec-interop",
        "pixelformat": "video-params/pixelformat",
        "video_codec": "video-codec",
        "current_vo": "current-vo",
        "current_gpu_context": "current-gpu-context",
    }
    result: dict[str, str | None] = {}
    for key, prop in props.items():
        try:
            val = getattr(player, prop.replace("-", "_"), None)
            # Some properties can be called or accessed
            if val is None:
                try:
                    val = player._get_property(prop)
                except Exception:
                    val = None
            result[key] = str(val) if val is not None else None
        except Exception:
            result[key] = None
    return result
