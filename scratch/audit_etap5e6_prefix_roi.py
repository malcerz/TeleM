"""ETAP 5E.6: measure prefix source ROI and alpha-composite parity."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.indicators.chart as chart_module
from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.chart import set_dynamic_layer_cache_enabled
from src.indicators.dispatcher import render_value_indicator


def _diff(a, b):
    delta = np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16))
    return int(delta.max()), int(np.any(delta != 0, axis=2).sum())


def main():
    layout, _regions, _anchor, *_ = setup()
    histories = WORKER_CACHE["_precomputed_chart_data"]
    captured = []
    original = chart_module.get_history_chart_prefix_background

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result[0].copy())
        return result

    chart_module.get_history_chart_prefix_background = capture
    try:
        for key in ("fit_cadence_text", "fit_heart_rate_text"):
            history = histories[key]
            cfg = layout["indicators"][key]
            for frame in (540, 1350, 2700, 4050):
                target = history.chart_start_dt + (history.chart_end_dt - history.chart_start_dt) * frame / (N - 1)
                visible = max(0, min(len(history) - 1, int(frame / (N - 1) * (len(history) - 1))))
                set_dynamic_layer_cache_enabled(True)
                render_value_indicator(
                    W, H, layout, "", key, history[visible],
                    "rpm" if key == "fit_cadence_text" else "BPM",
                    cfg.get("label", key), cfg_override=cfg,
                    formatted_val=f"{history[visible]:.0f}", history_data=history,
                    current_position=frame / (N - 1), target_dt=target,
                )
    finally:
        chart_module.get_history_chart_prefix_background = original

    result = {"samples": [], "summary": {}}
    for source in captured:
        alpha = source.getchannel("A")
        bbox = alpha.getbbox()
        base = Image.new("RGBA", source.size, (30, 40, 50, 120))
        full = base.copy()
        full.alpha_composite(source, (0, 0))
        crop = base.copy()
        if bbox:
            crop.alpha_composite(source.crop(bbox), (bbox[0], bbox[1]))
        old_paste = base.copy()
        old_paste.paste(source, (0, 0), source)
        result["samples"].append({
            "size": list(source.size),
            "alpha_bbox": list(bbox) if bbox else None,
            "alpha_bbox_area_ratio": ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / (source.width * source.height)) if bbox else 0.0,
            "full_alpha_vs_cropped_alpha": dict(zip(("max_diff", "different_pixels"), _diff(full, crop))),
            "old_masked_paste_vs_full_alpha": dict(zip(("max_diff", "different_pixels"), _diff(old_paste, full))),
        })
    if result["samples"]:
        result["summary"] = {
            "max_alpha_bbox_area_ratio": max(x["alpha_bbox_area_ratio"] for x in result["samples"]),
            "min_alpha_bbox_area_ratio": min(x["alpha_bbox_area_ratio"] for x in result["samples"]),
            "max_full_vs_crop_diff": max(x["full_alpha_vs_cropped_alpha"]["max_diff"] for x in result["samples"]),
            "max_old_paste_vs_full_alpha_diff": max(x["old_masked_paste_vs_full_alpha"]["max_diff"] for x in result["samples"]),
        }
    destination = ROOT / "scratch" / "etap5e6_prefix_roi_audit.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
