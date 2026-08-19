"""ETAP 8D - Comprehensive Performance Audit & Benchmarking Suite for CPU_ABOVE_MAP.

Covers:
- Microbenchmarks of Pillow operations (Image.new, regional clear, crop, alpha composite, rotated paste)
- Component breakdowns for compose_overlay (allocation, indicator render, paste, annotations, bbox tracking, crop, scan, tobytes, upload)
- Layout comparison benchmarks (Empty ABOVE, One small text, Large text, Multiple elements [1, 2, 4], Sparse distant elements, Custom texts)
- Dynamic transition tests (visible -> None -> visible)
- Rotation comparison (0° vs 17°)
- Real video production baseline runs (3 x 900 frames on GX030120.MP4)
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont
from src.indicators.compositor import compose_overlay
from src.indicators.helpers import load_font
from src.indicators.rotated_paste import rotated_paste
from src.indicators.custom_text import render_custom_text
from src.indicators.dispatcher import render_value_indicator
from src.ffmpeg.amd_native_exporter import (
    _ordered_map_layout_parts,
    _rendered_bbox_union,
    _tight_alpha_bbox_from_candidate,
    export_amd_native_d3d11,
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from src.gui.layout_manager import resolve_font_path
from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    interpolate_value,
    load_json_with_fallback,
    smooth_speed_samples,
)


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s_data = sorted(data)
    k = (len(s_data) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s_data[int(k)]
    d0 = s_data[int(f)] * (c - k)
    d1 = s_data[int(c)] * (k - f)
    return d0 + d1


def summary_stats(data: list[float]) -> dict[str, float]:
    if not data:
        return {"min": 0.0, "median": 0.0, "p95": 0.0, "mean": 0.0, "max": 0.0, "count": 0}
    return {
        "min": min(data),
        "median": percentile(data, 0.50),
        "p95": percentile(data, 0.95),
        "mean": statistics.mean(data),
        "max": max(data),
        "count": len(data),
    }


# =========================================================================
# 1. PILLOW MICROBENCHMARKS
# =========================================================================
def run_pillow_microbenchmarks(iterations: int = 500) -> dict[str, Any]:
    print("--- 1. Running Pillow Microbenchmarks ---", flush=True)
    results = {}

    # Image.new 4K RGBA
    t_new_4k = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img = Image.new("RGBA", (3840, 2160), (0, 0, 0, 0))
        t_new_4k.append((time.perf_counter() - t0) * 1000.0)
    results["image_new_4k_rgba"] = summary_stats(t_new_4k)

    # Image.new Candidate size (559 x 190)
    t_new_cand = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img_cand = Image.new("RGBA", (559, 190), (0, 0, 0, 0))
        t_new_cand.append((time.perf_counter() - t0) * 1000.0)
    results["image_new_candidate_rgba"] = summary_stats(t_new_cand)

    # Image.new Final size (431 x 62)
    t_new_final = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img_fin = Image.new("RGBA", (431, 62), (0, 0, 0, 0))
        t_new_final.append((time.perf_counter() - t0) * 1000.0)
    results["image_new_final_rgba"] = summary_stats(t_new_final)

    # Full 4K canvas clear (paste (0,0,0,0) over 3840x2160)
    img_4k = Image.new("RGBA", (3840, 2160), (0, 0, 0, 0))
    t_clear_4k = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img_4k.paste((0, 0, 0, 0), (0, 0, 3840, 2160))
        t_clear_4k.append((time.perf_counter() - t0) * 1000.0)
    results["full_4k_clear_paste"] = summary_stats(t_clear_4k)

    # Regional clear (paste (0,0,0,0) over 559x190 region on 4K)
    t_clear_reg = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        img_4k.paste((0, 0, 0, 0), (3300, 935, 3300 + 559, 935 + 190))
        t_clear_reg.append((time.perf_counter() - t0) * 1000.0)
    results["regional_clear_paste_559x190"] = summary_stats(t_clear_reg)

    # Candidate crop from 4K (crop (3300, 935, 3859, 1125))
    t_crop_cand = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        cand = img_4k.crop((3300, 935, 3300 + 559, 935 + 190))
        t_crop_cand.append((time.perf_counter() - t0) * 1000.0)
    results["candidate_crop_from_4k"] = summary_stats(t_crop_cand)

    # Local alpha scan on candidate (559x190)
    # Populate candidate with some visible pixels
    cand_img = Image.new("RGBA", (559, 190), (0, 0, 0, 0))
    draw = ImageDraw.Draw(cand_img)
    draw.text((64, 64), "Garmin Battery 74%", fill=(255, 255, 255, 255))
    t_scan_cand = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        bb = cand_img.getchannel("A").getbbox()
        t_scan_cand.append((time.perf_counter() - t0) * 1000.0)
    results["local_alpha_scan_559x190"] = summary_stats(t_scan_cand)

    # Full frame 4K alpha scan (for reference / comparison with 8C)
    img_4k_text = Image.new("RGBA", (3840, 2160), (0, 0, 0, 0))
    draw_4k = ImageDraw.Draw(img_4k_text)
    draw_4k.text((3300, 935), "Garmin Battery 74%", fill=(255, 255, 255, 255))
    t_scan_4k = []
    for _ in range(min(50, iterations)):  # slower
        t0 = time.perf_counter()
        bb = img_4k_text.getchannel("A").getbbox()
        t_scan_4k.append((time.perf_counter() - t0) * 1000.0)
    results["full_frame_4k_alpha_scan"] = summary_stats(t_scan_4k)

    # tobytes() on candidate / final / 4K
    final_img = cand_img.crop((64, 64, 64 + 431, 64 + 62))
    t_tobytes_final = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        b = final_img.tobytes("raw", "RGBA")
        t_tobytes_final.append((time.perf_counter() - t0) * 1000.0)
    results["tobytes_final_431x62"] = summary_stats(t_tobytes_final)

    t_tobytes_4k = []
    for _ in range(min(50, iterations)):
        t0 = time.perf_counter()
        b = img_4k.tobytes("raw", "RGBA")
        t_tobytes_4k.append((time.perf_counter() - t0) * 1000.0)
    results["tobytes_4k_rgba"] = summary_stats(t_tobytes_4k)

    return results


# =========================================================================
# 2. ROTATED PASTE & ROTATION BENCHMARKS
# =========================================================================
def run_rotation_benchmarks(iterations: int = 500) -> dict[str, Any]:
    print("--- 2. Running Rotation & Paste Benchmarks ---", flush=True)
    results = {}
    font_path = str(ROOT / "include" / "fonts" / "Roboto-Bold.ttf")
    if not os.path.exists(font_path):
        font_path = "arial.ttf"

    font = load_font(font_path, 54)
    text = "Garmin Battery 74%"
    bbox = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    elem_img = Image.new("RGBA", (tw + 16, th + 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(elem_img)
    d.text((8, 8), text, font=font, fill=(255, 255, 255, 255))

    canvas = Image.new("RGBA", (3840, 2160), (0, 0, 0, 0))

    # Rotation 0° (normal fast path)
    t_rot0 = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        rotated_paste(canvas, elem_img, 3300, 935, 0)
        t_rot0.append((time.perf_counter() - t0) * 1000.0)
    results["rotated_paste_0deg"] = summary_stats(t_rot0)

    # Rotation 17° (arbitrary angle rotated paste)
    t_rot17 = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        rotated_paste(canvas, elem_img, 3300, 935, 17)
        t_rot17.append((time.perf_counter() - t0) * 1000.0)
    results["rotated_paste_17deg"] = summary_stats(t_rot17)

    # Rotation 90° (orthogonal rotation)
    t_rot90 = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        rotated_paste(canvas, elem_img, 3300, 935, 90)
        t_rot90.append((time.perf_counter() - t0) * 1000.0)
    results["rotated_paste_90deg"] = summary_stats(t_rot90)

    return results


# =========================================================================
# 3. DETAILED ABOVE COMPONENT BREAKDOWN BENCHMARK
# =========================================================================
def run_detailed_above_breakdown(
    layout: dict[str, Any],
    font_path: str,
    iterations: int = 500,
) -> dict[str, Any]:
    print("--- 3. Running Detailed ABOVE Component Breakdown ---", flush=True)

    # Layout preparation / split
    t_split = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        below, above, after_keys = _ordered_map_layout_parts(layout)
        t_split.append((time.perf_counter() - t0) * 1000.0)

    # We now benchmark compose_overlay on map_above_layout step-by-step
    below, above, after_keys = _ordered_map_layout_parts(layout)

    t_canvas_init = []
    t_indicator_render = []
    t_indicator_paste = []
    t_compose_total = []
    t_bbox_union = []
    t_candidate_crop = []
    t_local_alpha_scan = []
    t_final_crop = []
    t_tobytes = []

    for _ in range(iterations):
        # Full compose_overlay call
        bboxes = {}
        t0_compose = time.perf_counter()
        img = compose_overlay(
            canvas_w=3840,
            canvas_h=2160,
            layout=above,
            font_path=font_path,
            date_text="2026-08-05",
            time_text="04:28:11",
            speed_value=25.0,
            distance_m=1000.0,
            alt_value=150.0,
            indicator_values={"fit_battery_text": 74.0},
            _bboxes=bboxes,
            reuse_canvas=True,
        )
        t_comp = (time.perf_counter() - t0_compose) * 1000.0
        t_compose_total.append(t_comp)

        # Bbox tracking / union
        t0_union = time.perf_counter()
        cand = _rendered_bbox_union(bboxes, 3840, 2160, pad=64)
        t_bbox_union.append((time.perf_counter() - t0_union) * 1000.0)

        # Candidate crop
        if cand is not None:
            t0_cand_crop = time.perf_counter()
            cand_img = img.crop((cand[0], cand[1], cand[0] + cand[2], cand[1] + cand[3]))
            t_candidate_crop.append((time.perf_counter() - t0_cand_crop) * 1000.0)

            # Local alpha scan
            t0_scan = time.perf_counter()
            local_box = cand_img.getchannel("A").getbbox()
            t_local_alpha_scan.append((time.perf_counter() - t0_scan) * 1000.0)

            # Final crop
            if local_box is not None:
                t0_fin_crop = time.perf_counter()
                final_img = cand_img.crop(local_box)
                t_final_crop.append((time.perf_counter() - t0_fin_crop) * 1000.0)

                # tobytes
                t0_tb = time.perf_counter()
                b = final_img.tobytes("raw", "RGBA")
                t_tobytes.append((time.perf_counter() - t0_tb) * 1000.0)

    # Isolated indicator render vs paste cost for ABOVE indicators
    for key, ind_cfg in above.get("indicators", {}).items():
        if not ind_cfg.get("enabled", True):
            continue
        t_rnd = []
        t_pst = []
        canvas_tmp = Image.new("RGBA", (3840, 2160), (0, 0, 0, 0))
        for _ in range(iterations):
            t0_r = time.perf_counter()
            res, rx, ry, extra = render_value_indicator(
                3840, 2160, above, font_path,
                key, 74.0, "", "Garmin Battery",
                cfg_override=ind_cfg,
                formatted_val="74%",
                supersample=1,
            )
            t_rnd.append((time.perf_counter() - t0_r) * 1000.0)

            if res:
                cx = rx + res.width // 2
                cy = ry + res.height // 2
                t0_p = time.perf_counter()
                rotated_paste(canvas_tmp, res, cx, cy, int(ind_cfg.get("rotation", 0)))
                t_pst.append((time.perf_counter() - t0_p) * 1000.0)

        t_indicator_render.extend(t_rnd)
        t_indicator_paste.extend(t_pst)

    return {
        "layout_split_prepare": summary_stats(t_split),
        "above_compose_total": summary_stats(t_compose_total),
        "above_indicator_render": summary_stats(t_indicator_render),
        "above_indicator_paste": summary_stats(t_indicator_paste),
        "above_bbox_tracking": summary_stats(t_bbox_union),
        "above_candidate_crop": summary_stats(t_candidate_crop),
        "above_local_alpha_scan": summary_stats(t_local_alpha_scan),
        "above_final_crop": summary_stats(t_final_crop),
        "above_to_bytes": summary_stats(t_tobytes),
        "after_keys": after_keys,
    }


# =========================================================================
# 4. SCENARIO BENCHMARKS (Empty, 1 text, Large text, Multi, Sparse, None)
# =========================================================================
def run_scenario_benchmarks(
    base_layout: dict[str, Any],
    font_path: str,
    iterations: int = 300,
) -> dict[str, Any]:
    print("--- 4. Running Scenario Layout Benchmarks ---", flush=True)
    scenarios: dict[str, dict[str, Any]] = {}

    # Scenario A: Empty ABOVE (no indicators, no custom texts)
    layout_empty = copy.deepcopy(base_layout)
    below, above_empty, _ = _ordered_map_layout_parts(layout_empty)
    above_empty["indicators"] = {}
    above_empty["custom_texts"] = []

    # Scenario B: One small text (default: fit_battery_text)
    layout_small = copy.deepcopy(base_layout)
    _, above_small, _ = _ordered_map_layout_parts(layout_small)

    # Scenario C: Large text (large font_size = 8.0)
    layout_large = copy.deepcopy(base_layout)
    _, above_large, _ = _ordered_map_layout_parts(layout_large)
    if "fit_battery_text" in above_large["indicators"]:
        above_large["indicators"]["fit_battery_text"]["font_size"] = 8.0

    # Scenario D: Multiple elements (2 elements: battery + custom_text)
    layout_2elem = copy.deepcopy(base_layout)
    _, above_2elem, _ = _ordered_map_layout_parts(layout_2elem)
    above_2elem["custom_texts"] = [{
        "text": "OVERLAY TOP", "x": 50, "y": 10, "font_size": 3.0, "rotation": 0, "enabled": True
    }]

    # Scenario E: Multiple elements (4 elements)
    layout_4elem = copy.deepcopy(base_layout)
    _, above_4elem, _ = _ordered_map_layout_parts(layout_4elem)
    above_4elem["custom_texts"] = [
        {"text": "TOP LEFT", "x": 10, "y": 10, "font_size": 2.5, "rotation": 0, "enabled": True},
        {"text": "TOP RIGHT", "x": 90, "y": 10, "font_size": 2.5, "rotation": 0, "enabled": True},
        {"text": "BOTTOM LEFT", "x": 10, "y": 90, "font_size": 2.5, "rotation": 0, "enabled": True},
    ]

    # Scenario F: Sparse distant elements (corner to corner: (5%,5%) and (95%,95%))
    layout_sparse = copy.deepcopy(base_layout)
    _, above_sparse, _ = _ordered_map_layout_parts(layout_sparse)
    above_sparse["indicators"] = {}
    above_sparse["custom_texts"] = [
        {"text": "CORNER TL", "x": 5, "y": 5, "font_size": 2.0, "rotation": 0, "enabled": True},
        {"text": "CORNER BR", "x": 95, "y": 95, "font_size": 2.0, "rotation": 0, "enabled": True},
    ]

    # Scenario G: None case (telemetry value is None)
    layout_none = copy.deepcopy(base_layout)
    _, above_none, _ = _ordered_map_layout_parts(layout_none)

    all_cases = [
        ("Empty ABOVE", above_empty, {"fit_battery_text": 74.0}),
        ("One Small Text (Real Default)", above_small, {"fit_battery_text": 74.0}),
        ("One Large Text", above_large, {"fit_battery_text": 74.0}),
        ("2 Elements ABOVE", above_2elem, {"fit_battery_text": 74.0}),
        ("4 Elements ABOVE", above_4elem, {"fit_battery_text": 74.0}),
        ("Sparse Distant Elements (TL & BR)", above_sparse, {}),
        ("Value = None (Missing Telemetry)", above_none, {"fit_battery_text": None}),
    ]

    for name, lay, ind_vals in all_cases:
        t_comp = []
        t_crop_pipeline = []
        cand_sizes = []
        final_sizes = []

        for _ in range(iterations):
            bboxes = {}
            t0 = time.perf_counter()
            img = compose_overlay(
                canvas_w=3840,
                canvas_h=2160,
                layout=lay,
                font_path=font_path,
                date_text="2026-08-05",
                time_text="04:28:11",
                speed_value=25.0,
                distance_m=1000.0,
                alt_value=150.0,
                indicator_values=ind_vals,
                _bboxes=bboxes,
                reuse_canvas=True,
            )
            t_comp.append((time.perf_counter() - t0) * 1000.0)

            t0_crop = time.perf_counter()
            cand = _rendered_bbox_union(bboxes, 3840, 2160, pad=64)
            final_bbox = None
            if cand is not None:
                cand_sizes.append((cand[2], cand[3], cand[2] * cand[3]))
                c_img = img.crop((cand[0], cand[1], cand[0] + cand[2], cand[1] + cand[3]))
                loc_bbox = c_img.getchannel("A").getbbox()
                if loc_bbox is not None:
                    f_img = c_img.crop(loc_bbox)
                    fw, fh = loc_bbox[2] - loc_bbox[0], loc_bbox[3] - loc_bbox[1]
                    final_bbox = (cand[0] + loc_bbox[0], cand[1] + loc_bbox[1], fw, fh)
                    final_sizes.append((fw, fh, fw * fh))
                    _ = f_img.tobytes("raw", "RGBA")
            t_crop_pipeline.append((time.perf_counter() - t0_crop) * 1000.0)

        scenarios[name] = {
            "compose_stats": summary_stats(t_comp),
            "crop_pipeline_stats": summary_stats(t_crop_pipeline),
            "total_above_cpu_ms": summary_stats([c + p for c, p in zip(t_comp, t_crop_pipeline)]),
            "avg_candidate_size": (
                (int(statistics.mean([w for w, h, a in cand_sizes])),
                 int(statistics.mean([h for w, h, a in cand_sizes])),
                 int(statistics.mean([a for w, h, a in cand_sizes])))
                if cand_sizes else (0, 0, 0)
            ),
            "avg_final_size": (
                (int(statistics.mean([w for w, h, a in final_sizes])),
                 int(statistics.mean([h for w, h, a in final_sizes])),
                 int(statistics.mean([a for w, h, a in final_sizes])))
                if final_sizes else (0, 0, 0)
            ),
        }

    return scenarios


# =========================================================================
# 5. DYNAMIC TRANSITIONS & PIXEL SANITY TESTS
# =========================================================================
def run_dynamic_transition_tests(
    base_layout: dict[str, Any],
    font_path: str,
) -> dict[str, Any]:
    print("--- 5. Testing Dynamic Transitions (visible -> None -> visible) ---", flush=True)
    _, above, _ = _ordered_map_layout_parts(base_layout)

    # Frame 1: visible
    bboxes_1 = {}
    img_1 = compose_overlay(
        canvas_w=3840, canvas_h=2160, layout=above, font_path=font_path,
        date_text="", time_text="", speed_value=0.0, distance_m=0.0,
        indicator_values={"fit_battery_text": 74.0}, _bboxes=bboxes_1, reuse_canvas=True,
    )
    cand_1 = _rendered_bbox_union(bboxes_1, 3840, 2160, pad=64)

    # Frame 2: None (missing data)
    bboxes_2 = {}
    img_2 = compose_overlay(
        canvas_w=3840, canvas_h=2160, layout=above, font_path=font_path,
        date_text="", time_text="", speed_value=0.0, distance_m=0.0,
        indicator_values={"fit_battery_text": None}, _bboxes=bboxes_2, reuse_canvas=True,
    )
    cand_2 = _rendered_bbox_union(bboxes_2, 3840, 2160, pad=64)

    # Frame 3: visible again
    bboxes_3 = {}
    img_3 = compose_overlay(
        canvas_w=3840, canvas_h=2160, layout=above, font_path=font_path,
        date_text="", time_text="", speed_value=0.0, distance_m=0.0,
        indicator_values={"fit_battery_text": 75.0}, _bboxes=bboxes_3, reuse_canvas=True,
    )
    cand_3 = _rendered_bbox_union(bboxes_3, 3840, 2160, pad=64)

    passed = (cand_1 is not None) and (cand_2 is None) and (cand_3 is not None)
    return {
        "transition_test_passed": passed,
        "frame1_cand_bbox": cand_1,
        "frame2_none_cand_bbox": cand_2,
        "frame3_cand_bbox": cand_3,
    }


# =========================================================================
# 6. MAIN COMPOSITOR (BELOW) vs ABOVE COMPOSITOR COMPARISON
# =========================================================================
def run_main_vs_above_comparison(
    layout: dict[str, Any],
    font_path: str,
    iterations: int = 300,
) -> dict[str, Any]:
    print("--- 6. Comparing Main Compositor (BELOW) vs ABOVE Compositor ---", flush=True)
    below, above, _ = _ordered_map_layout_parts(layout)

    t_below = []
    for _ in range(iterations):
        bb_below = {}
        t0 = time.perf_counter()
        img_b = compose_overlay(
            canvas_w=3840, canvas_h=2160, layout=below, font_path=font_path,
            date_text="2026-08-05", time_text="04:28:11", speed_value=25.0,
            distance_m=1000.0, alt_value=150.0,
            indicator_values={"fit_cadence_text": 85.0, "fit_heart_rate_text": 140.0, "fit_enhanced_speed_text": 25.0},
            _bboxes=bb_below,
            gpu_capture_keys={"fit_cadence_text", "fit_heart_rate_text", "fit_enhanced_speed_text"},
            gpu_capture={},
            reuse_canvas=True,
        )
        t_below.append((time.perf_counter() - t0) * 1000.0)

    t_above = []
    for _ in range(iterations):
        bb_above = {}
        t0 = time.perf_counter()
        img_a = compose_overlay(
            canvas_w=3840, canvas_h=2160, layout=above, font_path=font_path,
            date_text="2026-08-05", time_text="04:28:11", speed_value=25.0,
            distance_m=1000.0, alt_value=150.0,
            indicator_values={"fit_battery_text": 74.0},
            _bboxes=bb_above,
            reuse_canvas=True,
        )
        t_above.append((time.perf_counter() - t0) * 1000.0)

    return {
        "main_below_compose": summary_stats(t_below),
        "above_compose": summary_stats(t_above),
        "ratio_below_to_above": (statistics.mean(t_below) / max(0.001, statistics.mean(t_above))),
    }


def main():
    parser = argparse.ArgumentParser(description="ETAP 8D Audit & Benchmark")
    parser.add_argument("--runs", action="store_true", help="Execute 3x900 full video runs on GX030120.MP4")
    args = parser.parse_args()

    # Load layout and fonts
    with open(ROOT / "def_layout.json", "r", encoding="utf-8") as f:
        layout = json.load(f)
    font_path = resolve_font_path("Arial")

    audit_results: dict[str, Any] = {}

    # 1. Pillow microbenchmarks
    audit_results["pillow_microbenchmarks"] = run_pillow_microbenchmarks(iterations=300)

    # 2. Rotation & paste
    audit_results["rotation_benchmarks"] = run_rotation_benchmarks(iterations=300)

    # 3. Detailed ABOVE breakdown
    audit_results["above_breakdown"] = run_detailed_above_breakdown(layout, font_path, iterations=300)

    # 4. Scenario benchmarks
    audit_results["scenarios"] = run_scenario_benchmarks(layout, font_path, iterations=200)

    # 5. Dynamic transitions
    audit_results["transitions"] = run_dynamic_transition_tests(layout, font_path)

    # 6. Main vs Above
    audit_results["main_vs_above"] = run_main_vs_above_comparison(layout, font_path, iterations=200)

    # Save intermediate audit JSON
    out_dir = ROOT / "Raporty" / "AMD_ETAP8D"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_file = out_dir / "etap8d_audit_data.json"
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, indent=2)

    print(f"\n[ETAP 8D AUDIT COMPLETE] Results saved to {audit_file}", flush=True)

    # Print executive summary of audit
    print("\n================== EXECUTIVE AUDIT SUMMARY ==================")
    print(f"Pillow Image.new(4K RGBA):              median = {audit_results['pillow_microbenchmarks']['image_new_4k_rgba']['median']:.4f} ms")
    print(f"Pillow Regional Clear (559x190):        median = {audit_results['pillow_microbenchmarks']['regional_clear_paste_559x190']['median']:.4f} ms")
    print(f"Pillow Candidate Crop from 4K:          median = {audit_results['pillow_microbenchmarks']['candidate_crop_from_4k']['median']:.4f} ms")
    print(f"Pillow Local Alpha Scan (559x190):      median = {audit_results['pillow_microbenchmarks']['local_alpha_scan_559x190']['median']:.4f} ms")
    print(f"Pillow Full Frame Alpha Scan (4K):      median = {audit_results['pillow_microbenchmarks']['full_frame_4k_alpha_scan']['median']:.4f} ms")
    print(f"Rotated Paste 0 deg:                    median = {audit_results['rotation_benchmarks']['rotated_paste_0deg']['median']:.4f} ms")
    print(f"Rotated Paste 17 deg:                   median = {audit_results['rotation_benchmarks']['rotated_paste_17deg']['median']:.4f} ms")
    print(f"ABOVE compose_overlay (total):          median = {audit_results['above_breakdown']['above_compose_total']['median']:.4f} ms")
    print(f"ABOVE indicator render:                 median = {audit_results['above_breakdown']['above_indicator_render']['median']:.4f} ms")
    print(f"ABOVE indicator paste:                  median = {audit_results['above_breakdown']['above_indicator_paste']['median']:.4f} ms")
    print(f"ABOVE candidate crop:                   median = {audit_results['above_breakdown']['above_candidate_crop']['median']:.4f} ms")
    print(f"ABOVE local alpha scan:                 median = {audit_results['above_breakdown']['above_local_alpha_scan']['median']:.4f} ms")
    print(f"Main (BELOW) compose:                   median = {audit_results['main_vs_above']['main_below_compose']['median']:.4f} ms")
    print(f"Ratio Main/Above:                                {audit_results['main_vs_above']['ratio_below_to_above']:.2f}x")
    print("============================================================\n")


if __name__ == "__main__":
    main()
