from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import extract_altitude_samples, extract_exposure_samples, extract_iso_samples, extract_speed_samples, extract_temperature_samples, extract_track_samples, find_gps_anchor
from src.ffmpeg.command_builder import build_text_bbox_context, get_layout_hud_regions
from src.ffmpeg.streaming import _snap_nvidia_hud_layout
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, init_worker
from src.ffmpeg.frame_renderer import render_overlay_frame, _direct_region_members
from src.telemetry_precompute import build_telemetry_cache

W, H, N, FPS = 1920, 1080, 5400, 30000 / 1001


def setup():
    records = gpmf_to_exiftool_json(str(ROOT / "Video" / "GX030120.MP4"))[0]
    speed = extract_speed_samples(records); alt = extract_altitude_samples(records); track = extract_track_samples(records)
    iso = extract_iso_samples(records); exposure = extract_exposure_samples(records); temp = extract_temperature_samples(records)
    anchor = find_gps_anchor(records); fit = process_fit(str(ROOT / "Video" / "Poranna_jazda_na_rowerze.fit"), video_start_dt=anchor)
    layout = _snap_nvidia_hud_layout(normalize_layout(ROOT / "def_layout.json", W, H), W, H, 16)
    context = build_text_bbox_context(layout, fit_data=fit, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp)
    aw, ah, regions = get_layout_hud_regions(layout, W, H, max_regions=4, text_candidates=context["text_candidates"], phantom_keys=context["phantom_keys"])
    layout["_nvidia_direct_region"] = True; layout["_nvidia_phantom_keys"] = tuple(sorted(context["phantom_keys"])); layout["_nvidia_atlas_size"] = (aw, ah)
    fields = {"start_dt_utc": anchor, "speed_samples": speed, "track_samples": track, "alt_samples": alt, "iso_samples": iso, "exposure_samples": exposure, "temp_samples": temp}
    init_worker(W, H, "", layout, fields, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp, fit_data=fit, gps_track=fit.get("track"), start_dt_utc=anchor, tz_offset_hours=2, speed_samples=speed, track_samples=track, alt_samples=alt, target_fps=FPS, update_rate_step=1, total_overlay_frames=N, hud_regions=regions)
    cache = build_telemetry_cache(layout=layout, base_dt=anchor, tz_offset_hours=2, start_dt_utc=anchor, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp, fit_data=fit, gps_track=fit.get("track"), chart_data=WORKER_CACHE.get("_precomputed_chart_data"), resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache"), total_frames=N, target_fps=FPS)
    WORKER_CACHE["_telemetry_cache"] = cache
    return layout, regions, anchor, speed, track, alt


def main():
    layout, regions, anchor, speed, track, alt = setup()
    checkpoints = [0, 540, 1350, 2700, 4050, 4860, 5399]
    result = {"atlas": list(layout["_nvidia_atlas_size"]), "regions": [list(r) for r in regions], "ownership": [sorted(x) for x in (_direct_region_members(layout, regions) or [])], "parity": {}}
    for idx in checkpoints:
        WORKER_CACHE.pop("_prev_frame_data", None); WORKER_CACHE.pop("_prev_atlas_img", None)
        layout["_nvidia_direct_region"] = False
        legacy = render_overlay_frame(idx, anchor, 2, speed, track, alt, FPS, 1)
        WORKER_CACHE.pop("_prev_frame_data", None); WORKER_CACHE.pop("_prev_atlas_img", None)
        layout["_nvidia_direct_region"] = True
        direct = render_overlay_frame(idx, anchor, 2, speed, track, alt, FPS, 1)
        a, b = np.asarray(legacy), np.asarray(direct)
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
        result["parity"][str(idx)] = {"max_diff": int(diff.max()), "different_pixels": int(np.any(diff != 0, axis=2).sum()), "shape_legacy": list(a.shape), "shape_direct": list(b.shape)}
    (ROOT / "scratch" / "etap5c_direct_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
