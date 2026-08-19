"""Diagnose map geometry and inspect why the map appears as a stripe."""
import json
import sys
from pathlib import Path
from PIL import Image
import numpy as np

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, extract_altitude_samples, extract_exposure_samples,
    extract_iso_samples, extract_speed_samples, extract_temperature_samples,
    extract_track_samples, interpolate_value, load_json_with_fallback,
    smooth_speed_samples
)
from src.indicators.moving_map import render_map_working_image

def inspect_map_pixels():
    fit_path = root / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    json_path = root / "Video" / "GX030120.json"
    records = ensure_records_list(load_json_with_fallback(json_path))
    tm = TelemetryDataManager(
        extract_speed_samples, extract_altitude_samples, extract_track_samples,
        extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
        smooth_speed_samples, interpolate_value
    )
    tm.load_gpmf_records(records)
    tm.load_fit(fit_path)
    tm.start_dt_utc = tm.speed_samples[0][0]

    layout = json.load(open(root / "def_layout.json", encoding="utf-8"))
    gps_track = tm.get_gps_track_for_source("fit")
    print(f"GPS track points: {len(gps_track) if gps_track else 0}")
    
    curr_dt = tm.start_dt_utc
    map_img, dst_bbox = render_map_working_image(
        3840, 2160, layout, "track_map",
        gps_track, target_dt=curr_dt,
        current_position=0.0
    )
    if map_img:
        print(f"render_map_working_image -> size={map_img.size}, mode={map_img.mode}, dst_bbox={dst_bbox}")
        map_img.save(root / "scratch" / "gui_export_inspection" / "cpu_working_map.png")
    else:
        print("render_map_working_image returned None!")

    # Check the actual video exported frame
    extracted_frame_path = root / "scratch" / "gui_export_inspection" / "frame_0030.png"
    if extracted_frame_path.exists():
        vid_img = Image.open(extracted_frame_path)
        # Crop the exact dst_bbox (3035, 137, 691, 691)
        x, y, w, h = dst_bbox if dst_bbox else (3035, 137, 691, 691)
        map_vid_crop = vid_img.crop((x, y, x + w, y + h))
        map_vid_crop.save(root / "scratch" / "gui_export_inspection" / "vid_dst_bbox_crop.png")
        arr = np.array(map_vid_crop)
        print(f"Video crop at dst_bbox ({x}, {y}, {w}, {h}): min={arr.min()}, max={arr.max()}, mean={arr.mean():.2f}")

if __name__ == "__main__":
    inspect_map_pixels()
