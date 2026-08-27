import os
import sys
import time
import json
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.moving_map import render_map_working_image, ensure_map_tiles_cached
from src.moving_map import set_map_network_allowed, reset_map_tile_stats, get_map_tile_stats

PRESET = Path("presets/cycling_dashboard_v10.json")
VIDEO = Path("Video/GX010115.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

with open(PRESET, "r", encoding="utf-8") as f:
    layout = json.load(f)

telemetry = TelemetryDataManager()
telemetry.load_gpmf_from_exiftool(VIDEO)
telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
gps_track = telemetry.get_gps_track_for_source("fit")

# Ensure tiles are cached
info = ensure_map_tiles_cached(3840, 2160, layout, "track_map", gps_track)
print(f"Preload info: {info}")

set_map_network_allowed(False)
reset_map_tile_stats()

dur = (gps_track[-1][0].timestamp() - gps_track[0][0].timestamp())

timings = []
for i in range(100):
    current_pos = i / 1131.0
    t0 = time.perf_counter()
    img, dst = render_map_working_image(
        3840, 2160, layout, "track_map", gps_track,
        current_position=current_pos,
        map_heading=45.0 + i * 0.1,
    )
    if img:
        b = img.tobytes("raw", "RGBA")
    t1 = time.perf_counter()
    timings.append((t1 - t0) * 1000.0)

print(f"Map working image 100 frames: AVG={sum(timings)/len(timings):.3f} ms, Min={min(timings):.3f} ms, Max={max(timings):.3f} ms")
print(f"Map Tile stats: {get_map_tile_stats()}")
