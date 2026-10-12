"""Rigorously verify 1000 consecutive frames of dirty region compositing vs full-frame ground truth.

Loads:
- Real FIT telemetry: C:\\_DEV\\_SPORTCAMHUD_ETAP_4B_RESULTS_20261012\\fit\\24609739177.fit
- Production layout: def_layout.json (17 indicators, effects ON)
- 1000 frames from 120.0s @ 29.970 FPS.

On each frame:
1. Generates full-frame composed_img (Ground Truth).
2. Computes dirty_rects using amd_native_exporter logic.
3. Updates persistent canvas using ONLY the dirty_rect slices.
4. Compares persistent_canvas vs composed_img across all 3840x2160 pixels.
5. Records max_diff, MAE, diff_pixels, upload_bytes, rect counts.
"""

from __future__ import annotations
import sys
import json
import time
from datetime import timedelta
from pathlib import Path
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import numpy as np
from PIL import Image

from src.gui.telemetry_manager import TelemetryDataManager
from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
from src.indicators.compositor import compose_overlay
from src.indicators.gauge import get_gauge_dynamic_info, clear_gauge_cache
from src.indicators.bar import clear_bar_cache
from src.indicators.effects import clear_effects_cache
from src.ffmpeg.amd_native_exporter import (
    _dirty_rects_from_bboxes, _clip_rect, _resolve_gauge_layout_key
)

def run_1000_frames_dirty_region_test():
    clear_gauge_cache()
    clear_bar_cache()
    clear_effects_cache()

    fit_path = Path(r"C:\_DEV\_SPORTCAMHUD_ETAP_4B_RESULTS_20261012\fit\24609739177.fit")
    layout_path = repo_root / "def_layout.json"
    with open(layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)

    print(f"Loading telemetry from {fit_path}...")
    tm = TelemetryDataManager()
    tm.load_fit(str(fit_path), manual_path=fit_path)
    fit_field_plan = build_active_fit_field_plan(layout, (tm.fit_data or {}).keys())

    fps = 30000.0 / 1001.0
    start_sec = 120.0
    num_frames = 1000
    width, height = 3840, 2160

    print(f"Starting 1000-frame dirty region parity verification at {width}x{height}...")

    # Persistent canvas simulating D3D11 persistent HUD texture
    persistent_canvas = np.zeros((height, width, 4), dtype=np.uint8)
    previous_bboxes_holder = [{}]
    gauge_layout_key = _resolve_gauge_layout_key(layout)
    dirty_max_rects = 8
    gauge_full_refresh_n = 30

    stats = {
        "total_frames": num_frames,
        "max_diff_across_all": 0,
        "frames_with_diff": 0,
        "total_bytes_uploaded": 0,
        "avg_bytes_per_frame": 0,
        "max_bytes_in_frame": 0,
        "min_bytes_in_frame": float("inf"),
        "avg_rects_per_frame": 0.0,
        "diff_samples": [],
    }

    t0 = time.perf_counter()
    rect_count_sum = 0

    for idx in range(num_frames):
        current_time = start_sec + (idx / fps)
        target_dt = tm.start_dt_utc + timedelta(seconds=current_time) if tm.start_dt_utc else None

        frame_kwargs = prepare_overlay_frame_data(
            layout=layout,
            target_dt=target_dt,
            start_dt_utc=tm.start_dt_utc,
            tz_offset_hours=2,
            speed_samples=tm.speed_samples,
            track_samples=tm.track_samples,
            alt_samples=tm.alt_samples,
            iso_samples=tm.iso_samples,
            exposure_samples=tm.exposure_samples,
            temperature_samples=tm.temperature_samples,
            fit_data=tm.fit_data,
            gps_track=tm.get_gps_track_for_source("fit"),
            fit_field_plan=fit_field_plan,
        )

        _bboxes = {}
        _compose_breakdown = {}
        composed_img = compose_overlay(
            canvas_w=width, canvas_h=height, layout=layout, font_path="arial.ttf",
            _bboxes=_bboxes, breakdown=_compose_breakdown,
            **frame_kwargs
        )

        clamped_bboxes = dict(_bboxes)
        if idx == 0:
            # Frame 0: Full HUD upload
            persistent_canvas[:] = np.asarray(composed_img)
            upload_bytes = width * height * 4
            dirty_rects = [(0, 0, width, height)]
            previous_bboxes_holder[0] = dict(_bboxes)
        else:
            # Clamping logic from Etap 5A
            if idx % max(1, gauge_full_refresh_n) != 0:
                for _gk in list(clamped_bboxes.keys()):
                    _ginfo = get_gauge_dynamic_info(_gk)
                    if _ginfo and _ginfo.get("supported"):
                        _nb, _tb = _ginfo.get("needle_bbox"), _ginfo.get("text_bbox")
                        _sboxes = [_b for _b in [_nb, _tb] if _b is not None]
                        if _sboxes:
                            _orig_box = clamped_bboxes[_gk]
                            _sx0 = min(_b[0] for _b in _sboxes)
                            _sy0 = min(_b[1] for _b in _sboxes)
                            _sx1 = max(_b[2] for _b in _sboxes)
                            _sy1 = max(_b[3] for _b in _sboxes)
                            clamped_bboxes[_gk] = (
                                _orig_box[0] + int(_sx0),
                                _orig_box[1] + int(_sy0),
                                int(_sx1 - _sx0),
                                int(_sy1 - _sy0),
                            )

            dirty_rects = _dirty_rects_from_bboxes(
                previous_bboxes_holder[0], clamped_bboxes,
                width, height, dirty_max_rects,
            )

            clipped_dirty_rects = []
            for _r in dirty_rects:
                _cr = _clip_rect(_r, width, height, pad=0)
                if _cr is not None and _cr not in clipped_dirty_rects:
                    clipped_dirty_rects.append(_cr)
            dirty_rects = clipped_dirty_rects

            # Update persistent canvas with only dirty rect slices
            comp_arr = np.asarray(composed_img)
            upload_bytes = 0
            for rx, ry, rw, rh in dirty_rects:
                persistent_canvas[ry:ry+rh, rx:rx+rw] = comp_arr[ry:ry+rh, rx:rx+rw]
                upload_bytes += rw * rh * 4

            previous_bboxes_holder[0] = dict(clamped_bboxes)

        stats["total_bytes_uploaded"] += upload_bytes
        if idx > 0:
            stats["max_bytes_in_frame"] = max(stats["max_bytes_in_frame"], upload_bytes)
            stats["min_bytes_in_frame"] = min(stats["min_bytes_in_frame"], upload_bytes)
            rect_count_sum += len(dirty_rects)

        # Compare persistent_canvas with composed_img across entire 4K frame
        diff = np.abs(persistent_canvas.astype(int) - np.asarray(composed_img).astype(int))
        frame_max_diff = int(np.max(diff))
        stats["max_diff_across_all"] = max(stats["max_diff_across_all"], frame_max_diff)

        if frame_max_diff > 0:
            stats["frames_with_diff"] += 1
            diff_cnt = int(np.sum(np.any(diff > 0, axis=-1)))
            ys, xs = np.where(np.any(diff > 0, axis=-1))
            bbox = [int(np.min(xs)), int(np.min(ys)), int(np.max(xs)), int(np.max(ys))]
            if len(stats["diff_samples"]) < 10:
                stats["diff_samples"].append({
                    "frame": idx,
                    "max_diff": frame_max_diff,
                    "diff_pixels": diff_cnt,
                    "diff_bbox": bbox,
                })

        if (idx + 1) % 100 == 0 or idx == num_frames - 1:
            avg_b = (stats["total_bytes_uploaded"] - (width * height * 4)) / max(1, idx)
            print(f"Frame {idx+1:>4}/1000 | MaxDiff: {stats['max_diff_across_all']} | DiffFrames: {stats['frames_with_diff']} | AvgUpload: {avg_b/1024:.1f} KB/frame")

    elapsed = time.perf_counter() - t0
    stats["avg_bytes_per_frame"] = (stats["total_bytes_uploaded"] - (width * height * 4)) / (num_frames - 1)
    stats["avg_rects_per_frame"] = rect_count_sum / (num_frames - 1)
    stats["elapsed_sec"] = elapsed
    stats["fps_simulated"] = num_frames / elapsed

    print("\n" + "=" * 60)
    print(f"1000-FRAME DIRTY REGION TEST SUMMARY:")
    print(f"Max pixel diff across all 1000 frames: {stats['max_diff_across_all']}")
    print(f"Frames with any difference: {stats['frames_with_diff']} / {num_frames}")
    print(f"Average upload per frame (excluding f0): {stats['avg_bytes_per_frame']/1024:.1f} KB ({stats['avg_bytes_per_frame']:.0f} bytes)")
    print(f"Min upload per frame: {stats['min_bytes_in_frame']/1024:.1f} KB")
    print(f"Max upload per frame: {stats['max_bytes_in_frame']/1024:.1f} KB")
    print(f"Average dirty rects per frame: {stats['avg_rects_per_frame']:.2f}")
    print(f"Speed: {stats['fps_simulated']:.1f} FPS ({elapsed:.2f} s for 1000 frames)")
    print("=" * 60)

    out_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\_DEV\_SPORTCAMHUD_ETAP_5G_RESULTS_20261012\dirty_region_1000_frames_report.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print(f"Results saved to {out_file}")

if __name__ == "__main__":
    run_1000_frames_dirty_region_test()
