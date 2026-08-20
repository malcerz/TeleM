import sys, os, time, json
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from datetime import datetime, timedelta
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_extract import (
    load_json_with_fallback, ensure_records_list,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor,
)
from src.indicators.chart_builder import build_chart_data
from src.indicators.dispatcher import render_value_indicator
from src.indicators.frame_data import prepare_overlay_frame_data
from src.overlay_renderer import compose_overlay
from src.ffmpeg.worker_cache import init_worker, WORKER_CACHE, _resolve_cache_value
from src.ffmpeg.command_builder import get_layout_hud_regions, get_layout_hud_bbox

def run_atlas_geometry_audit():
    print("=" * 80)
    print("NVIDIA ETAP 5B.3: AUDYT GEOMETRII HUD ATLAS I FULL-FRAME FALLBACK")
    print("=" * 80)

    json_path = Path("Video/GX030120.json")
    fit_path = Path("Video/Poranna_jazda_na_rowerze.fit")
    raw_records = ensure_records_list(load_json_with_fallback(json_path))
    anchor_dt = find_gps_anchor(raw_records)
    fit_data = process_fit(str(fit_path), video_start_dt=anchor_dt)

    speed_samples = extract_speed_samples(raw_records)
    alt_samples = extract_altitude_samples(raw_records)
    track_samples = extract_track_samples(raw_records)
    iso_samples = extract_iso_samples(raw_records)
    exposure_samples = extract_exposure_samples(raw_records)
    temp_samples = extract_temperature_samples(raw_records)

    field_samples = {
        "start_dt_utc": anchor_dt,
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temp_samples": temp_samples,
    }

    layout = normalize_layout("def_layout.json", 1920, 1080)
    canvas_w, canvas_h = 1920, 1080
    min_dim = min(canvas_w, canvas_h)
    total_frames = 5400
    fps = 29.97

    # Init worker cache
    init_worker(
        video_width=canvas_w, video_height=canvas_h,
        field_samples=field_samples,
        layout=layout,
        font_path="",
        fit_data=fit_data,
        start_dt_utc=anchor_dt,
        target_fps=fps,
        total_overlay_frames=total_frames,
        gps_track=fit_data.get("track"),
    )

    # Prepare timeline checkpoints: 0%, 10%, 25%, 50%, 75%, 90%, 100%
    fractions = [0.0, 0.10, 0.25, 0.50, 0.75, 0.90, 1.0]
    frame_indices = [int(f * (total_frames - 1)) for f in fractions]

    # Pre-render frame_data for each checkpoint
    frame_data_pts = []
    for f_idx in frame_indices:
        target_dt = anchor_dt + timedelta(seconds=f_idx / fps)
        fd = prepare_overlay_frame_data(
            layout=layout,
            target_dt=target_dt,
            tz_offset_hours=0.0,
            start_dt_utc=anchor_dt,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temp_samples,
            fit_data=fit_data,
            gps_track=fit_data.get("track"),
            total_frames=total_frames,
            current_index=f_idx,
            chart_data=WORKER_CACHE.get("_precomputed_chart_data"),
            resolve_cache_value=_resolve_cache_value,
            _range_cache=WORKER_CACHE.get("_prep_cache"),
        )
        frame_data_pts.append((f_idx, target_dt, fd))

    indicators = layout.get("indicators", {})
    enabled_indicators = {k: v for k, v in indicators.items() if v and v.get("enabled", True)}

    # 1. Compute declared bbox for each indicator (exact logic from command_builder.py)
    indicator_declared = {}
    for key, cfg in enabled_indicators.items():
        lx = cfg.get("x", 0.0)
        ly = cfg.get("y", 0.0)
        px = int(round((lx / 100.0) * canvas_w)) if lx <= 100.0 else int(round(lx))
        py = int(round((ly / 100.0) * canvas_h)) if ly <= 100.0 else int(round(ly))
        rot = int(cfg.get("rotation", 0)) % 360
        form = cfg.get("form", "text")

        if form == "gauge":
            sz = cfg.get("size", 0.1)
            size_px = int(round(sz * min_dim)) if sz <= 1.0 else int(round((sz / 100.0) * min_dim))
            radius = int(size_px * 1.35)
            x1, y1 = px - radius - 10, py - radius - 10
            x2, y2 = px + radius + 10, py + radius + 10
        elif form in ("bar", "segment_bar"):
            sz = cfg.get("size", 0.2)
            size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
            bar_w = size_px + 80
            bar_h = max(60, int(size_px * 0.35)) + 50
            if rot in (90, 270):
                w_bar, h_bar = bar_h, bar_w
            else:
                w_bar, h_bar = bar_w, bar_h
            x1 = px - w_bar // 2 - 20
            y1 = py - h_bar // 2 - 20
            x2 = px + w_bar // 2 + 20
            y2 = py + h_bar // 2 + 20
        elif form in ("chart", "moving_map", "static_map", "map"):
            sz = cfg.get("size", cfg.get("w", 0.3))
            size_px = int(round(sz * canvas_w)) if sz <= 1.0 else int(round((sz / 100.0) * canvas_w))
            cw = size_px + 60
            ch = max(50, int(size_px * 0.45)) + 50
            x1 = px - cw // 2 - 20
            y1 = py - ch // 2 - 20
            x2 = px + cw // 2 + 20
            y2 = py + ch // 2 + 20
        elif key in ("time_block", "time_display") or "time" in key:
            x1 = px - 20
            y1 = py - 20
            x2 = px + int(canvas_w * 0.20) + 20
            y2 = py + int(canvas_h * 0.12) + 20
        else:
            fs_val = cfg.get("font_size", cfg.get("size", 0.02))
            fs = max(10, int(round(fs_val * min_dim)) if fs_val <= 1.0 else int(round((fs_val / 100.0) * min_dim)))
            text_w = max(int(canvas_w * 0.12), fs * 12)
            text_h = max(int(canvas_h * 0.06), fs * 3 + 20)
            x1 = px - 20
            y1 = py - 20
            x2 = px + text_w + 20
            y2 = py + text_h + 20

        bx = (max(0, x1), max(0, y1), min(canvas_w, x2), min(canvas_h, y2))
        indicator_declared[key] = {
            "center": (px, py), "rotation": rot, "form": form,
            "declared_bbox": bx, "declared_w": bx[2] - bx[0], "declared_h": bx[3] - bx[1],
            "declared_area": (bx[2] - bx[0]) * (bx[3] - bx[1]),
        }

    # 2. Render each indicator individually across all checkpoints to get actual alpha bbox
    indicator_actual = {}
    for key, decl in indicator_declared.items():
        cfg = enabled_indicators[key]
        union_box = None
        has_any_alpha = False
        cp_details = []

        for f_idx, t_dt, fd in frame_data_pts:
            # Single-indicator canvas
            single_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            single_layout = {"indicators": {key: cfg}, "custom_texts": []}
            res_img = compose_overlay(
                canvas_w, canvas_h, single_layout, font_path="",
                reuse_canvas=False,
                **fd
            )
            abox = res_img.getbbox()
            if abox is not None:
                has_any_alpha = True
                if union_box is None:
                    union_box = list(abox)
                else:
                    union_box[0] = min(union_box[0], abox[0])
                    union_box[1] = min(union_box[1], abox[1])
                    union_box[2] = max(union_box[2], abox[2])
                    union_box[3] = max(union_box[3], abox[3])
                cp_details.append((f_idx, abox, (abox[2]-abox[0])*(abox[3]-abox[1])))
            else:
                cp_details.append((f_idx, None, 0))

        if union_box:
            actual_w = union_box[2] - union_box[0]
            actual_h = union_box[3] - union_box[1]
            actual_area = actual_w * actual_h
        else:
            actual_w = actual_h = actual_area = 0
            union_box = (0, 0, 0, 0)

        is_phantom = not has_any_alpha
        decl_area = decl["declared_area"]
        waste_area = decl_area - actual_area
        waste_ratio = (decl_area / actual_area) if actual_area > 0 else float("inf")

        indicator_actual[key] = {
            "has_alpha": has_any_alpha,
            "is_phantom": is_phantom,
            "actual_union_bbox": tuple(union_box),
            "actual_w": actual_w,
            "actual_h": actual_h,
            "actual_area": actual_area,
            "waste_area": waste_area,
            "waste_ratio": waste_ratio,
            "checkpoints": cp_details,
        }

    # Print Table 1: Per-indicator declared vs actual
    print("\n--- TABELA 1: DECLARED BBOX VS ACTUAL ALPHA BBOX ---")
    print(f"{'Indicator':<25s} | {'Form':<10s} | {'Declared (WxH)':<16s} | {'Actual Union':<16s} | {'Decl Area':<10s} | {'Act Area':<10s} | {'Waste Ratio':<12s} | {'Status'}")
    print("-" * 125)
    sorted_waste = sorted(indicator_declared.keys(), key=lambda k: indicator_actual[k]["waste_area"], reverse=True)
    for k in sorted_waste:
        d = indicator_declared[k]
        a = indicator_actual[k]
        db = f"{d['declared_w']}x{d['declared_h']}"
        ab = f"{a['actual_w']}x{a['actual_h']}"
        status = "PHANTOM_BBOX" if a["is_phantom"] else ("OVERSIZED" if a["waste_ratio"] > 2.0 else "OK")
        w_str = f"{a['waste_ratio']:.1f}x" if a['actual_area'] > 0 else "INFINITE"
        print(f"{k:<25s} | {d['form']:<10s} | {db:<16s} | {ab:<16s} | {d['declared_area']:<10d} | {a['actual_area']:<10d} | {w_str:<12s} | {status}")

    # 3. Global BBox Edge Attribution
    gb_x1, gb_y1, gb_x2, gb_y2 = canvas_w, canvas_h, 0, 0
    left_causes, top_causes, right_causes, bottom_causes = [], [], [], []
    for k, d in indicator_declared.items():
        bx = d["declared_bbox"]
        if bx[0] < gb_x1: gb_x1 = bx[0]
        if bx[1] < gb_y1: gb_y1 = bx[1]
        if bx[2] > gb_x2: gb_x2 = bx[2]
        if bx[3] > gb_y2: gb_y2 = bx[3]

    for k, d in indicator_declared.items():
        bx = d["declared_bbox"]
        if bx[0] == gb_x1: left_causes.append(k)
        if bx[1] == gb_y1: top_causes.append(k)
        if bx[2] == gb_x2: right_causes.append(k)
        if bx[3] == gb_y2: bottom_causes.append(k)

    print("\n--- GLOBAL BBOX EDGE ATTRIBUTION ---")
    print(f"  Global BBox: ({gb_x1}, {gb_y1}) to ({gb_x2}, {gb_y2}) -> {gb_x2-gb_x1}x{gb_y2-gb_y1} ({(gb_x2-gb_x1)*(gb_y2-gb_y1)/(canvas_w*canvas_h)*100:.1f}%)")
    print(f"  LEFT edge   (x={gb_x1:4d}) caused by: {left_causes}")
    print(f"  TOP edge    (y={gb_y1:4d}) caused by: {top_causes}")
    print(f"  RIGHT edge  (x={gb_x2:4d}) caused by: {right_causes}")
    print(f"  BOTTOM edge (y={gb_y2:4d}) caused by: {bottom_causes}")

    # 4. Step-by-step Hierarchical Clustering Trace (to max_regions=3)
    print("\n--- HIERARCHICAL CLUSTERING TRACE ---")
    # Start with initial clusters with indicator tags
    clusters = []
    for k, d in indicator_declared.items():
        bx = d["declared_bbox"]
        clusters.append({
            "bbox": [bx[0], bx[1], bx[2], bx[3]],
            "indicators": [k],
        })

    merge_step = 1
    while len(clusters) > 3:
        best_pair = None
        best_waste = float("inf")
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                b1, b2 = clusters[i]["bbox"], clusters[j]["bbox"]
                mb = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
                ma = (mb[2] - mb[0]) * (mb[3] - mb[1])
                a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
                a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
                waste = ma - (a1 + a2)
                if waste < best_waste:
                    best_waste = waste
                    best_pair = (i, j)

        if best_pair is None:
            break
        i, j = best_pair
        c1, c2 = clusters[i], clusters[j]
        b1, b2 = c1["bbox"], c2["bbox"]
        mb = [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])]
        merged_inds = c1["indicators"] + c2["indicators"]
        print(f"  Merge {merge_step:2d}: '{c1['indicators']}' + '{c2['indicators']}'")
        print(f"           Box: [{mb[0]},{mb[1]},{mb[2]},{mb[3]}] ({mb[2]-mb[0]}x{mb[3]-mb[1]}) | Waste added: {best_waste:,} px")
        clusters.pop(j)
        clusters.pop(i)
        clusters.append({"bbox": mb, "indicators": merged_inds})
        merge_step += 1

    print("\n--- FINAL 3 REGIONS ---")
    for idx, c in enumerate(clusters):
        b = c["bbox"]
        w, h = b[2] - b[0], b[3] - b[1]
        print(f"  Region {idx}: {w}x{h} at ({b[0]},{b[1]}) | Area: {w*h:,} px ({w*h/(canvas_w*canvas_h)*100:.1f}%)")
        print(f"    Indicators ({len(c['indicators'])}): {c['indicators']}")

    # 5. MAX_REGIONS Evaluation (1 to 6)
    print("\n--- MAX_HUD_REGIONS EVALUATION (1 TO 6) ---")
    print(f"{'MAX_REGIONS':<12s} | {'Actual Regions':<14s} | {'Atlas WxH':<14s} | {'Area %':<10s} | {'MB/frame':<10s} | {'Packing Eff'}")
    print("-" * 80)
    for mr in range(1, 7):
        aw, ah, regs = get_layout_hud_regions(layout, canvas_w, canvas_h, max_regions=mr)
        slot_mb = (aw * ah * 4) / (1024 * 1024)
        area_pct = (aw * ah) / (canvas_w * canvas_h) * 100.0
        sum_reg_area = sum(r[4] * r[5] for r in regs)
        pack_eff = (sum_reg_area / (aw * ah)) * 100.0 if aw * ah > 0 else 0.0
        print(f"{mr:<12d} | {len(regs):<14d} | {f'{aw}x{ah}':<14s} | {f'{area_pct:.1f}%':<10s} | {f'{slot_mb:.2f} MB':<10s} | {pack_eff:.1f}%")

    # 6. Generate Diagnostic 1920x1080 Visual Image
    diag_img = Image.new("RGBA", (canvas_w, canvas_h), (20, 20, 25, 255))
    
    # Overlay actual composed frame 2700 at 40% opacity
    f2700_img = compose_overlay(canvas_w, canvas_h, layout, font_path="", **frame_data_pts[3][2])
    diag_img.alpha_composite(f2700_img)

    draw = ImageDraw.Draw(diag_img)
    
    # Colors for regions
    reg_colors = [(0, 255, 255), (255, 128, 0), (0, 255, 128), (255, 0, 255), (255, 255, 0), (128, 128, 255)]

    # Draw Final 3 Regions
    for idx, c in enumerate(clusters):
        b = c["bbox"]
        rc = reg_colors[idx % len(reg_colors)]
        draw.rectangle([b[0], b[1], b[2], b[3]], outline=rc, width=3)
        draw.text((b[0] + 8, b[1] + 8), f"REGION {idx}: {b[2]-b[0]}x{b[3]-b[1]} ({len(c['indicators'])} indicators)", fill=rc)

    # Draw individual declared bboxes (dashed/thin) and actual alpha bboxes
    for k in sorted_waste:
        d = indicator_declared[k]
        a = indicator_actual[k]
        db = d["declared_bbox"]
        ab = a["actual_union_bbox"]
        
        # Declared bbox in yellow
        draw.rectangle([db[0], db[1], db[2], db[3]], outline=(255, 255, 0, 100), width=1)
        # Actual alpha bbox in green (or red if phantom)
        if a["is_phantom"]:
            draw.text((db[0] + 4, db[1] + 20), f"{k} [PHANTOM]", fill=(255, 80, 80, 240))
        else:
            draw.rectangle([ab[0], ab[1], ab[2], ab[3]], outline=(50, 255, 50, 220), width=2)
            draw.text((db[0] + 4, db[1] + 4), f"{k}", fill=(200, 200, 200, 200))

    out_dir = Path("scratch/audit_diag")
    out_dir.mkdir(parents=True, exist_ok=True)
    diag_path = out_dir / "hud_atlas_geometry_map.png"
    diag_img.save(diag_path)
    print(f"\n[OK] Diagnostic visual geometry map saved to: {diag_path}")

    # Save full audit results to JSON
    audit_json = {
        "layout_indicators": indicator_declared,
        "actual_alpha": indicator_actual,
        "global_bbox": {
            "bbox": (gb_x1, gb_y1, gb_x2, gb_y2),
            "area_pct": (gb_x2-gb_x1)*(gb_y2-gb_y1)/(canvas_w*canvas_h)*100.0,
            "left_causes": left_causes, "top_causes": top_causes,
            "right_causes": right_causes, "bottom_causes": bottom_causes,
        },
        "final_3_regions": [
            {"region": idx, "bbox": c["bbox"], "w": c["bbox"][2]-c["bbox"][0], "h": c["bbox"][3]-c["bbox"][1], "indicators": c["indicators"]}
            for idx, c in enumerate(clusters)
        ],
    }
    with open("scratch/audit_etap5b3_results.json", "w") as f:
        json.dump(audit_json, f, indent=2)

if __name__ == "__main__":
    run_atlas_geometry_audit()
