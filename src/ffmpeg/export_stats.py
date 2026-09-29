"""Runtime encoder statistics shared by live progress and export completion."""

from __future__ import annotations

import re
from typing import Any


def _numeric(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def is_av1_quality_metric(stats: dict[str, Any] | None) -> bool:
    stats = stats or {}
    return bool(stats.get("is_av1")) or stats.get("codec") == "av1" or stats.get("quant_metric") == "base_q_idx"


def live_render_avg_qp(hud_state: dict[str, Any] | None) -> float | None:
    """Read the classical encoder average published by the live render HUD."""
    hud_state = hud_state or {}
    if is_av1_quality_metric(hud_state):
        return None
    for key in ("avg_qp", "qp_avg", "mean_qp"):
        value = _numeric(hud_state.get(key))
        if value is not None:
            return value
    match = re.search(
        r"\bQP\s+avg\s*:\s*([0-9]+(?:\.[0-9]+)?)",
        str(hud_state.get("compression_text", "")),
        re.IGNORECASE,
    )
    return _numeric(match.group(1)) if match else None


def resolve_render_avg_qp(
    stats: dict[str, Any] | None,
    *,
    generation_id: int,
    live_qp: Any = None,
    live_generation_id: int = 0,
) -> float | None:
    """Resolve only classical QP and use live fallback only for this generation."""
    stats = stats or {}
    try:
        stats_generation = int(stats.get("generation_id", 0) or 0)
    except (TypeError, ValueError):
        stats_generation = 0
    if stats_generation > 0 and generation_id > 0 and stats_generation != generation_id:
        return None
    if is_av1_quality_metric(stats):
        return None
    candidates = (
        stats.get("avg_qp"),
        stats.get("qp_avg"),
        (stats.get("encoder_stats") or {}).get("qp_avg"),
        (stats.get("amf_stats") or {}).get("avg_qp"),
    )
    for candidate in candidates:
        value = _numeric(candidate)
        if value is not None:
            return value
    if generation_id > 0 and generation_id == live_generation_id:
        return _numeric(live_qp)
    return None
