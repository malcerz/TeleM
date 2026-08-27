import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_processed_cache import read_processed_cache, apply_processed_cache
from src.indicators.compositor import compose_overlay
from src.indicators.chart import _render_chart_indicator
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts

VIDEO = repo_root / "Video" / "GX030120.MP4"
FIT = repo_root / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
layout = json.load(open(repo_root / "def_layout.json", encoding="utf-8"))

tm = TelemetryDataManager()
processed = read_processed_cache(VIDEO)
if processed is not None:
    apply_processed_cache(tm, processed)
else:
    tm.load_gpmf_from_exiftool(VIDEO)
tm.load_fit(VIDEO, start_dt=tm.start_dt_utc, manual_path=FIT)

w, h = 3840, 2160
font_path = "arial.ttf"
fps = 30000.0 / 1001.0

compose_layout, map_above_layout, map_after_keys = _ordered_map_layout_parts(layout)

hr_cfg = map_above_layout["indicators"]["fit_heart_rate_text"]
hr_history = tm.get_history_for_key("fit_heart_rate_text")

print("=" * 90)
print("PHASE 6 & 7: CHART INTERNAL LINE-BY-LINE TIMING BREAKDOWN (300 CALLS)")
print("=" * 90)

substages = {
    "1. get_history_chart_background": [],
    "2. timestamp_binary_search_and_interpolation": [],
    "3. header_cache_lookup": [],
    "4. final_static_lookup": [],
    "5. cursor_tile_crop_and_draw": [],
    "6. value_tile_render": [],
    "7. clip_tile_and_return": [],
    "TOTAL_RENDER_CHART": [],
}

for frame_idx in range(300):
    t_sec = frame_idx / fps
    target_dt = tm.start_dt_utc + (frame_idx * (1.0 / fps)) if tm.start_dt_utc else None
    
    t0 = time.perf_counter()
    res, rx, ry, _ = _render_chart_indicator(
        canvas_w=w, canvas_h=h, layout=map_above_layout, font_path=font_path,
        key="fit_heart_rate_text", value=145.0, unit="BPM", label="HR",
        cfg=hr_cfg, min_dim=1080, outline=2, fs=24, font=None,
        val_min=0, val_max=200, ticks=5, thickness=2, size_px=120, ss=1,
        history_data=hr_history, split_mode=True, target_dt=target_dt
    )
    t1 = time.perf_counter()
    substages["TOTAL_RENDER_CHART"].append((t1 - t0) * 1000.0)

for k, v in substages.items():
    if v:
        print(f"  {k:<45}: AVG {np.mean(v):6.3f} ms | Median {np.median(v):6.3f} ms | P95 {np.percentile(v, 95):6.3f} ms")
