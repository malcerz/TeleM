import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.telemetry_extract import ensure_records_list, load_json_with_fallback
from src.indicators.text import _render_text_indicator
from src.indicators.helpers import _STATIC_CACHE, load_font

VIDEO = Path("Video/GX030120.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
layout = json.load(open("def_layout.json", encoding="utf-8"))

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
else:
    tm.load_gpmf_from_exiftool(VIDEO)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

w, h = 3840, 2160
font_path = "arial.ttf"

# Check string variability for iso_text, exposure_text, temp_text across 2001 frames
fps = 30000.0 / 1001.0
text_keys = ["iso_text", "exposure_text", "temp_text"]
samples = {
    "iso_text": tm.iso_samples,
    "exposure_text": tm.exposure_samples,
    "temp_text": tm.temperature_samples,
}

print("=" * 80)
print("STRING VARIABILITY ANALYSIS (2001 FRAMES):")
print("=" * 80)

from datetime import timedelta
for key in text_keys:
    cfg = layout["indicators"].get(key, {})
    s_list = samples.get(key, [])
    strings = []
    for i in range(2001):
        dt = tm.start_dt_utc + timedelta(seconds=i / fps) if tm.start_dt_utc else None
        # Interpolate
        val = None
        if s_list:
            t_sec = i / fps
            idx = min(len(s_list) - 1, int(t_sec * 10))
            val = s_list[idx][1] if len(s_list[idx]) >= 2 else s_list[idx][0]
        v_str = f"{val:.1f}" if val is not None else "--"
        label = cfg.get("label", "")
        txt = f"{label}: {v_str}" if label else v_str
        strings.append(txt)
    
    unique_vals = set(strings)
    runs = 1
    for i in range(1, len(strings)):
        if strings[i] != strings[i-1]:
            runs += 1
    avg_run = len(strings) / runs
    print(f"{key:<15}: Total Frames={len(strings)}, Unique Strings={len(unique_vals)}, Runs={runs}, Avg Run Length={avg_run:.1f} frames, Repeat Ratio={1.0 - len(unique_vals)/len(strings):.3f}")
