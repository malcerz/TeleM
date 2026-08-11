"""Hardware detection for FFmpeg: GPU decoders and encoders.

Exposes:
    detect_gpu_decoder(preferred_encoder) -> str | None
    detect_best_encoder()                 -> str
    _test_hwaccel(hwaccel)               -> bool
    _test_encoder(encoder_name)          -> bool
    _nt_startupinfo()                    -> STARTUPINFO
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

# Cached result of GPU decoder detection (None = CPU fallback)
# False = not yet checked; dict[str, str|None] = checked per preferred_encoder
_GPU_DECODER_CACHE: str | None | bool | dict = False


def _nt_startupinfo() -> Any:
    """Return a STARTUPINFO that hides the console window on Windows."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def _test_hwaccel(hwaccel: str) -> bool:
    """Test whether a given ``-hwaccel`` actually works by running a quick FFmpeg command.

    Returns ``True`` if the device can be initialised, ``False`` otherwise.
    """
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-hwaccel", hwaccel,
                "-f", "lavfi", "-i", "color=c=black:s=352x288:d=0.1",
                "-f", "null", "-",
            ],
            capture_output=True, timeout=10,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        return r.returncode == 0
    except Exception:
        return False


def detect_gpu_decoder(preferred_encoder: str = "") -> str | None:
    """Return the best ``-hwaccel`` flag for this system, or ``None`` for CPU.

    If *preferred_encoder* is 'intel', prefers 'qsv' or 'd3d11va'.
    If *preferred_encoder* is 'nv', prefers 'cuda'.
    Checks NVIDIA (nvidia-smi), then queries ffmpeg -hwaccels for available
    hardware accelerators and validates each candidate with a short test.
    Result is cached per preferred encoder in ``_GPU_DECODER_CACHE``.
    """
    global _GPU_DECODER_CACHE
    cache_key = preferred_encoder.lower()
    if isinstance(_GPU_DECODER_CACHE, dict) and cache_key in _GPU_DECODER_CACHE:
        return _GPU_DECODER_CACHE[cache_key]

    if not isinstance(_GPU_DECODER_CACHE, dict):
        _GPU_DECODER_CACHE = {}

    selected_hw = None

    if preferred_encoder == "amd":
        for hw in ("d3d11va", "dxva2", "vulkan", "vaapi"):
            if _test_hwaccel(hw):
                selected_hw = hw
                break
    elif preferred_encoder == "intel":
        # On dual GPU systems (NVIDIA + Intel), '-hwaccel qsv' often locks up FFmpeg
        # when decoding input video in a pipe. 'd3d11va' / 'dxva2' work reliably on Intel GPU.
        for hw in ("d3d11va", "dxva2", "vulkan"):
            if _test_hwaccel(hw):
                selected_hw = hw
                break
    elif preferred_encoder == "nv":
        try:
            r = subprocess.run(
                ["nvidia-smi"], capture_output=True, timeout=5,
                **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
            )
            if r.returncode == 0 and _test_hwaccel("cuda"):
                selected_hw = "cuda"
        except Exception:
            pass

    if selected_hw is None:
        # Fallback priority check
        for hw in ("cuda", "d3d11va", "dxva2", "qsv", "vaapi", "vulkan"):
            if _test_hwaccel(hw):
                selected_hw = hw
                break

    _GPU_DECODER_CACHE[cache_key] = selected_hw
    return selected_hw


def _test_encoder(encoder_name: str) -> bool:
    """Test whether a given encoder actually works by running a quick encode.

    Returns ``True`` if the encoder initialises successfully, ``False`` otherwise.
    """
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-hide_banner",
                "-f", "lavfi", "-i", "color=c=black:s=352x288:d=0.1",
                "-c:v", encoder_name,
                "-f", "null", "-",
            ],
            capture_output=True, timeout=10,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        return r.returncode == 0
    except Exception:
        return False


def detect_best_encoder() -> str:
    """Detect the best available hardware encoder on this system.

    Returns one of ``'nv'`` (NVIDIA NVENC), ``'amd'`` (AMD AMF),
    ``'intel'`` (Intel QSV) or ``'cpu'`` (libx265 software).
    Result is cached for subsequent calls.
    """
    # Force detection if not yet done (do not use its result for encoding
    # decisions – we need a separate validation)
    detect_gpu_decoder()

    # Primary source of truth: check which encoders FFmpeg actually supports
    # and test each one to make sure the device is usable.
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        if r.returncode == 0:
            encoders = r.stdout
            # Prefer NVIDIA NVENC, then AMD AMF, then Intel QSV
            if "hevc_nvenc" in encoders and _test_encoder("hevc_nvenc"):
                return "nv"
            if "hevc_amf" in encoders and _test_encoder("hevc_amf"):
                return "amd"
            if "h264_amf" in encoders and _test_encoder("h264_amf"):
                return "amd"
            if "hevc_qsv" in encoders and _test_encoder("hevc_qsv"):
                return "intel"
    except Exception:
        pass

    # Fallback: nvidia-smi + encoder test (nvidia-smi may exist without
    # full NVENC driver support, so test separately)
    try:
        r = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        if r.returncode == 0 and _test_encoder("hevc_nvenc"):
            return "nv"
    except Exception:
        pass

    return "cpu"
