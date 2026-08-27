import os
import sys
import time
import json
from pathlib import Path
from datetime import timedelta
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.moving_map import render_map_working_image, _map_render_plan
from src.moving_map import MovingMapRenderer, track_up_rotation_degrees, track_up_working_size

VIDEO = Path("Video/GX010115.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
PRESET = Path("presets/cycling_dashboard_v10.json")

def main():
    with open(PRESET, "r", encoding="utf-8") as f:
        layout = json.load(f)

    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    gps_track = telemetry.get_gps_track_for_source("fit")

    target_fps = 59.94005994
    num_frames = 1131

    times_total = []
    times_render = []
    times_tobytes = []
    grid_cache_hits = 0
    grid_cache_misses = 0

    print(f"Profiling map_cpu_upload across {num_frames} frames in 4K (3840x2160)...")
    
    from src.telemetry_heading import interpolate_heading
    for i in range(num_frames):
        cur_time_s = i / target_fps
        c_dt = telemetry.start_dt_utc + timedelta(seconds=cur_time_s)
        heading = interpolate_heading(telemetry.heading_samples, c_dt)

        t0 = time.perf_counter()
        map_img, map_dst = render_map_working_image(
            3840, 2160, layout, "track_map",
            gps_track, target_dt=c_dt, current_position=None,
            map_heading=heading,
        )
        t_render = time.perf_counter() - t0

        t1 = time.perf_counter()
        if map_img is not None:
            map_bytes = map_img.tobytes("raw", "RGBA")
        t_tobytes = time.perf_counter() - t1

        t_tot = time.perf_counter() - t0
        times_total.append(t_tot * 1000.0)
        times_render.append(t_render * 1000.0)
        times_tobytes.append(t_tobytes * 1000.0)

    print(f"map_cpu_upload TOTAL AVG: {sum(times_total)/len(times_total):.3f} ms (Min: {min(times_total):.3f} ms, Max: {max(times_total):.3f} ms)")
    print(f"  render_map_working_image AVG: {sum(times_render)/len(times_render):.3f} ms")
    print(f"  map_img.tobytes('RGBA')  AVG: {sum(times_tobytes)/len(times_tobytes):.3f} ms")

if __name__ == "__main__":
    main()
