from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ns = runpy.run_path(str(ROOT / "scratch" / "audit_etap5b3_geometry.py"))
W, H, N, FPS = 1920, 1080, 5400, 30000 / 1001

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, find_gps_anchor)
from src.ffmpeg.command_builder import build_text_bbox_context, get_layout_hud_regions


def snap_layout(layout: dict, grid: int | None) -> dict:
    out = copy.deepcopy(layout)
    if not grid:
        return out
    for cfg in out.get("indicators", {}).values():
        if not cfg or not cfg.get("enabled", True):
            continue
        for axis, dim in (("x", W), ("y", H)):
            value = cfg.get(axis)
            if not isinstance(value, (int, float)):
                continue
            px = value / 100.0 * dim if value <= 100.0 else value
            snapped = round(px / grid) * grid
            delta = snapped - px
            limit = grid
            if abs(delta) > limit:
                continue
            snapped = max(0, min(dim, snapped))
            cfg[axis] = snapped / dim * 100.0 if value <= 100.0 else snapped
    return out


def region_stats(regions, w=W, h=H):
    area = sum(r[4] * r[5] for r in regions)
    atlas_w = max((r[2] + r[4] for r in regions), default=2)
    atlas_h = max((r[3] + r[5] for r in regions), default=2)
    return {
        "regions": len(regions), "atlas": [atlas_w, atlas_h],
        "area_pct": atlas_w * atlas_h / (w * h) * 100.0,
        "mb_frame": atlas_w * atlas_h * 4 / (1024 * 1024),
        "packing_efficiency_pct": area / (atlas_w * atlas_h) * 100.0,
        "rects": [list(r) for r in regions],
    }


def main():
    layout = normalize_layout(ROOT / "def_layout.json", W, H)
    records = gpmf_to_exiftool_json(str(ROOT / "Video" / "GX030120.MP4"))[0]
    speed = extract_speed_samples(records); alt = extract_altitude_samples(records)
    track = extract_track_samples(records); iso = extract_iso_samples(records)
    exposure = extract_exposure_samples(records); temp = extract_temperature_samples(records)
    anchor = find_gps_anchor(records)
    fit = process_fit(str(ROOT / "Video" / "Poranna_jazda_na_rowerze.fit"), video_start_dt=anchor)
    kwargs = dict(fit_data=fit, speed_samples=speed, track_samples=track, alt_samples=alt,
                  iso_samples=iso, exposure_samples=exposure, temperature_samples=temp)
    results = {}
    for grid in (None, 8, 16):
        variant = snap_layout(layout, grid)
        context = build_text_bbox_context(variant, **kwargs)
        key = "off" if grid is None else str(grid)
        results[key] = {"phantom_keys": sorted(context["phantom_keys"]), "max": {}}
        for maximum in range(3, 7):
            aw, ah, regions = get_layout_hud_regions(
                variant, W, H, max_regions=maximum,
                text_candidates=context["text_candidates"],
                phantom_keys=context["phantom_keys"], font_path="")
            stats = region_stats(regions)
            stats["atlas"] = [aw, ah]
            results[key]["max"][str(maximum)] = stats
        results[key]["deltas"] = {
            k: {axis: round(snap_layout(layout, grid)["indicators"][k][axis] * (W if axis == "x" else H) / 100.0 - layout["indicators"][k][axis] * (W if axis == "x" else H) / 100.0, 2)
                for axis in ("x", "y")}
            for k in layout.get("indicators", {}) if layout["indicators"].get(k)
        }
    out = ROOT / "scratch" / "etap5b5_geometry_audit.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for grid, item in results.items():
        print(f"GRID {grid}")
        for maximum, stats in item["max"].items():
            print(maximum, stats["atlas"], f"{stats['area_pct']:.3f}%", f"{stats['mb_frame']:.3f} MB", f"eff {stats['packing_efficiency_pct']:.1f}%")
        print("deltas", {k: v for k, v in item["deltas"].items() if any(v.values())})
        print("phantom", item["phantom_keys"])


if __name__ == "__main__":
    main()
