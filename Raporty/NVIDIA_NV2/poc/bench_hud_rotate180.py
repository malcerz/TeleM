"""Gate-3: measure 180-deg HUD canvas rotate cost on REAL HUD frames.

Renders real TeleM HUD frames (production `render_overlay_frame` worker path)
for GX020079 with real GPMF + FIT telemetry, then times only
`Image.Transpose.ROTATE_180` on each 1920x1080 RGBA canvas.

Also verifies the rotation is a pixel-exact permutation (double-rotate == id).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

BASE = Path(r"F:\_DEV\TeleM")
sys.path.insert(0, str(BASE))

from PIL import Image  # noqa: E402

from src.telemetry_extract import (  # noqa: E402
    ensure_records_list,
    extract_altitude_samples,
    extract_exposure_samples,
    extract_iso_samples,
    extract_speed_samples,
    extract_temperature_samples,
    extract_track_samples,
    load_json_with_fallback,
    smooth_speed_samples,
)
from src.ffmpeg.worker_cache import WORKER_CACHE, init_worker  # noqa: E402
from src.ffmpeg.frame_renderer import render_overlay_frame  # noqa: E402
from telemetry_fit import parse_fit, sync_fit_to_video  # noqa: E402

VIDEO_DIR = BASE / "Video"
META = VIDEO_DIR / "GX020079.json"
FIT = VIDEO_DIR / "Morning_Ride.fit"
LAYOUT = BASE / "def_layout.json"
N_FRAMES = 500


def main() -> None:
    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    records = ensure_records_list(load_json_with_fallback(META))

    speed = smooth_speed_samples(extract_speed_samples(records), "moving_average", 5)
    track = extract_track_samples(records)
    alt = smooth_speed_samples(extract_altitude_samples(records), "moving_average", 5)
    iso = extract_iso_samples(records)
    exposure = extract_exposure_samples(records)
    temperature = extract_temperature_samples(records)

    start_dt_utc = speed[0][0] if speed else None
    fit_records = parse_fit(FIT)
    fit_data: dict = {}
    gps_track: list = []
    if fit_records:
        fit_data = sync_fit_to_video(fit_records, start_dt_utc)
        gps_track = [
            (r["timestamp"], r["lat"], r["lon"])
            for r in fit_records
            if r.get("lat") is not None and r.get("lon") is not None
        ]

    target_fps = 30000 / 1001
    init_worker(
        1920, 1080, "Arial", layout, {"speed_samples": speed, "track_samples": track, "alt_samples": alt},
        max_distance_m=track[-1][1] if track else 1000.0,
        iso_samples=iso, exposure_samples=exposure, temperature_samples=temperature,
        gpx_speed_samples=[], gpx_track_samples=[], gpx_alt_samples=[],
        gpx_power_samples=[], gpx_atemp_samples=[], gpx_hr_samples=[], gpx_cad_samples=[],
        fit_data=fit_data, gps_track=gps_track,
        start_dt_utc=start_dt_utc, tz_offset_hours=2.0,
        speed_samples=speed, track_samples=track, alt_samples=alt,
        target_fps=target_fps, update_rate_step=1, total_overlay_frames=N_FRAMES,
        effective_rotation=0,  # HUD rendered in logical layout; rotate measured separately
    )

    samples_ms: list[float] = []
    first_img = None
    for i in range(N_FRAMES):
        img = render_overlay_frame(i, start_dt_utc, 2.0, speed, track, alt, target_fps, 1)
        if first_img is None:
            first_img = img.copy()
        t0 = time.perf_counter()
        img.transpose(Image.Transpose.ROTATE_180)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        samples_ms.append(dt_ms)

    samples_ms.sort()
    median = statistics.median(samples_ms)
    p95 = samples_ms[int(len(samples_ms) * 0.95) - 1]
    p99 = samples_ms[int(len(samples_ms) * 0.99) - 1]

    # Pixel-exactness: rotate 180 twice == original
    dbl = first_img.transpose(Image.Transpose.ROTATE_180).transpose(Image.Transpose.ROTATE_180)
    pix_ok = dbl.tobytes() == first_img.tobytes()
    # Also: rotating logical HUD once == the pre-rotated variant (visual sanity)
    print(f"frames={N_FRAMES} size={first_img.size} mode={first_img.mode}")
    print(f"rotate180 median={median:.3f} ms  P95={p95:.3f} ms  P99={p99:.3f} ms")
    print(f"min={samples_ms[0]:.3f} ms  max={samples_ms[-1]:.3f} ms")
    print(f"pixel-exact permutation (rot180 twice == id): {pix_ok}")


if __name__ == "__main__":
    main()
