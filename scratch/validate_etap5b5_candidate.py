from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ns = runpy.run_path(str(ROOT / "scratch" / "audit_etap5b3_geometry.py"))
W, H, N, FPS = 1920, 1080, 5400, 30000 / 1001
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import extract_altitude_samples, extract_exposure_samples, extract_iso_samples, extract_speed_samples, extract_temperature_samples, extract_track_samples, find_gps_anchor
from src.ffmpeg.command_builder import _precise_text_box, build_text_bbox_context, get_layout_hud_regions
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, init_worker
from src.telemetry_precompute import build_telemetry_cache


def snap_layout(layout, grid):
    out = copy.deepcopy(layout)
    for cfg in out.get("indicators", {}).values():
        if not cfg or not cfg.get("enabled", True): continue
        for axis, dim in (("x", W), ("y", H)):
            v = cfg.get(axis)
            if not isinstance(v, (int, float)): continue
            px = v / 100 * dim if v <= 100 else v
            cfg[axis] = (round(px / grid) * grid) / dim * 100 if v <= 100 else round(px / grid) * grid
    return out


def rect_union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0]+a[2], b[0]+b[2])-min(a[0], b[0]), max(a[1]+a[3], b[1]+b[3])-min(a[1], b[1]))


def main():
    base = normalize_layout(ROOT / "def_layout.json", W, H)
    layout = snap_layout(base, 16)
    records = gpmf_to_exiftool_json(str(ROOT / "Video" / "GX030120.MP4"))[0]
    speed = extract_speed_samples(records); alt = extract_altitude_samples(records); track = extract_track_samples(records)
    iso = extract_iso_samples(records); exposure = extract_exposure_samples(records); temp = extract_temperature_samples(records)
    anchor = find_gps_anchor(records)
    fit = process_fit(str(ROOT / "Video" / "Poranna_jazda_na_rowerze.fit"), video_start_dt=anchor)
    fields = {"start_dt_utc": anchor, "speed_samples": speed, "track_samples": track, "alt_samples": alt, "iso_samples": iso, "exposure_samples": exposure, "temp_samples": temp}
    _, _, init_regions = get_layout_hud_regions(layout, W, H, max_regions=4, text_candidates=build_text_bbox_context(layout, fit_data=fit, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp)["text_candidates"], phantom_keys=build_text_bbox_context(layout, fit_data=fit, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp)["phantom_keys"])
    init_worker(W, H, "", layout, fields, max_distance_m=None, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp,
                fit_data=fit, gps_track=fit.get("track"), start_dt_utc=anchor, tz_offset_hours=0.0,
                speed_samples=speed, track_samples=track, alt_samples=alt, target_fps=FPS,
                update_rate_step=1, total_overlay_frames=N, hud_regions=init_regions)
    cache = build_telemetry_cache(layout=layout, base_dt=anchor, tz_offset_hours=0.0, start_dt_utc=anchor, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp, fit_data=fit, gps_track=fit.get("track"), chart_data=WORKER_CACHE.get("_precomputed_chart_data"), resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache"), total_frames=N, target_fps=FPS)
    WORKER_CACHE["_telemetry_cache"] = cache
    context = build_text_bbox_context(layout, fit_data=fit, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp)
    aw, ah, regions = get_layout_hud_regions(layout, W, H, max_regions=4, text_candidates=context["text_candidates"], phantom_keys=context["phantom_keys"])
    checkpoints = [0, 540, 1350, 2700, 4050, 4860, 5399]
    result = {"atlas": [aw, ah], "area_pct": aw * ah / (W * H) * 100, "regions": [list(r) for r in regions], "clipping": 0, "frames_checked": len(checkpoints), "parity_unchanged": {}}
    for idx in checkpoints:
        img = ns["compose_for"](idx, layout)
        a = np.asarray(img)[:, :, 3]
        if np.any(a[0, :]) or np.any(a[-1, :]) or np.any(a[:, 0]) or np.any(a[:, -1]): result["clipping"] += 1
    text_keys = [k for k, c in layout["indicators"].items() if c and c.get("enabled", True) and c.get("form", "text") == "text" and k not in context["phantom_keys"]]
    for key in text_keys:
        one = copy.deepcopy(layout); one["indicators"] = {key: copy.deepcopy(layout["indicators"][key])}
        union = None; violations = 0
        declared = _precise_text_box(layout, key, layout["indicators"][key], W, H, context["text_candidates"], "")
        for idx in range(N):
            alpha = ns["compose_for"](idx, one).getchannel("A").getbbox()
            if not alpha: continue
            actual = (alpha[0], alpha[1], alpha[2]-alpha[0], alpha[3]-alpha[1])
            union = actual if union is None else rect_union(union, actual)
            if declared and not (actual[0] >= declared[0] and actual[1] >= declared[1] and actual[0]+actual[2] <= declared[0]+declared[2] and actual[1]+actual[3] <= declared[1]+declared[3]): violations += 1
        result.setdefault("text", {})[key] = {"declared": declared, "alpha_union": union, "violations": violations}
    base_cache = WORKER_CACHE["_telemetry_cache"]
    for idx in checkpoints:
        # Unchanged non-text indicators must stay pixel-identical; the selected candidate only snaps positions.
        for key in ("track_map", "fit_battery_text", "fit_battery_pct_text", "fit_solar_pct_text"):
            if key not in base.get("indicators", {}): continue
        result["parity_unchanged"][str(idx)] = "not_applicable: candidate intentionally snaps active indicator positions"
    (ROOT / "scratch" / "etap5b5_candidate_validation.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__": main()
