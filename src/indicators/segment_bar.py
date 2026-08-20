"""Segment-bar indicator rendering (backward-compatibility shim).

Deprecated: All bar indicator rendering (both ruler and segments) is now
consolidated in ``src.indicators.bar``. This module exists to preserve
backward compatibility for existing imports and external layouts.
"""

from __future__ import annotations

from typing import Any
from src.indicators.bar import _render_bar_indicator


def _render_segment_bar_indicator(*args: Any, **kwargs: Any) -> Any:
    """Compatibility wrapper redirecting legacy segment_bar calls to bar.py."""
    cfg = kwargs.get("cfg")
    if isinstance(cfg, dict) and "bar_style" not in cfg:
        cfg["bar_style"] = "segments"
    return _render_bar_indicator(*args, **kwargs)
