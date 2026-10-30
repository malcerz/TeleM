"""CPU (libx265) encoder profile and rate-control resolution.

Single source of truth for the CPU backend only; AMD, Intel and NVIDIA keep
their own mappings.

Profiles reuse the shared ``EncoderProfile`` labels (Szybki / Zbalansowany /
Jakość).  Rate control is explicit and never mixed:

* ``abr`` - average bitrate (``-b:v``), no ``-crf``.  This is an *average*
  target, not CBR and not a hard cap: no ``-maxrate``/``-bufsize`` is set, so
  short clips may deviate from the requested value (measured in CPU P0.3).
* ``crf`` - constant quality (``-crf``), no ``-b:v``.
"""

from __future__ import annotations

import os
import re
from typing import Any

from src.ffmpeg.encoder_profile import EncoderProfile

CPU_PROFILE_PRESETS: dict[EncoderProfile, str] = {
    EncoderProfile.FAST: "ultrafast",
    EncoderProfile.BALANCED: "faster",
    EncoderProfile.QUALITY: "medium",
}

RATE_MODE_ABR = "abr"
RATE_MODE_CRF = "crf"
DEFAULT_RATE_MODE = RATE_MODE_ABR
DEFAULT_CRF = 24
# Projects/presets saved before CPU P0.3 carry no cpu_* keys.  They were encoded
# with ``-preset medium -crf 24``; that mode is kept for them (explicit migration
# rule, never a silent switch to the new ABR / faster defaults).
LEGACY_PROFILE = EncoderProfile.QUALITY
LEGACY_RATE_MODE = RATE_MODE_CRF
_VALID_PRESETS = {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"}


def resolve_cpu_preset(profile: Any) -> str:
    """Map a profile (enum, GUI label or string) to a libx265 preset.

    ``TELEM_CPU_X265_PRESET`` overrides it for measurements only.
    """
    override = os.environ.get("TELEM_CPU_X265_PRESET", "").strip().lower()
    if override in _VALID_PRESETS:
        return override
    return CPU_PROFILE_PRESETS[EncoderProfile.from_str(profile)]


def resolve_rate_mode(value: Any) -> str:
    s = str(value or "").strip().lower()
    if s in ("crf", "quality", "jakosc", "jakość"):
        return RATE_MODE_CRF
    return RATE_MODE_ABR


def parse_bitrate_kbps(value: Any) -> int | None:
    """Parse '40M', '16384k', '16.5M', '40000000' into kb/s; None if invalid."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*([kKmM]?)(?:[bB]/?[sS]?)?\s*", str(value or ""))
    if not m:
        return None
    num = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    kbps = num * 1000 if unit == "m" else num if unit == "k" else num / 1000.0
    return int(round(kbps)) if kbps > 0 else None


def build_cpu_x265_args(profile: Any, rate_mode: Any, video_bitrate: Any) -> tuple[list[str], str]:
    """Return (ffmpeg video-codec args, human-readable description).

    ABR with an unparsable bitrate falls back to CRF and says so in the
    description, never silently.
    """
    preset = resolve_cpu_preset(profile)
    mode = resolve_rate_mode(rate_mode)
    args = ["-c:v", "libx265", "-preset", preset]
    extra = os.environ.get("TELEM_CPU_X265_PARAMS", "").strip()  # measurement only
    if extra:
        args += ["-x265-params", extra]
    if mode == RATE_MODE_ABR:
        kbps = parse_bitrate_kbps(video_bitrate)
        if kbps is not None:
            args += ["-b:v", f"{kbps}k"]
            return args, f"preset={preset} rate_control=ABR avg_bitrate={kbps}kbps (average, not CBR, no hard cap)"
        args += ["-crf", str(DEFAULT_CRF)]
        return args, (f"preset={preset} rate_control=CRF{DEFAULT_CRF} "
                      f"(FALLBACK: bitrate {video_bitrate!r} not parseable)")
    args += ["-crf", str(DEFAULT_CRF)]
    return args, f"preset={preset} rate_control=CRF{DEFAULT_CRF} (bitrate ignored)"


def settings_to_cpu_choice(settings: dict[str, Any] | None) -> tuple[str, str, bool]:
    """Resolve saved export settings to (profile value, rate mode, is_legacy).

    ``is_legacy`` is True when the settings predate CPU P0.3 (neither
    ``cpu_profile`` nor ``cpu_rate_mode`` stored): the previous encoding
    (medium + CRF 24) is kept.  A single missing key also falls back to its
    legacy value instead of the new default.
    """
    settings = settings or {}
    has_profile = settings.get("cpu_profile") is not None
    has_mode = settings.get("cpu_rate_mode") is not None
    if not has_profile and not has_mode:
        return LEGACY_PROFILE.value, LEGACY_RATE_MODE, True
    profile = (EncoderProfile.from_str(settings["cpu_profile"], default=LEGACY_PROFILE)
               if has_profile else LEGACY_PROFILE)
    mode = resolve_rate_mode(settings["cpu_rate_mode"]) if has_mode else LEGACY_RATE_MODE
    return profile.value, mode, False
