from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_altitude_samples, extract_exposure_samples, extract_iso_samples,
    extract_speed_samples, extract_temperature_samples, extract_track_samples,
)
from src.ffmpeg.command_builder import (
    _precise_text_box, build_text_bbox_context, get_layout_hud_regions,
)
from src.ffmpeg.streaming import _snap_nvidia_hud_layout


VIDEO = ROOT / "Video" / "GX030120.MP4"
FIT_FILES = {
    "Poranna": ROOT / "Video" / "Poranna_jazda_na_rowerze.fit",
    "Popoludniowa": ROOT / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit",
}


def fit_field_report(fit, layout):
    rows = []
    for key, cfg in layout.get("indicators", {}).items():
        if not (cfg.get("enabled", True) and key.startswith("fit_") and key.endswith("_text")):
            continue
        field = key[4:-5]
        values = fit.get(field, [])
        rows.append({"indicator": key, "field": field, "available": bool(values),
                     "count": len(values), "fit_keys": sorted(fit.keys())})
    return rows


def context_for(fit, records):
    speed = extract_speed_samples(records)
    alt = extract_altitude_samples(records)
    track = extract_track_samples(records)
    iso = extract_iso_samples(records)
    exposure = extract_exposure_samples(records)
    temp = extract_temperature_samples(records)
    return build_text_bbox_context(
        normalize_layout(str(ROOT / "def_layout.json"), 1920, 1080),
        fit_data=fit, speed_samples=speed, track_samples=track, alt_samples=alt,
        iso_samples=iso, exposure_samples=exposure, temperature_samples=temp,
    )


def run_variant(layout, ctx, name, max_regions=4, grid=16):
    runtime = _snap_nvidia_hud_layout(layout, 1920, 1080, grid)
    aw, ah, regions = get_layout_hud_regions(
        runtime, 1920, 1080, max_regions=max_regions,
        text_candidates=ctx["text_candidates"],
        phantom_keys=ctx["phantom_keys"], font_path="",
    )
    return {"name": name, "max_regions": max_regions, "grid": grid,
            "atlas": [aw, ah], "area_pct": aw * ah / (1920 * 1080) * 100,
            "regions": [list(r) for r in regions],
            "phantom_keys": sorted(ctx["phantom_keys"])}


def main():
    records = gpmf_to_exiftool_json(str(VIDEO))[0]
    base = normalize_layout(str(ROOT / "def_layout.json"), 1920, 1080)
    result = {"layout_fit_indicators": fit_field_report({}, base), "fits": {}}
    for name, path in FIT_FILES.items():
        fit = process_fit(str(path))
        ctx = context_for(fit, records)
        result["fits"][name] = {
            "all_available_fit_fields": sorted(fit.keys()),
            "indicator_availability": fit_field_report(fit, base),
            "resolved_numeric_candidates": {
                k: {"phantom": v.get("phantom"), "formatted_values": v.get("formatted_values", [])}
                for k, v in ctx["text_candidates"].items()
                if k in {"fit_battery_text", "fit_battery_pct_text", "fit_solar_pct_text"}
            },
            "variants": [],
        }
        runtime = _snap_nvidia_hud_layout(base, 1920, 1080, 16)
        precise_boxes = {}
        for key, cfg in runtime.get("indicators", {}).items():
            if not cfg.get("enabled", True) or cfg.get("form", "text") != "text" or key in ctx["phantom_keys"]:
                continue
            box = _precise_text_box(runtime, key, cfg, 1920, 1080, ctx["text_candidates"], "")
            if box is not None:
                precise_boxes[key] = list(box)
        result["fits"][name]["precise_text_boxes"] = precise_boxes
        result["fits"][name]["variants"].append(run_variant(base, ctx, "MAX4_GRID16_current", 4, 16))
        result["fits"][name]["variants"].append(run_variant(base, ctx, "MAX5_GRID16", 5, 16))
        for key in ("fit_battery_text", "fit_battery_pct_text", "fit_solar_pct_text"):
            if fit.get(key[4:-5]):
                candidate = copy.deepcopy(base)
                candidate["indicators"][key]["enabled"] = False
                result["fits"][name]["variants"].append(run_variant(candidate, ctx, f"disable_{key}", 4, 16))
        for positions in (
            {"fit_battery_pct_text": (86.0, 48.0), "fit_solar_pct_text": (86.0, 53.0)},
            {"fit_battery_pct_text": (84.0, 48.0), "fit_solar_pct_text": (84.0, 53.0)},
            {"fit_battery_pct_text": (50.0, 18.0), "fit_solar_pct_text": (50.0, 23.0)},
        ):
            candidate = copy.deepcopy(base)
            for key, (x, y) in positions.items():
                if fit.get(key[4:-5]):
                    candidate["indicators"][key]["x"] = x
                    candidate["indicators"][key]["y"] = y
            result["fits"][name]["variants"].append(run_variant(candidate, ctx, f"reposition_{positions}", 4, 16))
        if name == "Popoludniowa":
            local = []
            for grid in (8, 16):
                for dx1 in (-16, -8, 0, 8, 16):
                    for dy1 in (-16, -8, 0, 8, 16):
                        for dx2 in (-16, -8, 0, 8, 16):
                            for dy2 in (-16, -8, 0, 8, 16):
                                candidate = copy.deepcopy(base)
                                for key, dx, dy in (
                                    ("fit_battery_pct_text", dx1, dy1),
                                    ("fit_solar_pct_text", dx2, dy2),
                                ):
                                    cfg = candidate["indicators"][key]
                                    cfg["x"] = float(cfg["x"]) + dx / 1920 * 100
                                    cfg["y"] = float(cfg["y"]) + dy / 1080 * 100
                                v = run_variant(candidate, ctx, f"local_grid{grid}_{dx1}_{dy1}_{dx2}_{dy2}", 4, grid)
                                if v["area_pct"] <= 70.0:
                                    local.append(v)
            local.sort(key=lambda v: (v["area_pct"], v["atlas"][1], v["atlas"][0]))
            result["fits"][name]["local_reposition_candidates"] = local[:20]
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
