"""Wykrywanie parametrów i możliwości sprzętowych dla GUI TeleM.

Dostarcza czytelnych informacji o:
- systemie operacyjnym
- procesorze (CPU) i liczbie wątków
- pamięci RAM
- kartach graficznych (GPU)
- aktywnym akceleratorze podglądu
- obsługiwanych koderach sprzętowych (AMD, NVIDIA, Intel, CPU)
- obsługiwanych dekoderach sprzętowych (H.264, HEVC, AV1)
- maksymalnych rozdzielczościach kodowania/dekodowania
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class HardwareCapabilitiesInfo:
    os_name: str = "Nieznany"
    cpu_name: str = "Nieznany CPU"
    cpu_threads: str = "Nieznane"
    ram_total: str = "Nieznana"
    gpus: list[str] = field(default_factory=list)
    active_preview: str = "Auto"
    enc_amd: str = "Nieznane"
    enc_nvidia: str = "Nieznane"
    enc_intel: str = "Nieznane"
    enc_cpu: str = "Dostępne (libx264 / libx265)"
    dec_h264: str = "Dostępne (sprzętowe)"
    dec_hevc: str = "Dostępne (sprzętowe)"
    dec_av1: str = "Dostępne (wg runtime)"
    max_decode: str = "Do 8K (wg runtime)"
    max_encode: str = "Wg sterownika / runtime"


_CACHED_HW_INFO: Optional[HardwareCapabilitiesInfo] = None


def _get_ram_string() -> str:
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            gb = stat.ullTotalPhys / (1024 ** 3)
            return f"{gb:.1f} GB"
    except Exception:
        pass
    return "Nieznana"


def _get_cpu_info() -> tuple[str, str]:
    cpu_name = ""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        )
        name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        winreg.CloseKey(key)
        cpu_name = str(name).strip()
    except Exception:
        pass

    if not cpu_name:
        cpu_name = platform.processor() or "Nieznany procesor"

    threads = os.cpu_count() or 1
    threads_str = f"{threads} wątków"
    return cpu_name, threads_str


def _get_gpus() -> list[str]:
    seen: list[str] = []
    normalized_keys: set[str] = set()

    def _norm(s: str) -> str:
        return s.lower().replace("(tm)", "").replace("(r)", "").replace("-", " ").replace(" ", "")

    # 1. Sprawdź zarejestrowany adapter AMD z amd_capabilities
    try:
        from src.ffmpeg.amd_capabilities import get_gpu_capabilities
        caps = get_gpu_capabilities()
        if caps and caps.adapter_name and caps.adapter_name != "Unknown":
            drv = f" (sterownik {caps.driver_version})" if caps.driver_version and caps.driver_version != "Unknown" else ""
            item = f"{caps.adapter_name}{drv}"
            seen.append(item)
            normalized_keys.add(_norm(caps.adapter_name))
    except Exception:
        pass

    # 2. Rejestr Windows (wszystkie karty graficzne)
    try:
        import winreg
        base_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        )
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(base_key, i)
                i += 1
                if subkey_name.isdigit():
                    sub = winreg.OpenKey(base_key, subkey_name)
                    try:
                        desc, _ = winreg.QueryValueEx(sub, "DriverDesc")
                        desc_str = str(desc).strip()
                        if desc_str and "remote" not in desc_str.lower() and "basic" not in desc_str.lower():
                            nk = _norm(desc_str)
                            if nk not in normalized_keys:
                                normalized_keys.add(nk)
                                seen.append(desc_str)
                    except Exception:
                        pass
                    winreg.CloseKey(sub)
            except OSError:
                break
        winreg.CloseKey(base_key)
    except Exception:
        pass

    if not seen:
        seen.append("Wykrywanie automatyczne (DirectX / Vulkan)")
    return seen


def get_hardware_info(force_refresh: bool = False) -> HardwareCapabilitiesInfo:
    """Zwraca spójny model informacji sprzętowych systemu."""
    global _CACHED_HW_INFO
    if _CACHED_HW_INFO is not None and not force_refresh:
        return _CACHED_HW_INFO

    info = HardwareCapabilitiesInfo()

    # OS
    info.os_name = f"{platform.system()} {platform.release()} (kompilacja {platform.version().split('.')[-1]})"

    # CPU & RAM
    info.cpu_name, info.cpu_threads = _get_cpu_info()
    info.ram_total = _get_ram_string()

    # GPU
    info.gpus = _get_gpus()

    # Aktywny podgląd
    try:
        from src.gui.qt.mpv_hwdec import detect_preview_vendor, vendor_label
        p_vendor = detect_preview_vendor()
        info.active_preview = f"{vendor_label(p_vendor)} (d3d11va/mpv)"
    except Exception:
        info.active_preview = "Auto (d3d11va)"

    # Enkodery
    try:
        from src.ffmpeg.detection import _test_encoder
        has_amf = _test_encoder("hevc_amf") or _test_encoder("h264_amf")
        has_nv = _test_encoder("hevc_nvenc")
        has_qsv = _test_encoder("hevc_qsv")

        info.enc_amd = "Dostępne (AMF HEVC / H.264)" if has_amf else "Niedostępne"
        info.enc_nvidia = "Dostępne (NVENC)" if has_nv else "Niedostępne"
        try:
            from src.ffmpeg.intel_native_exporter import query_intel_capabilities
            intel_caps = query_intel_capabilities()
            intel_codecs = []
            if intel_caps.get("AV1_AVAILABLE") and intel_caps.get("AV1_10BIT"):
                intel_codecs.append("AV1")
            if intel_caps.get("HEVC_AVAILABLE") and intel_caps.get("HEVC_10BIT"):
                intel_codecs.append("HEVC")
            if intel_caps.get("H264_AVAILABLE") and intel_caps.get("H264_8BIT"):
                intel_codecs.append("H.264")
            if intel_codecs:
                info.enc_intel = f"Dostępne (QSV: {' / '.join(intel_codecs)})"
            else:
                info.enc_intel = "Niedostępne"
        except Exception:
            has_qsv = _test_encoder("hevc_qsv")
            info.enc_intel = "Dostępne (QSV)" if has_qsv else "Niedostępne"
        info.enc_cpu = "Dostępne (libx265 / libx264)"
    except Exception:
        info.enc_amd = "Wg sterownika (AMF)"
        info.enc_nvidia = "Niedostępne"
        info.enc_intel = "Niedostępne"
        info.enc_cpu = "Dostępne (CPU)"

    # Dekodery
    try:
        from src.ffmpeg.amd_capabilities import get_gpu_capabilities
        caps = get_gpu_capabilities()
        if caps.hardware_decode_available:
            info.dec_h264 = "Dostępne (sprzętowe D3D11VA)"
            info.dec_hevc = "Dostępne (sprzętowe Main / Main10)"
            info.dec_av1 = "Dostępne (sprzętowe / dav1d)"
        else:
            info.dec_h264 = "Dostępne (D3D11VA / CPU)"
            info.dec_hevc = "Dostępne (D3D11VA / CPU)"
            info.dec_av1 = "Dostępne (dav1d)"

        # Maks. rozdzielczość
        info.max_decode = "Do 8K (7680×4320)"
        if caps.max_encode_width and caps.max_encode_height:
            info.max_encode = f"Do {caps.max_encode_width}×{caps.max_encode_height} (AMF HEVC)"
        else:
            info.max_encode = "Do 4K / wg sterownika"
    except Exception:
        info.dec_h264 = "Dostępne (sprzętowe)"
        info.dec_hevc = "Dostępne (sprzętowe)"
        info.dec_av1 = "Dostępne (wg runtime)"
        info.max_decode = "Do 8K (wg runtime)"
        info.max_encode = "Wg sterownika / runtime"

    _CACHED_HW_INFO = info
    return info
