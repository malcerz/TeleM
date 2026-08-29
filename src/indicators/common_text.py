"""ETAP 5Z common-text eligibility contract.

This module deliberately contains the conservative eligibility decision only.
The canonical AMD layout has no qualifying high-cost simple-text widget, so a
candidate request must fall back to the reference renderer until an exact
implementation is proven.
"""

from __future__ import annotations

from typing import Any


COMMON_TEXT_AUDIT_KEYS = (
    "alt_text",
    "speed_text",
    "fit_distance_text",
    "fit_heart_rate_text",
    "fit_cadence_text",
    "fit_gopro_battery_text",
    "iso_text",
    "exposure_text",
    "temp_text",
)

_SIMPLE_TEXT_KEYS = frozenset(("iso_text", "exposure_text", "temp_text"))


def classify_common_text_widget(key: str, cfg: dict[str, Any] | None) -> str:
    """Return ``ELIGIBLE EXACT``, ``CONDITIONAL`` or ``NOT ELIGIBLE``.

    Only the three canonical ``form=text`` telemetry labels are candidates;
    all structured renderers are intentionally excluded from ETAP 5Z.
    """
    if not cfg or key not in COMMON_TEXT_AUDIT_KEYS:
        return "NOT ELIGIBLE"
    if cfg.get("form", "text") != "text":
        return "NOT ELIGIBLE"
    if key not in _SIMPLE_TEXT_KEYS:
        return "CONDITIONAL"
    unsupported = (
        cfg.get("rotation", 0) not in (0, "0")
        or cfg.get("icon", "none") not in (None, "", "none")
    )
    return "CONDITIONAL" if unsupported else "ELIGIBLE EXACT"


def common_text_fast_path_is_proven() -> bool:
    """The 5Z candidate remains disabled until exact parity is demonstrated."""
    return False
