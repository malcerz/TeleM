from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ["AMD_OVERLAY_PROFILE"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import extract_altitude_samples, extract_exposure_samples, extract_iso_samples, extract_speed_samples, extract_temperature_samples, extract_track_samples, find_gps_anchor
from src.ffmpeg.command_builder import build_text_bbox_context, get_layout_hud_regions
from src.ffmpeg.streaming import _snap_nvidia_hud_layout
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value, init_worker
from src.ffmpeg.frame_renderer import render_overlay_frame
from src.telemetry_precompute import build_telemetry_cache
from src.indicators.profiling import get_overlay_profiler

W, H, N, FPS = 1920, 1080, 5400, 30000 / 1001


def pct(values, p):
    values = sorted(values)
    pos = (len(values) - 1) * p
    lo, hi = int(pos), min(len(values) - 1, int(pos) + 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def main():
    records = gpmf_to_exiftool_json(str(ROOT / "Video" / "GX030120.MP4"))[0]
    speed = extract_speed_samples(records); alt = extract_altitude_samples(records); track = extract_track_samples(records)
    iso = extract_iso_samples(records); exposure = extract_exposure_samples(records); temp = extract_temperature_samples(records)
    anchor = find_gps_anchor(records)
    fit = process_fit(str(ROOT / "Video" / "Poranna_jazda_na_rowerze.fit"), video_start_dt=anchor)
    layout = _snap_nvidia_hud_layout(normalize_layout(ROOT / "def_layout.json", W, H), W, H, 16)
    context = build_text_bbox_context(layout, fit_data=fit, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp)
    _, _, regions = get_layout_hud_regions(layout, W, H, max_regions=4, text_candidates=context["text_candidates"], phantom_keys=context["phantom_keys"])
    if os.environ.get("TELEM_ETAP5C_DIRECT"):
        layout["_nvidia_direct_region"] = True
        layout["_nvidia_phantom_keys"] = tuple(sorted(context["phantom_keys"]))
        layout["_nvidia_atlas_size"] = (1900, 762)
    init_worker(W, H, "", layout, {"start_dt_utc": anchor, "speed_samples": speed, "track_samples": track, "alt_samples": alt, "iso_samples": iso, "exposure_samples": exposure, "temp_samples": temp}, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp, fit_data=fit, gps_track=fit.get("track"), start_dt_utc=anchor, tz_offset_hours=2, speed_samples=speed, track_samples=track, alt_samples=alt, target_fps=FPS, update_rate_step=1, total_overlay_frames=N, hud_regions=regions)
    cache = build_telemetry_cache(layout=layout, base_dt=anchor, tz_offset_hours=2, start_dt_utc=anchor, speed_samples=speed, track_samples=track, alt_samples=alt, iso_samples=iso, exposure_samples=exposure, temperature_samples=temp, fit_data=fit, gps_track=fit.get("track"), chart_data=WORKER_CACHE.get("_precomputed_chart_data"), resolve_cache_value=_resolve_cache_value, _range_cache=WORKER_CACHE.get("_prep_cache"), total_frames=N, target_fps=FPS)
    WORKER_CACHE["_telemetry_cache"] = cache
    profiler = get_overlay_profiler()
    # Warm-up is excluded; frames are intentionally spread through the timeline.
    for i in range(40): render_overlay_frame(i, anchor, 2, speed, track, alt, FPS, 1)
    profiler._frames.clear()
    timings = []
    for i in range(40, 340):
        profiler.start_frame(i, W, H)
        t0 = time.perf_counter(); img = render_overlay_frame(i, anchor, 2, speed, track, alt, FPS, 1); timings.append((time.perf_counter()-t0)*1000)
        # Reproduce the SHM-side conversion/copy without creating a process pool.
        import numpy as np
        shm = np.empty((img.height, img.width, 4), dtype=np.uint8)
        t1 = time.perf_counter(); arr = np.asarray(img); np.copyto(shm, arr); timings[-1] += (time.perf_counter()-t1)*1000
        profiler.finish_frame()
    result = {"frames": len(timings), "worker_like_ms": {"avg": statistics.fmean(timings), "median": statistics.median(timings), "p95": pct(timings,.95)}, "regions": [list(r) for r in regions], "atlas": [max(r[2]+r[4] for r in regions), max(r[3]+r[5] for r in regions)], "profiler": profiler.summary()}
    mode = os.environ.get("AMD_PIL_COMPOSITE_MODE", "OPTIMIZED").lower()
    profile_name = f"etap5d_{mode}_profile.json"
    (ROOT / "scratch" / profile_name).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"worker_like_ms": result["worker_like_ms"], "atlas": result["atlas"], "profiler_metrics": result["profiler"]["metrics"]}, indent=2))


if __name__ == "__main__": main()
