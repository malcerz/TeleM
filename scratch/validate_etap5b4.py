from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ns = runpy.run_path(str(ROOT / "scratch" / "audit_etap5b3_geometry.py"))
W, H, N, FPS = 1920, 1080, 5400, 30000 / 1001

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import extract_altitude_samples, extract_exposure_samples, extract_iso_samples, extract_speed_samples, extract_temperature_samples, extract_track_samples, find_gps_anchor
from src.ffmpeg.command_builder import _precise_text_box, build_text_bbox_context, get_layout_hud_regions
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_samples, _resolve_cache_value, init_worker
from src.telemetry_precompute import build_telemetry_cache


def main():
    layout = normalize_layout(ROOT / "def_layout.json", W, H)
    records = gpmf_to_exiftool_json(str(ROOT / "Video" / "GX030120.MP4"))[0]
    speed = extract_speed_samples(records); alt = extract_altitude_samples(records); track = extract_track_samples(records)
    iso = extract_iso_samples(records); exposure = extract_exposure_samples(records); temp = extract_temperature_samples(records)
    anchor = find_gps_anchor(records)
    fit = process_fit(str(ROOT / "Video" / "Poranna_jazda_na_rowerze.fit"), video_start_dt=anchor)
    fields = {"start_dt_utc": anchor, "speed_samples": speed, "track_samples": track, "alt_samples": alt, "iso_samples": iso, "exposure_samples": exposure, "temp_samples": temp}
    old_aw, old_ah, old_regions = get_layout_hud_regions(layout, W, H, max_regions=3)
    init_worker(W, H, "", layout, fields, None, iso, exposure, temp, None, None, None, None, None, None, None, fit, fit.get("track"), anchor, 0.0, speed, track, alt, FPS, 1, N, None, 0, None, old_regions, False)
    cache = build_telemetry_cache(layout=layout, base_dt=anchor, tz_offset_hours=0.0, start_dt_utc=anchor, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp, fit_data=fit, gps_track=fit.get("track"), chart_data=WORKER_CACHE.get("_precomputed_chart_data"), resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache"), total_frames=N, target_fps=FPS)
    WORKER_CACHE["_telemetry_cache"] = cache
    context = build_text_bbox_context(layout, fit_data=fit, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp)
    new_aw, new_ah, new_regions = get_layout_hud_regions(layout, W, H, max_regions=3, text_candidates=context["text_candidates"], phantom_keys=context["phantom_keys"], font_path="")

    checkpoints = [0, 540, 1350, 2700, 4050, 4860, 5399]
    text_keys = [k for k, cfg in layout["indicators"].items() if cfg and cfg.get("enabled", True) and cfg.get("form", "text") == "text"]
    coverage = {}
    for key in text_keys:
        cfg = layout["indicators"][key]
        declared = None
        for r in new_regions:
            if r[0] <= 10**9:
                pass
        one = copy.deepcopy(layout); one["indicators"] = {key: copy.deepcopy(cfg)}
        union = None
        for idx in checkpoints:
            img = ns["compose_for"](idx, one)
            alpha = img.getchannel("A").getbbox()
            if alpha:
                b = (alpha[0], alpha[1], alpha[2] - alpha[0], alpha[3] - alpha[1])
                union = b if union is None else ns["rect_union"](union, b)
        coverage[key] = {"union_alpha": union, "phantom": key in context["phantom_keys"]}
        if key not in context["phantom_keys"]:
            declared = _precise_text_box(layout, key, cfg, W, H, context["text_candidates"], "")
            full_union = None
            violations = 0
            for idx in range(N):
                img = ns["compose_for"](idx, one)
                alpha = img.getchannel("A").getbbox()
                if not alpha:
                    continue
                actual = (alpha[0], alpha[1], alpha[2] - alpha[0], alpha[3] - alpha[1])
                full_union = actual if full_union is None else ns["rect_union"](full_union, actual)
                if declared and not (
                    actual[0] >= declared[0] and actual[1] >= declared[1]
                    and actual[0] + actual[2] <= declared[0] + declared[2]
                    and actual[1] + actual[3] <= declared[1] + declared[3]
                ):
                    violations += 1
            coverage[key]["declared_bbox"] = declared
            coverage[key]["full_timeline_alpha_union"] = full_union
            coverage[key]["full_timeline_violations"] = violations

    # Reconstruct the atlas onto a full transparent canvas at 0/25/50/75/100%.
    parity = {}
    for idx in [0, 1350, 2700, 4050, 5399]:
        full = ns["compose_for"](idx, layout)
        atlas = Image.new("RGBA", (new_aw, new_ah), (0, 0, 0, 0))
        for dx, dy, ax, ay, rw, rh in new_regions:
            atlas.paste(full.crop((dx, dy, dx + rw, dy + rh)), (ax, ay))
        rebuilt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for dx, dy, ax, ay, rw, rh in new_regions:
            rebuilt.alpha_composite(atlas.crop((ax, ay, ax + rw, ay + rh)), (dx, dy))
        import numpy as np
        a, b = np.asarray(full), np.asarray(rebuilt)
        diff = np.abs(a.astype(int) - b.astype(int))
        parity[str(idx)] = {"max_diff": int(diff.max()), "different_pixels": int(np.any(diff != 0, axis=2).sum())}

    result = {"old": {"atlas_w": old_aw, "atlas_h": old_ah, "area_pct": old_aw * old_ah / (W * H) * 100}, "new": {"atlas_w": new_aw, "atlas_h": new_ah, "area_pct": new_aw * new_ah / (W * H) * 100, "phantom_keys": sorted(context["phantom_keys"]), "regions": new_regions}, "coverage": coverage, "parity": parity, "candidates": context["text_candidates"]}
    out = ROOT / "scratch" / "etap5b4_validation.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"old": result["old"], "new": result["new"], "parity": parity, "coverage": coverage}, indent=2))


if __name__ == "__main__":
    main()
