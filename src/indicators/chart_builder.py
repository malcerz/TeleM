"""Chart data builder — pre-compute chart history for all chart-type indicators.

Extracted from ``overlay_renderer.py``.
"""

from __future__ import annotations

import time
from typing import Any, Callable


def build_chart_data(
    layout: dict[str, Any],
    get_samples_fn: Callable[[str], tuple[list, list, list]],
    resolve_samples_fn: Callable[[str], list],
) -> dict[str, list[float]]:
    """Build chart history data for all chart-type indicators in a layout.

    This function is shared by the preview (hud_tuner_app.py) and the
    render pipeline (ffmpeg_pipeline.py) to eliminate code duplication
    and ensure identical behaviour in both paths.

    Args:
        layout: HUD layout dict with ``indicators`` key.
        get_samples_fn: ``(source) -> (speed, track, alt)`` triple.
        resolve_samples_fn: ``(field_name) -> list`` for non-speed/alt/dist.

    Returns:
        ``{indicator_key: [values]}`` for every enabled chart indicator.
    """
    chart_data: dict[str, list[float]] = {}
    for ind_key, ind_cfg in layout.get("indicators", {}).items():
        if ind_cfg.get("form") != "chart" or not ind_cfg.get("enabled", True):
            continue
        src = ind_cfg.get("source", "gpmf")
        if "speed" in ind_key:
            spd_s, _, _ = get_samples_fn(src)
            vals = [v for _, v in spd_s] if spd_s else []
        elif "dist" in ind_key:
            _, trk_s, _ = get_samples_fn(src)
            vals = [v for _, v in trk_s] if trk_s else []
        elif "alt" in ind_key:
            _, _, alt_s = get_samples_fn(src)
            vals = [v for _, v in alt_s] if alt_s else []
        elif "power" in ind_key:
            vals = [v for _, v in resolve_samples_fn("power")]
        elif "hr" in ind_key:
            vals = [v for _, v in resolve_samples_fn("hr")]
        elif "cad" in ind_key:
            vals = [v for _, v in resolve_samples_fn("cad")]
        elif "atemp" in ind_key:
            vals = [v for _, v in resolve_samples_fn("atemp")]
        elif "battery" in ind_key:
            vals = [v for _, v in resolve_samples_fn("battery")]
        elif "iso" in ind_key:
            vals = [v for _, v in resolve_samples_fn("iso")]
        elif "exposure" in ind_key:
            vals = [v for _, v in resolve_samples_fn("exposure")]
        elif "temp" in ind_key and "atemp" not in ind_key:
            vals = [v for _, v in resolve_samples_fn("temperature")]
        else:
            # Dla kluczy typu fit_{field_name}_text — wyciągnij field_name
            # i rozwiąż przez resolve_samples_fn
            if ind_key.startswith("fit_") and ind_key.endswith("_text"):
                field_name = ind_key[4:-5]
                vals = [v for _, v in resolve_samples_fn(field_name)]
            else:
                vals = []
        if vals and len(vals) >= 2:
            chart_data[ind_key] = vals
    return chart_data
