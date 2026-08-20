"""ETAP 5E.5 audit: transparent ROI parity and ready-raster transfer cost."""

from __future__ import annotations

import json
import statistics
import sys
import time
from bisect import bisect_right
from datetime import timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.dispatcher import render_value_indicator
from src.indicators.rotated_paste import composite_final, rotated_paste


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def summary(values: list[float]) -> dict[str, float]:
    return {
        "avg_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p95_ms": percentile(values, 0.95),
    }


def diff_stats(left: Image.Image, right: Image.Image) -> dict[str, int]:
    # ImageChops.getbbox on RGBA can ignore RGB-only differences when alpha is
    # unchanged.  Compare all four channels explicitly for pixel-exact audit.
    delta = np.abs(np.asarray(left, dtype=np.int16) - np.asarray(right, dtype=np.int16))
    return {
        "max_diff": int(delta.max()),
        "different_pixels": int(np.any(delta != 0, axis=2).sum()),
    }


def source_analysis(source: Image.Image) -> dict:
    alpha = source.getchannel("A")
    alpha_bbox = alpha.getbbox()
    alpha_extrema = alpha.getextrema()
    arr = np.asarray(source, dtype=np.uint8)
    transparent = arr[..., 3] == 0
    dirty = transparent & np.any(arr[..., :3] != 0, axis=2)
    full = source.width * source.height
    active = 0 if alpha_bbox is None else (alpha_bbox[2] - alpha_bbox[0]) * (alpha_bbox[3] - alpha_bbox[1])
    return {
        "size": [source.width, source.height],
        "getbbox": list(source.getbbox()) if source.getbbox() else None,
        "alpha_bbox": list(alpha_bbox) if alpha_bbox else None,
        "alpha_min": int(alpha_extrema[0]),
        "alpha_max": int(alpha_extrema[1]),
        "active_bbox_area_ratio": active / full if full else 0.0,
        "alpha_has_transparent_pixels": alpha_extrema[0] == 0,
        "transparent_pixels_with_nonzero_rgb": int(dirty.sum()),
        "max_nonzero_rgb_under_alpha_zero": int(arr[dirty, :3].max()) if dirty.any() else 0,
    }


def get_sources(layout, key, count=96):
    histories = WORKER_CACHE["_precomputed_chart_data"]
    history = histories[key]
    cfg = layout["indicators"][key]
    unit = "rpm" if key == "fit_cadence_text" else "BPM"
    label = cfg.get("label", key)
    region = (46, 754, 0, 248, 1828, 326)
    sources = []
    for i in range(count):
        frame = (i * (N - 1)) // max(1, count - 1)
        target = history.chart_start_dt + timedelta(seconds=frame / FPS)
        visible = bisect_right(history.timestamps, target) - 1
        value = history[visible] if visible >= 0 else 0.0
        source, rx, ry, _extra = render_value_indicator(
            W, H, layout, "", key, value, unit, label,
            cfg_override=cfg, formatted_val=f"{value:.0f}",
            history_data=history, current_position=frame / (N - 1),
            target_dt=target,
        )
        atlas_x = region[2]
        atlas_y = region[3]
        x = rx - (region[0] - atlas_x)
        y = ry - (region[1] - atlas_y)
        sources.append({"image": source, "x": x, "y": y, "frame": frame})
    return sources


def benchmark(sources, repeats=2000):
    methods = {
        "current_rotated_paste": [],
        "deployed_transparent_roi_fast_paste": [],
        "full_plain_paste": [],
        "cropped_plain_paste": [],
        "alpha_composite_reference": [],
    }
    prepared = []
    for item in sources:
        source = item["image"]
        alpha_bbox = source.getchannel("A").getbbox()
        prepared.append((source, item["x"], item["y"], alpha_bbox))

    for index in range(repeats):
        source, x, y, alpha_bbox = prepared[index % len(prepared)]
        for name in methods:
            target = Image.new("RGBA", (1900, 762), (0, 0, 0, 0))
            started = time.perf_counter()
            if name == "current_rotated_paste":
                rotated_paste(target, source, x + source.width // 2, y + source.height // 2, 0, prior_bboxes=[], cache_key="stage5e5")
            elif name == "deployed_transparent_roi_fast_paste":
                rotated_paste(target, source, x + source.width // 2, y + source.height // 2, 0, prior_bboxes=[], cache_key="stage5e5_deployed", destination_proven_empty=True)
            elif name == "full_plain_paste":
                target.paste(source, (x, y))
            elif name == "cropped_plain_paste":
                if alpha_bbox is not None:
                    cropped = source.crop(alpha_bbox)
                    target.paste(cropped, (x + alpha_bbox[0], y + alpha_bbox[1]))
            else:
                target.alpha_composite(source, (x, y))
            methods[name].append((time.perf_counter() - started) * 1000.0)
    return {name: summary(values) for name, values in methods.items()}


def parity(sources):
    result = {}
    for key, rotation in (("rotation_0", 0), ("rotation_180", 180), ("rotation_90", 90), ("rotation_270", 270)):
        values = []
        for item in sources:
            source = item["image"]
            if rotation == 90:
                rotated = source.transpose(Image.Transpose.ROTATE_90)
            elif rotation == 180:
                rotated = source.transpose(Image.Transpose.ROTATE_180)
            elif rotation == 270:
                rotated = source.transpose(Image.Transpose.ROTATE_270)
            else:
                rotated = source
            reference = Image.new("RGBA", rotated.size, (0, 0, 0, 0))
            reference.alpha_composite(rotated, (0, 0))
            plain = Image.new("RGBA", rotated.size, (0, 0, 0, 0))
            plain.paste(rotated, (0, 0))
            values.append(diff_stats(reference, plain))
        result[key] = {
            "max_diff": max(v["max_diff"] for v in values),
            "different_pixels": max(v["different_pixels"] for v in values),
            "min_different_pixels": min(v["different_pixels"] for v in values),
            "samples": len(values),
        }
    return result


def main():
    layout, _regions, _anchor, *_ = setup()
    output = {"charts": {}, "static_geometry": {}}
    output["static_geometry"] = {
        "cadence": [92, 796, 584, 264],
        "gauge": [766, 814, 324, 324],
        "heart_rate": [1244, 796, 584, 264],
        "cadence_gauge_intersects": False,
        "cadence_hr_intersects": False,
        "gauge_hr_intersects": False,
    }
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        sources = get_sources(layout, key)
        output["charts"][key] = {
            "raster_analysis": source_analysis(sources[len(sources) // 2]["image"]),
            "raster_analysis_first": source_analysis(sources[0]["image"]),
            "raster_analysis_last": source_analysis(sources[-1]["image"]),
            "transparent_roi_parity": parity(sources),
            "benchmark_2000": benchmark(sources),
        }
    destination = ROOT / "scratch" / "etap5e5_transparent_roi_audit.json"
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
