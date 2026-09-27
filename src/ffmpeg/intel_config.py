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


from src.ffmpeg.encoder_profile import EncoderProfile, DEFAULT_ENCODER_PROFILE, resolve_encoder_profile

# Intel oneVPL TargetUsage symbolic mapping
MFX_TARGETUSAGE_BEST_QUALITY: int = 1
MFX_TARGETUSAGE_BALANCED: int = 4
MFX_TARGETUSAGE_BEST_SPEED: int = 7

TARGET_USAGE_SYMBOLS: dict[int, str] = {
    1: "BEST_QUALITY",
    2: "QUALITY_2",
    3: "QUALITY_3",
    4: "BALANCED",
    5: "SPEED_5",
    6: "SPEED_6",
    7: "BEST_SPEED",
}

# Production baseline TargetUsages (Mandatory: BALANCED MUST BE CURRENT PRODUCTION)
CURRENT_H264_TARGET_USAGE: int = 7
CURRENT_HEVC_TARGET_USAGE: int = 7
CURRENT_AV1_TARGET_USAGE: int = 7

# Centralized Codec + Profile -> TargetUsage resolver map
INTEL_CODEC_PROFILE_TARGET_USAGE: dict[str, dict[EncoderProfile, int]] = {
    "h264": {
        EncoderProfile.FAST: MFX_TARGETUSAGE_BEST_SPEED,      # 7
        EncoderProfile.BALANCED: MFX_TARGETUSAGE_BALANCED,    # 4
        EncoderProfile.QUALITY: MFX_TARGETUSAGE_BEST_QUALITY,  # 1
    },
    "hevc": {
        EncoderProfile.FAST: MFX_TARGETUSAGE_BEST_SPEED,      # 7
        EncoderProfile.BALANCED: MFX_TARGETUSAGE_BALANCED,    # 4
        EncoderProfile.QUALITY: MFX_TARGETUSAGE_BEST_QUALITY,  # 1
    },
    "av1": {
        EncoderProfile.FAST: MFX_TARGETUSAGE_BEST_SPEED,      # 7
        EncoderProfile.BALANCED: MFX_TARGETUSAGE_BALANCED,    # 4
        EncoderProfile.QUALITY: MFX_TARGETUSAGE_BEST_QUALITY,  # 1
    },
}


def resolve_intel_target_usage(codec: str, profile: str | EncoderProfile | None) -> int:
    """Resolve effective oneVPL TargetUsage for a given Intel codec and profile.
    
    Environment variable TELEM_INTEL_TARGET_USAGE provides an immediate diagnostic override.
    Unset environment falls back to the canonical codec-profile mapping.
    """
    raw_env = os.environ.get("TELEM_INTEL_TARGET_USAGE")
    if raw_env is not None and raw_env.strip().isdigit():
        val = int(raw_env.strip())
        if 1 <= val <= 7:
            return val
    
    c = str(codec).strip().lower()
    if c in ("h264", "h264_qsv", "avc", "h264_nv12"):
        c_key = "h264"
    elif c in ("hevc", "hevc_qsv", "h265"):
        c_key = "hevc"
    else:
        c_key = "av1"
    
    prof_enum = resolve_encoder_profile(profile)
    return INTEL_CODEC_PROFILE_TARGET_USAGE.get(c_key, {}).get(prof_enum, 7)


class IntelEncoderEffectiveConfig(NamedTuple):
    profile: EncoderProfile
    codec: str
    target_usage: int
    target_usage_name: str
    bitrate: str
    resolution: str
    bit_depth: int
    hdr: str

    def format_log(self) -> str:
        return (
            f"INTEL_ENCODER_PROFILE: "
            f"profile={self.profile.value} "
            f"codec={self.codec.lower()} "
            f"target_usage={self.target_usage} ({self.target_usage_name}) "
            f"bitrate={self.bitrate} "
            f"resolution={self.resolution} "
            f"bit_depth={self.bit_depth} "
            f"hdr={self.hdr}"
        )


def resolve_intel_encoder_config(
    codec: str,
    profile: str | EncoderProfile | None,
    bitrate: str = "40M",
    width: int = 3840,
    height: int = 2160,
) -> IntelEncoderEffectiveConfig:
    """Resolve full effective Intel encoder configuration."""
    c = str(codec).strip().lower()
    if c in ("h264", "h264_qsv", "avc", "h264_nv12"):
        norm_codec = "h264"
        bit_depth = 8
        hdr = "NO"
    elif c in ("hevc", "hevc_qsv", "h265"):
        norm_codec = "hevc"
        bit_depth = 10
        hdr = "YES"
    else:
        norm_codec = "av1"
        bit_depth = 10
        hdr = "YES"

    prof = resolve_encoder_profile(profile)
    tu = resolve_intel_target_usage(norm_codec, prof)
    tu_name = TARGET_USAGE_SYMBOLS.get(tu, f"TU_{tu}")
    res_str = f"{width}x{height}"
    b_str = str(bitrate).strip() if bitrate else "40M"

    return IntelEncoderEffectiveConfig(
        profile=prof,
        codec=norm_codec,
        target_usage=tu,
        target_usage_name=tu_name,
        bitrate=b_str,
        resolution=res_str,
        bit_depth=bit_depth,
        hdr=hdr,
    )
