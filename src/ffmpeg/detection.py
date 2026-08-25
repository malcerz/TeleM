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
_BEST_ENCODER_CACHE: str | None = None


def _nt_startupinfo() -> Any:
    """Return a STARTUPINFO that hides the console window on Windows."""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def _test_hwaccel(hwaccel: str, ffmpeg_exe: str = "ffmpeg") -> bool:
    """Test whether a given ``-hwaccel`` is supported by the FFmpeg binary."""
    try:
        r = subprocess.run(
            [ffmpeg_exe, "-hide_banner", "-hwaccels"],
            capture_output=True, text=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        if r.returncode == 0:
            lines = [line.strip() for line in r.stdout.splitlines()]
            return hwaccel in lines
        return False
    except Exception:
        return False


def detect_gpu_decoder(preferred_encoder: str = "", ffmpeg_exe: str = "ffmpeg") -> str | None:
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
    if preferred_encoder == "cpu":
        _GPU_DECODER_CACHE[cache_key] = None
        return None

    if preferred_encoder == "amd":
        for hw in ("d3d11va", "dxva2"):
            if _test_hwaccel(hw, ffmpeg_exe):
                selected_hw = hw
                break
        if selected_hw is None:
            selected_hw = "d3d11va"
    elif preferred_encoder == "intel":
        # On dual GPU systems (NVIDIA + Intel), '-hwaccel qsv' often locks up FFmpeg
        # when decoding input video in a pipe. 'd3d11va' / 'dxva2' work reliably on Intel GPU.
        for hw in ("d3d11va", "dxva2", "vulkan"):
            if _test_hwaccel(hw, ffmpeg_exe):
                selected_hw = hw
                break
    elif preferred_encoder == "nv":
        try:
            r = subprocess.run(
                ["nvidia-smi"], capture_output=True, timeout=5,
                **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
            )
            if r.returncode == 0 and _test_hwaccel("cuda", ffmpeg_exe):
                selected_hw = "cuda"
        except Exception:
            pass

    if selected_hw is None:
        # Fallback priority check
        for hw in ("cuda", "d3d11va", "dxva2", "qsv", "vaapi", "vulkan"):
            if _test_hwaccel(hw, ffmpeg_exe):
                selected_hw = hw
                break

    _GPU_DECODER_CACHE[cache_key] = selected_hw
    return selected_hw


def _test_encoder(encoder_name: str, ffmpeg_exe: str = "ffmpeg") -> bool:
    """Test whether a given encoder actually works by running a quick encode.

    Returns ``True`` if the encoder initialises successfully, ``False`` otherwise.
    """
    try:
        r = subprocess.run(
            [
                ffmpeg_exe, "-hide_banner",
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


def detect_best_encoder(ffmpeg_exe: str = "ffmpeg") -> str:
    """Detect the best available hardware encoder on this system.

    Returns one of ``'nv'`` (NVIDIA NVENC), ``'amd'`` (AMD AMF),
    ``'intel'`` (Intel QSV) or ``'cpu'`` (libx265 software).
    Result is cached for subsequent calls.
    """
    global _BEST_ENCODER_CACHE
    if _BEST_ENCODER_CACHE is not None:
        return _BEST_ENCODER_CACHE

    # Force detection if not yet done (do not use its result for encoding
    # decisions – we need a separate validation)
    detect_gpu_decoder(ffmpeg_exe=ffmpeg_exe)

    # Primary source of truth: check which encoders FFmpeg actually supports
    # and test each one to make sure the device is usable.
    try:
        r = subprocess.run(
            [ffmpeg_exe, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        if r.returncode == 0:
            encoders = r.stdout
            # Prefer NVIDIA NVENC, then AMD AMF, then Intel QSV
            if "hevc_nvenc" in encoders and _test_encoder("hevc_nvenc", ffmpeg_exe):
                _BEST_ENCODER_CACHE = "nv"
                return "nv"
            if "hevc_amf" in encoders and _test_encoder("hevc_amf", ffmpeg_exe):
                _BEST_ENCODER_CACHE = "amd"
                return "amd"
            if "h264_amf" in encoders and _test_encoder("h264_amf", ffmpeg_exe):
                _BEST_ENCODER_CACHE = "amd"
                return "amd"
            if "hevc_qsv" in encoders and _test_encoder("hevc_qsv", ffmpeg_exe):
                _BEST_ENCODER_CACHE = "intel"
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
        if r.returncode == 0 and _test_encoder("hevc_nvenc", ffmpeg_exe):
            _BEST_ENCODER_CACHE = "nv"
            return "nv"
    except Exception:
        pass

    _BEST_ENCODER_CACHE = "cpu"
    return "cpu"


def _test_amd_gpu_compositor(ffmpeg_exe: str = "ffmpeg") -> bool:
    """Test whether AMD GPU hardware compositing (OpenCL/D3D11) initialises safely.

    Runs a 1-frame test command to verify that OpenCL device creation doesn't fail
    with queue creation errors on AMD APU/iGPU driver contexts.
    """
    try:
        r = subprocess.run(
            [
                ffmpeg_exe, "-hide_banner",
                "-init_hw_device", "opencl=ocl", "-filter_hw_device", "ocl",
                "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1",
                "-f", "lavfi", "-i", "color=c=white:s=100x100:d=0.1",
                "-filter_complex", "[0:v]format=nv12,hwupload[b];[1:v]hwupload[o];[b][o]overlay_opencl[v];[v]hwdownload,format=nv12[out]",
                "-map", "[out]", "-c:v", "hevc_amf", "-f", "null", "-",
            ],
            capture_output=True, timeout=5,
            **({} if os.name != "nt" else {"startupinfo": _nt_startupinfo()}),
        )
        return r.returncode == 0
    except Exception:
        return False


def detect_amd_native_support(ffmpeg_exe: str = "ffmpeg") -> bool:
    """Test whether native AMD C++ D3D11 + AMF pipeline is supported on this system."""
    if os.name != "nt":
        return False

    def _release_com(ptr) -> None:
        """Release an IUnknown COM pointer (ID3D11Device / ID3D11DeviceContext).

        D3D11CreateDevice returns refcounted COM interfaces; every created
        device/context must be Released or the device leaks driver-side kernel
        objects.  Release is vtable slot 2 (IUnknown::Release).
        """
        if not ptr or not ptr.value:
            return
        try:
            vtbl = ctypes.cast(ptr.value, ctypes.POINTER(ctypes.c_void_p))
            release = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p)(vtbl[2])
            release(ptr.value)
        except Exception:
            pass

    pDevice = None
    pContext = None
    try:
        import ctypes
        d3d11 = ctypes.windll.d3d11
        amf_dll = ctypes.windll.LoadLibrary("amfrt64.dll")

        pDevice = ctypes.c_void_p()
        pContext = ctypes.c_void_p()
        featureLevel = ctypes.c_uint()

        hr = d3d11.D3D11CreateDevice(
            None, 1, None, 0x8, None, 0, 7,
            ctypes.byref(pDevice), ctypes.byref(featureLevel), ctypes.byref(pContext)
        )
        if hr < 0:
            return False

        return _test_encoder("hevc_amf", ffmpeg_exe) or _test_encoder("h264_amf", ffmpeg_exe)
    except Exception:
        return False
    finally:
        # Always release the COM interfaces on success, failure and exception.
        _release_com(pContext)
        _release_com(pDevice)


def detect_amd_compose_backend(preferred_backend: str = "AUTO", ffmpeg_exe: str = "ffmpeg") -> str:
    """Select AMD overlay composition backend ('AMD_NATIVE_D3D11', 'D3D11_GPU', or 'SOFTWARE')."""
    pref = preferred_backend.upper()
    if pref == "SOFTWARE":
        return "SOFTWARE"
    if pref in ("AMD_NATIVE_D3D11", "AUTO", "GPU", "NATIVE"):
        if detect_amd_native_support(ffmpeg_exe):
            return "AMD_NATIVE_D3D11"
        if _test_amd_gpu_compositor(ffmpeg_exe):
            return "D3D11_GPU"
        return "SOFTWARE"
    return "SOFTWARE"


