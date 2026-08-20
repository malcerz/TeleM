from __future__ import annotations

import copy
import itertools
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    find_gps_anchor,
)
from src.ffmpeg.command_builder import get_layout_hud_bbox, get_layout_hud_regions
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_samples, _resolve_cache_value, init_worker
from src.telemetry_precompute import build_telemetry_cache

W, H = 1920, 1080
N = 5400
FPS = 30000 / 1001
SAMPLE_INDICES = [0, 540, 1350, 2700, 4050, 4860, 5399]
OUT = ROOT / "scratch" / "etap5b3_geometry"


def xy(cfg: dict, w: int, h: int) -> tuple[int, int]:
    lx, ly = cfg.get("x", 0.0), cfg.get("y", 0.0)
    px = int(round(lx / 100.0 * w)) if lx <= 100.0 else int(round(lx))
    py = int(round(ly / 100.0 * h)) if ly <= 100.0 else int(round(ly))
    return px, py


def declared_box(key: str, cfg: dict, w: int = W, h: int = H) -> tuple[int, int, int, int]:
    px, py = xy(cfg, w, h)
    rot = int(cfg.get("rotation", 0)) % 360
    form = cfg.get("form", "text")
    min_dim = min(w, h)
    if form == "gauge":
        sz = cfg.get("size", 0.1)
        size_px = int(round(sz * min_dim)) if sz <= 1.0 else int(round(sz / 100.0 * min_dim))
        radius = int(size_px * 1.35)
        x1, y1, x2, y2 = px - radius - 10, py - radius - 10, px + radius + 10, py + radius + 10
    elif form in ("bar", "segment_bar"):
        sz = cfg.get("size", 0.2)
        size_px = int(round(sz * w)) if sz <= 1.0 else int(round(sz / 100.0 * w))
        bar_w, bar_h = size_px + 80, max(60, int(size_px * 0.35)) + 50
        if rot in (90, 270):
            bar_w, bar_h = bar_h, bar_w
        x1, y1 = px - bar_w // 2 - 20, py - bar_h // 2 - 20
        x2, y2 = px + bar_w // 2 + 20, py + bar_h // 2 + 20
    elif form in ("chart", "moving_map", "static_map", "map"):
        sz = cfg.get("size", cfg.get("w", 0.3))
        size_px = int(round(sz * w)) if sz <= 1.0 else int(round(sz / 100.0 * w))
        cw, ch = size_px + 60, max(50, int(size_px * 0.45)) + 50
        x1, y1 = px - cw // 2 - 20, py - ch // 2 - 20
        x2, y2 = px + cw // 2 + 20, py + ch // 2 + 20
    elif key in ("time_block", "time_display") or "time" in key:
        x1, y1 = px - 20, py - 20
        x2, y2 = px + int(w * 0.20) + 20, py + int(h * 0.12) + 20
    else:
        fs_val = cfg.get("font_size", cfg.get("size", 0.02))
        fs = max(10, int(round(fs_val * min_dim)) if fs_val <= 1.0 else int(round(fs_val / 100.0 * min_dim)))
        text_w, text_h = max(int(w * 0.12), fs * 12), max(int(h * 0.06), fs * 3 + 20)
        x1, y1, x2, y2 = px - 20, py - 20, px + text_w + 20, py + text_h + 20
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    return x1, y1, max(0, x2 - x1), max(0, y2 - y1)


def rect_union(a, b):
    x1, y1 = min(a[0], b[0]), min(a[1], b[1])
    x2, y2 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return x1, y1, x2 - x1, y2 - y1


def clean_box(box):
    x1, y1, w, h = box
    x2, y2 = x1 + w, y1 + h
    if x1 % 2:
        x1 -= 1
    if y1 % 2:
        y1 -= 1
    w = max(2, x2 - x1)
    h = max(2, y2 - y1)
    if w % 2:
        w += 1
    if h % 2:
        h += 1
    w = min(W - x1, w)
    h = min(H - y1, h)
    return x1, y1, w, h


def cluster_detailed(boxes: dict[str, tuple[int, int, int, int]], max_regions: int):
    clusters = [{"keys": [k], "box": v} for k, v in boxes.items()]
    history = []
    while len(clusters) > max_regions:
        best = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                a, b = clusters[i], clusters[j]
                u = rect_union(a["box"], b["box"])
                waste = u[2] * u[3] - a["box"][2] * a["box"][3] - b["box"][2] * b["box"][3]
                candidate = (waste, i, j, u)
                if best is None or candidate[0] < best[0]:
                    best = candidate
        _, i, j, u = best
        a, b = clusters[i], clusters[j]
        history.append({"a": a["keys"], "b": b["keys"], "box_a": a["box"], "box_b": b["box"], "merged": u,
                        "area_a": a["box"][2] * a["box"][3], "area_b": b["box"][2] * b["box"][3],
                        "merged_area": u[2] * u[3], "wasted_area": u[2] * u[3] - a["box"][2] * a["box"][3] - b["box"][2] * b["box"][3]})
        clusters.pop(j); clusters.pop(i)
        clusters.append({"keys": a["keys"] + b["keys"], "box": u})
    for c in clusters:
        c["box"] = clean_box(c["box"])
    return clusters, history


def pack(clusters, padding=4):
    clean = [(c["box"][0], c["box"][1], c["box"][2], c["box"][3], c["keys"]) for c in clusters]
    best = None
    for order in itertools.permutations(clean):
        sx = sy = row_h = max_x = 0
        regs = []
        for x, y, w, h, keys in order:
            if sx + w > W and sx > 0:
                sx = 0; sy += row_h + padding; row_h = 0
            regs.append({"dest": (x, y, w, h), "atlas": (sx, sy, w, h), "keys": keys})
            sx += w + padding
            if sx % 2:
                sx += 1
            row_h = max(row_h, h); max_x = max(max_x, sx)
        aw = max_x if max_x % 2 == 0 else max_x + 1
        ah = sy + row_h
        if ah % 2:
            ah += 1
        candidate = (aw * ah, aw, ah, regs)
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def pack_vertical(clusters, padding=4):
    best = None
    clean = [(c["box"][0], c["box"][1], c["box"][2], c["box"][3], c["keys"]) for c in clusters]
    for order in itertools.permutations(clean):
        sx = sy = col_w = max_y = 0
        regs = []
        for x, y, w, h, keys in order:
            if sy + h > H and sy > 0:
                sy = 0; sx += col_w + padding; col_w = 0
            regs.append({"dest": (x, y, w, h), "atlas": (sx, sy, w, h), "keys": keys})
            sy += h + padding
            if sy % 2:
                sy += 1
            col_w = max(col_w, w); max_y = max(max_y, sy)
        aw = sx + col_w; ah = max_y - (padding if max_y else 0)
        if ah % 2:
            ah += 1
        if aw % 2:
            aw += 1
        candidate = (aw * ah, aw, ah, regs)
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def compose_for(index: int, layout: dict):
    data = WORKER_CACHE["_telemetry_cache"].lookup(index)
    return compose_overlay(
        W, H, layout, "", data["date_text"], data["time_text"],
        data["speed_value"], data["distance_m"], data["max_distance_m"],
        data["alt_value"], data["min_alt"], data["max_alt"],
        data["iso_value"], data["exposure_value"], data["temp_value"],
        indicator_values=data["indicator_values"], max_speed_kmh=data["max_speed_kmh"],
        power_value=data["power_value"], atemp_value=data["atemp_value"],
        hr_value=data["hr_value"], cad_value=data["cad_value"], battery_value=data["battery_value"],
        chart_data=data["chart_data"], current_position=data["current_position"],
        extra_indicators=data["extra_indicators"], gps_track=data["gps_track"],
        target_dt=data["target_dt"], start_dt_utc=data["start_dt_utc"],
        elapsed_seconds=data["elapsed_seconds"], avg_speed_kmh=data["avg_speed_kmh"],
        reuse_canvas=False,
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    layout = normalize_layout(ROOT / "def_layout.json", W, H)
    records = gpmf_to_exiftool_json(str(ROOT / "Video" / "GX030120.MP4"))[0]
    speed = extract_speed_samples(records); alt = extract_altitude_samples(records)
    track = extract_track_samples(records); iso = extract_iso_samples(records)
    exposure = extract_exposure_samples(records); temp = extract_temperature_samples(records)
    anchor = find_gps_anchor(records)
    fit = process_fit(str(ROOT / "Video" / "Poranna_jazda_na_rowerze.fit"), video_start_dt=anchor)
    fields = {"start_dt_utc": anchor, "speed_samples": speed, "track_samples": track, "alt_samples": alt,
              "iso_samples": iso, "exposure_samples": exposure, "temp_samples": temp}
    aw, ah, regs = get_layout_hud_regions(layout, W, H, max_regions=3)
    init_worker(W, H, "", layout, fields, None, iso, exposure, temp, None, None, None, None, None, None, None,
                fit, fit.get("track"), anchor, 0.0, speed, track, alt, FPS, 1, N, None, 0, None, regs, False)
    cache = build_telemetry_cache(layout=layout, base_dt=anchor, tz_offset_hours=0.0, start_dt_utc=anchor,
        speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure,
        temperature_samples=temp, fit_data=fit, gps_track=fit.get("track"), chart_data=WORKER_CACHE.get("_precomputed_chart_data"),
        resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache"), total_frames=N, target_fps=FPS)
    WORKER_CACHE["_telemetry_cache"] = cache

    active = {k: v for k, v in layout["indicators"].items() if v and v.get("enabled", True)}
    rows = {}
    per_sample = {}
    full_samples = {}
    declared_boxes = {}
    for key, cfg in active.items():
        declared = declared_box(key, cfg)
        samples = {}
        for idx in SAMPLE_INDICES:
            one = copy.deepcopy(layout)
            one["indicators"] = {key: copy.deepcopy(cfg)}
            img = compose_for(idx, one)
            alpha = img.getchannel("A").getbbox()
            samples[str(idx)] = alpha
        union = None
        for alpha in samples.values():
            if alpha:
                b = (alpha[0], alpha[1], alpha[2] - alpha[0], alpha[3] - alpha[1])
                union = b if union is None else rect_union(union, b)
        da = declared[2] * declared[3]
        aa = union[2] * union[3] if union else 0
        rows[key] = {"form": cfg.get("form", "text"), "enabled": cfg.get("enabled", True), "x": cfg.get("x"), "y": cfg.get("y"),
                     "size": cfg.get("size"), "rotation": cfg.get("rotation", 0), "declared_bbox": declared,
                     "actual_alpha_bbox": union, "declared_area": da, "actual_alpha_area": aa,
                     "waste_percent": (100.0 * (da - aa) / da if da else 0.0), "phantom": union is None,
                     "samples": samples}
        full_samples[key] = union
        declared_boxes[key] = declared

    clusters_by_max = {}
    for maximum in range(1, 7):
        clusters, history = cluster_detailed(declared_boxes, maximum)
        area, pw, ph, packed = pack(clusters)
        clusters_by_max[str(maximum)] = {"clusters": clusters, "merge_history": history, "packed": packed,
                                         "atlas_w": pw, "atlas_h": ph, "atlas_area": area,
                                         "area_pct": area / (W * H) * 100.0, "mb": area * 4 / 1024 / 1024,
                                         "sum_region_area": sum(c["box"][2] * c["box"][3] for c in clusters),
                                         "packing_efficiency": sum(c["box"][2] * c["box"][3] for c in clusters) / area}

    full = compose_for(SAMPLE_INDICES[3], layout)
    draw = ImageDraw.Draw(full)
    colors = [(255, 0, 0), (0, 180, 255), (255, 150, 0), (0, 220, 100), (200, 0, 255), (255, 255, 0)]
    clusters = clusters_by_max["3"]["clusters"]
    for ci, c in enumerate(clusters):
        x, y, w, h = c["box"]
        draw.rectangle((x, y, x + w, y + h), outline=colors[ci % len(colors)], width=3)
        draw.text((x + 4, y + 4), f"R{ci}: {','.join(c['keys'])}", fill=colors[ci % len(colors)])
    for key, row in rows.items():
        x, y, w, h = row["declared_bbox"]
        draw.rectangle((x, y, x + w, y + h), outline=(255, 255, 255), width=1)
        if row["actual_alpha_bbox"]:
            x, y, w, h = row["actual_alpha_bbox"]
            draw.rectangle((x, y, x + w, y + h), outline=(0, 255, 0), width=2)
    full.save(OUT / "GX030120_atlas_geometry_audit.png")

    global_bbox = get_layout_hud_bbox(layout, W, H)
    edge_attribution = {"left": [], "top": [], "right": [], "bottom": []}
    for key, cfg in active.items():
        one = copy.deepcopy(layout)
        one["indicators"] = {key: copy.deepcopy(cfg)}
        b = get_layout_hud_bbox(one, W, H)
        if b[0] == 0: edge_attribution["left"].append(key)
        if b[1] == 0: edge_attribution["top"].append(key)
        if b[0] + b[2] >= W: edge_attribution["right"].append(key)
        if b[1] + b[3] >= H: edge_attribution["bottom"].append(key)

    def scenario(boxes, maximum):
        clusters, history = cluster_detailed(boxes, maximum)
        area, pw, ph, packed = pack(clusters)
        return {"regions": len(clusters), "atlas_w": pw, "atlas_h": ph, "area_pct": area / (W * H) * 100.0,
                "mb": area * 4 / 1024 / 1024, "transport_reduction_pct": 100.0 - area / (W * H) * 100.0,
                "merge_history": history, "packed": packed}

    precise_boxes = {k: clean_box(v["actual_alpha_bbox"]) for k, v in rows.items() if v["actual_alpha_bbox"]}
    nonphantom_declared = {k: v for k, v in declared_boxes.items() if not rows[k]["phantom"]}
    render_observed_declared = {k: v for k, v in declared_boxes.items() if rows[k]["actual_alpha_bbox"]}
    scenarios = {
        "A_current": scenario(declared_boxes, 3),
        "B_precise_alpha_diagnostic": scenario(precise_boxes, 3),
        "C_phantom_elimination_diagnostic": scenario(nonphantom_declared, 3),
        "C2_exclude_all_not_observed_alpha": scenario(render_observed_declared, 3),
        "D_4_regions": scenario(declared_boxes, 4),
        "E_5_regions": scenario(declared_boxes, 5),
    }
    sample_data = cache.lookup(SAMPLE_INDICES[3])
    from src.indicators.dispatcher import render_value_indicator
    raster_sizes = {}
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        value, unit, label = sample_data["extra_indicators"][key]
        rendered, _, _, _ = render_value_indicator(W, H, layout, "", key, value, unit, label,
            cfg_override=layout["indicators"][key], history_data=sample_data["chart_data"].get(key),
            current_position=sample_data["current_position"], gps_track=sample_data["gps_track"],
            supersample=1, target_dt=sample_data["target_dt"])
        raster_sizes[key] = list(rendered.size) if rendered else None
    map_value, map_unit, map_label = 0.0, "", "Mapa"
    map_rendered, map_rx, map_ry, _ = render_value_indicator(W, H, layout, "", "track_map", map_value, map_unit, map_label,
        cfg_override=layout["indicators"]["track_map"], current_position=sample_data["current_position"],
        gps_track=sample_data["gps_track"], supersample=1, target_dt=sample_data["target_dt"])
    result = {"canvas": [W, H], "frames": N, "fps": FPS, "sample_indices": SAMPLE_INDICES,
              "active_indicators": list(active), "global_bbox": global_bbox, "global_area_pct": global_bbox[2] * global_bbox[3] / (W * H) * 100,
              "global_edge_attribution": edge_attribution,
              "data_probe": {"gps_track_points": len(sample_data.get("gps_track") or []), "current_position": sample_data.get("current_position"),
                             "chart_data_keys": sorted((sample_data.get("chart_data") or {}).keys()),
                             "indicator_value_keys": sorted((sample_data.get("indicator_values") or {}).keys()),
                             "extra_indicator_keys": sorted((sample_data.get("extra_indicators") or {}).keys())},
              "chart_raster_sizes": raster_sizes,
              "map_render_probe": {"returned": bool(map_rendered), "size": list(map_rendered.size) if map_rendered else None,
                                   "alpha_bbox": map_rendered.getchannel("A").getbbox() if map_rendered else None,
                                   "dst_origin": [map_rx, map_ry]},
              "current_regions": {"atlas_w": aw, "atlas_h": ah, "area": aw * ah, "area_pct": aw * ah / (W * H) * 100,
                                  "regions": regs}, "indicators": rows, "by_max_regions": clusters_by_max}
    result["scenarios"] = scenarios
    zero_clusters, _ = cluster_detailed(declared_boxes, 3)
    z_area, z_w, z_h, z_packed = pack(zero_clusters, padding=0)
    result["padding_audit"] = {"region_padding_current": 4, "region_padding_zero_diagnostic": {"atlas_w": z_w, "atlas_h": z_h,
        "area_pct": z_area / (W * H) * 100.0, "mb": z_area * 4 / 1024 / 1024, "packed": z_packed},
        "current_atlas_area": aw * ah, "current_padding_delta_area": aw * ah - z_area}
    v_area, v_w, v_h, v_packed = pack_vertical(zero_clusters, padding=4)
    result["packing_variants"] = {"horizontal_current": {"atlas_w": aw, "atlas_h": ah, "area": aw * ah},
        "vertical_current": {"atlas_w": v_w, "atlas_h": v_h, "area": v_area, "packed": v_packed}}
    (OUT / "geometry_audit.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"global_bbox": global_bbox, "current_atlas": [aw, ah, aw * ah / (W * H) * 100],
                      "active": list(active), "output": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
