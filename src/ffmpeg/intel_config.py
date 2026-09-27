"""Intel platform production configuration governance and single source of truth.

Centralizes validated production defaults for:
- Multi-Rect HUD upload (DEFAULT_INTEL_HUD_MULTIRECT = True)
- HUD worker count (DEFAULT_INTEL_HUD_WORKERS = 4)
- HUD prefetch depth (DEFAULT_INTEL_HUD_PREFETCH = 8)
- HUD texture ring depth (DEFAULT_INTEL_HUD_TEXTURE_RING = 1)
- Video Processor output ring depth (DEFAULT_INTEL_VP_RING = 8)
- oneVPL asynchronous encode depth (DEFAULT_INTEL_ENCODE_ASYNC = 8)

Semantics:
- Unset environment variables resolve to production defaults.
- TELEM_INTEL_HUD_MULTIRECT=0 / false / off explicitly disables Multi-Rect.
- TELEM_INTEL_HUD_WORKERS=<n> explicitly overrides worker count.
"""

from __future__ import annotations

import os
from typing import NamedTuple

# Validated production defaults (One Source of Truth)
DEFAULT_INTEL_HUD_MULTIRECT: bool = True
DEFAULT_INTEL_HUD_WORKERS: int = 4
DEFAULT_INTEL_HUD_PREFETCH: int = 8
DEFAULT_INTEL_HUD_TEXTURE_RING: int = 1
DEFAULT_INTEL_VP_RING: int = 8
DEFAULT_INTEL_ENCODE_ASYNC: int = 8


def get_intel_hud_multirect() -> bool:
    """Resolve Multi-Rect HUD upload setting.
    
    Semantics:
    - TELEM_INTEL_HUD_MULTIRECT unset -> production default True
    - TELEM_INTEL_HUD_MULTIRECT=0 / false / no / off -> explicit diagnostic override False
    - TELEM_INTEL_HUD_MULTIRECT=1 / true / yes / on -> True
    """
    raw = os.environ.get("TELEM_INTEL_HUD_MULTIRECT")
    if raw is None:
        return DEFAULT_INTEL_HUD_MULTIRECT
    val = raw.strip().lower()
    if val in ("0", "false", "no", "off"):
        return False
    if val in ("1", "true", "yes", "on"):
        return True
    return DEFAULT_INTEL_HUD_MULTIRECT


def get_intel_hud_workers() -> int:
    """Resolve HUD worker process count.
    
    Semantics:
    - TELEM_INTEL_HUD_WORKERS unset -> production default 4
    - explicit valid environment value -> override default
    """
    raw = os.environ.get("TELEM_INTEL_HUD_WORKERS")
    if raw is not None and raw.strip().isdigit():
        val = int(raw.strip())
        if val > 0:
            return val
    return DEFAULT_INTEL_HUD_WORKERS


def get_intel_hud_prefetch(workers: int | None = None) -> int:
    """Resolve HUD prefetch / in-flight queue depth."""
    raw = os.environ.get("TELEM_INTEL_HUD_PREFETCH")
    if raw is not None and raw.strip().isdigit():
        val = int(raw.strip())
        if val > 0:
            return val
    w = workers if workers is not None else get_intel_hud_workers()
    return max(DEFAULT_INTEL_HUD_PREFETCH, w * 2)


def get_intel_hud_texture_ring() -> int:
    """Resolve HUD texture ring depth."""
    raw = os.environ.get("TELEM_INTEL_HUD_RING_DEPTH")
    if raw is not None and raw.strip().isdigit():
        val = int(raw.strip())
        if val > 0:
            return val
    return DEFAULT_INTEL_HUD_TEXTURE_RING


def get_intel_vp_ring() -> int:
    """Resolve Video Processor ring depth."""
    raw = os.environ.get("TELEM_INTEL_VP_RING_DEPTH")
    if raw is not None and raw.strip().isdigit():
        val = int(raw.strip())
        if val > 0:
            return min(8, val)
    return DEFAULT_INTEL_VP_RING


def get_intel_encode_async() -> int:
    """Resolve oneVPL encode async depth."""
    raw = os.environ.get("TELEM_INTEL_MFX_ASYNC_DEPTH")
    if raw is not None and raw.strip().isdigit():
        val = int(raw.strip())
        if val > 0:
            return val
    return DEFAULT_INTEL_ENCODE_ASYNC


def get_intel_hw_decode() -> bool:
    """Resolve HEVC hardware decode setting."""
    raw = os.environ.get("TELEM_INTEL_HEVC_HW_DECODE")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


class IntelProductionConfig(NamedTuple):
    multirect: bool
    hud_workers: int
    hud_prefetch: int
    hud_texture_ring: int
    vp_ring: int
    encode_async: int
    hw_decode: bool
    preview: bool

    def format_log(self) -> str:
        mr_str = "TRUE" if self.multirect else "FALSE"
        hw_str = "TRUE" if self.hw_decode else "FALSE"
        prev_str = "TRUE" if self.preview else "FALSE"
        return (
            f"INTEL_PRODUCTION_CONFIG: "
            f"multirect={mr_str} "
            f"hud_workers={self.hud_workers} "
            f"hud_prefetch={self.hud_prefetch} "
            f"hud_texture_ring={self.hud_texture_ring} "
            f"vp_ring={self.vp_ring} "
            f"encode_async={self.encode_async} "
            f"hw_decode={hw_str} "
            f"preview={prev_str}"
        )


def resolve_intel_production_config(preview: bool = False) -> IntelProductionConfig:
    """Resolve effective Intel production configuration."""
    workers = get_intel_hud_workers()
    return IntelProductionConfig(
        multirect=get_intel_hud_multirect(),
        hud_workers=workers,
        hud_prefetch=get_intel_hud_prefetch(workers),
        hud_texture_ring=get_intel_hud_texture_ring(),
        vp_ring=get_intel_vp_ring(),
        encode_async=get_intel_encode_async(),
        hw_decode=get_intel_hw_decode(),
        preview=preview,
    )
