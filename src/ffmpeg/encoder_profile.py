"""Shared encoder quality-profile model and resolver.

Defines the single source of truth for encoder profiles across all backends:
- FAST: prioritize encode speed / lower encoder complexity (TargetUsage = 7)
- BALANCED: balanced quality and speed (TargetUsage = 4, default for new projects)
- QUALITY: prioritize encoding quality / higher encoder complexity (TargetUsage = 1)

Legacy Migration:
- Projects/presets missing 'encoder_profile' default to FAST (TargetUsage = 7)
  to preserve exact historical Intel production behavior.

The architecture is generic so NVIDIA and AMD mappings can be added later
without changing project/UI schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class EncoderProfile(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    QUALITY = "quality"

    @classmethod
    def from_str(cls, value: Any, default: "EncoderProfile" | None = None) -> "EncoderProfile":
        """Parse string, enum or None into a validated EncoderProfile.
        
        Handles Polish GUI labels, English names, casing, whitespace, None, and
        unknown values with deterministic fallback.
        """
        fallback = default if default is not None else cls.BALANCED
        if value is None:
            return fallback
        if isinstance(value, cls):
            return value
        s = str(value).strip().lower()
        if s in ("fast", "szybki", "speed", "best_speed"):
            return cls.FAST
        if s in ("quality", "jakość", "jakosc", "best_quality"):
            return cls.QUALITY
        if s in ("balanced", "zbalansowany", "default", "standard"):
            return cls.BALANCED
        return fallback

    @property
    def display_name(self) -> str:
        """Polish GUI label for the profile."""
        if self == EncoderProfile.FAST:
            return "Szybki"
        if self == EncoderProfile.QUALITY:
            return "Jakość"
        return "Zbalansowany"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Return list of (internal_value, display_name) for UI combo boxes."""
        return [
            (cls.FAST.value, "Szybki"),
            (cls.BALANCED.value, "Zbalansowany"),
            (cls.QUALITY.value, "Jakość"),
        ]


DEFAULT_ENCODER_PROFILE: EncoderProfile = EncoderProfile.BALANCED
LEGACY_DEFAULT_ENCODER_PROFILE: EncoderProfile = EncoderProfile.FAST


def resolve_encoder_profile(value: Any, default: EncoderProfile = DEFAULT_ENCODER_PROFILE) -> EncoderProfile:
    """Convenience helper to resolve any input into an EncoderProfile."""
    return EncoderProfile.from_str(value, default=default)
